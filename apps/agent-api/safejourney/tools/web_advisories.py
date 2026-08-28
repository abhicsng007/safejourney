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


def route_web_advisories(origin_label: str, dest_label: str, encoded_polyline: str) -> list[dict]:
    s = get_settings()
    pts = decode_polyline(encoded_polyline) if encoded_polyline else []
    if not s.gemini_available or not pts:
        return []

    from ..agents.llm import generate_with_search, parse_json_array

    prompt = (
        f"Find RECENT (last few weeks) reports of road hazards on or near the route from "
        f"'{origin_label}' to '{dest_label}' in India — road works / digging / sewer or utility "
        f"work, road closures or diversions, waterlogging or flooding, major accidents, or unsafe "
        f"stretches. Use live web search.\n\n"
        "Return ONLY a JSON array (max 5). Each item:\n"
        '{"type": one of ["roadwork","pothole","waterlogging","flood","accident","unsafe_area","other"], '
        '"locality": "<specific road/landmark/area on the route>", '
        '"summary": "<one factual sentence: what and where>", '
        '"source": "<publication or website name>"}\n'
        "Only include items supported by search results. If nothing credible, return []."
    )
    text = generate_with_search(prompt, system=_SYSTEM)
    items = parse_json_array(text or "")
    if not items:
        return []

    from .geocode import geocode_search, geocode_resolve

    center = pts[len(pts) // 2]
    out: list[dict] = []
    for it in items[:_MAX]:
        if not isinstance(it, dict):
            continue
        loc = (it.get("locality") or "").strip()
        summary = (it.get("summary") or "").strip()
        if not loc or not summary:
            continue
        coords = _resolve(loc, center, geocode_search, geocode_resolve)
        if not coords:
            continue
        # Snap to the route's closest approach; drop if the locality is far from the path.
        snapped = min(pts, key=lambda p: haversine_m(p[0], p[1], coords[0], coords[1]))
        if haversine_m(snapped[0], snapped[1], coords[0], coords[1]) > _MAX_SNAP_M:
            continue
        htype = it.get("type") if it.get("type") in _TYPE_SEV else "other"
        out.append({
            "type": htype,
            "severity": _TYPE_SEV[htype],
            "lat": snapped[0],
            "lng": snapped[1],
            "locality": loc,
            "summary": summary,
            "source": it.get("source") or "web",
        })
    return out


def _resolve(locality: str, center, geocode_search, geocode_resolve):
    """Geocode a locality to (lat, lng), biased to the route area. Real geocoder, not the LLM."""
    try:
        results = geocode_search(locality, center[0], center[1])
    except Exception:
        return None
    if not results:
        return None
    r = results[0]
    if r.get("lat") is not None:
        return (r["lat"], r["lng"])
    # Google autocomplete result — resolve the place_id to coordinates.
    try:
        d = geocode_resolve(r.get("place_id", ""))
        if d:
            return (d["lat"], d["lng"])
    except Exception:
        pass
    return None
