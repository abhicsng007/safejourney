# SafeJourney — Devpost Submission Guide

**Hackathon:** All Things Agentic (Google Cloud · Devpost) · **Category:** Taskmaster
(autonomous, background, multi-step execution).

## Mandatory requirements — how we meet them

| Requirement | How SafeJourney satisfies it |
|---|---|
| **Gemini 3.5+** (Gemini API / Vertex AI) | Every agent + the tick Decision agent + alert narration run on Gemini via Vertex (`GEMINI_MODEL=gemini-3.5-flash`, `agents/llm.py`, `agents/fleet.py`). |
| **≥1 Google Agent Framework** | **Google ADK** multi-agent fleet: Guardian Core orchestrates Prep, Route Guardian, Safe Harbor, Mobility, SOS (`safejourney/agents/fleet.py`). |
| **≥1 Google Cloud infra service** | **Cloud Run** (both services), **Firestore** (state), **Pub/Sub** + **Cloud Scheduler** (the autonomous loop). |
| Hosted URL / demo | Firebase Hosting (web) + Cloud Run (API). |
| Public repo w/ access | Add `testing@devpost.com` and `cloudhackathons@google.com` as readers. |
| Architecture diagram | `docs/architecture.md`. |
| ≤4-min video, unedited live execution + Cloud proof | See demo script below. |

Bonus points available: additional Google model (Gemma/Veo), a blog post, social posts.

**Second Google model — Gemma (bonus, and a real architectural reason).** Free-text / voice
crowd hazard reports are triaged into the structured hazard schema by **Gemma** (`gemma-3-12b-it`,
`services/triage.py` → `agents/llm.py:triage_report_gemma`), so a rider can just say *"live wire
in the water under the bridge"* and it files as `electrocution · critical`. Gemini stays reserved
for the low-volume, high-stakes reasoning (route/reroute/shelter decisions); Gemma absorbs the
high-volume classification firehose. A deterministic keyword classifier is the fallback, so the
feature (and the demo) never breaks when Gemma is unavailable.

## The 4-minute demo script (unedited)

1. **(0:00) The problem (15s).** One line + the fatality stats from the README.
2. **(0:15) Plan a trip (35s).** In the PWA, pick *MG Road → Whitefield*, mode *2-wheeler*,
   **Find the safest route** → show 3 routes ranked by safety, the recommended one, its
   precautions. Switch to the *Sikkim/Uttarakhand* preset to show the **GLOF cascade** flag —
   a hazard local weather alone would miss.
3. **(0:50) Start the Guardian (20s).** Show the "watching" state + live safety score.
4. **(1:10) Autonomous alert — the money shot (60s).** Tap **Live wire in water**. Within one
   tick a **REROUTE / take-shelter** alert toasts in, the feed updates, the map re-routes, and
   the interval tightens to 45s. Emphasise: *this is the agent acting on its own.*
   - For the **cloud** version: close the tab / lock the phone, then trigger the hazard via
     `curl .../demo/force-hazard`; the **FCM push** arrives with the app closed.
5. **(2:10) Google Cloud proof (60s).** Screen-share the console: Cloud Scheduler run history,
   Pub/Sub subscription delivering, Cloud Run request logs for `/monitor/evaluate`, and the
   Firestore `alerts`/`snapshots` documents being written.
6. **(3:10) Architecture (40s).** Walk the diagram: Scheduler → dispatcher → Pub/Sub → worker
   → Gemini decision → Firestore + FCM. Call out change-detection + adaptive intervals.
7. **(3:50) Close (10s).** Impact + it scales to any hard-road geography.

## Deploy checklist

```bash
# 0. Auth + project
gcloud auth login && gcloud config set project YOUR_PROJECT

# 1. Provision
PROJECT_ID=YOUR_PROJECT REGION=us-central1 bash infra/setup.sh

# 2. Firestore rules + indexes
firebase deploy --only firestore:rules,firestore:indexes   # (or gcloud firestore)

# 3. Build + deploy both Cloud Run services
PROJECT_ID=YOUR_PROJECT MAPS_KEY=YOUR_MAPS_KEY bash infra/deploy.sh

# 4. Wire the autonomous loop (Scheduler + Pub/Sub push)
PROJECT_ID=YOUR_PROJECT bash infra/schedule.sh

# 5. Web
cd apps/web && npm run build && firebase deploy --only hosting
```

## Pre-submission checklist
- [ ] `GEMINI_MODEL` set to a 3.5+ (hackathon-eligible) model on both services
- [ ] Repo public + `testing@devpost.com`, `cloudhackathons@google.com` added
- [ ] README spin-up verified from a clean clone
- [ ] Architecture diagram included
- [ ] ≤4-min video with unedited live alert + Cloud console proof
- [ ] Category selected: **Taskmaster**
- [ ] (Bonus) extra Google model + blog post
