#!/usr/bin/env bash
# Build both images with Cloud Build (Artifact Registry) and deploy both Cloud Run services.
# Run from the REPO ROOT.
# Usage: PROJECT_ID=your-project REGION=us-central1 MAPS_KEY=xxx bash infra/deploy.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
MAPS_KEY="${MAPS_KEY:-}"
MODEL="${GEMINI_MODEL:-gemini-3.5-flash}"
REPO="safejourney"

AR="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}"

echo "== Building images with Cloud Build =="
gcloud builds submit --config cloudbuild.yaml \
  --substitutions "_REGION=${REGION},_REPO=${REPO}" .

COMMON_ENV="GCP_PROJECT=${PROJECT_ID},GCP_LOCATION=${REGION},GOOGLE_GENAI_USE_VERTEXAI=true,USE_FIRESTORE=true,FIRESTORE_PROJECT=${PROJECT_ID},GEMINI_MODEL=${MODEL},FCM_ENABLED=false,GOOGLE_MAPS_API_KEY=${MAPS_KEY}"

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
echo "Next: PROJECT_ID=${PROJECT_ID} REGION=${REGION} bash infra/schedule.sh"
