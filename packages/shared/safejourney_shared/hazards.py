"""Hazard taxonomy and severity weighting.

The weights encode SafeJourney's point of view: which hazards actually kill people on
ordinary journeys in India (see README for the fatality data that motivates each).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class HazardType(str, Enum):
    # Weather / natural
    FLOOD = "flood"                 # waterlogging, flash flood, flooded underpass
    LIGHTNING = "lightning"         # active cell, open-ground exposure
    STORM = "storm"                 # heavy rain / high wind / cyclone
    HEAT = "heat"                   # extreme-heat window
    LANDSLIDE = "landslide"         # slope failure, rockfall
    GLOF = "glof"                   # glacier-lake outburst / upstream blockage cascade

    # Infrastructure / road
    ROADWORK = "roadwork"           # construction, diversions
    POTHOLE = "pothole"             # broken road, open manhole, pit
    UNLIT = "unlit"                 # unlit stretch at night
    BLACKSPOT = "blackspot"         # historical accident cluster
    RAIL_CROSSING = "rail_crossing" # unmanned railway crossing

    # Incident (recently occurred on the path)
    ELECTROCUTION = "electrocution" # live wire / waterlogged pole reported
    ACCIDENT = "accident"           # crash reported on corridor
    WATERLOGGING = "waterlogging"   # standing water reported

    # Human safety
    UNSAFE_AREA = "unsafe_area"     # crime hotspot / isolated stretch

    OTHER = "other"


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    CRITICAL = "critical"


# Numeric score per severity — used by the SafetyScore engine.
SEVERITY_SCORE: dict[Severity, float] = {
    Severity.INFO: 0.0,
    Severity.LOW: 1.0,
    Severity.MODERATE: 2.5,
    Severity.HIGH: 5.0,
    Severity.CRITICAL: 9.0,
}

# Per-hazard multiplier. Hazards that combine with rain to kill (flood+live wire) and
# hazards people cannot see coming (GLOF, lightning) carry the most weight.
HAZARD_WEIGHTS: dict[HazardType, float] = {
    HazardType.FLOOD: 1.4,
    HazardType.LIGHTNING: 1.5,
    HazardType.STORM: 1.0,
    HazardType.HEAT: 0.9,
    HazardType.LANDSLIDE: 1.6,
    HazardType.GLOF: 2.0,
    HazardType.ROADWORK: 0.7,
    HazardType.POTHOLE: 1.0,
    HazardType.UNLIT: 0.8,
    HazardType.BLACKSPOT: 1.1,
    HazardType.RAIL_CROSSING: 1.2,
    HazardType.ELECTROCUTION: 1.9,
    HazardType.ACCIDENT: 1.2,
    HazardType.WATERLOGGING: 1.1,
    HazardType.UNSAFE_AREA: 1.0,
    HazardType.OTHER: 0.8,
}

# Severity at or above which a hazard is treated as *blocking* — the route should be
# avoided outright rather than merely flagged.
BLOCKING_SEVERITY = Severity.CRITICAL

# Hazards whose CRITICAL form means "do not proceed on foot/two-wheeler through it".
HARD_BLOCK_TYPES = {
    HazardType.FLOOD,
    HazardType.ELECTROCUTION,
    HazardType.GLOF,
    HazardType.LANDSLIDE,
}


@dataclass
class Hazard:
    """A single detected hazard on (or near) a route corridor."""

    type: HazardType
    severity: Severity
    lat: float
    lng: float
    source: str                      # e.g. "open-meteo", "gdacs", "crowd", "overpass"
    description: str = ""
    # Distance along the route (metres from origin) where it applies, if known.
    distance_along_m: Optional[float] = None
    # How far the hazard sits from the route line, metres.
    offset_m: Optional[float] = None
    expires_at: Optional[float] = None  # epoch seconds; None = no known expiry
    meta: dict = field(default_factory=dict)

    @property
    def base_score(self) -> float:
        return SEVERITY_SCORE[self.severity] * HAZARD_WEIGHTS[self.type]

    @property
    def is_blocking(self) -> bool:
        return (
            self.severity == Severity.CRITICAL
            and self.type in HARD_BLOCK_TYPES
        )

    def key(self) -> str:
        """Stable identity for change-detection between monitoring ticks."""
        # Round location so tiny GPS jitter doesn't look like a new hazard.
        return f"{self.type.value}:{round(self.lat, 3)}:{round(self.lng, 3)}"

    def to_dict(self) -> dict:
        return {
            "type": self.type.value,
            "severity": self.severity.value,
            "lat": self.lat,
            "lng": self.lng,
            "source": self.source,
            "description": self.description,
            "distance_along_m": self.distance_along_m,
            "offset_m": self.offset_m,
            "expires_at": self.expires_at,
            "meta": self.meta,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Hazard":
        return cls(
            type=HazardType(d["type"]),
            severity=Severity(d["severity"]),
            lat=d["lat"],
            lng=d["lng"],
            source=d.get("source", "unknown"),
            description=d.get("description", ""),
            distance_along_m=d.get("distance_along_m"),
            offset_m=d.get("offset_m"),
            expires_at=d.get("expires_at"),
            meta=d.get("meta", {}),
        )
