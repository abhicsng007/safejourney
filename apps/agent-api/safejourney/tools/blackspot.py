"""Accident-blackspot hazards — historically crash-prone points near the route.

Ships a small curated seed of known blackspots (MoRTH/state road-safety data publishes ~5,000
national black spots; this is a demo subset around the app's preset cities + a couple of
notorious highway stretches). In production this list is loaded from that official dataset —
the matching logic is identical.
"""

from __future__ import annotations

from safejourney_shared.geo import point_near_polyline_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

# (lat, lng, name). Curated demo seed — representative, not exhaustive.
_BLACKSPOTS = [
    # Bengaluru
    (12.9166, 77.6101, "Silk Board junction, Bengaluru"),
    (13.0287, 77.5401, "Hebbal flyover approach, Bengaluru"),
    (12.9560, 77.7000, "Marathahalli bridge, Bengaluru"),
    (12.9345, 77.6260, "Koramangala–Sarjapur signal, Bengaluru"),
    # Mountain / highway
    (30.1490, 78.3200, "NH-7 Rishikesh–Devprayag cliff stretch"),
    (30.4200, 79.3300, "Alaknanda gorge bend, Uttarakhand"),
    (27.3900, 88.6100, "NH-10 Sevoke–Gangtok landslide bend, Sikkim"),
]

_MAX = 4


def blackspot_hazards(route_points: list[tuple[float, float]], max_offset_m: float = 200.0) -> list[Hazard]:
    if not route_points:
        return []
    hits: list[tuple[float, Hazard]] = []
    for blat, blng, name in _BLACKSPOTS:
        offset = point_near_polyline_m(blat, blng, route_points)
        if offset > max_offset_m:
            continue
        h = Hazard(
            HazardType.BLACKSPOT, Severity.MODERATE, blat, blng, "blackspot-db",
            f"{name} — recurring accident blackspot; cut speed, no overtaking.",
            offset_m=offset,
        )
        hits.append((offset, h))
    hits.sort(key=lambda x: x[0])
    return [h for _, h in hits[:_MAX]]
