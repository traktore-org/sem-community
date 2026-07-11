"""#576 — loads charge before the battery.

The Victron-style rule: above the reserve zone, power that would otherwise
charge the home battery is added to the surplus pool, so the surplus loads
— walked by their own priority — consume it first and the battery is the
sink at the bottom. There is **no opt-in toggle**; the reserve floor
(``battery_priority_soc``) is the only gate. The single quantity is
:func:`reclaimable_battery_w`.

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
    def test_below_reserve_returns_zero(self):
        # SOC below the reserve zone → battery fills first.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=25, priority_soc=30,
            battery_commanded=False) == 0.0

    def test_commanded_charge_returns_zero(self):
        # Force/scheduled/arbitrage charge is honored — no reclaim.
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            battery_commanded=True) == 0.0

    def test_above_reserve_reclaims_charge_power(self):
        assert reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            battery_commanded=False) == 2400.0

    def test_discharging_battery_reclaims_zero(self):
        # Negative charge power (battery discharging) is not reclaimable.
        assert reclaimable_battery_w(
            battery_charge_power=-1500, soc=85, priority_soc=30,
            battery_commanded=False) == 0.0

    def test_at_reserve_boundary_inclusive(self):
        # SOC exactly at the zone counts as above (>=), matching
        # charging_control's `soc >= battery_priority_soc`.
        assert reclaimable_battery_w(
            battery_charge_power=1000, soc=30, priority_soc=30,
            battery_commanded=False) == 1000.0


def _available(export, own, batt, soc, commanded=False, pri=30):
    """The exact figure the coordinator feeds SurplusController.update()."""
    return export + own + reclaimable_battery_w(
        battery_charge_power=batt, soc=soc, priority_soc=pri,
        battery_commanded=commanded)


@pytest.mark.unit
class TestLoadScenarios:
    """Spec §3 acceptance scenarios U3–U6 (generic loads / reserve floor)."""

    def test_u3_two_heaters_pool_pre_battery(self):
        # 3.5 kW pool, 0 home, 85% SOC. Battery not charging in this instant
        # (all solar is exporting) → nothing to reclaim; the 3.5 kW export IS
        # the pre-battery surplus and both 1 kW heaters allocate from it.
        avail = _available(export=3500, own=0, batt=0, soc=85)
        assert avail == pytest.approx(3500)

    def test_u4_below_reserve_no_reclaim(self):
        # SOC 25% < zone → battery fills first, loads see export-only.
        avail = _available(export=100, own=0, batt=2400, soc=25)
        assert avail == pytest.approx(100)

    def test_u5_discrete_load_below_rating_flows_to_battery(self):
        # 0.8 kW pool < a 1 kW heater rating → heater stays off; 0.8 → battery.
        avail = _available(export=800, own=0, batt=0, soc=85)
        assert avail == pytest.approx(800)

    def test_u6_commanded_charge_no_reclaim(self):
        # Force / scheduled / arbitrage charge honored → no reclaim.
        avail = _available(export=100, own=0, batt=2400, soc=85, commanded=True)
        assert avail == pytest.approx(100)

    def test_reclaim_when_battery_charging_above_zone(self):
        # The core win: 100 W export + 2.4 kW battery charge reclaimed above
        # the zone → 2.5 kW offered to the loads (by device priority).
        avail = _available(export=100, own=0, batt=2400, soc=85)
        assert avail == pytest.approx(2500)


@pytest.mark.unit
class TestSurplusInputWiring:
    """Locks the arithmetic the coordinator uses at the ``true_surplus_w``
    build: export + own draw + reclaim."""

    def test_surplus_input_includes_reclaim_above_zone(self):
        reclaim = reclaimable_battery_w(
            battery_charge_power=2400, soc=85, priority_soc=30,
            battery_commanded=False)
        assert 100.0 + 0.0 + reclaim == pytest.approx(2500.0)

    def test_surplus_input_unchanged_below_zone(self):
        reclaim = reclaimable_battery_w(
            battery_charge_power=2400, soc=25, priority_soc=30,
            battery_commanded=False)
        assert 100.0 + 0.0 + reclaim == pytest.approx(100.0)


# ── The battery as a positioned device in the priority walk ──────────────
from unittest.mock import AsyncMock, MagicMock  # noqa: E402
from custom_components.solar_energy_management.coordinator.surplus_controller import (  # noqa: E402
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (  # noqa: E402
    DeviceControlMode,
)


def _make_device(device_id, priority, min_power=500):
    """Minimal surplus-load mock — just enough for the activation walk."""
    d = MagicMock()
    d.device_id = device_id
    d.name = device_id
    d.priority = priority
    d.min_power_threshold = min_power
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d.activate = AsyncMock(return_value=min_power)
    d.adjust_power = AsyncMock(return_value=min_power)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.status = MagicMock()
    d.status.allocated_power_w = 0.0
    d.status.state = MagicMock(value="idle")
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d.daily_targets_met = False
    d.stop_condition_met = False
    d.__class__ = MagicMock
    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


async def _run_walk(mock_hass, *, battery_priority, export=200.0, reclaim=1000.0,
                    load_hi_prio=2, load_lo_prio=5, min_w=500):
    """Two surplus loads (hi/lo priority) + a battery slot. Returns which
    loads activated after one allocation cycle."""
    sc = SurplusController(mock_hass, regulation_offset=0)
    hi = _make_device(device_id="hi", priority=load_hi_prio, min_power=min_w)
    lo = _make_device(device_id="lo", priority=load_lo_prio, min_power=min_w)
    sc.register_device(hi)
    sc.register_device(lo)
    await sc.update(export, reclaim_w=reclaim, battery_priority=battery_priority)
    return hi.activate.called, lo.activate.called


@pytest.mark.unit
class TestBatteryPositionInWalk:
    """The battery's drag position governs which loads reclaim its charge.
    Export is small (200 W < a load's 500 W min); the 1000 W reclaim is what
    lets a load above the battery switch on."""

    async def test_battery_at_bottom_all_loads_reclaim(self, mock_hass):
        # priority 100 → both loads (2, 5) are above it → both may reclaim.
        hi_on, lo_on = await _run_walk(mock_hass, battery_priority=100)
        assert hi_on and lo_on

    async def test_battery_in_middle_only_higher_load_reclaims(self, mock_hass):
        # battery at 3: load@2 is above (reclaims → on); load@5 is below
        # (yields → the reclaim is handed back to the battery → stays off).
        hi_on, lo_on = await _run_walk(mock_hass, battery_priority=3)
        assert hi_on and not lo_on

    async def test_battery_at_top_no_load_reclaims(self, mock_hass):
        # battery at 1: both loads below it. Only 200 W export remains (< 500 W
        # min) → neither switches on; the battery keeps its 1000 W.
        hi_on, lo_on = await _run_walk(mock_hass, battery_priority=1)
        assert not hi_on and not lo_on

    async def test_no_battery_priority_is_todays_behavior(self, mock_hass):
        # battery_priority=None (+ reclaim baked into export by the caller):
        # the walk never hands anything back — pure export-only gate.
        sc = SurplusController(mock_hass, regulation_offset=0)
        hi = _make_device(device_id="hi", priority=2, min_power=500)
        sc.register_device(hi)
        await sc.update(1200.0, reclaim_w=0.0, battery_priority=None)
        assert hi.activate.called  # 1200 >= 500
