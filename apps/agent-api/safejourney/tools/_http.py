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
