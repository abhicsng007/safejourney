"""Direct Gemini access (GenAI SDK) for lightweight generation like alert narration.

Kept separate from the ADK fleet so a single quick call doesn't spin up an agent runner.
Returns None on any failure — callers always have a deterministic fallback.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from ..config import get_settings


@lru_cache
def _client():
    s = get_settings()
    if not s.gemini_available:
        return None
    try:
        from google import genai

        if s.use_vertex and s.gcp_project:
            return genai.Client(vertexai=True, project=s.gcp_project, location=s.gcp_location)
        if s.gemini_api_key:
            return genai.Client(api_key=s.gemini_api_key)
    except Exception as e:  # pragma: no cover
        print(f"[llm] genai client init failed ({e})")
    return None


def generate(prompt: str, system: str = "", max_tokens: int = 200) -> Optional[str]:
    client = _client()
    if client is None:
        return None
    s = get_settings()
    try:
        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=0.4,
            **_thinking_off(types),
        )
        resp = client.models.generate_content(model=s.gemini_model, contents=prompt, config=cfg)
        return (resp.text or "").strip() or None
    except Exception as e:  # pragma: no cover
        print(f"[llm] generate failed ({e})")
        return None


_NARRATOR_SYSTEM = (
    "You are SafeJourney, a calm, concise travel-safety companion for riders in India. "
    "Rewrite the given alert in 1-2 short sentences: warm, direct, specific, no jargon, no "
    "emojis. Lead with the action the person should take. Keep it under 240 characters."
)


def narrate_alert(action: str, hazard: dict, mode: str, base_message: str) -> Optional[str]:
    prompt = (
        f"Action: {action}\n"
        f"Traveller mode: {mode}\n"
        f"Hazard: {hazard.get('type')} (severity {hazard.get('severity')}) — {hazard.get('description')}\n"
        f"Draft message: {base_message}\n\n"
        "Rewrite the message following your instructions."
    )
    return generate(prompt, system=_NARRATOR_SYSTEM, max_tokens=120)


def generate_json(prompt: str, system: str = "", max_tokens: int = 512) -> Optional[dict]:
    """Ask Gemini for a single JSON object and parse it. Returns None on any failure so
    callers always fall back to deterministic logic."""
    client = _client()
    if client is None:
        return None
    s = get_settings()
    try:
        from google.genai import types

        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            max_output_tokens=max_tokens,
            temperature=0.2,
            response_mime_type="application/json",
            **_thinking_off(types),
        )
        resp = client.models.generate_content(model=s.gemini_model, contents=prompt, config=cfg)
        raw = (resp.text or "").strip()
        if not raw:
            return None
        return _parse_json_object(raw)
    except Exception as e:  # pragma: no cover
        print(f"[llm] generate_json failed ({e})")
        return None


def _thinking_off(types) -> dict:
    """thinking_config that disables model 'thinking' when the SDK/model supports it.

    gemini-2.5-* are thinking models: with a small max_output_tokens the internal thinking
    tokens consume the whole budget and the actual answer (our JSON) comes back truncated or
    empty. For these extraction tasks we don't need thinking, so cap it to 0 where available.
    Returned as kwargs so it's simply omitted on SDKs/models that don't support it."""
    if hasattr(types, "ThinkingConfig"):
        try:
            return {"thinking_config": types.ThinkingConfig(thinking_budget=0)}
        except Exception:
            return {}
    return {}


def generate_with_search(prompt: str, system: str = "", max_tokens: int = 2048) -> Optional[str]:
    """Generate grounded in live Google Search results (Vertex 'Grounding with Google Search').
    Returns the model's text (which we ask to be JSON) or None on any failure."""
    client = _client()
    if client is None:
        return None
    s = get_settings()
    try:
        from google.genai import types

        search_tool = types.Tool(google_search=types.GoogleSearch())
        cfg = types.GenerateContentConfig(
            system_instruction=system or None,
            tools=[search_tool],
            max_output_tokens=max_tokens,
            temperature=0.2,
            **_thinking_off(types),
        )
        resp = client.models.generate_content(model=s.gemini_model, contents=prompt, config=cfg)
        return (resp.text or "").strip() or None
    except Exception as e:  # pragma: no cover - grounding may be unavailable
        print(f"[llm] grounded search failed ({e})")
        return None


def parse_json_array(raw: str) -> list:
    """Lenient parse of a JSON array from model text (may be fenced or have prose around it)."""
    import json

    t = (raw or "").strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        val = json.loads(t)
        return val if isinstance(val, list) else []
    except Exception:
        i, j = t.find("["), t.rfind("]")
        if 0 <= i < j:
            try:
                val = json.loads(t[i : j + 1])
                if isinstance(val, list):
                    return val
            except Exception:
                pass
        # Fallback: the model emitted the objects comma-separated but forgot the enclosing
        # [ ] (a common grounded-search output). Wrap the {...}..{...} span and parse.
        oi, oj = t.find("{"), t.rfind("}")
        if 0 <= oi <= oj:
            span = t[oi : oj + 1].rstrip().rstrip(",")
            try:
                val = json.loads("[" + span + "]")
                return val if isinstance(val, list) else []
            except Exception:
                return []
        return []


def _parse_json_object(raw: str) -> Optional[dict]:
    import json

    # Strip a ```json fence if the model added one despite the mime type.
    t = raw.strip()
    if t.startswith("```"):
        t = t.strip("`")
        if t.lower().startswith("json"):
            t = t[4:]
    try:
        val = json.loads(t)
        return val if isinstance(val, dict) else None
    except Exception:
        # Last resort: grab the outermost {...}.
        i, j = t.find("{"), t.rfind("}")
        if 0 <= i < j:
            try:
                val = json.loads(t[i : j + 1])
                return val if isinstance(val, dict) else None
            except Exception:
                return None
        return None


_DECISION_SYSTEM = (
    "You are SafeJourney's Hazard Sentinel — the reasoning core that decides how to protect a "
    "traveller in India when new hazards appear on the road ahead. You are given the ground-truth "
    "hazards already detected by trusted sensors (weather, disaster feeds, road data, incident "
    "reports) — never invent or deny a hazard, only reason about what to DO. "
    "Choose exactly one action:\n"
    "- advisory: a real hazard, but they can proceed carefully with precautions.\n"
    "- harbor: not safe to continue now; divert to a nearby safe place and wait.\n"
    "- reroute: a safer alternative path exists; switch to it (ONLY if reroute_available is true).\n"
    "- sos: the traveller may be in immediate danger; prepare to alert contacts / emergency.\n"
    "Weigh the traveller's exposure by mode (a walker or two-wheeler rider is far more exposed to "
    "flood, lightning and live wires than someone in a car). Prefer the least-disruptive action "
    "that keeps them safe. Reply with a JSON object: "
    '{"action": "...", "title": "<=40 chars", "message": "1-2 warm, specific sentences leading '
    'with what to do, <=240 chars", "reason": "one short clause on why this action"}.'
)


@lru_cache
def _gemma_client():
    """A Gemini-API (AI Studio) client for Gemma. Gemma is not a Vertex publisher model for
    generateContent, so it needs the API-key path even when Gemini itself runs on Vertex."""
    s = get_settings()
    if not s.gemma_api_key:
        return None
    try:
        from google import genai

        # Force the Gemini Developer API (generativelanguage), not Vertex — otherwise the
        # global GOOGLE_GENAI_USE_VERTEXAI=true env routes the api_key to aiplatform and 403s.
        return genai.Client(api_key=s.gemma_api_key, vertexai=False)
    except Exception as e:  # pragma: no cover
        print(f"[llm] gemma client init failed ({e})")
        return None


def triage_report_gemma(
    text: str,
    allowed_types: list[str],
    allowed_severities: list[str],
) -> Optional[dict]:
    """Classify a free-text / voice hazard report into the structured hazard schema, using the
    small Gemma model (cheap enough to run on every crowd report at scale — Gemini is reserved
    for the low-volume reasoning). Returns {type, severity, description, confidence} or None.

    Gemma on the Gemini API doesn't accept a system instruction, JSON mime mode, or a thinking
    config, so this call is deliberately self-contained: everything is in the user prompt and
    the JSON is parsed leniently."""
    client = _gemma_client()
    if client is None:
        return None
    s = get_settings()
    prompt = (
        "Classify this road-hazard report from a traveller in India into a fixed schema.\n"
        f"type: exactly one of {allowed_types}\n"
        f"severity: exactly one of {allowed_severities} (danger to a two-wheeler rider/pedestrian now)\n"
        "description: one short factual clause (<=90 chars) restating the hazard incl. any landmark\n"
        "confidence: 0.0-1.0 (how sure of the type). If no real road hazard, type \"other\", confidence <0.4.\n\n"
        f"Report: {text!r}\n\n"
        "Output ONLY a single-line JSON object, no markdown, no explanation, no preamble. Example:\n"
        '{"type":"electrocution","severity":"critical","description":"live wire in floodwater near underpass","confidence":0.9}'
    )
    try:
        from google.genai import types

        # Gemma-4 spends output tokens on internal reasoning before emitting the JSON, so a
        # tight budget returns empty (MAX_TOKENS). 800 leaves ample room for the object.
        cfg = types.GenerateContentConfig(max_output_tokens=800, temperature=0.0)
        resp = client.models.generate_content(model=s.gemma_model, contents=prompt, config=cfg)
        raw = (resp.text or "").strip()
        return _parse_json_object(raw) if raw else None
    except Exception as e:  # pragma: no cover
        print(f"[llm] gemma triage failed ({e})")
        return None


def decide_action_llm(
    hazards: list[dict],
    mode: str,
    reroute_available: bool,
    baseline_action: str,
) -> Optional[dict]:
    """Let Gemini choose the response action + compose the message, grounded on real hazards.
    Returns a dict {action,title,message,reason} or None to fall back to the rule engine."""
    lines = [
        f"- {h.get('type')} (severity {h.get('severity')}): {h.get('description')}"
        for h in hazards
    ]
    prompt = (
        f"Traveller mode: {mode}\n"
        f"reroute_available: {str(reroute_available).lower()}\n"
        f"Rule-engine baseline action (safe floor): {baseline_action}\n"
        "New hazards on the road ahead:\n" + "\n".join(lines) + "\n\n"
        "Decide the single best action and write the alert. Do not choose reroute unless "
        "reroute_available is true. Return only the JSON object."
    )
    return generate_json(prompt, system=_DECISION_SYSTEM, max_tokens=300)
