"""Trip planning + route pre-detection.

Given an origin/destination/mode, produce candidate routes, scan each corridor for hazards,
score them, and return them safety-ranked with human-readable summaries and precautions.
"""

from __future__ import annotations

from safejourney_shared.hazards import Hazard, HazardType, Severity, SEVERITY_SCORE
from safejourney_shared.scoring import ScoredRoute, rank_routes, route_is_blocking, safety_score, classify_score

from ..tools.route import plan_routes
from ..tools.hazard_scan import scan_corridor
from .precautions import precautions_for


def _summary(hazards: list[Hazard], rating: str) -> str:
    if not hazards:
        return "No active hazards detected on this route."
    top = sorted(hazards, key=lambda h: SEVERITY_SCORE[h.severity], reverse=True)[:3]
    parts = [f"{h.type.value.replace('_', ' ')} ({h.severity.value})" for h in top]
    lead = {
        "safe": "Looks clear",
        "caution": "Minor hazards",
        "risky": "Notable hazards",
        "dangerous": "Serious hazards",
    }.get(rating, "Hazards")
    return f"{lead}: " + ", ".join(parts) + ("." if len(hazards) <= 3 else f", +{len(hazards) - 3} more.")


def score_route(
    route: dict,
    mode: str = "two_wheeler",
    risk_tolerance: float = 1.0,
) -> ScoredRoute:
    hazards = scan_corridor(route["points"])
    score = safety_score(hazards, mode=mode, risk_tolerance=risk_tolerance)
    rating = classify_score(score)
    return ScoredRoute(
        route_id=route["route_id"],
        score=score,
        hazards=hazards,
        blocking=route_is_blocking(hazards),
        summary=_summary(hazards, rating),
        encoded_polyline=route["encoded_polyline"],
        distance_m=route.get("distance_m", 0),
        duration_s=route.get("duration_s", 0),
        meta={"source": route.get("source", ""), "points": route["points"]},
    )


def plan_and_score(
    origin: tuple[float, float],
    dest: tuple[float, float],
    mode: str = "two_wheeler",
    risk_tolerance: float = 1.0,
) -> dict:
    """Return safety-ranked candidate routes + a recommendation."""
    candidates = plan_routes(origin, dest, mode)
    scored = [score_route(c, mode, risk_tolerance) for c in candidates]
    ranked = rank_routes(scored)

    recommended = ranked[0] if ranked else None
    all_blocking = bool(ranked) and all(r.blocking for r in ranked)

    result = {
        "routes": [r.to_dict() for r in ranked],
        "recommended_route_id": recommended.route_id if recommended else None,
        "all_routes_blocked": all_blocking,
        "advice": _plan_advice(ranked, all_blocking),
        "precautions": precautions_for(
            [h.type for h in (recommended.hazards if recommended else [])]
        ),
    }
    return result


def _plan_advice(ranked: list[ScoredRoute], all_blocking: bool) -> str:
    if not ranked:
        return "Could not compute a route. Check the locations and try again."
    best = ranked[0]
    if all_blocking:
        return (
            "Every route currently has a critical hazard. Consider delaying, switching mode, "
            "or waiting at a safe place — see precautions. If you must travel, proceed with "
            "extreme caution and keep live location sharing on."
        )
    rating = classify_score(best.score)
    if rating == "safe":
        return f"Recommended route looks clear. {len(ranked)} option(s) checked."
    return (
        f"Recommended the safest of {len(ranked)} route(s) ({rating}). "
        "Follow the precautions below, and I'll keep watching the road as you go."
    )
