"""SafeJourney monitor-worker — a thin Cloud Run service that receives per-trip evaluation
requests from Pub/Sub (push subscription) and runs the shared monitoring engine.

Decoupling the worker from the REST API means monitoring scales independently: Cloud
Scheduler pokes the dispatcher, which fans out one Pub/Sub message per due trip, and any
number of worker instances drain them in parallel.

Reuses `safejourney.services.monitor` — the exact same engine the REST API calls — so a
tick behaves identically however it is triggered.
"""

from __future__ import annotations

import base64
import json
import os

from fastapi import FastAPI, HTTPException, Request

from safejourney.services.monitor import evaluate_trip, dispatch

app = FastAPI(title="SafeJourney Monitor Worker", version="0.1.0")


@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "safejourney-monitor-worker"}


@app.post("/dispatch")
def dispatch_ep() -> dict:
    """Cloud Scheduler heartbeat target: evaluate every due active trip.

    (In the fan-out topology the dispatcher instead publishes one message per trip; this
    endpoint is the simpler single-service alternative and is handy for local runs.)
    """
    return dispatch()


@app.post("/pubsub/push")
async def pubsub_push(request: Request) -> dict:
    """Pub/Sub push endpoint. Envelope: {"message": {"data": <base64>, "attributes": {...}}}."""
    envelope = await request.json()
    msg = (envelope or {}).get("message")
    if not msg:
        raise HTTPException(400, "expected a Pub/Sub push envelope")

    trip_id = None
    data = msg.get("data")
    if data:
        try:
            trip_id = json.loads(base64.b64decode(data).decode()).get("trip_id")
        except Exception:
            trip_id = None
    trip_id = trip_id or msg.get("attributes", {}).get("trip_id")
    if not trip_id:
        # Ack anyway (return 200) so Pub/Sub doesn't redeliver a malformed message forever.
        return {"skipped": "no trip_id in message"}

    return evaluate_trip(trip_id)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=int(os.getenv("PORT", "8081")), reload=False)
