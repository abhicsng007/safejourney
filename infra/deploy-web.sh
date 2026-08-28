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

# Firebase web config (optional) — baked in so "app-closed" push works. Export these before
# running, e.g. from apps/web/.env, or leave unset to deploy without push.
FB_API_KEY="${VITE_FIREBASE_API_KEY:-}"
FB_AUTH_DOMAIN="${VITE_FIREBASE_AUTH_DOMAIN:-}"
FB_PROJECT_ID="${VITE_FIREBASE_PROJECT_ID:-}"
FB_SENDER_ID="${VITE_FIREBASE_MESSAGING_SENDER_ID:-}"
FB_APP_ID="${VITE_FIREBASE_APP_ID:-}"
FB_VAPID="${VITE_FIREBASE_VAPID_KEY:-}"
[ -n "$FB_API_KEY" ] && echo "Baking Firebase config (push enabled)" || echo "No Firebase config — deploying without push"

# Map basemap (optional) — a full MapLibre STYLE-JSON URL (not a bare API key), e.g.
#   https://api.maptiler.com/maps/streets-v2/style.json?key=YOUR_MAPTILER_KEY
# Leave unset to ship the keyless OpenStreetMap raster fallback.
MAP_STYLE_URL="${VITE_MAP_STYLE_URL:-}"
[ -n "$MAP_STYLE_URL" ] && echo "Baking map style URL (custom basemap)" || echo "No VITE_MAP_STYLE_URL — using OpenStreetMap raster fallback"

# Cloud Build config with the config as build-args (written to /tmp to keep it self-contained).
cat > /tmp/cloudbuild.web.yaml <<EOF
steps:
  - name: gcr.io/cloud-builders/docker
    args:
      - build
      - -f
      - apps/web/Dockerfile
      - --build-arg
      - VITE_API_URL=${API_URL}
      - --build-arg
      - VITE_MAP_STYLE_URL=${MAP_STYLE_URL}
      - --build-arg
      - VITE_FIREBASE_API_KEY=${FB_API_KEY}
      - --build-arg
      - VITE_FIREBASE_AUTH_DOMAIN=${FB_AUTH_DOMAIN}
      - --build-arg
      - VITE_FIREBASE_PROJECT_ID=${FB_PROJECT_ID}
      - --build-arg
      - VITE_FIREBASE_MESSAGING_SENDER_ID=${FB_SENDER_ID}
      - --build-arg
      - VITE_FIREBASE_APP_ID=${FB_APP_ID}
      - --build-arg
      - VITE_FIREBASE_VAPID_KEY=${FB_VAPID}
      - -t
      - ${IMAGE}
      - .
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
