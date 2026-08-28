"""Large-scale / cascading disaster signals — the part that catches things local weather
misses, like a glacier-lake outburst or landslide blockage *upstream* of the route.

Sources:
  - GDACS global disaster feed (keyless GeoJSON) for active floods/cyclones/quakes.
  - A curated list of GLOF/landslide-prone mountain basins; a route passing through or below
    one, during active rain, is flagged as a cascade risk (the Nepal/Sikkim scenario).
"""

from __future__ import annotations

from safejourney_shared.geo import haversine_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._http import get_json

_GDACS = "https://www.gdacs.org/gdacsapi/api/events/geteventlist/MAP"

# Curated high-risk mountain basins (lat, lng, radius_km, name). In production this comes
# from NDMA's ~190 monitored glacial lakes + CWC river gauges; the shape is the same.
_GLOF_BASINS = [
    (27.75, 88.20, 60, "Teesta / South Lhonak basin, Sikkim"),
    (30.73, 79.06, 50, "Alaknanda / Rishiganga basin, Uttarakhand"),
    (27.88, 86.72, 40, "Dudh Koshi / Everest region, Nepal"),
    (28.30, 85.30, 45, "Trishuli / Rasuwa basin, Nepal"),
    (34.55, 76.10, 45, "Upper Indus / Ladakh basin"),
]

_GDACS_TYPE = {
    "FL": (HazardType.FLOOD, "Active flood event"),
    "TC": (HazardType.STORM, "Tropical cyclone"),
    "EQ": (HazardType.LANDSLIDE, "Earthquake — landslide/aftershock risk"),
    "VO": (HazardType.OTHER, "Volcanic activity"),
}

_ALERT_SEVERITY = {"Red": Severity.CRITICAL, "Orange": Severity.HIGH, "Green": Severity.MODERATE}

_SEV_ORDER = [Severity.LOW, Severity.MODERATE, Severity.HIGH, Severity.CRITICAL]


def _scale_by_distance(sev: Severity, dist_m: float) -> Severity:
    """A regional event far from the route is a weaker signal — step its severity down."""
    if sev not in _SEV_ORDER or dist_m <= 25_000:
        return sev
    steps = 1 if dist_m <= 60_000 else 2
    return _SEV_ORDER[max(0, _SEV_ORDER.index(sev) - steps)]


def _glof_hazards(points: list[tuple[float, float]], raining: bool) -> list[Hazard]:
    out: list[Hazard] = []
    flagged: set[str] = set()
    for lat, lng in points:
        for blat, blng, radius_km, name in _GLOF_BASINS:
            if name in flagged:
                continue
            if haversine_m(lat, lng, blat, blng) <= radius_km * 1000:
                sev = Severity.CRITICAL if raining else Severity.MODERATE
                desc = (
                    f"Route passes through {name}, a glacier-lake/landslide-prone basin. "
                    + ("Active rain upstream sharply raises flash-flood/GLOF cascade risk."
                       if raining else
                       "Monitor upstream conditions; sudden surges possible even in clear weather.")
                )
                out.append(Hazard(HazardType.GLOF, sev, lat, lng, "glof-basin", desc))
                flagged.add(name)
    return out


def disaster_hazards(points: list[tuple[float, float]], raining: bool = False) -> list[Hazard]:
    out: list[Hazard] = _glof_hazards(points, raining)

    data = get_json(
        _GDACS,
        params={"alertlevel": "Orange;Red", "eventlist": "FL;TC;EQ;VO"},
        timeout=6.0,
    )
    features = (data or {}).get("features", []) if isinstance(data, dict) else []
    for f in features:
        try:
            geom = f.get("geometry", {}).get("coordinates", [])
            props = f.get("properties", {})
            elng, elat = float(geom[0]), float(geom[1])
        except Exception:
            continue
        etype = props.get("eventtype", "")
        if etype not in _GDACS_TYPE:
            continue
        htype, label = _GDACS_TYPE[etype]
        base = _ALERT_SEVERITY.get(props.get("alertlevel", "Orange"), Severity.HIGH)
        # Snap the regional event to the route's closest approach so it isn't dropped as
        # "off the line" (event footprints are large); state the real distance and step the
        # severity down with distance so a far event doesn't dominate the score.
        nearest = min(points, key=lambda p: haversine_m(p[0], p[1], elat, elng), default=None)
        if nearest is None:
            continue
        near = haversine_m(nearest[0], nearest[1], elat, elng)
        if near <= 120_000:  # 120 km
            name = props.get("name", label)
            sev = _scale_by_distance(base, near)
            out.append(Hazard(htype, sev, nearest[0], nearest[1], "gdacs",
                              f"{label}: {name} — regional advisory, ~{near/1000:.0f} km from your route.",
                              offset_m=0.0))
    return out
