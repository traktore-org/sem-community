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
        coord._battery_session_opposite_count = 0
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

    def test_session_ends_after_idle_window(self):
        """Session ends after 18 consecutive idle cycles (~3 min)."""
        coord = _make_coordinator()
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=500)
        coord._update_battery_session_tracking(power_active, flows)
        assert coord._battery_session.active is True

        # 18 idle cycles → ends
        power_idle = PowerReadings(battery_charge_power=0, battery_discharge_power=0)
        for _ in range(18):
            coord._update_battery_session_tracking(power_idle, PowerFlows())

        assert coord._battery_session.active is False

    def test_session_survives_short_idle_gap(self):
        """A brief gap (well under the idle window) keeps the session
        alive — the sunset/cloud-transit case that produced the
        original "1 hour discharge → 2 min session" bug."""
        coord = _make_coordinator()
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=500)
        coord._update_battery_session_tracking(power_active, flows)

        # 5 idle cycles (~50 s) — well below the 18-cycle threshold
        power_idle = PowerReadings(battery_charge_power=0, battery_discharge_power=0)
        for _ in range(5):
            coord._update_battery_session_tracking(power_idle, PowerFlows())

        assert coord._battery_session.active is True
        assert coord._battery_session_idle_count == 5

    def test_idle_counter_resets_on_active(self):
        """Idle counter resets when power returns above the dead-band."""
        coord = _make_coordinator()
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        flows = PowerFlows(solar_to_battery=500)
        coord._update_battery_session_tracking(power_active, flows)

        # 10 idle cycles (not enough to end — limit is 18)
        power_idle = PowerReadings(battery_charge_power=0, battery_discharge_power=0)
        for _ in range(10):
            coord._update_battery_session_tracking(power_idle, PowerFlows())
        assert coord._battery_session_idle_count == 10

        # Power returns above the 200 W dead-band — counter resets
        coord._update_battery_session_tracking(power_active, flows)
        assert coord._battery_session_idle_count == 0
        assert coord._battery_session.active is True

    def test_dead_band_idles_low_power(self):
        """Power below the 200 W dead-band counts as idle even though
        > 0, because that's the inverter's micro-rebalance regime."""
        coord = _make_coordinator()
        power_active = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        coord._update_battery_session_tracking(power_active, PowerFlows(solar_to_battery=500))

        # 150 W is below the new 200 W dead-band.
        power_low = PowerReadings(battery_charge_power=150, battery_discharge_power=0)
        coord._update_battery_session_tracking(power_low, PowerFlows())
        # Session still active, idle counter ticks up.
        assert coord._battery_session.active is True
        assert coord._battery_session_idle_count == 1


class TestBatterySessionDirectionChange:
    """Direction-change hysteresis — single-cycle blips don't end the
    session; sustained N-cycle reversal does (#TBD)."""

    def test_single_cycle_blip_does_not_end_session(self):
        """The user's screenshot scenario: a continuous discharge that
        gets a single cycle of +500 W charge during a sunset transient.
        Session must survive."""
        coord = _make_coordinator()
        power_discharge = PowerReadings(battery_charge_power=0, battery_discharge_power=1100)
        coord._update_battery_session_tracking(power_discharge, PowerFlows())
        assert coord._battery_session.session_type == "discharge"

        # One cycle of charge (the transient).
        power_blip = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        coord._update_battery_session_tracking(power_blip, PowerFlows(solar_to_battery=500))
        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "discharge"
        assert coord._battery_session_opposite_count == 1

        # Back to discharge — opposite counter resets.
        coord._update_battery_session_tracking(power_discharge, PowerFlows())
        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "discharge"
        assert coord._battery_session_opposite_count == 0

    def test_sustained_opposite_direction_ends_session(self):
        """Three consecutive cycles of opposite direction = real flip.
        Old session ends, new one starts on the next active cycle."""
        coord = _make_coordinator()
        power_discharge = PowerReadings(battery_charge_power=0, battery_discharge_power=1100)
        coord._update_battery_session_tracking(power_discharge, PowerFlows())
        assert coord._battery_session.session_type == "discharge"

        # 3 charge cycles in a row → flip after the third.
        power_charge = PowerReadings(battery_charge_power=500, battery_discharge_power=0)
        for _ in range(3):
            coord._update_battery_session_tracking(power_charge, PowerFlows(solar_to_battery=500))

        # After 3 opposite cycles the old session ends + a new one
        # starts on the same cycle (next call), now as charge.
        coord._update_battery_session_tracking(power_charge, PowerFlows(solar_to_battery=500))
        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "charge"


class TestBatterySessionRealWorld:
    """Real-world scenarios from the #TBD investigation."""

    def test_steady_one_hour_discharge_keeps_one_session(self):
        """User's reported case: 1 hour of steady 1.1 kW discharge
        with no fluctuations should produce one continuous session."""
        coord = _make_coordinator()
        power = PowerReadings(battery_charge_power=0, battery_discharge_power=1100)

        # 1 hour at 10 s update interval = 360 cycles.
        for _ in range(360):
            coord._update_battery_session_tracking(power, PowerFlows())

        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "discharge"
        # Energy: 1100 W × 3600 s / 3600 / 1000 = 1.1 kWh.
        assert abs(coord._battery_session.energy_kwh - 1.1) < 0.05

    def test_sunset_transient_keeps_session_alive(self):
        """Sunset: solar tails off, battery starts discharging, has
        occasional brief charge blips during inverter rebalance.
        Session should remain a single continuous session."""
        coord = _make_coordinator()
        power_discharge = PowerReadings(battery_charge_power=0, battery_discharge_power=800)
        power_blip_charge = PowerReadings(battery_charge_power=300, battery_discharge_power=0)

        # 10 minutes of discharge
        for _ in range(60):
            coord._update_battery_session_tracking(power_discharge, PowerFlows())

        # Single-cycle blip of charge (inverter rebalance)
        coord._update_battery_session_tracking(power_blip_charge, PowerFlows(solar_to_battery=300))

        # 10 more minutes of discharge
        for _ in range(60):
            coord._update_battery_session_tracking(power_discharge, PowerFlows())

        # One continuous session, never flipped.
        assert coord._battery_session.active is True
        assert coord._battery_session.session_type == "discharge"


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
