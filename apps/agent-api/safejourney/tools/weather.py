"""Weather hazards from Open-Meteo (keyless, real) with a deterministic offline fallback.

Turns raw forecast at points along the route into typed hazards: flood/waterlogging from
heavy rain, lightning from thunderstorm codes, storm from wind, heat from temperature.
"""

from __future__ import annotations

from safejourney_shared.geo import dedupe_close, geohash_encode
from safejourney_shared.hazards import Hazard, HazardType, Severity

from ._http import get_json

_OPEN_METEO = "https://api.open-meteo.com/v1/forecast"

# WMO weather codes → interpretation.
_THUNDER = {95, 96, 99}
_HEAVY_RAIN = {65, 67, 82}
_MODERATE_RAIN = {63, 81, 80}


def _rain_to_hazards(lat: float, lng: float, precip_mm: float, code: int) -> list[Hazard]:
    hz: list[Hazard] = []
    if code in _THUNDER:
        hz.append(Hazard(HazardType.LIGHTNING, Severity.HIGH, lat, lng, "open-meteo",
                         "Thunderstorm cell — lightning risk in the open."))
    if precip_mm >= 10 or code in _HEAVY_RAIN:
        hz.append(Hazard(HazardType.FLOOD, Severity.HIGH, lat, lng, "open-meteo",
                         f"Heavy rain ({precip_mm:.0f} mm/h) — waterlogging and flooded underpass risk."))
    elif precip_mm >= 4 or code in _MODERATE_RAIN:
        hz.append(Hazard(HazardType.WATERLOGGING, Severity.MODERATE, lat, lng, "open-meteo",
                         f"Moderate rain ({precip_mm:.0f} mm/h) — reduced visibility, slick roads."))
    return hz


def _temp_to_hazards(lat: float, lng: float, temp_c: float) -> list[Hazard]:
    if temp_c >= 44:
        return [Hazard(HazardType.HEAT, Severity.HIGH, lat, lng, "open-meteo",
                       f"Extreme heat ({temp_c:.0f}°C) — heatstroke risk for exposed travel.")]
    if temp_c >= 40:
        return [Hazard(HazardType.HEAT, Severity.MODERATE, lat, lng, "open-meteo",
                       f"High heat ({temp_c:.0f}°C) — hydrate, avoid midday exposure.")]
    return []


def _wind_to_hazards(lat: float, lng: float, gust_kmh: float) -> list[Hazard]:
    if gust_kmh >= 60:
        return [Hazard(HazardType.STORM, Severity.HIGH, lat, lng, "open-meteo",
                       f"Strong wind gusts ({gust_kmh:.0f} km/h) — falling branches/hoardings.")]
    return []


def _fallback(points: list[tuple[float, float]]) -> list[Hazard]:
    """Deterministic offline stand-in: quiet weather (no hazards) so behaviour is predictable.
    Real hazards in offline demos come from the incident/demo-hazard injection path."""
    return []


def _fetch_point(lat: float, lng: float) -> dict | None:
    return get_json(
        _OPEN_METEO,
        params={
            "latitude": round(lat, 4),
            "longitude": round(lng, 4),
            "current": "temperature_2m,precipitation,weather_code,wind_gusts_10m",
        },
    )


def weather_hazards(points: list[tuple[float, float]]) -> list[Hazard]:
    """Sample the corridor and return weather hazards. `points` = [(lat, lng), ...]."""
    from concurrent.futures import ThreadPoolExecutor

    sample = dedupe_close(points, min_gap_m=1500.0)[:8]  # cap API fan-out
    if not sample:
        return []
    # Fetch all sample points concurrently — a serial loop here was the main source of the
    # multi-second plan latency (8 points x per-route x per-candidate).
    with ThreadPoolExecutor(max_workers=len(sample)) as pool:
        results = list(pool.map(lambda p: _fetch_point(p[0], p[1]), sample))

    out: list[Hazard] = []
    any_live = False
    for (lat, lng), data in zip(sample, results):
        if not data or "current" not in data:
            continue
        any_live = True
        cur = data["current"]
        precip = float(cur.get("precipitation", 0) or 0)
        code = int(cur.get("weather_code", 0) or 0)
        temp = float(cur.get("temperature_2m", 25) or 25)
        gust = float(cur.get("wind_gusts_10m", 0) or 0)
        out += _rain_to_hazards(lat, lng, precip, code)
        out += _temp_to_hazards(lat, lng, temp)
        out += _wind_to_hazards(lat, lng, gust)
    if not any_live:
        return _fallback(sample)
    return out
