"""Config flow tests for local setup and optional provider behavior."""

from homeassistant.config_entries import SOURCE_USER
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.airport_aware_itinerary.const import (
    CONF_FR24_ADD_TO_TRACK_ENTITY,
    CONF_FR24_AUTO_TRACK,
    CONF_TRACKED_FLIGHTS_ENTITY,
    DOMAIN,
    NAME,
)


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
        CONF_TRACKED_FLIGHTS_ENTITY: "sensor.fr24_additional_tracked"
    }

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], user_input={}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {}


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
        CONF_FR24_AUTO_TRACK: True,
        CONF_FR24_ADD_TO_TRACK_ENTITY: "text.flightradar24_add_to_track",
        CONF_TRACKED_FLIGHTS_ENTITY: "sensor.flightradar24_additional_tracked",
    }
