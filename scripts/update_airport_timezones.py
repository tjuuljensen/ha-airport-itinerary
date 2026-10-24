#!/usr/bin/env python3
"""Build the bundled IATA timezone, city, and coordinate maps from mwgg/Airports.

Behavior: validates unique airport mappings and writes compact offline data.
Usage: python scripts/update_airport_timezones.py --commit <git-sha>
Inputs: a public mwgg/Airports commit, or --source-file with its airports.json.
Side effects: downloads only when --source-file is omitted; updates the bundled
  integration data file. It never changes Home Assistant runtime state.
Prerequisites: Python 3.10+; internet access only when downloading source data.
Author: Home Assistant Flight Itinerary maintainers.
Based on: mwgg/Airports, MIT licensed; see NOTICE.md.
Version: 1.2.0
Changelog: Add offline IATA coordinates for aircraft progress calculations.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import sys
import urllib.request
from collections import defaultdict
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

VERSION = "1.2.0"
SOURCE_REPOSITORY = "mwgg/Airports"
IATA_RE = re.compile(r"^[A-Z0-9]{3}$")
DOMAIN_DIR = Path(__file__).resolve().parents[1] / "custom_components" / "airport_aware_itinerary"
OUTPUT = DOMAIN_DIR / "data" / "airport_timezones.json"


def load_source(source_file: Path | None, commit: str) -> bytes:
    """Read a local pinned source file or download its raw GitHub URL."""
    if source_file:
        return source_file.read_bytes()
    url = f"https://raw.githubusercontent.com/{SOURCE_REPOSITORY}/{commit}/airports.json"
    request = urllib.request.Request(url, headers={"User-Agent": "ha-airport-itinerary-data-refresh/1"})
    with urllib.request.urlopen(request, timeout=30) as response:
        return response.read()


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


def build_map(source: bytes) -> dict[str, str]:
    """Validate source rows and return deterministic IATA-to-IANA mappings."""
    return build_maps(source)[0]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--version", action="version", version=VERSION)
    parser.add_argument("--commit", required=True, help="Full mwgg/Airports git commit SHA")
    parser.add_argument("--source-file", type=Path, help="Use an already downloaded airports.json")
    args = parser.parse_args()
    if not re.fullmatch(r"[0-9a-fA-F]{40}", args.commit):
        parser.error("--commit must be a full 40-character git SHA")

    source = load_source(args.source_file, args.commit.lower())
    mapping, cities, coordinates = build_maps(source)
    payload = {
        "metadata": {
            "source_repository": SOURCE_REPOSITORY,
            "source_commit": args.commit.lower(),
            "source_file": "airports.json",
            "source_sha256": hashlib.sha256(source).hexdigest(),
            "mapping_count": len(mapping),
            "city_count": len(cities),
            "coordinate_count": len(coordinates),
        },
        "airports": mapping,
        "airport_cities": cities,
        "airport_coordinates": coordinates,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(
        f"Wrote {len(mapping)} timezone mappings, {len(cities)} city mappings, "
        f"and {len(coordinates)} coordinate mappings "
        f"from {SOURCE_REPOSITORY}@{args.commit.lower()} to {OUTPUT}"
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, json.JSONDecodeError, urllib.error.URLError) as err:
        print(f"airport timezone generation failed: {err}", file=sys.stderr)
        raise SystemExit(1) from err
