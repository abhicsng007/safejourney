"""Recently-occurred incidents on/near the path — broken road, open manhole, electrocution,
accident, waterlogging — from crowd/official reports stored in Firestore.

This is how SafeJourney knows about a live wire down in the water *before* the traveller
reaches it: someone (or an official feed) reported it, geotagged, minutes earlier.
"""

from __future__ import annotations

import time

from safejourney_shared.geo import point_near_polyline_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ..repo import get_repo

# How long a crowd report stays relevant before it expires entirely (seconds). Transient
# conditions (waterlogging, a cleared accident) fade fast; physical damage (potholes, road
# works) lasts. A verified/official report gets a longer life (see ttl_for).
INCIDENT_TTL_S: dict[str, int] = {
    "waterlogging": 3 * 3600,
    "flood": 6 * 3600,
    "lightning": 2 * 3600,
    "storm": 3 * 3600,
    "electrocution": 6 * 3600,
    "accident": 3 * 3600,
    "unsafe_area": 12 * 3600,
    "landslide": 3 * 24 * 3600,
    "roadwork": 14 * 24 * 3600,
    "pothole": 7 * 24 * 3600,
}
_DEFAULT_TTL_S = 24 * 3600

_SEV_ORDER = [Severity.INFO, Severity.LOW, Severity.MODERATE, Severity.HIGH, Severity.CRITICAL]


def ttl_for(hazard_type: str, verified: bool = False) -> int:
    """Lifetime of a report of this type; verified/official reports live 3x longer."""
    base = INCIDENT_TTL_S.get(hazard_type, _DEFAULT_TTL_S)
    return base * 3 if verified else base


def _downgrade(sev: Severity) -> Severity:
    return _SEV_ORDER[max(0, _SEV_ORDER.index(sev) - 1)]


def incident_hazards(
    corridor_points: list[tuple[float, float]],
    corridor_geohashes: list[str],
    max_offset_m: float = 350.0,
) -> list[Hazard]:
    repo = get_repo()
    incidents = repo.incidents_in_cells(set(corridor_geohashes))
    now = time.time()
    out: list[Hazard] = []
    for inc in incidents:
        offset = point_near_polyline_m(inc.lat, inc.lng, corridor_points)
        if offset > max_offset_m:
            continue
        try:
            htype = HazardType(inc.type)
        except ValueError:
            htype = HazardType.OTHER
        try:
            sev = Severity(inc.severity)
        except ValueError:
            sev = Severity.MODERATE
        # Age the report against its type-specific lifetime: drop it once past its life, and
        # fade its severity (unverified reports only) over the second half of that life.
        ttl = ttl_for(inc.type, inc.verified)
        frac = (now - inc.reported_at) / ttl if ttl else 1.0
        if frac >= 1.0:
            continue  # stale — belt-and-suspenders with the repo's expires_at filter
        desc = inc.description or f"Reported {htype.value.replace('_', ' ')}"
        if not inc.verified and frac >= 0.5:
            sev = _downgrade(sev)
            desc += " (fading — unverified & aging)"
        out.append(Hazard(htype, sev, inc.lat, inc.lng, f"report:{inc.source}", desc,
                          offset_m=offset,
                          meta={"incident_id": inc.id, "verified": inc.verified,
                                "age_frac": round(frac, 2)}))
    return out
