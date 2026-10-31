"""Constants for the Airport-aware Flight Itinerary integration."""

from pathlib import Path

DOMAIN = "airport_aware_itinerary"
NAME = "Airport-aware Flight Itinerary"
PLATFORMS = ["sensor", "binary_sensor", "button", "switch"]
STORAGE_VERSION = 1
STORAGE_KEY = f"{DOMAIN}.json"
EVENT_UPDATED = f"{DOMAIN}_updated"
CONF_TRACKED_FLIGHTS_ENTITY = "tracked_flights_entity"
CONF_FR24_ADD_TO_TRACK_ENTITY = "fr24_add_to_track_entity"
CONF_FR24_AUTO_TRACK = "fr24_auto_track"
CONF_FR24_CONNECTION = "fr24_connection_enabled"
CONF_FR24_REMOVE_ENTITY = "fr24_remove_from_track_entity"
CONF_FR24_SWITCH = "fr24_api_switch"
CONF_FR24_CLEANUP = "fr24_auto_cleanup"
CONF_FR24_ENABLE = "fr24_auto_enable"
CONF_FR24_DISABLE = "fr24_auto_disable"
LIFECYCLE_DEFAULTS = {"connection_hours": 24, "api_before_minutes": 60,
                      "api_after_hours": 2, "cleanup_after_hours": 2}
EVENT_LIFECYCLE = f"{DOMAIN}_lifecycle_updated"
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
