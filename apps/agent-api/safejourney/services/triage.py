"""Crowd-report triage — turn a free-text / voice hazard report into the structured hazard
schema, so a traveller can just say "there's a live wire in the water under the bridge"
instead of hunting for the right button.

Two tiers, so it degrades gracefully and never breaks a demo:
  1. Gemma (small, cheap Google model) extracts {type, severity, description, confidence}.
     Gemini stays reserved for the high-stakes reasoning; Gemma absorbs the classification
     firehose — the reason SafeJourney runs two models.
  2. A deterministic keyword classifier is the fallback (and validator) when Gemma is
     unavailable or returns something off-schema.
"""

from __future__ import annotations

import re
from typing import Optional

from ..config import get_settings

# The hazard types a traveller can crowd-report (a subset of the full HazardType space —
# weather/geometry hazards come from sensors, not people).
REPORTABLE_TYPES: list[str] = [
    "electrocution", "flood", "waterlogging", "pothole", "accident",
    "roadwork", "landslide", "unsafe_area", "storm", "lightning", "other",
]
SEVERITIES: list[str] = ["info", "low", "moderate", "high", "critical"]

# Default danger level for each type when the classifier doesn't pin one down.
_DEFAULT_SEVERITY: dict[str, str] = {
    "electrocution": "critical",
    "landslide": "critical",
    "flood": "high",
    "accident": "high",
    "storm": "high",
    "lightning": "high",
    "waterlogging": "moderate",
    "pothole": "moderate",
    "unsafe_area": "moderate",
    "roadwork": "low",
    "other": "low",
}

# Keyword → type, in priority order (first match wins). The fallback classifier.
_KEYWORDS: list[tuple[str, str]] = [
    (r"live ?wire|\bwire\b|power ?line|powerline|\bcable\b|electrocut|shock|current|"
     r"\bpole\b|transformer|electric", "electrocution"),
    (r"landslide|rockfall|boulder|slope|mudslide|debris flow", "landslide"),
    (r"underpass|flood|submerg|inundat", "flood"),
    (r"waterlog|standing water|water logging|knee deep|water on the road", "waterlogging"),
    (r"pothole|manhole|open drain|\bpit\b|broken road|crater|caved", "pothole"),
    (r"accident|crash|collision|overturn|\bhit\b|pile ?up", "accident"),
    (r"construction|road ?work|digging|diversion|barricade|excavat", "roadwork"),
    (r"lightning|thunder", "lightning"),
    (r"storm|cyclone|gale|heavy wind|high wind", "storm"),
    (r"unsafe|isolated|\bdark\b|harass|robbery|theft|snatch|eve.?teas", "unsafe_area"),
]

_CRITICAL_CUES = re.compile(r"in (the )?water|standing water|flooded|knee|waist|live", re.I)


def _keyword_triage(text: str) -> dict:
    """Deterministic fallback: classify by keyword, guess a severity. Always returns a dict."""
    t = (text or "").lower()
    for pattern, htype in _KEYWORDS:
        if re.search(pattern, t):
            sev = _DEFAULT_SEVERITY.get(htype, "moderate")
            # A live wire *in water* is the worst case — bump to critical.
            if htype == "electrocution" and _CRITICAL_CUES.search(t):
                sev = "critical"
            return {
                "type": htype,
                "severity": sev,
                "description": (text or "").strip()[:90],
                "confidence": 0.55,
                "source": "keyword",
            }
    return {
        "type": "other",
        "severity": "low",
        "description": (text or "").strip()[:90] or "Unspecified hazard report",
        "confidence": 0.3,
        "source": "keyword",
    }


def _normalize(raw: dict, text: str) -> Optional[dict]:
    """Validate a model's output against the schema. Returns a clean dict or None if unusable."""
    if not isinstance(raw, dict):
        return None
    htype = str(raw.get("type", "")).strip().lower().replace(" ", "_")
    if htype not in REPORTABLE_TYPES:
        return None
    sev = str(raw.get("severity", "")).strip().lower()
    if sev not in SEVERITIES:
        sev = _DEFAULT_SEVERITY.get(htype, "moderate")
    desc = str(raw.get("description", "")).strip()[:90] or (text or "").strip()[:90]
    try:
        conf = float(raw.get("confidence", 0.6))
    except (TypeError, ValueError):
        conf = 0.6
    conf = max(0.0, min(1.0, conf))
    return {"type": htype, "severity": sev, "description": desc,
            "confidence": round(conf, 2), "source": "gemma"}


def triage_report(text: str) -> dict:
    """Classify a free-text hazard report. Tries Gemma, validates it, falls back to keywords.
    Always returns {type, severity, description, confidence, source} — never raises."""
    text = (text or "").strip()
    if not text:
        return {"type": "other", "severity": "low", "description": "",
                "confidence": 0.0, "source": "empty"}

    s = get_settings()
    if s.gemma_api_key:
        try:
            from ..agents.llm import triage_report_gemma

            raw = triage_report_gemma(text, REPORTABLE_TYPES, SEVERITIES)
            clean = _normalize(raw, text) if raw else None
            if clean:
                return clean
        except Exception as e:  # pragma: no cover
            print(f"[triage] gemma path failed ({e}); using keyword fallback.")

    return _keyword_triage(text)
