"""The agentic layer — puts Gemini reasoning on the critical path, grounded on the same
tools the deterministic services use.

Three entry points:
  * run_agent_trace  — one turn through the ADK Guardian fleet, returning the reply PLUS a
                       structured trace of the tools it called (powers the UI reasoning panel).
  * agentic_decision — the monitor's action choice, made by Gemini and validated against the
                       rule engine (which stays the safe floor + fallback).
  * plan_reasoning   — a short, grounded "why this route" narrative over a computed plan.

Everything degrades to the deterministic path when Gemini/ADK is unavailable, so the demo
never breaks.
"""

from __future__ import annotations

from typing import Optional

from safejourney_shared.hazards import Hazard, Severity
from safejourney_shared.models import AlertAction, Trip

from ..config import get_settings
from .decision import Decision, decide
from .precautions import precautions_for


# ---------------------------------------------------------------------------
# 1. Agent chat with a visible tool-call trace
# ---------------------------------------------------------------------------

_session_service = None


def _get_session_service():
    """A process-lifetime in-memory session service, so a session_id keeps its memory
    across chat turns and monitoring ticks within a running server. (Production step:
    swap for a Firestore/Vertex-backed ADK session service — see docs/architecture.md.)"""
    global _session_service
    if _session_service is None:
        from google.adk.sessions import InMemorySessionService

        _session_service = InMemorySessionService()
    return _session_service


def _summarize_tool_result(response) -> str:
    """Compress a tool's raw response into one human line for the trace panel."""
    if isinstance(response, dict):
        if "routes" in response:
            n = len(response.get("routes") or [])
            rec = response.get("recommended_route_id")
            return f"{n} route(s) scored; recommended {rec}."
        if "hazards" in response:
            hz = response.get("hazards") or []
            kinds = sorted({h.get("type") for h in hz if isinstance(h, dict)})
            return f"{len(hz)} hazard(s): {', '.join(kinds) or 'none'}."
        if "harbors" in response:
            return f"{len(response.get('harbors') or [])} safe harbour(s) nearby."
        if "precautions" in response:
            return f"{len(response.get('precautions') or [])} precaution(s)."
        keys = ", ".join(list(response.keys())[:4])
        return f"returned {{{keys}}}"
    text = str(response)
    return text[:160] + ("…" if len(text) > 160 else "")


def _trip_context(trip_id: str) -> str:
    """A compact, grounded snapshot of the active trip, prepended to the chat so Guardian
    answers about *this* journey instead of asking for origin/destination."""
    if not trip_id:
        return ""
    from ..repo import get_repo

    repo = get_repo()
    trip = repo.get_trip(trip_id)
    if not trip:
        return ""
    pos = trip.current_position or trip.origin
    lines = [
        "CONTEXT — the traveller is on this active trip (use it; don't ask for it again):",
        f"- trip_id: {trip.id}",
        f"- mode: {trip.mode.value}",
        f"- from: {trip.origin_label or f'{trip.origin.lat:.4f},{trip.origin.lng:.4f}'}",
        f"- to: {trip.destination_label or f'{trip.destination.lat:.4f},{trip.destination.lng:.4f}'}",
        f"- current position: {pos.lat:.5f},{pos.lng:.5f}",
        f"- status: {trip.status.value}",
    ]
    snap = repo.get_snapshot(trip.last_snapshot_id) if trip.last_snapshot_id else None
    if snap:
        if snap.hazards:
            hz = "; ".join(
                f"{h.get('type')}({h.get('severity')})" for h in snap.hazards[:6]
            )
            lines.append(f"- road ahead ({len(snap.hazards)} hazard(s), safety score "
                         f"{round(snap.safety_score, 1)}): {hz}")
        else:
            lines.append(f"- road ahead: clear (safety score {round(snap.safety_score, 1)})")
    lines.append("For the freshest read, call check_trip_now with this trip_id. "
                 "Answer directly and specifically about this route.")
    return "\n".join(lines) + "\n\n"


def run_agent_trace(
    message: str,
    session_id: str = "default",
    user_id: str = "local",
    trip_id: str = "",
) -> dict:
    """Run one turn through the Guardian Core fleet and capture a structured trace.

    Returns {reply, trace, agent}. `trace` is an ordered list of tool_call / tool_result
    steps the agent took — the visible evidence of grounded, agentic behaviour. When
    `trip_id` is given, the active trip's context is prepended so Guardian answers about it.
    Raises RuntimeError (from build_guardian) if ADK/Gemini isn't configured.
    """
    from ..agents.fleet import build_guardian

    guardian = build_guardian()  # raises a friendly error if ADK is missing
    from google.adk.runners import Runner
    from google.genai import types

    session_service = _get_session_service()
    runner = Runner(agent=guardian, app_name="safejourney", session_service=session_service)
    try:
        session_service.create_session_sync(
            app_name="safejourney", user_id=user_id, session_id=session_id
        )
    except Exception:
        pass  # session already exists — keep its memory

    prompt = _trip_context(trip_id) + message
    content = types.Content(role="user", parts=[types.Part(text=prompt)])
    trace: list[dict] = []
    reply = ""
    for event in runner.run(user_id=user_id, session_id=session_id, new_message=content):
        author = getattr(event, "author", "guardian_core") or "guardian_core"
        parts = (event.content.parts if event.content else None) or []
        for p in parts:
            fc = getattr(p, "function_call", None)
            fr = getattr(p, "function_response", None)
            if fc is not None:
                name = getattr(fc, "name", "tool")
                args = dict(getattr(fc, "args", {}) or {})
                # ADK delegates by calling the special `transfer_to_agent` tool. Surface it
                # as a first-class delegation step — the visible multi-agent hand-off.
                if name == "transfer_to_agent":
                    trace.append({
                        "kind": "delegate",
                        "from": author,
                        "to": args.get("agent_name") or args.get("agent") or "specialist",
                    })
                else:
                    trace.append({
                        "kind": "tool_call",
                        "name": name,
                        "args": args,
                        "agent": author,
                    })
            if fr is not None:
                name = getattr(fr, "name", "tool")
                if name == "transfer_to_agent":
                    continue  # the delegate step already conveys this
                trace.append({
                    "kind": "tool_result",
                    "name": name,
                    "summary": _summarize_tool_result(getattr(fr, "response", None)),
                    "agent": author,
                })
        if event.is_final_response() and parts:
            reply = "".join(getattr(p, "text", "") or "" for p in parts)
    return {"reply": reply or "(no response)", "trace": trace, "agent": "guardian_core"}


# ---------------------------------------------------------------------------
# 2. Agentic monitor decision (Gemini decides; rules validate + fall back)
# ---------------------------------------------------------------------------

_VALID_ACTIONS = {a.value for a in AlertAction}


def agentic_decision(
    new_hazards: list[Hazard],
    trip: Trip,
    reroute_available: bool,
) -> Optional[Decision]:
    """Decide the response to newly-appeared hazards.

    The deterministic rule engine (`decide`) is computed first as the grounded safe floor and
    validator. When Gemini is available it may refine the action and rewrite the message; the
    result is validated (a hallucinated or unsafe action is rejected back to the baseline).
    Returns None to stay silent (nothing worth interrupting for) — matching `decide`.
    """
    s = get_settings()
    # When Gemini is up, the agentic layer writes the message — so skip the baseline's own
    # narration call (no double round-trip). When it's down, let the baseline narrate.
    baseline = decide(new_hazards, trip, reroute_available, narrate=not s.gemini_available)
    if baseline is None:
        return None

    if not s.gemini_available:
        return baseline  # rule engine already narrated

    try:
        from ..agents.llm import decide_action_llm

        out = decide_action_llm(
            hazards=[h.to_dict() for h in new_hazards],
            mode=trip.mode.value,
            reroute_available=reroute_available,
            baseline_action=baseline.action.value,
        )
    except Exception as e:  # pragma: no cover
        print(f"[agentic] decision LLM failed ({e}); using rule baseline.")
        return baseline

    if not out:
        return baseline

    action = _validate_action(out.get("action"), reroute_available, baseline.action)
    title = (out.get("title") or baseline.title).strip()[:80]
    message = (out.get("message") or baseline.message).strip()
    reason = (out.get("reason") or "").strip()

    baseline.action = action
    baseline.title = title
    baseline.message = message
    # Precautions stay grounded in the encoded domain knowledge, keyed on the real hazards.
    baseline.precautions = precautions_for([h.type for h in new_hazards])
    if reason:
        # Surface the agent's rationale so the UI/trace can show *why*.
        baseline.__dict__["reason"] = reason
    return baseline


def _validate_action(
    raw: Optional[str], reroute_available: bool, fallback: AlertAction
) -> AlertAction:
    """Reject a hallucinated or unsafe action, snapping back to the rule-engine choice."""
    if not raw or raw not in _VALID_ACTIONS:
        return fallback
    action = AlertAction(raw)
    if action == AlertAction.REROUTE and not reroute_available:
        return fallback  # can't reroute when there's no safer path
    if action == AlertAction.CLEAR:
        return fallback  # CLEAR is emitted elsewhere, never as a hazard response
    return action


# ---------------------------------------------------------------------------
# 3. Grounded "why this route" reasoning for the plan screen
# ---------------------------------------------------------------------------

def plan_reasoning(plan: dict, mode: str) -> Optional[dict]:
    """A short natural-language rationale for the recommended route, grounded strictly in the
    already-computed plan. Returns {summary, provenance} or None when Gemini is unavailable."""
    s = get_settings()
    provenance = _provenance(plan)
    if not s.gemini_available:
        return {"summary": plan.get("advice", ""), "provenance": provenance} if provenance else None

    routes = plan.get("routes") or []
    if not routes:
        return None
    lines = []
    for r in routes:
        hz = ", ".join(sorted({h.get("type") for h in (r.get("hazards") or [])})) or "clear"
        lines.append(
            f"- {r.get('route_id')}: score {r.get('score')} ({r.get('rating')}), "
            f"{round((r.get('distance_m') or 0) / 1000, 1)} km, hazards: {hz}"
            + (" [recommended]" if r.get("route_id") == plan.get("recommended_route_id") else "")
        )
    prompt = (
        f"Traveller mode: {mode}\nRoutes considered (lower score = safer):\n"
        + "\n".join(lines)
        + "\n\nIn 1-2 sentences, explain to the traveller why the recommended route is the "
        "safest choice and the single most important precaution. Ground every claim in the "
        "data above; do not invent hazards. Plain, calm, no emojis."
    )
    try:
        from ..agents.llm import generate

        summary = generate(prompt, max_tokens=220)
    except Exception as e:  # pragma: no cover
        print(f"[agentic] plan_reasoning failed ({e})")
        summary = None
    return {"summary": summary or plan.get("advice", ""), "provenance": provenance}


def _provenance(plan: dict) -> list[str]:
    """Which real data sources grounded this plan — shown as chips so judges see it's real."""
    sources: set[str] = set()
    for r in plan.get("routes") or []:
        for h in r.get("hazards") or []:
            src = h.get("source")
            if src:
                sources.add(src.split(":")[0])
        meta_src = (r.get("meta") or {}).get("source")
        if meta_src:
            sources.add(meta_src)
    return sorted(sources)
