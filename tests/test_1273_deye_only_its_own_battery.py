"""#1273 — the Deye platform builds only Deye's own battery as the Deye one.

With ``battery_charge_platform: deye`` every battery used to be built as
the Deye battery. In a home of several batteries the sibling's charge and
sale commands then went to the Deye inverter's work mode and programs.
Deye has no single integration to match, so the rule is: the battery's own
entities must share an integration with the Deye control entities the
config names. A home of one battery is built as before.
"""
from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.solar_energy_management.coordinator.battery_adapters import (
    DeyeBatteryAdapter,
    GenericBatteryAdapter,
    adapter_for,
)

DEYE_POWER = "sensor.deye_battery_power"
SWITCH = "switch.deye_grid_charge"
CURRENT = "number.deye_charge_current"
VOLTAGE = "sensor.deye_battery_voltage"
MODE = "select.deye_energy_pattern"
PACK2_POWER = "sensor.pack2_power"


def _register(hass, platform, entity_id):
    domain, object_id = entity_id.split(".", 1)
    er.async_get(hass).async_get_or_create(
        domain, platform, f"uid_{object_id}", suggested_object_id=object_id)


@pytest.fixture
def home(hass):
    for eid in (DEYE_POWER, SWITCH, CURRENT, VOLTAGE, MODE):
        _register(hass, "solarman", eid)
    _register(hass, "modbus", PACK2_POWER)
    return hass


def _cfg(own, *, fleet=2, **extra):
    return {
        "battery_charge_platform": "deye",
        "deye_grid_charge_switch": SWITCH,
        "deye_charge_current_entity": CURRENT,
        "deye_battery_voltage_entity": VOLTAGE,
        "deye_work_mode_entity": MODE,
        "battery_fleet_size": fleet,
        "battery_own_entity_ids": tuple(own),
        **extra,
    }


class TestOnlyTheDeyeBatteryIsDeye:
    async def test_the_sibling_battery_is_generic(self, home):
        a = adapter_for(home, _cfg((PACK2_POWER,)))
        assert type(a) is GenericBatteryAdapter

    async def test_the_deye_battery_stays_deye(self, home):
        a = adapter_for(home, _cfg((DEYE_POWER,)))
        assert type(a) is DeyeBatteryAdapter

    async def test_one_shared_integration_is_enough(self, home):
        a = adapter_for(home, _cfg((PACK2_POWER, DEYE_POWER)))
        assert type(a) is DeyeBatteryAdapter

    async def test_a_home_of_one_battery_is_built_as_before(self, home):
        assert type(adapter_for(home, _cfg((PACK2_POWER,), fleet=1))) \
            is DeyeBatteryAdapter
        cfg = _cfg(())
        del cfg["battery_fleet_size"], cfg["battery_own_entity_ids"]
        assert type(adapter_for(home, cfg)) is DeyeBatteryAdapter

    async def test_no_own_entities_in_a_fleet_is_generic(self, home):
        assert type(adapter_for(home, _cfg(()))) is GenericBatteryAdapter

    async def test_an_entity_the_registry_does_not_know_is_no_match(self, home):
        a = adapter_for(home, _cfg(("sensor.ghost",)))
        assert type(a) is GenericBatteryAdapter

    async def test_controls_the_registry_does_not_know_is_generic(self, hass):
        _register(hass, "modbus", PACK2_POWER)
        a = adapter_for(hass, _cfg((PACK2_POWER,)))
        assert type(a) is GenericBatteryAdapter

    async def test_program_slots_count_as_deye_controls(self, hass):
        _register(hass, "solarman", "time.deye_slice_1")
        _register(hass, "solarman", DEYE_POWER)
        cfg = {
            "battery_charge_platform": "deye",
            "deye_program_groups": [{"time": "time.deye_slice_1"}],
            "battery_fleet_size": 2,
            "battery_own_entity_ids": (DEYE_POWER,),
        }
        assert type(adapter_for(hass, cfg)) is DeyeBatteryAdapter

    def test_no_registry_answer_is_generic(self):
        class _Hass:
            data: dict = {}
        assert type(adapter_for(_Hass(), _cfg((DEYE_POWER,)))) \
            is GenericBatteryAdapter
