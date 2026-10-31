"""Persistent in-memory itinerary data manager."""

from __future__ import annotations

from datetime import datetime, timezone
from copy import deepcopy
from typing import Any
from uuid import uuid4

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store

from .const import EVENT_UPDATED
from .lifecycle import occurrence, timestamp, iso

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
            return {"itineraries": [], "lifecycle": {}, "schema_version": 2}
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
        return {"itineraries": itineraries, "schema_version": 2,
                "lifecycle": saved.get("lifecycle", {}) if isinstance(saved.get("lifecycle"), dict) else {}}

    def snapshot(self) -> list[dict[str, Any]]:
        """Return a copy-safe view of stored itineraries."""
        return deepcopy(self._data["itineraries"])

    def lifecycle_snapshot(self) -> dict:
        return deepcopy(self._data.get("lifecycle", {}))

    async def async_update_lifecycle(self, state: dict, evidence: dict) -> None:
        """Commit observations and event receipts before publishing transitions."""
        changed = state != self._data.get("lifecycle", {})
        self._data["lifecycle"] = deepcopy(state)
        events = []
        for trip in self._data["itineraries"]:
            for leg in trip["legs"]:
                observed = evidence.get(occurrence(leg), {})
                saved = leg.setdefault("evidence", {})
                for kind, value in observed.items():
                    if kind in saved or not timestamp(value):
                        continue
                    saved[kind] = value
                    changed = True
                    if kind != "actual_arrival":
                        events.append({"itinerary_id": trip["id"], "itinerary_name": trip["name"],
                                       "leg_id": leg["id"], "flight_number": leg["flight_number"],
                                       "occurrence": occurrence(leg), "event": kind, "event_time": value,
                                       "evidence_source": "manual" if kind == "manual_completion" else "inferred" if kind == "inferred_completion" else "fr24"})
                finished = next((saved[key] for key in ("gate_arrival", "actual_arrival", "touchdown") if saved.get(key)), None)
                if finished and finished != leg.get("finished_at"):
                    leg["finished_at"] = finished
                    changed = True
                if saved.get("manual_completion") or saved.get("inferred_completion"):
                    leg["completed"] = True
        if changed:
            await self._store.async_save(self._data)
            for event in events:
                self._hass.bus.async_fire("airport_aware_itinerary_flight_event", event)
            self._fire_updated()

    async def async_mark_flight_completed(self, itinerary_id: str, leg_id: str) -> dict:
        trip = self._find(itinerary_id)
        leg = next((row for row in trip["legs"] if row["id"] == leg_id), None) if trip else None
        if leg is None:
            return {"success": False, "error": "Flight leg was not found."}
        await self.async_update_lifecycle(self.lifecycle_snapshot(), {
            occurrence(leg): {"manual_completion": iso(datetime.now(timezone.utc).timestamp())}
        })
        return {"success": True, "itinerary": deepcopy(trip)}

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
