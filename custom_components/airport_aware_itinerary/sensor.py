"""Native summary entity for locally stored flight itineraries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .airport_data import get_airport_cities, get_airport_coordinates, get_data_metadata
from .const import CONF_TRACKED_FLIGHTS_ENTITY, DOMAIN, EVENT_UPDATED
from .manager import ItineraryManager
from .plane_timezone import timezone_for_coordinates


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the itinerary summary sensor."""
    manager: ItineraryManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities([FlightItinerariesSensor(entry, manager)])


class FlightItinerariesSensor(SensorEntity):
    """Expose persisted itinerary data to dashboards and automations."""

    entity_description = SensorEntityDescription(
        key="itineraries",
        translation_key="itineraries",
        icon="mdi:airplane-clock",
    )

    def __init__(self, entry: ConfigEntry, manager: ItineraryManager) -> None:
        self._manager = manager
        self._entry = entry
        self._attr_unique_id = entry.entry_id
        self._attr_has_entity_name = True
        self._attr_suggested_object_id = "flight_itineraries"
        self._attr_native_value = 0
        self._attr_extra_state_attributes: dict[str, Any] = {}

    @callback
    def _refresh_attributes(self) -> None:
        itineraries = self._manager.snapshot()
        airport_cities = get_airport_cities()
        airport_coordinates = get_airport_coordinates()
        for itinerary in itineraries:
            for leg in itinerary.get("legs", []):
                origin = leg.get("origin_airport")
                destination = leg.get("destination_airport")
                if (
                    origin
                    and airport_cities.get(origin)
                    and not leg.get("origin_city")
                ):
                    leg["origin_city"] = airport_cities[origin]
                if (
                    destination
                    and airport_cities.get(destination)
                    and not leg.get("destination_city")
                ):
                    leg["destination_city"] = airport_cities[destination]
                if origin in airport_coordinates:
                    leg["origin_coordinates"] = airport_coordinates[origin]
                if destination in airport_coordinates:
                    leg["destination_coordinates"] = airport_coordinates[destination]
        self._attr_native_value = len(itineraries)
        metadata = get_data_metadata()
        source_entity = self._entry.options.get(
            CONF_TRACKED_FLIGHTS_ENTITY,
            self._entry.data.get(CONF_TRACKED_FLIGHTS_ENTITY),
        )
        source_state = self.hass.states.get(source_entity) if source_entity else None
        tracked_legs = self._match_tracked_legs(itineraries, source_state)
        source_health = _tracking_source_health(source_entity, source_state, tracked_legs)
        self._attr_extra_state_attributes = {
            "itineraries": itineraries,
            "tracking_source_entity": source_entity,
            "tracking_source_status": source_state.state if source_state else "not_configured",
            "tracking_source_health": source_health,
            "tracked_legs": tracked_legs,
            "airport_mapping_source": metadata.get("source_repository"),
            "airport_mapping_revision": metadata.get("source_commit"),
            "airport_mapping_count": metadata.get("mapping_count"),
            "airport_city_mapping_count": metadata.get("city_count"),
            "airport_coordinate_mapping_count": metadata.get("coordinate_count"),
        }

    async def async_added_to_hass(self) -> None:
        """Listen for local itinerary changes and optional FR24 updates."""
        await super().async_added_to_hass()
        await self._async_update()
        self.async_on_remove(self.hass.bus.async_listen(EVENT_UPDATED, self._handle_update))
        source_entity = self._entry.options.get(
            CONF_TRACKED_FLIGHTS_ENTITY,
            self._entry.data.get(CONF_TRACKED_FLIGHTS_ENTITY),
        )
        if source_entity:
            self.async_on_remove(
                async_track_state_change_event(self.hass, [source_entity], self._handle_update)
            )

    @callback
    def _handle_update(self, event: Any) -> None:
        """Refresh sensor state and persist newly confirmed arrivals."""
        self.hass.async_create_task(self._async_update())

    async def _async_update(self) -> None:
        """Persist completion timestamps before publishing updated attributes."""
        self._refresh_attributes()
        changed = False
        for tracked in self._attr_extra_state_attributes.get("tracked_legs", []):
            finished_at = tracked.get("finished_at")
            if finished_at:
                changed |= await self._manager.async_record_finished_at(
                    tracked["itinerary_id"], tracked["leg_id"], finished_at
                )
        if changed:
            self._refresh_attributes()
        self.async_write_ha_state()

    @staticmethod
    def _match_tracked_legs(
        itineraries: list[dict[str, Any]], source_state: Any
    ) -> list[dict[str, Any]]:
        """Match optional FR24 tracked-flight records to schedule occurrences."""
        if source_state is None or source_state.state in {"unknown", "unavailable"}:
            return []
        flights = source_state.attributes.get("flights", [])
        if not isinstance(flights, list):
            return []
        matches = []
        for itinerary in itineraries:
            for leg in itinerary.get("legs", []):
                scheduled = _timestamp(leg.get("departure", {}).get("utc_timestamp"))
                if not scheduled:
                    continue
                expected_number = str(leg.get("flight_number", "")).strip().upper()
                expected_origin = str(leg.get("origin_airport", "")).strip().upper()
                candidates = []
                expected_destination = str(
                    leg.get("destination_airport", "")
                ).strip().upper()
                for flight in flights:
                    if not isinstance(flight, dict):
                        continue
                    numbers = {
                        str(flight.get(key, "")).strip().upper()
                        for key in ("flight_number", "callsign")
                        if flight.get(key)
                    }
                    source_origin = str(flight.get("airport_origin_code_iata", "")).strip().upper()
                    source_destination = str(
                        flight.get("airport_destination_code_iata", "")
                    ).strip().upper()
                    source_time = next(
                        (
                            timestamp
                            for key in (
                                "time_scheduled_departure",
                                "time_estimated_departure",
                                "time_real_departure",
                            )
                            if (timestamp := _timestamp(flight.get(key)))
                        ),
                        0,
                    )
                    if (
                        expected_number in numbers
                        and (not source_origin or source_origin == expected_origin)
                        and (
                            not expected_destination
                            or not source_destination
                            or source_destination == expected_destination
                        )
                        and source_time
                        and abs(source_time - scheduled) <= 43200
                    ):
                        candidates.append((abs(source_time - scheduled), flight))
                if not candidates:
                    continue
                _, flight = min(candidates, key=lambda candidate: candidate[0])
                tracked_type = str(flight.get("tracked_type", "")).strip().lower()
                matched = {
                    "itinerary_id": itinerary["id"],
                    "leg_id": leg["id"],
                    "flight_number": expected_number,
                    "tracked_type": tracked_type,
                    "is_live": tracked_type == "live",
                    "aircraft_registration": str(flight.get("aircraft_registration", "")),
                    "position_updated_at": source_state.last_updated.isoformat(),
                }
                for key in (
                    "latitude",
                    "longitude",
                    "altitude",
                    "ground_speed",
                    "heading",
                    "on_ground",
                    "time_real_departure",
                    "time_estimated_departure",
                    "time_real_arrival",
                    "time_real_landing",
                    "time_gate_arrival",
                    "landing",
                    "gate_arrival",
                    "time_estimated_arrival",
                    "time_scheduled_arrival",
                    "airport_origin_city",
                    "airport_destination_city",
                    "airport_origin_timezone_offset",
                    "airport_origin_timezone_abbr",
                    "airport_destination_timezone_offset",
                    "airport_destination_timezone_abbr",
                ):
                    if flight.get(key) is not None:
                        matched[key] = flight[key]
                fallback = source_state.last_updated
                if isinstance(leg.get("finished_at"), str):
                    try:
                        fallback = datetime.fromisoformat(
                            leg["finished_at"].replace("Z", "+00:00")
                        )
                    except ValueError:
                        pass
                finished_at = _confirmed_finished_at(flight, fallback)
                if finished_at:
                    matched["finished_at"] = finished_at
                if flight.get("latitude") is not None and flight.get("longitude") is not None:
                    try:
                        matched["plane_timezone"] = timezone_for_coordinates(
                            flight["latitude"], flight["longitude"]
                        )
                    except (ImportError, OSError, ValueError):
                        matched["plane_timezone"] = None
                matches.append(matched)
        return matches

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return current itinerary attributes."""
        return self._attr_extra_state_attributes


def _confirmed_finished_at(flight: dict[str, Any], fallback: datetime) -> str | None:
    """Return a stable terminal timestamp for confirmed landing or gate arrival."""
    for key in (
        "time_gate_arrival",
        "gate_arrival",
        "time_real_landing",
        "landing",
        "time_real_arrival",
    ):
        value = flight.get(key)
        if isinstance(value, bool):
            if value:
                timestamp = _timestamp(flight.get("time_real_arrival"))
                if timestamp:
                    return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(
                        timespec="seconds"
                    )
                return fallback.astimezone(timezone.utc).isoformat(timespec="seconds")
            continue
        timestamp = _timestamp(value)
        if timestamp:
            return datetime.fromtimestamp(timestamp, tz=timezone.utc).isoformat(timespec="seconds")
    return None


def _timestamp(value: Any) -> float:
    """Parse numeric epoch or timezone-aware ISO datetime values."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value) if value > 0 else 0
    if not isinstance(value, str) or not value.strip():
        return 0
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError:
        return 0
    return parsed.timestamp() if parsed.tzinfo is not None else 0


def _tracking_source_health(source_entity: str | None, source_state: Any, tracked: list[dict[str, Any]]) -> str:
    """Describe whether the optional FR24 sensor currently supplies usable data."""
    if not source_entity:
        return "not_configured"
    if source_state is None:
        return "entity_missing"
    if source_state.state in {"unknown", "unavailable"}:
        return "unavailable"
    flights = source_state.attributes.get("flights")
    if not isinstance(flights, list):
        return "unsupported_data"
    if not flights:
        return "no_flights"
    if not tracked:
        return "no_matching_flight"
    if any(item.get("is_live") for item in tracked):
        return "live_match"
    return "scheduled_match"
