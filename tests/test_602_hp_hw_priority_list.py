"""#602/#576 — heat pump + hot water are first-class draggable rows in the ONE
priority list; their surplus priority is the drag position, not a standalone
heat_pump_priority/hot_water_priority knob."""

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


def _reg():
    return UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())


def _hp_hw():
    return [
        {"id": "heat_pump", "name": "Heat Pump", "priority_seed": 4,
         "power_entity": "sensor.hp_power", "energy_sensor": None,
         "switch_entity": None, "current_power_w": 1200, "is_on": True,
         "rated_power_w": 2000},
        {"id": "hot_water", "name": "Hot Water", "priority_seed": 6,
         "power_entity": None, "energy_sensor": "sensor.dhw_energy",
         "switch_entity": "switch.dhw", "current_power_w": 0, "is_on": False,
         "rated_power_w": 2500},
    ]


@pytest.mark.unit
class TestHpHwPriorityRows:
    def test_hp_hw_emitted_as_draggable_rows(self):
        reg = _reg()
        reg.set_load_controllers(_hp_hw())
        devs = reg.get_devices_for_sensor()
        assert "heat_pump" in devs and "hot_water" in devs
        assert devs["heat_pump"]["device_type"] == "heat_pump"
        assert devs["heat_pump"]["is_controllable"] is True
        # current_power is WATTS (card divides by 1000)
        assert devs["heat_pump"]["current_power"] == 1200
        assert devs["heat_pump"]["power_rating"] == 2000

    def test_priority_is_the_seed_when_not_dragged(self):
        reg = _reg()
        reg.set_load_controllers(_hp_hw())
        devs = reg.get_devices_for_sensor()
        assert devs["heat_pump"]["priority"] == 4   # from heat_pump_priority seed
        assert devs["hot_water"]["priority"] == 6

    def test_drag_position_wins_over_the_config_seed(self):
        reg = _reg()
        reg._priority_overrides["heat_pump"] = 1     # dragged to the top
        reg.set_load_controllers(_hp_hw())
        devs = reg.get_devices_for_sensor()
        assert devs["heat_pump"]["priority"] == 1    # drag beats the seed
        assert devs["hot_water"]["priority"] == 6    # untouched

    def test_no_rows_when_no_controllers(self):
        reg = _reg()
        reg.set_load_controllers([])
        devs = reg.get_devices_for_sensor()
        assert "heat_pump" not in devs and "hot_water" not in devs

    def test_load_controller_entities_for_dedup(self):
        reg = _reg()
        reg.set_load_controllers(_hp_hw())
        ents = reg._load_controller_entities()
        assert "sensor.hp_power" in ents   # HP power sensor
        assert "switch.dhw" in ents        # HW switch
