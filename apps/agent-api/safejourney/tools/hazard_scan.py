"""scan_corridor — fan out across every hazard source for a route corridor and return a
single merged, de-duplicated, route-annotated list of hazards.

Used in two places:
  * pre-trip route scoring (Route Guardian), and
  * each autonomous monitoring tick (Hazard Sentinel).
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from safejourney_shared.geo import (
    corridor_geohashes,
    point_near_polyline_m,
    sample_polyline,
)
from safejourney_shared.hazards import Hazard, HazardType

from .weather import weather_hazards
from .disaster import disaster_hazards
from .roadwork import roadwork_hazards
from .incident import incident_hazards

_WET_TYPES = {HazardType.FLOOD, HazardType.STORM, HazardType.WATERLOGGING, HazardType.LIGHTNING}


def _annotate(hazards: list[Hazard], route_pts: list[tuple[float, float]]) -> None:
    """Fill offset_m (distance from route line) so scoring can weight by exposure."""
    for h in hazards:
        if h.offset_m is None:
            h.offset_m = point_near_polyline_m(h.lat, h.lng, route_pts)


def _dedupe(hazards: list[Hazard]) -> list[Hazard]:
    """Keep the most severe hazard per (type, rounded-location) key."""
    from safejourney_shared.hazards import SEVERITY_SCORE

    best: dict[str, Hazard] = {}
    for h in hazards:
        k = h.key()
        if k not in best or SEVERITY_SCORE[h.severity] > SEVERITY_SCORE[best[k].severity]:
            best[k] = h
    return list(best.values())


def scan_corridor(
    route_points: list[tuple[float, float]],
    *,
    include_incidents: bool = True,
    include_roadwork: bool = True,
    include_disaster: bool = True,
    max_offset_m: float = 350.0,
) -> list[Hazard]:
    if not route_points:
        return []

    # Bounded sample so the number of external calls doesn't scale with route length.
    sampled = [(lat, lng) for lat, lng, _ in sample_polyline(route_points, step_m=500.0)]
    geohashes = corridor_geohashes(route_points, precision=7, step_m=150.0)

    # Run independent sources in parallel — the tick stays fast even with several feeds.
    hazards: list[Hazard] = []
    with ThreadPoolExecutor(max_workers=4) as pool:
        f_weather = pool.submit(weather_hazards, sampled)
        f_roadwork = pool.submit(roadwork_hazards, sampled) if include_roadwork else None
        f_incident = (
            pool.submit(incident_hazards, route_points, geohashes, max_offset_m)
            if include_incidents else None
        )

        weather = f_weather.result() or []
        hazards += weather
        if f_roadwork:
            hazards += f_roadwork.result() or []
        if f_incident:
            hazards += f_incident.result() or []

        # Disaster/GLOF reasoning depends on whether it's currently wet along the route.
        if include_disaster:
            raining = any(h.type in _WET_TYPES for h in weather)
            hazards += disaster_hazards(sampled, raining=raining) or []

    _annotate(hazards, route_points)
    # Drop hazards that turned out to be far from the actual line.
    hazards = [h for h in hazards if (h.offset_m or 0) <= max_offset_m or h.type == HazardType.GLOF]
    return _dedupe(hazards)
