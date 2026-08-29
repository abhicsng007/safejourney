"""Tiny HTTP helper with a hard timeout and graceful failure.

Tools use this so a slow or unreachable feed degrades to a fallback instead of hanging the
monitoring tick.
"""

from __future__ import annotations

from typing import Any, Optional


def get_json(
    url: str,
    params: Optional[dict] = None,
    timeout: float = 6.0,
    headers: Optional[dict] = None,
) -> Optional[Any]:
    try:
        import httpx  # lazy so the package imports even without httpx installed
    except Exception:
        return None
    try:
        hdrs = {"User-Agent": "SafeJourney/0.1"}
        if headers:
            hdrs.update(headers)
        r = httpx.get(url, params=params, timeout=timeout, headers=hdrs)
        if r.status_code == 200:
            return r.json()
        return None
    except Exception:
        return None


def post_json(url: str, json: dict, headers: Optional[dict] = None, timeout: float = 6.0) -> Optional[Any]:
    try:
        import httpx
    except Exception:
        return None
    try:
        r = httpx.post(url, json=json, headers=headers or {}, timeout=timeout)
        if r.status_code in (200, 201):
            return r.json()
        return None
    except Exception:
        return None


# Overpass mirrors, tried in order. The public endpoints throttle aggressively (HTTP 429)
# and time out under load, so we fail over across mirrors instead of silently returning
# nothing — which is what made a chosen route show 0 hazards. One attempt per mirror keeps
# the worst case bounded (mirrors x timeout) so a monitoring tick can't hang.
_OVERPASS_MIRRORS = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.kumi.systems/api/interpreter",
)


# Circuit breaker: when Overpass is throttling this IP (every mirror times out), a single
# corridor scan makes many queries and each burns the full mirror budget — stacking into
# minute-long requests. After a couple of total failures we trip the breaker and skip Overpass
# entirely for a cooldown, so scans stay fast (just without OSM hazards) and recover on their own.
_ov_fail_streak = 0
_ov_disabled_until = 0.0


def overpass_json(query: str, timeout: float = 4.0) -> Optional[Any]:
    """POST an Overpass QL query, failing over across mirrors. Returns parsed JSON or None.

    Logs the failure (status / reason) so a route coming back empty is diagnosable from
    Cloud Logging instead of vanishing silently.
    """
    global _ov_fail_streak, _ov_disabled_until
    import time as _t

    now = _t.time()
    if now < _ov_disabled_until:
        return None  # breaker open — don't call Overpass at all right now
    try:
        import httpx  # lazy so the package imports even without httpx installed
    except Exception:
        return None
    headers = {"User-Agent": "SafeJourney/0.1"}
    # Bound connect separately so an unreachable mirror fails fast (2s) instead of burning the
    # full read budget before failing over.
    tmo = httpx.Timeout(timeout, connect=2.0)
    last = ""
    for url in _OVERPASS_MIRRORS:
        try:
            r = httpx.post(url, data={"data": query}, timeout=tmo, headers=headers)
            if r.status_code == 200:
                _ov_fail_streak = 0
                return r.json()
            last = f"{url} -> HTTP {r.status_code}"
        except Exception as e:  # timeout / connection error — move to the next mirror
            last = f"{url} -> {type(e).__name__}"
    _ov_fail_streak += 1
    if _ov_fail_streak >= 2:
        _ov_disabled_until = now + 120.0  # cool down 2 min before trying Overpass again
        print(f"[overpass] tripping breaker for 120s after {_ov_fail_streak} failures", flush=True)
    print(f"[overpass] all mirrors failed; last={last}", flush=True)
    return None


def get_text(url: str, params: Optional[dict] = None, timeout: float = 6.0) -> Optional[str]:
    try:
        import httpx
    except Exception:
        return None
    try:
        r = httpx.get(url, params=params, timeout=timeout, headers={"User-Agent": "SafeJourney/0.1"})
        return r.text if r.status_code == 200 else None
    except Exception:
        return None
