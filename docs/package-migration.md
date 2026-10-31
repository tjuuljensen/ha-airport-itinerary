# Flight itinerary package cutover

This is a reusable migration checklist, not a record of any installation's
current state. Record deployment and acceptance in the configuration repository
that owns that Home Assistant instance.

The custom integration owns itinerary storage, FR24 reconciliation, completion,
and API timing. AaFI also bundles the dashboard cards and owns their tests. HomeAssistantConfig
continues to own badge priority, presentation windows, notification delivery,
and the existing plane-map entity. No live configuration is changed by installing
these source files alone.

## Before activation

- [ ] Back up `/config/packages/flight_itinerary.yaml`, its companion Jinja,
  `/config/automations/transit.yaml`, dashboard resource/card configuration, and
  the itinerary integration's storage through a normal HA backup.
- [ ] Record actual entity IDs, the selected FR24 config entry, the four current
  control options, notification destination, and both display-hour values.
- [ ] Before upgrading, turn off the integration's existing automatic-add option.
  Upgrades preserve it; leaving it on would run the new controller alongside
  the still-active legacy package. Keep integration controls off until the
  coordinated handoff below.
- [ ] Compare every legacy flight with the integration's saved itineraries:
  flight number, origin service date, airport-local departure, destination,
  expected arrival, and completion. Transfer missing entries using
  `create_itinerary`, `add_flight`, and manual completion where appropriate.
  Do not silently import compact JSON or overwrite existing trips.
- [ ] Record pre-existing Additional Tracked flights. They remain externally
  owned after cutover. Do not remove/re-add unrelated flights to establish ownership.
- [ ] Search active dashboards, scripts, automations, and templates for legacy
  `flight_itinerary_*` consumers. Repository references do not prove the live
  consumer set; inspect UI-owned dashboards as well.
- [ ] Copy the integration and dashboard through their existing deployment
  workflow, restart Core as required, refresh the dashboard resource cache, and
  verify the new services/entities before enabling any new control options.

## Ownership and entity mapping

| Legacy feature | New owner / handoff |
| --- | --- |
| Reconcile, add/remove retries, retained-flight cleanup | Integration options and persistent ownership ledger |
| `input_number.flight_itinerary_api_before_minutes` | Integration `api_before_minutes`; copy its current value |
| `input_number.flight_itinerary_connection_hours` | Integration `connection_hours`; copy its current value |
| `binary_sensor.flight_itinerary_day_active` | `binary_sensor.airport_itinerary_tracking_required` |
| `sensor.flight_itinerary_api_start_at` / `api_stop_at` | `sensor.airport_itinerary_api_start_at` / `api_stop_at` |
| Display-before/after helpers | Stay in YAML; now control badge visibility directly |
| `sensor.flight_itinerary_display` and `binary_sensor.flight_itinerary_display_active` | Replace definitions with the adapter; retain unique IDs |
| Matching display boolean, priority list, capacity mirror | Stay in YAML with existing identities |
| `sensor.flight_itinerary_plane` | Retain its existing definition; adapter supplies compatible fresh-position attributes |
| Notification helper/destination | Stay in YAML; consume the integration lifecycle event |
| Legacy form, manual completion buttons | New input card and `mark_flight_completed` action |
| Automatic 48-hour clear | Disable; itinerary history is retained |

The adapter's retained plane attributes are a compatibility bridge, not a new
integration map sensor. Keep the existing map entity and its consumers until a
separate map migration. The old `flight_itinerary_enabled` helper becomes a
presentation gate only after its tracking automations are disabled; use the
integration options for tracking control and update its dashboard label accordingly.

## Coordinated activation

1. Disable the legacy automations by their stable IDs: `flight_itinerary_reconcile`,
   `flight_itinerary_cleanup_final_tracking`, `flight_itinerary_clear_completed`,
   `flight_itinerary_tracked_took_off`, `flight_itinerary_tracked_landed`,
   `flight_itinerary_record_final_landing`, `flight_itinerary_add_form_flight`,
   and `flight_itinerary_mark_next_completed`. Disable old form/clear/cleanup
   dashboard actions so no user action invokes their scripts after handoff.
2. Retire the body of `disable_flightradar24_automatically` in
   `/config/automations/transit.yaml` from active configuration. Its old startup
   path can shut down the new controller. Enable integration shutdown only if
   it is the chosen shutdown owner; do not leave the old automation alongside it.
3. Replace only the legacy display sensor template, display-active binary sensor,
   and `flight_itinerary_display_badge_mirror` with
   [the adapter](../examples/flight_itinerary_display_adapter.yaml). Copy its
   [Jinja companion](../examples/flight_itinerary_adapter.jinja) into
   `/config/custom_templates/flight_itinerary_adapter.jinja`. Do not load old and
   new definitions of the same unique IDs simultaneously.
4. Keep existing helpers and values, the shared badge system, and the old plane
   sensor block. Adjust `sensor.flight_itineraries` in the example if HA assigned
   another ID. For a new badge installation, create the two display-number
   helpers with starting values **0.5** and **2** hours and the existing named
   boolean/notification helpers; do not set YAML `initial` on restored helpers.
   The adapter also uses 0.5/2 when the number helpers are absent/unavailable.
5. Update the badge with [the compatible card example](../examples/flight_itinerary_display_badge.yaml),
   which labels schedule-only timing. Retain the existing shared card templates,
   priority-list source, navigation target, and notification destination. The
   notification example uses `/map/flightradar24`; preserve your existing URL
   if the notify platform requires an absolute URL.
6. Configure the selected FR24 sensor, text controls, and switch from one config
   entry. Copy timing preferences; opt into additions, cleanup, and enablement.
   Enable guarded shutdown only after confirming the old transit writer is inactive.
7. Record the deployment versions, date, entity IDs, option values, and evidence
   in HomeAssistantConfig's owning migration ledger. Keep the original package
   and helper cleanup as a later, separately reviewed change.

## Acceptance and rollback

| Scenario | Expected result |
| --- | --- |
| Future flight outside its window | Saved schedule, no early add attempt |
| Window starts with fetching off | Enable only if configured; wait for matching FR24 occurrence |
| Add resolves to nothing | Retry at 15-minute cadence; no permanent submitted flag |
| Unrelated manually tracked flight | Neither removed nor used to justify shutdown |
| Gate arrival / retention deadline | Remove owned record; retain completion in itinerary |
| Restart or source unavailable | Resume tracking/cleanup safely; relinquish uncertain switch ownership |
| Manual switch-off | No automatic re-enable during that journey's active window |
| Change display-hour helpers | Badge window changes independently of FR24 timing |
| Priority slots full | Badge source may remain eligible; visible boolean respects capacity |
| Notification duplicate | One event per saved transition, without direct integration notification calls |
| Airport download fails | Current offline data and saved schedules remain usable |

If acceptance fails, disable all four new control options first. Restore the
backed-up display templates, companion Jinja, transit automation, and dashboard
references as one rollback. Re-enable legacy writers only after confirming the
new controller is read-only. Preserve the integration store; do not clear trips
or Additional Tracked as a rollback shortcut. Inspect ownership and restore the
store backup before downgrading the integration if necessary.

The active HA instance and installed FR24 version still need runtime acceptance.
Static tests cannot verify actual provider responses, live badge priority slots,
notification delivery, or UI-owned dashboard references.

## Initial source verification - 31 October 2026

The following records the original migration implementation, before subsequent
card and integration updates. It is historical evidence, not the current test
count or deployment status. See [contributor guidance](../CONTRIBUTING.md) for
the current validation procedure.

- Backend: 71 tests passed with Python 3.13.18 and Home Assistant 2026.2.3 in a
  disposable Ubuntu filesystem copy, including HA template/automation validation.
- Dashboard: 5 Node tests and 10 Chromium tests passed using Windows-native tools.
  The 320px and 490px screenshots were visually checked; a 390px card was also
  exercised in a mobile-sized viewport.
- Python undefined-name/unused-import checks, JSON/YAML parsing, JavaScript syntax,
  Git whitespace checks, and repository LF checks passed.
- That source-validation run performed no HA deployment, service call, restart,
  notification, or dashboard save. Runtime acceptance belongs to each installation.
