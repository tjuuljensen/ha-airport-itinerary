# Airport-aware Flight Itinerary

Create and manage flight itineraries in Home Assistant. Enter each airport's
local schedule details; the integration resolves the IANA timezone and stores
an offset-aware instant for dashboards and automations. It does not call an
online timezone service or fetch schedules.

## Install

The integration is under development in the local repository
`tjuuljensen/ha-airport-itinerary`; it is not yet published on GitHub or
available through HACS. For local evaluation, copy
`custom_components/airport_aware_itinerary` into `/config/custom_components/`
and restart Home Assistant. After the public repository is published, add it
in HACS as a custom **Integration** repository. Then add **Airport-aware Flight
Itinerary** from Settings > Devices & services.

No account is required. Airport timezones and city names are bundled and work
offline.
The host must have IANA timezone data available to Python's `zoneinfo`; Home
Assistant OS and supported Core installations normally provide it.

## Actions and data

The integration provides response-bearing actions in the
`airport_aware_itinerary` domain:

- `resolve_departure`: resolve an origin IATA code, service date (`YYYY-MM-DD`),
  and local departure time (`HH:MM`) to an offset-aware ISO timestamp.
- `create_itinerary`: create a named locally stored trip. The response returns
  its `itinerary.id`.
- `add_flight`: append a flight leg to that trip. Departure is required;
  destination and arrival local date/time are optional and must be provided as
  a complete set. If arrival is supplied, the stored leg also includes
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
is already in use; use the registered entity ID after setup. A separate
[Airport Itinerary Dashboard](https://github.com/tjuuljensen/lovelace-airport-itinerary)
HACS Dashboard repository provides itinerary input and reservation-style
schedule cards. Each reservation shows its own scheduled flight duration when
an expected destination-local arrival was entered; total journey duration is
calculated from the first departure to the final arrival.

To connect optional live data, open the integration's options and select the
Flightradar24 Additional Tracked sensor. The adapter reads its `flights`
attribute and matches a leg using flight number/callsign, compatible origin and
destination codes, and the nearest scheduled departure within 12 hours. A
scheduled FR24 record is kept distinct from an actively tracked flight. Without
that sensor, itinerary storage and time resolution continue to work. The
itinerary sensor reports whether tracking is not configured, unavailable,
unsupported, unmatched, scheduled, or live.

The options also support **Automatically add itinerary flights to FR24
tracking**. Enable it and select FR24's **Add to track** text entity. When a
flight is added to an itinerary, the integration sends its flight number using
Home Assistant's `text.set_value` action. Automatic tracking requires both the
Additional Tracked sensor and Add to track text entity, so it can skip flights
already listed by FR24, completed legs, duplicate flight numbers, and flights
whose departure was more than 12 hours ago. If the FR24 sensor is unavailable,
synchronization waits until it updates. This feature is opt-in; leaving it
disabled keeps the FR24 connection read-only. FR24's tracking input behavior is documented by the
[Flightradar24 integration](https://github.com/AlexandrErohin/home-assistant-flightradar24).

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
  Provenance and the upstream MIT notice are in [NOTICE.md](NOTICE.md).
- `2026-10-22 20:25` at DEN resolves to
  `2026-10-22T20:25:00-06:00`.
- Unknown airport codes, unavailable zone data, invalid dates/times, and
  daylight-saving gaps return visible validation errors. Repeated fall-back
  times require an explicit `fold` choice of `earlier` or `later`; pass
  `fold: earlier` or `fold: later` to `resolve_departure` when needed.
- Stored data survives Home Assistant restarts. Removing the integration entry
  does not delete stored trip data; `delete_itinerary` removes a trip explicitly.

## Maintain the airport map

The integration runs fully offline after installation. A maintainer refreshes
the data deliberately from a reviewed upstream commit:

```powershell
python scripts/update_airport_timezones.py --commit <full-40-character-sha>
```

The updater downloads the source at that exact commit, rejects malformed IATA
codes, missing zones, duplicate codes with conflicting zones or city names, and
invalid IANA names, then regenerates the compact maps. Review the source changes
and update the commit and attribution in this README and `NOTICE.md` in the same
release.

## Development

Run unit tests with `python -m pytest`. The test suite covers the pinned map,
timestamp conversion, DST transitions, invalid input, and source-map conflicts.
CI also runs the HACS integration validation action and Home Assistant's
`hassfest` checks against the integration.

## License

Integration source is MIT licensed; third-party airport data retains its
upstream MIT notice in `LICENSES/`.
