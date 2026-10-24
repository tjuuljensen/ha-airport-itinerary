"""Resolve airport-local date and time values to unambiguous instants."""

from __future__ import annotations

import re
from datetime import date, datetime, time, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

IATA_RE = re.compile(r"^[A-Z0-9]{3}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TIME_RE = re.compile(r"^\d{2}:\d{2}$")


class TimeResolutionError(ValueError):
    """A user-facing airport or local-time validation error."""


def resolve_local_time(
    airport_code: str,
    local_date: str,
    local_time: str,
    airports: dict[str, str],
    ambiguous_choice: str | None = None,
) -> dict[str, str]:
    """Return airport timezone and offset-aware ISO timestamp for local input."""
    code = airport_code.strip().upper() if isinstance(airport_code, str) else ""
    if not IATA_RE.fullmatch(code):
        raise TimeResolutionError("Enter a three-character IATA airport code.")

    timezone_name = airports.get(code)
    if not timezone_name:
        raise TimeResolutionError(f"No timezone data is available for airport {code}.")

    if not isinstance(local_date, str) or not DATE_RE.fullmatch(local_date):
        raise TimeResolutionError("Date must use YYYY-MM-DD format.")
    if not isinstance(local_time, str) or not TIME_RE.fullmatch(local_time):
        raise TimeResolutionError("Time must use 24-hour HH:MM format.")
    try:
        local_naive = datetime.combine(date.fromisoformat(local_date), time.fromisoformat(local_time))
    except ValueError as err:
        raise TimeResolutionError("Enter a valid calendar date and clock time.") from err

    try:
        zone = ZoneInfo(timezone_name)
    except (ZoneInfoNotFoundError, ValueError) as err:
        raise TimeResolutionError(
            f"Timezone data for {code} ({timezone_name}) is unavailable on this Home Assistant host."
        ) from err

    candidates: dict[datetime, datetime] = {}
    for fold in (0, 1):
        candidate = local_naive.replace(tzinfo=zone, fold=fold)
        utc_candidate = candidate.astimezone(timezone.utc)
        round_trip = utc_candidate.astimezone(zone).replace(tzinfo=None)
        if round_trip == local_naive:
            candidates[utc_candidate] = candidate

    if not candidates:
        raise TimeResolutionError(
            f"{local_date} {local_time} does not exist in {timezone_name} because clocks move forward."
        )
    if len(candidates) > 1:
        if ambiguous_choice not in {"earlier", "later"}:
            raise TimeResolutionError(
                f"{local_date} {local_time} occurs twice in {timezone_name} because clocks move back. "
                "Choose the earlier or later occurrence."
            )
        ordered = sorted(candidates.items())
        utc_candidate, resolved = ordered[0 if ambiguous_choice == "earlier" else -1]
    else:
        utc_candidate, resolved = next(iter(candidates.items()))

    offset = resolved.strftime("%z")
    return {
        "airport": code,
        "timezone": timezone_name,
        "local_datetime": local_naive.isoformat(timespec="minutes"),
        "timestamp": resolved.isoformat(timespec="seconds"),
        "utc_timestamp": utc_candidate.isoformat(timespec="seconds"),
        "utc_offset": f"{offset[:3]}:{offset[3:]}",
    }
