"""Native summary entity for locally stored flight itineraries."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.helpers import entity_registry as er
from homeassistant.components.sensor import SensorEntity, SensorEntityDescription

from .airport_data import get_airport_cities, get_airport_coordinates, get_data_metadata
from .const import CONF_TRACKED_FLIGHTS_ENTITY, CONF_FR24_CONNECTION, DOMAIN, EVENT_UPDATED, EVENT_LIFECYCLE
from .lifecycle import match_flight
from .manager import ItineraryManager
from .plane_timezone import timezone_for_coordinates


class ItineraryDeadline(SensorEntity):
    """UTC deadlines suitable for native HA time triggers."""

    _attr_has_entity_name = True
    _attr_device_class = "timestamp"

    def __init__(self, entry, key, tracker):
        self.key, self.tracker = key, tracker
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_name = "API start" if key == "api_start_at" else "API stop"
        self._attr_suggested_object_id = f"airport_itinerary_{key}"
        self.entity_id = f"sensor.airport_itinerary_{key}"

    @property
    def native_value(self):
        value = self.tracker.view.get(self.key)
        return datetime.fromisoformat(value) if value else None

    async def async_added_to_hass(self):
        self.async_on_remove(self.hass.bus.async_listen(EVENT_LIFECYCLE, self._updated))

    @callback
    def _updated(self, event):
        self.async_write_ha_state()


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    """Set up the itinerary summary sensor."""
    manager: ItineraryManager = hass.data[DOMAIN][entry.entry_id]["manager"]
    async_add_entities([FlightItinerariesSensor(entry, manager),
                        ItineraryDeadline(entry, "api_start_at", hass.data[DOMAIN][entry.entry_id]["tracker"]),
                        ItineraryDeadline(entry, "api_stop_at", hass.data[DOMAIN][entry.entry_id]["tracker"])])


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
        self.entity_id = "sensor.flight_itineraries"
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
        connected = self._entry.options.get(CONF_FR24_CONNECTION, True)
        source_state = self.hass.states.get(source_entity) if connected and source_entity else None
        tracked_legs = self._match_tracked_legs(itineraries, source_state)
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id, {})
        lifecycle = runtime["tracker"].view if runtime.get("tracker") else {}
        now = datetime.now(timezone.utc).timestamp()
        for itinerary in itineraries:
            for leg in itinerary.get("legs", []):
                live = next((row for row in tracked_legs if row["itinerary_id"] == itinerary["id"] and row["leg_id"] == leg["id"]), {})
                speed = live.get("ground_speed")
                if (leg.get("arrival_phase") == "landed" and live.get("is_live") and live.get("on_ground") is True
                        and isinstance(speed, (int, float)) and not isinstance(speed, bool) and speed > 0
                        and source_state and 0 <= now - source_state.last_updated.timestamp() <= 300
                        and lifecycle.get("fetching")):
                    leg["arrival_phase"] = "taxiing"
        source_health = _tracking_source_health(source_entity, source_state, tracked_legs) if connected else "disabled"
        self._attr_extra_state_attributes = {
            "itineraries": itineraries,
            "journeys": lifecycle.get("journeys", []),
            "tracking": lifecycle,
            "fr24_connection_entity": er.async_get(self.hass).async_get_entity_id(
                "switch", DOMAIN, f"{self._entry.entry_id}_fr24_connection"),
            "airport_data_refresh": runtime["airports"].status if runtime.get("airports") else {},
            "tracking_source_entity": source_entity,
            "tracking_source_status": source_state.state if source_state else "not_configured" if connected else "disabled",
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
        self.async_on_remove(self.hass.bus.async_listen(EVENT_LIFECYCLE, self._handle_update))
        source_entity = self._entry.options.get(
            CONF_TRACKED_FLIGHTS_ENTITY,
            self._entry.data.get(CONF_TRACKED_FLIGHTS_ENTITY),
        )
        if source_entity and self._entry.options.get(CONF_FR24_CONNECTION, True):
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
                flight = match_flight(leg, flights)
                if flight is None:
                    continue
                expected_number = leg.get("flight_number", "")
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
                    "has_landed",
                    "gate_arrived_sent",
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
                if matched.get("on_ground") in (0, 1) and "on_ground" in matched:
                    matched["on_ground"] = bool(matched["on_ground"])
                if leg.get("finished_at"):
                    matched["finished_at"] = leg["finished_at"]
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


def _tracking_source_health(source_entity: str | None, source_state: Any, tracked: list[dict[str, Any]]) -> str:
    """Describe whether the optional FR24 sensor currently supplies usable data."""
    if not source_entity:
        return "not_configured"
    if source_state is None:
        return "entity_missing"
    if source_state.state in {"unknown", "unavailable"}:
        return "unavailable"
    flights = source_state.attributes.get("flights")
    if not isinstance(flights, list) or any(not isinstance(flight, dict) for flight in flights):
        return "unsupported_data"
    if not flights:
        return "no_flights"
    if not tracked:
        return "no_matching_flight"
    if any(item.get("is_live") for item in tracked):
        return "live_match"
    return "scheduled_match"
