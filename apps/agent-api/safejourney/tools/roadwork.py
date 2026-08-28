"""Construction / road-work hazards from OpenStreetMap via the Overpass API (keyless).

Looks for active construction, roadworks and related barriers near the corridor. Offline or
on failure it returns nothing (roadworks then come from the incident/crowd path instead).
"""

from __future__ import annotations

from safejourney_shared.geo import haversine_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._overpass import cached_overpass_elements


def _bbox(points: list[tuple[float, float]], pad_deg: float = 0.01) -> tuple[float, float, float, float]:
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats) - pad_deg, min(lngs) - pad_deg, max(lats) + pad_deg, max(lngs) + pad_deg)


def roadwork_hazards(points: list[tuple[float, float]], max_items: int = 12) -> list[Hazard]:
    if not points:
        return []
    s, w, n, e = _bbox(points)
    # Constrain the query area so it stays cheap.
    if (n - s) * (e - w) > 0.5:  # ~ too large; skip to avoid heavy Overpass load
        return []
    query = f"""
    [out:json][timeout:8];
    (
      node["highway"="construction"]({s},{w},{n},{e});
      way["highway"="construction"]({s},{w},{n},{e});
      node["construction"]({s},{w},{n},{e});
      way["construction"]({s},{w},{n},{e});
      node["barrier"="construction"]({s},{w},{n},{e});
    );
    out center {max_items};
    """
    elements = cached_overpass_elements(f"roadwork:{s:.2f},{w:.2f},{n:.2f},{e:.2f}", query, timeout=6.0)
    out: list[Hazard] = []
    for el in elements[:max_items]:
        lat = el.get("lat") or el.get("center", {}).get("lat")
        lng = el.get("lon") or el.get("center", {}).get("lon")
        if lat is None or lng is None:
            continue
        # Only if actually near the route line (bbox is coarse).
        if min(haversine_m(lat, lng, p[0], p[1]) for p in points) > 300:
            continue
        name = el.get("tags", {}).get("name", "Construction / road work")
        out.append(Hazard(HazardType.ROADWORK, Severity.LOW, lat, lng, "overpass",
                          f"{name} on the route — expect diversion, debris or narrowed lanes."))
    return out
