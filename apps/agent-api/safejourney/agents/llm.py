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
            max_output_tokens=_max_out(s.gemini_model, max_tokens),
            temperature=0.4,
            **_thinking_off(types, s.gemini_model),
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
            max_output_tokens=_max_out(s.gemini_model, max_tokens),
            temperature=0.2,
            response_mime_type="application/json",
            **_thinking_off(types, s.gemini_model),
        )
        resp = client.models.generate_content(model=s.gemini_model, contents=prompt, config=cfg)
        raw = (resp.text or "").strip()
        if not raw:
            return None
        return _parse_json_object(raw)
    except Exception as e:  # pragma: no cover
        print(f"[llm] generate_json failed ({e})")
        return None


def _thinking_off(types, model: str = "") -> dict:
    """thinking_config that keeps 'thinking' from eating the answer, per model family.

    gemini-2.5-* / 1.5-* accept thinking_budget=0 to disable thinking outright (with a small
    max_output_tokens the thinking tokens otherwise consume the whole budget and the answer
    comes back empty). gemini-3.x REJECT budget=0 ("invalid argument") — they always think —
    so there we leave thinking on and instead give the call output headroom (see _max_out)."""
    m = model or ""
    if not hasattr(types, "ThinkingConfig"):
        return {}
    if m.startswith("gemini-2.5") or m.startswith("gemini-1.5"):
        try:
            return {"thinking_config": types.ThinkingConfig(thinking_budget=0)}
        except Exception:
            return {}
    return {}  # 3.x and unknown models: don't cap (budget=0 is invalid on 3.x)


def _max_out(model: str, requested: int) -> int:
    """Output-token budget. 3.x always thinks, and thinking shares the output budget — a tiny
    cap (e.g. 90 for a one-line narration) leaves no room for the actual reply, so give thinking
    models a floor. 2.5-* have thinking disabled above, so their small caps are fine."""
    m = model or ""
    if m.startswith("gemini-2.5") or m.startswith("gemini-1.5"):
        return requested
    return max(requested, 1024)


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
            max_output_tokens=_max_out(s.gemini_model, max_tokens),
            temperature=0.2,
            **_thinking_off(types, s.gemini_model),
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
    # Gemma-4 is a reasoning model: it spends output tokens "thinking" before it emits text, and
    # the more it's asked to produce, the longer it reasons (and the likelier it blows the token
    # budget and returns nothing). So we ask for the MINIMUM — just type + severity from a closed
    # vocabulary — and fill description/confidence ourselves. Keeps it as fast/reliable as it gets.
    prompt = (
        f"Report: {text!r}\n"
        "Classify this road-hazard report from a traveller in India. If it is NOT a real road "
        'hazard, use type "other".\n'
        f'Output ONLY a JSON object: {{"type":"<one of {"|".join(allowed_types)}>",'
        f'"severity":"<one of {"|".join(allowed_severities)}>"}}'
    )
    try:
        from google.genai import types

        cfg = types.GenerateContentConfig(max_output_tokens=768, temperature=0.0)
        resp = client.models.generate_content(model=s.gemma_model, contents=prompt, config=cfg)
        raw = (resp.text or "").strip()
        parsed = _parse_json_object(raw) if raw else None
        if not parsed or not parsed.get("type"):
            return None
        # We supply the description (the reporter's own words) and a fixed high confidence — a
        # returned classification is a confident signal for these short, concrete reports.
        parsed.setdefault("description", text.strip()[:90])
        parsed.setdefault("confidence", 0.9)
        return parsed
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
