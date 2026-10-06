"""#1053 — a charger's name, and its entities' names, follow the user's language.

RienduPre (Dutch UI) still saw English after the heat pump fix: an unnamed
charger was "EV Charger", and its entities read "EV Charger Power",
"EV Charger Session Energy". A charger without a name of its own now takes
the default in Home Assistant's language, its entities take their own part
from the translation files with the charger's name as a placeholder, and a
name the user typed always stays. Entity ids never change.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.utils.device_names import (
    charger_display_name,
)

ROOT = Path(__file__).resolve().parents[1]
LANGS = sorted(p.stem for p in (ROOT / "translations").glob("*.json"))


def _hass(lang):
    return SimpleNamespace(config=SimpleNamespace(language=lang))


@pytest.mark.parametrize("cfg, index, expect", [
    ({"name": "EV Charger"}, 0, "EV-lader"),
    ({"name": "EV Charger 2"}, 1, "EV-lader 2"),
    ({}, 0, "EV-lader"),
    ({}, 1, "EV-lader 2"),
    ({"name": ""}, 2, "EV-lader 3"),
    ({"name": "Garage"}, 0, "Garage"),
    ({"name": "KEBA P30"}, 1, "KEBA P30"),
])
def test_a_dutch_home_names_chargers_in_dutch(cfg, index, expect):
    assert charger_display_name(_hass("nl"), cfg, index) == expect


def test_plan_labels_carry_only_a_name_the_user_gave():
    """Tomorrow's plan shows its own translated word for an unnamed charger,
    so an old English default must not reach it as a label."""
    from custom_components.solar_energy_management.utils.device_names import (
        charger_own_name,
    )
    assert charger_own_name({"name": "EV Charger"}) is None
    assert charger_own_name({"name": "EV Charger 2"}) is None
    assert charger_own_name({}) is None
    assert charger_own_name({"name": " Garage "}) == "Garage"


def test_without_home_assistant_the_default_is_english():
    assert charger_display_name(None, {}, 0) == "EV Charger"
    assert charger_display_name(None, {"name": "EV Charger 2"}, 1) == "EV Charger 2"


def _per_charger_keys():
    src = (ROOT / "sensor.py").read_text(encoding="utf-8")
    return sorted(set(re.findall(r'translation_key="(per_charger_[a-z_0-9]+)"', src)))


def test_every_per_charger_sensor_has_a_translated_name_in_every_language():
    keys = _per_charger_keys()
    assert len(keys) >= 17, keys
    for lang in LANGS:
        sensors = json.loads((ROOT / "translations" / f"{lang}.json")
                             .read_text(encoding="utf-8"))["entity"]["sensor"]
        for key in keys:
            name = sensors.get(key, {}).get("name", "")
            assert "{charger}" in name, (lang, key, name)
    strings = json.loads((ROOT / "strings.json").read_text(encoding="utf-8"))
    for key in keys:
        assert "{charger}" in strings["entity"]["sensor"][key]["name"], key
    for lang in LANGS + ["strings"]:
        path = ROOT / ("strings.json" if lang == "strings"
                       else f"translations/{lang}.json")
        time_names = json.loads(path.read_text(encoding="utf-8"))["entity"]["time"]
        assert "{charger}" in time_names["per_charger_target_time"]["name"], lang


def test_every_flow_selector_has_its_options_in_every_language():
    flow = (ROOT / "config_flow.py").read_text(encoding="utf-8")
    keys = sorted(set(re.findall(r'translation_key="([a-z_]+)"', flow)))
    assert "tariff_mode" in keys and "solar_forecast_source" in keys
    for lang in LANGS:
        sel = json.loads((ROOT / "translations" / f"{lang}.json")
                         .read_text(encoding="utf-8")).get("selector", {})
        for key in keys:
            assert sel.get(key, {}).get("options"), (lang, key)


def test_the_flow_menus_read_dutch():
    from custom_components.solar_energy_management.config_flow import _flow_text
    flow = SimpleNamespace(hass=_hass("nl"))
    assert _flow_text(flow, "flow_edit_item", "Edit: {name}",
                      name="EV-lader") == "Bewerken: EV-lader"
    assert _flow_text(flow, "flow_add_heat_pump", "Add another heat pump") \
        == "Nog een warmtepomp toevoegen"
    assert _flow_text(SimpleNamespace(hass=None), "flow_remove_item",
                      "Remove: {name}", name="X") == "Remove: X"


@pytest.mark.asyncio
async def test_a_dutch_home_reads_dutch_charger_entities_and_keeps_their_ids(
        sem_real_hass, sem_config_entry):
    """A real setup in a Dutch Home Assistant, upgraded from the English
    names: the default charger's entities read Dutch, a named charger keeps
    its name, and every entity keeps the id it had."""
    from homeassistant.helpers import entity_registry as er

    from .test_services_real import _seed_sem_input_sensors

    sem_real_hass.config.language = "nl"
    _seed_sem_input_sensors(sem_real_hass)
    sem_config_entry.add_to_hass(sem_real_hass)
    base = dict(sem_config_entry.data["ev_chargers"][0])
    chargers = [{**base, "name": "EV Charger"},
                {**base, "id": "garage", "name": "Garage"}]
    sem_real_hass.config_entries.async_update_entry(
        sem_config_entry, options={**sem_config_entry.options,
                                   "ev_chargers": chargers})

    # The install as an older SEM left it: English names in the registry.
    reg = er.async_get(sem_real_hass)
    old = reg.async_get_or_create(
        "sensor", "solar_energy_management", "sem_charger_ev_charger_power",
        suggested_object_id="sem_charger_ev_charger_power",
        config_entry=sem_config_entry, original_name="EV Charger Power")
    assert old.entity_id == "sensor.sem_charger_ev_charger_power"

    assert await sem_real_hass.config_entries.async_setup(sem_config_entry.entry_id)
    await sem_real_hass.async_block_till_done()

    power = sem_real_hass.states.get("sensor.sem_charger_ev_charger_power")
    assert power is not None
    assert power.attributes.get("charger_name") == "EV-lader"
    assert "EV-lader Vermogen" in power.attributes.get("friendly_name", "")
    assert reg.async_get("sensor.sem_charger_ev_charger_power").unique_id \
        == "sem_charger_ev_charger_power"

    garage = sem_real_hass.states.get("sensor.sem_charger_garage_power")
    assert garage is not None
    assert "Garage Vermogen" in garage.attributes.get("friendly_name", "")

    target = sem_real_hass.states.get("time.sem_charger_ev_charger_target_time")
    assert target is not None
    assert "EV-lader Laden vóór" in target.attributes.get("friendly_name", "")

    mode = sem_real_hass.states.get("select.sem_charger_ev_charger_charge_mode")
    assert mode is not None
    assert "EV-lader" in mode.attributes.get("friendly_name", "")
