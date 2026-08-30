# SafeJourney 🧭

**An agentic travel-safety companion that watches the road you're *actually* on — and acts before the storm, the live wire, the flooded underpass, the broken road, or the unlit turn becomes the reason you don't get home.**

Built for the **All Things Agentic Hackathon** (Google Cloud · Devpost).
Powered by **Gemini 3.7 Flash** on Vertex AI + the **Google Agent Development Kit (ADK)**.

🔗 **Live app:** https://safejourney-web-868918244220.us-central1.run.app
🔗 **API:** https://safejourney-api-868918244220.us-central1.run.app

---

## The problem

In India (and similar geographies) the danger isn't the rare catastrophe — it's the **ordinary journey**:

| Hazard | Toll | Source |
|---|---|---|
| Road accidents | ~1.73 lakh deaths/yr (~546/day) | NCRB 2023 |
| Lightning | 2,825 deaths (96% rural) | India 2024 |
| Monsoon floods / cloudbursts / landslides | 2,707 deaths | India 2025 |
| Kolkata cloudburst | 9 of 12 deaths by electrocution (waterlogged live poles) | Sept 2025 |
| Sikkim glacial-lake outburst (GLOF) | 55 dead | Oct 2023 |

Navigation apps optimise for **speed**. Weather apps warn about a **city**. Neither *accompanies* the traveller and reasons about the specific hazard on their **next stretch of road**. SafeJourney does.

---

## What it does

SafeJourney is a **multi-agent system** that guards a journey end to end:

1. **Before you leave** — a pre-trip briefing grounded in live **weather, visibility and air quality (AQI)**, a **go / caution / wait** verdict, and a readiness checklist that reacts to conditions (fog lights, N95 for bad air, crosswind warnings).
2. **When you plan** — it scores every candidate route on **safety, not just speed**, and recommends the safest viable one, explaining *why not the fastest* ("+8 min to route around a recurring accident blackspot").
3. **While you travel** — an **autonomous background loop** re-scans the *road ahead* on an adaptive interval, detects what is **newly** dangerous (change-detection), decides an action with Gemini, and pushes a live alert — a reroute, a safe harbour, or precise precautions — **even with the app closed** (FCM push).
4. **On the road** — turn-by-turn with **spoken hazard narration** (Cloud Text-to-Speech), proximity warnings for hazards *along your path*, nearby **safe harbours** and **essentials** (ATM / pharmacy / fuel / water) spread across the whole route, and a **Guardian chat** that finds you water, food, an ATM or a pharmacy near your current location on request.
5. **Ambient awareness** — the whole UI **tints to the live weather** (storm indigo, smog amber, fog grey…) so risk is felt at a glance.

Every claim is **grounded in real data** — the agents never invent hazards.

---

## Why it's agentic (not a chatbot with an API)

- **A fleet of specialised agents** (Google ADK) that **delegate** to each other — you can watch the hand-off live in the app's reasoning timeline: *Hazard Sentinel → Decision Agent → advisory decided by Gemini.*
- **Autonomous, multi-step, background** behaviour: it keeps working after you close the tab, on an **adaptive schedule** it sets for itself based on how dangerous the road is (45 s near a critical hazard … 15 min when clear).
- **Tool-grounded reasoning**: the agents call real tools (routing, weather, AQI, OSM, crowd reports, disaster feeds, places, web search) and act on the results — reroute, shelter, warn, or stay silent.
- **Change-detection & self-validation**: only *new/escalated* hazards interrupt you; a deterministic rule engine validates (and can veto) the model's decision so a hallucination can never make the route *less* safe.

---

## Google technology used

| Product | Where it's used |
|---|---|
| **Gemini 3.7 Flash** (Vertex AI, `global`) | Reasoning behind every agent — route selection, monitoring decisions, prep verdicts, alert narration, chat |
| **Google Agent Development Kit (ADK)** | The multi-agent fleet, delegation, tool-calling, session memory |
| **Grounding with Google Search** (Gemini) | Web advisories — live, cited road/waterlogging/roadwork reports for the route |
| **Gemma** (`gemma-4-26b-a4b-it`, Gemini API) | Second model — high-volume crowd-report triage (free-text/voice → structured hazard) |
| **Google Cloud Text-to-Speech** (`en-IN-Neural2-A`) | Spoken turn-by-turn + hazard narration (with an on-device browser-speech fallback) |
| **Cloud Run** | Three scale-to-zero services: `agent-api`, `monitor-worker`, `web` |
| **Firestore** | Trips, hazard snapshots, alerts, crowd incidents, hazard cache |
| **Cloud Scheduler + Pub/Sub** | The autonomous monitoring loop (heartbeat → dispatch → per-trip fan-out) |
| **Firebase Cloud Messaging (FCM)** | App-closed push alerts, deep-linking back into the alerting trip |
| **Google Maps Platform** | Directions (routes), Places API New (`searchNearby` + `searchText`), Geocoding |
| **Cloud Build + Artifact Registry** | Container build & deploy |
| **Cloud Logging** | Observability of Scheduler runs, Pub/Sub delivery, agent traces |

*Keyless, non-Google data sources (graceful, honest grounding):* Open-Meteo (weather + air quality + visibility), OpenStreetMap Overpass (roadwork, road-condition tags, rail crossings), GDACS (global disasters), plus a curated GLOF/landslide-basin list and an accident-blackspot DB.

> See [`docs/architecture.md`](docs/architecture.md) for the full system diagram and agentic workflow, and [`docs/DEVPOST.md`](docs/DEVPOST.md) for the project story.

---

## Architecture at a glance

```
        React PWA (Vite · MapLibre + MapTiler · FCM · service worker)
              │  REST/HTTPS                              ▲  FCM push
              ▼                                          │
   ┌───────────────────────────┐            ┌────────────────────────────┐
   │  agent-api  (Cloud Run)    │            │ monitor-worker (Cloud Run) │
   │  Google ADK · Gemini 3.7   │            │ Hazard Sentinel + Decision │
   │  Guardian Core → Prep /    │            │ evaluate_trip() per tick   │
   │  Route Guardian / Safe     │◄── Pub/Sub trip-evaluate (fan-out) ─────┤
   │  Harbor / Mobility / SOS   │            └──────────▲─────────────────┘
   └──────────┬────────────────┘                        │ publish due trips
              │ read/write                     ┌─────────┴─────────┐
              ▼                                 │  Cloud Scheduler  │ heartbeat
        Firestore  ◄───────────────────────────┤  → /monitor/dispatch
   (trips · snapshots · alerts · incidents)     └───────────────────┘
```

---

## Repo layout

```
safeJourney/
  apps/
    web/            # React + Vite PWA (MapLibre + MapTiler, FCM, service worker)
    agent-api/      # FastAPI + Google ADK agents/tools           → Cloud Run
    monitor-worker/ # Pub/Sub-triggered Hazard Sentinel/Decision  → Cloud Run
  packages/shared/  # geo + SafetyScore + hazard schemas (Python)
  infra/            # Cloud Run / Firestore / Scheduler / FCM setup scripts
  docs/             # architecture, Devpost story, setup
```

---

## Quick start (local — no cloud keys required)

The backend runs locally with **graceful fallbacks**: weather/AQI use keyless Open-Meteo; Maps/Gemini/Firestore fall back to deterministic mock data / rule-based decisions / in-memory storage when keys are absent — so the whole flow works offline for development.

```bash
# 1. Agent API
cd apps/agent-api
python -m venv .venv && . .venv/Scripts/activate      # PowerShell: .venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn main:app --reload --port 8080

# 2. Web PWA (separate terminal)
cd apps/web
npm install
npm run dev                                            # open the printed Vite URL
```

Plan a trip → **Find the safest route** → **Start Guardian** → **▶ Simulate the drive (~1 min)** to watch the live guardian narrate turns and warn on hazards. To fire an autonomous alert on cue:

```bash
curl -X POST http://localhost:8080/demo/force-hazard \
  -H "Content-Type: application/json" \
  -d '{"tripId":"<id>","type":"electrocution","severity":"critical"}'
curl -X POST http://localhost:8080/monitor/evaluate \
  -H "Content-Type: application/json" -d '{"trip_id":"<id>"}'
```

---

## Deploy to Google Cloud

```bash
# Builds both backend images and deploys api + monitor (Gemini 3.7-flash on Vertex `global`)
PROJECT_ID=<project> REGION=us-central1 MAPS_KEY=<maps-key> bash infra/deploy.sh

# Deploy the PWA (bakes the API URL + optional Firebase push + MapTiler basemap)
PROJECT_ID=<project> REGION=us-central1 \
  VITE_MAP_STYLE_URL="<maptiler-style-url>" \
  VITE_FIREBASE_*=... bash infra/deploy-web.sh
```

> **Gemini 3.x note:** for this project the Gemini 3.x models are served by **Vertex AI only on the `global` location** (regional endpoints 404 on 3.x). `deploy.sh` sets `GOOGLE_GENAI_USE_VERTEXAI=true` + `GOOGLE_CLOUD_LOCATION=global` accordingly.

---

## Status

Fully deployed on Google Cloud and demoable end to end: plan a trip, close the app, and get a push when the road ahead turns dangerous. Live URL above.
