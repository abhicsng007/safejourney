# SafeJourney — Google Cloud & API Setup

There are three levels. Do **Level 1** to get the app fully working locally with real Gemini
in ~10 minutes. Do **Level 2** for real maps. Do **Level 3** to deploy to Google Cloud for
the hackathon submission (Cloud Run + Firestore + Pub/Sub + Scheduler).

> Every key below is optional — with none set, the app still runs on keyless fallbacks. Keys
> upgrade fallbacks to the real Google services.

---

## Prerequisites

- **gcloud CLI** — https://cloud.google.com/sdk/docs/install
- **Node 18+** and **Python 3.10+** (you already have these)
- A Google account. A billing account is needed for Level 3 (Cloud Run/Firestore); grab the
  **hackathon Cloud credits** from the Devpost *Resources* page so it's free.

Interactive login commands can't run headless — in this Claude Code session prefix them with
`!` (e.g. `! gcloud auth login`) so they run in your terminal, or just run them yourself.

---

## Level 1 — Real Gemini locally (fastest)

The simplest path uses a **Gemini API key** from Google AI Studio (no billing, no project
setup, generous free tier).

1. Create a key: https://aistudio.google.com/apikey → **Create API key** → copy it.
2. Install the Google libs and set the key in `apps/agent-api/.env`:

   ```
   # apps/agent-api/.env
   GOOGLE_GENAI_USE_VERTEXAI=false
   GOOGLE_API_KEY=paste-your-key-here
   GEMINI_MODEL=gemini-2.5-flash        # use a 3.5+ id for the submission (see note)
   ```

3. Install ADK + GenAI and run:

   ```bash
   cd apps/agent-api
   pip install ../../packages/shared -r requirements.txt   # includes google-adk, google-genai
   uvicorn main:app --port 8080
   ```

Now `/agent/chat` runs the real ADK Guardian fleet, and alert messages are narrated by Gemini.
`GET /config` should show `"gemini_available": true`.

> **Model id:** the hackathon requires **Gemini 3.5 or newer**. Model ids change over time —
> pick a current 3.5+ flash/pro id from https://aistudio.google.com (Level 1) or the Vertex
> **Model Garden** (Level 3) and put it in `GEMINI_MODEL`. `gemini-2.5-flash` is a safe local
> default; switch before you submit.

---

## Level 2 — Google Maps Platform (real routes, places, geocoding)

1. Console → **APIs & Services → Enable APIs & Services**, enable:
   - **Directions API** (route alternatives)
   - **Places API (New)** (safe harbours)
   - **Geocoding API** (address search)
   - **Maps JavaScript API** (optional, if you swap the web map to Google)
2. Console → **APIs & Services → Credentials → Create credentials → API key**. Copy it.
3. **Restrict the key** (recommended): Application restrictions → HTTP referrers (for web) or
   IP (for the server); API restrictions → only the four APIs above.
4. Put it in `apps/agent-api/.env`:

   ```
   GOOGLE_MAPS_API_KEY=paste-your-maps-key
   ```

`GET /config` will show `"maps_key": true` and routing/places now use Google instead of the
synthetic fallback.

---

## Level 3 — Full Google Cloud deployment (for submission)

### 3.1 Project, billing, auth
```bash
! gcloud auth login
gcloud projects create safejourney-<unique>        # or reuse an existing project
gcloud config set project safejourney-<unique>
# Link billing in the console: Billing → Link a billing account (apply hackathon credits)
! gcloud auth application-default login             # ADC, so local code can call Vertex/Firestore
```

### 3.2 Enable APIs + create Firestore + Pub/Sub topic
```bash
PROJECT_ID=safejourney-<unique> REGION=us-central1 bash infra/setup.sh
```
This enables: Cloud Run, Vertex AI (`aiplatform`), Firestore, Pub/Sub, Cloud Scheduler, Cloud
Build, Secret Manager, and the Maps/Routes/Places backends; creates the Firestore database and
the `trip-evaluate` topic.

Switch the API to **Vertex** (instead of the AI Studio key) by setting on the service:
```
GOOGLE_GENAI_USE_VERTEXAI=true
GCP_PROJECT=safejourney-<unique>
GCP_LOCATION=us-central1
```
(ADC / the Cloud Run service account provides credentials — no API key needed.)

### 3.3 Firestore rules + indexes
```bash
npm i -g firebase-tools && firebase login
firebase use safejourney-<unique>
firebase deploy --only firestore:rules,firestore:indexes
```

### 3.4 Deploy the two Cloud Run services
```bash
PROJECT_ID=safejourney-<unique> REGION=us-central1 MAPS_KEY=your-maps-key \
  GEMINI_MODEL=gemini-3.5-flash bash infra/deploy.sh
```
Prints the public API URL. Test it: `curl <API_URL>/health`.

### 3.5 Wire the autonomous loop (Scheduler + Pub/Sub push)
```bash
PROJECT_ID=safejourney-<unique> REGION=us-central1 bash infra/schedule.sh
```
Now Cloud Scheduler pokes `/monitor/dispatch` every 2 min; each due trip fans out via Pub/Sub
to the worker. This is the autonomous background loop the judges see in the console.

### 3.6 Deploy the web app
```bash
cd apps/web
echo "VITE_API_URL=<API_URL>" > .env
npm install && npm run build
firebase deploy --only hosting
```

---

## Level 4 — FCM push (optional, advanced)

Push-with-app-closed needs a Firebase Cloud Messaging client in the PWA (not yet wired — the
local build shows alerts via polling instead). To add it:
1. Firebase console (same project) → **Project settings → Cloud Messaging**; register a **Web
   app**, copy the config + generate a **Web Push (VAPID) key**.
2. Add the Firebase SDK to `apps/web`, request notification permission, get the device token,
   and pass it to `POST /trips/{id}/start` as `fcm_token`.
3. Set `FCM_ENABLED=true` on the API service (the Admin SDK uses the Cloud Run service account).

Ask and this client piece can be added.

---

## Which keys does each service read?

| Env var | Service | Effect if unset |
|---|---|---|
| `GOOGLE_API_KEY` **or** `GCP_PROJECT`+`GOOGLE_GENAI_USE_VERTEXAI=true` | agent-api | Gemini/ADK off → rule-based decisions |
| `GEMINI_MODEL` | agent-api | defaults to `gemini-2.5-flash` |
| `GOOGLE_MAPS_API_KEY` | agent-api | synthetic routes/places |
| `USE_FIRESTORE=true`+`FIRESTORE_PROJECT` | agent-api, worker | in-memory storage |
| `FCM_ENABLED=true` | agent-api | alerts logged, no OS push |
| `VITE_API_URL` | web | defaults to `http://localhost:8080` |

## Verify
```bash
curl localhost:8080/config     # shows which integrations are live
curl -X POST localhost:8080/agent/chat -H 'Content-Type: application/json' \
     -d '{"message":"Is it safe to ride to Whitefield now?"}'
```
