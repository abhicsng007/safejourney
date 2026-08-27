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
        # Fresh reports weigh full; decay confidence for older unverified ones.
        age_min = (now - inc.reported_at) / 60
        desc = inc.description or f"Reported {htype.value.replace('_', ' ')}"
        if not inc.verified and age_min > 120:
            desc += " (unverified, aging)"
        out.append(Hazard(htype, sev, inc.lat, inc.lng, f"report:{inc.source}", desc,
                          offset_m=offset, meta={"incident_id": inc.id, "verified": inc.verified}))
    return out
