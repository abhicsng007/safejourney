"""The autonomous monitoring engine — the Taskmaster core.

`dispatch()` finds active trips due for a check (called by Cloud Scheduler).
`evaluate_trip()` runs one monitoring cycle for a single trip (called per-trip via Pub/Sub,
or directly): scan the road ahead, detect what is *newly* dangerous, decide an action,
persist a snapshot, raise + push an alert, and schedule the next check adaptively.

Both the REST service and the Pub/Sub worker import these functions, so the behaviour is
identical however a tick is triggered.
"""

from __future__ import annotations

import time

from safejourney_shared.geo import corridor_geohashes, decode_polyline
from safejourney_shared.hazards import Hazard, Severity, SEVERITY_SCORE
from safejourney_shared.models import (
    Alert,
    AlertAction,
    HazardSnapshot,
    LatLng,
    Trip,
    TripStatus,
)
from safejourney_shared.scoring import safety_score, route_is_blocking

from ..config import get_settings
from ..repo import get_repo
from ..tools.hazard_scan import scan_corridor
from ..tools.notify import send_push
from .agentic import agentic_decision
from .planner import plan_and_score


def dispatch(now: float | None = None) -> dict:
    """Find due active trips and evaluate each. Returns a summary of what happened."""
    repo = get_repo()
    now = now or time.time()
    due = repo.due_active_trips(now)
    results = []
    for trip in due:
        try:
            results.append(evaluate_trip(trip.id))
        except Exception as e:  # pragma: no cover - one bad trip shouldn't stop the loop
            results.append({"trip_id": trip.id, "error": str(e)})
    return {"checked": len(due), "results": results, "ts": now}


def _remaining_points(trip: Trip) -> list[tuple[float, float]]:
    decoded = decode_polyline(trip.encoded_polyline) if trip.encoded_polyline else []
    return trip.remaining_polyline_points(decoded)


def _new_or_escalated(hazards: list[Hazard], prev_keys: set[str]) -> list[Hazard]:
    """Hazards not seen on the previous tick (change-detection = no alert spam)."""
    return [h for h in hazards if h.key() not in prev_keys]


def _adaptive_interval(hazards: list[Hazard]) -> int:
    s = get_settings()
    if not hazards:
        return s.max_interval_s
    top = max(SEVERITY_SCORE[h.severity] for h in hazards)
    if top >= SEVERITY_SCORE[Severity.CRITICAL]:
        return s.min_interval_s
    if top >= SEVERITY_SCORE[Severity.HIGH]:
        return max(s.min_interval_s, s.default_interval_s // 2)
    return s.default_interval_s


def _try_reroute(trip: Trip) -> dict | None:
    """Look for a safer, non-blocking alternative from the current position onward."""
    start = (
        (trip.current_position.lat, trip.current_position.lng)
        if trip.current_position
        else (trip.origin.lat, trip.origin.lng)
    )
    dest = (trip.destination.lat, trip.destination.lng)
    plan = plan_and_score(start, dest, trip.mode.value)
    for r in plan["routes"]:
        if not r["blocking"]:
            return r
    return None


def evaluate_trip(trip_id: str) -> dict:
    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return {"trip_id": trip_id, "error": "not found"}
    if trip.status != TripStatus.ACTIVE:
        return {"trip_id": trip_id, "skipped": f"status={trip.status.value}"}

    remaining = _remaining_points(trip)
    hazards = scan_corridor(remaining, mode=trip.mode.value)
    score = safety_score(hazards, mode=trip.mode.value)

    snap = HazardSnapshot(
        trip_id=trip.id,
        safety_score=score,
        hazards=[h.to_dict() for h in hazards],
    )
    repo.save_snapshot(snap)

    prev_keys = set(trip.last_hazard_keys)
    new_hazards = _new_or_escalated(hazards, prev_keys)

    alert_out = None
    reroute_route = None
    reroute_available = False

    if new_hazards and route_is_blocking(new_hazards):
        reroute_route = _try_reroute(trip)
        reroute_available = reroute_route is not None

    decision = agentic_decision(new_hazards, trip, reroute_available) if new_hazards else None

    if decision:
        reason = getattr(decision, "reason", "") or decision.__dict__.get("reason", "")
        decided_by = "gemini" if get_settings().gemini_available else "rules"
        # Apply a reroute by switching the trip's path to the safer route.
        if decision.action == AlertAction.REROUTE and reroute_route:
            trip.encoded_polyline = reroute_route["encoded_polyline"]
            pts = decode_polyline(trip.encoded_polyline)
            trip.corridor_geohashes = corridor_geohashes(pts)

        loc = LatLng(lat=new_hazards[0].lat, lng=new_hazards[0].lng)
        alert = Alert(
            trip_id=trip.id,
            uid=trip.uid,
            action=decision.action,
            severity=decision.severity.value,
            title=decision.title,
            message=decision.message,
            precautions=decision.precautions,
            hazard_types=decision.hazard_types,
            location=loc,
            meta={"reroute": bool(reroute_route), "reason": reason, "decided_by": decided_by},
        )
        repo.save_alert(alert)
        pushed = send_push(
            token=trip.fcm_token,
            title=alert.title,
            body=alert.message,
            data={"tripId": trip.id, "alertId": alert.id, "action": alert.action.value},
        )
        alert_out = {"id": alert.id, "action": alert.action.value,
                     "severity": alert.severity, "pushed": pushed}

    # Update bookkeeping + schedule the next tick.
    trip.last_snapshot_id = snap.id
    trip.last_hazard_keys = [h.key() for h in hazards]
    interval = _adaptive_interval(hazards)
    trip.monitor_interval_s = interval
    trip.next_check_at = time.time() + interval
    repo.save_trip(trip)

    return {
        "trip_id": trip.id,
        "hazards": len(hazards),
        "new_hazards": len(new_hazards),
        "safety_score": round(score, 2),
        "alert": alert_out,
        "next_check_in_s": interval,
    }
