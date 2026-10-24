"""Resolve the timezone for optional live aircraft coordinates."""

from __future__ import annotations

from functools import lru_cache


@lru_cache(maxsize=1)
def _finder():
    """Return the shared offline timezone boundary lookup."""
    try:
        from timezonefinder import TimezoneFinder
    except ImportError:
        return None

    return TimezoneFinder()


def timezone_for_coordinates(latitude: object, longitude: object) -> str | None:
    """Return an IANA timezone for valid WGS84 coordinates, if resolvable."""
    try:
        lat = float(latitude)
        lon = float(longitude)
    except (TypeError, ValueError):
        return None
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        return None
    finder = _finder()
    if finder is None:
        return None
    return finder.timezone_at(lat=lat, lng=lon)
