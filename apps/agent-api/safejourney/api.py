"""FastAPI surface for SafeJourney.

Groups:
  * trips      — plan/create, start, position, complete, alerts
  * monitor    — dispatch (Scheduler) + evaluate (Pub/Sub push) + tick (manual)
  * agent      — chat through the Guardian Core (ADK)
  * demo       — force a hazard so the autonomous alert fires on cue
"""

from __future__ import annotations

import base64
import json
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from safejourney_shared.models import LatLng, Incident
from safejourney_shared.geo import geohash_encode

from .config import get_settings
from .repo import get_repo
from .services import trips as trips_svc
from .services.planner import plan_and_score
from .services.monitor import dispatch as monitor_dispatch, evaluate_trip
from .tools.places import find_safe_harbors


app = FastAPI(title="SafeJourney API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------- request models ----------
class PlanReq(BaseModel):
    origin: LatLng
    destination: LatLng
    mode: str = "two_wheeler"
    risk_tolerance: float = 1.0


class CreateTripReq(BaseModel):
    uid: str = "local"
    origin: LatLng
    destination: LatLng
    mode: str = "two_wheeler"
    origin_label: str = ""
    destination_label: str = ""
    risk_tolerance: float = 1.0


class ChooseRouteReq(BaseModel):
    route: dict


class StartReq(BaseModel):
    fcm_token: str = ""


class PositionReq(BaseModel):
    lat: float
    lng: float


class ChatReq(BaseModel):
    message: str
    session_id: str = "default"
    user_id: str = "local"


class ForceHazardReq(BaseModel):
    tripId: str
    type: str = "flood"
    severity: str = "critical"
    at_fraction: float = 0.5
    description: str = ""


class IncidentReq(BaseModel):
    type: str
    severity: str = "high"
    lat: float
    lng: float
    description: str = ""
    source: str = "crowd"


# ---------- meta ----------
@app.get("/health")
def health() -> dict:
    return {"ok": True, "service": "safejourney-api"}


@app.get("/config")
def config() -> dict:
    return get_settings().summary()


# ---------- planning ----------
@app.post("/plan")
def plan(req: PlanReq) -> dict:
    return plan_and_score(
        (req.origin.lat, req.origin.lng),
        (req.destination.lat, req.destination.lng),
        req.mode,
        req.risk_tolerance,
    )


@app.get("/safe-harbors")
def safe_harbors(lat: float, lng: float) -> dict:
    return {"harbors": find_safe_harbors(lat, lng)}


# ---------- trips ----------
@app.post("/trips")
def create_trip(req: CreateTripReq) -> dict:
    return trips_svc.create_trip(
        uid=req.uid,
        origin=req.origin,
        destination=req.destination,
        mode=req.mode,
        origin_label=req.origin_label,
        destination_label=req.destination_label,
        risk_tolerance=req.risk_tolerance,
    )


@app.get("/trips")
def list_trips(uid: Optional[str] = None) -> dict:
    return {"trips": [t.model_dump(mode="json") for t in get_repo().list_trips(uid)]}


@app.get("/trips/{trip_id}")
def get_trip(trip_id: str) -> dict:
    t = get_repo().get_trip(trip_id)
    if not t:
        raise HTTPException(404, "trip not found")
    return t.model_dump(mode="json")


@app.post("/trips/{trip_id}/choose-route")
def choose_route(trip_id: str, req: ChooseRouteReq) -> dict:
    t = trips_svc.choose_route(trip_id, req.route)
    if not t:
        raise HTTPException(404, "trip not found")
    return t.model_dump(mode="json")


@app.post("/trips/{trip_id}/start")
def start_trip(trip_id: str, req: StartReq) -> dict:
    t = trips_svc.start_trip(trip_id, req.fcm_token)
    if not t:
        raise HTTPException(404, "trip not found")
    return t.model_dump(mode="json")


@app.post("/trips/{trip_id}/position")
def update_position(trip_id: str, req: PositionReq) -> dict:
    t = trips_svc.update_position(trip_id, LatLng(lat=req.lat, lng=req.lng))
    if not t:
        raise HTTPException(404, "trip not found")
    return t.model_dump(mode="json")


@app.post("/trips/{trip_id}/complete")
def complete_trip(trip_id: str) -> dict:
    t = trips_svc.complete_trip(trip_id)
    if not t:
        raise HTTPException(404, "trip not found")
    return t.model_dump(mode="json")


@app.get("/trips/{trip_id}/alerts")
def trip_alerts(trip_id: str) -> dict:
    return {"alerts": [a.model_dump(mode="json") for a in get_repo().list_alerts(trip_id)]}


@app.get("/trips/{trip_id}/hazards")
def trip_hazards(trip_id: str) -> dict:
    """Hazards from the trip's most recent monitoring snapshot (for the live map)."""
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip or not trip.last_snapshot_id:
        return {"hazards": [], "safety_score": None}
    snap = repo.get_snapshot(trip.last_snapshot_id)
    if not snap:
        return {"hazards": [], "safety_score": None}
    return {"hazards": snap.hazards, "safety_score": snap.safety_score}


@app.post("/alerts/{alert_id}/ack")
def ack_alert(alert_id: str) -> dict:
    a = get_repo().ack_alert(alert_id)
    if not a:
        raise HTTPException(404, "alert not found")
    return a.model_dump(mode="json")


# ---------- incidents (crowd reports) ----------
@app.post("/incidents")
def report_incident(req: IncidentReq) -> dict:
    inc = Incident(
        type=req.type, severity=req.severity, lat=req.lat, lng=req.lng,
        geohash=geohash_encode(req.lat, req.lng, 7),
        description=req.description, source=req.source,
    )
    get_repo().add_incident(inc)
    return inc.model_dump(mode="json")


# ---------- monitoring (autonomous background loop) ----------
@app.post("/monitor/dispatch")
def monitor_dispatch_ep() -> dict:
    """Called by Cloud Scheduler on a heartbeat: evaluate all due active trips."""
    return monitor_dispatch()


@app.post("/monitor/tick")
def monitor_tick() -> dict:
    """Manual single cycle (same as dispatch) — handy for local demos."""
    return monitor_dispatch()


@app.post("/monitor/evaluate")
async def monitor_evaluate(payload: dict) -> dict:
    """Evaluate one trip. Accepts either {"trip_id": ...} or a Pub/Sub push envelope."""
    trip_id = payload.get("trip_id")
    if not trip_id and "message" in payload:  # Pub/Sub push format
        msg = payload["message"]
        data = msg.get("data")
        if data:
            try:
                decoded = json.loads(base64.b64decode(data).decode())
                trip_id = decoded.get("trip_id")
            except Exception:
                trip_id = None
        trip_id = trip_id or msg.get("attributes", {}).get("trip_id")
    if not trip_id:
        raise HTTPException(400, "trip_id required")
    return evaluate_trip(trip_id)


# ---------- demo hook ----------
@app.post("/demo/force-hazard")
def demo_force_hazard(req: ForceHazardReq) -> dict:
    """Inject a hazard on a trip's road ahead so the next tick raises a real alert."""
    return trips_svc.force_hazard(
        req.tripId, req.type, req.severity, req.at_fraction, req.description
    )


# ---------- agent chat (ADK) ----------
@app.post("/agent/chat")
def agent_chat(req: ChatReq) -> dict:
    try:
        from .agents.fleet import run_guardian

        reply = run_guardian(req.message, req.session_id, req.user_id)
        return {"reply": reply, "agent": "guardian_core"}
    except RuntimeError as e:
        # ADK/Gemini not configured — return a clear, non-fatal message.
        return {"reply": None, "error": str(e), "agent": "guardian_core"}
