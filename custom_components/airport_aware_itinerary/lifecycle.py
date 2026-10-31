"""Provider-independent occurrence matching and journey timing."""

from __future__ import annotations

import math
import re
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo


def timestamp(value) -> float:
    """Read a finite epoch or an explicitly zoned ISO timestamp."""
    if isinstance(value, bool):
        return 0
    if isinstance(value, (float, int)):
        return float(value) if math.isfinite(value) and value > 0 else 0
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timestamp() if parsed.tzinfo else 0
        except (ValueError, OverflowError):
            pass
    return 0


def iso(value: float) -> str | None:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="seconds") if value else None


def number(value) -> str:
    value = re.sub(r"[^A-Z0-9]", "", str(value or "").upper())
    match = re.fullmatch(r"([A-Z]{2,3}|[A-Z]\d|\d[A-Z])(\d+)([A-Z]?)", value)
    return f"{match[1]}{int(match[2])}{match[3]}" if match else value


def flight_numbers(flight: dict) -> set[str]:
    return {number(flight.get(key)) for key in ("flight_number", "callsign")} - {""}


def occurrence(leg: dict) -> str:
    return "|".join((number(leg.get("flight_number")), str(timestamp(leg.get("departure", {}).get("utc_timestamp"))),
                     leg.get("origin_airport", ""), leg.get("destination_airport", "")))


def identity(flight: dict) -> str:
    """Identity of a provider occurrence, never just its reusable flight number."""
    return "|".join((str(flight.get("id", "")), number(flight.get("flight_number") or flight.get("callsign")),
                     str(timestamp(flight.get("time_scheduled_departure")))))


def match_flight(leg: dict, flights: list[dict]) -> dict | None:
    departure = timestamp(leg.get("departure", {}).get("utc_timestamp"))
    if not departure:
        return None
    candidates = []
    for flight in flights:
        if not isinstance(flight, dict) or number(leg.get("flight_number")) not in flight_numbers(flight):
            continue
        if any(leg.get(local) and flight.get(remote) and leg[local].upper() != str(flight[remote]).upper()
               for local, remote in (("origin_airport", "airport_origin_code_iata"),
                                     ("destination_airport", "airport_destination_code_iata"))):
            continue
        scheduled = timestamp(flight.get("time_scheduled_departure"))
        if not scheduled or abs(scheduled - departure) > 12 * 3600:
            continue
        zone = leg.get("departure", {}).get("timezone")
        if zone and leg.get("service_date"):
            if datetime.fromtimestamp(scheduled, ZoneInfo(zone)).date().isoformat() != leg["service_date"]:
                continue
        candidates.append((abs(scheduled - departure), flight))
    candidates.sort(key=lambda item: item[0])
    if not candidates or len(candidates) > 1 and candidates[0][0] == candidates[1][0]:
        return None
    return candidates[0][1]


def expires_at(leg: dict) -> float:
    departure = leg.get("departure", {})
    try:
        zone = ZoneInfo(departure["timezone"])
        day = datetime.fromisoformat(leg["service_date"]).date() + timedelta(days=2)
        return datetime.combine(day, time.min, zone).timestamp()
    except (KeyError, ValueError):
        return timestamp(departure.get("utc_timestamp")) + 48 * 3600


def terminal(leg: dict) -> bool:
    evidence = leg.get("evidence", {})
    return bool(leg.get("completed") or leg.get("finished_at") or any(evidence.get(key) for key in
                ("touchdown", "gate_arrival", "actual_arrival", "inferred_completion", "manual_completion")))


def journeys(itineraries: list[dict], now: float, options: dict) -> list[dict]:
    """Calculate UTC boundaries independently of badge presentation windows."""
    result = []
    connection = options.get("connection_hours", 24) * 3600
    lead = options.get("api_before_minutes", 60) * 60
    grace = options.get("api_after_hours", 2) * 3600
    for trip in itineraries:
        groups = []
        for leg in sorted(trip.get("legs", []), key=lambda row: timestamp(row.get("departure", {}).get("utc_timestamp"))):
            if groups:
                previous = groups[-1][-1]
                end = timestamp((previous.get("arrival") or {}).get("utc_timestamp")) or timestamp(previous["departure"].get("utc_timestamp"))
                disconnected = previous.get("destination_airport") and leg.get("origin_airport") and previous["destination_airport"] != leg["origin_airport"]
                split = disconnected or timestamp(leg["departure"].get("utc_timestamp")) - end > connection
            else:
                split = True
            if split:
                groups.append([])
            groups[-1].append(leg)
        for group in groups:
            first, last = group[0], group[-1]
            departure = timestamp(first["departure"].get("utc_timestamp"))
            evidence = last.get("evidence", {})
            touchdown = timestamp(evidence.get("touchdown")) or timestamp(evidence.get("actual_arrival")) or timestamp(evidence.get("gate_arrival")) or timestamp(last.get("finished_at"))
            stop = touchdown + grace if touchdown else max(expires_at(leg) for leg in group)
            all_completed = all(terminal(leg) for leg in group)
            if all_completed and not touchdown:
                stop = max(timestamp(leg.get("evidence", {}).get("manual_completion")) or timestamp(leg.get("evidence", {}).get("inferred_completion")) for leg in group) or stop
            airborne = any(leg.get("fresh_airborne") for leg in group)
            required = departure - lead <= now < stop or airborne
            result.append({
                "id": f"{trip['id']}:{first['id']}", "itinerary_id": trip["id"], "name": trip["name"],
                "leg_ids": [leg["id"] for leg in group], "departure_at": iso(departure),
                "arrival_at": (last.get("arrival") or {}).get("utc_timestamp"),
                "touchdown_at": iso(touchdown), "completed": all_completed,
                "api_start_at": iso(departure - lead), "api_stop_at": None if airborne and now >= stop else iso(stop),
                "expires_at": iso(max(expires_at(leg) for leg in group)),
                "tracking_required": required, "airborne": airborne,
                "status": "airborne" if airborne else "completed" if all_completed else "expired" if now >= stop else "active" if now >= departure else "scheduled",
                "completion_source": "confirmed" if touchdown else "manual_or_inferred" if all_completed else "schedule",
            })
    return sorted(result, key=lambda item: (item["departure_at"], item["id"]))
