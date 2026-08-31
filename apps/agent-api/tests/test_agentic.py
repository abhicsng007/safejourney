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


def test_plan_trace_shows_multiagent_handoff():
    plan = {
        "routes": [
            {"route_id": "g0", "rating": "caution", "score": 4,
             "meta": {"source": "google-directions"},
             "hazards": [{"type": "flood", "source": "open-meteo"}]},
        ],
        "recommended_route_id": "g0",
        "advice": "Take the safer corridor.",
    }
    trace = agentic.build_plan_trace(plan, "two_wheeler", decided_by="rules")
    kinds = [t["kind"] for t in trace]
    assert "delegate" in kinds and "tool_call" in kinds and "decision" in kinds
    tos = [t.get("to") for t in trace if t["kind"] == "delegate"]
    assert "route_guardian" in tos and "hazard_sentinel" in tos and "prep" in tos
    decision = next(t for t in trace if t["kind"] == "decision")
    assert decision["action"] == "advisory"


def test_chat_intent_routes_the_guardian_chips():
    assert agentic.chat_intent("Where can I get water or food nearby?") == "nearby"
    assert agentic.chat_intent("Nearest ATM and pharmacy?") == "nearby"
    assert agentic.chat_intent("Find me a safe place to wait") == "harbor"
    assert agentic.chat_intent("Is my route safe right now?") == "status"
    assert agentic.chat_intent("What should I pack for the mountains?") is None


def test_cites_from_nearby_places_are_clickable():
    cites = agentic.cites_from_tool("find_nearby", {
        "query": "water",
        "places": [
            {"name": "Bisleri store", "lat": 12.97, "lng": 77.60, "address": "MG Road"},
            {"name": "Cafe", "lat": 12.98, "lng": 77.61},
        ],
    })
    labels = [c["label"] for c in cites]
    assert "Google Places" in labels
    store = next(c for c in cites if c["label"] == "Bisleri store")
    assert store["url"].startswith("https://www.google.com/maps")
    assert "12.97" in store["url"]


def test_cites_from_mobility_keep_provider_urls():
    cites = agentic.cites_from_tool("get_mobility_options", {
        "options": [
            {"provider": "Uber", "kind": "cab",
             "url": "https://m.uber.com/ul/?action=setPickup"},
        ],
    })
    uber = next(c for c in cites if c["label"] == "Uber")
    assert uber["url"].startswith("https://m.uber.com")


def test_cite_plan_has_clickable_urls():
    from safejourney.sources import cite_plan
    plan = {
        "routes": [
            {"route_id": "g0", "meta": {"source": "google-directions"},
             "hazards": [{"source": "open-meteo"}, {"source": "gdacs"}]},
        ],
        "conditions": {"source": "open-meteo"},
    }
    origin, dest = (12.97, 77.60), (12.96, 77.75)
    cites = cite_plan(plan, origin, dest)
    ids = {c["id"] for c in cites}
    assert "open-meteo" in ids and "gdacs" in ids and "google-directions" in ids
    maps = next(c for c in cites if c["id"] == "google-directions")
    assert maps["url"].startswith("https://www.google.com/maps/dir/")
    meteo = next(c for c in cites if c["id"] == "open-meteo")
    assert meteo["url"].startswith("http")
