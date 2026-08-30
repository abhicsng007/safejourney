"""Routing — Google Directions API with alternatives, plus an offline fallback that
synthesizes distinct candidate routes so the pre-detection flow works without a Maps key.
"""

from __future__ import annotations

import html
import math
import re

from safejourney_shared.geo import bearing_deg, encode_polyline, haversine_m

from ._http import get_json
from ..config import get_settings

_DIRECTIONS = "https://maps.googleapis.com/maps/api/directions/json"

_TAG_RE = re.compile(r"<[^>]+>")

# Words in a Google walking instruction that mean the step uses a specific pedestrian
# feature — used to tag the step (and drop an icon beside it) in the written directions.
_STEP_FEATURE = [
    ("pedestrian overpass", ("footbridge", "🌉")),
    ("foot over", ("footbridge", "🌉")),
    ("footbridge", ("footbridge", "🌉")),
    ("pedestrian bridge", ("footbridge", "🌉")),
    ("overpass", ("footbridge", "🌉")),
    ("underpass", ("underpass", "🚇")),
    ("subway", ("underpass", "🚇")),
    ("stairs", ("stairs", "🪜")),
    ("crosswalk", ("crossing", "🦓")),
    ("cross ", ("crossing", "🦓")),
]


def _strip_html(s: str) -> str:
    """Google step instructions arrive as HTML (road names in <b>). Flatten to readable text."""
    s = s.replace("<div", " <div")
    return html.unescape(_TAG_RE.sub("", s)).strip()


def _clean_steps(leg: dict) -> list[dict]:
    """Turn a Directions leg's steps into compact turn-by-turn directions for the UI."""
    steps: list[dict] = []
    for st in leg.get("steps", []):
        instr = _strip_html(st.get("html_instructions", ""))
        if not instr:
            continue
        low = instr.lower()
        feature, icon = None, None
        for kw, (t, ic) in _STEP_FEATURE:
            if kw in low:
                feature, icon = t, ic
                break
        sl = st.get("start_location", {})
        el = st.get("end_location", {})
        steps.append({
            "instruction": instr,
            "distance_m": st.get("distance", {}).get("value", 0),
            "duration_s": st.get("duration", {}).get("value", 0),
            "start": {"lat": sl.get("lat"), "lng": sl.get("lng")},
            "end": {"lat": el.get("lat"), "lng": el.get("lng")},
            "feature": feature,
            "icon": icon,
        })
    return steps


_COMPASS = (
    "north", "north-east", "east", "south-east",
    "south", "south-west", "west", "north-west",
)


def _compass(bearing: float) -> str:
    return _COMPASS[int((bearing + 22.5) // 45) % 8]


def _signed_heading_delta(prev: float, new: float) -> float:
    """Signed turn in degrees, (-180, 180]. Positive is right."""
    return (new - prev + 540.0) % 360.0 - 180.0


def _turn_instruction(delta: float) -> str | None:
    mag = abs(delta)
    if mag < 18:
        return None
    side = "right" if delta > 0 else "left"
    if mag < 45:
        return f"Bear {side}"
    if mag < 110:
        return f"Turn {side}"
    if mag < 160:
        return f"Make a sharp {side} turn"
    return "Make a U-turn"


def _seg_len(pts: list[tuple[float, float]], i0: int, i1: int) -> float:
    total = 0.0
    for i in range(i0, i1):
        a, b = pts[i], pts[i + 1]
        total += haversine_m(a[0], a[1], b[0], b[1])
    return total


def _make_step(
    instruction: str,
    start: tuple[float, float],
    end: tuple[float, float],
    distance_m: float,
) -> dict:
    return {
        "instruction": instruction,
        "distance_m": round(distance_m),
        "duration_s": round(distance_m / 8.3) if distance_m else 0,
        "start": {"lat": start[0], "lng": start[1]},
        "end": {"lat": end[0], "lng": end[1]},
        "feature": None,
        "icon": None,
    }


def _steps_from_points(
    pts: list[tuple[float, float]],
    continue_every_m: float = 2000.0,
) -> list[dict]:
    """Synthesize Google-style turn-by-turn steps from a polyline.

    Used when Directions is unavailable (no key / throttled) so the voice
    navigator still has maneuvers to announce instead of going silent.
    Step 0 is the departure heading. Later steps start at vertices where
    heading changes enough to be a real turn, and on long quiet stretches
    a 'continue' cue is dropped every ~2 km so a 15 km fallback isn't mute.
    """
    if len(pts) < 2:
        return []
    step_b = bearing_deg(pts[0][0], pts[0][1], pts[1][0], pts[1][1])
    pending = f"Head {_compass(step_b)} toward your destination"
    last_i = 0
    travelled = 0.0
    steps: list[dict] = []
    for i in range(1, len(pts) - 1):
        nxt = pts[i + 1]
        b = bearing_deg(pts[i][0], pts[i][1], nxt[0], nxt[1])
        phrase = _turn_instruction(_signed_heading_delta(step_b, b))
        travelled += haversine_m(pts[i - 1][0], pts[i - 1][1], pts[i][0], pts[i][1])
        incoming = _seg_len(pts, last_i, i)
        is_turn = bool(phrase) and incoming >= 40
        is_cont = travelled >= continue_every_m and incoming >= continue_every_m * 0.75
        if not (is_turn or is_cont):
            continue
        steps.append(_make_step(pending, pts[last_i], pts[i], incoming))
        pending = phrase if is_turn else "Continue toward your destination"
        last_i = i
        travelled = 0.0
        step_b = b
    steps.append(_make_step(pending, pts[last_i], pts[-1], _seg_len(pts, last_i, len(pts) - 1)))
    return steps

_MODE_MAP = {
    "walk": "walking",
    "two_wheeler": "driving",   # Directions has no 2-wheeler mode; driving is the closest.
    "car": "driving",
    "transit": "transit",
}


def _fallback_routes(origin: tuple[float, float], dest: tuple[float, float]) -> list[dict]:
    """Two or three plausible distinct routes: a direct line and bowed variants."""
    (olat, olng), (dlat, dlng) = origin, dest
    straight_m = haversine_m(olat, olng, dlat, dlng)
    routes = []

    def build(bow: float, label: str, factor: float) -> dict:
        # Perpendicular offset applied at the midpoint to bow the route.
        mlat, mlng = (olat + dlat) / 2, (olng + dlng) / 2
        dx, dy = dlat - olat, dlng - olng
        norm = math.hypot(dx, dy) or 1e-9
        # perpendicular unit vector
        px, py = -dy / norm, dx / norm
        clat, clng = mlat + px * bow, mlng + py * bow
        pts = [(olat, olng)]
        # quadratic bezier through control point
        for i in range(1, 10):
            t = i / 10
            lat = (1 - t) ** 2 * olat + 2 * (1 - t) * t * clat + t ** 2 * dlat
            lng = (1 - t) ** 2 * olng + 2 * (1 - t) * t * clng + t ** 2 * dlng
            pts.append((lat, lng))
        pts.append((dlat, dlng))
        dist = straight_m * factor
        return {
            "route_id": label,
            "encoded_polyline": encode_polyline(pts),
            "points": pts,
            "distance_m": round(dist),
            "duration_s": round(dist / 8.3),  # ~30 km/h
            "summary": label.replace("_", " ").title(),
            "source": "fallback",
            "steps": _steps_from_points(pts),
        }

    routes.append(build(0.0, "direct", 1.0))
    routes.append(build(0.012, "bypass_a", 1.18))
    routes.append(build(-0.010, "bypass_b", 1.12))
    return routes


def plan_routes(
    origin: tuple[float, float],
    dest: tuple[float, float],
    mode: str = "two_wheeler",
) -> list[dict]:
    """Return candidate routes as dicts with an encoded_polyline + decoded points.

    Each dict: {route_id, encoded_polyline, points, distance_m, duration_s, summary, source}.
    """
    s = get_settings()
    if not s.maps_api_key:
        return _fallback_routes(origin, dest)

    data = get_json(
        _DIRECTIONS,
        params={
            "origin": f"{origin[0]},{origin[1]}",
            "destination": f"{dest[0]},{dest[1]}",
            "alternatives": "true",
            "mode": _MODE_MAP.get(mode, "driving"),
            "key": s.maps_api_key,
        },
        timeout=8.0,
    )
    if not data or data.get("status") != "OK":
        return _fallback_routes(origin, dest)

    from safejourney_shared.geo import decode_polyline

    out: list[dict] = []
    for i, r in enumerate(data.get("routes", [])):
        enc = r.get("overview_polyline", {}).get("points", "")
        if not enc:
            continue
        leg = (r.get("legs") or [{}])[0]
        out.append({
            "route_id": f"g{i}",
            "encoded_polyline": enc,
            "points": decode_polyline(enc),
            "distance_m": leg.get("distance", {}).get("value", 0),
            "duration_s": leg.get("duration", {}).get("value", 0),
            "summary": r.get("summary", f"Route {i + 1}"),
            "source": "google-directions",
            "steps": _clean_steps(leg),
        })
    return out or _fallback_routes(origin, dest)
