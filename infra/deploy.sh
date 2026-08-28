#!/usr/bin/env bash
# Build both images with Cloud Build (Artifact Registry) and deploy both Cloud Run services.
# Run from the REPO ROOT.
# Usage: PROJECT_ID=your-project REGION=us-central1 MAPS_KEY=xxx bash infra/deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
MAPS_KEY="${MAPS_KEY:-}"
# Must be a model your project can access in $REGION and that supports Search grounding.
# gemini-3.5-flash is NOT available to all projects/regions (404) — 2.5-flash is a safe default.
MODEL="${GEMINI_MODEL:-gemini-2.5-flash}"
FCM_ENABLED="${FCM_ENABLED:-false}"   # set true once Firebase Cloud Messaging is configured
WEB_APP_URL="${WEB_APP_URL:-}"        # deployed PWA URL, so a push click deep-links back
REPO="safejourney"

AR="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"

echo "== Building images with Cloud Build =="
gcloud builds submit --config cloudbuild.yaml \
  --substitutions "_REGION=${REGION},_REPO=${REPO}" .

COMMON_ENV="GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,USE_FIRESTORE=true,FIRESTORE_PROJECT=${PROJECT_ID},GEMINI_MODEL=${MODEL},FCM_ENABLED=${FCM_ENABLED},WEB_APP_URL=${WEB_APP_URL},GOOGLE_MAPS_API_KEY=${MAPS_KEY}"

echo "== Deploying agent-api =="
gcloud run deploy safejourney-api \
  --image "${AR}/api:latest" \
  --region "$REGION" \
  --allow-unauthenticated \
  --memory 1Gi \
  --set-env-vars "$COMMON_ENV"

echo "== Deploying monitor-worker =="
gcloud run deploy safejourney-monitor \
  --image "${AR}/worker:latest" \
  --region "$REGION" \
  --no-allow-unauthenticated \
  --memory 1Gi \
  --set-env-vars "$COMMON_ENV"

echo ""
echo "agent-api URL:"
gcloud run services describe safejourney-api --region "$REGION" --format='value(status.url)'
echo ""
echo "IMPORTANT (once per project): create the Firestore indexes the monitor needs, or every"
echo "monitoring tick 500s and active trips never get hazards/alerts:"
echo "  PROJECT_ID=${PROJECT_ID} bash infra/deploy-indexes.sh"
echo "Next: PROJECT_ID=${PROJECT_ID} REGION=${REGION} bash infra/schedule.sh"
