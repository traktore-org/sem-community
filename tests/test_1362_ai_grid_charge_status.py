"""#1362 — an AI assistant can tell the user how to set up a grid charge.

matekogon's DESS Monitor battery needs the "grid charge through a select"
setting. The assistant's setup tool now says whether a grid charge is set up,
where it is set, and — when it is not — which selects sit on the battery's
own device and what options they offer. Read only: the user sets it.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.helpers import device_registry as dr, entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management import llm as sem_llm
from custom_components.solar_energy_management.setup_status import grid_charge_part


def _battery_device(hass, *, select_options):
    """A battery device with its power sensor and one select."""
    entry = MockConfigEntry(domain="dess_like", unique_id="inv")
    entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id, identifiers={("dess_like", "inv")}, name="Inverter")
    reg = er.async_get(hass)
    reg.async_get_or_create("sensor", "dess_like", "bp", suggested_object_id="bat_power",
                            config_entry=entry, device_id=dev.id)
    reg.async_get_or_create("select", "dess_like", "src", suggested_object_id="charge_source",
                            config_entry=entry, device_id=dev.id)
    hass.states.async_set("sensor.bat_power", "120", {"unit_of_measurement": "W"})
    hass.states.async_set("select.charge_source", select_options[0],
                          {"options": select_options, "friendly_name": "Charge source"})


def _coord(hass, **config):
    return SimpleNamespace(
        hass=hass, config=config, _observer_mode=False,
        _forecast_reader=SimpleNamespace(source=None),
        source_recommendation=MagicMock(return_value=None),
        _sensor_reader=SimpleNamespace(_energy_dashboard_config=SimpleNamespace(
            battery_power_list=["sensor.bat_power"], battery_power_pairs=[])))


async def test_not_set_up_names_the_selects_on_the_battery_device(sem_real_hass):
    _battery_device(sem_real_hass, select_options=["Solar first", "Utility", "Solar only"])
    out = grid_charge_part(sem_real_hass, _coord(sem_real_hass))
    assert out["configured"] is False
    assert out["where"].startswith("Configuration tab")
    [sel] = out["selects_on_battery_device"]
    assert sel["entity"] == "select.charge_source"
    assert sel["options"] == ["Solar first", "Utility", "Solar only"]


async def test_set_up_reports_the_setting_and_lists_nothing_else(sem_real_hass):
    _battery_device(sem_real_hass, select_options=["Solar first", "Utility"])
    out = grid_charge_part(sem_real_hass, _coord(
        sem_real_hass, battery_charge_select_entity="select.charge_source",
        battery_charge_select_option="Utility"))
    assert out["configured"] is True
    assert out["battery_charge_select_option"] == "Utility"
    assert "selects_on_battery_device" not in out


async def test_a_charge_switch_alone_counts_as_set_up(sem_real_hass):
    out = grid_charge_part(sem_real_hass, _coord(
        sem_real_hass, battery_force_charge_switch="switch.grid_charge"))
    assert out["configured"] is True


async def test_no_battery_read_yet_gives_an_empty_list_not_an_error(sem_real_hass):
    coord = _coord(sem_real_hass)
    coord._sensor_reader = None
    out = grid_charge_part(sem_real_hass, coord)
    assert out["configured"] is False and out["selects_on_battery_device"] == []


async def test_the_ai_setup_tool_carries_it(sem_real_hass):
    _battery_device(sem_real_hass, select_options=["Solar first", "Utility"])
    out = await sem_llm.build_setup_status(sem_real_hass, _coord(sem_real_hass))
    assert out["battery_grid_charge"]["configured"] is False
    assert out["battery_grid_charge"]["selects_on_battery_device"][0]["entity"] == "select.charge_source"
