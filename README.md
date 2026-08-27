# SafeJourney 🧭

**An agentic travel-safety companion that watches the road you're actually on — and acts before the storm, the live wire, the flooded underpass, or the unlit turn becomes the reason you don't get home.**

Built for the **All Things Agentic Hackathon** (Google Cloud · Devpost) — Taskmaster category.

SafeJourney is a **multi-agent system** (Google ADK + Gemini) that:

1. **Pre-detects** hazards the moment you choose a route, and offers a safety-ranked
   alternative or precise precautions instead of just the fastest path.
2. **Autonomously monitors your remaining path in the background** at adaptive intervals —
   construction/road works, recent incidents on that path (broken road, open manhole,
   electrocution), and upstream signals that can cascade into calamity (a glacier-lake /
   landslide blockage upstream of your route, as in Nepal) — and pushes a live alert with a
   reroute, a safe harbour, or step-by-step precautions **even with the app closed**.

---

## Why it matters

The danger in India (and similar geographies) is the *ordinary journey*:

| Hazard | Toll | Source |
|---|---|---|
| Road accidents | ~1.73 lakh deaths/yr (~546/day) | NCRB 2023 |
| Lightning | 2,825 deaths (96% rural) | India 2024 |
| Monsoon floods / cloudbursts / landslides | 2,707 deaths | India 2025 |
| Kolkata cloudburst | 9 of 12 deaths by electrocution (waterlogged live poles) | Sept 2025 |
| Sikkim glacial-lake outburst (GLOF) | 55 dead | Oct 2023 |

Existing apps are reactive SOS buttons or city-wide weather. None *accompany* the traveller
and reason about the hazard on their **next stretch of road**.

---

## Architecture

```
PWA (React+Vite, Google Maps JS, Firebase Auth, FCM push)
        │  REST                                   ▲  FCM push
        ▼                                         │
 agent-api (Cloud Run)          monitor-worker (Cloud Run)
 Google ADK · Gemini 3.5+       Google ADK · Gemini 3.5+
 Guardian Core + agents         Hazard Sentinel + Decision agent
        │                                 ▲            │
        ▼   Firestore (users·trips·snapshots·alerts·incidents·hazardCache)
        │                                 │ Pub/Sub (per-trip)
 Monitor dispatcher ◄── Pub/Sub tick ── Cloud Scheduler (heartbeat)
```

See [`docs/architecture.md`](docs/architecture.md) for the full diagram and data flow.

### Mandatory Google stack (hackathon requirements)
- **Gemini 3.5+** via Vertex AI — reasoning behind every agent.
- **Google ADK** (Python) — the multi-agent framework.
- **Cloud Run + Firestore + Pub/Sub + Cloud Scheduler** — infra + autonomous background loop.
- Plus Google Maps Platform (Directions/Places/Roads/Weather), Firebase Auth/Hosting/FCM.

---

## Repo layout

```
safeJourney/
  apps/
    web/            # React + Vite PWA (Maps JS, Auth, FCM, service worker)
    agent-api/      # FastAPI + Google ADK agents/tools  → Cloud Run
    monitor-worker/ # Pub/Sub-triggered Hazard Sentinel   → Cloud Run
  packages/shared/  # geohash + SafetyScore + hazard schemas (Python)
  infra/            # gcloud/Firestore rules, Scheduler/Pub/Sub setup
  docs/             # architecture + submission assets
```

---

## Quick start (local, no cloud keys required)

The backend runs locally with **graceful fallbacks** — weather uses the keyless
[Open-Meteo](https://open-meteo.com) API, and Google Maps / Gemini calls fall back to
deterministic mock data when their keys are absent, so you can develop the whole flow offline.

```bash
# 1. Agent API
cd apps/agent-api
python -m venv .venv && . .venv/Scripts/activate   # Windows PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
cp .env.example .env                                # fill in keys when you have them
uvicorn app.main:app --reload --port 8080

# 2. Web PWA (separate terminal)
cd apps/web
npm install
npm run dev
```

Then open the printed Vite URL, plan a trip, and start it. To see the **autonomous alert**
fire locally, hit the demo hook:

```bash
curl -X POST http://localhost:8080/demo/force-hazard \
  -H "Content-Type: application/json" \
  -d '{"tripId":"<id>","type":"flood","severity":"critical"}'
curl -X POST http://localhost:8080/monitor/tick        # runs one monitoring cycle
```

See per-app READMEs for cloud deployment (Cloud Run, Firebase, Scheduler/Pub/Sub).

---

## Status

Built in phases (see `docs/architecture.md`). Phase 2 — the autonomous background monitoring
loop — is the demoable core: plan a trip, close the app, get a push when the road ahead turns
dangerous.
