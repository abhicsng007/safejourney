"""SafeJourney shared domain logic — hazards, geo utilities, safety scoring, models.

Imported by both `agent-api` and `monitor-worker` so the definition of "how dangerous
is this?" lives in exactly one place.
"""

from .hazards import Hazard, HazardType, Severity, HAZARD_WEIGHTS, SEVERITY_SCORE
from .geo import (
    decode_polyline,
    encode_polyline,
    haversine_m,
    geohash_encode,
    corridor_geohashes,
    sample_polyline,
    point_near_polyline_m,
)
from .scoring import safety_score, ScoredRoute, classify_score
from .models import (
    LatLng,
    Trip,
    TripStatus,
    TravelMode,
    HazardSnapshot,
    Alert,
    AlertAction,
    Incident,
    UserProfile,
)

__all__ = [
    "Hazard",
    "HazardType",
    "Severity",
    "HAZARD_WEIGHTS",
    "SEVERITY_SCORE",
    "decode_polyline",
    "encode_polyline",
    "haversine_m",
    "geohash_encode",
    "corridor_geohashes",
    "sample_polyline",
    "point_near_polyline_m",
    "safety_score",
    "ScoredRoute",
    "classify_score",
    "LatLng",
    "Trip",
    "TripStatus",
    "TravelMode",
    "HazardSnapshot",
    "Alert",
    "AlertAction",
    "Incident",
    "UserProfile",
]
