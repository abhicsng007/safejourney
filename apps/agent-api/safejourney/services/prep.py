"""Pre-trip readiness — the 'before you leave home' step.

Given a computed journey plan + travel mode, decide go / caution / wait and produce a
readiness checklist grounded in the route's actual hazards and forecast (the 'you forgot
your rain cover' moment the app opens with). Deterministic by design; Gemini optionally adds
a one-line, situation-aware headline. Never fails the caller.
"""

from __future__ import annotations

from typing import Optional

from safejourney_shared.hazards import HazardType

from ..config import get_settings

# Wet/exposure hazard groupings reused for checklist reasoning.
_WET = {"flood", "waterlogging", "storm", "lightning"}
_EXPOSED_MODES = {"walk", "two_wheeler"}

# Base kit every journey needs, per mode.
_BASE_KIT: dict[str, list[tuple[str, str]]] = {
    "walk": [
        ("Phone charged + power bank", "You'll rely on live location and alerts the whole way."),
        ("ID and some cash", "In case you need a cab or help en route."),
        ("Water", "Stay hydrated, especially on longer walks."),
    ],
    "two_wheeler": [
        ("Helmet (fastened)", "Non-negotiable — most two-wheeler deaths are head injuries."),
        ("Licence + RC + insurance", "Carry your riding documents."),
        ("Phone mount + power bank", "So you can follow alerts without holding the phone."),
    ],
    "car": [
        ("Licence + RC + insurance", "Carry your driving documents."),
        ("Check fuel / charge", "Avoid stopping in an unsafe spot to refuel."),
        ("Phone charger", "Keep navigation and alerts alive."),
    ],
    "transit": [
        ("Transit card / cash", "For a smooth boarding and any last-mile cab."),
        ("Phone charged + power bank", "You'll get alerts on the platform and in transit."),
        ("ID", "Useful for any checks or help en route."),
    ],
}


def _checklist(mode: str, htypes: set[str], conditions: Optional[dict] = None) -> list[dict]:
    items = list(_BASE_KIT.get(mode, _BASE_KIT["two_wheeler"]))

    wet = htypes & _WET
    if wet:
        if mode == "two_wheeler":
            items.append(("Rain cover / poncho + anti-fog visor", "Rain and reduced visibility are on your route."))
        elif mode == "walk":
            items.append(("Umbrella / rain jacket + grippy shoes", "Wet, slick surfaces ahead."))
        else:
            items.append(("Wipers/defog ready, waterproof bag", "Rain is expected along the way."))

    if "heat" in htypes:
        items.append(("Extra water, cap, sunscreen", "Extreme-heat window on your route — heatstroke risk."))
    if "lightning" in htypes:
        items.append(("Plan indoor stops", "Active lightning — know where you can duck inside."))
    if "unlit" in htypes:
        items.append(("Lights / reflective layer", "Dark, poorly-lit stretch on the way."))
    if htypes & {"glof", "landslide"}:
        items.append(("Tell someone your route + ETA", "Upstream flood / slope risk — someone should know where you are."))
    if htypes & {"pothole", "roadwork", "accident"}:
        items.append(("Allow extra time", "Broken road / works / an incident ahead — don't rush."))

    # Fog / low visibility (hazard-level: visibility under ~2.5 km on the route).
    if "fog" in htypes:
        if mode in _EXPOSED_MODES:
            items.append(("Fog light on + anti-fog visor, hi-vis layer", "Low visibility ahead — be seen and slow right down."))
        else:
            items.append(("Fog lights + demist ready", "Low visibility ahead — keep lights on, extra following distance."))
    # Unhealthy air (hazard-level: US AQI >= 151 on the route).
    if "air_quality" in htypes:
        items.append(("N95 mask" + (" (windows up, recirculate)" if mode == "car" else ""),
                      "Unhealthy air on your route — protect your lungs, especially outdoors."))

    items += _condition_items(mode, conditions, htypes)
    return [{"item": t, "reason": r, "done": False} for t, r in items]


def _condition_items(mode: str, conditions: Optional[dict], htypes: set[str]) -> list[tuple[str, str]]:
    """Reminders from the live conditions summary for readings that matter but haven't crossed
    the hazard threshold (moderate haze, sensitive-group AQI, gusty-but-not-storm wind).
    Skips anything already covered by a hazard-level item above."""
    out: list[tuple[str, str]] = []
    if not conditions:
        return out
    vis = conditions.get("visibility")
    aqi = conditions.get("aqi")
    weather = conditions.get("weather")

    if vis and vis.get("level") == "moderate" and "fog" not in htypes:
        out.append(("Headlight on, extra following distance",
                    f"Visibility ~{vis.get('km')} km — hazy; keep lights on and speed down."))
    if aqi and "air_quality" not in htypes and (aqi.get("us_aqi") or 0) >= 101:
        # 101–150: unhealthy for sensitive groups (below the mask-everyone threshold).
        out.append(("Mask if sensitive (N95)",
                    f"AQI {aqi.get('us_aqi')} — unhealthy for sensitive groups; mask up if you have asthma/heart issues."))
    if (weather and weather.get("gusty") and "storm" not in htypes
            and mode in _EXPOSED_MODES):
        out.append(("Brace for crosswinds",
                    f"Gusts ~{weather.get('wind_kmh')} km/h — grip firmly and watch for loose debris."))
    return out


def _verdict(rating: str, all_blocked: bool, htypes: set[str], mode: str) -> tuple[str, str]:
    """Return (verdict, headline). verdict ∈ {go, caution, wait}."""
    exposed = mode in _EXPOSED_MODES
    if all_blocked or rating == "dangerous":
        return ("wait", "Hold off for now — every route ahead has a serious hazard. Better to wait than risk it.")
    active_bolt_flood = bool(htypes & {"lightning", "flood"})
    if rating == "risky" or (exposed and active_bolt_flood):
        return ("caution", "You can go, but conditions are rough — gear up, leave a little early, and I'll watch the road.")
    if rating == "caution":
        return ("caution", "Mostly fine with a few things to watch. Grab the kit below and head out.")
    return ("go", "Looks clear to travel. Quick kit check and you're good to go.")


def _apply_conditions_verdict(
    verdict: str, headline: str, conditions: Optional[dict], htypes: set[str], mode: str
) -> tuple[str, str]:
    """Nudge a 'go' up to 'caution' when the environment warrants it but no hazard fired —
    sensitive-group air (AQI 101–150) or hazy visibility. Never downgrades a 'wait'/'caution'."""
    if verdict != "go" or not conditions:
        return verdict, headline
    aqi = conditions.get("aqi") or {}
    vis = conditions.get("visibility") or {}
    if (aqi.get("us_aqi") or 0) >= 101:
        return ("caution", f"Air quality is poor (AQI {aqi.get('us_aqi')}) — you can go, but mask up if you're sensitive.")
    if vis.get("level") == "moderate" and mode in _EXPOSED_MODES:
        return ("caution", f"Visibility is down to ~{vis.get('km')} km — go with lights on and take it slow.")
    return verdict, headline


def readiness(plan: dict, mode: str) -> dict:
    """Build the pre-trip readiness verdict + checklist from an already-computed plan.

    Reuses the plan's recommended route hazards (and the first-mile walk leg if present) so
    there are no extra external calls.
    """
    routes = plan.get("routes") or []
    rec = next(
        (r for r in routes if r.get("route_id") == plan.get("recommended_route_id")),
        routes[0] if routes else None,
    )
    htypes: set[str] = set()
    if rec:
        htypes |= {h.get("type") for h in (rec.get("hazards") or [])}
    # Fold in the walk-to-station leg's hazards — the exposed first mile matters most.
    first_leg = plan.get("first_leg")
    if first_leg:
        htypes |= {h.get("type") for h in (first_leg.get("hazards") or [])}
    htypes.discard(None)

    conditions = plan.get("conditions")
    rating = rec.get("rating") if rec else "safe"
    verdict, headline = _verdict(rating, bool(plan.get("all_routes_blocked")), htypes, mode)
    verdict, headline = _apply_conditions_verdict(verdict, headline, conditions, htypes, mode)
    checklist = _checklist(mode, htypes, conditions)

    result = {
        "verdict": verdict,
        "headline": headline,
        "checklist": checklist,
        "hazard_types": sorted(htypes),
    }
    narrated = _narrate(mode, verdict, htypes, headline)
    if narrated:
        result["headline"] = narrated
    return result


def _narrate(mode: str, verdict: str, htypes: set[str], fallback: str) -> Optional[str]:
    s = get_settings()
    if not s.gemini_available:
        return None
    try:
        from ..agents.llm import generate

        hz = ", ".join(sorted(htypes)) or "no active hazards"
        prompt = (
            f"You are SafeJourney's Prep companion. Mode: {mode}. Decision: {verdict}. "
            f"Hazards on the route: {hz}. In ONE warm, specific sentence (<=160 chars, no emojis), "
            "tell the traveller whether to go now and the single most important thing to take or do."
        )
        return generate(prompt, max_tokens=90)
    except Exception as e:  # pragma: no cover
        print(f"[prep] narrate skipped ({e})")
        return None
