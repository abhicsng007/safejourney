"""Alternative mobility options — what to do when the current plan breaks.

Returns tappable cab deep-links (Uber, Ola), a transit directions link, and the nearest
stations. Deep-links use each app's public URL scheme, so there are no paid APIs or keys —
they open the installed app (or its site) with the pickup/drop pre-filled.
"""

from __future__ import annotations

from urllib.parse import quote

from .places import nearest_station, find_safe_harbors


def _cab_links(olat: float, olng: float, dlat: float | None, dlng: float | None) -> list[dict]:
    uber = (
        f"https://m.uber.com/ul/?action=setPickup&pickup[latitude]={olat}&pickup[longitude]={olng}"
    )
    ola = f"https://book.olacabs.com/?serviceType=p2p&utm_source=safejourney&lat={olat}&lng={olng}"
    if dlat is not None and dlng is not None:
        uber += f"&dropoff[latitude]={dlat}&dropoff[longitude]={dlng}"
        ola += f"&drop_lat={dlat}&drop_lng={dlng}"
    return [
        {"provider": "Uber", "kind": "cab", "url": uber,
         "why": "Door-to-door; get out of the hazard fast."},
        {"provider": "Ola", "kind": "cab", "url": ola,
         "why": "Cabs and autos; widely available in Indian cities."},
    ]


def _transit_link(olat: float, olng: float, dlat: float | None, dlng: float | None) -> dict | None:
    if dlat is None or dlng is None:
        return None
    url = (
        "https://www.google.com/maps/dir/?api=1"
        f"&origin={quote(f'{olat},{olng}')}&destination={quote(f'{dlat},{dlng}')}&travelmode=transit"
    )
    return {"provider": "Public transit", "kind": "transit", "url": url,
            "why": "Metro/bus is sheltered and unaffected by waterlogged roads."}


def mobility_options(
    lat: float, lng: float, dest_lat: float | None = None, dest_lng: float | None = None
) -> dict:
    """Safer ways to continue from the current point: cabs, transit, and nearby stations."""
    options = _cab_links(lat, lng, dest_lat, dest_lng)
    transit = _transit_link(lat, lng, dest_lat, dest_lng)
    if transit:
        options.append(transit)
    station = nearest_station(lat, lng)
    harbors = [h for h in find_safe_harbors(lat, lng, limit=3)]
    return {
        "options": options,
        "nearest_station": station,
        "safe_harbors": harbors,
    }
