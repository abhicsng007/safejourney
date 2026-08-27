# SafeJourney — Deploy from the Google Cloud Console (no local tools)

This path uses **Cloud Shell** (the terminal built into the Cloud Console). It already has
`gcloud`, `firebase`, `docker`, Node and Python installed and is pre-authenticated as you — so
you install nothing on your own machine.

Total time ~20-30 min.

---

## 1. Create a project + turn on billing (Console UI)

1. Go to **https://console.cloud.google.com**.
2. Top bar → project dropdown → **New Project** → name it `safejourney` → **Create**, then
   select it.
3. Left menu → **Billing** → **Link a billing account**. Apply your **hackathon Cloud credits**
   (from the Devpost *Resources* page) so usage is free.

---

## 2. Open Cloud Shell

Click the **`>_` terminal icon** in the top-right of the Console. A shell opens at the bottom
with your project already active. Confirm:

```bash
gcloud config get-value project      # should print safejourney-...
```

If it's blank: `gcloud config set project YOUR_PROJECT_ID`.

---

## 3. Get the code into Cloud Shell

**Option A — via GitHub (recommended; you also need a public repo for the submission).**

On your PC, push the project once:
```bash
cd D:/Downloads/safeJourney
git init && git add . && git commit -m "SafeJourney"
git branch -M main
git remote add origin https://github.com/<you>/safejourney.git   # create the empty repo first
git push -u origin main
```
Then in **Cloud Shell**:
```bash
git clone https://github.com/<you>/safejourney.git
cd safejourney
```

**Option B — upload directly (no GitHub yet).** In Cloud Shell, click **⋮ → Upload**, upload a
zip of the folder, then `unzip safejourney.zip && cd safejourney`.

---

## 4. Provision Google Cloud (one script)

```bash
PROJECT_ID=$(gcloud config get-value project) REGION=us-central1 bash infra/setup.sh
```
This enables the APIs (Vertex AI, Cloud Run, Firestore, Pub/Sub, Cloud Scheduler, Cloud Build,
Artifact Registry, Maps), creates the Firestore database, the `trip-evaluate` Pub/Sub topic,
the Artifact Registry repo, and grants the Cloud Run runtime account Vertex + Firestore access.

> If prompted to authorize Cloud Shell (`gcloud` API calls), click **Authorize**.

---

## 5. (Optional) A Maps key for real routes/places

**APIs & Services → Credentials → Create credentials → API key.** Enable *Directions*,
*Places (New)*, *Geocoding*. Copy the key; pass it as `MAPS_KEY=...` in the next step. Skip to
use synthetic routes.

---

## 6. Deploy the two Cloud Run services

```bash
PROJECT_ID=$(gcloud config get-value project) REGION=us-central1 \
  GEMINI_MODEL=gemini-3.5-flash MAPS_KEY=YOUR_MAPS_KEY \
  bash infra/deploy.sh
```
Cloud Build builds both images and deploys `safejourney-api` (public) and `safejourney-monitor`
(private). It prints the **API URL** at the end — copy it.

> Set `GEMINI_MODEL` to a current **3.5+** id (check **Vertex AI → Model Garden**). This
> satisfies the "Gemini 3.5 or newer" requirement.

Test it:
```bash
API_URL=$(gcloud run services describe safejourney-api --region us-central1 --format='value(status.url)')
curl $API_URL/health
curl $API_URL/config      # gemini_available + use_firestore should be true
```

---

## 7. Wire the autonomous background loop

```bash
PROJECT_ID=$(gcloud config get-value project) REGION=us-central1 bash infra/schedule.sh
```
Creates the **Cloud Scheduler** heartbeat (every 2 min → `/monitor/dispatch`) and the
**Pub/Sub push subscription** to the worker. This is the autonomous loop the judges see running.

---

## 8. Deploy the web app (Firebase Hosting)

```bash
firebase login --no-localhost         # opens a link; paste the code back
firebase use $(gcloud config get-value project)

# point the web app at your deployed API, then build
echo "VITE_API_URL=$API_URL" > apps/web/.env
npm --prefix apps/web install
npm --prefix apps/web run build

firebase deploy --only hosting,firestore:rules,firestore:indexes
```
Firebase prints your **Hosting URL** — that's your public demo link.

---

## 9. Where to watch it work (for your demo video)

In the Console, these four screens are your "visual proof of Google Cloud deployment":

| What | Console location |
|---|---|
| Services running | **Cloud Run** → `safejourney-api`, `safejourney-monitor` |
| Heartbeat firing | **Cloud Scheduler** → `safejourney-heartbeat` → *Run history* |
| Per-trip fan-out | **Pub/Sub** → Subscriptions → `trip-evaluate-push` (delivery metrics) |
| Live logs | **Cloud Run** → `safejourney-monitor` → **Logs** (see `evaluate_trip`) |
| Data written | **Firestore** → *Data* → `trips`, `alerts`, `snapshots` |

Trigger a live alert on the deployed API (works with the app closed):
```bash
# create + start a trip, then force a hazard
TRIP=$(curl -s -X POST $API_URL/trips -H 'Content-Type: application/json' \
  -d '{"uid":"demo","origin":{"lat":12.9757,"lng":77.605},"destination":{"lat":12.9698,"lng":77.75},"mode":"two_wheeler"}' \
  | python3 -c 'import sys,json;print(json.load(sys.stdin)["trip"]["id"])')
curl -s -X POST $API_URL/trips/$TRIP/start -H 'Content-Type: application/json' -d '{}' >/dev/null
curl -s -X POST $API_URL/demo/force-hazard -H 'Content-Type: application/json' \
  -d "{\"tripId\":\"$TRIP\",\"type\":\"electrocution\",\"severity\":\"critical\"}"
# within ~2 min the Scheduler tick raises a reroute alert; watch it in the worker logs + Firestore
curl -s $API_URL/trips/$TRIP/alerts
```

---

## Troubleshooting

- **`allow-unauthenticated` denied** — an org policy blocks public services. Deploy with
  `--no-allow-unauthenticated` and call the API with an identity token, or ask your admin.
- **Vertex 403 / permission denied** — re-run `infra/setup.sh` (it grants
  `aiplatform.user` to the runtime SA), or grant it in **IAM**.
- **Build fails on shared package** — always run `deploy.sh` from the **repo root** (the
  Dockerfiles copy `packages/shared`).
- **Model not found** — the `GEMINI_MODEL` id isn't available in your region; pick another
  3.5+ id from Model Garden or change `GCP_LOCATION`.
