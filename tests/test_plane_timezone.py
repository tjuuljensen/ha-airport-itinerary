"""Tests for optional live-aircraft timezone resolution."""

from custom_components.airport_aware_itinerary.plane_timezone import timezone_for_coordinates


def test_plane_coordinates_resolve_to_local_timezone():
    assert timezone_for_coordinates(55.6181, 12.6560) == "Europe/Copenhagen"


def test_invalid_coordinates_have_no_timezone():
    assert timezone_for_coordinates("not-a-number", 12.0) is None
    assert timezone_for_coordinates(91, 12.0) is None
