"""Optional forwarding of itinerary flights to the FR24 tracking input."""

from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timezone
from typing import Any

from homeassistant.core import Event, HomeAssistant, callback

from .manager import ItineraryManager

_LOGGER = logging.getLogger(__name__)
_FLIGHT_NUMBER_RE = re.compile(r"[^A-Z0-9]")
_PAST_FLIGHT_GRACE_SECONDS = 12 * 60 * 60


class FR24ItineraryTracker:
    """Send eligible itinerary flight numbers to FR24's Add to track entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        manager: ItineraryManager,
        source_entity: str | None,
        add_to_track_entity: str,
    ) -> None:
        self._hass = hass
        self._manager = manager
        self._source_entity = source_entity
        self._add_to_track_entity = add_to_track_entity
        self._submitted: set[str] = set()
        self._lock = asyncio.Lock()

    @callback
    def handle_itinerary_updated(self, event: Event) -> None:
        """Queue an idempotent sync after itinerary changes."""
        self._hass.async_create_task(self.async_sync())

    @callback
    def handle_source_updated(self, event: Event) -> None:
        """Retry when the selected FR24 sensor becomes available or updates."""
        self._hass.async_create_task(self.async_sync())

    async def async_sync(self) -> None:
        """Track upcoming flights that are not already in FR24's source list."""
        if not self._hass.services.has_service("text", "set_value"):
            _LOGGER.warning(
                "Cannot auto-track itinerary flights: Home Assistant text.set_value is unavailable"
            )
            return

        async with self._lock:
            source_state = (
                self._hass.states.get(self._source_entity)
                if self._source_entity
                else None
            )
            if self._source_entity and (
                source_state is None
                or source_state.state in {"unknown", "unavailable"}
            ):
                _LOGGER.debug(
                    "Waiting for FR24 source %s before synchronizing itinerary flights",
                    self._source_entity,
                )
                return
            existing = _existing_flight_numbers(source_state)
            now = datetime.now(timezone.utc).timestamp()
            requested: set[str] = set()
            for itinerary in self._manager.snapshot():
                for leg in itinerary.get("legs", []):
                    flight_number = str(leg.get("flight_number", "")).strip().upper()
                    flight_key = _normalize_flight_number(flight_number)
                    if (
                        not flight_key
                        or leg.get("completed")
                        or leg.get("finished_at")
                        or flight_key in existing
                        or flight_key in self._submitted
                        or flight_key in requested
                        or _is_too_old(leg, now)
                    ):
                        continue
                    requested.add(flight_key)
                    try:
                        await self._hass.services.async_call(
                            "text",
                            "set_value",
                            {
                                "entity_id": self._add_to_track_entity,
                                "value": flight_number,
                            },
                            blocking=True,
                        )
                    except Exception:
                        _LOGGER.exception(
                            "Could not add itinerary flight %s to FR24 tracking",
                            flight_number,
                        )
                        continue
                    self._submitted.add(flight_key)
                    _LOGGER.debug("Added itinerary flight %s to FR24 tracking", flight_number)


def _normalize_flight_number(value: str) -> str:
    """Normalize a flight number for comparison with FR24 records."""
    return _FLIGHT_NUMBER_RE.sub("", value.upper())


def _existing_flight_numbers(source_state: Any) -> set[str]:
    """Return normalized flight numbers already listed by the selected sensor."""
    if source_state is None or source_state.state in {"unknown", "unavailable"}:
        return set()
    flights = source_state.attributes.get("flights")
    if not isinstance(flights, list):
        return set()
    return {
        _normalize_flight_number(str(flight.get("flight_number", "")))
        for flight in flights
        if isinstance(flight, dict) and flight.get("flight_number")
    }


def _is_too_old(leg: dict[str, Any], now: float) -> bool:
    """Avoid sending completed historical legs or departures long in the past."""
    departure = leg.get("departure", {}).get("utc_timestamp")
    if isinstance(departure, (int, float)) and not isinstance(departure, bool):
        timestamp = float(departure)
    elif isinstance(departure, str):
        try:
            timestamp = datetime.fromisoformat(
                departure.replace("Z", "+00:00")
            ).timestamp()
        except ValueError:
            return False
    else:
        return False
    return timestamp < now - _PAST_FLIGHT_GRACE_SECONDS
