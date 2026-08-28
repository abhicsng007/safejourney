"""Geospatial helpers — no external geo dependency required.

Everything here is pure-Python so it runs identically in the agent-api and the
monitor-worker, and in unit tests, without native libs.
"""

from __future__ import annotations

import math
from typing import Iterable

_EARTH_R = 6_371_000.0  # metres
_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def haversine_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Great-circle distance in metres."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlmb = math.radians(lng2 - lng1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlmb / 2) ** 2
    return 2 * _EARTH_R * math.asin(min(1.0, math.sqrt(a)))


def bearing_deg(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Initial compass bearing from point 1 to point 2, in degrees [0, 360)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lng2 - lng1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360.0) % 360.0


def angle_diff_deg(a: float, b: float) -> float:
    """Smallest absolute difference between two bearings, in [0, 180]."""
    d = abs(a - b) % 360.0
    return d if d <= 180.0 else 360.0 - d


def decode_polyline(encoded: str) -> list[tuple[float, float]]:
    """Decode a Google/Mapbox encoded polyline into [(lat, lng), ...].

    Implements the standard polyline5 algorithm.
    """
    coords: list[tuple[float, float]] = []
    index = lat = lng = 0
    length = len(encoded)
    while index < length:
        for is_lng in (False, True):
            shift = result = 0
            while True:
                b = ord(encoded[index]) - 63
                index += 1
                result |= (b & 0x1F) << shift
                shift += 5
                if b < 0x20:
                    break
            delta = ~(result >> 1) if (result & 1) else (result >> 1)
            if is_lng:
                lng += delta
            else:
                lat += delta
        coords.append((lat / 1e5, lng / 1e5))
    return coords


def encode_polyline(points: list[tuple[float, float]]) -> str:
    """Encode [(lat, lng), ...] into a polyline5 string (inverse of decode_polyline)."""

    def _enc(value: int) -> str:
        value = ~(value << 1) if value < 0 else (value << 1)
        chunks = []
        while value >= 0x20:
            chunks.append((0x20 | (value & 0x1F)) + 63)
            value >>= 5
        chunks.append(value + 63)
        return "".join(chr(c) for c in chunks)

    out = []
    plat = plng = 0
    for lat, lng in points:
        ilat, ilng = round(lat * 1e5), round(lng * 1e5)
        out.append(_enc(ilat - plat))
        out.append(_enc(ilng - plng))
        plat, plng = ilat, ilng
    return "".join(out)


def sample_polyline(
    points: list[tuple[float, float]], step_m: float = 400.0
) -> list[tuple[float, float, float]]:
    """Resample a polyline to roughly even spacing.

    Returns [(lat, lng, distance_along_m), ...]. Used so hazard lookups happen at a
    bounded number of points regardless of how densely the route is encoded.
    """
    if not points:
        return []
    out: list[tuple[float, float, float]] = [(points[0][0], points[0][1], 0.0)]
    dist_along = 0.0
    next_sample = step_m  # cumulative distance of the next point to emit
    for (lat1, lng1), (lat2, lng2) in zip(points, points[1:]):
        seg = haversine_m(lat1, lng1, lat2, lng2)
        if seg == 0:
            continue
        seg_start = dist_along
        # Emit every step_m boundary that falls inside this segment. Tracking the boundary in
        # CUMULATIVE distance (not a per-segment carry) is what makes this work on dense routes
        # whose individual segments are shorter than step_m — the previous carry never reset and
        # so almost no mid-route points were emitted, starving every corridor hazard lookup.
        while next_sample <= dist_along + seg:
            t = (next_sample - seg_start) / seg
            out.append((lat1 + (lat2 - lat1) * t, lng1 + (lng2 - lng1) * t, next_sample))
            next_sample += step_m
        dist_along += seg
    # Always include the final point.
    last = points[-1]
    out.append((last[0], last[1], dist_along))
    return out


def point_near_polyline_m(
    lat: float, lng: float, points: list[tuple[float, float]]
) -> float:
    """Minimum distance in metres from a point to a polyline (segment-aware)."""
    if not points:
        return float("inf")
    best = float("inf")
    for (lat1, lng1), (lat2, lng2) in zip(points, points[1:]):
        best = min(best, _point_seg_dist_m(lat, lng, lat1, lng1, lat2, lng2))
    if len(points) == 1:
        best = haversine_m(lat, lng, points[0][0], points[0][1])
    return best


def distance_along_polyline_m(
    lat: float, lng: float, points: list[tuple[float, float]]
) -> float:
    """How far along the route (metres from its start) the point projects to.

    Finds the segment the point is closest to, then returns the cumulative length up to that
    segment plus the projected distance onto it. Used to tell the traveller a hazard is
    'X metres ahead'.
    """
    if not points or len(points) < 2:
        return 0.0
    best_d = float("inf")
    best_along = 0.0
    cum = 0.0
    for (alat, alng), (blat, blng) in zip(points, points[1:]):
        seg_len = haversine_m(alat, alng, blat, blng)
        d, t = _point_seg_dist_and_t(lat, lng, alat, alng, blat, blng)
        if d < best_d:
            best_d = d
            best_along = cum + t * seg_len
        cum += seg_len
    return best_along


def _point_seg_dist_and_t(
    plat: float, plng: float, alat: float, alng: float, blat: float, blng: float
) -> tuple[float, float]:
    """Distance from P to segment AB and the clamped projection parameter t in [0, 1]."""
    lat0 = math.radians((alat + blat) / 2)
    mx = math.cos(lat0) * (math.pi / 180) * _EARTH_R
    my = (math.pi / 180) * _EARTH_R
    ax, ay = alng * mx, alat * my
    bx, by = blng * mx, blat * my
    px, py = plng * mx, plat * my
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(px - ax, py - ay), 0.0
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy), t


def _point_seg_dist_m(
    plat: float, plng: float, alat: float, alng: float, blat: float, blng: float
) -> float:
    """Distance from P to segment AB, using a local equirectangular projection (fine at
    city scale)."""
    lat0 = math.radians((alat + blat) / 2)
    mx = math.cos(lat0) * (math.pi / 180) * _EARTH_R  # metres per degree lng
    my = (math.pi / 180) * _EARTH_R                    # metres per degree lat
    ax, ay = alng * mx, alat * my
    bx, by = blng * mx, blat * my
    px, py = plng * mx, plat * my
    dx, dy = bx - ax, by - ay
    seg2 = dx * dx + dy * dy
    if seg2 == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg2))
    cx, cy = ax + t * dx, ay + t * dy
    return math.hypot(px - cx, py - cy)


def geohash_encode(lat: float, lng: float, precision: int = 7) -> str:
    """Encode a coordinate to a geohash. precision 7 ≈ 150m cell (good for corridors)."""
    lat_range = [-90.0, 90.0]
    lng_range = [-180.0, 180.0]
    gh: list[str] = []
    bits = 0
    bit = 0
    even = True
    while len(gh) < precision:
        if even:
            mid = (lng_range[0] + lng_range[1]) / 2
            if lng >= mid:
                bits = (bits << 1) | 1
                lng_range[0] = mid
            else:
                bits = bits << 1
                lng_range[1] = mid
        else:
            mid = (lat_range[0] + lat_range[1]) / 2
            if lat >= mid:
                bits = (bits << 1) | 1
                lat_range[0] = mid
            else:
                bits = bits << 1
                lat_range[1] = mid
        even = not even
        bit += 1
        if bit == 5:
            gh.append(_BASE32[bits])
            bit = 0
            bits = 0
    return "".join(gh)


def corridor_geohashes(
    points: list[tuple[float, float]], precision: int = 7, step_m: float = 150.0
) -> list[str]:
    """Set of geohash cells covering the route line — the trip's spatial index.

    Used to (a) query nearby incidents efficiently and (b) key the hazard cache.
    """
    seen: set[str] = set()
    for lat, lng, _ in sample_polyline(points, step_m=step_m):
        seen.add(geohash_encode(lat, lng, precision))
    return sorted(seen)


def dedupe_close(
    coords: Iterable[tuple[float, float]], min_gap_m: float = 250.0
) -> list[tuple[float, float]]:
    """Thin a list of points so no two are closer than min_gap_m — keeps API fan-out small."""
    out: list[tuple[float, float]] = []
    for lat, lng in coords:
        if all(haversine_m(lat, lng, o[0], o[1]) >= min_gap_m for o in out):
            out.append((lat, lng))
    return out
