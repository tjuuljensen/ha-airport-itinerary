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
Version: 1.3.0
Changelog: Share airport validation with the manual runtime refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
import urllib.request
from pathlib import Path

VERSION = "1.3.0"
SOURCE_REPOSITORY = "mwgg/Airports"
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


# Load the dependency-free validator without importing Home Assistant.
_validator_spec = importlib.util.spec_from_file_location("airport_validation", DOMAIN_DIR / "airport_validation.py")
_validator = importlib.util.module_from_spec(_validator_spec)
_validator_spec.loader.exec_module(_validator)
build_maps = _validator.build_maps


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
