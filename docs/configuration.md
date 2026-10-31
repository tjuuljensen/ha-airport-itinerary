# Configuration and usage

Configure AaFI through **Settings > Devices & services**. No integration YAML
block is required. The entity IDs below are defaults; check the registered IDs
in your installation. Start with saved schedules, then enable optional FR24
controls individually.

## Actions and data

The integration provides response-bearing actions in the
`airport_aware_itinerary` domain:

- `resolve_departure`: resolve an origin IATA code, service date (`YYYY-MM-DD`),
  and local departure time (`HH:MM`) to an offset-aware ISO timestamp.
- `create_itinerary`: create a named locally stored trip. The response returns
  its `itinerary.id`.
- `add_flight`: append a flight leg to that trip. Departure is required;
  destination is optional. If either arrival date or time is supplied, both
  are required, together with the destination airport. If arrival is supplied, the stored leg also includes
  `flight_time_seconds`, calculated from the two resolved UTC instants. This
  gives the scheduled flight duration across airport timezones and DST changes.
- `remove_flight`, `clear_itinerary`, and `delete_itinerary`: maintain trips.
- `rename_itinerary`: update a trip name while preserving its identifier and flights.

Expected validation errors are returned as `success: false` with a readable
`error`. Call actions from a script with `response_variable`, for example:

```yaml
sequence:
  - action: airport_aware_itinerary.resolve_departure
    data:
      origin_airport: DEN
      service_date: "2026-10-22"
      departure_time: "20:25"
    response_variable: departure
  - if:
      - condition: template
        value_template: "{{ departure.success }}"
    then:
      - action: persistent_notification.create
        data:
          title: Departure resolved
          message: "{{ departure.timestamp }} ({{ departure.timezone }})"
    else:
      - action: persistent_notification.create
        data:
          title: Departure needs attention
          message: "{{ departure.error }}"
```

`sensor.flight_itineraries` exposes stored trips and
legs as attributes. The entity registry may adjust the object ID if that name
is already in use; use the registered entity ID after setup. AaFI includes
the itinerary input and reservation-style schedule cards. They install and
update with the integration; no separate Dashboard repository is required. Each reservation shows its own scheduled flight duration when
an expected destination-local arrival was entered; total journey duration is
calculated from the first departure to the final arrival.

## Switch between live tracking and schedule-only mode

Use **FR24 connection** in AaFI's configuration entities. The itinerary card
can optionally show a **Live tracking / Schedule only** control: enable
**Show FR24 connection control** in its visual editor, or set
`show_fr24_connection_control: true`. It is hidden by default; hiding it does
not change the integration's connection mode. The same master toggle appears in
integration options as **Enable FR24 connection**. Its entity is normally
`switch.airport_itinerary_fr24_connection` (HA may append a suffix).

Off stops FR24 reads, events, submissions, cleanup and API switching. All four
entity selections, individual automatic-control preferences and timing settings
are retained. Saved trips, schedules and confirmed history remain available.
The badge adapter uses schedule timing while off; it receives no new AaFI live
position for the map. Independent FR24 map consumers may continue updating.
The tracking-required sensor is off and API start/stop sensors have no deadline.

Disconnecting does not turn off FR24's own fetching switch or remove its tracked
flights. Confirmed ownership and pending cleanup are kept for reconnection;
unconfirmed additions are not adopted across the disconnected interval. AaFI
relinquishes API-session ownership, so reconnecting does not claim an already-on
FR24 session. Reconnect resumes the saved control preferences after checking the
entity selections still belong to one FR24 integration entry. Existing installs
keep their current live connection on upgrade.

## Dashboard and optional FR24 tracking

With storage-managed Lovelace resources, AaFI registers its bundled module and
updates recognized old standalone resource URLs in place. Dashboard card types
and configurations stay the same. Reload the browser after an integration update.
For YAML-managed resources, follow [the card guide](dashboard-cards.md).

To connect optional live data, open the integration's options and select the
Flightradar24 Additional Tracked sensor. The adapter reads its `flights`
attribute and matches a leg using flight number/callsign, compatible origin and
destination codes, and the nearest scheduled departure within 12 hours. A
scheduled FR24 record is kept distinct from an actively tracked flight. Without
that sensor, itinerary storage and time resolution continue to work. The
itinerary sensor reports whether tracking is not configured, unavailable,
unsupported, unmatched, scheduled, or live.

The options independently enable automatic additions, owned-flight cleanup,
pre-departure API fetching, and guarded shutdown. All are opt-in. Select FR24
entities from the same integration entry. Additions run from four hours before
departure until six hours afterward, with 15-minute retries. A completed service
call is not confirmation: the tracked sensor must show the matching occurrence.
Pre-existing tracked flights are never adopted or removed.

Cleanup removes an owned flight at gate arrival or, by default, two hours after
touchdown. Actual arrival is the fallback when touchdown was not observed.
Deleting an itinerary retains pending tracking cleanup. FR24's global cleanup
setting stays under FR24's control.

Connected journeys use a maximum connection of 24 hours by default. API fetching
can start 60 minutes before a journey and continue until two hours after its final
touchdown; both windows are configurable. Optional shutdown affects only sessions
started by this integration and waits for every itinerary and pending cleanup.
Unrelated tracked flights and unavailable/stale source data prevent shutdown.
A manual switch-off pauses automatic enablement for the active journey.
Restart/reload relinquishes shutdown ownership because session continuity cannot
be established; a pre-existing on switch is left alone.

Use **mark_flight_completed** with `itinerary_id` and `leg_id` for manual repair.
The card checkmark is hidden by default; enable **Show Finish flight control**
in the visual editor or set `show_finish_flight_control: true` to show it.
It does not invent an actual landing time. Itinerary history is retained until
you explicitly clear or delete it. Notifications can consume
`airport_aware_itinerary_flight_event`; delivery stays in your automations.
See [tracking behavior and automation interfaces](tracking.md).

The integration exposes `binary_sensor.airport_itinerary_tracking_required`,
`sensor.airport_itinerary_api_start_at`, and `sensor.airport_itinerary_api_stop_at`,
plus `journeys` and `tracking` attributes on the itinerary sensor. Entity IDs
may receive a suffix if already occupied.

Migrating the original YAML package requires a coordinated handoff. Follow the
[package migration checklist](package-migration.md) before enabling controls.
Do not run both sets of FR24 writers at once.

Aircraft-local time is optional enrichment: resolving a tracked position to an
IANA timezone requires the `timezonefinder` Python package to be available.
That package is deliberately not an integration requirement, so its installation
cannot block Home Assistant setup. If unavailable, FR24 details still work and
the dashboard reports the aircraft timezone as unavailable.

## Time and data behavior

- The bundled maps are generated from `mwgg/Airports` at commit
  `a89e4e0dda9d9878337e2da190ebe1ef1d6af705`: 7,918 IATA-to-timezone mappings,
  7,744 IATA-to-city mappings, and 7,918 offline IATA-to-coordinate mappings. The sensor adds
  city names and coordinates to itinerary legs at read time, including existing
  saved itineraries. The dashboard uses these coordinates with a recent FR24
  position to estimate progress along the great-circle route.
  Provenance and the upstream MIT notice are in [NOTICE.md](../NOTICE.md).
- `2026-10-22 20:25` at DEN resolves to
  `2026-10-22T20:25:00-06:00`.
- Unknown airport codes, unavailable zone data, invalid dates/times, and
  daylight-saving gaps return visible validation errors. Repeated fall-back
  times require an explicit `fold` choice of `earlier` or `later`; pass
  `fold: earlier` or `fold: later` to `resolve_departure` when needed.
- Stored data survives Home Assistant restarts. Removing the integration entry
  does not delete stored trip data; `delete_itinerary` removes a trip explicitly.

## Repeated daylight-saving times

When clocks move backward, some local times occur twice. At Copenhagen on
25 October 2026, **02:30 earlier** is 00:30 UTC (UTC+02:00), while **02:30 later**
is 01:30 UTC (UTC+01:00). Choose the occurrence matching the airline's schedule.
Automatic is suitable for ordinary times; an ambiguous time is rejected until
you choose. This setting does not change the airport's timezone.

The input card provides separate departure and arrival selectors because the
two airports may change clocks on different dates. Actions use `fold` for
departure and `arrival_fold` for arrival. When clocks move forward, a skipped
time does not exist: neither choice can repair it. Correct the entered schedule.

## Refresh the offline airport map

Use **Refresh airport data** in the integration's configuration entities, or call
`airport_aware_itinerary.refresh_airport_data` with a response variable. This is
an explicit online operation; normal operation and startup remain offline.
It resolves the latest `mwgg/Airports` commit, downloads that exact revision,
validates it, and atomically saves a separate HA-managed cache. Failed downloads,
invalid data, and storage errors leave the active map unchanged.

The itinerary sensor exposes the active `airport_mapping_revision`, mapping
counts, and `airport_data_refresh` status, last success, and last error. Use
**Restore bundled airport data** (or `restore_bundled_airport_data`) to discard
the cache. Neither action changes saved flight timestamps or airport timezones;
new flights use the active map. Updated city names and coordinates enrich the
dashboard immediately.

## Action field reference

All actions use the `airport_aware_itinerary` domain. The complete field selectors
are also available in [services.yaml](../custom_components/airport_aware_itinerary/services.yaml)
and Home Assistant Developer tools > Actions.

| Action | Required inputs | Optional inputs |
| --- | --- | --- |
| `resolve_departure` | `origin_airport`, `service_date`, `departure_time` | `fold` |
| `create_itinerary` | `name` | None |
| `rename_itinerary` | `itinerary_id`, `name` | None |
| `add_flight` | `itinerary_id`, `flight_number`, `origin_airport`, `service_date`, `departure_time` | `label`, `destination_airport`, `arrival_date`, `arrival_time`, `fold`, `arrival_fold` |
| `remove_flight` | `itinerary_id`, `leg_id` | None |
| `clear_itinerary` | `itinerary_id` | None |
| `delete_itinerary` | `itinerary_id` | None |
| `mark_flight_completed` | `itinerary_id`, `leg_id` | None |
| `refresh_airport_data` | None | None |
| `restore_bundled_airport_data` | None | None |

Dates use `YYYY-MM-DD`, times use `HH:MM`, and airport codes use IATA. Optional
`fold` and `arrival_fold` accept `earlier` or `later`; omit them for ordinary
local times. Read returned `success` before using the response.
