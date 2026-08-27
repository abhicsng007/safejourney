"""SafetyScore — turns a set of hazards on a route into a single comparable number.

Lower is safer. The score is exposure-aware (a hazard spanning 2km of your path matters
more than a point hazard) and profile-aware (a two-wheeler rider is far more exposed to
lightning and waterlogging than someone in a car).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .hazards import Hazard, HazardType, Severity

# How much more/less each travel mode is exposed to a given hazard type.
# 1.0 = baseline. >1 = more dangerous in this mode.
_MODE_EXPOSURE: dict[str, dict[HazardType, float]] = {
    "walk": {
        HazardType.FLOOD: 1.4,
        HazardType.ELECTROCUTION: 1.6,
        HazardType.LIGHTNING: 1.5,
        HazardType.UNLIT: 1.4,
        HazardType.UNSAFE_AREA: 1.5,
        HazardType.HEAT: 1.4,
        HazardType.POTHOLE: 0.6,
    },
    "two_wheeler": {
        HazardType.FLOOD: 1.5,
        HazardType.ELECTROCUTION: 1.5,
        HazardType.LIGHTNING: 1.5,
        HazardType.POTHOLE: 1.5,
        HazardType.WATERLOGGING: 1.4,
        HazardType.ACCIDENT: 1.3,
        HazardType.STORM: 1.3,
        HazardType.SHARP_TURN: 1.4,
    },
    "car": {
        HazardType.FLOOD: 1.1,
        HazardType.LIGHTNING: 0.4,
        HazardType.ELECTROCUTION: 0.5,
        HazardType.POTHOLE: 0.9,
        HazardType.UNSAFE_AREA: 0.6,
        HazardType.HEAT: 0.4,
    },
    "transit": {
        HazardType.FLOOD: 0.9,
        HazardType.LIGHTNING: 0.5,
        HazardType.UNSAFE_AREA: 0.9,
        HazardType.POTHOLE: 0.3,
    },
}


def _mode_factor(mode: str, htype: HazardType) -> float:
    return _MODE_EXPOSURE.get(mode, {}).get(htype, 1.0)


def _exposure_factor(hazard: Hazard) -> float:
    """A hazard right on the path (offset 0) counts fully; one 400m off counts little."""
    if hazard.offset_m is None:
        return 1.0
    if hazard.offset_m <= 30:
        return 1.0
    if hazard.offset_m >= 400:
        return 0.15
    # Linear falloff between 30m and 400m.
    return 1.0 - 0.85 * (hazard.offset_m - 30) / (400 - 30)


@dataclass
class ScoredRoute:
    route_id: str
    score: float
    hazards: list[Hazard]
    blocking: bool
    summary: str = ""
    encoded_polyline: str = ""
    distance_m: float = 0.0
    duration_s: float = 0.0
    meta: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "route_id": self.route_id,
            "score": round(self.score, 2),
            "rating": classify_score(self.score),
            "blocking": self.blocking,
            "summary": self.summary,
            "encoded_polyline": self.encoded_polyline,
            "distance_m": self.distance_m,
            "duration_s": self.duration_s,
            "hazards": [h.to_dict() for h in self.hazards],
            "meta": self.meta,
        }


def safety_score(
    hazards: list[Hazard],
    mode: str = "two_wheeler",
    risk_tolerance: float = 1.0,
) -> float:
    """Aggregate hazard danger for one route. Lower = safer.

    risk_tolerance: 0.5 (cautious user, weights danger up) .. 1.5 (bold user, weights down).
    """
    total = 0.0
    for h in hazards:
        contrib = h.base_score * _mode_factor(mode, h.type) * _exposure_factor(h)
        total += contrib
    # Cautious users should see higher scores for the same hazards.
    total = total / max(0.25, risk_tolerance)
    return round(total, 3)


def route_is_blocking(hazards: list[Hazard]) -> bool:
    return any(h.is_blocking for h in hazards)


def classify_score(score: float) -> str:
    """Human-facing band for a route score."""
    if score <= 2:
        return "safe"
    if score <= 6:
        return "caution"
    if score <= 14:
        return "risky"
    return "dangerous"


def rank_routes(routes: list[ScoredRoute]) -> list[ScoredRoute]:
    """Safest first; a non-blocking route always beats a blocking one."""
    return sorted(routes, key=lambda r: (r.blocking, r.score))
