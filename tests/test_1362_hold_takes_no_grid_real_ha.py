"""#1362 — the hold that took no grid, in a real Home Assistant.

The unit tests use a fake ``hass``. Here the two inverter selects are REAL
``select`` entities (the template integration, each writing an
``input_select`` like an inverter integration writes its register), and SEM's
adapter calls HA's real ``select.select_option`` service. The inverter's own
rule (hold mode + a mains charge source = a grid charge) is checked on the
states Home Assistant shows after every cycle.
"""
from __future__ import annotations

import importlib.util
import json

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from homeassistant.setup import async_setup_component

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.hold_select import (
    SelectHold,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

MODE = "select.inverter_output_source_priority"
SOURCE = "select.inverter_charger_source_priority"
MODES = ["Utility", "Solar first", "SBU"]
SOURCES = ["Solar first", "Solar and mains", "Only solar"]


class _Store:
    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


def _template_select(name, backing):
    return {
        "name": name,
        "state": "{{ states('%s') }}" % backing,
        "options": "{{ state_attr('%s', 'options') }}" % backing,
        "select_option": {
            "action": "input_select.select_option",
            "target": {"entity_id": backing},
            "data": {"option": "{{ option }}"},
        },
    }


async def _setup(hass, mode="SBU", source="Solar and mains"):
    assert await async_setup_component(hass, "input_select", {"input_select": {
        "inv_out": {"options": MODES, "initial": mode},
        "inv_src": {"options": SOURCES, "initial": source},
    }})
    assert await async_setup_component(hass, "template", {"template": [{
        "select": [
            _template_select("Inverter output source priority", "input_select.inv_out"),
            _template_select("Inverter charger source priority", "input_select.inv_src"),
        ]}]})
    await hass.async_block_till_done()
    assert hass.states.get(MODE).state == mode
    assert hass.states.get(SOURCE).state == source


def _adapter(hass, store):
    return GenericBatteryAdapter(hass, {
        "battery_id": "b1",
        "battery_hold_select_entity": MODE,
        "battery_hold_select_option": "Utility",
        "battery_hold_record": ForcedChargeRecord(store),
        "battery_charge_select_entity": SOURCE,
        "battery_charge_select_option": "Solar and mains",
        "forced_charge_record": ForcedChargeRecord(_Store()),
    })


def _grid_charges(hass) -> bool:
    return (hass.states.get(MODE).state == "Utility"
            and hass.states.get(SOURCE).state == "Solar and mains")


async def _cycle(hass, adapter, decision):
    await actuate_battery(decision, adapter)
    await hass.async_block_till_done()
    assert not _grid_charges(hass), "the hold charged the battery from the grid"


@pytest.fixture(autouse=True)
def _no_dwell(monkeypatch):
    monkeypatch.setattr(SelectHold, "MIN_HOLD_S", 0.0)
    monkeypatch.setattr(SelectHold, "SHOW_WITHIN_S", 0.0)
    monkeypatch.setattr(SelectHold, "AWAY_FOR_S", 0.0)


HOLD = BatteryDecision(battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
                       discharge_limit_w=0.0)
NORMAL = BatteryDecision(battery_id="b1", intent=BatteryIntent.NORMAL)


@pytest.mark.asyncio
async def test_the_reported_hold_in_a_real_home_assistant(sem_real_hass):
    hass = sem_real_hass
    await _setup(hass)
    a = _adapter(hass, _Store())
    for _ in range(3):
        await _cycle(hass, a, HOLD)
    assert hass.states.get(MODE).state == "Utility"
    assert hass.states.get(SOURCE).state == "Only solar"
    for _ in range(2):
        await _cycle(hass, a, NORMAL)
    assert hass.states.get(MODE).state == "SBU"
    assert hass.states.get(SOURCE).state == "Solar and mains"


@pytest.mark.asyncio
async def test_a_restart_mid_hold_in_a_real_home_assistant(sem_real_hass):
    hass = sem_real_hass
    await _setup(hass)
    store = _Store()
    await _cycle(hass, _adapter(hass, store), HOLD)
    b = _adapter(hass, store)                      # the next lifetime
    await b.async_adopt_hold()
    await _cycle(hass, b, NORMAL)
    assert hass.states.get(MODE).state == "SBU"
    assert hass.states.get(SOURCE).state == "Solar and mains"
