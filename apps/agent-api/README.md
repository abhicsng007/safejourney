# SafeJourney — agent-api

FastAPI service hosting the Google ADK agent fleet, the hazard tools, and the autonomous
monitoring engine. Deploys to Cloud Run.

## Run locally (no cloud keys needed)

```bash
python -m venv .venv
. .venv/Scripts/activate           # PowerShell: .venv\Scripts\Activate.ps1
pip install ../../packages/shared  # shared domain package
pip install -r requirements.txt    # (or: pip install -e '.[google,dev]')
cp .env.example .env
uvicorn main:app --reload --port 8080
```

With an empty `.env` everything degrades gracefully: weather uses keyless Open-Meteo, routes/
places/decisions use synthetic/rule-based fallbacks, and storage is in-memory.

## Enable the real Google stack (for the hackathon)

Set in `.env`:
- `GCP_PROJECT` + `GOOGLE_GENAI_USE_VERTEXAI=true` (or `GOOGLE_API_KEY=...`), and
  `GEMINI_MODEL=gemini-3.5-flash` (or newer) → Gemini + ADK fleet come alive.
- `USE_FIRESTORE=true` + `FIRESTORE_PROJECT=...` → persistent state.
- `GOOGLE_MAPS_API_KEY=...` → real Directions/Places.
- `FCM_ENABLED=true` → real push.

## Key endpoints

| Method | Path | Purpose |
|---|---|---|
| POST | `/plan` | Safety-ranked routes for an origin/destination (no trip created) |
| POST | `/trips` | Create a trip on the safest route (route pre-detection) |
| POST | `/trips/{id}/start` | Activate autonomous monitoring |
| POST | `/trips/{id}/position` | Update live position |
| GET | `/trips/{id}/alerts` · `/hazards` | Alert feed / latest hazard snapshot |
| POST | `/monitor/dispatch` | **Cloud Scheduler** heartbeat — evaluate all due trips |
| POST | `/monitor/evaluate` | Evaluate one trip (Pub/Sub push or `{trip_id}`) |
| POST | `/demo/force-hazard` | Inject a hazard so the next tick alerts (demo hook) |
| POST | `/agent/chat` | Chat through the Guardian Core (ADK) |

## Run the agent fleet in ADK dev UI

```bash
pip install google-adk
export GOOGLE_API_KEY=...      # or Vertex env
adk web                        # discovers safejourney/agent.py -> root_agent
```

## Tests

```bash
PYTHONPATH="../../packages/shared:." python -m pytest tests/ -v
```
