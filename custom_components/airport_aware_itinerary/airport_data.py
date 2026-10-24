"""Load bundled, versioned IATA airport timezone, city, and coordinate maps."""

from __future__ import annotations

import json
from functools import lru_cache

from .const import AIRPORTS_FILE


@lru_cache(maxsize=1)
def get_airport_timezones() -> dict[str, str]:
    """Return IATA-to-IANA mappings packaged with the integration."""
    payload = json.loads(AIRPORTS_FILE.read_text(encoding="utf-8"))
    mappings = payload.get("airports")
    if not isinstance(mappings, dict):
        raise ValueError("Bundled airport timezone data is malformed.")
    if any(
        not isinstance(code, str)
        or not isinstance(zone, str)
        or len(code) != 3
        or not zone
        for code, zone in mappings.items()
    ):
        raise ValueError("Bundled airport timezone data contains invalid entries.")
    return mappings


@lru_cache(maxsize=1)
def get_airport_cities() -> dict[str, str]:
    """Return IATA-to-city names packaged with the integration."""
    payload = json.loads(AIRPORTS_FILE.read_text(encoding="utf-8"))
    cities = payload.get("airport_cities", {})
    if not isinstance(cities, dict):
        raise ValueError("Bundled airport city data is malformed.")
    if any(
        not isinstance(code, str)
        or not isinstance(city, str)
        or len(code) != 3
        or not city.strip()
        for code, city in cities.items()
    ):
        raise ValueError("Bundled airport city data contains invalid entries.")
    return cities


@lru_cache(maxsize=1)
def get_airport_coordinates() -> dict[str, dict[str, float]]:
    """Return validated IATA-to-coordinate mappings for route progress."""
    payload = json.loads(AIRPORTS_FILE.read_text(encoding="utf-8"))
    coordinates = payload.get("airport_coordinates", {})
    if not isinstance(coordinates, dict):
        raise ValueError("Bundled airport coordinate data is malformed.")
    for code, point in coordinates.items():
        if not isinstance(code, str) or len(code) != 3 or not isinstance(point, dict):
            raise ValueError("Bundled airport coordinate data contains invalid entries.")
        latitude, longitude = point.get("latitude"), point.get("longitude")
        if (
            isinstance(latitude, bool)
            or not isinstance(latitude, (int, float))
            or not -90 <= latitude <= 90
            or isinstance(longitude, bool)
            or not isinstance(longitude, (int, float))
            or not -180 <= longitude <= 180
        ):
            raise ValueError(f"Bundled airport coordinates are invalid for {code}.")
    return coordinates


def get_data_metadata() -> dict[str, object]:
    """Return source revision metadata for diagnostics and entity attributes."""
    payload = json.loads(AIRPORTS_FILE.read_text(encoding="utf-8"))
    return payload.get("metadata", {})
