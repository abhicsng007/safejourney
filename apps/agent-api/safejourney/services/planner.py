"""Trip planning + route pre-detection.

Given an origin/destination/mode, produce candidate routes, scan each corridor for hazards,
score them, and return them safety-ranked with human-readable summaries and precautions.
"""

from __future__ import annotations

from safejourney_shared.hazards import Hazard, HazardType, Severity, SEVERITY_SCORE
from safejourney_shared.scoring import ScoredRoute, rank_routes, route_is_blocking, safety_score, classify_score

from ..tools.route import plan_routes
from ..tools.hazard_scan import scan_corridor
from ..tools.places import nearest_station
from .precautions import precautions_for


def _summary(hazards: list[Hazard], rating: str) -> str:
    if not hazards:
        return "No active hazards detected on this route."
    top = sorted(hazards, key=lambda h: SEVERITY_SCORE[h.severity], reverse=True)[:3]
    parts = [f"{h.type.value.replace('_', ' ')} ({h.severity.value})" for h in top]
    lead = {
        "safe": "Looks clear",
        "caution": "Minor hazards",
        "risky": "Notable hazards",
        "dangerous": "Serious hazards",
    }.get(rating, "Hazards")
    return f"{lead}: " + ", ".join(parts) + ("." if len(hazards) <= 3 else f", +{len(hazards) - 3} more.")


def score_route(
    route: dict,
    mode: str = "two_wheeler",
    risk_tolerance: float = 1.0,
) -> ScoredRoute:
    hazards = scan_corridor(route["points"], mode=mode)
    score = safety_score(hazards, mode=mode, risk_tolerance=risk_tolerance)
    rating = classify_score(score)
    return ScoredRoute(
        route_id=route["route_id"],
        score=score,
        hazards=hazards,
        blocking=route_is_blocking(hazards),
        summary=_summary(hazards, rating),
        encoded_polyline=route["encoded_polyline"],
        distance_m=route.get("distance_m", 0),
        duration_s=route.get("duration_s", 0),
        meta={
            "source": route.get("source", ""),
            "points": route["points"],
            "steps": route.get("steps", []),
        },
    )


def _emit(on_event, event: dict) -> None:
    if not on_event:
        return
    try:
        on_event(event)
    except Exception:
        pass


def plan_and_score(
    origin: tuple[float, float],
    dest: tuple[float, float],
    mode: str = "two_wheeler",
    risk_tolerance: float = 1.0,
    on_event=None,
) -> dict:
    """Return safety-ranked candidate routes + a recommendation.

    `on_event`, when given, is called with structured trace dicts as each specialist
    agent hands off — the same schema the UI reasoning timeline already renders.
    """
    from ..sources import describe

    _emit(on_event, {"kind": "delegate", "from": "guardian_core", "to": "route_guardian"})
    _emit(on_event, {
        "kind": "tool_call", "name": "plan_safe_routes", "agent": "route_guardian",
        "args": {"mode": mode},
    })
    candidates = plan_routes(origin, dest, mode)
    src_name = (candidates[0].get("source") if candidates else "") or "google-directions"
    _emit(on_event, {
        "kind": "tool_result", "name": "plan_safe_routes", "agent": "route_guardian",
        "summary": (
            f"{len(candidates)} candidate route(s) from Directions — now scoring each on safety, "
            "not just speed."
        ),
    })
    cited = describe(src_name, origin=origin, dest=dest)
    if cited:
        _emit(on_event, {"kind": "cite", "source": cited})

    _emit(on_event, {"kind": "delegate", "from": "route_guardian", "to": "hazard_sentinel"})
    _emit(on_event, {
        "kind": "tool_call", "name": "scan_route_hazards", "agent": "hazard_sentinel",
        "args": {"corridors": len(candidates), "feeds": "weather · OSM · disasters · blackspots"},
    })

    # Score candidates concurrently — each scan_corridor does its own network fan-out, so
    # scoring 3 routes serially tripled the plan latency. One worker per candidate.
    if len(candidates) > 1:
        from concurrent.futures import ThreadPoolExecutor

        with ThreadPoolExecutor(max_workers=len(candidates)) as pool:
            scored = list(pool.map(lambda c: score_route(c, mode, risk_tolerance), candidates))
    else:
        scored = [score_route(c, mode, risk_tolerance) for c in candidates]
    ranked = rank_routes(scored)

    recommended = ranked[0] if ranked else None
    all_blocking = bool(ranked) and all(r.blocking for r in ranked)

    # Cite every distinct feed that actually returned a hazard (or conditions).
    seen_src: set[str] = set()
    n_hz = 0
    kinds: set[str] = set()
    for r in ranked:
        n_hz += len(r.hazards)
        for h in r.hazards:
            kinds.add(h.type.value.replace("_", " "))
            sid = (h.source or "").split(":")[0]
            if sid and sid not in seen_src:
                seen_src.add(sid)
                c = describe(h.source, origin=origin, dest=dest)
                if c:
                    _emit(on_event, {"kind": "cite", "source": c})

    kinds_s = ", ".join(sorted(kinds)[:5]) or "none"
    _emit(on_event, {
        "kind": "tool_result", "name": "scan_route_hazards", "agent": "hazard_sentinel",
        "summary": (
            f"{n_hz} hazard(s) across {len(ranked)} corridor(s)"
            + (f": {kinds_s}." if n_hz else " — corridors look clear.")
        ),
    })

    # Pre-trip environmental briefing (weather / visibility / air quality). Fold the fog +
    # unhealthy-air hazards it finds into the recommended route so they score, show on the map,
    # and warn during the drive like any other hazard — and keep the summary for the UI card.
    conditions = _unavailable_conditions()
    if recommended is not None:
        _emit(on_event, {
            "kind": "tool_call", "name": "check_trip_now", "agent": "prep",
            "args": {"layer": "weather · visibility · AQI"},
        })
        conditions = _apply_conditions(recommended, mode, risk_tolerance)
        cond_src = conditions.get("source")
        if cond_src and cond_src != "unavailable":
            c = describe(cond_src, origin=origin, dest=dest)
            if c:
                _emit(on_event, {"kind": "cite", "source": c})
        w = (conditions.get("weather") or {}).get("label") or "conditions"
        _emit(on_event, {
            "kind": "tool_result", "name": "check_trip_now", "agent": "prep",
            "summary": f"Briefing: {w}.",
        })

    _emit(on_event, {"kind": "delegate", "from": "hazard_sentinel", "to": "route_guardian"})
    rating = classify_score(recommended.score) if recommended is not None else ""
    _emit(on_event, {
        "kind": "decision",
        "agent": "route_guardian",
        "action": "clear" if rating == "safe" else "advisory",
        "title": (
            f"Safest of {len(ranked)}: {rating}" if ranked else "No route"
        ),
        "reason": _plan_advice(ranked, all_blocking),
        "decided_by": "route_guardian",
    })

    result = {
        "routes": [r.to_dict() for r in ranked],
        "recommended_route_id": recommended.route_id if recommended else None,
        "all_routes_blocked": all_blocking,
        "advice": _plan_advice(ranked, all_blocking),
        "conditions": conditions,
        "precautions": precautions_for(
            [h.type for h in (recommended.hazards if recommended else [])]
        ),
    }
    return result


def _unavailable_conditions() -> dict:
    return {"weather": None, "visibility": None, "aqi": None, "source": "unavailable"}


def _apply_conditions(route: ScoredRoute, mode: str, risk_tolerance: float) -> dict:
    """Fetch conditions for a scored route, merge the implied hazards in, and re-score it.
    Returns the summary dict for the UI (empty/unavailable when offline)."""
    from safejourney_shared.geo import distance_along_polyline_m
    from ..tools.conditions import route_conditions

    pts = route.meta.get("points") or []
    if not pts:
        return _unavailable_conditions()
    summary, cond_hz = route_conditions(pts)
    if cond_hz:
        existing = {h.key() for h in route.hazards}
        for h in cond_hz:
            if h.key() in existing:
                continue
            h.offset_m = 0.0  # sampled on the route line itself
            if h.distance_along_m is None:
                h.distance_along_m = distance_along_polyline_m(h.lat, h.lng, pts)
            route.hazards.append(h)
        route.score = safety_score(route.hazards, mode=mode, risk_tolerance=risk_tolerance)
        route.blocking = route_is_blocking(route.hazards)
        route.summary = _summary(route.hazards, classify_score(route.score))
    return summary


def first_mile_leg(
    origin: tuple[float, float],
    mode: str,
    risk_tolerance: float = 1.0,
) -> dict | None:
    """The exposed walk from home to the nearest station (transit journeys only).

    Returns a scored walk leg dict (station + hazards) so prep/monitoring can reason about
    the first mile — 'walking to the metro in a storm' — or None when it doesn't apply.
    """
    if mode != "transit":
        return None
    station = nearest_station(origin[0], origin[1])
    if not station:
        return None
    candidates = plan_routes(origin, (station["lat"], station["lng"]), "walk")
    if not candidates:
        return None
    scored = score_route(candidates[0], "walk", risk_tolerance)
    leg = scored.to_dict()
    leg["station"] = station
    leg["mode"] = "walk"
    return leg


def plan_journey(
    origin: tuple[float, float],
    dest: tuple[float, float],
    mode: str = "two_wheeler",
    risk_tolerance: float = 1.0,
    on_event=None,
) -> dict:
    """plan_and_score + the home→station first leg for transit journeys.

    Kept separate from plan_and_score so the monitor's reroute path stays lean (no station
    lookups on every tick) — only the planning entry points compose the full journey.
    """
    plan = plan_and_score(origin, dest, mode, risk_tolerance, on_event=on_event)
    leg = first_mile_leg(origin, mode, risk_tolerance)
    if leg:
        plan["first_leg"] = leg
    return plan


def _plan_advice(ranked: list[ScoredRoute], all_blocking: bool) -> str:
    if not ranked:
        return "Could not compute a route. Check the locations and try again."
    best = ranked[0]
    if all_blocking:
        return (
            "Every route currently has a critical hazard. Consider delaying, switching mode, "
            "or waiting at a safe place — see precautions. If you must travel, proceed with "
            "extreme caution and keep live location sharing on."
        )
    rating = classify_score(best.score)
    if rating == "safe":
        return f"Recommended route looks clear. {len(ranked)} option(s) checked."
    return (
        f"Recommended the safest of {len(ranked)} route(s) ({rating}). "
        "Follow the precautions below, and I'll keep watching the road as you go."
    )
