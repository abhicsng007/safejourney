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
