"""Restart-safe FR24 reconciliation through public HA entities only."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
import logging

from homeassistant.core import callback
from homeassistant.helpers.event import async_track_point_in_utc_time, async_track_state_change_event

from .const import (
    CONF_FR24_ADD_TO_TRACK_ENTITY, CONF_FR24_AUTO_TRACK, CONF_FR24_CLEANUP,
    CONF_FR24_DISABLE, CONF_FR24_ENABLE, CONF_FR24_REMOVE_ENTITY, CONF_FR24_SWITCH,
    CONF_TRACKED_FLIGHTS_ENTITY, CONF_FR24_CONNECTION, EVENT_LIFECYCLE, EVENT_UPDATED,
)
from .lifecycle import expires_at, flight_numbers, identity, iso, journeys, match_flight, number, occurrence, terminal, timestamp

_LOGGER = logging.getLogger(__name__)
RETRY_SECONDS = 900
FR24_EVENTS = {"flightradar24_tracked_took_off": "departure",
               "flightradar24_tracked_landed": "touchdown",
               "flightradar24_tracked_arrived_gate": "gate_arrival"}
EVIDENCE_FIELDS = {"departure": ("time_real_departure",), "touchdown": ("time_real_landing", "landing"),
                   "gate_arrival": ("time_gate_arrival", "gate_arrival"), "actual_arrival": ("time_real_arrival",)}


class FR24ItineraryTracker:
    """Own only observed additions, with conservative switch-session ownership."""

    def __init__(self, hass, manager, options: dict) -> None:
        self._hass, self._manager, self.options = hass, manager, options
        self._lock = asyncio.Lock()
        self._cancel_timer = None
        self._unsubscribers = []
        self._stopped = False
        self._events = []
        self._session_owned = False  # Never assume continuity across restart/reload.
        self._switch_command = False
        self._paused = set(manager.lifecycle_snapshot().get("paused_journeys", []))
        self.view = {"journeys": [], "tracking_required": False}

    def start(self):
        self._unsubscribers.append(self._hass.bus.async_listen(EVENT_UPDATED, self.handle_itinerary_updated))
        if not self.connection_enabled:
            return
        entities = [self.options.get(key) for key in (CONF_TRACKED_FLIGHTS_ENTITY, CONF_FR24_SWITCH)]
        if any(entities):
            self._unsubscribers.append(async_track_state_change_event(self._hass, [x for x in entities if x], self.handle_source_updated))
        for event in FR24_EVENTS:
            self._unsubscribers.append(self._hass.bus.async_listen(event, self._handle_flight_event))

    @callback
    def stop(self):
        self._stopped = True
        if self._cancel_timer:
            self._cancel_timer()
        for unsubscribe in self._unsubscribers:
            unsubscribe()

    @callback
    def handle_itinerary_updated(self, event):
        if not self._stopped:
            self._hass.async_create_task(self.async_sync())

    @callback
    def handle_source_updated(self, event):
        if not self.connection_enabled:
            return
        if event.data.get("entity_id") == self.options.get(CONF_FR24_SWITCH):
            old, new = event.data.get("old_state"), event.data.get("new_state")
            if not self._switch_command and old and new and old.state == "on" and new.state == "off":
                self._session_owned = False
                self._paused.update(j["id"] for j in self.view["journeys"] if j["tracking_required"])
            if not new or new.state in {"unknown", "unavailable"}:
                self._session_owned = False
        self.handle_itinerary_updated(event)

    @callback
    def _handle_flight_event(self, event):
        if not self.connection_enabled:
            return
        self._events.append((FR24_EVENTS[event.event_type], dict(event.data)))
        self.handle_itinerary_updated(event)

    def _state(self, option):
        entity = self.options.get(option)
        return self._hass.states.get(entity) if entity else None

    async def _call(self, domain, service, option, **data):
        if self._stopped or not self.connection_enabled:
            return False
        entity = self.options.get(option)
        if not entity:
            return False
        try:
            await self._hass.services.async_call(domain, service, {"entity_id": entity, **data}, blocking=True)
            return True
        except Exception as err:
            _LOGGER.warning("FR24 %s failed: %s", service, err)
            self.view["last_error"] = str(err)
            return False

    async def async_sync(self, now=None):
        async with self._lock:
            if self._stopped:
                return
            now = now if now is not None else datetime.now(timezone.utc).timestamp()
            await self._sync(now)

    async def _sync(self, now):
        if not self.connection_enabled:
            await self._sync_schedule_only(now)
            return
        state = self._manager.lifecycle_snapshot()
        records = state.setdefault("records", {})
        trips = self._manager.snapshot()
        source = self._state(CONF_TRACKED_FLIGHTS_ENTITY)
        healthy = bool(source and source.state not in {"unknown", "unavailable"}
                       and isinstance(source.attributes.get("flights"), list)
                       and all(isinstance(flight, dict) for flight in source.attributes["flights"]))
        flights = source.attributes["flights"] if healthy else []
        switch = self._state(CONF_FR24_SWITCH)
        fetching = switch.state == "on" if self.options.get(CONF_FR24_SWITCH) and switch else not self.options.get(CONF_FR24_SWITCH)
        fresh = healthy and fetching and 0 <= now - source.last_updated.timestamp() <= 300
        responsive = healthy and fetching and 0 <= now - getattr(source, "last_reported", source.last_updated).timestamp() <= 300
        active = {}
        for trip in trips:
            for leg in trip["legs"]:
                active.setdefault(occurrence(leg), []).append(leg)
        observed = {}
        events, self._events = self._events, []
        for key, legs in active.items():
            leg = legs[0]
            source_entity = self.options.get(CONF_TRACKED_FLIGHTS_ENTITY)
            previous = records.get(key)
            if previous and previous.get("source_entity") != source_entity:
                # Never apply an old source's ownership to a newly selected sensor.
                if previous.get("owned") or previous.get("pending_add"):
                    records[f"{previous.get('source_entity')}|{key}"] = previous
                records.pop(key)
                archived = records.pop(f"{source_entity}|{key}", None)
                if archived:
                    records[key] = archived
            record = records.setdefault(key, {"leg": deepcopy(leg), "owned": False,
                                               "source_entity": source_entity})
            record["leg"] = deepcopy(leg)
            evidence = record.setdefault("evidence", {})
            for sibling in legs:
                evidence.update(sibling.get("evidence", {}))
            match = match_flight(leg, flights)
            for kind, payload in events:
                previous_identity = identity(record["last_flight"]) if record.get("last_flight") else None
                if match_flight(leg, [payload]) and identity(payload) in {identity(match) if match else None, previous_identity}:
                    event_time = next((timestamp(payload.get(field)) for field in EVIDENCE_FIELDS[kind]
                                       if 0 < timestamp(payload.get(field)) <= now + 60), now)
                    evidence.setdefault(kind, iso(event_time))
            if match:
                if record.get("pending_add") and identity(match) not in record.get("baseline", []):
                    record.update(owned=True, identity=identity(match), pending_add=False)
                previous = record.get("last_flight", {})
                same_id = previous.get("id") and previous.get("id") == match.get("id")
                same_schedule = (timestamp(previous.get("time_scheduled_departure")) > 0
                                 and timestamp(previous.get("time_scheduled_departure")) == timestamp(match.get("time_scheduled_departure")))
                registration_matches = not (previous.get("aircraft_registration") and match.get("aircraft_registration")) or previous.get("aircraft_registration") == match.get("aircraft_registration")
                if (record.get("owned") and record.get("identity") != identity(match)
                        and (same_id or same_schedule and registration_matches)
                        and not any(identity(row) == record.get("identity") for row in flights)
                        and sum(number(leg["flight_number"]) in flight_numbers(row) for row in flights) == 1):
                    # FR24 replaces scheduled IDs with live IDs. Keep only a uniquely continuous occurrence.
                    record["identity"] = identity(match)
                if fresh:
                    for kind, names in EVIDENCE_FIELDS.items():
                        value = next((timestamp(match.get(name)) for name in names if timestamp(match.get(name))), 0)
                        if value and value <= now + 60:
                            evidence.setdefault(kind, iso(value))
                    # These sticky flags are observations, not timestamps. Never
                    # reuse the landing time as the later gate observation time.
                    if (match.get("has_landed") is True or evidence.get("actual_arrival")) and not evidence.get("touchdown"):
                        evidence.setdefault("touchdown", evidence.get("actual_arrival") or iso(now))
                    if match.get("gate_arrived_sent") is True:
                        evidence.setdefault("gate_arrival", iso(now))
                    record["last_flight"] = {key: match[key] for key in (
                        "id", "flight_number", "callsign", "aircraft_registration", "tracked_type", "on_ground",
                        "airport_origin_code_iata", "airport_destination_code_iata", "time_scheduled_departure") if key in match}
                airborne = bool(fresh and match.get("tracked_type") == "live" and match.get("on_ground") in (False, 0)
                                and "on_ground" in match and not leg.get("completed") and not leg.get("finished_at")
                                and not any(evidence.get(k) for k in ("touchdown", "gate_arrival", "actual_arrival", "manual_completion", "inferred_completion")))
            else:
                airborne = False
                previous = record.get("last_flight", {})
                if fresh and previous.get("aircraft_registration") and previous.get("tracked_type") == "live" and "on_ground" in previous and previous.get("on_ground") in (False, 0):
                    continuation = [f for f in flights if f.get("aircraft_registration") == previous["aircraft_registration"]
                                    and f.get("tracked_type") == "live"
                                    and leg.get("destination_airport") and f.get("airport_origin_code_iata") == leg["destination_airport"]
                                    and number(leg["flight_number"]) not in flight_numbers(f)
                                    and timestamp(f.get("time_scheduled_departure")) > timestamp(previous.get("time_scheduled_departure"))]
                    if len(continuation) == 1:
                        evidence.setdefault("inferred_completion", iso(now))
                        if record.get("owned") and previous.get("id") and continuation[0].get("id") == previous["id"]:
                            record["identity"] = identity(continuation[0])
            observed[key] = evidence
            for sibling in legs:
                sibling["evidence"] = evidence
                sibling["fresh_airborne"] = airborne
        current_journeys = journeys(trips, now, self.options)
        required = any(j["tracking_required"] for j in current_journeys)
        self._paused.intersection_update(j["id"] for j in current_journeys if j["tracking_required"])
        state["paused_journeys"] = sorted(self._paused)
        starts = [timestamp(j["api_start_at"]) for j in current_journeys if timestamp(j["api_start_at"]) > now]
        stops = [timestamp(j["api_stop_at"]) for j in current_journeys if j["tracking_required"] and j["api_stop_at"]]
        self.view = {"connection_enabled": True, "journeys": current_journeys, "tracking_required": required,
                     "api_start_at": iso(min(starts)) if starts else None,
                     "api_stop_at": iso(max(stops)) if stops else None,
                     "fetching": fetching, "auto_track": bool(self.options.get(CONF_FR24_AUTO_TRACK)),
                     "source_available": healthy, "paused_journeys": sorted(self._paused),
                     "last_error": self.view.get("last_error")}
        await self._manager.async_update_lifecycle(state, observed)
        if self.options.get(CONF_FR24_ENABLE) and required and switch and switch.state == "off" and any(
                j["tracking_required"] and j["id"] not in self._paused for j in current_journeys):
            self._switch_command = True
            try:
                if await self._call("switch", "turn_on", CONF_FR24_SWITCH):
                    switch = self._state(CONF_FR24_SWITCH)
                    self._session_owned = bool(switch and switch.state == "on")
                    fetching = self._session_owned
            finally:
                self._switch_command = False
        cleanup_pending = False
        requested = set()
        for key, record in list(records.items()):
            if record.get("source_entity") != self.options.get(CONF_TRACKED_FLIGHTS_ENTITY):
                continue
            leg = record["leg"]
            evidence = record.get("evidence", {})
            if record.get("pending_add"):
                pending_match = match_flight(leg, flights)
                if pending_match and identity(pending_match) not in record.get("baseline", []):
                    record.update(owned=True, identity=identity(pending_match), pending_add=False)
                elif now > record.get("add_attempt_at", 0) + RETRY_SECONDS and not active.get(key):
                    record["pending_add"] = False
                if record.get("pending_add") and not active.get(key):
                    cleanup_pending = True
            current = next((flight for flight in flights if identity(flight) == record.get("identity")), None)
            legs = active.get(key, [])
            touchdown = timestamp(evidence.get("touchdown")) or timestamp(evidence.get("actual_arrival")) or timestamp(leg.get("finished_at"))
            due = (not legs or evidence.get("manual_completion") or evidence.get("inferred_completion")
                   or evidence.get("gate_arrival") or touchdown and now >= touchdown + self.options.get("cleanup_after_hours", 2) * 3600
                   or now >= expires_at(leg) and not any(row.get("fresh_airborne") for row in legs))
            if record.get("owned") and healthy and current is None:
                record.update(owned=False, pending_remove=False)
            if record.get("owned") and due:
                cleanup_pending = True
                removal_number = current.get("flight_number") if current else None
                safe = removal_number and sum(number(removal_number) in flight_numbers(f) for f in flights) == 1
                if current and any(other_key != key and not terminal(other) and now < expires_at(other)
                                   and match_flight(other, flights) == current for other_key, rows in active.items() for other in rows):
                    safe = False
                if self.options.get(CONF_FR24_CLEANUP) and responsive and safe and now - record.get("remove_attempt_at", 0) >= RETRY_SECONDS:
                    record.update(remove_attempt_at=now, pending_remove=True)
                    await self._manager.async_update_lifecycle(state, {})
                    await self._call("text", "set_value", CONF_FR24_REMOVE_ENTITY, value=removal_number)
            departure = timestamp(leg.get("departure", {}).get("utc_timestamp"))
            eligible = bool(legs and departure - 4 * 3600 <= now <= departure + 6 * 3600
                            and not any(terminal(row) or row.get("finished_at") or row.get("evidence", {}).get("touchdown")
                                        or row.get("evidence", {}).get("actual_arrival") for row in legs))
            already_listed = any(number(leg.get("flight_number")) in flight_numbers(f) for f in flights)
            if self.options.get(CONF_FR24_AUTO_TRACK) and healthy and fetching and eligible and not already_listed and number(leg["flight_number"]) not in requested and now - record.get("add_attempt_at", 0) >= RETRY_SECONDS:
                record.update(pending_add=True, baseline=[identity(f) for f in flights], add_attempt_at=now)
                await self._manager.async_update_lifecycle(state, {})
                raw, variant = leg["flight_number"], number(leg["flight_number"])
                value = variant if record.get("try_variant") and variant != raw else raw
                record["try_variant"] = not record.get("try_variant", False)
                requested.add(number(raw))
                await self._call("text", "set_value", CONF_FR24_ADD_TO_TRACK_ENTITY, value=value)
            if not legs and not record.get("owned") and not record.get("pending_add"):
                records.pop(key, None)
        owned_ids = {r.get("identity") for r in records.values() if r.get("owned") and r.get("source_entity") == self.options.get(CONF_TRACKED_FLIGHTS_ENTITY)}
        unrelated = any(identity(f) not in owned_ids for f in flights)
        self.view.update(fetching=fetching, cleanup_pending=cleanup_pending, session_owned=self._session_owned)
        if self.options.get(CONF_FR24_DISABLE) and self._session_owned and fetching and not required and responsive and not cleanup_pending and not unrelated:
            self._switch_command = True
            try:
                await self._call("switch", "turn_off", CONF_FR24_SWITCH)
                switch = self._state(CONF_FR24_SWITCH)
                if switch and switch.state == "off":
                    self._session_owned = False
                    self.view.update(fetching=False, session_owned=False)
            finally:
                self._switch_command = False
        await self._manager.async_update_lifecycle(state, {})
        self._hass.bus.async_fire(EVENT_LIFECYCLE)
        boundaries = starts + stops
        for record in records.values():
            departure = timestamp(record["leg"].get("departure", {}).get("utc_timestamp"))
            touchdown = timestamp(record.get("evidence", {}).get("touchdown")) or timestamp(record.get("evidence", {}).get("actual_arrival"))
            boundaries.extend([departure - 4 * 3600, departure + 6 * 3600 + 1, expires_at(record["leg"])])
            if touchdown:
                boundaries.append(touchdown + self.options.get("cleanup_after_hours", 2) * 3600)
        next_check = min([now + RETRY_SECONDS] + [t for t in boundaries if t > now])
        if self._cancel_timer:
            self._cancel_timer()
        if not self._stopped:
            self._cancel_timer = async_track_point_in_utc_time(self._hass, self._timer_fired, datetime.fromtimestamp(next_check, timezone.utc))

    @callback
    def _timer_fired(self, now):
        self.handle_itinerary_updated(None)

    @property
    def connection_enabled(self):
        """Existing installations retain their connection until explicitly disabled."""
        return self.options.get(CONF_FR24_CONNECTION, True)

    @callback
    def set_connection_enabled(self, enabled):
        """Close the service/event gate immediately, before an options reload."""
        self.options[CONF_FR24_CONNECTION] = enabled
        if not enabled:
            self._session_owned = False
            self._events.clear()
            if self._cancel_timer:
                self._cancel_timer()
                self._cancel_timer = None

    async def _sync_schedule_only(self, now):
        """Publish schedule timing without observing or changing FR24 state."""
        self.set_connection_enabled(False)
        state = self._manager.lifecycle_snapshot()
        for record in state.get("records", {}).values():
            # An unconfirmed addition cannot be attributed across a disconnected gap.
            record["pending_add"] = False
        groups = journeys(self._manager.snapshot(), now, self.options)
        for group in groups:
            group.update(tracking_required=False, api_start_at=None, api_stop_at=None)
        self.view = {"connection_enabled": False, "journeys": groups,
                     "tracking_required": False, "api_start_at": None, "api_stop_at": None,
                     "fetching": False, "auto_track": False, "source_available": False,
                     "paused_journeys": sorted(self._paused), "last_error": None,
                     "cleanup_pending": any(r.get("owned") or r.get("pending_remove")
                                            for r in state.get("records", {}).values()),
                     "session_owned": False}
        await self._manager.async_update_lifecycle(state, {})
        self._hass.bus.async_fire(EVENT_LIFECYCLE)
        if not self._stopped:
            self._cancel_timer = async_track_point_in_utc_time(
                self._hass, self._timer_fired, datetime.fromtimestamp(now + RETRY_SECONDS, timezone.utc))
