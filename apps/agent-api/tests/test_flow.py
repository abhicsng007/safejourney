"""End-to-end test of the core SafeJourney flow, fully offline.

Network-backed tools are patched out so the test is deterministic; the demo hazard-injection
path drives the hazards. Verifies: route pre-detection, trip start, autonomous evaluation
raising a reroute alert, and change-detection suppressing duplicate alerts.
"""

import pytest

from safejourney_shared.models import LatLng
from safejourney import repo as repo_mod
from safejourney.tools import hazard_scan
from safejourney.services import trips as trips_svc
from safejourney.services.monitor import evaluate_trip, dispatch


@pytest.fixture(autouse=True)
def clean_repo(monkeypatch):
    # Fresh in-memory repo per test.
    monkeypatch.setattr(repo_mod, "_repo", repo_mod.InMemoryRepo())
    # Make external feeds deterministic (no network in tests).
    monkeypatch.setattr(hazard_scan, "weather_hazards", lambda pts: [])
    monkeypatch.setattr(hazard_scan, "disaster_hazards", lambda pts, raining=False: [])
    monkeypatch.setattr(hazard_scan, "roadwork_hazards", lambda pts, max_items=12: [])
    yield


# Bengaluru: MG Road area -> Whitefield-ish
ORIGIN = LatLng(lat=12.9757, lng=77.6050)
DEST = LatLng(lat=12.9698, lng=77.7500)


def _make_active_trip():
    created = trips_svc.create_trip("u1", ORIGIN, DEST, mode="two_wheeler",
                                    origin_label="MG Road", destination_label="Whitefield")
    trip_id = created["trip"]["id"]
    trips_svc.start_trip(trip_id)
    return trip_id, created["plan"]


def test_route_predetection_returns_ranked_routes():
    _, plan = _make_active_trip()
    assert len(plan["routes"]) >= 2
    # With no hazards, nothing is blocked and a route is recommended.
    assert plan["recommended_route_id"] is not None
    assert plan["all_routes_blocked"] is False
    scores = [r["score"] for r in plan["routes"]]
    assert scores == sorted(scores)  # safest first


def test_clean_trip_no_alert():
    trip_id, _ = _make_active_trip()
    result = evaluate_trip(trip_id)
    assert result["alert"] is None
    assert result["new_hazards"] == 0
    # No hazards -> longest interval.
    assert result["next_check_in_s"] >= 180


def test_injected_flood_triggers_reroute_alert():
    trip_id, _ = _make_active_trip()
    inj = trips_svc.force_hazard(trip_id, "flood", "critical", at_fraction=0.5)
    assert "incident" in inj

    result = evaluate_trip(trip_id)
    alert = result["alert"]
    assert alert is not None, "a critical flood on the path must raise an alert"
    assert alert["action"] in ("reroute", "harbor")
    assert alert["severity"] == "critical"
    # Critical hazard -> tightest monitoring interval.
    assert result["next_check_in_s"] <= 60


def test_change_detection_suppresses_duplicate():
    trip_id, _ = _make_active_trip()
    trips_svc.force_hazard(trip_id, "electrocution", "critical", at_fraction=0.4)
    first = evaluate_trip(trip_id)
    assert first["alert"] is not None
    # Second tick: same hazard, no new alert.
    second = evaluate_trip(trip_id)
    assert second["alert"] is None
    assert second["new_hazards"] == 0


def test_dispatch_checks_due_trips():
    trip_id, _ = _make_active_trip()
    trips_svc.force_hazard(trip_id, "flood", "critical")
    summary = dispatch()
    assert summary["checked"] >= 1
    assert any(r.get("trip_id") == trip_id for r in summary["results"])
