"""Explicit airport downloads with an atomic, validated offline cache."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import hashlib
import json
import re

import aiohttp
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .airport_data import set_active_data
from .airport_validation import build_maps
from .const import AIRPORTS_FILE, DOMAIN, EVENT_LIFECYCLE

MAX_BYTES = 20 * 1024 * 1024


def validate_payload(payload):
    """Use the same validation for disk caches as for upstream records."""
    if not isinstance(payload, dict) or not isinstance(payload.get("metadata"), dict):
        raise ValueError("Airport cache metadata is malformed.")
    zones = payload.get("airports", {})
    cities = payload.get("airport_cities", {})
    coordinates = payload.get("airport_coordinates", {})
    if not all(isinstance(value, dict) for value in (zones, cities, coordinates)):
        raise ValueError("Airport cache maps are malformed.")
    rows = {code: {"iata": code, "tz": zone, "city": cities.get(code),
                   "lat": coordinates.get(code, {}).get("latitude"), "lon": coordinates.get(code, {}).get("longitude")}
            for code, zone in zones.items()}
    rebuilt = build_maps(json.dumps(rows).encode())
    if rebuilt != (zones, cities, coordinates):
        raise ValueError("Airport cache maps are not canonical or contain orphan records.")
    if not re.fullmatch(r"[0-9a-f]{40}", str(payload["metadata"].get("source_commit", ""))):
        raise ValueError("Airport cache revision is invalid.")
    return payload


class AirportDataRefresh:
    def __init__(self, hass):
        self.hass = hass
        self.store = Store(hass, 1, f"{DOMAIN}.airports")
        self.lock = asyncio.Lock()
        self.status = {"status": "bundled", "last_success": None, "last_error": None}
        self.bundled = None

    async def async_load(self):
        self.bundled = await self.hass.async_add_executor_job(lambda: validate_payload(json.loads(AIRPORTS_FILE.read_text(encoding="utf-8"))))
        set_active_data(self.bundled)
        try:
            saved = await self.store.async_load()
            if saved:
                payload = await self.hass.async_add_executor_job(validate_payload, saved["payload"])
                set_active_data(payload)
                self.status.update(status="cached", last_success=saved.get("last_success"))
        except (ValueError, KeyError, TypeError, AttributeError, OSError):
            self.status.update(status="bundled", last_error="Invalid airport cache; using bundled data.")

    def _publish(self):
        self.hass.bus.async_fire(EVENT_LIFECYCLE)

    async def _download(self, url):
        session = async_get_clientsession(self.hass)
        async with session.get(url, timeout=aiohttp.ClientTimeout(total=30), headers={"User-Agent": "ha-airport-itinerary"}) as response:
            response.raise_for_status()
            chunks, size = [], 0
            async for chunk in response.content.iter_chunked(65536):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise ValueError("Airport download exceeds the size limit.")
                chunks.append(chunk)
            return b"".join(chunks)

    async def async_refresh(self):
        if self.lock.locked():
            return {"success": False, "error": "An airport-data operation is already running."}
        async with self.lock:
            self.status.update(status="refreshing", last_error=None)
            self._publish()
            try:
                revision = json.loads(await self._download("https://api.github.com/repos/mwgg/Airports/commits/HEAD"))["sha"]
                if not isinstance(revision, str) or not re.fullmatch(r"[0-9a-f]{40}", revision):
                    raise ValueError("Upstream did not return a valid commit SHA.")
                source = await self._download(f"https://raw.githubusercontent.com/mwgg/Airports/{revision}/airports.json")
                zones, cities, coordinates = await self.hass.async_add_executor_job(build_maps, source)
                payload = {"airports": zones, "airport_cities": cities, "airport_coordinates": coordinates,
                           "metadata": {"source_repository": "mwgg/Airports", "source_commit": revision,
                                        "source_sha256": hashlib.sha256(source).hexdigest(), "mapping_count": len(zones),
                                        "city_count": len(cities), "coordinate_count": len(coordinates)}}
                finished = datetime.now(timezone.utc).isoformat(timespec="seconds")
                await self.store.async_save({"payload": payload, "last_success": finished})
                set_active_data(payload)
                self.status.update(status="cached", last_success=finished, last_error=None)
                result = {"success": True, **payload["metadata"]}
            except (aiohttp.ClientError, TimeoutError, ValueError, KeyError, TypeError, OSError) as err:
                self.status.update(status="error", last_error=str(err))
                result = {"success": False, "error": str(err)}
            self._publish()
            return result

    async def async_restore(self):
        if self.lock.locked():
            return {"success": False, "error": "An airport-data operation is already running."}
        async with self.lock:
            try:
                await self.store.async_remove()
            except OSError as err:
                return {"success": False, "error": str(err)}
            set_active_data(self.bundled)
            self.status.update(status="bundled", last_error=None)
            self._publish()
            return {"success": True}
