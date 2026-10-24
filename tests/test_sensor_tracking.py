"""Tests for optional FR24-to-itinerary flight matching."""

from datetime import datetime, timezone
from types import SimpleNamespace

from custom_components.airport_aware_itinerary.sensor import (
    FlightItinerariesSensor,
    _tracking_source_health,
)


def _source(flights, state="2"):
    return SimpleNamespace(
        state=state,
        attributes={"flights": flights},
        last_updated=datetime(2026, 10, 23, 12, 0, tzinfo=timezone.utc),
    )


def _leg():
    return {
        "id": "leg-1",
        "flight_number": "SK935",
        "origin_airport": "CPH",
        "destination_airport": "LAX",
        "departure": {"utc_timestamp": "2026-10-23T10:00:00+00:00"},
    }


def test_match_uses_nearest_consistent_live_record():
    live = {
        "flight_number": "SK935",
        "tracked_type": "live",
        "airport_origin_code_iata": "CPH",
        "airport_destination_code_iata": "LAX",
        "time_scheduled_departure": "2026-10-23T10:02:00+00:00",
        "time_estimated_arrival": "2026-10-23T18:45:00+00:00",
        "latitude": 55.0,
        "longitude": 10.0,
    }
    wrong_destination = {
        **live,
        "airport_destination_code_iata": "JFK",
        "time_scheduled_departure": "2026-10-23T10:00:00+00:00",
    }
    older_occurrence = {
        **live,
        "time_scheduled_departure": "2026-10-22T10:00:00+00:00",
    }

    matches = FlightItinerariesSensor._match_tracked_legs(
        [{"id": "trip-1", "legs": [_leg()]}],
        _source([wrong_destination, older_occurrence, live]),
    )

    assert len(matches) == 1
    assert matches[0]["is_live"] is True
    assert matches[0]["time_estimated_arrival"] == live["time_estimated_arrival"]


def test_scheduled_record_is_matched_but_not_marked_live():
    scheduled = {
        "flight_number": "SK935",
        "tracked_type": "scheduled",
        "airport_origin_code_iata": "CPH",
        "time_scheduled_departure": "2026-10-23T10:00:00+00:00",
    }

    matches = FlightItinerariesSensor._match_tracked_legs(
        [{"id": "trip-1", "legs": [_leg()]}], _source([scheduled])
    )

    assert len(matches) == 1
    assert matches[0]["is_live"] is False


def test_unavailable_or_unsupported_sources_do_not_match():
    itinerary = [{"id": "trip-1", "legs": [_leg()]}]

    assert FlightItinerariesSensor._match_tracked_legs(
        itinerary, _source([], state="unavailable")
    ) == []
    assert FlightItinerariesSensor._match_tracked_legs(
        itinerary,
        SimpleNamespace(
            state="1",
            attributes={"flights": "invalid"},
            last_updated=datetime.now(timezone.utc),
        ),
    ) == []


def test_tracking_source_health_explains_connection_state():
    assert _tracking_source_health(None, None, []) == "not_configured"
    assert _tracking_source_health("sensor.fr24", None, []) == "entity_missing"
    assert _tracking_source_health("sensor.fr24", _source([], "unavailable"), []) == "unavailable"
    assert _tracking_source_health("sensor.fr24", _source([]), []) == "no_flights"
    assert _tracking_source_health("sensor.fr24", _source([{}]), []) == "no_matching_flight"
