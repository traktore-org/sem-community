"""#646 — stable-line report guards.

1. The three sensors the reporter's HA warned about must carry VALID
   device_class/state_class pairings (monetary→TOTAL/None; predictions and
   computed deficits carry no ENERGY device_class).
2. ROI payback publishes None (→ unknown) on fresh installs instead of the
   0.0 default that read as "already paid off".
"""
from __future__ import annotations



from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass

from custom_components.solar_energy_management.sensor import SENSOR_TYPES
from custom_components.solar_energy_management.coordinator.types import CostData

_BY_KEY = {d.key: d for d in SENSOR_TYPES}


class TestStateClassValidity646:
    def test_roi_annual_savings_monetary_total(self):
        d = _BY_KEY["roi_annual_savings"]
        assert d.device_class == SensorDeviceClass.MONETARY
        # monetary permits only None or TOTAL
        assert d.state_class in (None, SensorStateClass.TOTAL)

    def test_forecast_corrected_today_is_not_energy_class(self):
        d = _BY_KEY["forecast_corrected_today"]
        # a prediction fluctuates — ENERGY (total/total_increasing-only)
        # was invalid with MEASUREMENT
        assert d.device_class is None
        assert d.state_class == SensorStateClass.MEASUREMENT

    def test_battery_scheduler_deficit_is_not_energy_class(self):
        d = _BY_KEY["battery_scheduler_deficit_kwh"]
        assert d.device_class is None
        assert d.state_class == SensorStateClass.MEASUREMENT

    def test_no_other_invalid_monetary_or_energy_pairings(self):
        """Sweep the whole table so the class can't reappear on a sibling."""
        for d in SENSOR_TYPES:
            if d.device_class == SensorDeviceClass.MONETARY:
                assert d.state_class in (None, SensorStateClass.TOTAL), d.key
            if d.device_class == SensorDeviceClass.ENERGY:
                assert d.state_class in (
                    SensorStateClass.TOTAL,
                    SensorStateClass.TOTAL_INCREASING,
                ), d.key


class TestRoiPaybackUnknown646:
    def test_default_is_none_not_zero(self):
        # 0.0 published as "0.0 years" — reading as already-paid-off on
        # installs with no savings history yet
        assert CostData().roi_payback_years is None

    def test_to_dict_carries_none_through(self):
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        data = SEMData()
        assert data.to_dict()["roi_payback_years"] is None
