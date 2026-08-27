"""Trip lifecycle — create (with route pre-detection), start, update position, complete —
plus the demo hazard-injection hook used to make the autonomous alert fire on cue.
"""

from __future__ import annotations

import time

from safejourney_shared.geo import corridor_geohashes, decode_polyline, geohash_encode
from safejourney_shared.hazards import HazardType, Severity
from safejourney_shared.models import (
    Incident,
    LatLng,
    Trip,
    TravelMode,
    TripStatus,
)

from ..config import get_settings
from ..repo import get_repo
from .planner import plan_and_score, plan_journey


def create_trip(
    uid: str,
    origin: LatLng,
    destination: LatLng,
    mode: str = "two_wheeler",
    origin_label: str = "",
    destination_label: str = "",
    risk_tolerance: float = 1.0,
) -> dict:
    """Plan + score routes (incl. the home→station first leg), create the trip on the
    recommended (safest) route."""
    plan = plan_journey(
        (origin.lat, origin.lng), (destination.lat, destination.lng), mode, risk_tolerance
    )
    routes = plan["routes"]
    chosen = next((r for r in routes if r["route_id"] == plan["recommended_route_id"]), routes[0] if routes else None)

    trip = Trip(
        uid=uid,
        mode=TravelMode(mode),
        origin=origin,
        destination=destination,
        origin_label=origin_label,
        destination_label=destination_label,
        status=TripStatus.PLANNED,
    )
    if chosen:
        trip.encoded_polyline = chosen["encoded_polyline"]
        pts = decode_polyline(trip.encoded_polyline)
        trip.corridor_geohashes = corridor_geohashes(pts)
        trip.distance_m = chosen.get("distance_m", 0)
        trip.duration_s = chosen.get("duration_s", 0)

    get_repo().save_trip(trip)
    return {"trip": trip.model_dump(mode="json"), "plan": plan}


def choose_route(trip_id: str, route: dict) -> Trip | None:
    """Override the trip's path with a specific candidate route (dict from a plan)."""
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return None
    trip.encoded_polyline = route["encoded_polyline"]
    pts = decode_polyline(trip.encoded_polyline)
    trip.corridor_geohashes = corridor_geohashes(pts)
    trip.distance_m = route.get("distance_m", trip.distance_m)
    trip.duration_s = route.get("duration_s", trip.duration_s)
    repo.save_trip(trip)
    return trip


def start_trip(trip_id: str, fcm_token: str = "") -> Trip | None:
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return None
    trip.status = TripStatus.ACTIVE
    trip.started_at = time.time()
    trip.current_position = trip.current_position or trip.origin
    trip.next_check_at = time.time()  # first tick eligible immediately
    if fcm_token:
        trip.fcm_token = fcm_token
    repo.save_trip(trip)
    return trip


def update_position(trip_id: str, pos: LatLng) -> Trip | None:
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return None
    trip.current_position = pos
    repo.save_trip(trip)
    return trip


def complete_trip(trip_id: str) -> Trip | None:
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return None
    trip.status = TripStatus.COMPLETED
    trip.completed_at = time.time()
    repo.save_trip(trip)
    return trip


def set_status(trip_id: str, status: str) -> Trip | None:
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return None
    trip.status = TripStatus(status)
    repo.save_trip(trip)
    return trip


def force_hazard(
    trip_id: str,
    hazard_type: str = "flood",
    severity: str = "critical",
    at_fraction: float = 0.5,
    description: str = "",
) -> dict:
    """DEMO HOOK: inject an incident on the trip's remaining corridor so the next monitoring
    tick detects it and fires a real alert. This makes the autonomous behaviour demoable on
    cue (the 'unedited live execution' moment) without waiting for real weather."""
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return {"error": "trip not found"}
    pts = decode_polyline(trip.encoded_polyline)
    if not pts:
        return {"error": "trip has no route"}
    idx = min(len(pts) - 1, max(0, int(len(pts) * at_fraction)))
    lat, lng = pts[idx]

    try:
        HazardType(hazard_type)
    except ValueError:
        hazard_type = "flood"
    try:
        Severity(severity)
    except ValueError:
        severity = "critical"

    desc = description or {
        "flood": "Underpass flooding fast; water rising over the road.",
        "electrocution": "Fallen live wire reported in standing water near a pole.",
        "landslide": "Fresh landslide debris reported blocking a lane.",
        "pothole": "Large open pit / broken road reported.",
    }.get(hazard_type, "Hazard reported on the road ahead.")

    inc = Incident(
        type=hazard_type,
        severity=severity,
        lat=lat,
        lng=lng,
        geohash=geohash_encode(lat, lng, 7),
        description=desc,
        source="demo",
        verified=True,
        reported_at=time.time(),
        expires_at=time.time() + 3600,
    )
    repo.add_incident(inc)
    # Make the trip due for an immediate check.
    trip.next_check_at = 0.0
    repo.save_trip(trip)
    return {"incident": inc.model_dump(mode="json"), "at": {"lat": lat, "lng": lng}}
