"""Walk-only pedestrian-safety hazards from OpenStreetMap (Overpass, keyless).

Google's `mode=walking` router already prefers footpaths and crossings and refuses to send
pedestrians through motorway-only tunnels — so this detector is not a router. It is a
*warning* layer: it flags the stretches a walking route may still have to share with fast
traffic where there is no footpath, and vehicle-only underpasses the route runs alongside,
so the walker gets told before they get there.

High-confidence signals only (OSM footpath tagging in India is patchy, so we never guess
"no footpath" from a *missing* tag — only from explicit vehicle-only / `foot=no` ways with
no pedestrian way nearby):

  * the route point sits on/next to a `motorway|trunk|…` or a `foot=no` way, AND
  * there is no footway / path / pedestrian way within reach.

A vehicle-only `tunnel=yes` way triggers the stronger "vehicle-only underpass" message.
"""

from __future__ import annotations

from safejourney_shared.geo import haversine_m, point_near_polyline_m, sample_polyline
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._overpass import cached_overpass_elements

# highway=* values that are pedestrian ways (walking here is the intended use).
_PED_HIGHWAY = {"footway", "path", "pedestrian", "steps", "living_street"}
# highway=* values that are vehicle-only / unsafe to walk along.
_VEHICLE_HIGHWAY = {"motorway", "trunk", "motorway_link", "trunk_link"}

# A route point this close (m) to a vehicle-only way is treated as walking along it.
_NEAR_VEHICLE_M = 20.0
# ...and this far (m) from any pedestrian way means there's no footpath to fall back to.
_FAR_FROM_PED_M = 35.0
# Don't emit two hazards for the same stretch — collapse points closer than this along-route.
_MIN_GAP_M = 200.0


def classify_way(tags: dict) -> str | None:
    """'pedestrian', 'vehicle_only', or None — the walk-safety role of an OSM way.

    Pure/tag-only so it's unit-testable without the network.
    """
    if not tags:
        return None
    highway = tags.get("highway", "")
    foot = tags.get("foot", "")

    # Explicitly walkable wins, even if it's a service road with foot=yes.
    if highway in _PED_HIGHWAY or foot == "yes" or tags.get("footway"):
        return "pedestrian"
    if tags.get("sidewalk") in ("both", "left", "right", "yes"):
        return "pedestrian"

    if highway in _VEHICLE_HIGHWAY or foot == "no":
        return "vehicle_only"
    return None


def _is_underpass(tags: dict) -> bool:
    return tags.get("tunnel") == "yes" or tags.get("covered") == "yes"


def _way_points(el: dict) -> list[tuple[float, float]]:
    geom = el.get("geometry") or []
    return [(g["lat"], g["lon"]) for g in geom if "lat" in g and "lon" in g]


def _bbox(points, pad_deg: float = 0.008):
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats) - pad_deg, min(lngs) - pad_deg, max(lats) + pad_deg, max(lngs) + pad_deg)


def pedestrian_hazards(points: list[tuple[float, float]], max_items: int = 6) -> list[Hazard]:
    """Flag no-footpath / vehicle-only-underpass stretches along a *walking* route corridor."""
    if not points or len(points) < 2:
        return []
    s, w, n, e = _bbox(points)
    if (n - s) * (e - w) > 0.5:  # keep the Overpass query cheap
        return []

    query = f"""
    [out:json][timeout:12];
    (
      way["highway"~"^(motorway|trunk|motorway_link|trunk_link)$"]({s},{w},{n},{e});
      way["highway"]["foot"="no"]({s},{w},{n},{e});
      way["highway"~"^(footway|path|pedestrian|steps|living_street)$"]({s},{w},{n},{e});
      way["highway"]["foot"="yes"]({s},{w},{n},{e});
      way["highway"]["sidewalk"~"^(both|left|right|yes)$"]({s},{w},{n},{e});
    );
    out geom 400;
    """
    elements = cached_overpass_elements(
        f"ped:{s:.2f},{w:.2f},{n:.2f},{e:.2f}", query, timeout=12.0
    )

    ped_ways: list[list[tuple[float, float]]] = []
    veh_ways: list[tuple[list[tuple[float, float]], dict]] = []
    for el in elements:
        pts = _way_points(el)
        if len(pts) < 2:
            continue
        tags = el.get("tags", {}) or {}
        role = classify_way(tags)
        if role == "pedestrian":
            ped_ways.append(pts)
        elif role == "vehicle_only":
            veh_ways.append((pts, tags))

    if not veh_ways:
        return []

    # Walk the route at foot scale so a short underpass between sparse overview points is caught.
    samples = [(lat, lng) for lat, lng, _ in sample_polyline(points, step_m=60.0)]

    out: list[Hazard] = []
    last: tuple[float, float] | None = None
    for lat, lng in samples:
        # nearest vehicle-only way, keeping its tags for the underpass check
        dv = float("inf")
        dv_tags: dict = {}
        for way_pts, tags in veh_ways:
            d = point_near_polyline_m(lat, lng, way_pts)
            if d < dv:
                dv, dv_tags = d, tags
        if dv > _NEAR_VEHICLE_M:
            continue
        dp = min((point_near_polyline_m(lat, lng, wp) for wp in ped_ways), default=float("inf"))
        if dp <= _FAR_FROM_PED_M:
            continue  # there's a footpath right here — fine to walk

        # Space hazards out so one long stretch isn't reported every 60m.
        if last is not None and haversine_m(lat, lng, last[0], last[1]) < _MIN_GAP_M:
            continue
        last = (lat, lng)

        if _is_underpass(dv_tags):
            out.append(Hazard(
                HazardType.NO_FOOTPATH, Severity.HIGH, lat, lng, "overpass",
                "Vehicle-only underpass — no pedestrian path through. Use the footbridge or "
                "signalled crossing instead of walking through it.",
            ))
        else:
            road = dv_tags.get("name") or "this road"
            out.append(Hazard(
                HazardType.NO_FOOTPATH, Severity.MODERATE, lat, lng, "overpass",
                f"No footpath along {road} here — fast traffic and no pavement. "
                "Walk facing traffic, keep to the edge, or cross to a side that has one.",
            ))
        if len(out) >= max_items:
            break
    return out
