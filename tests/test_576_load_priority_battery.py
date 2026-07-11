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


@pytest.mark.unit
class TestConfigKey:
    def test_config_default_is_off(self):
        from custom_components.solar_energy_management.const import (
            DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY,
        )
        assert DEFAULT_LOAD_PRIORITY_ABOVE_BATTERY is False


@pytest.mark.unit
class TestSurplusInputWiring:
    """Locks the exact arithmetic the coordinator uses at the
    ``true_surplus_w`` build (coordinator.py:3016): export + own draw +
    reclaim."""

    def test_surplus_input_includes_reclaim_above_zone(self):
        grid_export, own_draw, batt_charge, soc = 100.0, 0.0, 2400.0, 85.0
        reclaim = reclaimable_battery_w(
            battery_charge_power=batt_charge, soc=soc, priority_soc=30,
            enabled=True, battery_commanded=False)
        available = grid_export + own_draw + reclaim
        assert available == pytest.approx(2500.0)  # 100 export + 2400 reclaimed

    def test_surplus_input_unchanged_when_disabled(self):
        reclaim = reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            enabled=False, battery_commanded=False)
        assert 100.0 + 0.0 + reclaim == pytest.approx(100.0)  # today's value


def _available(export, own, batt, soc, enabled, commanded=False, pri=30):
    """The exact figure the coordinator feeds SurplusController.update()."""
    return export + own + reclaimable_battery_w(
        battery_charge_power=batt, soc=soc, priority_soc=pri,
        enabled=enabled, battery_commanded=commanded)


@pytest.mark.unit
class TestLoadScenarios:
    """Spec §3 acceptance scenarios U3–U6 (generic loads / reserve floor)."""

    def test_u3_two_heaters_pool_pre_battery(self):
        # 3.5 kW pool, 0 home, 85% SOC. Battery not charging in this instant
        # (all solar is exporting) → nothing to reclaim; the 3.5 kW export IS
        # the pre-battery surplus and both 1 kW heaters allocate from it.
        avail = _available(export=3500, own=0, batt=0, soc=85, enabled=True)
        assert avail == pytest.approx(3500)

    def test_u4_below_reserve_no_reclaim(self):
        # SOC 25% < zone → battery fills first, loads see export-only.
        avail = _available(export=100, own=0, batt=2400, soc=25, enabled=True)
        assert avail == pytest.approx(100)

    def test_u5_discrete_load_below_rating_flows_to_battery(self):
        # 0.8 kW pool < a 1 kW heater rating → heater stays off; 0.8 → battery.
        avail = _available(export=800, own=0, batt=0, soc=85, enabled=True)
        assert avail == pytest.approx(800)

    def test_u6_commanded_charge_no_reclaim(self):
        # Force / scheduled / arbitrage charge honored → no reclaim.
        avail = _available(export=100, own=0, batt=2400, soc=85,
                           enabled=True, commanded=True)
        assert avail == pytest.approx(100)

    def test_u_reclaim_when_battery_charging_above_zone(self):
        # The core loads win: 100 W export + 2.4 kW battery charge reclaimed
        # above the zone → 2.5 kW offered to the loads.
        avail = _available(export=100, own=0, batt=2400, soc=85, enabled=True)
        assert avail == pytest.approx(2500)
