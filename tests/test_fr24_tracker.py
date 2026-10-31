"""Lifecycle regressions use HA states/services, without contacting FR24."""

from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import AsyncMock

import pytest

from custom_components.airport_aware_itinerary.fr24_tracker import FR24ItineraryTracker
from custom_components.airport_aware_itinerary.manager import ItineraryManager
from custom_components.airport_aware_itinerary.lifecycle import occurrence, identity, iso, journeys, match_flight
from custom_components.airport_aware_itinerary.lifecycle import expires_at, number
from homeassistant.core import Event
from pytest_homeassistant_custom_component.common import async_fire_time_changed

SOURCE = "sensor.fr24_additional_tracked"
SWITCH = "switch.fr24_api"
ADD = "text.fr24_add"
REMOVE = "text.fr24_remove"
NOW = datetime(2026, 10, 23, 10, tzinfo=timezone.utc).timestamp()


def leg(number="SK0935", offset=3600, **extra):
    return {"id": f"leg-{number}-{offset}", "flight_number": number,
            "origin_airport": "CPH", "destination_airport": "LAX", "service_date": "2026-10-23",
            "departure": {"utc_timestamp": iso(NOW + offset), "timezone": "Europe/Copenhagen"}, **extra}


def flight(row=None, **extra):
    row = row or leg()
    return {"id": "provider-1", "flight_number": "SK935", "time_scheduled_departure": row["departure"]["utc_timestamp"],
            "airport_origin_code_iata": row["origin_airport"], "airport_destination_code_iata": row["destination_airport"],
            "tracked_type": "schedule", **extra}


@pytest.fixture
def setup_tracker(hass, freezer):
    freezer.move_to(datetime.fromtimestamp(NOW, timezone.utc))
    trackers = []
    calls = []

    async def text_service(call):
        calls.append(dict(call.data))  # Deliberately silent, like an unresolved FR24 request.

    async def switch_service(call):
        calls.append({"service": call.service, **call.data})
        hass.states.async_set(SWITCH, "on" if call.service == "turn_on" else "off")

    hass.services.async_register("text", "set_value", text_service)
    hass.services.async_register("switch", "turn_on", switch_service)
    hass.services.async_register("switch", "turn_off", switch_service)

    def make(rows=None, flights=None, saved=None, **options):
        hass.states.async_set(SOURCE, str(len(flights or [])), {"flights": flights or []})
        hass.states.async_set(SWITCH, "on")
        manager = ItineraryManager(hass, AsyncMock(), saved or {"itineraries": [{"id": "trip", "name": "Trip", "legs": rows if rows is not None else [leg()]}]})
        config = {"tracked_flights_entity": SOURCE, "fr24_add_to_track_entity": ADD,
                  "fr24_remove_from_track_entity": REMOVE, "fr24_api_switch": SWITCH,
                  "fr24_auto_track": True, "fr24_auto_cleanup": True, **options}
        tracker = FR24ItineraryTracker(hass, manager, config)
        trackers.append(tracker)
        return tracker, manager, calls

    yield make
    for tracker in trackers:
        tracker.stop()


async def test_silent_add_retries_and_observation_confirms_ownership(hass, setup_tracker, freezer):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    assert calls == [{"entity_id": ADD, "value": "SK0935"}]
    await tracker.async_sync(NOW + 899)
    assert len(calls) == 1
    await tracker.async_sync(NOW + 900)
    assert calls[-1]["value"] == "SK935"
    record = manager.lifecycle_snapshot()["records"][occurrence(leg())]
    assert record["pending_add"] and not record["owned"]
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW + 901)
    assert manager.lifecycle_snapshot()["records"][occurrence(leg())]["owned"]


async def test_disconnect_retains_owned_cleanup_and_ignores_fr24_events(hass, setup_tracker):
    tracker, manager, calls = setup_tracker(fr24_auto_enable=True, fr24_auto_disable=True)
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW + 1)
    calls.clear()
    tracker.set_connection_enabled(False)
    tracker._handle_flight_event(Event("flightradar24_tracked_landed", flight(time_real_landing=NOW)))
    hass.states.async_set(SOURCE, "1", {"flights": [flight(time_gate_arrival=NOW)]})
    await tracker.async_sync(NOW + 2)
    assert not calls and not tracker._events
    assert not tracker.view["tracking_required"] and tracker.view["api_start_at"] is None
    assert not tracker.view["connection_enabled"] and not tracker.view["session_owned"]
    record = manager.lifecycle_snapshot()["records"][occurrence(leg())]
    assert record["owned"] and not record["evidence"]
    saved = deepcopy(manager._data)
    restarted, restored, _ = setup_tracker(saved=saved, flights=[flight(time_gate_arrival=NOW)], fr24_connection_enabled=False)
    await restarted.async_sync(NOW + 3)
    assert not calls and restored.lifecycle_snapshot()["records"][occurrence(leg())]["owned"]
    restarted.set_connection_enabled(True)
    await restarted.async_sync(NOW + 4)
    assert calls == [{"entity_id": REMOVE, "value": "SK935"}]


async def test_disconnect_does_not_adopt_unconfirmed_addition(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    tracker.set_connection_enabled(False)
    await tracker.async_sync(NOW + 1)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    calls.clear()
    tracker.set_connection_enabled(True)
    await tracker.async_sync(NOW + 2)
    assert not manager.lifecycle_snapshot()["records"][occurrence(leg())]["owned"]
    assert not calls


async def test_windows_and_same_number_different_dates(setup_tracker):
    rows = [leg(offset=5 * 3600), leg(offset=-7 * 3600), leg(offset=3600), leg(offset=25 * 3600, service_date="2026-10-24")]
    tracker, _, calls = setup_tracker(rows)
    await tracker.async_sync(NOW)
    assert len(calls) == 1


async def test_preexisting_record_never_owned_or_removed(hass, setup_tracker):
    tracker, manager, calls = setup_tracker(flights=[flight(time_gate_arrival=NOW - 10)])
    await tracker.async_sync(NOW)
    assert not calls
    assert not manager.lifecycle_snapshot()["records"][occurrence(leg())]["owned"]


async def test_cleanup_survives_restart_and_deleted_itinerary(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW)
    await manager.async_delete_itinerary("trip")
    restarted, restored, _ = setup_tracker(saved=deepcopy(manager._data), flights=[flight()])
    await restarted.async_sync(NOW)
    assert calls[-1] == {"entity_id": REMOVE, "value": "SK935"}
    assert restored.lifecycle_snapshot()["records"][occurrence(leg())]["owned"]
    hass.states.async_set(SOURCE, "0", {"flights": []})
    await restarted.async_sync(NOW + 1)
    assert not restored.lifecycle_snapshot()["records"]


async def test_delete_while_add_is_pending_still_cleans_confirmed_addition(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    await manager.async_delete_itinerary("trip")
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW + 1)
    assert calls[-1]["entity_id"] == REMOVE


async def test_touchdown_retention_and_gate_cleanup_persist_evidence(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight(time_real_landing=NOW - 60)]})
    await tracker.async_sync(NOW)
    assert len(calls) == 1
    assert manager.snapshot()[0]["legs"][0]["finished_at"] == iso(NOW - 60)
    assert manager.snapshot()[0]["legs"][0]["arrival_phase"] == "landed"
    assert not tracker.view["journeys"][0]["completed"]
    assert tracker.view["journeys"][0]["arrival_pending"]
    hass.states.async_set(SOURCE, "1", {"flights": [flight(time_real_landing=NOW - 60, time_gate_arrival=NOW)]})
    await tracker.async_sync(NOW)
    assert calls[-1]["entity_id"] == REMOVE
    assert manager.snapshot()[0]["legs"][0]["arrival_phase"] == "at_gate"
    assert manager.snapshot()[0]["legs"][0]["final_arrival_at"] == iso(NOW)
    assert tracker.view["journeys"][0]["completed"]
    assert tracker.view["journeys"][0]["api_stop_at"] == iso(NOW - 60 + 7200)


async def test_real_arrival_waits_for_gate_flag_and_survives_restart(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    events = []
    unsubscribe = hass.bus.async_listen("airport_aware_itinerary_flight_event", lambda event: events.append(event.data))
    await tracker.async_sync(NOW)
    landed = flight(tracked_type="live", on_ground=True, has_landed=True,
                    time_real_arrival=NOW - 600, gate_arrived_sent=False)
    hass.states.async_set(SOURCE, "1", {"flights": [landed]})
    await tracker.async_sync(NOW)
    await hass.async_block_till_done()
    stored = manager.snapshot()[0]["legs"][0]
    assert stored["arrival_phase"] == "landed" and stored["final_arrival_at"] is None
    assert tracker.view["journeys"][0]["status"] == "landed"
    assert [event["event"] for event in events] == ["touchdown"]
    assert len(calls) == 1  # Landing did not immediately remove the owned flight.
    tracker.stop()
    restarted, restored, _ = setup_tracker(saved=deepcopy(manager._data), flights=[])
    await restarted.async_sync(NOW + 1)
    assert restored.snapshot()[0]["legs"][0]["arrival_phase"] == "landed"
    assert not restored.snapshot()[0]["legs"][0]["final_arrival_at"]
    assert len(calls) == 1  # Do not add a disappeared landed flight again.
    hass.states.async_set(SOURCE, "1", {"flights": [{**landed, "gate_arrived_sent": True}]})
    await restarted.async_sync(NOW + 2)
    await restarted.async_sync(NOW + 3)
    await hass.async_block_till_done()
    stored = restored.snapshot()[0]["legs"][0]
    assert stored["final_arrival_at"] == iso(NOW + 2)  # Not the earlier landing time.
    assert stored["arrival_phase"] == "at_gate"
    assert [event["event"] for event in events] == ["touchdown", "gate_arrival"]
    assert events[-1]["event_time"] == iso(NOW + 2)
    restarted.stop()
    again, restored, _ = setup_tracker(saved=deepcopy(restored._data), flights=[])
    await again.async_sync(NOW + 4)
    assert restored.snapshot()[0]["legs"][0]["arrival_phase"] == "at_gate"
    unsubscribe()


@pytest.mark.parametrize("flag", [False, "false", "true", 1, None])
async def test_gate_flag_requires_boolean_confirmation(setup_tracker, flag):
    tracker, manager, _ = setup_tracker(flights=[flight(gate_arrived_sent=flag)])
    await tracker.async_sync(NOW)
    assert manager.snapshot()[0]["legs"][0]["final_arrival_at"] is None


async def test_stale_gate_flag_does_not_create_final_arrival(setup_tracker):
    tracker, manager, _ = setup_tracker(flights=[flight(gate_arrived_sent=True)])
    await tracker.async_sync(NOW + 301)
    assert manager.snapshot()[0]["legs"][0]["final_arrival_at"] is None


async def test_legacy_finished_timestamp_is_landing_not_gate(setup_tracker):
    tracker, manager, _ = setup_tracker(rows=[leg(finished_at=iso(NOW - 60))])
    await tracker.async_sync(NOW)
    stored = manager.snapshot()[0]["legs"][0]
    assert stored["finished_at"] == iso(NOW - 60)
    assert stored["arrival_phase"] == "landed" and stored["final_arrival_at"] is None
    assert not tracker.view["journeys"][0]["completed"]


async def test_manual_completion_deduplicates_events_without_landing(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    events = []
    unsubscribe = hass.bus.async_listen("airport_aware_itinerary_flight_event", lambda event: events.append(event.data))
    await manager.async_mark_flight_completed("trip", leg()["id"])
    await manager.async_mark_flight_completed("trip", leg()["id"])
    await hass.async_block_till_done()
    await tracker.async_sync(NOW)
    stored = manager.snapshot()[0]["legs"][0]
    assert stored["completed"] and not stored.get("finished_at")
    assert len(events) == 1 and events[0]["evidence_source"] == "manual"
    assert not calls
    unsubscribe()


async def test_unavailable_source_blocks_cleanup_and_shutdown(hass, setup_tracker):
    tracker, manager, calls = setup_tracker(fr24_auto_disable=True)
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW)
    await manager.async_delete_itinerary("trip")
    hass.states.async_set(SOURCE, "unavailable")
    tracker._session_owned = True
    calls.clear()
    await tracker.async_sync(NOW + 1)
    assert not calls and tracker.view["cleanup_pending"]


async def test_shutdown_only_owned_sessions_without_unrelated_flights(hass, setup_tracker, freezer):
    tracker, manager, calls = setup_tracker(fr24_auto_enable=True, fr24_auto_disable=True)
    hass.states.async_set(SWITCH, "off")
    await tracker.async_sync(NOW)
    assert tracker.view["session_owned"]
    await manager.async_delete_itinerary("trip")
    hass.states.async_set(SOURCE, "1", {"flights": [flight(flight_number="BA123")]})
    calls.clear()
    await tracker.async_sync(NOW + 1)
    assert not any(call.get("service") == "turn_off" for call in calls)
    freezer.move_to(datetime.fromtimestamp(NOW + 901, timezone.utc))
    hass.states.async_set(SOURCE, "0", {"flights": []})
    await tracker.async_sync(NOW + 901)
    assert calls[-1]["service"] == "turn_off"
    restarted, _, calls = setup_tracker(rows=[], fr24_auto_disable=True)
    calls.clear()
    await restarted.async_sync(NOW)
    assert not calls  # A running switch after restart is not an owned session.


async def test_manual_off_is_respected_until_journey_ends(hass, setup_tracker):
    tracker, _, calls = setup_tracker(fr24_auto_enable=True)
    tracker.start()
    await tracker.async_sync(NOW)
    hass.states.async_set(SWITCH, "off")
    await hass.async_block_till_done()
    calls.clear()
    await tracker.async_sync(NOW + 1)
    assert not calls and tracker.view["paused_journeys"]


async def test_shared_occurrence_is_not_removed_when_one_trip_is_deleted(hass, setup_tracker):
    tracker, manager, calls = setup_tracker(saved={"itineraries": [
        {"id": "trip", "name": "One", "legs": [leg()]}, {"id": "two", "name": "Two", "legs": [leg(id="other")]}]})
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW)
    await manager.async_delete_itinerary("trip")
    calls.clear()
    await tracker.async_sync(NOW)
    assert not calls


async def test_aircraft_continuation_is_inferred_only_with_matching_destination(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight(tracked_type="live", on_ground=False, aircraft_registration="OY-X")]})
    await tracker.async_sync(NOW)
    continuation = flight(flight_number="SK999", tracked_type="live", airport_origin_code_iata="LAX", airport_destination_code_iata="SFO",
                          aircraft_registration="OY-X", time_scheduled_departure=NOW + 7200)
    hass.states.async_set(SOURCE, "1", {"flights": [continuation]})
    await tracker.async_sync(NOW + 1)
    stored = manager.snapshot()[0]["legs"][0]
    assert stored["evidence"]["inferred_completion"]
    assert not stored.get("finished_at")
    assert calls[-1] == {"entity_id": REMOVE, "value": "SK999"}


def test_matching_is_occurrence_specific_and_ambiguous_matches_are_rejected():
    row = leg()
    assert match_flight(row, [flight()])
    assert match_flight(row, [flight(time_scheduled_departure=NOW + 86400)]) is None
    assert match_flight(row, [flight(), flight(id="another")]) is None
    assert number("B60012") == "B612"
    assert number("SAS0935") == "SAS935"
    assert number("SK 00935") == "SK935"


def test_connection_grouping_uses_utc_and_splits_long_or_disconnected_stays():
    first = leg(arrival={"utc_timestamp": iso(NOW + 3600)})
    second = leg("SK2", 7200, origin_airport="LAX", destination_airport="SFO")
    third = leg("SK3", 3 * 86400, origin_airport="SFO", destination_airport="CPH")
    result = journeys([{"id": "trip", "name": "Trip", "legs": [first, second, third]}], NOW, {})
    assert [len(item["leg_ids"]) for item in result] == [2, 1]


async def test_tracking_waits_when_fetching_is_off(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    hass.states.async_set(SWITCH, "off")
    await tracker.async_sync(NOW)
    assert not calls
    assert not manager.lifecycle_snapshot()["records"][occurrence(leg())].get("pending_add")


async def test_overdue_touchdown_cleanup_and_fresh_airborne_expiry(hass, setup_tracker, freezer):
    row = leg(offset=-10 * 3600)
    owned = {"leg": row, "owned": True, "identity": identity(flight(row)), "source_entity": SOURCE,
             "evidence": {"touchdown": iso(NOW - 7201)}}
    saved = {"itineraries": [{"id": "trip", "name": "Trip", "legs": [row]}], "lifecycle": {"records": {occurrence(row): owned}}}
    tracker, _, calls = setup_tracker(saved=saved, flights=[flight(row)])
    await tracker.async_sync(NOW)
    assert calls[-1]["entity_id"] == REMOVE
    future = NOW + 3 * 86400
    freezer.move_to(datetime.fromtimestamp(future, timezone.utc))
    row = leg()
    saved = {"itineraries": [{"id": "trip", "name": "Trip", "legs": [row]}], "lifecycle": {"records": {occurrence(row): {
        "leg": row, "owned": True, "identity": identity(flight(row)), "source_entity": SOURCE}}}}
    tracker, _, calls = setup_tracker(saved=saved, flights=[flight(row, tracked_type="live", on_ground=False)])
    calls.clear()
    await tracker.async_sync(future)
    assert tracker.view["tracking_required"]
    assert not calls


async def test_disappearance_is_not_completion_and_removal_ambiguity_is_safe(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "0", {"flights": []})
    await tracker.async_sync(NOW + 1)
    assert not manager.snapshot()[0]["legs"][0].get("finished_at")
    assert not manager.snapshot()[0]["legs"][0].get("completed")


async def test_gate_event_survives_provider_cleanup_and_deduplicates(hass, setup_tracker):
    tracker, manager, calls = setup_tracker(flights=[flight(tracked_type="live", on_ground=False)])
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "0", {"flights": []})
    tracker._handle_flight_event(Event("flightradar24_tracked_arrived_gate", flight()))
    await hass.async_block_till_done()
    assert manager.snapshot()[0]["legs"][0]["evidence"]["gate_arrival"]


def test_origin_day_expiry_crosses_dst_in_local_time():
    row = leg(service_date="2026-10-24")
    # Two local midnights cross Europe's autumn clock change: UTC offset changes.
    assert iso(expires_at(row)) == "2026-10-25T23:00:00+00:00"


async def test_connecting_source_after_offline_use_starts_tracking(hass, setup_tracker):
    tracker, manager, calls = setup_tracker(tracked_flights_entity=None)
    await tracker.async_sync(NOW)
    assert not calls
    connected, _, _ = setup_tracker(saved=deepcopy(manager._data))
    await connected.async_sync(NOW)
    assert calls[-1]["entity_id"] == ADD


async def test_native_timer_reconciles_at_add_window_boundary(hass, setup_tracker, freezer):
    tracker, _, calls = setup_tracker(rows=[leg(offset=4 * 3600 + 60)])
    await tracker.async_sync(NOW)
    assert not calls
    boundary = datetime.fromtimestamp(NOW + 60, timezone.utc)
    freezer.move_to(boundary)
    async_fire_time_changed(hass, boundary)
    await hass.async_block_till_done()
    assert calls[-1]["entity_id"] == ADD


async def test_duplicate_number_makes_cleanup_non_destructive(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight()]})
    await tracker.async_sync(NOW)
    await manager.async_mark_flight_completed("trip", leg()["id"])
    hass.states.async_set(SOURCE, "2", {"flights": [flight(), flight(id="manual-next-day", time_scheduled_departure=NOW + 86400)]})
    calls.clear()
    await tracker.async_sync(NOW)
    assert not calls
    assert tracker.view["cleanup_pending"]


async def test_schedule_to_live_id_change_preserves_owned_occurrence(hass, setup_tracker):
    tracker, manager, calls = setup_tracker()
    await tracker.async_sync(NOW)
    hass.states.async_set(SOURCE, "1", {"flights": [flight(id="scheduled", aircraft_registration="OY-X")]})
    await tracker.async_sync(NOW)
    live = flight(id="live", tracked_type="live", on_ground=0, aircraft_registration="OY-X")
    hass.states.async_set(SOURCE, "1", {"flights": [live]})
    await tracker.async_sync(NOW)
    record = manager.lifecycle_snapshot()["records"][occurrence(leg())]
    assert record["owned"] and record["identity"] == identity(live)
    assert tracker.view["journeys"][0]["airborne"]
    await manager.async_mark_flight_completed("trip", leg()["id"])
    await tracker.async_sync(NOW)
    assert calls[-1]["entity_id"] == REMOVE
    assert not tracker.view["journeys"][0]["airborne"]
