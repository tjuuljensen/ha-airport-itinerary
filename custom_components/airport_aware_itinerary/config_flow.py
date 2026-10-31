"""UI setup flow for the Airport-aware Flight Itinerary integration."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import selector

from .const import (
    CONF_FR24_ADD_TO_TRACK_ENTITY,
    CONF_FR24_AUTO_TRACK,
    CONF_FR24_CONNECTION,
    CONF_TRACKED_FLIGHTS_ENTITY,
    DOMAIN,
    NAME,
    CONF_FR24_REMOVE_ENTITY, CONF_FR24_SWITCH, CONF_FR24_CLEANUP,
    CONF_FR24_ENABLE, CONF_FR24_DISABLE, LIFECYCLE_DEFAULTS,
)


from .fr24_config import connection_error


class AirportAwareItineraryConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Set up one local itinerary store per Home Assistant instance."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Create the local integration entry without requiring an account."""
        await self.async_set_unique_id(DOMAIN)
        self._abort_if_unique_id_configured()
        if user_input is not None:
            tracked_source = user_input.get(CONF_TRACKED_FLIGHTS_ENTITY)
            data = {CONF_TRACKED_FLIGHTS_ENTITY: tracked_source} if tracked_source else {}
            return self.async_create_entry(title=NAME, data=data)
        return self.async_show_form(step_id="user", data_schema=vol.Schema({}))

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Return options flow for the optional FR24 sensor connection."""
        return AirportAwareItineraryOptionsFlow()


class AirportAwareItineraryOptionsFlow(config_entries.OptionsFlow):
    """Configure an optional Flightradar24 tracked-flights sensor."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Configure optional FR24 data and itinerary auto-tracking."""
        if user_input is not None:
            enabled = user_input.get(CONF_FR24_CONNECTION, True)
            tracked_source = user_input.get(CONF_TRACKED_FLIGHTS_ENTITY)
            auto_track = user_input.get(CONF_FR24_AUTO_TRACK, False)
            add_to_track_entity = user_input.get(CONF_FR24_ADD_TO_TRACK_ENTITY)
            error = connection_error(self.hass, user_input) if enabled else None
            if enabled and error:
                return self.async_show_form(step_id="init", data_schema=self._options_schema(user_input), errors={"base": error})
            options = {CONF_TRACKED_FLIGHTS_ENTITY: None} if not tracked_source and self.config_entry.data.get(CONF_TRACKED_FLIGHTS_ENTITY) else {}
            if tracked_source:
                options[CONF_TRACKED_FLIGHTS_ENTITY] = tracked_source
            if add_to_track_entity:
                options[CONF_FR24_ADD_TO_TRACK_ENTITY] = add_to_track_entity
            if auto_track:
                options[CONF_FR24_AUTO_TRACK] = True
            options[CONF_FR24_CONNECTION] = enabled
            for key in (CONF_FR24_REMOVE_ENTITY, CONF_FR24_SWITCH, CONF_FR24_CLEANUP,
                        CONF_FR24_ENABLE, CONF_FR24_DISABLE, *LIFECYCLE_DEFAULTS):
                if key in user_input:
                    options[key] = user_input[key]
            return self.async_create_entry(
                data=options,
            )
        return self.async_show_form(step_id="init", data_schema=self._options_schema())

    def _options_schema(self, values: dict[str, Any] | None = None) -> vol.Schema:
        """Build the options form with saved or rejected values as defaults."""
        options = self.config_entry.options
        values = values or {}
        tracked_source = values.get(
            CONF_TRACKED_FLIGHTS_ENTITY,
            options.get(CONF_TRACKED_FLIGHTS_ENTITY, self.config_entry.data.get(CONF_TRACKED_FLIGHTS_ENTITY)),
        )
        add_to_track_entity = values.get(
            CONF_FR24_ADD_TO_TRACK_ENTITY,
            options.get(CONF_FR24_ADD_TO_TRACK_ENTITY),
        )
        auto_track = values.get(CONF_FR24_AUTO_TRACK, options.get(CONF_FR24_AUTO_TRACK, False))
        schema: dict[Any, Any] = {
            vol.Optional(CONF_FR24_CONNECTION, default=values.get(CONF_FR24_CONNECTION, options.get(CONF_FR24_CONNECTION, True))): selector.BooleanSelector(),
            vol.Optional(
                CONF_TRACKED_FLIGHTS_ENTITY,
                description={"suggested_value": tracked_source} if tracked_source else {},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", integration="flightradar24")
            ),
            vol.Optional(CONF_FR24_AUTO_TRACK, default=auto_track): selector.BooleanSelector(),
            vol.Optional(
                CONF_FR24_ADD_TO_TRACK_ENTITY,
                description={"suggested_value": add_to_track_entity} if add_to_track_entity else {},
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="text", integration="flightradar24")
            ),
        }
        for key, domain in ((CONF_FR24_REMOVE_ENTITY, "text"), (CONF_FR24_SWITCH, "switch")):
            value = values.get(key, options.get(key))
            schema[vol.Optional(key, description={"suggested_value": value} if value else {})] = selector.EntitySelector(
                selector.EntitySelectorConfig(domain=domain, integration="flightradar24"))
        for key in (CONF_FR24_CLEANUP, CONF_FR24_ENABLE, CONF_FR24_DISABLE):
            schema[vol.Optional(key, default=values.get(key, options.get(key, False)))] = selector.BooleanSelector()
        for key, default in LIFECYCLE_DEFAULTS.items():
            maximum = 240 if key == "api_before_minutes" else 48
            minimum = 1 if key == "connection_hours" else 0
            schema[vol.Optional(key, default=values.get(key, options.get(key, default)))] = selector.NumberSelector(
                selector.NumberSelectorConfig(min=minimum, max=maximum, step=1 if key in ("connection_hours", "api_before_minutes") else 0.5, mode=selector.NumberSelectorMode.BOX))
        return vol.Schema(schema)
