#!/usr/bin/env bash
# Create the Firestore composite indexes the app's queries need. Without these, the query
# in repo.due_active_trips (status == active AND next_check_at <= now) fails with
# FAILED_PRECONDITION and every monitoring tick 500s — so active trips never get hazards,
# alerts, or reroutes. infra/deploy.sh does NOT do this, so run it once per project.
#
# The index definitions mirror infra/firestore.indexes.json (which `firebase deploy
# --only firestore:indexes` would apply if you use the Firebase CLI instead).
# Usage: PROJECT_ID=your-project bash infra/deploy-indexes.sh
set -euo pipefail

PROJECT_ID="${PROJECT_ID:?set PROJECT_ID}"
gcloud config set project "$PROJECT_ID" >/dev/null

echo "Creating trips(status, next_check_at) — the monitoring dispatch query..."
gcloud firestore indexes composite create \
  --collection-group=trips \
  --field-config=field-path=status,order=ascending \
  --field-config=field-path=next_check_at,order=ascending \
  --async || echo "  (already exists or in progress)"

echo "Indexes are building asynchronously — check with:"
echo "  gcloud firestore indexes composite list --format='value(state,fields.fieldPath)'"
echo "They must reach READY before the monitor tick works. Usually a few minutes."
