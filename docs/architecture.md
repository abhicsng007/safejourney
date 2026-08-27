# SafeJourney — Architecture

## One-paragraph summary

SafeJourney is a **multi-agent, event-driven** system that keeps a traveller safe on the
specific route they are taking. A React PWA plans a trip; the **agent-api** (Google ADK +
Gemini on Cloud Run) pre-detects hazards across candidate routes and returns them
safety-ranked. Once a trip is active, an autonomous loop — **Cloud Scheduler → agent-api
dispatcher → Pub/Sub → monitor-worker** — re-scans the *road ahead* on an adaptive interval,
detects what is **newly** dangerous (change-detection), decides an action with Gemini, writes
an alert to **Firestore**, and pushes it to the phone via **FCM**, even with the app closed.

## System diagram

```
                         ┌──────────────────────────────────────────────┐
                         │  PWA (React + Vite, MapLibre/Google Maps)      │
                         │  plan · safety-ranked routes · live map ·      │
                         │  alert feed · safe harbour · SOS               │
                         └───────┬───────────────────────────▲───────────┘
                 REST / HTTPS    │                           │ FCM push
                                 ▼                           │
        ┌────────────────────────────────────┐   ┌───────────┴───────────────────────┐
        │  agent-api  (Cloud Run)             │   │  monitor-worker (Cloud Run)        │
        │  ─ Google ADK fleet (Gemini 3.5+)   │   │  ─ shares safejourney engine       │
        │    Guardian Core → Prep, Route      │   │  ─ /pubsub/push → evaluate_trip()  │
        │    Guardian, Safe Harbor, Mobility, │   │    (Hazard Sentinel + Decision)    │
        │    SOS                               │   └───────▲─────────────────┬─────────┘
        │  ─ /plan /trips /monitor/dispatch    │           │ Pub/Sub push     │ read/write
        │  ─ tools: weather, disaster, road-   │           │ (per trip)       │
        │    work, incident, route, places,    │           │                  ▼
        │    notify, hazard_scan               │──────┐    │        ┌───────────────────┐
        └───────────────┬─────────────────────┘  fan │    │        │     Firestore     │
                        │ read/write                 │out │        │  users · trips ·  │
                        ▼                             ▼    │        │  snapshots ·      │
        ┌───────────────────────────────┐   ┌──────────────────┐   │  alerts ·         │
        │          Firestore            │   │   Pub/Sub topic   │   │  incidents ·      │
        │  (state + hazard cache)       │   │   trip-evaluate   │   │  hazardCache      │
        └───────────────────────────────┘   └────────▲─────────┘   └───────────────────┘
                        ▲                             │ publish 1 msg / due trip
                        │ query due trips             │
                        │                    ┌────────┴─────────┐
                        └────────────────────│ Cloud Scheduler  │  every 2 min heartbeat
                                             └──────────────────┘
```

## The agent fleet (Google ADK)

| Agent | Role | Key tools |
|---|---|---|
| **Guardian Core** | Root orchestrator; delegates, holds memory, decides when to speak | all |
| **Prep** | Pre-trip go/no-go, timing, checklist | `plan_safe_routes`, `get_precautions` |
| **Route Guardian** | Safety-rank routes, pick safest viable | `plan_safe_routes`, `scan_route_hazards` |
| **Hazard Sentinel** | Background per-tick corridor scan (in worker) | `scan_corridor` (all hazard tools) |
| **Safe Harbor** | Nearest vetted refuge | `get_safe_harbors` (Places) |
| **Mobility** | Transit/cab alternatives when the plan breaks | `get_safe_harbors`, transit |
| **SOS** | Escalation, contacts, 112, first-response guidance | `get_safe_harbors` |
| **Decision** (in tick) | hazards + profile → action + rationale (Gemini) | — |

## Hazard sources (ADK tools)

| Tool | Detects | Source |
|---|---|---|
| `weather` | flood, waterlogging, lightning, storm, heat | Open-Meteo (keyless) / Google Weather |
| `disaster` | active floods/cyclones/quakes, **GLOF/landslide cascade** | GDACS + curated GLOF basins |
| `roadwork` | construction / diversions | OSM Overpass |
| `incident` | broken road, open manhole, **electrocution**, accident, waterlogging | Firestore crowd/official reports |
| `route` | candidate routes + alternatives | Google Directions (fallback: synthetic) |
| `places` | safe harbours | Google Places (fallback: synthetic) |

## Key data flow: one monitoring tick

1. **Cloud Scheduler** (every 2 min) → `POST /monitor/dispatch`.
2. Dispatcher queries Firestore: `trips where status==active and next_check_at<=now`.
3. For each due trip → publish `{trip_id}` to Pub/Sub `trip-evaluate` (fan-out).
4. **monitor-worker** receives the push → `evaluate_trip(trip_id)`:
   - trim route to the **remaining** path ahead of current position;
   - `scan_corridor` fans out across hazard tools in parallel;
   - compute `SafetyScore`, persist a **snapshot**;
   - **change-detect** vs last tick's hazard keys → only *new/escalated* hazards;
   - `decide()` (Gemini) → silent / advisory / reroute / harbour / SOS;
   - on reroute, switch the trip to a safer route; write **alert**; **FCM push**;
   - set `next_check_at` **adaptively** (45s near critical … 15 min when clear).

## Why this scores the rubric

- **Innovation & Utility (40%)** — autonomous, background, multi-step; acts on the physical
  hazard on the user's next stretch of road; grounded in real fatality data.
- **Architecture (30%)** — decoupled event-driven loop, single shared engine, clean tool/
  agent separation, state in Firestore, change-detection, adaptive scheduling, graceful
  degradation everywhere.
- **Demo & Production-readiness (30%)** — deploys to Cloud Run (scale-to-zero), reproducible
  scripts, deterministic `force-hazard` demo hook for unedited live execution, Cloud console
  visibility (Scheduler runs, Pub/Sub delivery, Cloud Run logs, Firestore docs).

## Local ↔ Cloud parity

Every external dependency degrades gracefully: Open-Meteo needs no key; Maps/Gemini/Firestore
fall back to synthetic routes / rule-based decisions / in-memory storage. So the *exact same
code* runs offline for development and, with env vars set, on Google Cloud for the submission.
