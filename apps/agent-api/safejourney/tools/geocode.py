"""Place search + reverse geocoding for the location pickers.

Server-side proxy so the browser never holds the Maps key and there are no referrer issues.
Uses Google Places (New) when a key is present; falls back to keyless OpenStreetMap
(Nominatim) so search and "locate me" work with zero setup.

Response shape is uniform across both providers:
  search  -> [{label, place_id, lat, lng}]  (lat/lng may be None on the Google path)
  resolve -> {label, lat, lng}              (only needed when a result has no lat/lng)
  reverse -> {label, lat, lng}
"""

from __future__ import annotations

from typing import Optional

from ._http import get_json, post_json
from ..config import get_settings

_AUTOCOMPLETE = "https://places.googleapis.com/v1/places:autocomplete"
_DETAILS = "https://places.googleapis.com/v1/places/"  # + place_id
_NOMINATIM_SEARCH = "https://nominatim.openstreetmap.org/search"
_NOMINATIM_REVERSE = "https://nominatim.openstreetmap.org/reverse"


# ---------- search (type-ahead) ----------
def geocode_search(
    query: str, lat: Optional[float] = None, lng: Optional[float] = None, limit: int = 6
) -> list[dict]:
    query = (query or "").strip()
    if len(query) < 3:
        return []
    s = get_settings()
    if s.maps_api_key:
        out = _google_autocomplete(query, lat, lng, limit, s.maps_api_key)
        if out is not None:
            return out
    return _nominatim_search(query, lat, lng, limit)


def _google_autocomplete(query, lat, lng, limit, key) -> Optional[list[dict]]:
    body: dict = {"input": query}
    if lat is not None and lng is not None:
        body["locationBias"] = {"circle": {"center": {"latitude": lat, "longitude": lng},
                                           "radius": 30000.0}}
    headers = {
        "Content-Type": "application/json",
        "X-Goog-Api-Key": key,
        "X-Goog-FieldMask": "suggestions.placePrediction.placeId,suggestions.placePrediction.text",
    }
    data = post_json(_AUTOCOMPLETE, json=body, headers=headers, timeout=6.0)
    if not isinstance(data, dict):
        return None
    out: list[dict] = []
    for sug in data.get("suggestions", [])[:limit]:
        pred = sug.get("placePrediction") or {}
        pid = pred.get("placeId")
        label = (pred.get("text") or {}).get("text", "")
        if pid and label:
            out.append({"label": label, "place_id": pid, "lat": None, "lng": None})
    return out


def _nominatim_search(query, lat, lng, limit) -> list[dict]:
    params = {"q": query, "format": "jsonv2", "limit": limit, "addressdetails": 0}
    # Light bias toward the map view if we have a point (a ~1° box around it).
    if lat is not None and lng is not None:
        params["viewbox"] = f"{lng-0.6},{lat+0.6},{lng+0.6},{lat-0.6}"
        params["bounded"] = 0
    data = get_json(_NOMINATIM_SEARCH, params=params, timeout=6.0)
    out: list[dict] = []
    for r in data or []:
        try:
            out.append({
                "label": r.get("display_name", ""),
                "place_id": f"osm:{r.get('osm_type','')}:{r.get('osm_id','')}",
                "lat": float(r["lat"]),
                "lng": float(r["lon"]),
            })
        except Exception:
            continue
    return out


# ---------- resolve a Google place_id to coordinates ----------
def geocode_resolve(place_id: str) -> Optional[dict]:
    if not place_id:
        return None
    if place_id.startswith("osm:"):
        return None  # OSM results already carry lat/lng from search
    s = get_settings()
    if not s.maps_api_key:
        return None
    headers = {
        "X-Goog-Api-Key": s.maps_api_key,
        "X-Goog-FieldMask": "location,displayName,formattedAddress",
    }
    data = get_json(_DETAILS + place_id, headers=headers, timeout=6.0)
    if not isinstance(data, dict):
        return None
    loc = data.get("location") or {}
    lat, lng = loc.get("latitude"), loc.get("longitude")
    if lat is None or lng is None:
        return None
    label = data.get("formattedAddress") or (data.get("displayName") or {}).get("text", "")
    return {"label": label, "lat": lat, "lng": lng}


# ---------- reverse geocode (for the GPS "locate me" label) ----------
def reverse_geocode(lat: float, lng: float) -> dict:
    s = get_settings()
    if s.maps_api_key:
        headers = {
            "X-Goog-Api-Key": s.maps_api_key,
            "X-Goog-FieldMask": "places.formattedAddress,places.displayName,places.location",
        }
        body = {
            "maxResultCount": 1,
            "locationRestriction": {
                "circle": {"center": {"latitude": lat, "longitude": lng}, "radius": 50.0}
            },
        }
        data = post_json("https://places.googleapis.com/v1/places:searchNearby",
                         json=body, headers=headers, timeout=6.0)
        places = (data or {}).get("places", []) if isinstance(data, dict) else []
        if places:
            p = places[0]
            label = p.get("formattedAddress") or (p.get("displayName") or {}).get("text", "")
            if label:
                return {"label": label, "lat": lat, "lng": lng}
    # Nominatim reverse (keyless).
    data = get_json(_NOMINATIM_REVERSE, params={"lat": lat, "lon": lng, "format": "jsonv2"}, timeout=6.0)
    label = (data or {}).get("display_name") if isinstance(data, dict) else None
    return {"label": label or f"{lat:.4f}, {lng:.4f}", "lat": lat, "lng": lng}
