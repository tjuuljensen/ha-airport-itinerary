# Changelog

## 0.3.10 - 2026-10-31

Includes dashboard card version 1.6.10.

- Distinguish landing, observed taxiing and final gate arrival. Read FR24's
  `has_landed` and `gate_arrived_sent` flags and retain transition evidence across
  restarts and provider cleanup. `time_real_arrival` alone does not confirm a gate.
- Keep landing colours active while awaiting gate confirmation, then retain the
  arrival colour until the configured finish delay. Start automatic collapse
  from gate confirmation and preserve final arrival during automatic selection.
- Expose `arrival_phase`, `arrival_pending` and `final_arrival_at` for consumers.
  Update the reusable badge examples to show these transitions and retain final
  arrival until their configured display window ends.

## 0.3.9 - 2026-10-31

Includes dashboard card version 1.6.9.

- Keep scheduled and estimated arrival times in normal text colour until landing
  or arrival is confirmed. Custom status, progress and finished colours respect
  the same rule. An overdue schedule, pre-departure ground position or manual
  completion does not colour arrival; retained arrival evidence survives cleanup.

## 0.3.8 - 2026-10-31

First consolidated AaFI release, including dashboard card version 1.6.8.
Requires Home Assistant 2026.2.3 or later.

### Integration and tracking

- Keep schedules offline with airport-local dates, IANA timezones and independent
  departure/arrival choices for repeated daylight-saving times.
- Connect or disconnect FR24 with one switch while retaining entity selections
  and control preferences.
- Reconcile tracking requests persistently, match dated occurrences and confirm
  additions/removals through FR24's tracked sensor. Automatic additions, owned
  cleanup, API enablement and guarded shutdown are individually opt-in.
- Group connected legs into journeys and expose tracking demand and API timing.
  Preserve completion evidence, pending cleanup and itinerary history.
- Support manual completion and deduplicated lifecycle events for user automations.
- Refresh airport data on demand into validated HA-managed storage, with a bundled
  fallback. Existing saved timestamps and timezones remain unchanged.

### Bundled dashboard cards

- Install and register both cards with AaFI; no separate Dashboard repository is
  required. Migrate recognized standalone resource URLs for UI-managed resources.
- Keep flight drafts while folding, editing names, receiving updates or correcting
  errors. Improve narrow layouts and native date/time field alignment.
- Suggest arrival dates and prepare an unsaved reversed return-trip draft after
  saving a single outbound flight.
- Select the active itinerary or nearest upcoming one by default; sort the dropdown
  by itinerary start time, earliest first, while preserving manual selection.
- Explain tracking state, distinguish live ground/airborne status and tolerate
  small browser/server clock differences to prevent status flicker.
- Apply flight colours only to departure time, arrival time, status and progress.
  Explicit card colours also apply without FR24.
- Hide the FR24 connection and Finish flight controls by default; enable each in
  the card editor when wanted.

### Installation and upgrade

Add `https://github.com/tjuuljensen/ha-airport-itinerary` to HACS as a custom
**Integration** repository and download this release. Restart HA, add the AaFI
integration if needed, and reload the browser. YAML-managed Lovelace resources
still require the module entry documented in the card guide.

For a legacy YAML itinerary package, disable its tracking writers and select one
shutdown owner before enabling AaFI's automatic controls. Badge presentation,
notifications and existing map entities remain in the HA configuration; follow
the [migration checklist](docs/package-migration.md). New installs can begin
with saved schedules and no FR24 connection.

Back up HA configuration, itinerary storage and dashboard resources before an
upgrade. Do not clear stored trips or manually tracked FR24 flights to migrate.
See the [README](README.md#update-and-recovery) for recovery guidance.
