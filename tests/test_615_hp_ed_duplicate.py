"""#615 — a heat pump (or hot water) configured in SEM AND also added to HA's
Energy Dashboard as an individual device must appear ONCE in the overview /
priority list, not twice.

Root shape (same class as #559 service-vs-ED and #576 charger-vs-ED): the
authoritative direct registration is keyed by its control id (``heat_pump`` /
``hot_water``) while the ED auto-discovered row for the SAME physical appliance
is keyed ``energy_dashboard_<slug>``. The id-keyed dedup can't see that they're
the same device, so it emitted both — the reporter saw "warmtepomp" (their ED
friendly name) AND "heatpump" side by side. Dedup on the SHARED ENTITY instead:
the ED row is dropped, the authoritative control-id row survives.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
    UnifiedDevice,
)


class _FakeCtrl:
    """Direct heat-pump / hot-water registration as held in
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
        self.device_type = SimpleNamespace(value="setpoint")
        self.control_mode = SimpleNamespace(value="surplus")

    def get_current_consumption(self):
        return self._power


class _SurplusController:
    def __init__(self, devices):
        self._devices = dict(devices)

    def get_device(self, did):
        return self._devices.get(did)


def _reg(surplus_devices, ed_devices=None):
    r = UnifiedDeviceRegistry(MagicMock(), _SurplusController(surplus_devices),
                              MagicMock(), MagicMock())
    r._has_battery = False
    r._devices = list(ed_devices or [])
    # hass.states.get() → no live state (power reads fall back to 0)
    r.hass.states.get = MagicMock(return_value=None)
    return r


@pytest.mark.unit
class TestHeatPumpEnergyDashboardDuplicate:
    def test_ed_row_sharing_energy_sensor_is_suppressed(self):
        # HP configured in SEM with a #600 energy counter, AND the user added
        # that same counter to HA's Energy Dashboard → discovered as
        # "warmtepomp".
        hp = _FakeCtrl("heat_pump", "Heat Pump", 4, 2000,
                       energy_entity="sensor.warmtepomp_energy")
        ed = UnifiedDevice(
            energy_sensor="sensor.warmtepomp_energy",
            power_sensor=None,
            name="warmtepomp",
            priority=5,
        )
        devs = _reg({"heat_pump": hp}, [ed]).get_devices_for_sensor()
        assert "heat_pump" in devs                       # authoritative kept
        assert ed.device_id not in devs                  # ED duplicate dropped
        # exactly one heat-pump-ish row
        assert sum(1 for d in devs.values()
                   if d.get("device_type") == "heat_pump") == 1
        assert len(devs) == 1

    def test_ed_row_sharing_power_sensor_is_suppressed(self):
        hp = _FakeCtrl("heat_pump", "Heat Pump", 4, 2000,
                       power_entity="sensor.hp_power")
        ed = UnifiedDevice(
            energy_sensor="sensor.hp_energy",
            power_sensor="sensor.hp_power",
            name="warmtepomp",
            priority=5,
        )
        devs = _reg({"heat_pump": hp}, [ed]).get_devices_for_sensor()
        assert "heat_pump" in devs
        assert ed.device_id not in devs

    def test_hot_water_ed_duplicate_suppressed(self):
        hw = _FakeCtrl("hot_water", "Hot Water", 6, 2500,
                       switch_entity="switch.boiler",
                       energy_entity="sensor.boiler_energy")
        ed = UnifiedDevice(
            energy_sensor="sensor.boiler_energy",
            power_sensor=None,
            name="Boiler",
            priority=5,
        )
        devs = _reg({"hot_water": hw}, [ed]).get_devices_for_sensor()
        assert "hot_water" in devs
        assert ed.device_id not in devs

    def test_ed_row_sharing_switch_entity_is_suppressed(self):
        # A boiler registered by its control switch, with an ED row whose
        # discovered/mapped control points at the SAME switch → one row.
        hw = _FakeCtrl("hot_water", "Hot Water", 6, 2500,
                       switch_entity="switch.boiler")
        ed = UnifiedDevice(
            energy_sensor="sensor.boiler_energy",
            power_sensor=None,
            name="Boiler",
            priority=5,
            control={"entity": "switch.boiler"},
        )
        devs = _reg({"hot_water": hw}, [ed]).get_devices_for_sensor()
        assert "hot_water" in devs
        assert ed.device_id not in devs

    def test_unrelated_ed_device_is_not_suppressed(self):
        # An ED device that does NOT share any entity with the heat pump must
        # survive — the dedup keys on the shared entity, not "is there a HP".
        hp = _FakeCtrl("heat_pump", "Heat Pump", 4, 2000,
                       energy_entity="sensor.hp_energy")
        ed = UnifiedDevice(
            energy_sensor="sensor.dishwasher_energy",
            power_sensor="sensor.dishwasher_power",
            name="Dishwasher",
            priority=5,
        )
        devs = _reg({"heat_pump": hp}, [ed]).get_devices_for_sensor()
        assert "heat_pump" in devs
        assert ed.device_id in devs                      # kept — distinct device

    def test_no_heat_pump_configured_ed_row_survives(self):
        # Without a direct registration there is nothing to dedup against — the
        # ED "warmtepomp" is the only row and must show.
        ed = UnifiedDevice(
            energy_sensor="sensor.warmtepomp_energy",
            power_sensor=None,
            name="warmtepomp",
            priority=5,
        )
        devs = _reg({}, [ed]).get_devices_for_sensor()
        assert ed.device_id in devs
