"""Cached Overpass access — the reliability layer over the public Overpass mirrors.

Two-tier so a chosen route stops flapping between "has hazards" and "0 hazards":
  * FRESH window — within it, serve the cached elements and skip the network entirely
    (keeps us well under Overpass's rate limits when many ticks scan the same corridor).
  * STALE-ON-ERROR — when a live fetch fails on every mirror (429/timeout), fall back to
    the last-known elements instead of returning nothing, for up to STORE_TTL_S.

Real crowd-mapped OSM data throughout — nothing synthetic; caching just makes the one live
source we have survive throttling.
"""

from __future__ import annotations

import time

from ..config import get_settings
from ..repo import get_repo
from ._http import overpass_json

# Road works / potholes / crossings change slowly, so a cached fetch stays valid for hours.
STORE_TTL_S = 6 * 3600


def cached_overpass_elements(cache_key: str, query: str, timeout: float = 6.0) -> list[dict]:
    """Run an Overpass query behind the repo TTL cache. Returns the raw `elements` list."""
    repo = get_repo()
    fresh_s = get_settings().hazard_cache_ttl_s  # short "don't re-fetch" window (default 300s)
    now = time.time()

    cached = repo.cache_get(cache_key)
    if cached and (now - cached.get("ts", 0)) < fresh_s:
        return cached.get("elements", [])  # fresh enough — no network call

    data = overpass_json(query, timeout=timeout)
    if isinstance(data, dict):
        elements = data.get("elements", []) or []
        repo.cache_set(cache_key, {"ts": now, "elements": elements}, STORE_TTL_S)
        return elements

    # Live fetch failed on every mirror — serve the last-known result rather than nothing.
    if cached:
        print(f"[overpass] live fetch failed; serving cached elements for {cache_key}", flush=True)
        return cached.get("elements", [])
    return []
