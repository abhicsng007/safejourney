"""Safe-harbour discovery — nearest places a traveller can safely wait out a hazard.

Google Places Nearby Search (New) when a key is present; a small synthetic fallback set
otherwise so the flow demos offline.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from safejourney_shared.geo import haversine_m, sample_polyline

from ._http import post_json
from ..config import get_settings

_PLACES_NEARBY = "https://places.googleapis.com/v1/places:searchNearby"
_PLACES_TEXT = "https://places.googleapis.com/v1/places:searchText"


def find_places_text(query: str, lat: float, lng: float, radius_m: int = 2500, limit: int = 6) -> list[dict]:
    """Free-text place search near a point — 'drinking water', 'food', 'ATM', 'pharmacy',
    'restroom', 'tea'… Returns the closest matches with name, distance and address. Keyless
    fallback returns [] (the caller words a graceful 'couldn't search' reply)."""
    s = get_settings()
    q = (query or "").strip()
    if not q or not s.maps_api_key:
        return []
    body = {
        "textQuery": q,
        "locationBias": {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}
        },
        "maxResultCount": limit,
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": s.maps_api_key,
        "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType,places.formattedAddress",
    }
    data = post_json(_PLACES_TEXT, json=body, headers=headers, timeout=8.0)
    places = (data or {}).get("places", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for p in places:
        loc = p.get("location", {})
        plat, plng = loc.get("latitude"), loc.get("longitude")
        if plat is None:
            continue
        out.append({
            "name": p.get("displayName", {}).get("text", q.title()),
            "type": p.get("primaryType", ""),
            "lat": plat,
            "lng": plng,
            "distance_m": round(haversine_m(lat, lng, plat, plng)),
            "address": p.get("formattedAddress", ""),
        })
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit]

# Ranked by how good a refuge each is (staffed, sheltered, lit, open late).
_HARBOR_TYPES = [
    "hospital", "police", "subway_station", "train_station",
    "gas_station", "shopping_mall", "convenience_store",
]

_LABEL = {
    "hospital": "Hospital",
    "police": "Police station",
    "subway_station": "Metro station",
    "train_station": "Station",
    "gas_station": "Fuel station (staffed, lit)",
    "shopping_mall": "Mall (sheltered, open)",
    "convenience_store": "Open store",
}


def _fallback(lat: float, lng: float) -> list[dict]:
    # A couple of nearby synthetic harbours around the point.
    return [
        {"name": "Metro Station", "type": "subway_station", "lat": lat + 0.003, "lng": lng + 0.001,
         "distance_m": round(haversine_m(lat, lng, lat + 0.003, lng + 0.001)),
         "label": "Metro station", "why": "Covered, lit, staffed — safe from lightning and rain."},
        {"name": "City Hospital", "type": "hospital", "lat": lat - 0.004, "lng": lng + 0.002,
         "distance_m": round(haversine_m(lat, lng, lat - 0.004, lng + 0.002)),
         "label": "Hospital", "why": "24x7, medical help on site."},
        {"name": "24h Store", "type": "convenience_store", "lat": lat + 0.001, "lng": lng - 0.003,
         "distance_m": round(haversine_m(lat, lng, lat + 0.001, lng - 0.003)),
         "label": "Open store", "why": "Sheltered, open, people around."},
    ]


_STATION_TYPES = {"subway_station", "train_station", "transit_station", "bus_station", "light_rail_station"}


def _synthetic_station(lat: float, lng: float) -> dict:
    """A station a short walk away so the transit flow demos offline / on empty results."""
    slat, slng = lat + 0.004, lng + 0.0025
    return {"name": "Nearest Metro", "type": "subway_station", "lat": slat, "lng": slng,
            "distance_m": round(haversine_m(lat, lng, slat, slng)),
            "label": "Metro station", "why": "Board here for the transit leg."}


def nearest_station(lat: float, lng: float) -> dict | None:
    """The closest boardable station to a point — the target of the home→station first leg."""
    s = get_settings()
    if not s.maps_api_key:
        return _synthetic_station(lat, lng)
    body = {
        "includedTypes": list(_STATION_TYPES),
        "maxResultCount": 1,
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 2500.0}
        },
        "rankPreference": "DISTANCE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": s.maps_api_key,
        "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType",
    }
    data = post_json(_PLACES_NEARBY, json=body, headers=headers, timeout=8.0)
    places = (data or {}).get("places", []) if isinstance(data, dict) else []
    if not places:
        return _synthetic_station(lat, lng)
    p = places[0]
    loc = p.get("location", {})
    plat, plng = loc.get("latitude"), loc.get("longitude")
    if plat is None:
        return None
    return {
        "name": p.get("displayName", {}).get("text", "Station"),
        "type": p.get("primaryType", "transit_station"),
        "lat": plat, "lng": plng,
        "distance_m": round(haversine_m(lat, lng, plat, plng)),
        "label": _LABEL.get(p.get("primaryType", ""), "Station"),
        "why": "Board here for the transit leg.",
    }


# Essential-supply stops for a journey (before or mid-trip).
_ESSENTIAL_TYPES = ["pharmacy", "gas_station", "atm", "convenience_store", "supermarket"]
_ESSENTIAL_LABEL = {
    "pharmacy": ("Pharmacy", "💊", "Medicines, first-aid, water."),
    "gas_station": ("Fuel / charge", "⛽", "Fuel, air, restroom, snacks."),
    "atm": ("ATM", "🏧", "Cash for cabs/tolls."),
    "convenience_store": ("Store", "🛒", "Water, snacks, rain cover."),
    "supermarket": ("Supermarket", "🛒", "Supplies for the journey."),
}


def _essentials_fallback(lat: float, lng: float) -> list[dict]:
    seed = [
        ("pharmacy", 0.002, -0.001),
        ("gas_station", -0.003, 0.002),
        ("convenience_store", 0.001, 0.003),
        ("atm", 0.0015, -0.0025),
    ]
    out = []
    for t, dlat, dlng in seed:
        label, icon, why = _ESSENTIAL_LABEL[t]
        out.append({"name": label, "type": t, "lat": lat + dlat, "lng": lng + dlng,
                    "distance_m": round(haversine_m(lat, lng, lat + dlat, lng + dlng)),
                    "label": label, "icon": icon, "why": why})
    return out


def find_essentials(lat: float, lng: float, radius_m: int = 1500, limit: int = 6) -> list[dict]:
    """Nearby places to pick up journey essentials — pharmacy, fuel, ATM, water/snacks."""
    s = get_settings()
    if not s.maps_api_key:
        return _essentials_fallback(lat, lng)[:limit]
    body = {
        "includedTypes": _ESSENTIAL_TYPES,
        "maxResultCount": limit,
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}
        },
        "rankPreference": "DISTANCE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": s.maps_api_key,
        "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType",
    }
    data = post_json(_PLACES_NEARBY, json=body, headers=headers, timeout=8.0)
    places = (data or {}).get("places", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for p in places:
        loc = p.get("location", {})
        plat, plng = loc.get("latitude"), loc.get("longitude")
        if plat is None:
            continue
        ptype = p.get("primaryType", "")
        label, icon, why = _ESSENTIAL_LABEL.get(ptype, ("Shop", "🛒", "Supplies."))
        out.append({
            "name": p.get("displayName", {}).get("text", label),
            "type": ptype, "lat": plat, "lng": plng,
            "distance_m": round(haversine_m(lat, lng, plat, plng)),
            "label": label, "icon": icon, "why": why,
        })
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit] or _essentials_fallback(lat, lng)[:limit]


def find_safe_harbors(lat: float, lng: float, radius_m: int = 1200, limit: int = 4) -> list[dict]:
    s = get_settings()
    if not s.maps_api_key:
        return _fallback(lat, lng)[:limit]

    body = {
        "includedTypes": _HARBOR_TYPES,
        "maxResultCount": limit,
        "locationRestriction": {
            "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": float(radius_m)}
        },
        "rankPreference": "DISTANCE",
    }
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": s.maps_api_key,
        "X-Goog-FieldMask": "places.displayName,places.location,places.primaryType,places.businessStatus",
    }
    data = post_json(_PLACES_NEARBY, json=body, headers=headers, timeout=8.0)
    places = (data or {}).get("places", []) if isinstance(data, dict) else []
    out: list[dict] = []
    for p in places:
        loc = p.get("location", {})
        plat, plng = loc.get("latitude"), loc.get("longitude")
        if plat is None:
            continue
        ptype = p.get("primaryType", "")
        out.append({
            "name": p.get("displayName", {}).get("text", "Safe place"),
            "type": ptype,
            "lat": plat,
            "lng": plng,
            "distance_m": round(haversine_m(lat, lng, plat, plng)),
            "label": _LABEL.get(ptype, "Safe place"),
            "why": "Sheltered, staffed refuge to wait out the hazard.",
        })
    out.sort(key=lambda x: x["distance_m"])
    return out[:limit] or _fallback(lat, lng)[:limit]


# --- route-corridor variants: cover the WHOLE path, not just one point ---

def _sample_route(points: list[tuple[float, float]], step_m: float = 1000.0, max_samples: int = 16):
    """Evenly-spaced query anchors along the route so places are found the whole way.
    Anchors ~1 km apart keep the search circles overlapping through the middle of the route, so a
    place near the path is found wherever it is — not only near the ends."""
    sampled = [(la, ln) for la, ln, _ in sample_polyline(points, step_m=step_m)]
    if len(sampled) <= max_samples:
        return sampled
    idx = [round(i * (len(sampled) - 1) / (max_samples - 1)) for i in range(max_samples)]
    return [sampled[i] for i in idx]


def _dedupe_places(items: list[dict], round_dp: int = 4) -> list[dict]:
    """Merge the overlapping results from adjacent anchors, keeping the closest instance."""
    best: dict[tuple, dict] = {}
    for it in items:
        k = (round(it["lat"], round_dp), round(it["lng"], round_dp))
        if k not in best or it["distance_m"] < best[k]["distance_m"]:
            best[k] = it
    return list(best.values())


def _along_route(points, finder, radius_m, per_point, total_limit, max_off_m) -> list[dict]:
    if not points:
        return []
    anchors = _sample_route(points)
    with ThreadPoolExecutor(max_workers=min(8, len(anchors))) as pool:
        lists = pool.map(lambda p: finder(p[0], p[1], radius_m, per_point), anchors)
    merged = [x for lst in lists for x in (lst or [])]
    # Re-express distance as metres from the route LINE, and how far ALONG the route each place
    # sits (so we can drop anything off-path and keep the rest ordered by position on the route).
    from safejourney_shared.geo import point_near_polyline_m, distance_along_polyline_m

    for x in merged:
        x["distance_m"] = round(point_near_polyline_m(x["lat"], x["lng"], points))
        x["_along"] = distance_along_polyline_m(x["lat"], x["lng"], points)
    # Keep only places genuinely NEAR the path — never show one that's off across town.
    out = [x for x in _dedupe_places(merged) if x["distance_m"] <= max_off_m]
    out.sort(key=lambda x: x["_along"])
    if len(out) <= total_limit:
        return [_strip_along(x) for x in out]
    # More near-path places than we want to plot: thin EVENLY by position along the route so the
    # ones we keep stay spread over the whole journey (dense stretches don't crowd out the rest),
    # without inventing gaps where places actually exist.
    idx = sorted({round(i * (len(out) - 1) / (total_limit - 1)) for i in range(total_limit)})
    return [_strip_along(out[i]) for i in idx]


def _strip_along(x: dict) -> dict:
    x.pop("_along", None)
    return x


def find_safe_harbors_route(
    points, radius_m: int = 1200, per_point: int = 5, total_limit: int = 16, max_off_m: int = 900
) -> list[dict]:
    """Safe harbours near the whole route corridor. A refuge a little off the line is still
    useful (you'd divert to it), so the off-path cutoff is looser than for essentials."""
    return _along_route(points, find_safe_harbors, radius_m, per_point, total_limit, max_off_m)


def find_essentials_route(
    points, radius_m: int = 1000, per_point: int = 6, total_limit: int = 20, max_off_m: int = 450
) -> list[dict]:
    """Journey essentials (pharmacy/fuel/ATM/store) right along the route — kept close to the
    path (you grab these in passing), found the whole way, not only at the ends."""
    return _along_route(points, find_essentials, radius_m, per_point, total_limit, max_off_m)
