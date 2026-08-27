"""Tests for the agentic layer: Gemini decides, the rule engine validates + falls back.

No network or real Gemini — the LLM call is monkeypatched so behaviour is deterministic.
"""

import pytest

from safejourney_shared.hazards import Hazard, HazardType, Severity
from safejourney_shared.models import AlertAction, LatLng, TravelMode, Trip, TripStatus

from safejourney.services import agentic
from safejourney.agents import llm as llm_mod


def _trip(mode="two_wheeler"):
    return Trip(
        uid="u1",
        mode=TravelMode(mode),
        origin=LatLng(lat=12.97, lng=77.60),
        destination=LatLng(lat=12.96, lng=77.75),
        status=TripStatus.ACTIVE,
    )


def _flood():
    return Hazard(HazardType.FLOOD, Severity.CRITICAL, 12.965, 77.7, "demo",
                  "Underpass flooding fast.", offset_m=10)


class _FakeSettings:
    def __init__(self, gemini):
        self.gemini_available = gemini


def test_falls_back_to_rules_without_gemini(monkeypatch):
    monkeypatch.setattr(agentic, "get_settings", lambda: _FakeSettings(False))
    d = agentic.agentic_decision([_flood()], _trip(), reroute_available=True)
    assert d is not None
    assert d.action == AlertAction.REROUTE  # rule engine: blocking + reroute available
    assert d.precautions  # grounded precautions attached


def test_llm_action_used_and_message_applied(monkeypatch):
    monkeypatch.setattr(agentic, "get_settings", lambda: _FakeSettings(True))
    monkeypatch.setattr(
        llm_mod, "decide_action_llm",
        lambda **kw: {"action": "harbor", "title": "Pull over now",
                      "message": "Head to the marked safe place and wait.",
                      "reason": "flood is impassable on a two-wheeler"},
    )
    d = agentic.agentic_decision([_flood()], _trip(), reroute_available=True)
    assert d.action == AlertAction.HARBOR
    assert d.title == "Pull over now"
    assert "safe place" in d.message
    assert d.__dict__.get("reason")


def test_hallucinated_action_rejected_to_baseline(monkeypatch):
    monkeypatch.setattr(agentic, "get_settings", lambda: _FakeSettings(True))
    monkeypatch.setattr(llm_mod, "decide_action_llm",
                        lambda **kw: {"action": "teleport", "message": "poof"})
    d = agentic.agentic_decision([_flood()], _trip(), reroute_available=True)
    # Invalid action snaps back to the rule-engine choice.
    assert d.action == AlertAction.REROUTE


def test_reroute_rejected_when_unavailable(monkeypatch):
    monkeypatch.setattr(agentic, "get_settings", lambda: _FakeSettings(True))
    monkeypatch.setattr(llm_mod, "decide_action_llm",
                        lambda **kw: {"action": "reroute", "message": "switching"})
    d = agentic.agentic_decision([_flood()], _trip(), reroute_available=False)
    # Rule baseline with no reroute available -> harbor; LLM reroute is invalid here.
    assert d.action == AlertAction.HARBOR


def test_llm_failure_keeps_baseline(monkeypatch):
    monkeypatch.setattr(agentic, "get_settings", lambda: _FakeSettings(True))

    def _boom(**kw):
        raise RuntimeError("gemini down")

    monkeypatch.setattr(llm_mod, "decide_action_llm", _boom)
    d = agentic.agentic_decision([_flood()], _trip(), reroute_available=True)
    assert d.action == AlertAction.REROUTE  # survived the failure


def test_no_hazards_stays_silent(monkeypatch):
    monkeypatch.setattr(agentic, "get_settings", lambda: _FakeSettings(True))
    assert agentic.agentic_decision([], _trip(), reroute_available=True) is None


def test_provenance_extracted_from_plan():
    plan = {
        "routes": [
            {"route_id": "g0", "meta": {"source": "google-directions"},
             "hazards": [{"source": "open-meteo"}, {"source": "gdacs"},
                         {"source": "report:demo"}]},
        ],
        "recommended_route_id": "g0",
    }
    prov = agentic._provenance(plan)
    assert "open-meteo" in prov and "gdacs" in prov and "report" in prov
    assert "google-directions" in prov
