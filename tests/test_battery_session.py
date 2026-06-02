"""Tests for battery session tracking.

Verifies charge/discharge session lifecycle, source attribution,
cost/savings calculation, and hysteresis-based session end detection.
"""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings, PowerFlows, BatterySessionData,
)


def _make_coordinator():
    """Create a minimal coordinator mock for battery session tracking."""
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator

    with patch.object(SEMCoordinator, '__init__', return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
        coord.config = {
            "update_interval": 10,
            "electricity_import_rate": 0.30,
        }
        # Post-#351 L1, energy accumulators integrate against the
        # actual update interval (DataUpdateCoordinator.update_interval)
        # not the requested one in config. Mirror config here.
        coord.update_interval = timedelta(seconds=10)
        coord._battery_session = BatterySessionData()
        coord._battery_session_idle_count = 0
        # Mock energy calculator with live import rate (used since #223 fix)
        coord._energy_calculator = type('MockCalc', (), {'_import_rate': 0.30})()
        return coord


class TestBatterySessionStart:
    """Test session start conditions."""

    def test_charge_session_starts(self):
        """Charging above 50W starts a charge session."""
        coord = _make_coordinator()
        power = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=400, grid_to_battery=100)

        coord._update_battery_session_tracking(power, flows)

        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "charge"
        assert coord._battery_session.start_time is not None

    def test_discharge_session_starts(self):
        """Discharging above 50W starts a discharge session."""
        coord = _make_coordinator()
        power = PowerReadings(battery_charge_power=0, battery_discharge_power=800)
        flows = PowerFlows()

        coord._update_battery_session_tracking(power, flows)

        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "discharge"

    def test_no_session_below_threshold(self):
        """Power below 50W does not start a session."""
        coord = _make_coordinator()
        power = PowerReadings(battery_charge_power=30, battery_discharge_power=10)
        flows = PowerFlows()

        coord._update_battery_session_tracking(power, flows)

        assert coord._battery_session.active is False
        assert coord._battery_session.session_type == "idle"


class TestBatterySessionEnd:
    """Test session end via hysteresis."""

    def test_session_ends_after_3_idle_cycles(self):
        """Session ends after 3 consecutive idle cycles."""
        coord = _make_coordinator()
        # Start a charge session
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=500)
        coord._update_battery_session_tracking(power_active, flows)
        assert coord._battery_session.active is True

        # 3 idle cycles
        power_idle = PowerReadings(battery_charge_power=0, battery_discharge_power=0)
        for i in range(3):
            coord._update_battery_session_tracking(power_idle, PowerFlows())

        assert coord._battery_session.active is False

    def test_session_survives_1_idle_cycle(self):
        """Session survives 1 idle cycle (hysteresis)."""
        coord = _make_coordinator()
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=500)
        coord._update_battery_session_tracking(power_active, flows)

        # 1 idle cycle
        power_idle = PowerReadings(battery_charge_power=0, battery_discharge_power=0)
        coord._update_battery_session_tracking(power_idle, PowerFlows())

        assert coord._battery_session.active is True
        assert coord._battery_session_idle_count == 1

    def test_idle_counter_resets_on_active(self):
        """Idle counter resets when power returns."""
        coord = _make_coordinator()
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=500)
        coord._update_battery_session_tracking(power_active, flows)

        # 2 idle cycles (not enough to end)
        power_idle = PowerReadings(battery_charge_power=0, battery_discharge_power=0)
        coord._update_battery_session_tracking(power_idle, PowerFlows())
        coord._update_battery_session_tracking(power_idle, PowerFlows())
        assert coord._battery_session_idle_count == 2

        # Power returns — counter resets
        coord._update_battery_session_tracking(power_active, flows)
        assert coord._battery_session_idle_count == 0
        assert coord._battery_session.active is True


class TestBatterySessionDirectionChange:
    """Test session handling on charge/discharge direction switch."""

    def test_direction_change_ends_session(self):
        """Switching from charge to discharge ends current session and starts new."""
        coord = _make_coordinator()

        # Start charge session
        power_charge = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        coord._update_battery_session_tracking(power_charge, PowerFlows(solar_to_battery=500))
        assert coord._battery_session.session_type == "charge"

        # Switch to discharge
        power_discharge = PowerReadings(battery_charge_power=0, battery_discharge_power=800)
        coord._update_battery_session_tracking(power_discharge, PowerFlows())

        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "discharge"
        # Energy should be from the new session (near zero), not carried over
        assert coord._battery_session.energy_kwh < 0.01


class TestBatterySessionEnergyAccumulation:
    """Test energy and cost/savings accumulation."""

    def test_charge_energy_accumulation(self):
        """Charge session accumulates energy from solar and grid flows."""
        coord = _make_coordinator()
        power = PowerReadings(battery_charge_power=3600, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=2400, grid_to_battery=1200)

        # 10 cycles × 10s interval = 100s
        for _ in range(10):
            coord._update_battery_session_tracking(power, flows)

        session = coord._battery_session
        # 3600W × 100s / 3600 / 1000 = 0.1 kWh total
        assert abs(session.energy_kwh - 0.1) < 0.01
        # Solar: 2400W × 100s / 3600 / 1000 = 0.0667 kWh
        assert abs(session.solar_energy_kwh - 0.0667) < 0.005
        # Grid: 1200W × 100s / 3600 / 1000 = 0.0333 kWh
        assert abs(session.grid_energy_kwh - 0.0333) < 0.005
        # Solar share: 66.7%
        assert abs(session.solar_share_pct - 66.7) < 1.0

    def test_charge_cost_calculation(self):
        """Charge session cost = grid energy × import rate."""
        coord = _make_coordinator()
        coord.config["electricity_import_rate"] = 0.30
        power = PowerReadings(battery_charge_power=3600, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=0, grid_to_battery=3600)

        # 10 cycles × 10s = 100s → 0.1 kWh from grid
        for _ in range(10):
            coord._update_battery_session_tracking(power, flows)

        # Cost: 0.1 kWh × 0.30 = 0.03
        assert abs(coord._battery_session.cost - 0.03) < 0.005

    def test_discharge_savings_calculation(self):
        """Discharge session savings = energy × import rate (avoided grid)."""
        coord = _make_coordinator()
        coord.config["electricity_import_rate"] = 0.30
        power = PowerReadings(battery_charge_power=0, battery_discharge_power=3600)
        flows = PowerFlows()

        # 10 cycles × 10s = 100s → 0.1 kWh
        for _ in range(10):
            coord._update_battery_session_tracking(power, flows)

        # Savings: 0.1 kWh × 0.30 = 0.03
        assert abs(coord._battery_session.savings - 0.03) < 0.005

    def test_100_percent_solar_charge(self):
        """Charge fully from solar → 100% solar share, zero cost."""
        coord = _make_coordinator()
        power = PowerReadings(battery_charge_power=2000, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=2000, grid_to_battery=0)

        for _ in range(5):
            coord._update_battery_session_tracking(power, flows)

        session = coord._battery_session
        assert session.solar_share_pct > 99.0
        assert session.cost < 0.001


class TestBatterySessionToDict:
    """Test battery session data in SEMData.to_dict()."""

    def test_battery_session_in_to_dict(self):
        """Battery session fields appear in to_dict output."""
        from custom_components.solar_energy_management.coordinator.types import SEMData

        data = SEMData()
        data.battery_session = BatterySessionData(
            active=True,
            session_type="charge",
            energy_kwh=1.5,
            solar_share_pct=80.0,
            cost=0.09,
            savings=0.0,
            duration_minutes=30.0,
            avg_power_w=3000.0,
        )

        result = data.to_dict()
        assert result["battery_session_active"] is True
        assert result["battery_session_type"] == "charge"
        assert result["battery_session_energy"] == 1.5
        assert result["battery_session_solar_share"] == 80.0
        assert result["battery_session_cost"] == 0.09
        assert result["battery_session_savings"] == 0.0
        assert result["battery_session_duration"] == 30.0
        assert result["battery_session_avg_power"] == 3000.0

    def test_idle_session_defaults(self):
        """Idle session has sensible defaults."""
        from custom_components.solar_energy_management.coordinator.types import SEMData

        data = SEMData()
        result = data.to_dict()
        assert result["battery_session_active"] is False
        assert result["battery_session_type"] == "idle"
        assert result["battery_session_energy"] == 0
