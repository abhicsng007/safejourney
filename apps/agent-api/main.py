"""Uvicorn entrypoint for the SafeJourney agent-api Cloud Run service."""

import os

from safejourney.api import app  # noqa: F401  (imported for uvicorn target `main:app`)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8080")), reload=False)
