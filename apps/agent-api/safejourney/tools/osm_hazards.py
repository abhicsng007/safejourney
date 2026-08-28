"""Extra road hazards from OpenStreetMap (Overpass, keyless): unmanned railway crossings,
explicit `hazard=*` tags (curves, dips, falling rocks, flood-prone, …) and speed breakers.

Real crowd-maintained map data — the same source as construction — so it adds genuine
variety on the map without inventing anything.
"""

from __future__ import annotations

from safejourney_shared.geo import haversine_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._http import get_json

_OVERPASS = "https://overpass-api.de/api/interpreter"

# OSM hazard=<value> -> (our type, severity, label)
_HAZARD_TAG = {
    "curve": (HazardType.SHARP_TURN, Severity.LOW, "Sharp curve"),
    "hairpin": (HazardType.SHARP_TURN, Severity.MODERATE, "Hairpin bend"),
    "dip": (HazardType.POTHOLE, Severity.LOW, "Road dip"),
    "bump": (HazardType.POTHOLE, Severity.LOW, "Bump in road"),
    "pothole": (HazardType.POTHOLE, Severity.MODERATE, "Pothole"),
    "falling_rocks": (HazardType.LANDSLIDE, Severity.MODERATE, "Falling rocks"),
    "rockfall": (HazardType.LANDSLIDE, Severity.MODERATE, "Rockfall"),
    "landslide": (HazardType.LANDSLIDE, Severity.HIGH, "Landslide-prone"),
    "flood_prone": (HazardType.FLOOD, Severity.MODERATE, "Flood-prone stretch"),
    "slippery": (HazardType.OTHER, Severity.LOW, "Slippery road"),
    "ice": (HazardType.OTHER, Severity.MODERATE, "Icy road"),
    "steep_incline": (HazardType.OTHER, Severity.LOW, "Steep incline"),
    "animal_crossing": (HazardType.OTHER, Severity.LOW, "Animal crossing"),
    "children": (HazardType.OTHER, Severity.LOW, "School zone / children"),
}


def _bbox(points, pad_deg: float = 0.01):
    lats = [p[0] for p in points]
    lngs = [p[1] for p in points]
    return (min(lats) - pad_deg, min(lngs) - pad_deg, max(lats) + pad_deg, max(lngs) + pad_deg)


def _hazard_from_element(el: dict) -> Hazard | None:
    lat = el.get("lat") or el.get("center", {}).get("lat")
    lng = el.get("lon") or el.get("center", {}).get("lon")
    if lat is None or lng is None:
        return None
    tags = el.get("tags", {}) or {}

    if tags.get("railway") in ("level_crossing", "crossing"):
        supervised = tags.get("supervised", "")
        sev = Severity.MODERATE if supervised != "yes" else Severity.LOW
        note = "Unmanned railway crossing" if supervised != "yes" else "Railway crossing"
        return Hazard(HazardType.RAIL_CROSSING, sev, lat, lng, "overpass",
                      f"{note} — stop, look both ways, cross only when clearly safe.")

    if "hazard" in tags:
        htype, sev, label = _HAZARD_TAG.get(
            tags["hazard"], (HazardType.OTHER, Severity.LOW, tags["hazard"].replace("_", " ").title()))
        return Hazard(htype, sev, lat, lng, "overpass", f"{label} ahead — proceed with care.")

    if "traffic_calming" in tags:
        return Hazard(HazardType.POTHOLE, Severity.LOW, lat, lng, "overpass",
                      "Speed breaker — slow down before it.")
    return None


def osm_hazards(points: list[tuple[float, float]], max_items: int = 20) -> list[Hazard]:
    if not points:
        return []
    s, w, n, e = _bbox(points)
    if (n - s) * (e - w) > 0.5:  # keep the query cheap
        return []
    query = f"""
    [out:json][timeout:8];
    (
      node["railway"="level_crossing"]({s},{w},{n},{e});
      node["railway"="crossing"]["crossing"!="pedestrian"]({s},{w},{n},{e});
      node["hazard"]({s},{w},{n},{e});
      way["hazard"]({s},{w},{n},{e});
      node["traffic_calming"]({s},{w},{n},{e});
    );
    out center {max_items};
    """
    data = get_json(_OVERPASS, params={"data": query}, timeout=9.0)
    elements = (data or {}).get("elements", []) if isinstance(data, dict) else []
    out: list[Hazard] = []
    for el in elements[:max_items]:
        h = _hazard_from_element(el)
        if not h:
            continue
        # Only if actually near the route line (bbox is coarse).
        if min(haversine_m(h.lat, h.lng, p[0], p[1]) for p in points) > 300:
            continue
        out.append(h)
    return out
