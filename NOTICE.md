# Third-party data

The bundled `airport_timezones.json` is generated from
[`mwgg/Airports`](https://github.com/mwgg/Airports), pinned to commit
`a89e4e0dda9d9878337e2da190ebe1ef1d6af705`. The upstream project is licensed
under MIT. Its license notice is included in
[`LICENSES/mwgg-Airports-MIT.txt`](LICENSES/mwgg-Airports-MIT.txt).

The integration bundles IATA-to-IANA timezone mappings, IATA-to-city names,
and IATA airport coordinates from that source. Airport timezone, city, or
coordinate data can be incomplete or incorrect upstream; report a specific
airport and evidence through this project's issue tracker.

When the optional Flightradar24 source is configured and the Python environment
provides [timezonefinder](https://github.com/jannikmi/timezonefinder), aircraft
coordinates can be resolved locally. Its code is MIT licensed. Its separately
distributed timezonefinder-data boundary dataset is licensed under the Open
Database License (ODbL) and is not bundled in this repository. The optional
lookup is not an integration requirement; see that package's metadata for
current license and dataset attribution.
