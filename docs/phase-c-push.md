# Phase C — Real autonomy: app-closed push (runbook)

Everything in the code is env-driven and ready. These are the steps **you** run (they need
your GCP/Firebase credentials and `gcloud` auth, which can't be done for you). The goal: start
a trip, **close the tab**, and get a real OS notification when the road ahead turns dangerous.

There are two independently-testable pieces:
- **Server-side autonomy** — Cloud Scheduler ticks the monitor, no client loop.
- **Web push** — Firebase Cloud Messaging delivers the alert to a closed app.

---

## 0. Prerequisites

```bash
gcloud auth login
gcloud auth application-default login
export PROJECT_ID=your-gcp-project
export REGION=us-central1
```

Your GCP project and Firebase project should be the **same project** (Firebase is just a
console over a GCP project). If you don't have Firebase on it yet: open
<https://console.firebase.google.com>, "Add project", and pick your existing GCP project.

---

## 1. Firebase Cloud Messaging setup (one-time, in the console)

1. **Register a Web App**: Firebase console → Project settings (gear) → *General* → *Your apps*
   → **Web** (`</>`). Give it a nickname. Copy the **SDK config** object — you need
   `apiKey`, `authDomain`, `projectId`, `messagingSenderId`, `appId`.
2. **VAPID key**: Project settings → *Cloud Messaging* → *Web configuration* → **Web Push
   certificates** → *Generate key pair*. Copy the key (this is `VITE_FIREBASE_VAPID_KEY`).
3. That's it — no plan upgrade needed; web push is free.

Put the web values in `apps/web/.env` (copy from `.env.example`):

```
VITE_FIREBASE_API_KEY=...
VITE_FIREBASE_AUTH_DOMAIN=your-project.firebaseapp.com
VITE_FIREBASE_PROJECT_ID=your-project
VITE_FIREBASE_MESSAGING_SENDER_ID=...
VITE_FIREBASE_APP_ID=...
VITE_FIREBASE_VAPID_KEY=...
```

The backend (`firebase-admin`) needs **no keys on Cloud Run** — it uses the runtime service
account's ADC automatically. For a **local** backend that actually sends push, download a
service-account key (Project settings → *Service accounts* → *Generate new private key*) and:

```bash
export GOOGLE_APPLICATION_CREDENTIALS=/path/to/firebase-adminsdk.json
export FCM_ENABLED=true
```

---

## 2. Deploy (server-side autonomy + push)

From the **repo root**:

```bash
# Provision APIs, Artifact Registry, Firestore, Pub/Sub, IAM (idempotent).
bash infra/setup.sh

# Build + deploy agent-api and monitor-worker. Turn push ON and give the API the web URL
# (you'll know the web URL after step 3 — re-run this line then, or set it now if known).
FCM_ENABLED=true MAPS_KEY="$YOUR_MAPS_KEY" bash infra/deploy.sh

# Deploy the web PWA. Export the Firebase vars first so they're baked into the bundle:
set -a; source apps/web/.env; set +a
bash infra/deploy-web.sh
# -> prints the web URL, e.g. https://safejourney-web-xxxx.run.app

# Re-deploy the API with WEB_APP_URL so push clicks deep-link back to the trip:
WEB_APP_URL="https://safejourney-web-xxxx.run.app" FCM_ENABLED=true MAPS_KEY="$YOUR_MAPS_KEY" bash infra/deploy.sh

# Wire the autonomous loop: Cloud Scheduler heartbeat (every minute) + Pub/Sub push sub.
bash infra/schedule.sh
```

Notes
- The heartbeat is **every minute** (`HEARTBEAT_CRON` overridable). It only *evaluates* trips
  whose adaptive `next_check_at` has passed, so it's not a check-per-minute — near-hazard
  trips tick down to `MIN_INTERVAL_S`, quiet ones wait up to `MAX_INTERVAL_S`.
- Push works only over **HTTPS or localhost** (a browser Geolocation/Push requirement). The
  deployed Cloud Run URL is HTTPS, so it just works. `file://` or a LAN IP will not.

---

## 3. The demo (the flagship moment)

1. Open the deployed **web URL** on a laptop or phone. Plan a trip → prep → **Start Guardian**.
   The browser asks for **notification permission** → Allow. You'll see a green
   "Push enabled" toast (this registered the FCM token on the trip).
2. **Close the tab** (or lock the phone).
3. From any terminal, force a hazard on that trip's road ahead:
   ```bash
   API=https://safejourney-api-xxxx.run.app
   TRIP=trip_xxxxxxxx        # visible in the app, or GET $API/trips
   curl -X POST "$API/demo/force-hazard" \
     -H 'Content-Type: application/json' \
     -d "{\"tripId\":\"$TRIP\",\"type\":\"flood\",\"severity\":\"critical\"}"
   ```
4. Within ~a minute the **Scheduler heartbeat** evaluates the trip server-side, the Sentinel
   decides *reroute/harbor*, and an **OS notification appears with the app closed**. Tapping it
   re-opens the app on that trip.

Want it instantly instead of waiting for the heartbeat? Poke the dispatcher once:
```bash
curl -X POST "$API/monitor/dispatch"
```

---

## 4. Verifying it's really server-side (not the client loop)

- In the app, the client still ticks every 6s **only while the tab is open** (dev convenience).
- With the tab **closed**, the only thing evaluating the trip is **Cloud Scheduler → agent-api**.
  Confirm in logs:
  ```bash
  gcloud run services logs read safejourney-api --region "$REGION" --limit 50 | grep -i dispatch
  ```
- The alert row in Firestore carries `meta.decided_by` = `gemini` (once Vertex is on) — proof
  the action was chosen by the agent, not hard-coded.

---

## 5. Troubleshooting

| Symptom | Fix |
|---|---|
| No permission prompt on Start | Not served over HTTPS/localhost, or `VITE_FIREBASE_*` not baked in (rebuild web with the env exported). |
| "Push enabled" toast never shows | `fcmConfigured()` false — a `VITE_FIREBASE_*` value is blank. Check the built bundle's env. |
| Permission granted but no push | Backend `FCM_ENABLED` not `true`, or the runtime SA lacks FCM. Check `gcloud run services logs read safejourney-api` for `[notify]`. |
| Push shows twice | Only the SW's `onBackgroundMessage` should render it; don't add a second `notification` display path. |
| Push arrives but click does nothing | `WEB_APP_URL` not set on the API — redeploy with it. |
| Heartbeat not firing | `gcloud scheduler jobs describe safejourney-heartbeat --location $REGION`; check it's ENABLED and the URI is the API's `/monitor/dispatch`. |
