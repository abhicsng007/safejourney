"""Decision engine — given the hazards newly present on the road ahead, decide what to do:
stay silent, advise a precaution, reroute, divert to a safe harbour, or escalate.

Deterministic rules make the call (safe, testable, demo-reliable). Gemini optionally
rewrites the message into warm, specific, situation-aware language.
"""

from __future__ import annotations

from dataclasses import dataclass

from safejourney_shared.hazards import Hazard, HazardType, Severity, SEVERITY_SCORE
from safejourney_shared.models import AlertAction, Trip

from .precautions import precautions_for
from ..config import get_settings


@dataclass
class Decision:
    action: AlertAction
    severity: Severity
    title: str
    message: str
    precautions: list[str]
    hazard_types: list[str]


def _top(hazards: list[Hazard]) -> Hazard:
    return max(hazards, key=lambda h: h.base_score)


def _template_message(action: AlertAction, top: Hazard, count: int) -> tuple[str, str]:
    ht = top.type.value.replace("_", " ")
    if action == AlertAction.REROUTE:
        return (
            f"Rerouting you around {ht}",
            f"A {top.severity.value} {ht} is on the road ahead — {top.description} "
            "I've found a safer way and updated your route.",
        )
    if action == AlertAction.HARBOR:
        return (
            f"Pull over — {ht} ahead",
            f"{top.description} It isn't safe to continue right now. Head to the nearest safe "
            "place I've marked and wait; I'll tell you when it clears.",
        )
    if action == AlertAction.SOS:
        return (
            "Are you okay? Escalating",
            f"A {top.severity.value} {ht} is on your path and you may be in danger. "
            "I'm getting ready to alert your contacts and share your live location.",
        )
    # advisory
    extra = f" (+{count - 1} more)" if count > 1 else ""
    return (
        f"Heads up: {ht} ahead{extra}",
        f"{top.description} Take the precautions below as you pass through.",
    )


def decide(
    new_hazards: list[Hazard],
    trip: Trip,
    reroute_available: bool,
    narrate: bool = True,
) -> Decision | None:
    """Return a Decision, or None to stay silent (nothing new worth interrupting for).

    `narrate=False` skips the Gemini message rewrite — used when the agentic layer will make
    its own LLM call, so we never pay for two Gemini round-trips per decision.
    """
    if not new_hazards:
        return None

    top = _top(new_hazards)
    blocking = [h for h in new_hazards if h.is_blocking]
    max_sev = max(new_hazards, key=lambda h: SEVERITY_SCORE[h.severity]).severity
    htypes = sorted({h.type.value for h in new_hazards})

    # --- choose action ---
    if blocking:
        action = AlertAction.REROUTE if reroute_available else AlertAction.HARBOR
        severity = Severity.CRITICAL
    elif max_sev == Severity.HIGH:
        # High but not a hard-block: strong advisory; harbour if it's the exposure-heavy
        # combo of lightning/flood for an exposed traveller.
        exposed = trip.mode.value in {"walk", "two_wheeler"}
        wet_or_bolt = top.type in {HazardType.LIGHTNING, HazardType.FLOOD}
        action = AlertAction.HARBOR if (exposed and wet_or_bolt) else AlertAction.ADVISORY
        severity = Severity.HIGH
    elif max_sev in (Severity.MODERATE, Severity.LOW):
        action = AlertAction.ADVISORY
        severity = max_sev
    else:
        return None  # info-only

    title, message = _template_message(action, top, len(new_hazards))
    precs = precautions_for([h.type for h in new_hazards])

    decision = Decision(
        action=action,
        severity=severity,
        title=title,
        message=message,
        precautions=precs,
        hazard_types=htypes,
    )
    if narrate:
        _maybe_narrate(decision, trip, top)
    return decision


def _maybe_narrate(decision: Decision, trip: Trip, top: Hazard) -> None:
    """Optionally use Gemini to rephrase the message. Never fails the decision."""
    s = get_settings()
    if not s.gemini_available:
        return
    try:
        from ..agents.llm import narrate_alert  # lazy; needs google-genai/ADK

        better = narrate_alert(
            action=decision.action.value,
            hazard=top.to_dict(),
            mode=trip.mode.value,
            base_message=decision.message,
        )
        if better:
            decision.message = better
    except Exception as e:  # pragma: no cover
        print(f"[decision] narration skipped ({e})")
