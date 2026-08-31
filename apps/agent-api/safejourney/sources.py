"""Catalog of real data sources SafeJourney grounds claims on.

Every cited source here is something the agents actually called (or a live Google
Search chunk). The UI turns these into clickable chips so a traveller — or a
judge — can open the evidence, not just read a label.
"""

from __future__ import annotations

# id prefix (or exact id) -> display metadata. Longer/more-specific keys first when matching.
_CATALOG: dict[str, dict] = {
    "open-meteo": {
        "label": "Open-Meteo",
        "blurb": "Live weather, visibility & air quality",
        "url": "https://open-meteo.com",
        "icon": "🌤",
    },
    "gdacs": {
        "label": "GDACS",
        "blurb": "Global disaster alerts",
        "url": "https://www.gdacs.org",
        "icon": "🚨",
    },
    "glof-basin": {
        "label": "NDMA GLOF basins",
        "blurb": "Monitored glacial-lake / cascade basins",
        "url": "https://ndma.gov.in/Natural-Hazards/Glacial-Lake-Outburst-Flood",
        "icon": "🏔",
    },
    "overpass": {
        "label": "OpenStreetMap",
        "blurb": "Road works, lighting, crossings",
        "url": "https://www.openstreetmap.org",
        "icon": "🗺",
    },
    "blackspot-db": {
        "label": "MoRTH blackspots",
        "blurb": "Recurring accident clusters",
        "url": "https://morth.nic.in/road-safety",
        "icon": "⚠",
    },
    "google-directions": {
        "label": "Google Directions",
        "blurb": "Candidate driving / walking paths",
        "url": "https://www.google.com/maps",
        "icon": "🧭",
    },
    "fallback": {
        "label": "Local router",
        "blurb": "Offline candidate paths (Maps key not configured)",
        "url": "",
        "icon": "🧭",
    },
    "google-places": {
        "label": "Google Places",
        "blurb": "Nearby harbours & essentials",
        "url": "https://developers.google.com/maps/documentation/places/web-service",
        "icon": "📍",
    },
    "google-search": {
        "label": "Google Search",
        "blurb": "Grounded web advisories",
        "url": "https://www.google.com",
        "icon": "🔎",
    },
    "web": {
        "label": "Web report",
        "blurb": "Grounded news / civic notice",
        "url": "",
        "icon": "🌐",
    },
    "geometry": {
        "label": "Route geometry",
        "blurb": "Hairpins & sharp bends on the path",
        "url": "",
        "icon": "🌀",
    },
    "report": {
        "label": "Crowd report",
        "blurb": "Traveller-filed hazard on this road",
        "url": "",
        "icon": "📣",
    },
    "crowd": {
        "label": "Crowd report",
        "blurb": "Traveller-filed hazard on this road",
        "url": "",
        "icon": "📣",
    },
    "gemini": {
        "label": "Gemini",
        "blurb": "Grounded route rationale",
        "url": "https://ai.google.dev",
        "icon": "✦",
    },
}


def source_id(raw: str) -> str:
    """Collapse 'report:crowd' / 'open-meteo' into a catalog key."""
    s = (raw or "").strip().lower()
    if not s:
        return ""
    head = s.split(":", 1)[0]
    return head


def describe(raw: str, *, origin: tuple[float, float] | None = None,
             dest: tuple[float, float] | None = None,
             url: str = "") -> dict | None:
    """A UI-ready citation dict, or None if the id is empty/unknown-with-no-url."""
    sid = source_id(raw)
    meta = _CATALOG.get(sid) or _CATALOG.get(raw or "")
    if not meta:
        if not sid and not url:
            return None
        meta = {"label": sid or "Source", "blurb": "", "url": "", "icon": "📄"}
    out = {
        "id": sid or "source",
        "label": meta["label"],
        "blurb": meta.get("blurb", ""),
        "icon": meta.get("icon", "📄"),
        "url": (url or "").strip() or meta.get("url") or "",
    }
    # Deep-link a few sources to the actual place, so a click isn't just a homepage.
    if sid == "google-directions" and origin and dest:
        out["url"] = (
            f"https://www.google.com/maps/dir/{origin[0]},{origin[1]}/{dest[0]},{dest[1]}"
        )
    elif sid == "open-meteo" and origin:
        out["url"] = (
            f"https://open-meteo.com/en/docs#latitude={origin[0]:.4f}&longitude={origin[1]:.4f}"
        )
    elif sid == "overpass" and origin:
        out["url"] = f"https://www.openstreetmap.org/#map=13/{origin[0]:.4f}/{origin[1]:.4f}"
    elif sid == "gdacs":
        out["url"] = "https://www.gdacs.org"
    return out


def cite_plan(
    plan: dict,
    origin: tuple[float, float] | None = None,
    dest: tuple[float, float] | None = None,
) -> list[dict]:
    """Deduped, clickable citations for everything that grounded this plan."""
    seen: set[str] = set()
    out: list[dict] = []
    for r in plan.get("routes") or []:
        meta_src = (r.get("meta") or {}).get("source")
        if meta_src:
            _add(out, seen, meta_src, origin, dest)
        for h in r.get("hazards") or []:
            src = h.get("source") if isinstance(h, dict) else getattr(h, "source", None)
            if src:
                _add(out, seen, src, origin, dest)
    cond = plan.get("conditions") or {}
    if cond.get("source") and cond.get("source") != "unavailable":
        _add(out, seen, cond["source"], origin, dest)
    return out


def _add(out, seen, raw, origin, dest, url: str = ""):
    d = describe(raw, origin=origin, dest=dest, url=url)
    if not d:
        return
    key = d["id"] + "|" + (d["url"] or "")
    if key in seen:
        return
    seen.add(key)
    out.append(d)
