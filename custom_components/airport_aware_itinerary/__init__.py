"""Airport-aware flight itinerary integration."""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall, SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.storage import Store

from .airport_data import get_airport_timezones
from .const import (
    CONF_ARRIVAL_DATE,
    CONF_FR24_CONNECTION,
    CONF_ARRIVAL_TIME,
    CONF_DEPARTURE_TIME,
    CONF_DESTINATION_AIRPORT,
    CONF_ORIGIN_AIRPORT,
    CONF_SERVICE_DATE,
    DOMAIN,
    EVENT_LIFECYCLE,
    PLATFORMS,
    SERVICE_ADD_FLIGHT,
    SERVICE_CLEAR_ITINERARY,
    SERVICE_CREATE_ITINERARY,
    SERVICE_DELETE_ITINERARY,
    SERVICE_REMOVE_FLIGHT,
    SERVICE_RESOLVE_DEPARTURE,
    SERVICE_RENAME_ITINERARY,
    STORAGE_KEY,
    STORAGE_VERSION,
)
from .manager import ItineraryManager
from .fr24_tracker import FR24ItineraryTracker
from .airport_refresh import AirportDataRefresh
from .frontend import async_setup_frontend
from .timezones import TimeResolutionError, resolve_local_time

_MANAGER: str = "manager"
_LOGGER = logging.getLogger(__name__)


async def async_setup(hass: HomeAssistant, config: dict[str, Any]) -> bool:
    """Set up the integration domain."""
    hass.data.setdefault(DOMAIN, {})
    return True


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Load stored itinerary data and register actions/entities."""
    await async_setup_frontend(hass)
    store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
    saved = await store.async_load()
    airports = AirportDataRefresh(hass)
    await airports.async_load()
    manager = ItineraryManager(hass, store, saved)
    tracker = FR24ItineraryTracker(hass, manager, {**entry.data, **entry.options})
    hass.data[DOMAIN][entry.entry_id] = {_MANAGER: manager, "tracker": tracker, "airports": airports}
    _register_services(hass, manager, airports)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    tracker.start()
    entry.async_on_unload(tracker.stop)
    await tracker.async_sync()
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    hass.bus.async_fire(EVENT_LIFECYCLE)
    return True


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload entities after optional tracking-source settings change."""
    if not entry.options.get(CONF_FR24_CONNECTION, True):
        tracker = hass.data[DOMAIN][entry.entry_id]["tracker"]
        tracker.set_connection_enabled(False)
        await tracker.async_sync()
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload the integration and its actions."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    hass.data[DOMAIN].pop(entry.entry_id, None)
    for service in (
        SERVICE_RESOLVE_DEPARTURE,
        SERVICE_CREATE_ITINERARY,
        SERVICE_ADD_FLIGHT,
        SERVICE_REMOVE_FLIGHT,
        SERVICE_CLEAR_ITINERARY,
        SERVICE_DELETE_ITINERARY,
        SERVICE_RENAME_ITINERARY,
        "mark_flight_completed", "refresh_airport_data", "restore_bundled_airport_data",
    ):
        hass.services.async_remove(DOMAIN, service)
    return True


def _register_services(hass: HomeAssistant, manager: ItineraryManager, airports: AirportDataRefresh) -> None:
    """Register response-bearing itinerary actions."""

    async def resolve_departure(call: ServiceCall) -> dict[str, Any]:
        return _resolve(call.data)

    async def create_itinerary(call: ServiceCall) -> dict[str, Any]:
        return await manager.async_create_itinerary(call.data["name"])

    async def add_flight(call: ServiceCall) -> dict[str, Any]:
        try:
            leg = _make_leg(call.data)
        except TimeResolutionError as err:
            return {"success": False, "error": str(err)}
        return await manager.async_add_flight(call.data["itinerary_id"], leg)

    async def remove_flight(call: ServiceCall) -> dict[str, Any]:
        return await manager.async_remove_flight(
            call.data["itinerary_id"], call.data["leg_id"]
        )

    async def clear_itinerary(call: ServiceCall) -> dict[str, Any]:
        return await manager.async_clear_itinerary(call.data["itinerary_id"])

    async def delete_itinerary(call: ServiceCall) -> dict[str, Any]:
        return await manager.async_delete_itinerary(call.data["itinerary_id"])

    async def rename_itinerary(call: ServiceCall) -> dict[str, Any]:
        return await manager.async_rename_itinerary(
            call.data["itinerary_id"], call.data["name"]
        )

    async def mark_completed(call):
        return await manager.async_mark_flight_completed(call.data["itinerary_id"], call.data["leg_id"])

    async def refresh_airports(call):
        return await airports.async_refresh()

    async def restore_airports(call):
        return await airports.async_restore()

    strings = {vol.Required(key): str for key in (CONF_ORIGIN_AIRPORT, CONF_SERVICE_DATE, CONF_DEPARTURE_TIME)}
    resolve_schema = vol.Schema(
        {
            **strings,
            vol.Optional("fold", default=""): vol.In(["", "earlier", "later"]),
        }
    )
    services = (
        (SERVICE_RESOLVE_DEPARTURE, resolve_departure, resolve_schema),
        (SERVICE_CREATE_ITINERARY, create_itinerary, vol.Schema({vol.Required("name"): str})),
        (
            SERVICE_ADD_FLIGHT,
            add_flight,
            vol.Schema(
                {
                    vol.Required("itinerary_id"): str,
                    vol.Required("flight_number"): str,
                    vol.Required(CONF_ORIGIN_AIRPORT): str,
                    vol.Required(CONF_SERVICE_DATE): str,
                    vol.Required(CONF_DEPARTURE_TIME): str,
                    vol.Optional("fold", default=""): vol.In(["", "earlier", "later"]),
                    vol.Optional(CONF_DESTINATION_AIRPORT): str,
                    vol.Optional(CONF_ARRIVAL_DATE): str,
                    vol.Optional(CONF_ARRIVAL_TIME): str,
                    vol.Optional("arrival_fold", default=""): vol.In(["", "earlier", "later"]),
                    vol.Optional("label", default=""): str,
                }
            ),
        ),
        (
            SERVICE_REMOVE_FLIGHT,
            remove_flight,
            vol.Schema({vol.Required("itinerary_id"): str, vol.Required("leg_id"): str}),
        ),
        (
            SERVICE_CLEAR_ITINERARY,
            clear_itinerary,
            vol.Schema({vol.Required("itinerary_id"): str}),
        ),
        (
            SERVICE_DELETE_ITINERARY,
            delete_itinerary,
            vol.Schema({vol.Required("itinerary_id"): str}),
        ),
        (
            SERVICE_RENAME_ITINERARY,
            rename_itinerary,
            vol.Schema({vol.Required("itinerary_id"): str, vol.Required("name"): str}),
        ),
    )
    for name, handler, schema in services:
        hass.services.async_register(
            DOMAIN,
            name,
            handler,
            schema=schema,
            supports_response=SupportsResponse.ONLY,
        )
    for name, handler, schema in (
        ("mark_flight_completed", mark_completed, vol.Schema({vol.Required("itinerary_id"): str, vol.Required("leg_id"): str})),
        ("refresh_airport_data", refresh_airports, vol.Schema({})),
        ("restore_bundled_airport_data", restore_airports, vol.Schema({})),
    ):
        hass.services.async_register(DOMAIN, name, handler, schema=schema, supports_response=SupportsResponse.ONLY)


def _resolve(data: dict[str, Any]) -> dict[str, Any]:
    """Resolve service input to an explicit airport-local timestamp."""
    try:
        result = resolve_local_time(
            data.get(CONF_ORIGIN_AIRPORT),
            data.get(CONF_SERVICE_DATE),
            data.get(CONF_DEPARTURE_TIME),
            get_airport_timezones(),
            data.get("fold") or None,
        )
    except TimeResolutionError as err:
        return {"success": False, "error": str(err)}
    except (OSError, ValueError) as err:
        raise HomeAssistantError(f"Airport timezone data could not be loaded: {err}") from err
    return {"success": True, **result}


def _make_leg(data: dict[str, Any]) -> dict[str, Any]:
    """Validate and normalize one itinerary leg."""
    flight_number = data.get("flight_number", "").strip().upper()
    if not flight_number or len(flight_number) > 16:
        raise TimeResolutionError("Enter a flight number between 1 and 16 characters.")

    departure = resolve_local_time(
        data.get(CONF_ORIGIN_AIRPORT),
        data.get(CONF_SERVICE_DATE),
        data.get(CONF_DEPARTURE_TIME),
        get_airport_timezones(),
        data.get("fold") or None,
    )
    destination = data.get(CONF_DESTINATION_AIRPORT, "").strip().upper()
    if destination and destination not in get_airport_timezones():
        raise TimeResolutionError(f"No timezone data is available for airport {destination}.")

    arrival_date = data.get(CONF_ARRIVAL_DATE, "").strip()
    arrival_time = data.get(CONF_ARRIVAL_TIME, "").strip()
    if bool(arrival_date) != bool(arrival_time):
        raise TimeResolutionError("Enter both arrival date and local time, or leave both blank.")
    arrival = None
    if arrival_date or arrival_time:
        if not destination:
            raise TimeResolutionError("Enter the destination airport to resolve arrival time.")
        arrival = resolve_local_time(
            destination, arrival_date, arrival_time, get_airport_timezones(), data.get("arrival_fold") or None
        )
        if arrival["utc_timestamp"] <= departure["utc_timestamp"]:
            raise TimeResolutionError("Arrival must be later than departure.")

    return {
        "flight_number": flight_number,
        "origin_airport": departure["airport"],
        "destination_airport": destination,
        "destination_timezone": get_airport_timezones().get(destination, ""),
        "service_date": data[CONF_SERVICE_DATE],
        "departure_time": data[CONF_DEPARTURE_TIME],
        "departure": departure,
        "arrival_date": arrival_date,
        "arrival_time": arrival_time,
        "arrival": arrival,
        "flight_time_seconds": (
            int(
                datetime.fromisoformat(arrival["utc_timestamp"]).timestamp()
                - datetime.fromisoformat(departure["utc_timestamp"]).timestamp()
            )
            if arrival
            else None
        ),
        "label": data.get("label", "").strip()
        or (f"{departure['airport']}-{destination}" if destination else flight_number),
    }
