"""#938 — a Solar-only load ran at night on the battery's GRID charge.

alexmc1510 (Huawei SUN2000 + LUNA, Spain, 2.0 → 2.1.0-beta.9): a pool pump
in mode "Solar only", target 4 h/day, was switched on by SEM at 01:29,
again at 01:45 after a manual off, and off at 06:03 — "4.3/4 h on solar
today" with the sun at 0 W the whole time.

The mechanism: ``SurplusController.update()`` allocates from
``surplus + reclaim``. The export surplus is pinned ``≤ solar`` since #620
(the @onkelfu night report) — but the #576 reclaim (battery-charge power a
load above the battery may take instead) joined the pool BELOW that bound,
and read the WHOLE charge power as solar. A pack charging from the grid at
night (an inverter TOU window — nothing SEM commanded, so the U6 "commanded
battery is honoured" gate did not apply) is positive charge power with the
meter behind it, not the sun. The EV side of the same shape was closed in
#899 (the redirect); this is the loads' sibling.

Two independent ceilings, both physics:

1. ``reclaimable_battery_w(grid_import_w=…)`` — only the share of the charge
   the meter is NOT importing is solar-funded (``charge − import``).
2. ``solar_bounded_reclaim`` — the pool as a whole never exceeds the sun
   (``surplus + reclaim ≤ solar``), the #620 invariant on the sum instead of
   on one addend.

Plus a source-level guard so the reclaim cannot reach ``update()`` unbounded
again, whichever way the coordinator block is next refactored.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    reclaimable_battery_w,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    solar_bounded_reclaim,
    solar_bounded_surplus,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode

_COORD = Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"


# ── 1. the solar-funded share ────────────────────────────────────────────


@pytest.mark.unit
class TestReclaimIsTheSolarFundedShare:
    def test_night_grid_charge_reclaims_nothing(self):
        # The reporter's night: pack charging 3 kW, meter importing house + pack.
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=45.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=3400.0,
        ) == 0.0

    def test_dawn_tou_charge_reclaims_only_what_the_sun_funds(self):
        # 07:30, valle window still open: sun 800 W, house 300 W, pack 3 kW,
        # meter imports 2.5 kW → the sun funds 500 W of the charge, no more.
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=45.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=2500.0,
        ) == pytest.approx(500.0)

    def test_solar_charge_with_no_import_is_the_576_win_unchanged(self):
        # The core #576 case: 2.4 kW going into the pack from the sun, meter
        # at 0 import → all of it is on the table for a load above the battery.
        assert reclaimable_battery_w(
            battery_charge_power=2400.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=0.0,
        ) == pytest.approx(2400.0)

    def test_default_import_is_zero_so_old_callers_keep_their_answer(self):
        assert reclaimable_battery_w(
            battery_charge_power=2400.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False,
        ) == pytest.approx(2400.0)

    def test_negative_or_none_import_reads_as_zero(self):
        # An export figure (or a None from a dark meter) must not ADD to the
        # reclaim — the term only ever takes away.
        for imp in (-500.0, None):
            assert reclaimable_battery_w(
                battery_charge_power=1000.0, soc=60.0, priority_soc=30.0,
                battery_commanded=False, grid_import_w=imp,
            ) == pytest.approx(1000.0)

    def test_commanded_and_below_reserve_still_zero(self):
        # The #576 gates keep precedence — the import term never re-opens them.
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=True, grid_import_w=0.0,
        ) == 0.0
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=20.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=0.0,
        ) == 0.0


# ── 2. the pool never exceeds the sun ────────────────────────────────────


@pytest.mark.unit
class TestSolarBoundedReclaim:
    def test_night_pins_the_reclaim_to_zero(self):
        # Sun 0 W, export surplus 0 W: whatever the pack is drawing, none of it
        # is surplus. This alone closes the reporter's night even with a dark
        # grid meter (import read as 0 → ceiling 1 is inert).
        assert solar_bounded_reclaim(3000.0, surplus_w=0.0, solar_w=0.0) == 0.0

    def test_day_with_room_passes_through(self):
        assert solar_bounded_reclaim(1800.0, surplus_w=700.0, solar_w=3000.0) == 1800.0

    def test_pool_is_clipped_to_the_sun(self):
        # 400 W export surplus + 3 kW "reclaim" with 1 kW of sun → 600 W is all
        # the sun has left once the export half is counted.
        assert solar_bounded_reclaim(3000.0, surplus_w=400.0, solar_w=1000.0) == 600.0

    def test_surplus_already_at_the_sun_leaves_nothing(self):
        assert solar_bounded_reclaim(500.0, surplus_w=1000.0, solar_w=1000.0) == 0.0

    def test_no_solar_reading_skips_the_cap_like_620(self):
        assert solar_bounded_reclaim(1500.0, surplus_w=0.0, solar_w=None) == 1500.0

    def test_negative_or_none_reclaim_is_zero(self):
        assert solar_bounded_reclaim(-200.0, surplus_w=0.0, solar_w=5000.0) == 0.0
        assert solar_bounded_reclaim(None, surplus_w=0.0, solar_w=5000.0) == 0.0

    def test_invariant_holds_across_a_sweep(self):
        # surplus + bounded_reclaim ≤ solar, for every combination.
        for solar in (0.0, 300.0, 1000.0, 5000.0):
            for surplus in (0.0, 200.0, 1000.0):
                s = solar_bounded_surplus(grid_export_w=surplus, active_draw_w=0.0, solar_w=solar)
                for reclaim in (0.0, 500.0, 3000.0):
                    r = solar_bounded_reclaim(reclaim, surplus_w=s, solar_w=solar)
                    assert s + r <= solar + 1e-9, (solar, surplus, reclaim)
                    assert r >= 0.0


# ── 3. the walk: the pump stays off at night, and still runs by day ──────


def _solar_only_load(device_id="pump", priority=1, min_power=713):
    """A switch load in mode Surplus with NO battery opt-ins — the dashboard's
    "Solar only" (no Tier-1 assist, no overnight battery, no cheap-hours grid)."""
    d = MagicMock()
    d.device_id = device_id
    d.name = device_id
    d.priority = priority
    d.min_power_threshold = min_power
    d.rated_power = min_power
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = False
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = False
    d.top_up_policy = "solar_only"
    d.needs_offpeak_activation = True   # has a deficit — must NOT matter here
    d.has_runtime_deficit = True
    d.activate = AsyncMock(return_value=min_power)
    d.adjust_power = AsyncMock(return_value=min_power)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.status = MagicMock()
    d.status.allocated_power_w = 0.0
    d.status.state = MagicMock(value="idle")
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.comfort_state = ""
    d.__class__ = MagicMock

    async def _deact():
        d.is_active = False
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


def _reporter_night():
    """The coordinator's two-line pipeline for the reporter's night readings:
    sun 0 W, meter importing 3.4 kW, pack charging 3 kW, SoC above reserve."""
    surplus = solar_bounded_surplus(grid_export_w=0.0, active_draw_w=0.0, solar_w=0.0)
    raw = reclaimable_battery_w(
        battery_charge_power=3000.0, soc=45.0, priority_soc=30.0,
        battery_commanded=False, grid_import_w=3400.0,
    )
    return surplus, raw, solar_bounded_reclaim(raw, surplus_w=surplus, solar_w=0.0)


@pytest.mark.unit
class TestNightWalk:
    async def test_the_unbounded_reclaim_would_have_started_the_pump(self, mock_hass):
        # Pin the failure, so the fix below is not a vacuous pass: feed the
        # walk the pre-#938 pool (raw charge power as reclaim) and the
        # Solar-only pump switches on with the sun at 0 W.
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _solar_only_load()
        sc.register_device(pump)
        await sc.update(0.0, reclaim_w=3000.0, battery_priority=100, is_night=True)
        assert pump.activate.called

    async def test_bounded_pipeline_keeps_the_pump_off(self, mock_hass):
        surplus, raw, reclaim = _reporter_night()
        assert raw == 0.0 and reclaim == 0.0 and surplus == 0.0
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _solar_only_load()
        sc.register_device(pump)
        for _ in range(4):  # past the median-of-3 + EMA warm-up
            await sc.update(surplus, reclaim_w=reclaim, battery_priority=100,
                            battery_soc=45.0, battery_reserve_soc=10.0,
                            is_night=True)
        assert not pump.activate.called

    async def test_dark_meter_night_is_still_closed_by_the_solar_ceiling(self, mock_hass):
        # Grid sensor dark → import read as 0 → ceiling 1 inert. The sun is
        # still 0 W, so ceiling 2 pins the pool alone.
        surplus = solar_bounded_surplus(grid_export_w=0.0, active_draw_w=0.0, solar_w=0.0)
        raw = reclaimable_battery_w(
            battery_charge_power=3000.0, soc=45.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=0.0,
        )
        assert raw == 3000.0
        reclaim = solar_bounded_reclaim(raw, surplus_w=surplus, solar_w=0.0)
        assert reclaim == 0.0
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _solar_only_load()
        sc.register_device(pump)
        await sc.update(surplus, reclaim_w=reclaim, battery_priority=100, is_night=True)
        assert not pump.activate.called

    async def test_running_pump_is_stopped_when_the_night_pool_is_empty(self, mock_hass):
        # The 01:39 restart case: the pump is ON (adopted after the upgrade)
        # and the pool is 0 → the deficit LIFO ends it; nothing re-arms it.
        surplus, _raw, reclaim = _reporter_night()
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _solar_only_load()
        pump.is_active = True
        pump._sem_owned = True
        pump.get_current_consumption = MagicMock(return_value=713.0)
        pump.can_deactivate = MagicMock(return_value=True)
        sc.register_device(pump)
        for _ in range(4):
            await sc.update(surplus, reclaim_w=reclaim, battery_priority=100, is_night=True)
        assert pump.deactivate.called
        assert not pump.activate.called

    async def test_daytime_solar_charge_is_still_reclaimed(self, mock_hass):
        # The #576 promise survives: sun 3 kW, 100 W export, pack taking
        # 2.4 kW from the sun, no import → the pump above the battery runs.
        surplus = solar_bounded_surplus(grid_export_w=100.0, active_draw_w=0.0, solar_w=3000.0)
        raw = reclaimable_battery_w(
            battery_charge_power=2400.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=0.0,
        )
        reclaim = solar_bounded_reclaim(raw, surplus_w=surplus, solar_w=3000.0)
        assert reclaim == pytest.approx(2400.0)
        sc = SurplusController(mock_hass, regulation_offset=0)
        pump = _solar_only_load()
        sc.register_device(pump)
        await sc.update(surplus, reclaim_w=reclaim, battery_priority=100, is_night=False)
        assert pump.activate.called


# ── 4. the guard: the reclaim cannot reach update() unbounded ────────────


def _surplus_block_calls(tree: ast.Module):
    """Every Call in coordinator.py, with the assignments in scope, keyed by
    the callee's dotted name."""
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            calls.append(node)
    return calls


def _callee(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return ast.unparse(f)
    return ""


def _kw(node: ast.Call, name: str):
    for kw in node.keywords:
        if kw.arg == name:
            return kw.value
    return None


@pytest.mark.unit
class TestCoordinatorWiringGuard:
    """Source-level: the value handed to ``_surplus_controller.update(reclaim_w=…)``
    must be the result of ``solar_bounded_reclaim``, and the reclaim itself
    must carry the meter's import. A refactor that drops either ceiling
    fails here, before it fails on somebody's pool pump."""

    def setup_method(self):
        self.tree = ast.parse(_COORD.read_text(encoding="utf-8"))
        self.calls = _surplus_block_calls(self.tree)

    def _enclosing_function(self, target: ast.AST) -> ast.AST:
        """The (async) def that contains ``target`` — assignments are resolved
        inside it only, so a same-named local elsewhere (the trace display
        reads its own ``reclaim_w``) cannot vouch for, or fail, this site."""
        best = None
        for node in ast.walk(self.tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= target.lineno <= (node.end_lineno or node.lineno):
                    if best is None or node.lineno > best.lineno:
                        best = node
        assert best is not None, "update() call site is not inside a function"
        return best

    def _assignments_of(self, name: str, scope: ast.AST):
        out = []
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == name:
                        out.append(node.value)
        return out

    def test_update_receives_a_solar_bounded_reclaim(self):
        updates = [c for c in self.calls
                   if _callee(c).endswith("_surplus_controller.update")]
        assert len(updates) == 1, "expected exactly one surplus-controller update() call site"
        val = _kw(updates[0], "reclaim_w")
        assert isinstance(val, ast.Name), "reclaim_w must be a named value, not an expression"
        sources = self._assignments_of(val.id, self._enclosing_function(updates[0]))
        assert sources, f"{val.id} is never assigned in the update() call's function"
        for src in sources:
            assert isinstance(src, ast.Call) and _callee(src) == "solar_bounded_reclaim", (
                f"{val.id} must be produced by solar_bounded_reclaim(), got {ast.unparse(src)}")
            assert _kw(src, "surplus_w") is not None and _kw(src, "solar_w") is not None

    def test_reclaim_carries_the_meter_import(self):
        recl = [c for c in self.calls if _callee(c) == "reclaimable_battery_w"]
        assert recl, "reclaimable_battery_w() is no longer called from the coordinator"
        for c in recl:
            imp = _kw(c, "grid_import_w")
            assert imp is not None, "reclaimable_battery_w() called without grid_import_w"
            assert "grid_import_power" in ast.unparse(imp)
