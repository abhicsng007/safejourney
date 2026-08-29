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
    distance_along_polyline_m,
    point_near_polyline_m,
    sample_polyline,
)
from safejourney_shared.hazards import Hazard, HazardType

from .weather import weather_hazards
from .disaster import disaster_hazards
from .roadwork import roadwork_hazards
from .incident import incident_hazards
from .geometry_hazards import sharp_turn_hazards
from .lighting import unlit_hazards
from .blackspot import blackspot_hazards
from .osm_hazards import osm_hazards
from .pedestrian_hazards import pedestrian_hazards

_WET_TYPES = {HazardType.FLOOD, HazardType.STORM, HazardType.WATERLOGGING, HazardType.LIGHTNING}


def _annotate(hazards: list[Hazard], route_pts: list[tuple[float, float]]) -> None:
    """Fill offset_m (distance from route line, for exposure weighting) and distance_along_m
    (metres from the start of the given corridor — i.e. how far ahead the hazard is)."""
    for h in hazards:
        if h.offset_m is None:
            h.offset_m = point_near_polyline_m(h.lat, h.lng, route_pts)
        if h.distance_along_m is None:
            h.distance_along_m = distance_along_polyline_m(h.lat, h.lng, route_pts)


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
    mode: str = "two_wheeler",
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

    # Run independent network sources in parallel under a HARD total budget: a throttled feed
    # (e.g. Overpass timing out on every mirror) must never stall the whole scan. We collect
    # whatever finished within the deadline and abandon stragglers (shutdown(wait=False)), so a
    # tick/plan stays responsive and simply loses that one feed's hazards for this run.
    import time as _time

    hazards: list[Hazard] = []
    pool = ThreadPoolExecutor(max_workers=6)
    try:
        f_weather = pool.submit(weather_hazards, sampled)
        f_roadwork = pool.submit(roadwork_hazards, sampled) if include_roadwork else None
        f_incident = (
            pool.submit(incident_hazards, route_points, geohashes, max_offset_m)
            if include_incidents else None
        )
        f_unlit = pool.submit(unlit_hazards, sampled) if include_roadwork else None
        f_osm = pool.submit(osm_hazards, sampled) if include_roadwork else None
        f_ped = pool.submit(pedestrian_hazards, route_points) if mode == "walk" else None

        deadline = _time.time() + 9.0

        def _grab(f):
            if f is None:
                return []
            try:
                return f.result(timeout=max(0.1, deadline - _time.time())) or []
            except Exception:
                return []  # slow/failed feed — skip it for this scan

        weather = _grab(f_weather)
        hazards += weather
        for f in (f_roadwork, f_incident, f_unlit, f_osm, f_ped):
            hazards += _grab(f)

        # Disaster/GLOF reasoning depends on whether it's currently wet along the route.
        if include_disaster:
            raining = any(h.type in _WET_TYPES for h in weather)
            f_disaster = pool.submit(disaster_hazards, sampled, raining)
            hazards += _grab(f_disaster)
    finally:
        pool.shutdown(wait=False, cancel_futures=True)

    # Local, no-network detectors — cheap, always on.
    hazards += sharp_turn_hazards(route_points) or []
    hazards += blackspot_hazards(route_points, max_offset_m) or []

    _annotate(hazards, route_points)
    # Drop hazards that turned out to be far from the actual line.
    hazards = [h for h in hazards if (h.offset_m or 0) <= max_offset_m or h.type == HazardType.GLOF]
    return _dedupe(hazards)
