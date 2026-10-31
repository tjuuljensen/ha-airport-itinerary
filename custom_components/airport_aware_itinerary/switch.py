"""Persistent master connection control, independent of FR24's fetching switch."""

from homeassistant.components.switch import SwitchEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .const import CONF_FR24_CONNECTION, DOMAIN, EVENT_LIFECYCLE
from .fr24_config import connection_error


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([FR24ConnectionSwitch(entry, hass.data[DOMAIN][entry.entry_id]["tracker"])])


class FR24ConnectionSwitch(SwitchEntity):
    _attr_has_entity_name = True
    _attr_name = "FR24 connection"
    _attr_icon = "mdi:airplane-cog"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, entry, tracker):
        self.entry, self.tracker = entry, tracker
        self._attr_unique_id = f"{entry.entry_id}_fr24_connection"
        self.entity_id = "switch.airport_itinerary_fr24_connection"

    @property
    def is_on(self):
        return self.tracker.connection_enabled

    async def async_added_to_hass(self):
        self.hass.bus.async_fire(EVENT_LIFECYCLE)

    async def _set_enabled(self, enabled):
        if self.is_on == enabled:
            return
        if enabled and connection_error(self.hass, {**self.entry.data, **self.entry.options}):
            raise HomeAssistantError("Check the FR24 entity selections in Airport Itinerary options before enabling the connection.")
        if not enabled:
            self.tracker.set_connection_enabled(False)
            # Finish any in-flight reconciliation before replacing its manager.
            await self.tracker.async_sync()
        self.hass.config_entries.async_update_entry(
            self.entry, options={**self.entry.options, CONF_FR24_CONNECTION: enabled})
        self.async_write_ha_state()

    async def async_turn_on(self, **kwargs):
        await self._set_enabled(True)

    async def async_turn_off(self, **kwargs):
        await self._set_enabled(False)
