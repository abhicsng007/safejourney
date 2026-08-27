"""Tests for the Phase D hazard detectors: sharp turns, blackspots, unlit, mobility."""

from safejourney_shared.hazards import HazardType, Severity

from safejourney.tools.geometry_hazards import sharp_turn_hazards
from safejourney.tools.blackspot import blackspot_hazards
from safejourney.tools.lighting import _is_night
from safejourney.tools.mobility import mobility_options


def test_sharp_turn_flags_hairpin():
    # East along a straight, then a sharp doubling-back turn; segments are road-scale (~150m).
    pts = [(12.9000, 77.6000), (12.9000, 77.6015), (12.9012, 77.6003)]
    hz = sharp_turn_hazards(pts)
    assert hz, "a ~130° turn on long segments must be flagged"
    assert hz[0].type == HazardType.SHARP_TURN
    assert hz[0].severity == Severity.MODERATE  # hairpin


def test_gentle_curve_not_flagged():
    # A nearly-straight path — no meaningful heading change.
    pts = [(12.9000, 77.6000), (12.9010, 77.6010), (12.9020, 77.6020)]
    assert sharp_turn_hazards(pts) == []


def test_short_wiggle_not_flagged():
    # A sharp angle but on tiny segments (polyline noise, < min segment length) — ignored.
    pts = [(12.90000, 77.60000), (12.90002, 77.60002), (12.90000, 77.60004)]
    assert sharp_turn_hazards(pts) == []


def test_blackspot_matches_route_through_silk_board():
    route = [(12.9150, 77.6090), (12.9166, 77.6101), (12.9180, 77.6112)]
    hz = blackspot_hazards(route)
    assert hz and hz[0].type == HazardType.BLACKSPOT
    assert "Silk Board" in hz[0].description


def test_blackspot_ignores_far_route():
    route = [(28.6000, 77.2000), (28.6010, 77.2010)]  # Delhi — no seeded blackspot near
    assert blackspot_hazards(route) == []


def test_night_gate():
    # Midnight UTC at lng 0 -> night; noon UTC at lng 0 -> day.
    import calendar

    midnight = calendar.timegm((2025, 6, 1, 0, 0, 0, 0, 0, 0))
    noon = calendar.timegm((2025, 6, 1, 12, 0, 0, 0, 0, 0))
    assert _is_night(0.0, midnight) is True
    assert _is_night(0.0, noon) is False


def test_mobility_returns_cab_and_transit_links():
    mob = mobility_options(12.9166, 77.6101, 12.97, 77.75)
    providers = [o["provider"] for o in mob["options"]]
    assert "Uber" in providers and "Ola" in providers and "Public transit" in providers
    assert all(o["url"].startswith("http") for o in mob["options"])
    assert mob["nearest_station"] is not None


def test_mobility_without_destination_has_no_transit():
    mob = mobility_options(12.9166, 77.6101)
    assert all(o["kind"] != "transit" for o in mob["options"])
