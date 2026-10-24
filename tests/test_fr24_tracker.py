"""Tests for copying itinerary flight numbers into FR24 tracking."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.airport_aware_itinerary.fr24_tracker import FR24ItineraryTracker


class _States:
    def __init__(self, state):
        self._state = state

    def get(self, entity_id):
        assert entity_id == "sensor.fr24_additional_tracked"
        return self._state


class _Services:
    def __init__(self):
        self.async_call = AsyncMock()

    @staticmethod
    def has_service(domain, service):
        return (domain, service) == ("text", "set_value")


class _Manager:
    def __init__(self, itineraries):
        self._itineraries = itineraries

    def snapshot(self):
        return self._itineraries


class _Hass:
    def __init__(self, state):
        self.states = _States(state)
        self.services = _Services()


def _leg(flight_number, departure, **extra):
    return {
        "flight_number": flight_number,
        "departure": {"utc_timestamp": departure.isoformat()},
        **extra,
    }


async def test_sync_adds_upcoming_unique_flights_and_skips_existing_or_finished():
    now = datetime.now(timezone.utc)
    state = SimpleNamespace(
        state="1",
        attributes={"flights": [{"flight_number": "BA001"}]},
    )
    manager = _Manager(
        [
            {
                "legs": [
                    _leg("UA760", now + timedelta(days=1)),
                    _leg("ua 760", now + timedelta(days=2)),
                    _leg("BA001", now + timedelta(days=1)),
                    _leg("SK935", now + timedelta(days=1), completed=True),
                    _leg("LH100", now - timedelta(days=2)),
                ]
            }
        ]
    )
    hass = _Hass(state)
    tracker = FR24ItineraryTracker(
        hass,
        manager,
        "sensor.fr24_additional_tracked",
        "text.flightradar24_add_to_track",
    )

    await tracker.async_sync()
    await tracker.async_sync()

    hass.services.async_call.assert_awaited_once_with(
        "text",
        "set_value",
        {
            "entity_id": "text.flightradar24_add_to_track",
            "value": "UA760",
        },
        blocking=True,
    )
