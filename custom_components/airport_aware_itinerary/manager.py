"""Persistent in-memory itinerary data manager."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import EVENT_UPDATED

class ItineraryManager:
    """Manage and persist named itineraries and their flight legs."""

    def __init__(
        self, hass: HomeAssistant, store: Store[dict[str, Any]], saved: dict[str, Any] | None
    ) -> None:
        self._store = store
        self._hass = hass
        self._data = self._validate_saved(saved)

    @staticmethod
    def _validate_saved(saved: dict[str, Any] | None) -> dict[str, Any]:
        if saved is None:
            return {"itineraries": []}
        if not isinstance(saved, dict) or not isinstance(saved.get("itineraries"), list):
            return {"itineraries": []}
        itineraries = [
            item
            for item in saved["itineraries"]
            if isinstance(item, dict)
            and isinstance(item.get("id"), str)
            and isinstance(item.get("name"), str)
            and isinstance(item.get("legs"), list)
        ]
        return {"itineraries": itineraries}

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a copy-safe view of stored itineraries."""
        return [dict(item, legs=[dict(leg) for leg in item["legs"]]) for item in self._data["itineraries"]]

    async def async_create_itinerary(self, name: str) -> dict[str, Any]:
        """Create a named itinerary and persist it."""
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 100:
            return {"success": False, "error": "Enter an itinerary name of 1 to 100 characters."}
        itinerary = {
            "id": uuid4().hex,
            "name": clean_name,
            "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "legs": [],
        }
        self._data["itineraries"].append(itinerary)
        await self._store.async_save(self._data)
        self._fire_updated()
        return {"success": True, "itinerary": itinerary}

    async def async_add_flight(self, itinerary_id: str, leg: dict[str, Any]) -> dict[str, Any]:
        """Add a normalized flight leg to an itinerary."""
        itinerary = self._find(itinerary_id)
        if itinerary is None:
            return {"success": False, "error": "Itinerary was not found."}
        normalized = dict(leg, id=uuid4().hex)
        itinerary["legs"].append(normalized)
        await self._store.async_save(self._data)
        self._fire_updated()
        return {"success": True, "itinerary": itinerary, "leg": normalized}

    async def async_record_finished_at(
        self, itinerary_id: str, leg_id: str, finished_at: str
    ) -> bool:
        """Persist the latest confirmed completion time for a flight leg."""
        itinerary = self._find(itinerary_id)
        if itinerary is None:
            return False
        leg = next(
            (item for item in itinerary["legs"] if item.get("id") == leg_id), None
        )
        if leg is None:
            return False
        try:
            candidate = datetime.fromisoformat(finished_at.replace("Z", "+00:00"))
            current_value = leg.get("finished_at")
            current = (
                datetime.fromisoformat(current_value.replace("Z", "+00:00"))
                if isinstance(current_value, str)
                else None
            )
        except ValueError:
            return False
        if candidate.tzinfo is None or (current is not None and current >= candidate):
            return False
        leg["finished_at"] = candidate.astimezone(timezone.utc).isoformat(timespec="seconds")
        await self._store.async_save(self._data)
        self._fire_updated()
        return True

    async def async_remove_flight(self, itinerary_id: str, leg_id: str) -> dict[str, Any]:
        """Remove a flight leg from an itinerary."""
        itinerary = self._find(itinerary_id)
        if itinerary is None:
            return {"success": False, "error": "Itinerary was not found."}
        legs = itinerary["legs"]
        remaining = [leg for leg in legs if leg.get("id") != leg_id]
        if len(remaining) == len(legs):
            return {"success": False, "error": "Flight leg was not found."}
        itinerary["legs"] = remaining
        await self._store.async_save(self._data)
        self._fire_updated()
        return {"success": True, "itinerary": itinerary}

    async def async_clear_itinerary(self, itinerary_id: str) -> dict[str, Any]:
        """Clear all flight legs while retaining the named itinerary."""
        itinerary = self._find(itinerary_id)
        if itinerary is None:
            return {"success": False, "error": "Itinerary was not found."}
        itinerary["legs"] = []
        await self._store.async_save(self._data)
        self._fire_updated()
        return {"success": True, "itinerary": itinerary}

    async def async_delete_itinerary(self, itinerary_id: str) -> dict[str, Any]:
        """Delete an itinerary and all its legs."""
        remaining = [item for item in self._data["itineraries"] if item["id"] != itinerary_id]
        if len(remaining) == len(self._data["itineraries"]):
            return {"success": False, "error": "Itinerary was not found."}
        self._data["itineraries"] = remaining
        await self._store.async_save(self._data)
        self._fire_updated()
        return {"success": True, "itineraries": self.snapshot()}

    async def async_rename_itinerary(self, itinerary_id: str, name: str) -> dict[str, Any]:
        """Rename a stored itinerary and persist the change."""
        clean_name = name.strip()
        if not clean_name or len(clean_name) > 100:
            return {
                "success": False,
                "error": "Enter an itinerary name of 1 to 100 characters.",
            }
        itinerary = self._find(itinerary_id)
        if itinerary is None:
            return {"success": False, "error": "Itinerary was not found."}
        itinerary["name"] = clean_name
        await self._store.async_save(self._data)
        self._fire_updated()
        return {
            "success": True,
            "itinerary": dict(itinerary, legs=[dict(leg) for leg in itinerary["legs"]]),
        }

    def _find(self, itinerary_id: str) -> dict[str, Any] | None:
        return next(
            (item for item in self._data["itineraries"] if item["id"] == itinerary_id), None
        )

    def _fire_updated(self) -> None:
        """Notify the entity platform after persistent data changes."""
        self._hass.bus.async_fire(EVENT_UPDATED)
