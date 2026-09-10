"""#938 — a Solar-only load ran at night on the battery's GRID charge.

alexmc1510 (2.0 → 2.1.0-beta.9; a battery the inverter fills from the grid on its own night schedule): a pool pump
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
   the meter is NOT importing is solar-funded (``charge − import``). The
   import is the meter's live reading, or — through a dark cycle — the last
   readable one (``held_grid_import``): the reader's 0.0 fallback would
   otherwise credit the whole charge for one blink. A meter never read this
   lifetime reclaims nothing.
2. ``solar_bounded_reclaim`` — the pool as a whole never exceeds the sun
   (``surplus + reclaim ≤ solar``), the #620 invariant on the sum instead of
   on one addend. No sun reading → no reclaim.

Plus a source-level guard so the reclaim cannot reach ``update()`` unbounded
again, whichever way the coordinator block is next refactored.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_reclaim import (
    held_grid_import,
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

    def test_negative_import_reads_as_zero(self):
        # An export figure must not ADD to the reclaim — the term only ever
        # takes away.
        assert reclaimable_battery_w(
            battery_charge_power=1000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=-500.0,
        ) == pytest.approx(1000.0)

    def test_meter_never_read_reclaims_nothing(self):
        # None = no readable meter yet this lifetime: no evidence the sun is
        # funding the charge → fail closed, whatever the pack is drawing.
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=None,
        ) == 0.0

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


@pytest.mark.unit
class TestHeldGridImport:
    """The import ceiling through a dark meter: hold, don't forgive (#925)."""

    def test_readable_meter_is_the_answer_and_becomes_the_hold(self):
        assert held_grid_import(None, grid_import_w=2300.0, grid_import_known=True) == 2300.0
        assert held_grid_import(900.0, grid_import_w=0.0, grid_import_known=True) == 0.0

    def test_dark_cycle_rides_on_the_last_readable_value(self):
        # The reader's fallback on a dark cycle is 0.0 — which must NOT
        # become "no import" for the reclaim.
        assert held_grid_import(2300.0, grid_import_w=0.0, grid_import_known=False) == 2300.0

    def test_dark_meter_never_read_is_none(self):
        assert held_grid_import(None, grid_import_w=0.0, grid_import_known=False) is None

    def test_negative_reading_holds_as_zero(self):
        assert held_grid_import(None, grid_import_w=-400.0, grid_import_known=True) == 0.0

    def test_a_blink_by_day_does_not_credit_the_grid_charge(self):
        # Day, pack on a grid-assisted schedule: sun 1.2 kW, house 500 W,
        # pack charging 3 kW, meter importing 2.3 kW → 700 W is the sun's.
        held = held_grid_import(None, grid_import_w=2300.0, grid_import_known=True)
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=held,
        ) == pytest.approx(700.0)
        # Next cycle the meter blinks: reader hands 0.0 + unavailable. The
        # pre-hold pipeline reclaimed 3000 here; the held one still says 700.
        held = held_grid_import(held, grid_import_w=0.0, grid_import_known=False)
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=held,
        ) == pytest.approx(700.0)

    def test_boot_with_a_dark_meter_reclaims_nothing_until_it_is_read(self):
        held = held_grid_import(None, grid_import_w=0.0, grid_import_known=False)
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=held,
        ) == 0.0
        held = held_grid_import(held, grid_import_w=0.0, grid_import_known=True)
        assert reclaimable_battery_w(
            battery_charge_power=3000.0, soc=60.0, priority_soc=30.0,
            battery_commanded=False, grid_import_w=held,
        ) == pytest.approx(3000.0)


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

    def test_no_solar_reading_reclaims_nothing(self):
        # Unlike solar_bounded_surplus (export IS evidence of the sun), a
        # charging battery with no sun reading is no evidence at all.
        assert solar_bounded_reclaim(1500.0, surplus_w=0.0, solar_w=None) == 0.0

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
        # The main surplus pass hands the device the whole remaining pool
        # (0 export + 3000 reclaim); every force pass would pass
        # min_power_threshold (713) and set a marker. Pin which one fired.
        pump.activate.assert_awaited_once_with(3000.0)
        assert pump._offpeak_forced is False
        assert pump._batt_overnight_forced is False

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

    async def test_zero_import_night_is_still_closed_by_the_solar_ceiling(self, mock_hass):
        # A meter that reads 0 import while the pack charges (a generator, a
        # sign the detector has not caught yet) → ceiling 1 inert. The sun
        # is still 0 W, so ceiling 2 pins the pool alone.
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
        """Every value bound to ``name`` in ``scope`` — plain assignments, and
        the rebinding forms a refactor could slip in (``+=``, an annotated
        assignment, a walrus) are reported too, so a later ``reclaim_w += x``
        cannot hide behind a clean first assignment."""
        out = []
        for node in ast.walk(scope):
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name) and t.id == name:
                        out.append(node.value)
            elif isinstance(node, ast.AugAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name:
                    out.append(node)  # an AugAssign is never a bounding call → fails below
            elif isinstance(node, ast.AnnAssign):
                if isinstance(node.target, ast.Name) and node.target.id == name and node.value is not None:
                    out.append(node.value)
            elif isinstance(node, ast.NamedExpr):
                if isinstance(node.target, ast.Name) and node.target.id == name:
                    out.append(node.value)
        return out

    def _resolved_text(self, value: ast.AST, scope: ast.AST) -> str:
        """The source text a keyword value stands for — the expression
        itself, or (for a bare name) every binding of that name in scope,
        so ``known=_grid_known`` is judged by what ``_grid_known`` is."""
        if isinstance(value, ast.Name):
            bindings = self._assignments_of(value.id, scope)
            assert bindings, f"{value.id} is never assigned in the enclosing function"
            return " | ".join(ast.unparse(b) for b in bindings)
        return ast.unparse(value)

    def _sources(self, value: ast.AST, scope: ast.AST):
        """The call(s) a keyword value ultimately comes from: an inline call,
        or every binding of the name it refers to."""
        if isinstance(value, ast.Call):
            return [value]
        assert isinstance(value, ast.Name), (
            f"expected a name or an inline call, got {ast.unparse(value)}")
        sources = self._assignments_of(value.id, scope)
        assert sources, f"{value.id} is never assigned in the enclosing function"
        return sources

    def test_update_receives_a_solar_bounded_reclaim(self):
        updates = [c for c in self.calls
                   if _callee(c).endswith("_surplus_controller.update")]
        assert len(updates) == 1, "expected exactly one surplus-controller update() call site"
        scope = self._enclosing_function(updates[0])
        val = _kw(updates[0], "reclaim_w")
        assert val is not None, "update() called without reclaim_w"
        for src in self._sources(val, scope):
            assert isinstance(src, ast.Call) and _callee(src) == "solar_bounded_reclaim", (
                f"reclaim_w must be produced by solar_bounded_reclaim(), got {ast.unparse(src)}")
            solar_kw = _kw(src, "solar_w")
            assert solar_kw is not None and "solar_power" in self._resolved_text(solar_kw, scope), (
                "solar_bounded_reclaim() must be handed the live solar reading")
            surplus_kw = _kw(src, "surplus_w")
            assert surplus_kw is not None
            for s in self._sources(surplus_kw, scope):
                assert isinstance(s, ast.Call) and _callee(s) == "solar_bounded_surplus", (
                    f"surplus_w must be the #620-bounded surplus, got {ast.unparse(s)}")

    def test_reclaim_carries_the_held_meter_import(self):
        recl = [c for c in self.calls if _callee(c) == "reclaimable_battery_w"]
        assert recl, "reclaimable_battery_w() is no longer called from the coordinator"
        for c in recl:
            scope = self._enclosing_function(c)
            imp = _kw(c, "grid_import_w")
            assert imp is not None, "reclaimable_battery_w() called without grid_import_w"
            for s in self._sources(imp, scope):
                assert isinstance(s, ast.Call) and _callee(s) == "held_grid_import", (
                    f"grid_import_w must come from held_grid_import(), got {ast.unparse(s)}")
                live = _kw(s, "grid_import_w")
                known = _kw(s, "grid_import_known")
                assert live is not None and "grid_import_power" in self._resolved_text(live, scope)
                assert known is not None and (
                    "grid_power_unavailable" in self._resolved_text(known, scope)), (
                    "the hold must be driven by the reader's dark flag")


# ── 5. the trace says why: raw vs bounded, and how long the meter is held ─


from types import SimpleNamespace  # noqa: E402

from custom_components.solar_energy_management.coordinator.coordinator import (  # noqa: E402
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.cycle_trace import (  # noqa: E402
    TraceCollector,
)


class _TraceStub:
    """Minimal host for the unbound trace methods (the
    ``test_cycle_trace_wiring`` pattern) carrying one cycle's reclaim."""
    _collect_trace = SEMCoordinator._collect_trace
    _trace_ev = SEMCoordinator._trace_ev
    _trace_battery = SEMCoordinator._trace_battery
    _trace_loads = SEMCoordinator._trace_loads
    _trace_heat_pump = SEMCoordinator._trace_heat_pump
    trace_recent = SEMCoordinator.trace_recent

    def __init__(self, cycle_reclaim):
        self._trace = TraceCollector(maxlen=10)
        self.time_manager = SimpleNamespace(is_night_mode=lambda: True)
        self.config = {}
        self._ev_device = None
        self._observer_mode = False
        self._cycle_reclaim = cycle_reclaim


@pytest.mark.unit
class TestTracePublishesTheCeilings:
    """The next such report must be answerable from a diagnostics dump: a
    night with the pack charging at 3 kW and the loads' pool at 0 has to
    READ as "grid charge, not surplus" — in the battery record AND the
    loads record — and the import ceiling has to say how long it has been
    riding on a held value."""

    def _collect(self, cycle_reclaim):
        s = _TraceStub(cycle_reclaim)
        sem = SimpleNamespace(
            calculated_current=0, charging_strategy_reason="", available_power=0,
            status=SimpleNamespace(battery_status="charging"),
            surplus_control=SimpleNamespace(
                surplus_total_devices=1, surplus_active_devices=0,
                surplus_available=False, surplus_total_w=0.0,
                surplus_distributable_w=0.0, surplus_allocated_w=0.0),
            heat_pump=None,
        )
        pw = SimpleNamespace(
            ev_power=0.0, ev_connected=False, battery_soc=45.0,
            battery_charge_power=3000.0, battery_discharge_power=0.0,
        )
        s._collect_trace(sem, pw, None)
        return s.trace_recent(1)[0]["subsystems"]

    def test_night_grid_charge_reads_as_raw_3000_bounded_0(self):
        subs = self._collect({
            "reclaim_w": 0, "reclaim_raw_w": 3000, "import_held_s": 0,
            "battery_priority": 3, "battery_commanded": False,
        })
        batt = subs["battery"]["management"]["data"]
        assert batt["reclaim_raw_w"] == 3000
        assert batt["reclaim_yielded_w"] == 0
        loads = subs["loads"]["process"]["data"]
        assert loads["reclaim_raw_w"] == 3000
        assert loads["reclaim_w"] == 0
        assert loads["import_held_s"] == 0

    def test_held_meter_age_is_published(self):
        subs = self._collect({
            "reclaim_w": 700, "reclaim_raw_w": 700, "import_held_s": 42,
            "battery_priority": 3, "battery_commanded": False,
        })
        assert subs["loads"]["process"]["data"]["import_held_s"] == 42

    def test_a_cycle_without_reclaim_bookkeeping_still_traces(self):
        # Before the surplus block has run once (first cycle, or a cycle
        # that raised before it) the dict is empty — the trace must not
        # depend on the new keys being there.
        subs = self._collect({})
        assert subs["loads"]["process"]["data"]["reclaim_raw_w"] == 0
        assert subs["loads"]["process"]["data"]["import_held_s"] == 0
        assert subs["battery"]["management"]["data"]["reclaim_raw_w"] == 0
