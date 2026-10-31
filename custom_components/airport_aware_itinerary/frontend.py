"""Serve the bundled cards and maintain their single Lovelace resource."""

import asyncio
import logging
from pathlib import Path
from urllib.parse import urlsplit

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.lovelace import LOVELACE_DATA

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)
CARD_VERSION = "1.6.9"
CARD_PATH = Path(__file__).parent / "www" / "airport-itinerary.js"
CARD_URL = "/airport_aware_itinerary/airport-itinerary.js"
RESOURCE_URL = f"{CARD_URL}?v={CARD_VERSION}"
LEGACY_PATHS = {
    "/hacsfiles/lovelace-airport-itinerary/airport-itinerary.js",
    "/local/community/lovelace-airport-itinerary/airport-itinerary.js",
    "/local/lovelace-airport-itinerary/airport-itinerary.js",
}


def _is_our_resource(url):
    parsed = urlsplit(url)
    return not parsed.scheme and not parsed.netloc and parsed.path in {CARD_URL, *LEGACY_PATHS}


async def async_setup_frontend(hass):
    """Register once per HA process; reloads must not duplicate HTTP routes."""
    runtime = hass.data.setdefault(DOMAIN, {})
    lock = runtime.setdefault("frontend_lock", asyncio.Lock())
    async with lock:
        if not runtime.get("frontend_registered"):
            await hass.http.async_register_static_paths([
                StaticPathConfig(CARD_URL, str(CARD_PATH), cache_headers=False)
            ])
            runtime["frontend_registered"] = True
        lovelace = hass.data[LOVELACE_DATA]
        if lovelace.resource_mode != "storage":
            _LOGGER.info("YAML Lovelace resources: register %s as a module and remove the former standalone card resource", RESOURCE_URL)
            return
        resources = lovelace.resources
        # Loading is essential on older Core versions: an empty unloaded collection
        # must never be saved over the user's existing dashboard resources.
        await resources.async_get_info()
        ours = [row for row in resources.async_items() if _is_our_resource(row.get("url", ""))]
        if ours:
            primary = next((row for row in ours if urlsplit(row["url"]).path == CARD_URL), ours[0])
            if primary["url"] != RESOURCE_URL or primary.get("type") != "module":
                await resources.async_update_item(primary["id"], {"url": RESOURCE_URL, "res_type": "module"})
            for duplicate in ours:
                if duplicate["id"] != primary["id"]:
                    await resources.async_delete_item(duplicate["id"])
        else:
            await resources.async_create_item({"url": RESOURCE_URL, "res_type": "module"})
