# Airport Itinerary Dashboard

Two bundled Home Assistant dashboard cards for the
[Airport-aware Flight Itinerary integration](https://github.com/tjuuljensen/ha-airport-itinerary):

- **Itinerary input** creates named itineraries and adds scheduled flights using
  airport-local dates and times.
- **Itinerary reservations** presents each leg in a booking-style card with
  local airport clocks, schedule status, journey timing, and optional live
  Flightradar24 details.

Without live tracking, the schedule card's progress bar uses the entered
departure and arrival times and does not claim that a flight departed or
arrived on time. A fresh FR24 scheduled match can supply updated estimated
departure and arrival times before the aircraft is live. Once a live match has
a recent position, the card uses it to estimate progress along the great-circle
route. Missing or stale FR24 data falls back to the saved schedule, with a
message explaining the tracking state. The card accepts HA update timestamps up
to one minute ahead of the browser clock to prevent status flicker from clock
skew; data older than five minutes remains stale. Journey totals and airport clocks are
calculated locally from saved airport timezones.

The schedule card works without a live-flight provider. Flight labels are
optional: when omitted, the card derives a route label from the airport codes,
or uses the flight number if no destination was entered.

## Install with AaFI

AaFI 0.3.10 bundles card version 1.6.10. Follow the
[HACS or manual installation steps](../README.md#install-with-hacs), restart HA
and add the AaFI integration, then reload the browser. Both cards are installed
and registered automatically with UI-managed Lovelace resources; no separate
card download or manual resource entry is needed.

To place them on a dashboard, use **Edit dashboard > Add card** and choose
**Airport Itinerary Input** or **Airport Itinerary Reservations**. AaFI makes
the cards available but leaves dashboard placement to you. Known standalone
resource URLs are migrated without changing existing card configurations. Keep
only one Airport Itinerary module in Resources.

For explicitly YAML-managed **resources**, add or replace the card resource with
the following entry. This exception does not apply merely because a card's own
configuration is written in YAML:

```yaml
lovelace:
  resource_mode: yaml
  resources:
    - url: /airport_aware_itinerary/airport-itinerary.js?v=1.6.10
      type: module
```

Merge this entry into your existing resources; retain other cards. When removing
AaFI or downgrading to a version without bundled cards, restore the previous card
resource URL from your backup. Do not load old unguarded standalone versions
alongside the bundled module.

The schedule card can optionally expose **FR24 connection** as a Live tracking /
Schedule only switch. It is hidden by default. Enable **Show FR24 connection
control** in the card's visual editor, or add `show_fr24_connection_control: true`
to that card's YAML. Setting it to false or omitting it hides the control without
changing the connection mode. This changes AaFI's connection, not FR24's own fetching switch. Your
saved entity/control settings and entered flight drafts are retained.

The cards use **sensor.flight_itineraries** by default and can also discover
the integration sensor by its `itineraries` attribute if Home Assistant assigned
it a different entity ID. You can still pass the sensor's entity ID explicitly
as the card's **entity**.

Both cards provide a Home Assistant visual editor. The input editor sets the
itinerary sensor, title, and input-card folding options. The schedule editor
also exposes itinerary selection, colors, finish timing, status color overrides,
and airport display name overrides. Color fields accept CSS colors and Home
Assistant theme variables such as `var(--info-color)`. Existing YAML-only keys
are preserved when editing a card visually.

## Itinerary input card

~~~yaml
type: custom:airport-itinerary-input
entity: sensor.flight_itineraries
title: Add a flight
~~~

The itinerary selector stays at the top of the card, with icon buttons to create
an itinerary or rename the selected one. The header chevron folds the whole
card into a compact view. The input card also folds its flight fields while no
itinerary is selected; this is on by default and can be changed in the visual
editor or with `fold_empty_itineraries`. Set `initial_fold: true` to start with
the whole card collapsed.

The example placeholders are `E.g. Copenhagen - San Francisco, Oslo - Rome, ...`
for itinerary names and `SK935, DY1870, ...` for flight numbers. The example
route label and destination placeholder use CPH-SFO.

The form requires a trip name when creating a trip, and a flight number,
origin airport, airport service date, and local departure time when adding a
flight. Destination airport and its expected local arrival date/time are
optional. A label is optional and defaults to a route such as **CPH-SFO**.
If you type a route in that exact form into the label field, the card fills the
origin and destination airport fields as soon as both codes are present.

The arrival date initially follows the departure date. Editing or clearing it
stops that suggestion; arrival time stays blank. An untouched suggested date is
not sent until an arrival time is supplied. No flight duration is guessed from
the airport pair. Fields stack below a card width of 420px; wider cards align
date and time controls even when labels wrap. Drafts survive folding, sensor
updates, name editing, and validation errors.

For the first flight in an empty itinerary, **Add + prepare return** saves the
outbound and prepares a separate unsaved return draft. Both airports are required.
Airports and the route label are reversed; the suggested date is the outbound
arrival date, or its departure date when arrival is absent. Enter the return's
number and times, and explicitly create its itinerary. Cancelling the name form
discards the draft without creating an empty trip. This shortcut does not reverse
multi-leg itineraries.

Repeated autumn clock times need an explicit earlier/later choice. For example,
at CPH on 25 October 2026, 02:30 occurs at both 00:30 UTC (earlier, UTC+02:00) and
01:30 UTC (later, UTC+01:00). Use the occurrence on your airline's schedule.
Departure and arrival have independent selectors; Automatic is appropriate when
the local time occurs once. During spring's forward clock change, skipped times
do not exist and must be corrected rather than assigned an occurrence.
Daylight-saving gaps, unknown airports, and invalid schedules appear inline;
failed entries are not saved.

The date and time controls use native browser inputs. Their picker display can
follow the browser or operating-system locale rather than Home Assistant's
profile settings, while the values sent to the integration remain normalized
as `YYYY-MM-DD` and `HH:MM`. The card passes Home Assistant's language to the
controls where the browser honors it, and uses the Home Assistant locale for
schedule clock formatting.

## Itinerary reservations card

~~~yaml
type: custom:airport-itinerary-schedule
entity: sensor.flight_itineraries
title: Itinerary
~~~

When more than one itinerary exists, the card includes a trip selector. A
specific itinerary can be pinned with its ID:

~~~yaml
type: custom:airport-itinerary-schedule
entity: sensor.flight_itineraries
itinerary_id: 0123456789abcdef0123456789abcdef
~~~

Use **Edit name** to rename the selected itinerary. **Remove itinerary** asks
for confirmation before deleting that itinerary and all of its flights.
The **Finish flight** checkmark is hidden by default. Enable **Show Finish flight
control** in the visual editor, or set `show_finish_flight_control: true` on the
schedule card. When the integration exposes `mark_flight_completed`, this action
asks you to confirm manual completion of a leg. It stops automatic additions and queues
owned tracking cleanup, without claiming a confirmed landing. Manual and inferred
completion are labelled separately.

Itinerary dropdowns show the earliest first departure first, with undated trips last.
The schedule card automatically selects an active journey first, otherwise the
nearest upcoming journey. If all journeys are finished or undated, it falls back
to the first listed itinerary. An explicit dropdown selection stays selected
until the card is reloaded or that itinerary is removed. A configured
`itinerary_id` always takes precedence. Dropdown ordering remains earliest first.

A number-only scheduled watch displays **Added to FR24—waiting for flight details**.
This acknowledges the FR24 watch without treating it as a confirmed dated match.
A fresh live FR24 record with `on_ground: true` displays **On ground**; it does
not imply boarding, taxiing or takeoff. **Airborne** requires a fresh off-ground
report. Observed arrival/completion takes precedence. Fresh ongoing ground or
airborne tracking prevents a delayed flight being labelled finished merely
because its scheduled arrival passed.

Tracking notices distinguish a future tracking window, fetching switched off,
waiting for FR24, an unavailable source, and an unmatched occurrence. An empty
tracked sensor before the window opens is normal; the saved schedule stays usable.

Use the chevron in the card header to collapse or expand the entire itinerary.
Each flight also has its own chevron. To fold each finished flight
independently, set `auto_collapse_after_minutes` to a positive number. The
flight folds after its finish delay and the configured number of additional
minutes. This lets a finished leg tuck away while a later or airborne leg stays
visible. The option is disabled by default. A flight can be expanded or folded
manually at any time. Add the option to a full schedule-card configuration like
this:

~~~yaml
type: custom:airport-itinerary-schedule
entity: sensor.flight_itineraries
auto_collapse_after_minutes: 10
~~~


Total journey time, elapsed time, and remaining time are in the folded
**Itinerary details** section. They are calculated from the scheduled first
departure and final expected arrival. These values do not require FR24, but a
final expected arrival must be entered to calculate the complete journey
duration and remaining time. Without one, elapsed time can still be shown after
departure and remaining time is labelled as pending.

Each leg's folded **Flight details** section shows the current time at its
origin and destination airports. When the optional FR24 source provides a
recent aircraft position, it also shows the local time at that position. FR24
data is never required to display the itinerary.

Airport labels include the IATA code and city from the integration's bundled
offline airport data. A matching FR24 record can provide a city when the
bundled map does not have one. Use `airport_names` to override labels for this
card, for example:

~~~yaml
type: custom:airport-itinerary-schedule
entity: sensor.flight_itineraries
airport_names:
  CPH: Copenhagen
  LAX: Los Angeles
~~~

Each leg shows its scheduled flight duration when both local departure and
destination arrival were entered. That duration is calculated from the stored
offset-aware timestamps, so crossing timezones or daylight-saving boundaries
does not distort the elapsed time. A leg without an expected arrival displays
“Arrival not entered”; it does not infer a duration from a flight number.

Upcoming flights stay neutral until their scheduled window ends. After confirmed
arrival (or scheduled arrival when no live match exists), the progress bar uses
the progress color during the finish delay, then the departure time and bar use
the finished colour unless explicit status/progress colours take precedence.
The arrival time follows these colours only after confirmed landing or arrival.
The delay defaults to 300 seconds and its completion timestamp is persisted
by the integration for confirmed arrivals. Schedule-only progress is grey,
while a flight with FR24 data uses the live progress color. Schedule-only legs
without an active airborne signal change to “Finished (scheduled)” after the
delay, so the card does not imply a confirmed arrival. The remaining-time label
moves with the scheduled progress position. Header, progress, and flight-status colors can be
overridden per card:

~~~yaml
type: custom:airport-itinerary-schedule
header_background: "#123B2C"
header_background_opacity: 70

# Optional: override status-based progress/time colours.
# progress_color: var(--primary-color)
finished_color: var(--disabled-text-color)
finish_delay_seconds: 300
status_colors:
  scheduled: var(--primary-text-color)
  in_transit: var(--state-active-color)
  airborne: var(--info-color)
  landed: var(--success-color)
  arrived: var(--success-color)
  connection: var(--success-color)
  completed: var(--disabled-text-color)
~~~

`header_background` accepts a CSS color. Set `header_background_opacity` from
0 (transparent) to 100 (opaque) to apply an opacity percentage independently.
Colourisation is limited to the **departure time, arrival time, status badge and
progress bar/marker**. Headings, airport names, descriptive labels, flight details
and action icons keep their normal styling, including after a flight finishes.

With matched FR24 data, departure and progress use the current status colour by
default; the badge uses that same status colour. **Arrival keeps its normal text
colour until landing or arrival is confirmed**, even when an estimate is overdue
or custom colours are configured. Being on the ground before takeoff, manual or
inferred completion, and a passed scheduled arrival do not qualify. Confirmed
arrival evidence retained after FR24 cleanup still qualifies.

Without FR24 data, the bar is muted and an elapsed departure uses the theme
primary colour. Future departures and unconfirmed arrivals retain normal text
colour. Schedule-only timing never proves actual departure or arrival.

Explicit card settings apply in both modes:

- **status_colors** colours the status badge, departure and bar for that status,
  and arrival once landing or arrival is confirmed.
- **progress_color** overrides the bar, departure and confirmed arrival, while the
  badge retains its status colour. It remains effective after finishing unless a
  finished override is configured.
- **finished_color**, when configured, overrides the badge, departure, progress
  and confirmed arrival after the finish delay. Without it, explicit status/progress
  colours remain in effect; otherwise eligible finished times and progress use the
  muted default. An unconfirmed arrival remains normal text in either case.

**finish_delay_seconds** defaults to 300. Supported **status_colors** keys are
scheduled, in_transit, airborne, landed, arrived, connection, and completed.
These options do not tint unrelated text or action icons.

Landing shows **Landed · awaiting gate**, or **Taxiing to gate** when fresh ground
movement is available; both use `status_colors.landed`. These colours survive
loss of the FR24 record. Landing does not start the finish or auto-collapse timer.
Gate confirmation shows **Final arrival · at gate** with `status_colors.arrived`.
That colour remains for the finish delay, including during automatic itinerary
selection, before the configured finished colour and collapse settings apply.
Explicit status/progress colours still persist after that delay unless a finished
colour overrides them. Manual completion and removal remain available actions.

The reusable badge adapter separately keeps final arrival visible for its
configured `after` window from gate confirmation, falling back to touchdown when
no gate evidence is available. Its reconcile/priority rules can dismiss the badge
without deleting arrival evidence or stored trips.

## Actions

The input card calls the integration's **create_itinerary** and **add_flight**
actions and uses their response data to show validation errors. The schedule
card calls **remove_flight** for a leg's remove control. Clear or delete a full
itinerary through the integration's other actions.

## Development

The cards, tests and documentation are maintained with the integration in AaFI.
The distributable is
[`custom_components/airport_aware_itinerary/www/airport-itinerary.js`](../custom_components/airport_aware_itinerary/www/airport-itinerary.js);
there is no separate card build or Dashboard release to install.
See [contributor guidance](../CONTRIBUTING.md) for Node and browser checks,
platform requirements and release validation.
