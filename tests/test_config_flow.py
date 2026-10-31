"""Config flow tests for local setup and optional provider behavior."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airport_aware_itinerary.const import (
    CONF_FR24_ADD_TO_TRACK_ENTITY,
    CONF_FR24_AUTO_TRACK,
    CONF_TRACKED_FLIGHTS_ENTITY,
    DOMAIN,
    NAME,
    LIFECYCLE_DEFAULTS,
)

CONTROL_DEFAULTS = {**LIFECYCLE_DEFAULTS, "fr24_connection_enabled": True, "fr24_auto_cleanup": False,
                    "fr24_auto_enable": False, "fr24_auto_disable": False}


@pytest.fixture(autouse=True)
def registered_fr24_entities(hass):
    entry = MockConfigEntry(domain="flightradar24", data={})
    entry.add_to_hass(hass)
    registry = er.async_get(hass)
    for domain, object_id in (("sensor", "fr24_additional_tracked"), ("sensor", "flightradar24_additional_tracked"),
                              ("text", "flightradar24_add_to_track"), ("text", "flightradar24_remove_from_track"),
                              ("switch", "flightradar24_api_data_fetching")):
        registry.async_get_or_create(domain, "flightradar24", object_id, suggested_object_id=object_id, config_entry=entry)


async def test_user_can_configure_without_provider(hass):
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        user_input={},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == NAME
    assert result["data"] == {}


async def test_only_one_local_itinerary_store_can_be_configured(hass):
    first = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )
    await hass.config_entries.flow.async_configure(first["flow_id"], user_input={})

    second = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": SOURCE_USER},
    )

    assert second["type"] is FlowResultType.ABORT
    assert second["reason"] == "already_configured"


async def test_options_can_connect_and_disconnect_fr24_sensor(hass):
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, data={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_TRACKED_FLIGHTS_ENTITY: "sensor.fr24_additional_tracked"},
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_TRACKED_FLIGHTS_ENTITY: "sensor.fr24_additional_tracked", **CONTROL_DEFAULTS,
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == CONTROL_DEFAULTS


async def test_auto_tracking_requires_and_saves_fr24_add_entity(hass):
    entry = MockConfigEntry(domain=DOMAIN, title=NAME, data={})
    entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={CONF_FR24_AUTO_TRACK: True},
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "select_add_to_track_entity"}

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        user_input={
            CONF_FR24_AUTO_TRACK: True,
            CONF_FR24_ADD_TO_TRACK_ENTITY: "text.flightradar24_add_to_track",
            CONF_TRACKED_FLIGHTS_ENTITY: "sensor.flightradar24_additional_tracked",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        **CONTROL_DEFAULTS,
        CONF_FR24_AUTO_TRACK: True,
        CONF_FR24_ADD_TO_TRACK_ENTITY: "text.flightradar24_add_to_track",
        CONF_TRACKED_FLIGHTS_ENTITY: "sensor.flightradar24_additional_tracked",
    }


async def test_options_reject_entities_from_different_fr24_entries(hass):
    other = MockConfigEntry(domain="flightradar24", data={})
    other.add_to_hass(hass)
    er.async_get(hass).async_get_or_create("switch", "flightradar24", "other", suggested_object_id="other_fr24", config_entry=other)
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={
        CONF_TRACKED_FLIGHTS_ENTITY: "sensor.fr24_additional_tracked", "fr24_api_switch": "switch.other_fr24"})
    assert result["errors"] == {"base": "different_fr24_entry"}


async def test_disconnected_options_keep_missing_entities_for_later_repair(hass):
    entry = MockConfigEntry(domain=DOMAIN, data={})
    entry.add_to_hass(hass)
    options = {"fr24_connection_enabled": False, "tracked_flights_entity": "sensor.removed_fr24",
               "fr24_add_to_track_entity": "text.removed_fr24", "fr24_auto_track": True}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input=options)
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert all(result["data"][key] == value for key, value in options.items())
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], user_input={**options, "fr24_connection_enabled": True})
    assert result["errors"] == {"base": "different_fr24_entry"}
