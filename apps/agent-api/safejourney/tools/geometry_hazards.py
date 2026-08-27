"""Route-geometry hazards — sharp bends / hairpins detected from the polyline itself.

No external call: we walk the route, measure the heading change at each vertex, and flag
road-scale turns above a threshold. Cheap, offline, and it lights up exactly where it should
— the hairpins on a mountain route (e.g. Rishikesh→Joshimath) rather than ordinary city
corners.
"""

from __future__ import annotations

from safejourney_shared.geo import angle_diff_deg, bearing_deg, haversine_m
from safejourney_shared.hazards import Hazard, HazardType, Severity

# Only consider a vertex a real road turn when the segments meeting it are long enough that
# it isn't just dense-polyline wiggle, and the heading change is genuinely sharp.
_MIN_SEG_M = 45.0
_SHARP_DEG = 55.0        # below this: a normal bend, ignored
_HAIRPIN_DEG = 100.0     # at/above this: a hairpin — bumped severity
_MAX_TURNS = 4           # cap so a windy route doesn't spam identical warnings


def sharp_turn_hazards(points: list[tuple[float, float]], max_turns: int = _MAX_TURNS) -> list[Hazard]:
    if len(points) < 3:
        return []
    candidates: list[tuple[float, Hazard]] = []  # (turn_deg, hazard) for ranking
    for (a, b, c) in zip(points, points[1:], points[2:]):
        in_len = haversine_m(a[0], a[1], b[0], b[1])
        out_len = haversine_m(b[0], b[1], c[0], c[1])
        if in_len < _MIN_SEG_M or out_len < _MIN_SEG_M:
            continue
        turn = angle_diff_deg(bearing_deg(*a, *b), bearing_deg(*b, *c))
        if turn < _SHARP_DEG:
            continue
        if turn >= _HAIRPIN_DEG:
            sev, word = Severity.MODERATE, "Hairpin bend"
        else:
            sev, word = Severity.LOW, "Sharp bend"
        h = Hazard(
            HazardType.SHARP_TURN, sev, b[0], b[1], "geometry",
            f"{word} (~{turn:.0f}°) — likely blind; slow well before it.",
            offset_m=0.0,
        )
        candidates.append((turn, h))
    # Keep the sharpest few so the warning stays meaningful.
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [h for _, h in candidates[:max_turns]]
