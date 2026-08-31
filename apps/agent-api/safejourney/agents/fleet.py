"""The SafeJourney multi-agent fleet (Google ADK).

Guardian Core is the root orchestrator; it delegates to specialist sub-agents. All are
constructed lazily so importing this module never requires ADK to be installed — call
`build_guardian()` (which raises a clear error if ADK is missing) or `run_guardian()`.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Optional

from ..config import get_settings


def _adk():
    """Import ADK, raising a friendly error if it isn't available."""
    try:
        from google.adk.agents import Agent  # noqa: F401
        import google.adk  # noqa: F401
        return True
    except Exception as e:
        raise RuntimeError(
            "Google ADK is not installed/available. `pip install google-adk` and set "
            "Gemini credentials (GOOGLE_API_KEY or Vertex project) to use the agent fleet."
        ) from e


PREP_INSTRUCTION = """You are the Prep Agent. Before a trip you help the traveller leave
safely: given the destination, mode and current conditions, decide go / wait / leave-earlier,
and give a short readiness checklist (documents, water, umbrella, power bank, helmet).
Use plan_safe_routes to understand the route and its hazards. Be concise and specific."""

ROUTE_GUARDIAN_INSTRUCTION = """You are the Route Guardian. You compare routes on SAFETY,
not just speed. Call plan_safe_routes, then recommend the safest viable route, explain why
in one sentence, and list the top precautions. If every route is blocked, say so and advise
waiting or changing mode."""

SAFE_HARBOR_INSTRUCTION = """You are the Safe Harbor Agent. When it isn't safe to continue,
call get_safe_harbors for the traveller's location and recommend the single best nearby
refuge (prefer staffed, sheltered, lit places), with its distance and why it's safe."""

MOBILITY_INSTRUCTION = """You are the Mobility Agent. When the current plan breaks, suggest
safer alternatives (metro, bus, cab) with brief trade-offs on safety and time. Keep it short."""

SOS_INSTRUCTION = """You are the SOS/Guardian Agent. In a dangerous situation, calmly guide
first-response steps, confirm before escalating, and remind the traveller their live location
can be shared with trusted contacts and 112. Never panic the user."""

CORE_INSTRUCTION = """You are SafeJourney's Guardian Core — a calm, protective travel
companion for riders in India. Your goal: get the traveller to their destination safely.

Delegate to your specialists:
- Prep for pre-trip readiness and timing.
- Route Guardian to choose the safest route.
- Safe Harbor when the traveller must wait somewhere safe.
- Mobility when the plan must change (transit/cab).
- SOS for danger and escalation.

When the traveller asks where to GET or FIND anything — water, food, a meal, a pharmacy or
medicine, an ATM/cash, fuel, a restroom, tea/coffee, a repair shop — call find_nearby with a
plain-words query and the traveller's CURRENT position from the CONTEXT block, then reply with
the two or three closest options: name, how far, and direction if useful. Don't ask for their
location; it's in the context.

Use tools to ground every claim in real data — never invent hazards or places. Interrupt only
when it matters; be brief, specific, and lead with the action. Speak the traveller's language if
they switch. When conditions are dangerous, prioritise their safety over saving time."""

# Lean chat path: one agent, one tool round, no specialist hop. The Ask Guardian UI still
# shows the tool/citation trace; we just don't pay for extra Gemini 3 thinking hops.
CHAT_INSTRUCTION = """You are SafeJourney's on-road Guardian. Answer THIS traveller, now.

Call at most ONE tool, then reply in 2–4 short sentences. Lead with the action.
- find_nearby — water, food, ATM, pharmacy, fuel, restroom, tea (use CURRENT lat/lng from CONTEXT)
- get_safe_harbors — a place to wait out a hazard
- get_mobility_options — cab / metro alternatives
- get_precautions — how to stay safe given hazard types already in CONTEXT

Do NOT replan routes. Do NOT rescan the road. CONTEXT already has the latest hazards and
safety score — use it. Never invent places or hazards. Don't ask for their location."""


def _chat_generate_config():
    """Low-thinking, short replies — Ask Guardian should feel instant, not like a planner."""
    try:
        from google.genai import types
        kw = {}
        if hasattr(types, "ThinkingConfig"):
            try:
                kw["thinking_config"] = types.ThinkingConfig(thinking_level="low")
            except Exception:
                pass
        return types.GenerateContentConfig(temperature=0.3, max_output_tokens=512, **kw)
    except Exception:
        return None


@lru_cache
def build_guardian():
    """Build and cache the Guardian Core agent with its sub-agents."""
    _adk()
    from google.adk.agents import Agent

    from .adk_tools import (
        plan_safe_routes,
        scan_route_hazards,
        get_safe_harbors,
        find_nearby,
        get_mobility_options,
        check_trip_now,
        get_precautions,
        report_incident,
    )

    s = get_settings()
    model = s.gemini_model

    prep = Agent(name="prep", model=model, description="Pre-trip readiness & timing.",
                 instruction=PREP_INSTRUCTION, tools=[plan_safe_routes, get_precautions])
    route_guardian = Agent(name="route_guardian", model=model,
                           description="Safety-ranked route selection.",
                           instruction=ROUTE_GUARDIAN_INSTRUCTION,
                           tools=[plan_safe_routes, scan_route_hazards, get_precautions])
    safe_harbor = Agent(name="safe_harbor", model=model, description="Nearest safe refuge.",
                        instruction=SAFE_HARBOR_INSTRUCTION, tools=[get_safe_harbors])
    mobility = Agent(name="mobility", model=model, description="Transit/cab alternatives.",
                     instruction=MOBILITY_INSTRUCTION,
                     tools=[get_mobility_options, get_safe_harbors])
    sos = Agent(name="sos", model=model, description="Danger guidance & escalation.",
                instruction=SOS_INSTRUCTION, tools=[get_safe_harbors])

    guardian = Agent(
        name="guardian_core",
        model=model,
        description="SafeJourney orchestrator that keeps travellers safe end to end.",
        instruction=CORE_INSTRUCTION,
        sub_agents=[prep, route_guardian, safe_harbor, mobility, sos],
        tools=[plan_safe_routes, scan_route_hazards, check_trip_now,
               get_safe_harbors, find_nearby, get_mobility_options, get_precautions, report_incident],
    )
    return guardian


@lru_cache
def build_chat_guardian():
    """Single-agent Guardian for Ask Guardian — same tools, no sub-agent delegation.

    The full fleet (`build_guardian`) is right for planning / ADK web, but each
    transfer_to_agent is another Gemini 3 thinking round-trip. Chat only needs one hop.
    """
    _adk()
    from google.adk.agents import Agent

    from .adk_tools import (
        get_safe_harbors,
        find_nearby,
        get_mobility_options,
        get_precautions,
    )

    s = get_settings()
    kwargs = dict(
        name="guardian_core",
        model=s.gemini_model,
        description="Fast on-road Guardian for chat.",
        instruction=CHAT_INSTRUCTION,
        tools=[find_nearby, get_safe_harbors, get_mobility_options, get_precautions],
    )
    cfg = _chat_generate_config()
    if cfg is not None:
        kwargs["generate_content_config"] = cfg
    return Agent(**kwargs)


# Expose `root_agent` so the `adk web` / `adk run` dev tools can discover the fleet.
def _root_agent_or_none():
    try:
        return build_guardian()
    except Exception:
        return None


def run_guardian(message: str, session_id: str = "default", user_id: str = "local") -> str:
    """Run one turn through the Guardian Core and return its text reply.

    Uses an in-memory session; for production wire ADK's session service to Firestore.
    """
    guardian = build_guardian()
    from google.adk.runners import Runner
    from google.adk.sessions import InMemorySessionService
    from google.genai import types

    session_service = InMemorySessionService()
    runner = Runner(agent=guardian, app_name="safejourney", session_service=session_service)
    try:
        session_service.create_session_sync(app_name="safejourney", user_id=user_id, session_id=session_id)
    except Exception:
        pass  # session may already exist

    content = types.Content(role="user", parts=[types.Part(text=message)])
    final = ""
    for event in runner.run(user_id=user_id, session_id=session_id, new_message=content):
        if event.is_final_response() and event.content and event.content.parts:
            final = "".join(p.text or "" for p in event.content.parts)
    return final or "(no response)"
