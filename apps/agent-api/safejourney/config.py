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
    # (Set GEMINI_MODEL=gemini-3.5-flash or newer for the hackathon submission.)

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
            "use_vertex": self.use_vertex,
            "gemini_available": self.gemini_available,
            "maps_key": bool(self.maps_api_key),
            "use_firestore": self.use_firestore,
            "fcm_enabled": self.fcm_enabled,
        }


@lru_cache
def get_settings() -> Settings:
    return Settings()
