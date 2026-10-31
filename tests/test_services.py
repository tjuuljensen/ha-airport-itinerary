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


async def test_connection_switch_preserves_options_and_schedules(hass):
    fr24 = MockConfigEntry(domain="flightradar24", data={})
    fr24.add_to_hass(hass)
    registry = er.async_get(hass)
    for domain, key in [("sensor", "fr24"), ("text", "fr24_add"), ("text", "fr24_remove"), ("switch", "fr24_api")]:
        registry.async_get_or_create(domain, "flightradar24", key, suggested_object_id=key, config_entry=fr24)
    entry = MockConfigEntry(domain=DOMAIN, data={}, options={
        "tracked_flights_entity": "sensor.fr24", "fr24_add_to_track_entity": "text.fr24_add",
        "fr24_remove_from_track_entity": "text.fr24_remove", "fr24_api_switch": "switch.fr24_api",
        "fr24_auto_track": True, "api_before_minutes": 90,
    })
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    expected = dict(entry.options)
    created = await hass.services.async_call(DOMAIN, "create_itinerary", {"name": "Keep me"}, blocking=True, return_response=True)
    for enabled in (False, True, False):
        await hass.services.async_call("switch", "turn_on" if enabled else "turn_off",
            {"entity_id": "switch.airport_itinerary_fr24_connection"}, blocking=True)
        await hass.async_block_till_done()
        assert dict(entry.options) == {**expected, "fr24_connection_enabled": enabled}
        assert hass.states.get("switch.airport_itinerary_fr24_connection").state == ("on" if enabled else "off")
        sensor = hass.states.get("sensor.flight_itineraries")
        assert sensor.attributes["fr24_connection_entity"] == "switch.airport_itinerary_fr24_connection"
        assert sensor.attributes["itineraries"][0]["id"] == created["itinerary"]["id"]
        if not enabled:
            assert sensor.attributes["tracking_source_health"] == "disabled"
            assert sensor.attributes["tracked_legs"] == []
            assert hass.states.get("binary_sensor.airport_itinerary_tracking_required").state == "off"
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("switch.airport_itinerary_fr24_connection").state == "off"


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
    assert added["leg"]["label"] == "Denver to Munich"
    entity_id = er.async_get(hass).async_get_entity_id("sensor", DOMAIN, entry.entry_id)
    entity = hass.states.get(entity_id)
    assert entity is not None
    assert entity.attributes["itineraries"][0]["legs"][0]["flight_number"] == "UA760"


async def test_arrival_fold_is_independent_and_saved_times_survive_map_changes(hass):
    from custom_components.airport_aware_itinerary.airport_data import get_airport_timezones, set_active_data, data_payload
    from copy import deepcopy
    await _setup(hass)
    created = await hass.services.async_call(DOMAIN, "create_itinerary", {"name": "DST arrival"}, blocking=True, return_response=True)
    payload = {"itinerary_id": created["itinerary"]["id"], "flight_number": "TEST1", "origin_airport": "LHR",
               "destination_airport": "CPH", "service_date": "2026-10-24", "departure_time": "23:00",
               "arrival_date": "2026-10-25", "arrival_time": "02:30"}
    rejected = await hass.services.async_call(DOMAIN, "add_flight", payload, blocking=True, return_response=True)
    assert not rejected["success"] and "occurs twice" in rejected["error"]
    added = await hass.services.async_call(DOMAIN, "add_flight", {**payload, "arrival_fold": "later"}, blocking=True, return_response=True)
    assert added["success"]
    assert added["leg"]["arrival"]["utc_timestamp"] == "2026-10-25T01:30:00+00:00"
    original = data_payload()
    changed = deepcopy(original)
    changed["airports"]["CPH"] = "Europe/London"
    try:
        set_active_data(changed)
        assert get_airport_timezones()["CPH"] == "Europe/London"
        entry_data = next(value for value in hass.data[DOMAIN].values() if isinstance(value, dict) and "manager" in value)
        saved = entry_data["manager"].snapshot()[0]["legs"][0]
        assert saved["arrival"]["timezone"] == "Europe/Copenhagen"
        assert saved["arrival"]["utc_timestamp"] == "2026-10-25T01:30:00+00:00"
    finally:
        set_active_data(original)


async def test_public_lifecycle_entities_and_manual_completion_service(hass):
    entry = await _setup(hass)
    assert hass.states.get("binary_sensor.airport_itinerary_tracking_required").state == "off"
    assert hass.states.get("sensor.airport_itinerary_api_start_at") is not None
    assert hass.states.get("button.airport_itinerary_refresh_airport_data") is not None
    result = await hass.services.async_call(DOMAIN, "mark_flight_completed", {"itinerary_id": "missing", "leg_id": "missing"}, blocking=True, return_response=True)
    assert result["success"] is False
    assert await hass.config_entries.async_unload(entry.entry_id)
    assert not hass.services.has_service(DOMAIN, "refresh_airport_data")
