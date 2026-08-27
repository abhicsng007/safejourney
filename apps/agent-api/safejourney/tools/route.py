"""Routing — Google Directions API with alternatives, plus an offline fallback that
synthesizes distinct candidate routes so the pre-detection flow works without a Maps key.
"""

from __future__ import annotations

import math

from safejourney_shared.geo import encode_polyline, haversine_m

from ._http import get_json
from ..config import get_settings

_DIRECTIONS = "https://maps.googleapis.com/maps/api/directions/json"

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
        })
    return out or _fallback_routes(origin, dest)
