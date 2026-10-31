"""Shared validation for bundled and manually refreshed airport data."""

import json
import math
import re
from collections import defaultdict
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

IATA_RE = re.compile(r"^[A-Z0-9]{3}$")


def build_maps(source: bytes) -> tuple[dict[str, str], dict[str, str], dict[str, dict[str, float]]]:
    """Validate source rows and return deterministic timezone, city, and coordinate maps."""
    records = json.loads(source)
    if not isinstance(records, dict):
        raise ValueError("Source JSON root must be an object.")

    candidates: dict[str, set[str]] = defaultdict(set)
    city_candidates: dict[str, set[str]] = defaultdict(set)
    coordinate_candidates: dict[str, set[tuple[float, float]]] = defaultdict(set)
    for record in records.values():
        if not isinstance(record, dict):
            raise ValueError("Airport record must be an object.")
        raw_code = record.get("iata")
        code = raw_code.strip().upper() if isinstance(raw_code, str) else ""
        if not code:
            continue
        if not IATA_RE.fullmatch(code):
            raise ValueError(f"Invalid IATA code in source: {raw_code!r}.")
        zone = record.get("tz")
        if not isinstance(zone, str) or not zone.strip():
            raise ValueError(f"Airport {code} has no IANA timezone.")
        candidates[code].add(zone.strip())
        city = record.get("city")
        if isinstance(city, str) and city.strip():
            city_candidates[code].add(city.strip())
        latitude, longitude = record.get("lat"), record.get("lon")
        if latitude is not None or longitude is not None:
            if (
                isinstance(latitude, bool)
                or not isinstance(latitude, (int, float))
                or not math.isfinite(latitude)
                or not -90 <= latitude <= 90
                or isinstance(longitude, bool)
                or not isinstance(longitude, (int, float))
                or not math.isfinite(longitude)
                or not -180 <= longitude <= 180
            ):
                raise ValueError(f"Airport {code} has invalid coordinates.")
            coordinate_candidates[code].add((float(latitude), float(longitude)))

    conflicts = {code: sorted(zones) for code, zones in candidates.items() if len(zones) != 1}
    if conflicts:
        sample = ", ".join(f"{code}={zones}" for code, zones in sorted(conflicts.items())[:10])
        raise ValueError(f"Conflicting timezone mappings for {len(conflicts)} IATA codes: {sample}")

    result = {code: next(iter(zones)) for code, zones in sorted(candidates.items())}
    invalid_zones = []
    for code, zone_name in result.items():
        try:
            ZoneInfo(zone_name)
        except (ZoneInfoNotFoundError, ValueError):
            invalid_zones.append(f"{code}={zone_name}")
    if invalid_zones:
        raise ValueError("Invalid IANA zones in source: " + ", ".join(invalid_zones[:10]))
    if not result:
        raise ValueError("Source contained no usable IATA airport codes.")

    city_conflicts = {
        code: sorted(cities)
        for code, cities in city_candidates.items()
        if len(cities) != 1
    }
    if city_conflicts:
        sample = ", ".join(
            f"{code}={cities}" for code, cities in sorted(city_conflicts.items())[:10]
        )
        raise ValueError(
            f"Conflicting city mappings for {len(city_conflicts)} IATA codes: {sample}"
        )

    cities = {
        code: next(iter(names)) for code, names in sorted(city_candidates.items())
    }
    coordinate_conflicts = {
        code: sorted(points)
        for code, points in coordinate_candidates.items()
        if len(points) != 1
    }
    if coordinate_conflicts:
        sample = ", ".join(
            f"{code}={points}"
            for code, points in sorted(coordinate_conflicts.items())[:10]
        )
        raise ValueError(
            f"Conflicting airport coordinates for {len(coordinate_conflicts)} IATA codes: {sample}"
        )
    coordinates = {
        code: {"latitude": point[0], "longitude": point[1]}
        for code, points in sorted(coordinate_candidates.items())
        for point in points
    }
    return result, cities, coordinates

