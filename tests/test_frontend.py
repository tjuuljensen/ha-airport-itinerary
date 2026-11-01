"""Bundled resource migration must preserve unrelated dashboard resources."""

from types import SimpleNamespace
from unittest.mock import AsyncMock

from custom_components.airport_aware_itinerary.frontend import (
    CARD_PATH, CARD_URL, CARD_VERSION, RESOURCE_URL, async_setup_frontend,
)
from custom_components.airport_aware_itinerary.const import DOMAIN
from homeassistant.components.lovelace import LOVELACE_DATA
from pytest_homeassistant_custom_component.common import MockConfigEntry


class Resources:
    def __init__(self, rows):
        self.rows = rows
        self.loaded = False

    async def async_get_info(self):
        self.loaded = True

    def async_items(self):
        assert self.loaded, "Must load persisted resources before any mutation"
        return self.rows

    async def async_update_item(self, id, data):
        row = next(row for row in self.rows if row["id"] == id)
        row.update(url=data["url"], type=data["res_type"])

    async def async_delete_item(self, id):
        self.rows = [row for row in self.rows if row["id"] != id]

    async def async_create_item(self, data):
        self.rows.append({"id": "new", "url": data["url"], "type": data["res_type"]})


async def test_resource_migration_is_idempotent_and_preserves_other_resources():
    unrelated = {"id": "other", "url": "/local/my-card.js?v=3", "type": "module"}
    external = {"id": "external", "url": "https://example.org/local/lovelace-airport-itinerary/airport-itinerary.js", "type": "module"}
    resources = Resources([unrelated.copy(), external.copy(),
        {"id": "old", "url": "/hacsfiles/lovelace-airport-itinerary/airport-itinerary.js?v=24", "type": "module"},
        {"id": "duplicate", "url": "/local/lovelace-airport-itinerary/airport-itinerary.js", "type": "module"}])
    http = SimpleNamespace(async_register_static_paths=AsyncMock())
    hass = SimpleNamespace(http=http, data={LOVELACE_DATA: SimpleNamespace(resource_mode="storage", resources=resources)})
    await async_setup_frontend(hass)
    await async_setup_frontend(hass)
    assert resources.rows == [unrelated, external, {"id": "old", "url": RESOURCE_URL, "type": "module"}]
    http.async_register_static_paths.assert_awaited_once()
    assert CARD_PATH.is_file()


async def test_new_install_registers_resource_and_yaml_mode_is_not_modified():
    resources = Resources([])
    ll = SimpleNamespace(resource_mode="storage", resources=resources)
    hass = SimpleNamespace(http=SimpleNamespace(async_register_static_paths=AsyncMock()), data={LOVELACE_DATA: ll})
    await async_setup_frontend(hass)
    assert resources.rows == [{"id": "new", "url": RESOURCE_URL, "type": "module"}]
    ll.resource_mode = "yaml"
    ll.resources = Resources([])
    await async_setup_frontend(hass)
    assert not ll.resources.loaded
    assert not ll.resources.rows


async def test_bundled_module_is_served_by_ha_and_survives_entry_reload(hass, hass_client):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    sensor = hass.states.get("sensor.flight_itineraries")
    assert sensor.attributes["card_version"] == CARD_VERSION
    assert f'const CARD_VERSION = "{CARD_VERSION}";' in CARD_PATH.read_text()
    client = await hass_client()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert await response.read() == CARD_PATH.read_bytes()
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    response = await client.get(CARD_URL)
    assert response.status == 200
    assert sum(row["url"] == RESOURCE_URL for row in hass.data[LOVELACE_DATA].resources.async_items()) == 1
