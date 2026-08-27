# SafeJourney — monitor-worker

A thin Cloud Run service that runs the **autonomous monitoring** cycle. It reuses
`safejourney.services.monitor` (the exact engine the REST API calls), so a tick behaves
identically however it's triggered.

## Topology

```
Cloud Scheduler ──heartbeat──▶ agent-api /monitor/dispatch
                                   │ publishes one message per due trip
                                   ▼
                             Pub/Sub  trip-evaluate
                                   │ push subscription
                                   ▼
                        monitor-worker /pubsub/push ──▶ evaluate_trip(trip_id)
```

Decoupling the worker lets evaluation scale independently of the API: many worker instances
drain the topic in parallel, and Cloud Run scales each to zero when idle.

## Endpoints
- `POST /pubsub/push` — Pub/Sub push target; extracts `trip_id` and evaluates it.
- `POST /dispatch` — single-service alternative that evaluates all due trips directly.
- `GET /health`

## Run locally

```bash
pip install ../../packages/shared ../agent-api
pip install -r requirements.txt
uvicorn main:app --port 8081
# then: curl -X POST localhost:8081/dispatch
```

## Deploy
Built from the repo root; see `infra/deploy.sh` and `infra/schedule.sh`.
