"""Render the thin adapter with HA's own template environment."""

import json
from pathlib import Path
import yaml

from homeassistant.helpers.template import Template

from custom_components.airport_aware_itinerary.lifecycle import iso

NOW = 1792749600
MACRO = (Path(__file__).parents[1] / "examples/flight_itinerary_adapter.jinja").read_text()


def render(hass, journeys, trips=None, tracked=None, before=0.5, after=2, now=NOW, enabled=True):
    template = Template(MACRO + "{{ display_model(journeys, trips, tracked, enabled, true, now_ts, before, after) }}", hass)
    result = template.async_render({"journeys": journeys, "trips": trips or [], "tracked": tracked or [],
                                    "enabled": enabled, "now_ts": now, "before": before, "after": after}, parse_result=False)
    return json.loads(result)


def journey(id="one", **extra):
    return {"id": id, "itinerary_id": id, "departure_at": iso(NOW + 3600), "arrival_at": iso(NOW + 7200),
            "touchdown_at": None, "expires_at": iso(NOW + 86400), "completed": False, "leg_ids": [], **extra}


def test_badge_uses_configured_before_window(hass):
    assert not render(hass, [journey()])["badge_active"]
    assert render(hass, [journey()], before=2)["badge_active"]
    assert not render(hass, [journey()], before=2, enabled=False)["badge_active"]


def test_badge_retains_arrival_colour_until_gate_based_retention_expires(hass):
    row = journey(departure_at=iso(NOW - 14400), touchdown_at=iso(NOW - 3600), completed=True)
    assert render(hass, [row], after=2)["badge_active"]
    assert not render(hass, [row], after=1)["badge_active"]
    row["final_arrival_at"] = iso(NOW - 1800)
    assert render(hass, [row], after=1)["badge_active"]
    assert render(hass, [row], after=1)["status"] == "arrived"
    assert not render(hass, [row], after=1, now=NOW + 1800)["badge_active"]


def test_badge_distinguishes_landing_taxiing_and_gate(hass):
    leg = {"id": "leg", "flight_number": "MS760", "departure": {"utc_timestamp": iso(NOW - 7200)},
           "arrival": {"utc_timestamp": iso(NOW - 900)}, "finished_at": iso(NOW - 600),
           "evidence": {"actual_arrival": iso(NOW - 600)}}
    trip = {"id": "one", "name": "Trip", "legs": [leg]}
    group = journey(departure_at=iso(NOW - 7200), touchdown_at=iso(NOW - 600), leg_ids=["leg"])
    assert render(hass, [group], [trip])["status"] == "landed"
    live = {"itinerary_id": "one", "leg_id": "leg", "is_live": True, "on_ground": True,
            "ground_speed": 12, "position_updated_at": iso(NOW)}
    assert render(hass, [group], [trip], [live])["status"] == "taxiing"
    assert render(hass, [group], [trip], [live], now=NOW + 301)["status"] == "landed"
    group["final_arrival_at"] = iso(NOW)
    leg["evidence"]["gate_arrival"] = iso(NOW)
    model = render(hass, [group], [trip])
    assert model["status"] == "arrived"
    assert model["flight"]["data"]["gate_arrival"] == NOW


def test_active_journey_wins_and_ties_are_deterministic(hass):
    rows = [journey("upcoming"), journey("b", departure_at=iso(NOW - 60)), journey("a", departure_at=iso(NOW - 60))]
    model = render(hass, rows, before=2)
    assert model["journey_id"] == "a"
    assert model["schedule_only"]


def test_schedule_completion_is_not_presented_as_confirmed_arrival(hass):
    row = journey(departure_at=iso(NOW - 7200), arrival_at=iso(NOW - 1800), completion_source="schedule")
    model = render(hass, [row])
    assert model["status"] != "arrived"
    assert model["completion_source"] == "schedule"
    assert not model["position_fresh"]


def test_adapter_keeps_plane_compatibility_only_for_fresh_airborne_leg(hass):
    row = {"id": "leg", "flight_number": "SK935", "origin_airport": "CPH", "destination_airport": "LAX",
           "departure": {"utc_timestamp": iso(NOW - 60)}, "arrival": {"utc_timestamp": iso(NOW + 3600)}}
    trip = {"id": "one", "name": "Trip", "legs": [row]}
    group = journey(departure_at=iso(NOW - 60), leg_ids=["leg"])
    tracked = {"itinerary_id": "one", "leg_id": "leg", "is_live": True, "on_ground": False,
               "latitude": 55, "longitude": 12, "position_updated_at": iso(NOW)}
    model = render(hass, [group], [trip], [tracked])
    assert model["status"] == "airborne" and model["position_fresh"]
    assert model["flight"]["data"]["airport_origin_code_iata"] == "CPH"
    stale = render(hass, [group], [trip], [tracked], now=NOW + 301)
    assert not stale["position_fresh"] and stale["latitude"] is None


async def test_adapter_templates_and_automations_validate_with_ha(hass):
    from homeassistant.components.template.config import async_validate_config_section
    from homeassistant.components.automation.config import async_validate_config_item
    config = yaml.safe_load((Path(__file__).parents[1] / "examples/flight_itinerary_display_adapter.yaml").read_text())
    for section in config["template"]:
        assert await async_validate_config_section(hass, section)
    for automation in config["automation"]:
        assert await async_validate_config_item(hass, "automation", automation)
