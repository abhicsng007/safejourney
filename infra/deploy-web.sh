#!/usr/bin/env bash
# Build the web PWA and deploy it to Cloud Run (public). Run from the REPO ROOT, after the
# agent-api is deployed (it reads that service's URL to bake into the frontend bundle).
# Usage: PROJECT_ID=your-project REGION=us-central1 bash infra/deploy-web.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"
REPO="safejourney"
IMAGE="${REGION}-docker.pkg.dev/${PROJECT_ID}/${REPO}/web:latest"

API_URL="$(gcloud run services describe safejourney-api --region "$REGION" --format='value(status.url)')"
echo "Baking API URL into the frontend: ${API_URL}"

# Cloud Build config with the API URL as a build-arg (written to /tmp to keep it self-contained).
cat > /tmp/cloudbuild.web.yaml <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args: ['build','-f','apps/web/Dockerfile','--build-arg','VITE_API_URL=${API_URL}','-t','${IMAGE}','.']
images: ['${IMAGE}']
options:
  logging: CLOUD_LOGGING_ONLY
EOF

gcloud builds submit --config /tmp/cloudbuild.web.yaml .

gcloud run deploy safejourney-web \
  --image "$IMAGE" \
  --region "$REGION" \
  --allow-unauthenticated \
  --port 8080

echo ""
echo "Web app URL:"
gcloud run services describe safejourney-web --region "$REGION" --format='value(status.url)'
