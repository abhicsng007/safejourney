# SafeJourney — Devpost submission

*Paste the sections below into the Devpost project story. Tagline: “An agentic travel-safety companion that watches the road you’re actually on — and acts before it hurts you.”*

---

## Inspiration

In India, the danger isn't the rare catastrophe — it's the **ordinary journey home**. Every day roughly 546 people die on Indian roads (NCRB 2023). In 2024, lightning killed 2,825 people, 96% of them in the open. During the 2025 monsoon, floods, cloudbursts and landslides killed over 2,700. In a single September 2025 Kolkata cloudburst, **9 of 12 deaths were electrocutions** — live electrical poles standing in waterlogged streets. In 2023, a glacial-lake outburst in Sikkim killed 55 people downstream, hours after the trigger, kilometres away.

We kept noticing the same gap: **navigation apps optimise for speed, and weather apps warn about a whole city — but nothing accompanies the traveller and reasons about the specific hazard on their *next stretch of road.*** The flooded underpass, the live wire, the broken road, the unlit hairpin, the sewage-flooded lane in Burari — the things that actually get people hurt are local, temporary, and route-specific. That felt like exactly the job for an agent: something that watches, reasons, and *acts* on your behalf while you're just trying to get home.

## What it does

SafeJourney is a **multi-agent guardian** for a single journey, end to end:

- **Before you leave**, it gives a pre-trip briefing grounded in live **weather, visibility and air quality (AQI)**, a clear **go / caution / wait** verdict, and a readiness checklist that reacts to the conditions (fog lights for low visibility, an N95 for unhealthy air, a crosswind warning when it's gusty).
- **When you plan a route**, it scores every candidate on **safety, not just speed**, recommends the safest viable one, and shows *why not the fastest* — e.g. "+8 minutes to route around a recurring accident blackspot the fastest path runs straight through."
- **While you travel**, an **autonomous background loop** re-scans the *road ahead* on an interval it sets itself, detects what is **newly** dangerous, decides an action with Gemini, and pushes a live alert — reroute, safe harbour, or precise precautions — **even with the app closed**.
- **On the road**, it delivers turn-by-turn with **spoken hazard narration**, warns about hazards *along your actual path*, marks **safe harbours** and **essentials** (ATM / pharmacy / fuel / water) spread across the whole route, and answers a **Guardian chat** — "where can I get water or food nearby?" — with real places and distances from where you are right now.
- The entire interface **tints to the live weather** — storm indigo, smog amber, fog grey — so risk is something you feel, not something you have to read.

Everything is **grounded in real data**; the agents never invent a hazard.

## How we built it

The system is a **monorepo of three Cloud Run services plus a shared engine**:

- **`agent-api` (FastAPI + Google ADK).** A fleet of specialised agents — **Guardian Core** orchestrates **Prep, Route Guardian, Safe Harbor, Mobility and SOS**, delegating between them and calling grounded tools. Reasoning runs on **Gemini 3.7 Flash** via **Vertex AI**.
- **`monitor-worker` (Cloud Run).** The autonomous loop: **Cloud Scheduler** heartbeats the dispatcher, which queries **Firestore** for due active trips and fans each out over **Pub/Sub**; the worker runs a **Hazard Sentinel** corridor scan on the *remaining* path, change-detects new hazards, and a **Decision Agent** (Gemini) chooses an action that a deterministic rule engine validates. Alerts persist to Firestore and push via **Firebase Cloud Messaging**.
- **`packages/shared`.** A single Python engine — geohashing, the `SafetyScore` model, and typed hazard schemas — used identically by the API and the worker.
- **`web` (React + Vite PWA).** MapLibre + a MapTiler basemap, a live reasoning timeline, the conditions card, the weather-reactive theme, and voice via **Google Cloud Text-to-Speech** with an on-device browser-speech fallback.

Grounding comes from **Gemini's Grounding with Google Search** (live web advisories), **Google Maps Platform** (Directions, Places New, Geocoding), and keyless feeds (Open-Meteo weather/AQI, OpenStreetMap Overpass, GDACS). A second Google model, **Gemma**, handles the high-volume crowd-report triage — turning free-text or spoken hazard reports into the structured schema — so Gemini stays reserved for high-stakes reasoning.

## Challenges we ran into

- **Grounding real, local hazards.** Broken roads, open manholes and sewage-flooded lanes aren't in any structured feed. We combined OpenStreetMap tags, an accident-blackspot DB, geometry (sharp turns / unlit stretches), crowd reports, and — crucially — **Gemini Search grounding**, which surfaced genuinely local, cited reports (Burari waterlogging, sewage over the carriageway) and snaps them onto the route so they warn you *during* the drive.
- **Keeping the demo honest and offline-capable.** Every external dependency degrades gracefully, so the exact same code runs offline (keyless weather, synthetic routes, rule-based decisions) and, with keys, on Google Cloud.
- **Making a compressed drive feel real.** Getting turn-by-turn narration, path-based proximity warnings, and the map marker to stay in sync during a ~1-minute simulated drive took several rewrites of the speech channel and the along-route projection math.
- **Getting on Gemini 3.x.** Vertex's *regional* endpoints 404 on every Gemini 3.x id, and the Developer-API free tier caps at ~20 requests/day. The unlock was **Vertex on the `global` location**, which serves `gemini-3.7-flash` with full quota — plus making our thinking-token handling model-aware (Gemini 3.x always "thinks", so a zero thinking budget is invalid and a tiny output budget starves the answer).

## Accomplishments that we're proud of

- A genuinely **autonomous, multi-agent** system — it keeps working after you close the app, on a schedule it decides for itself, and you can **watch the agents delegate** in a live reasoning timeline.
- **Safety over speed, with the trade-off made explicit** — the fastest-vs-safest card is honest about the minutes it costs to avoid a blackspot.
- **Local truth reaches the traveller** — web-grounded waterlogging/roadwork/sewage in a specific neighbourhood actually warns you on the road, not just on a planning screen.
- **Two Google models, each on the right job** — Gemini for reasoning, Gemma for the triage firehose, plus Cloud TTS for hands-free, eyes-on-the-road guidance.
- It's **deployed and demoable end to end** on Google Cloud, with a deterministic hazard-injection hook for unedited live execution.

## What we learned

- **Grounding is the whole game.** An agent is only as trustworthy as the data it acts on; pairing structured feeds with Search grounding — and letting a rule engine validate the model — is what makes an autonomous safety action safe to ship.
- **Model access is a real engineering surface.** The same model id behaves completely differently across Vertex regional vs `global` vs the Developer API (availability, quota, thinking semantics) — worth verifying empirically, not assuming.
- **Change-detection and adaptive scheduling** are what turn "call an LLM in a loop" into an agent that's calm, cheap, and interrupts only when it matters.
- **Accessibility is a feature, not a nicety** — spoken narration and an at-a-glance weather-tinted UI matter most exactly when a rider can't look at a screen.

## What's next for SafeJourney

- **Real device GPS + live sharing** with trusted contacts and one-tap 112, and richer SOS escalation.
- **Broader hazard coverage** — more OSM road-condition signals, official municipal feeds, and a growing crowd-report network so local knowledge compounds.
- **On-device Gemma** for offline triage and voice-in where connectivity is worst (the same places the hazards are).
- **Personalisation** — vehicle type, night vs day, and rider risk tolerance shaping both routing and how loudly the guardian speaks.
- **Partnerships** with delivery fleets and city transport authorities, where a per-route safety guardian scales to thousands of daily riders.
