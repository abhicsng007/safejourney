"""Pydantic models for the SafeJourney domain — the shapes stored in Firestore and passed
across the REST + Pub/Sub boundaries.
"""

from __future__ import annotations

import time
import uuid
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field

from .hazards import Hazard


def _now() -> float:
    return time.time()


def _id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:12]}"


class LatLng(BaseModel):
    lat: float
    lng: float


class TravelMode(str, Enum):
    WALK = "walk"
    TWO_WHEELER = "two_wheeler"
    CAR = "car"
    TRANSIT = "transit"


class TripStatus(str, Enum):
    PLANNED = "planned"
    ACTIVE = "active"
    PAUSED = "paused"     # holding at a safe harbour
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class AlertAction(str, Enum):
    ADVISORY = "advisory"     # take a precaution, keep going
    REROUTE = "reroute"       # switch to a safer path
    HARBOR = "harbor"         # divert to a safe place and wait
    SOS = "sos"               # escalate to contacts / emergency
    CLEAR = "clear"           # previously-flagged hazard has passed


class UserProfile(BaseModel):
    uid: str
    display_name: str = ""
    default_mode: TravelMode = TravelMode.TWO_WHEELER
    risk_tolerance: float = 1.0        # 0.5 cautious .. 1.5 bold
    language: str = "en"
    medical_notes: str = ""
    trusted_contacts: list[dict] = Field(default_factory=list)  # {name, phone}
    home: Optional[LatLng] = None


class Incident(BaseModel):
    """A recently-occurred, location-specific event on/near a path (crowd or official)."""

    id: str = Field(default_factory=lambda: _id("inc"))
    type: str                          # HazardType value
    severity: str                      # Severity value
    lat: float
    lng: float
    geohash: str = ""
    description: str = ""
    source: str = "crowd"
    verified: bool = False
    reported_at: float = Field(default_factory=_now)
    expires_at: Optional[float] = None


class HazardSnapshot(BaseModel):
    """The result of one hazard evaluation of a trip corridor."""

    id: str = Field(default_factory=lambda: _id("snap"))
    trip_id: str
    created_at: float = Field(default_factory=_now)
    safety_score: float = 0.0
    hazards: list[dict] = Field(default_factory=list)   # Hazard.to_dict()

    def hazard_objects(self) -> list[Hazard]:
        return [Hazard.from_dict(h) for h in self.hazards]


class Alert(BaseModel):
    id: str = Field(default_factory=lambda: _id("alert"))
    trip_id: str
    uid: str = ""
    created_at: float = Field(default_factory=_now)
    action: AlertAction
    severity: str
    title: str
    message: str
    precautions: list[str] = Field(default_factory=list)
    hazard_types: list[str] = Field(default_factory=list)
    location: Optional[LatLng] = None
    acknowledged: bool = False
    meta: dict = Field(default_factory=dict)


class Trip(BaseModel):
    id: str = Field(default_factory=lambda: _id("trip"))
    uid: str
    mode: TravelMode = TravelMode.TWO_WHEELER
    origin: LatLng
    destination: LatLng
    origin_label: str = ""
    destination_label: str = ""

    status: TripStatus = TripStatus.PLANNED
    encoded_polyline: str = ""
    corridor_geohashes: list[str] = Field(default_factory=list)
    distance_m: float = 0.0
    duration_s: float = 0.0

    current_position: Optional[LatLng] = None
    started_at: Optional[float] = None
    completed_at: Optional[float] = None

    # Device token for push notifications (FCM).
    fcm_token: str = ""

    # Autonomous-monitoring bookkeeping.
    monitor_interval_s: int = 180
    next_check_at: float = 0.0
    last_snapshot_id: str = ""
    last_hazard_keys: list[str] = Field(default_factory=list)  # for change-detection

    created_at: float = Field(default_factory=_now)

    def remaining_polyline_points(self, decoded: list[tuple[float, float]]) -> list[tuple[float, float]]:
        """Trim the route to what's ahead of the current position, so monitoring only
        looks at road the traveller hasn't passed yet."""
        if not self.current_position or not decoded:
            return decoded
        from .geo import haversine_m

        cur = (self.current_position.lat, self.current_position.lng)
        # Find the nearest vertex, keep everything from there onward.
        idx = min(
            range(len(decoded)),
            key=lambda i: haversine_m(cur[0], cur[1], decoded[i][0], decoded[i][1]),
        )
        return decoded[idx:] or decoded
