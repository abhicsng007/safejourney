"""Unlit-road hazards from OpenStreetMap (Overpass, keyless), gated to night hours.

A dark stretch only matters after dusk, so we skip the query entirely in daylight. We look
for ways explicitly tagged `lit=no` near the corridor — a high-confidence signal — rather
than guessing from missing tags.
"""

from __future__ import annotations

import time

from safejourney_shared.geo import haversine_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._http import get_json

_OVERPASS = "https://overpass-api.de/api/interpreter"


def _is_night(lng: float, now: float | None = None) -> bool:
    """Rough local-time night check (no tz lib): local hour ≈ UTC hour + lng/15."""
    t = time.gmtime(now if now is not None else time.time())
    local_hour = (t.tm_hour + t.tm_min / 60.0 + lng / 15.0) % 24
    return local_hour >= 18.5 or local_hour < 6.0


def _bbox(points, pad_deg: float = 0.01):
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats) - pad_deg, min(lngs) - pad_deg, max(lats) + pad_deg, max(lngs) + pad_deg)


def unlit_hazards(points: list[tuple[float, float]], max_items: int = 8, now: float | None = None) -> list[Hazard]:
    if not points:
        return []
    # Gate on the middle of the route — one night check for the corridor.
    mid = points[len(points) // 2]
    if not _is_night(mid[1], now):
        return []
    s, w, n, e = _bbox(points)
    if (n - s) * (e - w) > 0.5:  # keep the Overpass query cheap
        return []
    query = f"""
    [out:json][timeout:8];
    (
      way["highway"]["lit"="no"]({s},{w},{n},{e});
    );
    out center {max_items};
    """
    data = get_json(_OVERPASS, params={"data": query}, timeout=9.0)
    elements = (data or {}).get("elements", []) if isinstance(data, dict) else []
    out: list[Hazard] = []
    for el in elements[:max_items]:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lng is None:
            continue
        if min(haversine_m(lat, lng, p[0], p[1]) for p in points) > 300:
            continue
        name = el.get("tags", {}).get("name", "Unlit road")
        out.append(Hazard(HazardType.UNLIT, Severity.LOW, lat, lng, "overpass",
                          f"{name} — no street lighting at night; use lights and stay visible."))
    return out
