"""Tests for bundled airport coordinates and source-map generation."""

import json

import pytest

from custom_components.airport_aware_itinerary.airport_data import (
    get_airport_coordinates,
)
from scripts.update_airport_timezones import build_maps


def test_bundled_airport_coordinates_are_available_for_major_airports():
    coordinates = get_airport_coordinates()

    assert coordinates["CPH"]["latitude"] == pytest.approx(55.618, abs=0.1)
    assert coordinates["CPH"]["longitude"] == pytest.approx(12.656, abs=0.1)
    assert -90 <= coordinates["LAX"]["latitude"] <= 90
    assert -180 <= coordinates["LAX"]["longitude"] <= 180


def test_build_maps_includes_valid_iata_coordinates():
    source = json.dumps(
        {
            "KCPH": {
                "iata": "CPH",
                "tz": "Europe/Copenhagen",
                "city": "Copenhagen",
                "lat": 55.6181,
                "lon": 12.6561,
            }
        }
    ).encode()

    zones, cities, coordinates = build_maps(source)

    assert zones == {"CPH": "Europe/Copenhagen"}
    assert cities == {"CPH": "Copenhagen"}
    assert coordinates == {"CPH": {"latitude": 55.6181, "longitude": 12.6561}}


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(91, 0), (0, 181), (float("nan"), 0), (None, 1)],
)
def test_build_maps_rejects_invalid_coordinates(latitude, longitude):
    source = json.dumps(
        {
            "KCPH": {
                "iata": "CPH",
                "tz": "Europe/Copenhagen",
                "lat": latitude,
                "lon": longitude,
            }
        }
    ).encode()

    with pytest.raises(ValueError, match="invalid coordinates"):
        build_maps(source)
