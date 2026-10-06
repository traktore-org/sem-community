"""#1053 — SEM's own device names follow the user's language.

RienduPre (Dutch UI) saw the plan say "Heat Pump — draait naar verwachting".
The heat pump and hot-water devices SEM controls were named by English
literals ("Heat Pump", "Heat Pump 2", "Hot Water") that no flow lets the user
change. A default name now comes from the shared translation file in the
Home Assistant language; a name the user set always wins.
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.utils.device_names import (
    device_display_name,
)

ROOT = Path(__file__).resolve().parents[1]


def _hass(lang):
    return SimpleNamespace(config=SimpleNamespace(language=lang))


@pytest.mark.parametrize("lang, kind, expect", [
    ("nl", "heat_pump", "Warmtepomp"),
    ("de", "heat_pump", "Wärmepumpe"),
    ("en", "heat_pump", "Heat pump"),
    ("nl", "hot_water", "Warm water"),
    ("fr", "hot_water", "Eau chaude"),
])
def test_no_name_gives_the_translated_default(lang, kind, expect):
    assert device_display_name(_hass(lang), None, kind) == expect
    assert device_display_name(_hass(lang), "", kind) == expect


@pytest.mark.parametrize("stored", ["Heat Pump", "Heat pump"])
def test_the_old_english_default_is_translated(stored):
    assert device_display_name(_hass("nl"), stored, "heat_pump") == "Warmtepomp"


def test_a_numbered_default_keeps_its_number():
    assert device_display_name(_hass("nl"), "Heat Pump 2", "heat_pump") == "Warmtepomp 2"
    assert device_display_name(_hass("nl"), None, "heat_pump", number=3) == "Warmtepomp 3"


def test_the_old_hot_water_default_is_translated():
    assert device_display_name(_hass("nl"), "Hot Water", "hot_water") == "Warm water"


@pytest.mark.parametrize("stored", ["Vloerverwarming", "Heat Pump Garage", "Boiler"])
def test_a_name_the_user_set_always_wins(stored):
    assert device_display_name(_hass("nl"), stored, "heat_pump") == stored


def test_an_unknown_language_falls_back_to_english():
    assert device_display_name(_hass("xx"), None, "heat_pump") == "Heat pump"


def test_every_language_has_both_device_names():
    data = json.loads((ROOT / "dashboard" / "translations.json").read_text("utf-8"))
    missing = [(lang, key) for lang, table in data.items()
               for key in ("device_heat_pump", "device_hot_water")
               if not table.get(key)]
    assert missing == []


def test_the_controllers_get_the_display_name():
    """The setup builds the heat pump and hot-water controllers through the
    one resolver, never from an English literal."""
    import ast
    src = (ROOT / "__init__.py").read_text("utf-8")
    literals = [n.value for n in ast.walk(ast.parse(src))
                if isinstance(n, ast.Constant) and n.value in ("Heat Pump", "Hot Water")]
    assert literals == []


def test_no_home_assistant_yet_gives_english():
    assert device_display_name(None, None, "heat_pump", number=2) == "Heat pump 2"


@pytest.mark.asyncio
async def test_a_dutch_home_names_the_heat_pump_in_dutch(sem_real_hass, sem_config_entry):
    """A real setup in a Dutch Home Assistant: the heat pump and hot-water
    devices SEM controls carry Dutch names, and a named extra unit keeps its
    own name."""
    from custom_components.solar_energy_management.const import DOMAIN
    from .test_services_real import _seed_sem_input_sensors

    sem_real_hass.config.language = "nl"
    _seed_sem_input_sensors(sem_real_hass)
    for eid in ("switch.hp_relay", "switch.hp_relay_b",
                "switch.hp2_relay", "switch.hp2_relay_b"):
        sem_real_hass.states.async_set(eid, "off")
    sem_real_hass.states.async_set("switch.boiler", "off")
    sem_config_entry.add_to_hass(sem_real_hass)
    sem_real_hass.config_entries.async_update_entry(
        sem_config_entry, options={
            **sem_config_entry.options,
            "heat_pump_relay1_entity": "switch.hp_relay",
            "heat_pump_relay2_entity": "switch.hp_relay_b",
            "heat_pumps": [{"name": "Vloerverwarming",
                            "heat_pump_relay1_entity": "switch.hp2_relay",
                            "heat_pump_relay2_entity": "switch.hp2_relay_b"}],
            "hot_water_entity": "switch.boiler",
        })
    assert await sem_real_hass.config_entries.async_setup(sem_config_entry.entry_id)
    await sem_real_hass.async_block_till_done()

    coord = sem_real_hass.data[DOMAIN][sem_config_entry.entry_id]
    coord = getattr(coord, "coordinator", coord)
    names = {getattr(d, "device_id", None): d.name
             for d in coord._surplus_controller.get_devices_sorted()}
    assert names.get("heat_pump") == "Warmtepomp"
    assert names.get("heat_pump_2") == "Vloerverwarming"
    assert names.get("hot_water") == "Warm water"
