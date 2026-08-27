#!/usr/bin/env bash
# Wire the autonomous background loop:
#   Cloud Scheduler (heartbeat) -> agent-api /monitor/dispatch, which fans out per-trip
#   Pub/Sub messages -> push subscription -> monitor-worker /pubsub/push.
# Usage: PROJECT_ID=your-project REGION=us-central1 bash infra/schedule.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"

API_URL="$(gcloud run services describe safejourney-api --region "$REGION" --format='value(status.url)')"
WORKER_URL="$(gcloud run services describe safejourney-monitor --region "$REGION" --format='value(status.url)')"
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
INVOKER_SA="service-${PROJECT_NUMBER}@gcp-sa-pubsub.iam.gserviceaccount.com"

HEARTBEAT_CRON="${HEARTBEAT_CRON:-* * * * *}"   # every minute — snappy for the live demo
echo "== Scheduler heartbeat -> ${API_URL}/monitor/dispatch (cron: ${HEARTBEAT_CRON}) =="
# agent-api is public (--allow-unauthenticated), so the heartbeat needs no auth token.
# (To secure it later, create a service account, grant it run.invoker on safejourney-api,
#  and add: --oidc-service-account-email <that-sa>.)
# The dispatcher itself only evaluates trips whose adaptive next_check_at has passed, so a
# 1-minute heartbeat does not mean a check every minute — near-hazard trips tick down to
# MIN_INTERVAL_S while quiet trips wait up to MAX_INTERVAL_S.
if gcloud scheduler jobs describe safejourney-heartbeat --location "$REGION" >/dev/null 2>&1; then
  gcloud scheduler jobs update http safejourney-heartbeat \
    --location "$REGION" --schedule "$HEARTBEAT_CRON" \
    --uri "${API_URL}/monitor/dispatch" --http-method POST
else
  gcloud scheduler jobs create http safejourney-heartbeat \
    --location "$REGION" --schedule "$HEARTBEAT_CRON" \
    --uri "${API_URL}/monitor/dispatch" --http-method POST
fi

echo "== Pub/Sub push subscription -> ${WORKER_URL}/pubsub/push =="
# Allow Pub/Sub to mint OIDC tokens for the worker.
gcloud run services add-iam-policy-binding safejourney-monitor \
  --region "$REGION" --member "serviceAccount:${INVOKER_SA}" --role roles/run.invoker

gcloud pubsub subscriptions create trip-evaluate-push \
  --topic trip-evaluate \
  --push-endpoint "${WORKER_URL}/pubsub/push" \
  --push-auth-service-account "$INVOKER_SA" \
  --ack-deadline 60 \
  2>/dev/null || echo "subscription exists"

echo "Autonomous loop wired. The heartbeat runs every 2 minutes; per-trip evaluation is"
echo "adaptive (down to ${MIN_INTERVAL_S:-45}s when hazards are near)."
