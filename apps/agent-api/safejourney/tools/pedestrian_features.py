"""Pedestrian infrastructure along a walking route, from OpenStreetMap (Overpass, keyless).

Where `pedestrian_hazards` flags the *bad* stretches (no footpath), this returns the *good*
crossing points a walker should aim for, so the map can mark them and the directions can name
them: foot-over-bridges, zebra / signalled crossings, and pedestrian underpasses / subways.
"""

from __future__ import annotations

from safejourney_shared.geo import haversine_m, point_near_polyline_m

from ._overpass import cached_overpass_elements

# How far off the route line a feature can sit and still be "on your path".
_NEAR_ROUTE_M = 45.0
# Crossings closer than this belong to the same junction — collapse to one marker.
_CLUSTER_M = 30.0


def _bbox(points, pad_deg: float = 0.006):
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats) - pad_deg, min(lngs) - pad_deg, max(lats) + pad_deg, max(lngs) + pad_deg)


def _crossing_label(tags: dict) -> tuple[str, str]:
    """(label, icon) for a highway=crossing node from its crossing subtype."""
    kind = tags.get("crossing") or tags.get("crossing_ref") or ""
    if kind in ("zebra", "marked", "uncontrolled") or tags.get("crossing_ref") == "zebra":
        return "Zebra crossing", "🦓"
    if kind in ("traffic_signals",) or tags.get("crossing:signals") == "yes":
        return "Signalled crossing", "🚦"
    return "Pedestrian crossing", "🚸"


def classify_feature(el: dict) -> tuple[str, str, str] | None:
    """(type, label, icon) for an OSM element, or None if it's not a pedestrian feature.

    Pure/tag-only so it's unit-testable without the network.
    """
    tags = el.get("tags", {}) or {}
    highway = tags.get("highway", "")

    if el.get("type") == "node" and tags.get("railway") == "subway_entrance":
        return ("underpass", "Metro entrance / subway", "🚇")
    if el.get("type") == "node" and highway == "crossing":
        label, icon = _crossing_label(tags)
        return ("crossing", label, icon)

    # Ways: a footway that bridges or tunnels, or an explicit foot bridge.
    is_footway = highway in ("footway", "path", "steps", "pedestrian")
    if is_footway and tags.get("bridge") == "yes":
        return ("footbridge", "Foot-over-bridge", "🌉")
    if tags.get("man_made") == "bridge" and tags.get("foot") == "yes":
        return ("footbridge", "Foot-over-bridge", "🌉")
    if is_footway and tags.get("tunnel") == "yes":
        return ("underpass", "Pedestrian underpass", "🚇")
    return None


def _el_point(el: dict) -> tuple[float, float] | None:
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lng = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lng is None:
        return None
    return (lat, lng)


def pedestrian_features(points: list[tuple[float, float]], max_items: int = 40) -> list[dict]:
    """Foot-over-bridges, crossings and pedestrian underpasses on the walking corridor."""
    if not points or len(points) < 2:
        return []
    s, w, n, e = _bbox(points)
    if (n - s) * (e - w) > 0.5:  # keep the Overpass query cheap
        return []

    query = f"""
    [out:json][timeout:12];
    (
      node["highway"="crossing"]({s},{w},{n},{e});
      node["railway"="subway_entrance"]({s},{w},{n},{e});
      way["highway"~"^(footway|path|steps|pedestrian)$"]["bridge"="yes"]({s},{w},{n},{e});
      way["man_made"="bridge"]["foot"="yes"]({s},{w},{n},{e});
      way["highway"~"^(footway|path|steps|pedestrian)$"]["tunnel"="yes"]({s},{w},{n},{e});
    );
    out center 300;
    """
    elements = cached_overpass_elements(
        f"pedfeat:{s:.2f},{w:.2f},{n:.2f},{e:.2f}", query, timeout=12.0
    )

    candidates: list[dict] = []
    for el in elements:
        cls = classify_feature(el)
        if not cls:
            continue
        pt = _el_point(el)
        if not pt:
            continue
        # Only features actually on the walker's path.
        if point_near_polyline_m(pt[0], pt[1], points) > _NEAR_ROUTE_M:
            continue
        ftype, label, icon = cls
        name = (el.get("tags", {}) or {}).get("name")
        candidates.append({
            "type": ftype,
            "label": f"{label}{f' · {name}' if name else ''}",
            "icon": icon,
            "lat": pt[0],
            "lng": pt[1],
        })

    # Walking order, then collapse each junction's cluster of crossing nodes into one marker.
    start = points[0]
    candidates.sort(key=lambda f: haversine_m(start[0], start[1], f["lat"], f["lng"]))
    out: list[dict] = []
    for f in candidates:
        if any(haversine_m(f["lat"], f["lng"], k["lat"], k["lng"]) < _CLUSTER_M for k in out):
            continue
        out.append(f)
        if len(out) >= max_items:
            break
    return out
