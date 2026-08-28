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
