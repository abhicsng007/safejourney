#!/usr/bin/env bash
# Provision the Google Cloud resources SafeJourney needs.
# Usage: PROJECT_ID=your-project REGION=us-central1 bash infra/setup.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
REGION="${REGION:-us-central1}"

echo "== Setting project =="
gcloud config set project "$PROJECT_ID"

echo "== Enabling APIs =="
gcloud services enable \
  run.googleapis.com \
  aiplatform.googleapis.com \
  firestore.googleapis.com \
  pubsub.googleapis.com \
  cloudscheduler.googleapis.com \
  cloudbuild.googleapis.com \
  artifactregistry.googleapis.com \
  cloudresourcemanager.googleapis.com \
  secretmanager.googleapis.com \
  maps-backend.googleapis.com \
  routes.googleapis.com \
  places-backend.googleapis.com

echo "== Artifact Registry repo for container images =="
gcloud artifacts repositories create safejourney \
  --repository-format=docker --location="$REGION" \
  --description="SafeJourney service images" 2>/dev/null || echo "AR repo exists"

echo "== Firestore (Native mode) =="
gcloud firestore databases create --location="$REGION" 2>/dev/null || echo "Firestore already exists."

echo "== Pub/Sub topic for per-trip evaluation =="
gcloud pubsub topics create trip-evaluate 2>/dev/null || echo "topic exists"

echo "== Granting the Cloud Run runtime service account access to Vertex + Firestore =="
PROJECT_NUMBER="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)')"
RUNTIME_SA="${PROJECT_NUMBER}-compute@developer.gserviceaccount.com"
for role in roles/aiplatform.user roles/datastore.user roles/pubsub.publisher; do
  gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member "serviceAccount:${RUNTIME_SA}" --role "$role" >/dev/null
done
echo "Granted aiplatform.user, datastore.user, pubsub.publisher to ${RUNTIME_SA}"

echo "Done. Next: bash infra/deploy.sh to build & deploy the services,"
echo "then bash infra/schedule.sh to wire Cloud Scheduler + the push subscription."
