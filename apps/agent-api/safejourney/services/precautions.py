"""Hazard-specific safety guidance — the life-saving domain knowledge, encoded once.

Each hazard type maps to concrete, do-this-now precautions grounded in how people actually
get killed (waterlogging + live poles, sheltering under trees in lightning, etc.).
"""

from __future__ import annotations

from safejourney_shared.hazards import HazardType

PRECAUTIONS: dict[HazardType, list[str]] = {
    HazardType.FLOOD: [
        "Do not enter waterlogged underpasses or roads — depth is deceptive and currents pull.",
        "Stay away from electric poles, streetlights and junction boxes in standing water.",
        "If water is flowing over the road, turn back — 15 cm of moving water can sweep you off.",
    ],
    HazardType.WATERLOGGING: [
        "Avoid puddles hiding potholes or open manholes.",
        "Keep clear of lamp posts and metal poles standing in water.",
        "Ride slow; brakes are weak when wet.",
    ],
    HazardType.ELECTROCUTION: [
        "Do NOT step into or touch water near any pole, wire or metal box here.",
        "Assume every fallen wire is live. Keep at least 10 m away.",
        "Warn others nearby and report it; wait for the utility to isolate power.",
    ],
    HazardType.LIGHTNING: [
        "Get off open ground and away from the tallest objects.",
        "Do NOT shelter under trees or beside metal poles — move indoors or into a vehicle.",
        "Stay put 30 minutes after the last thunder before continuing.",
    ],
    HazardType.STORM: [
        "Watch for falling branches, hoardings and loose sheets.",
        "Reduce speed and increase following distance in gusts.",
        "If wind is severe, pull into a sheltered, sturdy spot and wait.",
    ],
    HazardType.HEAT: [
        "Carry and sip water; avoid direct sun during the peak window.",
        "Take shaded breaks; watch for dizziness or cramps (early heatstroke).",
        "Prefer covered or air-conditioned transit if available.",
    ],
    HazardType.LANDSLIDE: [
        "Do not stop under steep or freshly-cut slopes.",
        "Watch for fallen rocks, cracks or mud on the road and turn back if unsure.",
        "Cross vulnerable stretches quickly; never during or right after heavy rain.",
    ],
    HazardType.GLOF: [
        "This valley can flood suddenly from upstream — do not camp or halt near the riverbed.",
        "Know the high ground on your route; move to it at the first roar or rise in water.",
        "Heed local siren/警 warnings and official advisories immediately.",
    ],
    HazardType.ROADWORK: [
        "Expect diversions, loose gravel and narrowed lanes — slow down.",
        "Watch for unmarked edges and workers on the carriageway.",
    ],
    HazardType.POTHOLE: [
        "Broken road / open pit ahead — slow and keep both hands ready.",
        "Do not swerve blindly; check your blind spot before avoiding it.",
    ],
    HazardType.UNLIT: [
        "Dark stretch ahead — use lights, stay visible, avoid stopping.",
        "Prefer the better-lit alternative if offered.",
    ],
    HazardType.BLACKSPOT: [
        "Accident-prone stretch — cut speed, no overtaking.",
        "Anticipate sudden merges and pedestrians.",
    ],
    HazardType.SHARP_TURN: [
        "Sharp bend ahead — slow before the turn, not in it.",
        "Stay in your lane; oncoming traffic can cut the corner.",
        "Sound your horn on blind hairpins in the hills.",
    ],
    HazardType.RAIL_CROSSING: [
        "Unmanned crossing — stop, look both ways, cross only when clearly safe.",
    ],
    HazardType.ACCIDENT: [
        "Crash reported ahead — approach slowly, expect stopped traffic and responders.",
    ],
    HazardType.UNSAFE_AREA: [
        "Isolated/less-safe stretch — keep moving, stay on lit main roads, share your live location.",
    ],
    HazardType.OTHER: [
        "Proceed with heightened caution through this stretch.",
    ],
}


def precautions_for(types: list[HazardType], limit: int = 5) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for t in types:
        for p in PRECAUTIONS.get(t, []):
            if p not in seen:
                out.append(p)
                seen.add(p)
    return out[:limit]
