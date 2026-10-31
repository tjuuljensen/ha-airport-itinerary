"""Shared validation for options and the master connection switch."""

from homeassistant.helpers import entity_registry as er

from .const import (
    CONF_FR24_ADD_TO_TRACK_ENTITY, CONF_FR24_AUTO_TRACK, CONF_FR24_CLEANUP,
    CONF_FR24_DISABLE, CONF_FR24_ENABLE, CONF_FR24_REMOVE_ENTITY,
    CONF_FR24_SWITCH, CONF_TRACKED_FLIGHTS_ENTITY,
)


def connection_error(hass, options):
    if options.get(CONF_FR24_AUTO_TRACK) and not options.get(CONF_FR24_ADD_TO_TRACK_ENTITY):
        return "select_add_to_track_entity"
    if any(options.get(key) for key in (CONF_FR24_AUTO_TRACK, CONF_FR24_CLEANUP, CONF_FR24_ENABLE, CONF_FR24_DISABLE)) and not options.get(CONF_TRACKED_FLIGHTS_ENTITY):
        return "select_tracked_flights_entity"
    if options.get(CONF_FR24_CLEANUP) and not options.get(CONF_FR24_REMOVE_ENTITY):
        return "select_remove_entity"
    if (options.get(CONF_FR24_ENABLE) or options.get(CONF_FR24_DISABLE)) and not options.get(CONF_FR24_SWITCH):
        return "select_api_switch"
    registry = er.async_get(hass)
    selected = [registry.async_get(options[key]) for key in (
        CONF_TRACKED_FLIGHTS_ENTITY, CONF_FR24_ADD_TO_TRACK_ENTITY,
        CONF_FR24_REMOVE_ENTITY, CONF_FR24_SWITCH) if options.get(key)]
    if selected and (any(item is None or item.platform != "flightradar24" or not item.config_entry_id for item in selected)
                     or len({item.config_entry_id for item in selected if item}) != 1):
        return "different_fr24_entry"
    return None
