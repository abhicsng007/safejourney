"""Pre-trip environmental briefing — weather, visibility and air quality along the route.

Two outputs from one set of (keyless) Open-Meteo calls:
  * a compact **summary** for the map's conditions card (what it's like out there right now), and
  * the **hazards** those conditions imply — low-visibility fog and unhealthy air — so they
    flow into the same route scoring / warning path as every other hazard.

Degrades to a neutral "unavailable" summary (and no hazards) when offline, so the UI still
renders and behaviour stays predictable in a no-network demo.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

from safejourney_shared.geo import dedupe_close
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._http import get_json

_FORECAST = "https://api.open-meteo.com/v1/forecast"
_AIR = "https://air-quality-api.open-meteo.com/v1/air-quality"

# WMO weather code → (label, emoji). Ranked lower→higher by how much it should worry a traveller.
_WMO = {
    0: ("Clear", "☀️"),
    1: ("Mainly clear", "🌤️"), 2: ("Partly cloudy", "⛅"), 3: ("Overcast", "☁️"),
    45: ("Fog", "🌫️"), 48: ("Freezing fog", "🌫️"),
    51: ("Light drizzle", "🌦️"), 53: ("Drizzle", "🌦️"), 55: ("Heavy drizzle", "🌦️"),
    56: ("Freezing drizzle", "🌧️"), 57: ("Freezing drizzle", "🌧️"),
    61: ("Light rain", "🌦️"), 63: ("Rain", "🌧️"), 65: ("Heavy rain", "🌧️"),
    66: ("Freezing rain", "🌧️"), 67: ("Freezing rain", "🌧️"),
    71: ("Light snow", "🌨️"), 73: ("Snow", "🌨️"), 75: ("Heavy snow", "❄️"), 77: ("Snow grains", "🌨️"),
    80: ("Rain showers", "🌦️"), 81: ("Rain showers", "🌧️"), 82: ("Violent showers", "⛈️"),
    85: ("Snow showers", "🌨️"), 86: ("Snow showers", "❄️"),
    95: ("Thunderstorm", "⛈️"), 96: ("Thunderstorm + hail", "⛈️"), 99: ("Thunderstorm + hail", "⛈️"),
}

# Higher = surface this one in the summary when the route spans different conditions.
_CODE_RANK = {95: 9, 96: 9, 99: 9, 82: 8, 65: 7, 67: 7, 63: 6, 81: 6, 75: 6, 86: 6,
              48: 6, 45: 5, 55: 5, 57: 5, 61: 4, 80: 4, 73: 4, 53: 3, 51: 3, 71: 3, 77: 3,
              3: 2, 2: 1, 1: 1, 66: 7, 85: 4, 56: 4, 0: 0}


def _weather_meta(code: int) -> tuple[str, str]:
    return _WMO.get(code, ("Unknown", "🌡️"))


def _visibility_level(m: float) -> tuple[str, str]:
    if m >= 5000:
        return "good", "Good"
    if m >= 2000:
        return "moderate", "Moderate"
    if m >= 1000:
        return "poor", "Poor"
    return "poor", "Very poor"


def _aqi_category(us_aqi: float) -> tuple[str, str]:
    """US AQI bands → (level, label). level drives the card colour."""
    if us_aqi <= 50:
        return "good", "Good"
    if us_aqi <= 100:
        return "moderate", "Moderate"
    if us_aqi <= 150:
        return "poor", "Unhealthy (sensitive)"
    if us_aqi <= 200:
        return "poor", "Unhealthy"
    if us_aqi <= 300:
        return "bad", "Very unhealthy"
    return "bad", "Hazardous"


def _fetch_forecast(lat: float, lng: float) -> dict | None:
    return get_json(
        _FORECAST,
        params={
            "latitude": round(lat, 4),
            "longitude": round(lng, 4),
            "current": "temperature_2m,relative_humidity_2m,precipitation,weather_code,wind_gusts_10m",
            "hourly": "visibility",
            "forecast_days": 1,
        },
    )


def _fetch_air(lat: float, lng: float) -> dict | None:
    return get_json(
        _AIR,
        params={"latitude": round(lat, 4), "longitude": round(lng, 4), "current": "us_aqi,pm2_5"},
    )


def _current_visibility_m(fc: dict) -> float | None:
    """Visibility over the journey window: the worst of the current + next 2 forecast hours."""
    hourly = fc.get("hourly") or {}
    times = hourly.get("time") or []
    vis = hourly.get("visibility") or []
    if not times or not vis:
        return None
    now_t = (fc.get("current") or {}).get("time")
    idx = times.index(now_t) if now_t in times else 0
    window = [v for v in vis[idx: idx + 3] if v is not None]
    return min(window) if window else None


def _fog_hazard(lat: float, lng: float, vis_m: float) -> Hazard | None:
    if vis_m < 1000:
        return Hazard(HazardType.FOG, Severity.HIGH, lat, lng, "open-meteo",
                      f"Dense fog — visibility under {vis_m/1000:.1f} km. Use fog lights, slow right down.")
    if vis_m < 2500:
        return Hazard(HazardType.FOG, Severity.MODERATE, lat, lng, "open-meteo",
                      f"Low visibility ({vis_m/1000:.1f} km) — mist/haze, keep extra distance.")
    return None


def _air_hazard(lat: float, lng: float, us_aqi: float, pm25: float) -> Hazard | None:
    if us_aqi >= 201:
        return Hazard(HazardType.AIR_QUALITY, Severity.HIGH, lat, lng, "open-meteo",
                      f"Very unhealthy air (AQI {us_aqi:.0f}, PM2.5 {pm25:.0f}) — mask up, limit exposure.")
    if us_aqi >= 151:
        return Hazard(HazardType.AIR_QUALITY, Severity.MODERATE, lat, lng, "open-meteo",
                      f"Unhealthy air (AQI {us_aqi:.0f}) — wear an N95, avoid heavy exertion outdoors.")
    return None


def _unavailable() -> dict:
    return {
        "weather": None,
        "visibility": None,
        "aqi": None,
        "source": "unavailable",
    }


def route_conditions(points: list[tuple[float, float]]) -> tuple[dict, list[Hazard]]:
    """Sample the corridor and return (summary, hazards).

    `points` = [(lat, lng), ...]. Summary surfaces the WORST reading along the route (the part
    that should shape the traveller's decision), not a bland average.
    """
    sample = dedupe_close(points, min_gap_m=3000.0)[:5]  # cap external fan-out
    if not sample:
        return _unavailable(), []

    with ThreadPoolExecutor(max_workers=min(10, len(sample) * 2)) as pool:
        fc_futs = [pool.submit(_fetch_forecast, la, ln) for la, ln in sample]
        air_futs = [pool.submit(_fetch_air, la, ln) for la, ln in sample]
        forecasts = [f.result() for f in fc_futs]
        airs = [f.result() for f in air_futs]

    hazards: list[Hazard] = []
    worst_code = None            # (rank, code, temp, humidity, wind)
    min_vis: tuple[float, float, float] | None = None   # (vis_m, lat, lng)
    max_aqi: tuple[float, float, float, float] | None = None  # (aqi, pm25, lat, lng)

    for (lat, lng), fc in zip(sample, forecasts):
        if not fc or "current" not in fc:
            continue
        cur = fc["current"]
        code = int(cur.get("weather_code", 0) or 0)
        rank = _CODE_RANK.get(code, 0)
        if worst_code is None or rank > worst_code[0]:
            worst_code = (rank, code,
                          float(cur.get("temperature_2m", 0) or 0),
                          float(cur.get("relative_humidity_2m", 0) or 0),
                          float(cur.get("wind_gusts_10m", 0) or 0))
        vis = _current_visibility_m(fc)
        if vis is not None:
            if min_vis is None or vis < min_vis[0]:
                min_vis = (vis, lat, lng)
            hz = _fog_hazard(lat, lng, vis)
            if hz:
                hazards.append(hz)

    for (lat, lng), air in zip(sample, airs):
        if not air or "current" not in air:
            continue
        acur = air["current"]
        aqi = acur.get("us_aqi")
        if aqi is None:
            continue
        aqi = float(aqi)
        pm25 = float(acur.get("pm2_5", 0) or 0)
        if max_aqi is None or aqi > max_aqi[0]:
            max_aqi = (aqi, pm25, lat, lng)
        hz = _air_hazard(lat, lng, aqi, pm25)
        if hz:
            hazards.append(hz)

    if worst_code is None and min_vis is None and max_aqi is None:
        return _unavailable(), []

    summary: dict = {"source": "open-meteo"}

    if worst_code is not None:
        _, code, temp, hum, wind = worst_code
        label, icon = _weather_meta(code)
        summary["weather"] = {
            "code": code, "label": label, "icon": icon,
            "temp_c": round(temp, 1), "humidity": round(hum),
            "wind_kmh": round(wind), "gusty": wind >= 40,
        }
    else:
        summary["weather"] = None

    if min_vis is not None:
        vis_m = min_vis[0]
        level, vlabel = _visibility_level(vis_m)
        summary["visibility"] = {"m": round(vis_m), "km": round(vis_m / 1000, 1),
                                 "level": level, "label": vlabel}
    else:
        summary["visibility"] = None

    if max_aqi is not None:
        aqi, pm25, _, _ = max_aqi
        level, alabel = _aqi_category(aqi)
        summary["aqi"] = {"us_aqi": round(aqi), "pm2_5": round(pm25, 1),
                          "level": level, "category": alabel}
    else:
        summary["aqi"] = None

    return summary, hazards
