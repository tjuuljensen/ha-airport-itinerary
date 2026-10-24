"""Constants for the Airport-aware Flight Itinerary integration."""

from pathlib import Path

DOMAIN = "airport_aware_itinerary"
NAME = "Airport-aware Flight Itinerary"
PLATFORMS = ["sensor"]
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.json"
EVENT_UPDATED = f"{DOMAIN}_updated"
CONF_TRACKED_FLIGHTS_ENTITY = "tracked_flights_entity"
CONF_FR24_ADD_TO_TRACK_ENTITY = "fr24_add_to_track_entity"
CONF_FR24_AUTO_TRACK = "fr24_auto_track"
DATA_DIR = Path(__file__).parent / "data"
AIRPORTS_FILE = DATA_DIR / "airport_timezones.json"

SERVICE_RESOLVE_DEPARTURE = "resolve_departure"
SERVICE_CREATE_ITINERARY = "create_itinerary"
SERVICE_ADD_FLIGHT = "add_flight"
SERVICE_REMOVE_FLIGHT = "remove_flight"
SERVICE_CLEAR_ITINERARY = "clear_itinerary"
SERVICE_DELETE_ITINERARY = "delete_itinerary"
SERVICE_RENAME_ITINERARY = "rename_itinerary"

CONF_ORIGIN_AIRPORT = "origin_airport"
CONF_DESTINATION_AIRPORT = "destination_airport"
CONF_SERVICE_DATE = "service_date"
CONF_DEPARTURE_TIME = "departure_time"
CONF_ARRIVAL_DATE = "arrival_date"
CONF_ARRIVAL_TIME = "arrival_time"
