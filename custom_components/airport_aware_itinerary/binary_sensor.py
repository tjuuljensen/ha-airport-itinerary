"""Aggregate itinerary fetching requirement for external automations."""

from homeassistant.components.binary_sensor import BinarySensorEntity
from homeassistant.core import callback
from .const import DOMAIN, EVENT_LIFECYCLE


async def async_setup_entry(hass, entry, async_add_entities):
    async_add_entities([TrackingRequired(entry, hass.data[DOMAIN][entry.entry_id]["tracker"])])


class TrackingRequired(BinarySensorEntity):
    _attr_has_entity_name = True
    _attr_name = "Tracking required"
    _attr_icon = "mdi:airplane-clock"
    _attr_suggested_object_id = "airport_itinerary_tracking_required"

    def __init__(self, entry, tracker):
        self._attr_unique_id = f"{entry.entry_id}_tracking_required"
        self.entity_id = "binary_sensor.airport_itinerary_tracking_required"
        self.tracker = tracker

    @property
    def is_on(self):
        return self.tracker.view.get("tracking_required", False)

    async def async_added_to_hass(self):
        self.async_on_remove(self.hass.bus.async_listen(EVENT_LIFECYCLE, self._updated))

    @callback
    def _updated(self, event):
        self.async_write_ha_state()
