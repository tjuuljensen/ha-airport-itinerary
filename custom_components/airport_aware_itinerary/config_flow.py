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
    CONF_TRACKED_FLIGHTS_ENTITY,
    DOMAIN,
    NAME,
)


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
            tracked_source = user_input.get(CONF_TRACKED_FLIGHTS_ENTITY)
            auto_track = user_input.get(CONF_FR24_AUTO_TRACK, False)
            add_to_track_entity = user_input.get(CONF_FR24_ADD_TO_TRACK_ENTITY)
            if auto_track and not add_to_track_entity:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(user_input),
                    errors={"base": "select_add_to_track_entity"},
                )
            if auto_track and not tracked_source:
                return self.async_show_form(
                    step_id="init",
                    data_schema=self._options_schema(user_input),
                    errors={"base": "select_tracked_flights_entity"},
                )
            options = {}
            if tracked_source:
                options[CONF_TRACKED_FLIGHTS_ENTITY] = tracked_source
            if add_to_track_entity:
                options[CONF_FR24_ADD_TO_TRACK_ENTITY] = add_to_track_entity
            if auto_track:
                options[CONF_FR24_AUTO_TRACK] = True
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
            vol.Optional(
                CONF_TRACKED_FLIGHTS_ENTITY,
                **({"default": tracked_source} if tracked_source else {}),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="sensor", integration="flightradar24")
            ),
            vol.Optional(CONF_FR24_AUTO_TRACK, default=auto_track): selector.BooleanSelector(),
            vol.Optional(
                CONF_FR24_ADD_TO_TRACK_ENTITY,
                **({"default": add_to_track_entity} if add_to_track_entity else {}),
            ): selector.EntitySelector(
                selector.EntitySelectorConfig(domain="text", integration="flightradar24")
            ),
        }
        return vol.Schema(schema)
