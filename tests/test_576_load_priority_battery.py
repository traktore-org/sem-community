"""#576 — load priority above battery charging.

The Victron-style "loads/EV charge before the battery" rule: above the
reserve zone, power that would otherwise charge the home battery is made
available to higher-priority consumers (generic surplus loads in Phase 1,
the EV in Phase 2). The single gated quantity is
:func:`reclaimable_battery_w`; both control paths add the SAME number to
their surplus input, so the model has one definition and is fully
unit-testable without a coordinator.

Design: docs/superpowers/specs/2026-07-10-load-priority-above-battery-design.md
Plan:   docs/superpowers/plans/2026-07-10-load-priority-above-battery.md
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    reclaimable_battery_w,
)


@pytest.mark.unit
class TestReclaimableBatteryW:
    def test_disabled_returns_zero(self):
        # Toggle off → never reclaim (byte-identical to today).
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=False, battery_commanded=False) == 0.0

    def test_below_reserve_returns_zero(self):
        # SOC below the reserve zone → battery fills first.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=25, priority_soc=30,
            enabled=True, battery_commanded=False) == 0.0

    def test_commanded_charge_returns_zero(self):
        # Force/scheduled/arbitrage charge is honored — no reclaim.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=True, battery_commanded=True) == 0.0

    def test_above_reserve_reclaims_charge_power(self):
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=True, battery_commanded=False) == 2400.0

    def test_discharging_battery_reclaims_zero(self):
        # Negative charge power (battery discharging) is not reclaimable.
        assert reclaimable_battery_w(
            battery_charge_power=-1500, soc=85, priority_soc=30,
            enabled=True, battery_commanded=False) == 0.0

    def test_at_reserve_boundary_inclusive(self):
        # SOC exactly at the zone counts as above (>=), matching
        # charging_control's `soc >= battery_priority_soc`.
        assert reclaimable_battery_w(
            battery_charge_power=1000, soc=30, priority_soc=30,
            enabled=True, battery_commanded=False) == 1000.0
