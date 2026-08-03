"""#602/#576 — heat pump + hot water are first-class draggable rows in the ONE
priority list; their surplus priority is the drag position (resolved by
``priority_for``), not a standalone heat_pump_priority/hot_water_priority knob.

They're surfaced by the registry's direct-registration path
(``_surplus_device_row``) straight from the surplus controller — no separate
emit path (a parallel one was dead code and was removed)."""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


class _FakeCtrl:
    """Minimal stand-in for a HeatPumpController / HotWaterController as held in
    ``SurplusController._devices`` (keyed by control id)."""

    def __init__(self, did, name, priority, rated, *, on=False, power=0.0,
                 power_entity=None, energy_entity=None, switch_entity=None):
        self.device_id = did
        self.name = name
        self.priority = priority
        self.rated_power = rated
        self.is_active = on
        self._power = power
        self.power_entity_id = power_entity
        self.energy_entity_id = energy_entity
        self.entity_id = switch_entity
        self.is_ev = False
        # device_type reports the generic 'setpoint' enum value, as the real
        # controllers do — the registry must override it to the control id.
        self.device_type = SimpleNamespace(value="setpoint")
        self.control_mode = SimpleNamespace(value="surplus")

    def get_current_consumption(self):
        return self._power


class _SurplusController:
    def __init__(self, devices):
        self._devices = dict(devices)

    def get_device(self, did):
        return self._devices.get(did)


def _reg(devices):
    r = UnifiedDeviceRegistry(MagicMock(), _SurplusController(devices),
                              MagicMock(), MagicMock())
    r._has_battery = False
    return r


def _hp_hw():
    return {
        "heat_pump": _FakeCtrl("heat_pump", "Heat Pump", 4, 2000, on=True,
                               power=1200, power_entity="sensor.hp_power"),
        "hot_water": _FakeCtrl("hot_water", "Hot Water", 6, 2500,
                               energy_entity="sensor.dhw_energy",
                               switch_entity="switch.dhw"),
    }


@pytest.mark.unit
class TestHpHwPriorityRows:
    def test_hp_hw_emitted_as_draggable_rows(self):
        reg = _reg(_hp_hw())
        devs = reg.get_devices_for_sensor()
        assert "heat_pump" in devs and "hot_water" in devs
        # device_type is overridden from 'setpoint' → control id so the card
        # renders the right glyph.
        assert devs["heat_pump"]["device_type"] == "heat_pump"
        assert devs["hot_water"]["device_type"] == "hot_water"
        assert devs["heat_pump"]["is_controllable"] is True
        # current_power is WATTS (card divides by 1000)
        assert devs["heat_pump"]["current_power"] == 1200
        assert devs["heat_pump"]["power_rating"] == 2000

    def test_priority_is_the_seed_when_not_dragged(self):
        reg = _reg(_hp_hw())
        devs = reg.get_devices_for_sensor()
        # seed = the controller's construction priority (from heat_pump_priority)
        assert devs["heat_pump"]["priority"] == 4
        assert devs["hot_water"]["priority"] == 6

    def test_drag_position_wins_over_the_config_seed(self):
        reg = _reg(_hp_hw())
        reg._priority_overrides["heat_pump"] = 1     # dragged to the top
        devs = reg.get_devices_for_sensor()
        assert devs["heat_pump"]["priority"] == 1    # drag beats the seed
        assert devs["hot_water"]["priority"] == 6    # untouched

    def test_no_rows_when_no_controllers(self):
        reg = _reg({})
        devs = reg.get_devices_for_sensor()
        assert "heat_pump" not in devs and "hot_water" not in devs

    def test_companion_energy_sensor_surfaced(self):
        # #600 — a power-sensor-less HW controller surfaces its energy counter
        # so the card can derive power.
        reg = _reg(_hp_hw())
        devs = reg.get_devices_for_sensor()
        assert devs["hot_water"]["energy_sensor"] == "sensor.dhw_energy"
        assert devs["hot_water"]["switch_entity"] == "switch.dhw"
