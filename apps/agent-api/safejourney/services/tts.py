"""Google Cloud Text-to-Speech — a natural neural voice for the Guardian's spoken alerts.

This is the premium tier behind the browser's on-device speech: when it's available the alert
is narrated by a Chirp/Neural2 voice; on any failure the caller falls back to the browser voice,
so narration never breaks (and works offline).
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from ..config import get_settings


@lru_cache
def _client():
    try:
        from google.cloud import texttospeech

        return texttospeech.TextToSpeechClient()
    except Exception as e:  # pragma: no cover - library or creds missing
        print(f"[tts] client unavailable ({e})")
        return None


def tts_available() -> bool:
    return _client() is not None


def synthesize(text: str) -> Optional[bytes]:
    """Return MP3 audio bytes for `text`, or None to fall back to the browser voice."""
    text = (text or "").strip()
    if not text:
        return None
    client = _client()
    if client is None:
        return None
    s = get_settings()
    try:
        from google.cloud import texttospeech

        # Derive the language code from the voice name (e.g. "en-IN-Neural2-A" -> "en-IN").
        lang = "-".join(s.tts_voice.split("-")[:2]) or "en-IN"
        resp = client.synthesize_speech(
            input=texttospeech.SynthesisInput(text=text[:600]),
            voice=texttospeech.VoiceSelectionParams(language_code=lang, name=s.tts_voice),
            audio_config=texttospeech.AudioConfig(
                audio_encoding=texttospeech.AudioEncoding.MP3,
                speaking_rate=1.0,
            ),
        )
        return resp.audio_content or None
    except Exception as e:  # pragma: no cover
        print(f"[tts] synthesize failed ({e})")
        return None
