"""Tests for local airport date/time resolution."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = spec_from_file_location(
    "airport_aware_itinerary_timezones",
    ROOT / "custom_components" / "airport_aware_itinerary" / "timezones.py",
)
TIMEZONES = module_from_spec(SPEC)
SPEC.loader.exec_module(TIMEZONES)

AIRPORTS = {
    "DEN": "America/Denver",
    "MUC": "Europe/Berlin",
    "CPH": "Europe/Copenhagen",
    "SYD": "Australia/Sydney",
    "PHX": "America/Phoenix",
}


def test_denver_example_has_explicit_correct_offset():
    result = TIMEZONES.resolve_local_time(" den ", "2026-10-22", "20:25", AIRPORTS)

    assert result["timestamp"] == "2026-10-22T20:25:00-06:00"
    assert result["utc_timestamp"] == "2026-10-23T02:25:00+00:00"
    assert result["timezone"] == "America/Denver"


def test_dst_gap_is_rejected():
    with pytest.raises(TIMEZONES.TimeResolutionError, match="does not exist"):
        TIMEZONES.resolve_local_time("DEN", "2026-03-08", "02:30", AIRPORTS)


def test_dst_fold_requires_an_explicit_occurrence():
    with pytest.raises(TIMEZONES.TimeResolutionError, match="occurs twice"):
        TIMEZONES.resolve_local_time("DEN", "2026-11-01", "01:30", AIRPORTS)


def test_dst_fold_chooses_earlier_or_later_instant():
    earlier = TIMEZONES.resolve_local_time("DEN", "2026-11-01", "01:30", AIRPORTS, "earlier")
    later = TIMEZONES.resolve_local_time("DEN", "2026-11-01", "01:30", AIRPORTS, "later")

    assert earlier["timestamp"] == "2026-11-01T01:30:00-06:00"
    assert later["timestamp"] == "2026-11-01T01:30:00-07:00"


@pytest.mark.parametrize(
    ("code", "date_text", "time_text", "message"),
    [
        ("XXX", "2026-10-22", "20:25", "No timezone data"),
        ("DENV", "2026-10-22", "20:25", "three-character"),
        ("DEN", "2026-2-2", "20:25", "YYYY-MM-DD"),
        ("DEN", "2026-10-22", "24:00", "valid calendar"),
        ("DEN", "2026-02-30", "20:25", "valid calendar"),
    ],
)
def test_invalid_input_is_visible(code, date_text, time_text, message):
    with pytest.raises(TIMEZONES.TimeResolutionError, match=message):
        TIMEZONES.resolve_local_time(code, date_text, time_text, AIRPORTS)


def test_map_is_bundled_with_provenance_and_expected_coverage():
    import json

    data_path = ROOT / "custom_components" / "airport_aware_itinerary" / "data" / "airport_timezones.json"
    payload = json.loads(data_path.read_text(encoding="utf-8"))

    assert payload["metadata"]["source_commit"] == "a89e4e0dda9d9878337e2da190ebe1ef1d6af705"
    assert payload["metadata"]["mapping_count"] == len(payload["airports"]) == 7918
    assert payload["airports"]["DEN"] == "America/Denver"
    assert payload["airports"]["MUC"] == "Europe/Berlin"
    assert payload["airports"]["PHX"] == "America/Phoenix"


def test_duplicate_iata_with_conflicting_zones_is_rejected():
    from importlib.util import module_from_spec, spec_from_file_location
    import json

    update_spec = spec_from_file_location(
        "update_airport_timezones",
        ROOT / "scripts" / "update_airport_timezones.py",
    )
    update = module_from_spec(update_spec)
    update_spec.loader.exec_module(update)
    source = json.dumps(
        {
            "AAAA": {"iata": "XYZ", "tz": "America/Denver"},
            "BBBB": {"iata": "XYZ", "tz": "America/Phoenix"},
        }
    ).encode()

    with pytest.raises(ValueError, match="Conflicting timezone mappings"):
        update.build_map(source)
