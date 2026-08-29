"""Runtime configuration, read from the environment.

Every external dependency is optional: if a key is missing the corresponding tool falls
back to a keyless source or deterministic mock, so the whole system runs locally with an
empty .env. This is what lets you develop and demo offline.
"""

from __future__ import annotations

import os
from functools import lru_cache


def _b(name: str, default: bool = False) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return v.strip().lower() in {"1", "true", "yes", "on"}


class Settings:
    # --- Google Cloud / Gemini ---
    gcp_project: str = os.getenv("GCP_PROJECT", "")
    gcp_location: str = os.getenv("GCP_LOCATION", "us-central1")
    # Use Vertex AI if a project is set; otherwise the Gemini API key path.
    use_vertex: bool = _b("GOOGLE_GENAI_USE_VERTEXAI", bool(os.getenv("GCP_PROJECT")))
    gemini_api_key: str = os.getenv("GOOGLE_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
    gemini_model: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")
    # (Override GEMINI_MODEL only with a model your GCP project can access in its region and
    #  that supports Search grounding — an unavailable id makes grounded calls 404.)
    # Gemma — a small, cheap open model used for the high-volume crowd-report triage (turning
    # free-text/voice hazard reports into the structured hazard schema). Gemini stays reserved
    # for low-volume, high-stakes reasoning; Gemma absorbs the classification firehose.
    # Gemma is NOT served as a Vertex publisher model for generateContent, so it's called via
    # the Gemini API (AI Studio) with an API key — independent of the Vertex path Gemini uses.
    gemma_model: str = os.getenv("GEMMA_MODEL", "gemma-4-26b-a4b-it")
    gemma_api_key: str = (
        os.getenv("GEMMA_API_KEY", "")
        or os.getenv("GOOGLE_API_KEY", "")
        or os.getenv("GEMINI_API_KEY", "")
    )

    # --- Text-to-Speech (spoken alerts; second Google model — Chirp/Neural2 voices) ---
    tts_voice: str = os.getenv("TTS_VOICE", "en-IN-Neural2-A")

    # --- Maps Platform ---
    maps_api_key: str = os.getenv("GOOGLE_MAPS_API_KEY", "")

    # --- Firestore ---
    # If empty, an in-memory repository is used (great for local dev/tests).
    firestore_project: str = os.getenv("FIRESTORE_PROJECT", "") or os.getenv("GCP_PROJECT", "")
    use_firestore: bool = _b("USE_FIRESTORE", bool(os.getenv("FIRESTORE_PROJECT") or os.getenv("GCP_PROJECT")))

    # --- Pub/Sub (background monitoring) ---
    pubsub_topic_evaluate: str = os.getenv("PUBSUB_TOPIC_EVALUATE", "trip-evaluate")

    # --- FCM push ---
    fcm_enabled: bool = _b("FCM_ENABLED", False)
    # Public URL of the web PWA — used to deep-link a push back into the app at the trip.
    web_app_url: str = os.getenv("WEB_APP_URL", "")

    # --- Behaviour ---
    corridor_offset_m: float = float(os.getenv("CORRIDOR_OFFSET_M", "350"))
    default_interval_s: int = int(os.getenv("DEFAULT_INTERVAL_S", "180"))
    min_interval_s: int = int(os.getenv("MIN_INTERVAL_S", "45"))
    max_interval_s: int = int(os.getenv("MAX_INTERVAL_S", "900"))
    hazard_cache_ttl_s: int = int(os.getenv("HAZARD_CACHE_TTL_S", "300"))

    @property
    def gemini_available(self) -> bool:
        return bool(self.gemini_api_key) or self.use_vertex

    def summary(self) -> dict:
        return {
            "gemini_model": self.gemini_model,
            "gemma_model": self.gemma_model,
            "gemma_enabled": bool(self.gemma_api_key),
            "tts_voice": self.tts_voice,
            "use_vertex": self.use_vertex,
            "gemini_available": self.gemini_available,
            "maps_key": bool(self.maps_api_key),
            "use_firestore": self.use_firestore,
            "fcm_enabled": self.fcm_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
