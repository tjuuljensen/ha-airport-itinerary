"""Airport cache integrity and failure recovery."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import aiohttp
import pytest

from custom_components.airport_aware_itinerary.airport_data import get_airport_timezones, get_data_metadata, set_active_data
from custom_components.airport_aware_itinerary.airport_refresh import AirportDataRefresh

REVISION = "a" * 40
SOURCE = json.dumps({"TEST": {"iata": "CPH", "tz": "Europe/Copenhagen", "city": "Copenhagen", "lat": 55.6, "lon": 12.6}}).encode()


@pytest.fixture
async def airports(hass):
    refresh = AirportDataRefresh(hass)
    refresh.store = AsyncMock()
    refresh.store.async_load.return_value = None
    await refresh.async_load()
    yield refresh
    set_active_data(None)


async def test_refresh_persists_only_valid_complete_data_and_restore_works(airports):
    airports._download = AsyncMock(side_effect=[json.dumps({"sha": REVISION}).encode(), SOURCE])
    result = await airports.async_refresh()
    assert result["success"] and get_data_metadata()["source_commit"] == REVISION
    assert get_airport_timezones() == {"CPH": "Europe/Copenhagen"}
    airports.store.async_save.assert_awaited_once()
    assert airports._download.call_args_list[1].args[0].endswith(f"/{REVISION}/airports.json")
    assert (await airports.async_restore())["success"]
    assert len(get_airport_timezones()) > 7000


@pytest.mark.parametrize("failure", [TimeoutError("timeout"), aiohttp.ClientResponseError(SimpleNamespace(real_url="https://api.github.com"), (), status=429, message="rate limited"), ValueError("bad JSON")])
async def test_network_failure_keeps_current_airport_map(airports, failure):
    before = get_data_metadata().copy()
    airports._download = AsyncMock(side_effect=failure)
    assert not (await airports.async_refresh())["success"]
    assert get_data_metadata() == before
    airports.store.async_save.assert_not_awaited()


async def test_conflicting_data_does_not_replace_map(airports):
    source = json.loads(SOURCE)
    source["OTHER"] = {**source["TEST"], "tz": "Europe/London"}
    airports._download = AsyncMock(side_effect=[json.dumps({"sha": REVISION}).encode(), json.dumps(source).encode()])
    assert not (await airports.async_refresh())["success"]
    assert len(get_airport_timezones()) > 7000
    airports.store.async_save.assert_not_awaited()


async def test_concurrent_refresh_and_restore_do_not_overlap(airports):
    async with airports.lock:
        assert not (await airports.async_refresh())["success"]
        assert not (await airports.async_restore())["success"]


async def test_corrupt_cache_falls_back_offline(hass):
    refresh = AirportDataRefresh(hass)
    refresh.store = AsyncMock()
    refresh.store.async_load.return_value = {"payload": {"airports": {"CPH": "Not/AZone"}, "metadata": {}}}
    refresh._download = AsyncMock()
    await refresh.async_load()
    assert refresh.status["last_error"]
    assert len(get_airport_timezones()) > 7000
    refresh._download.assert_not_awaited()
    set_active_data(None)


async def test_save_failure_keeps_last_known_good_map(airports):
    before = get_data_metadata().copy()
    airports._download = AsyncMock(side_effect=[json.dumps({"sha": REVISION}).encode(), SOURCE])
    airports.store.async_save.side_effect = OSError("disk full")
    assert not (await airports.async_refresh())["success"]
    assert get_data_metadata() == before
