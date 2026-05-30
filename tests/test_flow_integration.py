"""Tests for the time-integrated energy flow attribution (#282).

The legacy ``calculate_energy_flows`` used proportional allocation over
daily totals — credited solar to the EV even when the EV was unplugged,
because it only knew ``daily_solar`` and ``daily_ev`` ratios. A sunny
morning followed by a brief afternoon EV plug-in showed an inflated
flow_solar_to_ev_energy that didn't reflect reality.

The new ``integrate_energy_flows`` runs every cycle, integrating
``power_flows`` (already-correctly-attributed by ``calculate_power_flows``
based on the cycle's current demand) over time. Result: solar that
flowed to the grid at noon while the EV was idle stays counted as
solar_to_grid, never re-allocated to a later EV session.
"""
from datetime import date, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerFlows,
    PowerReadings,
)


class TestIntegrateEnergyFlows:
    """Time-integrated daily flow attribution."""

    def test_one_cycle_at_zero_ev_produces_zero_solar_to_ev(self):
        # Sun shining, no EV — solar_to_ev MUST stay 0.
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_grid = 5000.0  # 5 kW flowing to grid
        flows.solar_to_home = 500.0
        flows.solar_to_ev = 0.0
        result = fc.integrate_energy_flows(flows, interval_seconds=30)
        assert result.solar_to_ev == 0.0
        # The grid flow should be credited
        assert result.solar_to_grid > 0.04   # 5000 W * 30 s = 41.7 Wh = 0.042 kWh

    def test_integration_accumulates_kwh_correctly(self):
        # 10 cycles of 30 s @ 1 kW solar→ev = 5 minutes total = 0.083 kWh
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_ev = 1000.0  # 1 kW
        for _ in range(10):
            result = fc.integrate_energy_flows(flows, interval_seconds=30)
        # 1 kW * (10 * 30 / 3600) h = 0.0833 kWh
        assert abs(result.solar_to_ev - 0.0833) < 0.001

    def test_mixed_sources_attribute_independently(self):
        # 5 minutes (10 x 30 s) with simultaneous mixed flows
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_ev = 6000.0     # 6 kW direct sun
        flows.battery_to_ev = 4000.0   # 4 kW from battery
        flows.grid_to_ev = 0.0
        for _ in range(10):
            result = fc.integrate_energy_flows(flows, interval_seconds=30)
        # 6 kW * (300/3600) = 0.5 kWh ; 4 kW * (300/3600) = 0.333 kWh
        assert abs(result.solar_to_ev - 0.5) < 0.001
        assert abs(result.battery_to_ev - 0.333) < 0.005
        assert result.grid_to_ev == 0.0

    def test_legacy_proportional_allocation_diverges_from_integration(self):
        """Pin the bug-and-fix: with the EV unplugged in the morning and
        a brief afternoon session, the legacy ``calculate_energy_flows``
        credits solar to EV proportionally to daily totals — inflating the
        attribution. The new method does NOT.

        This is the user-reported scenario behind #282."""
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        fc = FlowCalculator()

        # Step 1: morning — 50 kWh solar export, no EV
        morning = PowerFlows()
        morning.solar_to_grid = 5000.0  # would integrate to 5 kWh per hour
        # 1 hour at 5 kW
        for _ in range(120):  # 120 * 30 s = 1 hour
            fc.integrate_energy_flows(morning, interval_seconds=30)

        # Step 2: afternoon EV session — only battery+grid to EV
        afternoon = PowerFlows()
        afternoon.solar_to_ev = 0.0           # solar already exported
        afternoon.battery_to_ev = 8000.0      # 8 kW from battery
        afternoon.grid_to_ev = 2000.0         # 2 kW from grid
        for _ in range(60):  # 30 min
            fc.integrate_energy_flows(afternoon, interval_seconds=30)

        integrated = fc.integrate_energy_flows(PowerFlows(), interval_seconds=0)
        # Integrated says solar→ev was zero — TRUE to physics.
        assert integrated.solar_to_ev == 0.0
        # Battery+grid took the EV load
        assert integrated.battery_to_ev > 3.9    # 8 kW * 0.5 h = 4 kWh
        assert integrated.grid_to_ev > 0.9       # 2 kW * 0.5 h = 1 kWh

        # Legacy method called with the SAME daily totals would inflate
        # solar→ev. Build EnergyTotals from the same integration:
        legacy = fc.calculate_energy_flows(EnergyTotals(
            daily_solar=5.0,           # the 1h export
            daily_grid_import=1.0,     # the EV grid sip
            daily_battery_discharge=4.0,  # the EV battery feed
            daily_home=0.0,
            daily_ev=5.0,              # total EV intake
            daily_battery_charge=0.0,
            daily_grid_export=4.99,    # almost all of the morning solar
        ))
        # The legacy proportional formula spreads solar across EV + export by
        # demand ratio (ev / (ev + export)) ≈ 5/(5+4.99) ≈ 0.5. So legacy
        # claims ~2.5 kWh solar→ev — fictional, the EV got 0 kWh of direct
        # solar in this scenario.
        assert legacy.solar_to_ev > 1.5  # legacy says > 1.5 kWh
        # And the new method says 0.
        assert integrated.solar_to_ev < 0.1


class TestFlowAccumulatorPersistence:
    """Persistence across HA restarts (#282)."""

    def test_get_state_snapshot_round_trips(self):
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_ev = 1000.0
        flows.battery_to_home = 500.0
        for _ in range(60):  # 30 min
            fc.integrate_energy_flows(flows, interval_seconds=30)

        snapshot = fc.get_flow_accumulator_state()
        # Snapshot has the date + the accumulated values
        assert "date" in snapshot
        assert "accumulators" in snapshot
        assert snapshot["accumulators"]["solar_to_ev"] > 0.4

        # Round-trip into a fresh calculator
        fc2 = FlowCalculator()
        fc2.restore_flow_accumulator_state(snapshot)
        flows_zero = PowerFlows()
        result = fc2.integrate_energy_flows(flows_zero, interval_seconds=0)
        # Restored values are present
        assert result.solar_to_ev > 0.4
        assert result.battery_to_home > 0.2

    def test_stale_snapshot_from_yesterday_is_dropped(self):
        # Build a snapshot dated yesterday — restore should ignore it so we
        # don't carry yesterday's numbers into today's flow_*_to_*_energy.
        fc = FlowCalculator()
        yesterday = (fc._current_date - timedelta(days=1)).isoformat()
        fc.restore_flow_accumulator_state({
            "date": yesterday,
            "accumulators": {"solar_to_ev": 99.0},
        })
        # Accumulator should remain empty
        assert fc._flow_accumulators.get("solar_to_ev", 0.0) == 0.0

    def test_malformed_snapshot_is_safely_ignored(self):
        fc = FlowCalculator()
        # Garbage shouldn't raise — just no-op restore.
        fc.restore_flow_accumulator_state(None)
        fc.restore_flow_accumulator_state({"date": "not-a-date"})
        fc.restore_flow_accumulator_state({"accumulators": "not-a-dict"})
        assert fc._flow_accumulators == {}


class TestDayRollover:
    def test_accumulators_clear_at_local_midnight(self, monkeypatch):
        from homeassistant.util import dt as dt_util

        # Day 1: accumulate something
        fc = FlowCalculator()
        flows = PowerFlows()
        flows.solar_to_ev = 1000.0
        fc.integrate_energy_flows(flows, interval_seconds=30)
        assert fc._flow_accumulators["solar_to_ev"] > 0

        # Advance to "tomorrow"
        original_now = dt_util.now
        tomorrow = original_now().replace(hour=0, minute=0, second=1) + timedelta(days=1)
        monkeypatch.setattr(dt_util, "now", lambda: tomorrow)

        # Next cycle should detect the rollover and clear
        fc.integrate_energy_flows(PowerFlows(), interval_seconds=30)
        # solar_to_ev cleared (zero accumulation in the new cycle since flows are 0)
        assert fc._flow_accumulators.get("solar_to_ev", 0.0) == 0.0
