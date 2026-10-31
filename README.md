# Airport-aware Flight Itinerary (AaFI)

Keep your flight plans in Home Assistant, from entering the booking to following
the journey. AaFI stores trips with one or more flight legs and displays departure
and arrival times in each airport's local timezone. Two included dashboard cards
let you enter flights and view your itinerary. Optional Flightradar24 (FR24)
tracking adds live details as they become available.

## What you can use it for

- **Keep a trip together.** Create a named itinerary for a single flight or a
  journey with connections. The dashboard selects an active itinerary or the
  next upcoming one, while keeping past trips available.
- **Avoid converting flight times yourself.** Enter the local dates and times
  shown on your booking. AaFI looks up the airports' timezones, handles different
  dates and daylight-saving offsets, and calculates duration when arrival is
  supplied. For example, enter a Copenhagen departure in Copenhagen time and a
  New York arrival in New York time, regardless of your HA timezone.
- **See the plan even without live data.** Your saved schedule and airport clocks
  remain available when FR24 is disconnected, unavailable or not installed.
- **Follow flights with less manual tracking setup.** With FR24 connected, AaFI
  can request tracking before departure, show available live information and
  clean up flights it owns after completion. Each automatic feature is optional.
- **Use the journey in your own automations.** Sensors expose journey timing and
  tracking demand; lifecycle events can drive notifications. Badge and notification
  examples are provided for adapting an existing HA setup.

### With or without Flightradar24

| | Schedule-only | With FR24 connected |
| --- | --- | --- |
| Enter and retain trips | Yes, stored locally | Yes, the same saved trips |
| Airport-local times and scheduled duration | From your booking and the offline airport dataset | The same, with available estimated/actual times shown alongside the plan |
| Progress | Based on entered departure/arrival times when available | Uses a fresh aircraft position when available; otherwise falls back to the schedule |
| Departure and arrival evidence | A schedule alone cannot confirm either | Uses matching provider evidence; manual or inferred completion is identified separately |
| Tracking and fetching automation | No FR24 connection needed | Optional additions, owned-flight cleanup, fetching enablement and guarded shutdown |

AaFI does not search for flights, import airline bookings, or fetch a timetable
from a flight number. You enter the planned schedule yourself. It does not guess
flight duration from airport distance. FR24 data can be late, incomplete or absent,
so a scheduled arrival time is never proof that the aircraft has landed.

AaFI also does not replace the FR24 integration, create a plane-map entity, or
send notifications by itself. Your HA automations handle notification delivery;
existing badge and map setups can use the [adapter examples](examples/README.md).

## Install with HACS

Use AaFI as a **custom Integration repository** in an existing
[HACS installation](https://hacs.dev/docs/use/). This installs the integration
and both cards together.

1. In HACS, open the top-right menu and choose **Custom repositories**.
2. Enter `https://github.com/tjuuljensen/ha-airport-itinerary`, select
   **Integration** as the type, and add it.
3. Find **Airport-aware Flight Itinerary** in HACS, open it and download it.
4. Restart Home Assistant.
5. Open **Settings > Devices & services > Add integration**, search for
   **Airport-aware Flight Itinerary**, and complete setup. No AaFI account or
   integration YAML block is required.
6. Reload your browser, then add the included cards to your dashboard as below.

These steps follow HACS's [custom repository procedure](https://hacs.dev/docs/faq/custom_repositories/).
There is no separate Dashboard repository or card download to install.

Select release **0.3.7** or later for the consolidated integration and cards.
AaFI is installed through HACS's custom repository feature; inclusion in the
default HACS catalogue is separate. See [release notes](CHANGELOG.md) for changes.

### Manual installation

Copy the complete `custom_components/airport_aware_itinerary` directory from
AaFI into `/config/custom_components/airport_aware_itinerary`. Include its `www`
directory, which contains the cards. Restart HA and complete steps 5 and 6 above.

Home Assistant **2026.2.3 or later** is required. HA must provide IANA timezone
data to Python's `zoneinfo`, as normal HA OS and supported Core installations do.

## The cards install automatically

When AaFI loads, it serves and registers both cards automatically with HA's
default, UI-managed Lovelace resources. Card updates arrive with integration
updates. You do not need to copy JavaScript files or add a resource URL manually.

You choose where the cards appear: open your dashboard's **Edit dashboard > Add
card** picker and select **Airport Itinerary Input** and **Airport Itinerary
Reservations**. AaFI does not insert cards into existing dashboards for you.
Reload the browser if the new card types have not appeared yet.

For YAML card configuration, the same cards are:

```yaml
type: custom:airport-itinerary-input
title: Add a flight
initial_fold: true
```

```yaml
type: custom:airport-itinerary-schedule
title: Itinerary
```

The cards discover the itinerary sensor. Set `entity` explicitly if needed,
using the ID registered in your installation. `initial_fold: true` starts the
input card collapsed for a compact dashboard; expand it when you want to add a
flight. The itinerary dropdown is sorted by trip start time, newest first.

If you explicitly manage **Lovelace resources in YAML**, add the module entry
shown in the [card guide](docs/dashboard-cards.md#install-with-aafi); AaFI cannot
edit that YAML for you. Merely using YAML to configure a card does not require
this exception. Known old standalone resource URLs are migrated automatically
in UI-managed resources; keep only one AaFI card module.

## Your first itinerary

1. Open **Airport Itinerary Input**, create a named trip, and select it.
2. Enter the flight number, origin airport's three-letter IATA code, and the
   departure date/time at that airport. Add a destination and its local arrival
   date/time if you have them.
3. Save the flight. Add further legs to the same itinerary for connections, or
   use **Add + prepare return** on the first leg to draft a separate return trip.
4. View the trip in **Airport Itinerary Reservations**. The card chooses the
   active trip, or the nearest upcoming one; you can select another from the
   dropdown at any time.

The arrival date is suggested from departure until you edit it; check it against
the booking, especially for overnight flights and different timezones. Arrival
time is never guessed. For an ambiguous autumn clock time, choose its earlier
or later occurrence using the separate departure/arrival selectors. See the
[DST explanation](docs/configuration.md#repeated-daylight-saving-times).

No FR24 setup is needed for this workflow. Airport data is bundled and available
offline. **Refresh airport data** is an optional online action that updates the
airport lookup, not your saved schedules or flight status.

## Configure live tracking

Install and configure the separate
[Flightradar24 integration](https://github.com/AlexandrErohin/home-assistant-flightradar24)
first. In AaFI's options, enable **FR24 connection** and select FR24's
**Additional Tracked** sensor. This lets AaFI display matching flight details
without enabling automatic controls.

To automate tracking, select the FR24 **Add to track** and **Remove from track**
entities and its API-fetching switch as needed. All selected entities must belong
to the same FR24 configuration entry. Enable only the features you want:

- **Automatic additions:** request flights during their tracking window and retry
  while waiting for FR24 details.
- **Automatic cleanup:** remove owned flights after completion; leave unrelated,
  manually tracked flights alone.
- **Automatic API enablement:** start fetching before a journey.
- **Guarded shutdown:** stop fetching only for sessions AaFI started and when no
  itinerary, pending cleanup or unrelated tracked flight requires it to stay on.

Automatic additions, cleanup, API enablement and guarded shutdown are independently
opt-in. Use **FR24 connection** to switch AaFI between live and schedule-only mode
while retaining all entity selections and preferences. Turning it off does not
turn off FR24 itself or remove its tracked flights.

The schedule card can show a **Live tracking / Schedule only** control if you
enable **Show FR24 connection control** in its editor. The **Finish flight**
checkmark is also optional and hidden by default; enable **Show Finish flight
control** when manual completion is useful. Manual completion does not invent a
landing time. See the [card guide](docs/dashboard-cards.md) for these settings,
colours and folding, and the [tracking guide](docs/tracking.md) for timing defaults
and shutdown safeguards.

For an existing YAML itinerary package, follow the
[migration checklist](docs/package-migration.md) before enabling automatic controls.
Keep exactly one tracking/shutdown owner. Badge presentation, notifications and
existing map entities remain in your Home Assistant configuration.

## Documentation

| Topic | Guide |
| --- | --- |
| Actions, entities, FR24 connection, airport refresh and daylight-saving times | [Configuration and usage](docs/configuration.md) |
| Card installation, options, colour rules and mobile forms | [Dashboard cards](docs/dashboard-cards.md) |
| Tracking windows, ownership, journeys, lifecycle events and storage | [Tracking reference](docs/tracking.md) |
| Legacy package handoff, badge adapter and rollback | [Package migration](docs/package-migration.md) |
| Reusable badge/notification examples and their dependencies | [Examples](examples/README.md) |
| Tests, Windows/Linux workflows, airport-data maintenance and releases | [Contributing](CONTRIBUTING.md) |
| Source, deployment and legacy repository boundaries | [Repository ownership](docs/architecture/repository-ownership.md) |

## Update and recovery

Back up HA configuration and itinerary storage before an upgrade. Update through
HACS, or replace the complete integration directory for a manual installation,
then restart Core and reload the dashboard. The cards update with the integration;
no separate card update is needed. Existing trip IDs and schedules are retained.

If an update fails, disable AaFI's automatic controls, restore the previous
complete integration and its matching resource URL, and restart. A downgrade to
code predating the lifecycle ledger may require the corresponding storage backup.
See [storage compatibility](docs/tracking.md#storage-compatibility). Do not
hand-edit HA storage while Core is running.

Removing the integration entry does not delete saved trips. Use its explicit
clear/delete actions when you intend to remove history. See the configuration
guide for manual completion and recovery of the bundled airport dataset.

## License

Integration and bundled card source are [MIT licensed](LICENSE). Bundled airport
data comes from `mwgg/Airports`; [NOTICE.md](NOTICE.md) records provenance and
third-party licences.
