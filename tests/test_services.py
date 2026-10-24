"""Home Assistant action tests for time resolution and itinerary storage."""

from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airport_aware_itinerary.const import DOMAIN


async def _setup(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_resolve_departure_returns_explicit_local_offset(hass):
    await _setup(hass)

    result = await hass.services.async_call(
        DOMAIN,
        "resolve_departure",
        {"origin_airport": "DEN", "service_date": "2026-10-22", "departure_time": "20:25"},
        blocking=True,
        return_response=True,
    )

    assert result["success"] is True
    assert result["timestamp"] == "2026-10-22T20:25:00-06:00"


async def test_unknown_airport_returns_visible_error(hass):
    await _setup(hass)

    result = await hass.services.async_call(
        DOMAIN,
        "resolve_departure",
        {"origin_airport": "XXX", "service_date": "2026-10-22", "departure_time": "20:25"},
        blocking=True,
        return_response=True,
    )

    assert result["success"] is False
    assert "No timezone data" in result["error"]


async def test_create_and_add_actions_persist_native_itinerary(hass):
    entry = await _setup(hass)
    created = await hass.services.async_call(
        DOMAIN,
        "create_itinerary",
        {"name": "Autumn trip"},
        blocking=True,
        return_response=True,
    )
    itinerary_id = created["itinerary"]["id"]

    added = await hass.services.async_call(
        DOMAIN,
        "add_flight",
        {
            "itinerary_id": itinerary_id,
            "flight_number": "UA760",
            "origin_airport": "DEN",
            "destination_airport": "MUC",
            "service_date": "2026-10-22",
            "departure_time": "20:25",
            "label": "Denver to Munich",
        },
        blocking=True,
        return_response=True,
    )

    assert added["success"] is True
    assert added["leg"]["departure"]["timestamp"] == "2026-10-22T20:25:00-06:00"
    assert added["leg"]["destination_timezone"] == "Europe/Berlin"
    assert added["leg"]["label"] == "DEN-MUC"
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, entry.entry_id)
    entity = hass.states.get(entity_id)
    assert entity is not None
    assert entity.attributes["itineraries"][0]["legs"][0]["flight_number"] == "UA760"
