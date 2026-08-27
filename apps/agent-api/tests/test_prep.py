"""Tests for pre-trip readiness — verdict + hazard-grounded checklist."""

from safejourney.services.prep import readiness


def _plan(hazard_types, rating="safe", all_blocked=False, first_leg_hazards=None):
    plan = {
        "recommended_route_id": "r0",
        "all_routes_blocked": all_blocked,
        "routes": [
            {"route_id": "r0", "rating": rating,
             "hazards": [{"type": t} for t in hazard_types]},
        ],
    }
    if first_leg_hazards is not None:
        plan["first_leg"] = {"hazards": [{"type": t} for t in first_leg_hazards]}
    return plan


def test_clear_route_is_go_with_base_kit():
    r = readiness(_plan([]), "two_wheeler")
    assert r["verdict"] == "go"
    items = " ".join(c["item"].lower() for c in r["checklist"])
    assert "helmet" in items  # base two-wheeler kit


def test_rain_adds_rain_gear():
    r = readiness(_plan(["flood"], rating="risky"), "two_wheeler")
    assert r["verdict"] == "caution"
    items = " ".join(c["item"].lower() for c in r["checklist"])
    assert "rain" in items or "visor" in items


def test_all_blocked_says_wait():
    r = readiness(_plan(["flood"], rating="dangerous", all_blocked=True), "two_wheeler")
    assert r["verdict"] == "wait"


def test_heat_adds_water_and_sun():
    r = readiness(_plan(["heat"]), "walk")
    items = " ".join(c["item"].lower() for c in r["checklist"])
    assert "water" in items and ("cap" in items or "sunscreen" in items)


def test_first_leg_hazards_fold_into_checklist():
    # Main transit route clear, but the walk-to-station leg is wet -> rain gear appears.
    r = readiness(_plan([], first_leg_hazards=["storm"]), "walk")
    items = " ".join(c["item"].lower() for c in r["checklist"])
    assert "rain" in items or "umbrella" in items
    assert "storm" in r["hazard_types"]
