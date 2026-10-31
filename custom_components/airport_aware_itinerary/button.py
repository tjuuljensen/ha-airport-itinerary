"""Explicit maintenance actions; never download on an automatic schedule."""

from homeassistant.components.button import ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError
from .const import DOMAIN


async def async_setup_entry(hass, entry, async_add_entities):
    airports = hass.data[DOMAIN][entry.entry_id]["airports"]
    async_add_entities([AirportDataButton(entry, airports, False), AirportDataButton(entry, airports, True)])


class AirportDataButton(ButtonEntity):
    _attr_has_entity_name = True
    _attr_entity_category = EntityCategory.CONFIG
    _attr_icon = "mdi:airport"

    def __init__(self, entry, airports, restore):
        self.airports, self.restore = airports, restore
        self._attr_name = "Restore bundled airport data" if restore else "Refresh airport data"
        key = "restore_bundled_airport_data" if restore else "refresh_airport_data"
        self._attr_unique_id = f"{entry.entry_id}_{key}"
        self._attr_suggested_object_id = f"airport_itinerary_{key}"
        self.entity_id = f"button.airport_itinerary_{key}"

    async def async_press(self):
        result = await (self.airports.async_restore() if self.restore else self.airports.async_refresh())
        if not result["success"]:
            raise HomeAssistantError(result["error"])
