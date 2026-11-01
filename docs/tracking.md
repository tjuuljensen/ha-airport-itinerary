# Tracking and automation interfaces

Airport Itinerary stores the schedule independently of FR24. Losing FR24 does
not delete a trip or turn a scheduled arrival into a confirmed arrival.

## Options

| Option | Default | Behavior |
| --- | --- | --- |
| `fr24_connection_enabled` | On for compatibility | Master read/control gate; off keeps all settings and saved schedules |
| `fr24_auto_track` | Off; existing setting preserved | Submit eligible flight numbers and confirm them through the selected sensor |
| `fr24_auto_cleanup` | Off | Remove only records this integration added and subsequently observed |
| `fr24_auto_enable` | Off | Turn fetching on before journeys |
| `fr24_auto_disable` | Off | Turn off an automatically owned session, including after restart |
| `api_before_minutes` | 60; range 0–240 | Lead time before each journey |
| `api_after_hours` | 2; range 0–48 | Fetching grace after final touchdown, with actual arrival as fallback |
| `cleanup_after_hours` | 2; range 0–48 | Per-flight retention after touchdown; gate arrival ends retention immediately |
| `connection_hours` | 24; range 1–48 | Maximum gap between connected legs |

Configure `tracked_flights_entity`, `fr24_add_to_track_entity`,
`fr24_remove_from_track_entity`, and `fr24_api_switch` as needed. The options
flow rejects entities belonging to different FR24 configuration entries.
Use the master connection toggle for a reversible disconnection.
Clear an optional entity field to remove it. Leave FR24's global cleanup
option under FR24's own settings; if it removes a record earlier, the itinerary
retains evidence already observed but cannot recover evidence never received.

## Occurrences, ownership, and retries

Matching requires a flight number/callsign, compatible airport codes, and a
scheduled departure within 12 hours of the saved departure. When the saved
origin timezone and service date are available, the FR24 departure must fall
on that origin-local date. Leading zeros are normalized; ties are ambiguous.

Automatic additions run from departure minus four hours through departure plus
six hours. Requests alternate the entered and zero-stripped number where these
differ. Retry attempts are separated by 15 minutes. A flight already listed by
number is not submitted again, even if it is the wrong occurrence; the dashboard
reports that no suitable match was found.

Ownership is recorded after a requested occurrence appears in the sensor.
Existing records are external. FR24's public controls provide no transaction ID,
so a simultaneous manual addition of the identical occurrence cannot be
distinguished from the integration's request. Avoid manually adding the same
flight while an automatic attempt is pending. Removal requires a matching saved
provider identity and an unambiguous flight number; there is no clear-all call.
When FR24 replaces a scheduled ID with a live ID, ownership follows only a
unique matching scheduled occurrence with compatible aircraft registration.

Identical occurrences shared by itineraries share tracking. Removing one
reference does not remove a record another itinerary still needs. Pending
cleanup survives removal of the final reference and restarts. A deleted leg
with an unconfirmed addition keeps a short reconciliation grace before the
request is discarded. Cleanup retries when FR24 is available and fetching again;
it does not override a manual fetching pause just to remove a record.

Disappearance is not arrival. Aircraft continuation is inferred only after an
observed airborne flight changes to a different live flight on the same
registration, departing from the saved destination. Inferred completion is
labelled separately and does not create a landing timestamp. A continuation
record is removed only if the previously owned provider ID also remains the same.

## Journeys and shutdown

Legs are grouped chronologically per itinerary. Disconnected airports and gaps
above the maximum connection split journeys. If the previous arrival is absent,
its departure is the connection-gap reference. A missing final completion uses
midnight after the origin service date's following day as the expiry fallback;
fresh airborne evidence keeps tracking required. Expiry is never recorded as
confirmed completion.

`binary_sensor.airport_itinerary_tracking_required` expresses aggregate demand
even when automatic switching is disabled. The next API start and active API
stop timestamp sensors can be used in native time triggers. A null deadline
means there is no known deadline, not permission to shut down.

Shutdown waits until no journey requires fetching, no cleanup/request grace is
pending, the source is available, and every additional tracked record is owned.
An unchanged empty flight list permits idle shutdown even if its last update is
old. Nonempty lists still require a responsive source; flight evidence and
removal keep their freshness requirements. Unavailable or malformed sources
block shutdown.

Fetching ownership is persisted before automatic turn-on and retained through
restart/reload and temporary switch unavailability. Startup immediately checks
saved journey deadlines, and source/switch recovery triggers another check.
Control is bound to the configured switch and flight sensor; changing either or
disconnecting FR24 relinquishes it. Unknown/pre-existing sessions, including
sessions from versions before 0.3.14 without saved control, remain external and
are not adopted. Turn such a session off once to return to automatic scheduling.

Manual switch-off pauses active journeys until their active windows end. Manual
off-to-on clears those pauses and sets a persisted keep-on override; turn it off
to clear that override. A saved automatic session found off at startup is treated
as a pause. Changes made entirely while HA is offline cannot be distinguished
when the switch returns in the same state; the last saved control applies.

The tracking.fetching_reason attribute explains the current decision:
active_journey, arrival_grace_period, manual_keep_on, manual_pause,
external_session, unrelated_tracked_flights, cleanup_pending,
source_unavailable, source_stale, switch_unavailable,
automatic_shutdown_disabled, shutdown_pending (service not yet confirmed),
off, or disconnected. The tracking.manual_keep_on attribute exposes the
persisted manual override.

## Sensor data and events

Arrival progresses independently of scheduled timing:

- **Landed**: touchdown timestamps, `time_real_arrival`, the landing event or a
  fresh `has_landed: true` observation establish landing, not final arrival.
- **Taxiing**: a landed flight has fresh live ground data with positive speed.
  Without fresh movement evidence the display remains landed, awaiting gate.
- **At gate / final arrival**: a gate timestamp, the FR24 gate event or a fresh
  `gate_arrived_sent: true` observation establishes final arrival. This reflects
  the provider's gate detection, not independent airport confirmation.

Flags without timestamps use their first observation time. Gate observation
does not reuse an earlier `time_real_arrival` as its timestamp. Gate and landing
events remain deduplicated across restart; loss of a record creates neither.
Existing cleanup/API grace timers still bound tracking when no gate evidence
arrives. Timer expiry does not turn landing into confirmed final arrival.

Existing itinerary and tracked-leg attributes remain available. Additions:

- `journeys`: deterministic IDs, itinerary/leg IDs, departure/arrival/touchdown,
  expiry and API boundaries, `tracking_required`, status, and completion source.
- `tracking`: aggregate demand, fetching state, source availability, paused
  journeys, cleanup pending, session ownership, and last service error.
- Leg `evidence`: departure, touchdown, gate arrival, actual arrival, inferred
  completion, or manual completion timestamps as observed. Existing
  `finished_at` remains reserved for confirmed evidence and may be a landing
  timestamp for compatibility; it does not by itself prove gate arrival.
- Leg `arrival_phase`: `landed`, `taxiing`, `at_gate`, `completed` (manual/inferred),
  or null before arrival evidence. `final_arrival_at` is the gate timestamp only.
- Journey `arrival_pending` identifies landed legs awaiting final arrival;
  `completed` now requires gate, manual or inferred completion for every leg.
  Journey `final_arrival_at` is the final leg's gate timestamp.

`airport_aware_itinerary_flight_event` provides `event`, `itinerary_id`,
`itinerary_name`, `leg_id`, `flight_number`, `occurrence`, `event_time`, and
`evidence_source`. Events are `departure`, `touchdown`, `gate_arrival`,
`inferred_completion`, or `manual_completion`; sources are `fr24`, `inferred`,
or `manual`. Transition receipts are persisted before emission so duplicate
observations/restarts do not resend notifications. A crash between persistence
and event emission can lose that notification; this is not a durable message queue.

Use `mark_flight_completed` for manual repair. It takes `itinerary_id` and
`leg_id`, returns the updated itinerary, and queues cleanup without claiming an
actual arrival. There is no automatic trip-history deletion.

## Storage compatibility

The existing HA store remains at storage version 1. Its payload migrates
additively to `schema_version: 2`, retaining itinerary/leg IDs and schedules and
adding the lifecycle ledger. Position updates are not written into the ledger;
only bounded matching identity and transition evidence are retained. Airport
refresh uses a separate `airport_aware_itinerary.airports` store.

Back up the itinerary store before rolling back to a pre-lifecycle version:
older code may discard the ledger on its next save. Never hand-edit HA storage
while Core is running.
