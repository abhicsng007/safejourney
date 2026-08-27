"""Safe-harbour discovery — nearest places a traveller can safely wait out a hazard.

Google Places Nearby Search (New) when a key is present; a small synthetic fallback set
otherwise so the flow demos offline.
"""

from __future__ import annotations

from safejourney_shared.geo import haversine_m

from ._http import post_json
from ..config import get_settings

_PLACES_NEARBY = "https://places.googleapis.com/v1/places:searchNearby"

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
