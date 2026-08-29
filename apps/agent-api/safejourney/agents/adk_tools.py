"""ADK-facing tool functions.

ADK derives each tool's schema from the function signature + docstring, so these wrappers
expose primitive parameters (floats, strings) and return JSON-serializable dicts. They
delegate to the same underlying services the REST API and monitor use.
"""

from __future__ import annotations

from safejourney_shared.geo import decode_polyline
from safejourney_shared.hazards import HazardType
from safejourney_shared.models import LatLng

from ..services.planner import plan_and_score
from ..services import trips as trips_svc
from ..services.monitor import evaluate_trip as _evaluate_trip
from ..tools.hazard_scan import scan_corridor
from ..tools.places import find_safe_harbors as _find_safe_harbors
from ..tools.mobility import mobility_options as _mobility_options
from ..services.precautions import precautions_for


def plan_safe_routes(origin_lat: float, origin_lng: float,
                     dest_lat: float, dest_lng: float, mode: str = "two_wheeler") -> dict:
    """Plan candidate routes from origin to destination and rank them by safety.

    Returns routes (safest first) with a safety score, rating, detected hazards, and a
    recommended route id, plus precautions for the recommended route.

    Args:
        origin_lat: Origin latitude.
        origin_lng: Origin longitude.
        dest_lat: Destination latitude.
        dest_lng: Destination longitude.
        mode: One of walk, two_wheeler, car, transit.
    """
    return plan_and_score((origin_lat, origin_lng), (dest_lat, dest_lng), mode)


def scan_route_hazards(encoded_polyline: str, mode: str = "two_wheeler") -> dict:
    """Scan a specific route (Google-encoded polyline) for current hazards.

    Returns the list of detected hazards with type, severity, location and description.

    Args:
        encoded_polyline: A Google/Mapbox encoded polyline for the route.
        mode: Travel mode; "walk" adds a pedestrian check for no-footpath / vehicle-only
            underpass stretches.
    """
    pts = decode_polyline(encoded_polyline)
    hazards = scan_corridor(pts, mode=mode)
    return {
        "count": len(hazards),
        "hazards": [h.to_dict() for h in hazards],
        "precautions": precautions_for([h.type for h in hazards]),
    }


def get_safe_harbors(lat: float, lng: float) -> dict:
    """Find the nearest safe places (metro, hospital, police, open store) to shelter at.

    Args:
        lat: Current latitude.
        lng: Current longitude.
    """
    return {"harbors": _find_safe_harbors(lat, lng)}


def get_mobility_options(lat: float, lng: float, dest_lat: float = 0.0, dest_lng: float = 0.0) -> dict:
    """Find safer alternative ways to continue: cab (Uber/Ola) deep-links, public transit,
    and the nearest station — for when the current route is blocked or unsafe.

    Args:
        lat: Current latitude.
        lng: Current longitude.
        dest_lat: Destination latitude (0 if unknown).
        dest_lng: Destination longitude (0 if unknown).
    """
    dlat = dest_lat or None
    dlng = dest_lng or None
    return _mobility_options(lat, lng, dlat, dlng)


def check_trip_now(trip_id: str) -> dict:
    """Run one live safety evaluation of an active trip's road ahead, right now.

    Returns hazard counts, the safety score, and any alert that was raised.

    Args:
        trip_id: The trip id to evaluate.
    """
    return _evaluate_trip(trip_id)


def get_precautions(hazard_types: list[str]) -> dict:
    """Return concrete safety precautions for the given hazard types.

    Args:
        hazard_types: Hazard type names, e.g. ["flood", "lightning"].
    """
    types = []
    for t in hazard_types:
        try:
            types.append(HazardType(t))
        except ValueError:
            continue
    return {"precautions": precautions_for(types)}


def report_incident(trip_id: str, hazard_type: str, severity: str = "high",
                    description: str = "") -> dict:
    """Report a hazard the traveller or a source observed on a trip's route (crowd report).

    Args:
        trip_id: The trip the report applies to.
        hazard_type: e.g. flood, electrocution, pothole, accident, waterlogging.
        severity: info, low, moderate, high, or critical.
        description: Free-text description of what was seen.
    """
    return trips_svc.force_hazard(trip_id, hazard_type, severity, description=description)


ALL_TOOLS = [
    plan_safe_routes,
    scan_route_hazards,
    get_safe_harbors,
    get_mobility_options,
    check_trip_now,
    get_precautions,
    report_incident,
]
