"""Web-grounded route advisories — the honest 'research the path on the web'.

Uses Gemini with Google Search grounding to find RECENT reports of road works, digging,
closures, waterlogging, accidents or unsafe conditions on/near a route, then anchors each to
a real coordinate by geocoding the mentioned locality (never by letting the model guess
lat/lng) and snapping it to the route. Results are clearly area-level, source-cited, and
marked unverified — they are NOT folded into the safety score.
"""

from __future__ import annotations

from safejourney_shared.geo import decode_polyline, haversine_m

from ..config import get_settings

# Advisory type -> a conservative severity for an *unverified web report*.
_TYPE_SEV = {
    "roadwork": "moderate",
    "pothole": "moderate",
    "waterlogging": "moderate",
    "flood": "high",
    "accident": "high",
    "unsafe_area": "moderate",
    "other": "low",
}

_SYSTEM = (
    "You research current, real road conditions in India from live web results. You only report "
    "what search results actually support; you never invent incidents or coordinates."
)

_MAX = 5
_MAX_SNAP_M = 6000.0  # drop advisories whose geocoded locality is far from the route
_RECENCY_DAYS = 35    # only surface conditions reported within roughly the last month


def _is_stale(date_str: str, today, days: int = _RECENCY_DAYS) -> bool:
    """True if a model-provided report date is clearly older than the recency window.

    Lenient: only rejects a date we can actually parse and that is definitively too old, so a
    missing/odd date never drops a real advisory (the prompt is the primary recency guard).
    """
    import datetime as _dt

    s = (date_str or "").strip()[:10]
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y/%m/%d", "%Y/%m"):
        try:
            d = _dt.datetime.strptime(s, fmt).date()
            return d < today - _dt.timedelta(days=days)
        except ValueError:
            continue
    return False  # unparseable/blank — keep it, trust the prompt


def route_web_advisories(origin_label: str, dest_label: str, encoded_polyline: str) -> list[dict]:
    """Back-compat wrapper: returns just the advisories list."""
    return route_web_advisories_debug(origin_label, dest_label, encoded_polyline)["advisories"]


def route_web_advisories_debug(
    origin_label: str, dest_label: str, encoded_polyline: str
) -> dict:
    """Same as route_web_advisories but also returns a `diag` dict explaining how many items
    the model returned and where each was dropped (unresolved geocode / too far from route).
    Lets us see which link in the chain went empty instead of guessing."""
    s = get_settings()
    pts = decode_polyline(encoded_polyline) if encoded_polyline else []
    diag: dict = {
        "gemini_available": s.gemini_available,
        "model": s.gemini_model,
        "route_points": len(pts),
        "raw_len": 0,
        "raw_preview": "",
        "parsed_count": 0,
        "kept": 0,
        "dropped_no_geocode": 0,
        "dropped_too_far": 0,
        "dropped_stale": 0,
        "error": None,
    }
    if not s.gemini_available or not pts:
        if not s.gemini_available:
            diag["error"] = "gemini_not_configured"
        elif not pts:
            diag["error"] = "empty_polyline"
        return {"advisories": [], "diag": diag}

    from ..agents.llm import generate_with_search, parse_json_array

    import datetime as _dt

    today = _dt.date.today()
    cutoff = today - _dt.timedelta(days=_RECENCY_DAYS)
    prompt = (
        f"Today's date is {today.isoformat()}. Research CURRENT, real road conditions on or near "
        f"the route from '{origin_label}' to '{dest_label}' in India using live web search. "
        f"Report ONLY conditions that are active right now and were reported, updated or confirmed "
        f"within the last {_RECENCY_DAYS} days (on or after {cutoff.isoformat()}). Do NOT include "
        f"older incidents, road works that have since finished, or reports from earlier months or "
        f"previous years — if the most recent evidence you can find for an item is older than that, "
        f"leave it out. Prefer the most recently reported items and search with recency in mind "
        f"(e.g. include the current month and year in your queries).\n\n"
        f"Look for: road works / digging / sewer or utility line laying, torn-up or broken roads, "
        f"potholes, road closures or diversions, waterlogging or flooding, poor drainage, major "
        f"accidents, or stretches locally considered unsafe. Consider news, civic/municipal "
        f"notices, local forums, resident complaints and map reviews.\n\n"
        "Return ONLY a JSON array (max 5). Each item:\n"
        '{"type": one of ["roadwork","pothole","waterlogging","flood","accident","unsafe_area","other"], '
        '"locality": "<specific road/landmark/area on the route>", '
        '"summary": "<one factual sentence: what and where>", '
        '"date": "<when this was reported/confirmed, YYYY-MM-DD or YYYY-MM; the most recent date you can confirm>", '
        '"source": "<where you saw it: publication, forum, municipal notice, or map reviews>"}\n'
        f"Only include items your search results actually support AND that are from the last "
        f"{_RECENCY_DAYS} days. If nothing credible and recent, return []."
    )
    try:
        text = generate_with_search(prompt, system=_SYSTEM)
    except Exception as e:  # generate_with_search already guards, but be defensive
        diag["error"] = f"search_failed: {e}"
        return {"advisories": [], "diag": diag}

    if text is None:
        diag["error"] = "search_returned_none"
        return {"advisories": [], "diag": diag}

    diag["raw_len"] = len(text)
    diag["raw_preview"] = text[:500]
    items = parse_json_array(text or "")
    diag["parsed_count"] = len(items)
    if not items:
        if text.strip() and text.strip() not in ("[]", "[ ]"):
            diag["error"] = "parse_empty"  # model replied but not a usable JSON array
        return {"advisories": [], "diag": diag}

    from .geocode import geocode_search, geocode_resolve

    center = pts[len(pts) // 2]
    # Region context to disambiguate hyperlocal names for a weak (keyless) geocoder — e.g.
    # "Kamal Vihar" alone is ambiguous, "Kamal Vihar, Burari" / "..., India" is not.
    region_hints = _region_hints(origin_label, dest_label)
    out: list[dict] = []
    for it in items[:_MAX]:
        if not isinstance(it, dict):
            continue
        loc = (it.get("locality") or "").strip()
        summary = (it.get("summary") or "").strip()
        if not loc or not summary:
            continue
        report_date = (it.get("date") or "").strip()
        # Safety net beyond the prompt: drop items the model dated clearly outside the window.
        if _is_stale(report_date, today):
            diag["dropped_stale"] += 1
            continue
        # Resolve to the candidate nearest the route (handles same-named places elsewhere).
        snapped = _resolve(loc, pts, center, region_hints, geocode_search, geocode_resolve)
        if not snapped:
            diag["dropped_no_geocode"] += 1
            continue
        if snapped[2] > _MAX_SNAP_M:
            diag["dropped_too_far"] += 1
            continue
        htype = it.get("type") if it.get("type") in _TYPE_SEV else "other"
        out.append({
            "type": htype,
            "severity": _TYPE_SEV[htype],
            "lat": snapped[0],
            "lng": snapped[1],
            "locality": loc,
            "summary": summary,
            "date": report_date,
            "source": it.get("source") or "web",
        })
    diag["kept"] = len(out)
    return {"advisories": out, "diag": diag}


def _region_hints(origin_label: str, dest_label: str) -> list[str]:
    """Context suffixes to disambiguate a bare locality for a weak geocoder.

    Includes the origin/dest labels, their trailing area token (the bit after the last comma,
    e.g. 'Burari'), and 'India' as a country anchor. De-duplicated, order preserved.
    """
    hints: list[str] = []
    for label in (origin_label or "", dest_label or ""):
        label = label.strip()
        if label:
            hints.append(label)
            tail = label.split(",")[-1].strip()
            if tail and tail != label:
                hints.append(tail)
    hints.append("India")
    seen: set[str] = set()
    out: list[str] = []
    for h in hints:
        k = h.lower()
        if h and k not in seen:
            seen.add(k)
            out.append(h)
    return out


def _resolve(locality, pts, center, region_hints, geocode_search, geocode_resolve):
    """Resolve a locality to the (lat, lng, dist_to_route) candidate CLOSEST to the route.

    Tries the bare locality first, then with each region hint appended, and across all the
    geocoder's returned candidates keeps the one nearest the path — so a same-named place in
    another city is naturally rejected instead of taken just because it ranked first. Returns
    None if nothing geocodes. Uses a real geocoder, never the LLM, for coordinates.
    """
    queries = [locality] + [f"{locality}, {h}" for h in region_hints]
    best = None  # (lat, lng, dist)
    for q in queries:
        try:
            results = geocode_search(q, center[0], center[1])
        except Exception:
            continue
        for r in results or []:
            coord = _coord_of(r, geocode_resolve)
            if not coord:
                continue
            snapped = min(pts, key=lambda p: haversine_m(p[0], p[1], coord[0], coord[1]))
            dist = haversine_m(snapped[0], snapped[1], coord[0], coord[1])
            if best is None or dist < best[2]:
                best = (snapped[0], snapped[1], dist)
        # Good enough on-route match found; no need to try broader hints.
        if best is not None and best[2] <= _MAX_SNAP_M:
            break
    return best


def _coord_of(r: dict, geocode_resolve):
    """Extract (lat, lng) from a geocode result, resolving a Google place_id if needed."""
    if r.get("lat") is not None:
        return (r["lat"], r["lng"])
    try:
        d = geocode_resolve(r.get("place_id", ""))
        if d:
            return (d["lat"], d["lng"])
    except Exception:
        pass
    return None
