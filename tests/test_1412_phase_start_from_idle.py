"""(#1412) Phase mode "auto" could never reach one phase from an idle start.

Three defects, one report (a charger that changes phases through a number
entity, a small PV system in winter):

1. The auto planner answered only once it had a phase belief, and the belief
   comes from a measured draw. With less sun than three phases need at the
   minimum current the car never started, so the belief never formed and the
   planner never asked for one phase.
2. After a switch to one phase the day decision still priced the minimum
   current at the configured phase count (6 A = 4140 W instead of 1380 W).
3. Switch values saved outside the number entity's range could never be
   written, and nothing said so.

The charger here is a fixture: a number entity with a range. No brand.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coordinator_mod,
    ev_control,
)
from custom_components.solar_energy_management.coordinator.build_view import (
    FleetCycleState, build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    AUTO_MAX_PER_SESSION, AUTO_MIN_INTERVAL_S, AUTO_START_DELAY_S,
    PhaseAutoPlanner,
)
from custom_components.solar_energy_management.coordinator.ev_phases import (
    switch_values_problem,
)


def _hold(planner, start, seconds, surplus_w, believed=None, idle=True):
    """Ask the planner every 10 s for ``seconds`` — as the cycle does.
    Returns the last answer and the time of it."""
    t, answer = start, None
    while t <= start + seconds:
        answer = planner.desired(t, believed, surplus_w, idle=idle)
        t += 10.0
    return answer, t - 10.0

ONE_P_MIN_W = 6 * 230.0          # 1380 W
THREE_P_MIN_W = 3 * 6 * 230.0    # 4140 W
THIN_SUN_W = 2000.0              # covers one phase, not three


# ── 1. the planner ──────────────────────────────────────────────────────

class TestPlannerStartsOnOnePhase:

    def _p(self):
        return PhaseAutoPlanner(min_current_a=6, voltage=230.0)

    def test_thin_sun_on_an_idle_charger_asks_for_one_phase(self):
        p = self._p()
        assert p.desired(0.0, None, THIN_SUN_W, idle=True) is None, (
            "not on the first cycle: the sun must hold")
        answer, _t = _hold(p, 10.0, AUTO_START_DELAY_S, THIN_SUN_W)
        assert answer == 1

    def test_a_cloud_starts_the_wait_again(self):
        p = self._p()
        _answer, t = _hold(p, 0.0, 200.0, THIN_SUN_W)
        p.desired(t + 10, None, 500.0, idle=True)          # below one phase
        answer, t = _hold(p, t + 20, AUTO_START_DELAY_S - 30, THIN_SUN_W)
        assert answer is None, "the 200 s before the cloud do not count"
        answer, _t = _hold(p, t + 10, 60.0, THIN_SUN_W)
        assert answer == 1

    def test_sun_for_three_phases_asks_for_nothing(self):
        """The car starts as it is set up; the draw then gives the belief."""
        p = self._p()
        answer, _t = _hold(p, 0.0, AUTO_START_DELAY_S + 60, THREE_P_MIN_W + 500)
        assert answer is None

    def test_too_little_sun_for_one_phase_asks_for_nothing(self):
        p = self._p()
        answer, _t = _hold(p, 0.0, AUTO_START_DELAY_S + 60, ONE_P_MIN_W - 100)
        assert answer is None

    def test_a_charger_that_draws_is_never_started_cold(self):
        """Unknown phases under load: only a measurement may answer."""
        p = self._p()
        answer, _t = _hold(p, 0.0, AUTO_START_DELAY_S + 60, THIN_SUN_W,
                           idle=False)
        assert answer is None

    def test_idle_defaults_to_false(self):
        """A caller that says nothing about the charger gets today's answer."""
        p = self._p()
        t, answer = 0.0, None
        while t <= AUTO_START_DELAY_S + 60:
            answer = p.desired(t, None, THIN_SUN_W)
            t += 10.0
        assert answer is None

    def test_the_interval_between_switches_holds(self):
        p = self._p()
        p.note_switched(0.0)
        answer, t = _hold(p, 10.0, AUTO_START_DELAY_S + 60, THIN_SUN_W)
        assert answer is None
        answer, _t = _hold(p, t + 10, AUTO_MIN_INTERVAL_S, THIN_SUN_W)
        assert answer == 1

    def test_the_session_cap_holds(self):
        p = self._p()
        t = 0.0
        for _ in range(AUTO_MAX_PER_SESSION):
            p.note_switched(t)
            t += AUTO_MIN_INTERVAL_S + 1
        answer, _t = _hold(p, t, AUTO_START_DELAY_S + 60, THIN_SUN_W)
        assert answer is None

    def test_a_new_car_waits_its_own_time(self):
        p = self._p()
        _answer, t = _hold(p, 0.0, AUTO_START_DELAY_S - 20, THIN_SUN_W)
        p.new_session()
        answer, t = _hold(p, t + 10, 60.0, THIN_SUN_W)
        assert answer is None, "the last car's minutes are not this car's"
        answer, _t = _hold(p, t + 10, AUTO_START_DELAY_S, THIN_SUN_W)
        assert answer == 1

    def test_a_window_from_before_a_pause_does_not_count(self):
        """Manual mode or an unplugged car skips the planner. Back in auto,
        the sun must hold again."""
        p = self._p()
        p.desired(0.0, None, THIN_SUN_W, idle=True)
        back = 2 * 3600.0
        assert p.desired(back, None, THIN_SUN_W, idle=True) is None
        answer, _t = _hold(p, back + 10, AUTO_START_DELAY_S, THIN_SUN_W)
        assert answer == 1

    def test_a_known_belief_is_decided_as_before(self):
        p = self._p()
        answer, _t = _hold(p, 0.0, AUTO_START_DELAY_S + 60, THIN_SUN_W,
                           believed=1)
        assert answer is None, "one phase and thin sun: stay"


# ── 1. the per-charger tick ─────────────────────────────────────────────

SWITCH = "number.wallbox_phase_threshold"


def _host(cfg_over=None, observer=False, number_range=(0.0, 32.0)):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = observer
    h._surplus_controller = None
    h.config = {}
    state = MagicMock()
    state.state = "0"
    state.attributes = ({"min": number_range[0], "max": number_range[1]}
                        if number_range else {})
    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: state),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    h.cfg = {
        "ev_phase_switch_entity": SWITCH,
        "ev_phase_switching_enabled": True,
        "phase_mode": "auto",
        "ev_phase_switch_value_1p": "32",
        "ev_phase_switch_value_3p": "0",
        "ev_voltage": 230,
        "ev_min_current": 6,
    }
    h.cfg.update(cfg_over or {})
    return h


def _idle(budget=THIN_SUN_W):
    return ChargerDecision(
        charger_id="c1", mode="solar_only", intent=ChargerIntent.IDLE,
        budget_w=budget, reason="solar_only: surplus below min — idle")


def _cp(power_w=0.0, charging=False, connected=True):
    return ChargerPower(charger_id="c1", power_w=power_w,
                        connected=connected, charging=charging)


def _run(h, decision, cp, t):
    return asyncio.run(h._phase_switch_tick("c1", h.cfg, decision, cp, t))


def _cycles(h, decision, cp, start=0.0, seconds=None):
    """Run the tick every 10 s, as the cycle does. Returns what each cycle
    gave back and the time of the last one."""
    seconds = AUTO_START_DELAY_S + 60 if seconds is None else seconds
    t, out = start, []
    while t <= start + seconds:
        out.append(_run(h, decision, cp, t))
        t += 10.0
    return out, t - 10.0


class TestTickStartsOnOnePhase:

    def test_thin_sun_writes_the_one_phase_value_once(self):
        h = _host()
        _run(h, _idle(), _cp(), 0.0)
        h.hass.services.async_call.assert_not_awaited()
        _out, t = _cycles(h, _idle(), _cp(), start=10.0)
        h.hass.services.async_call.assert_awaited_once()
        call = h.hass.services.async_call.await_args
        assert call.args[:2] == ("number", "set_value")
        assert call.args[2] == {"entity_id": SWITCH, "value": 32.0}
        # settle over: SEM believes one phase from here
        _cycles(h, _idle(), _cp(), start=t + 10, seconds=120.0)
        assert h._phase_believed["c1"] == 1
        h.hass.services.async_call.assert_awaited_once()

    def test_no_switch_while_the_charger_draws(self):
        """Phases unknown and a car drawing: no start, no stop, no write."""
        h = _host()
        d = ChargerDecision(
            charger_id="c1", mode="always_max",
            intent=ChargerIntent.CHARGE_MAX, budget_w=0.0, reason="max")
        out, _t = _cycles(h, d, _cp(power_w=300.0, charging=True))
        assert all(o is d for o in out)
        h.hass.services.async_call.assert_not_awaited()

    def test_a_draw_the_charging_flag_misses_is_still_a_draw(self):
        h = _host()
        _cycles(h, _idle(), _cp(power_w=300.0, charging=False))
        h.hass.services.async_call.assert_not_awaited()

    def test_a_charge_sem_asked_for_is_not_started_cold(self):
        """SEM commands amps (a grid floor) and the car has not started yet:
        the draw will give the phases. No switch to one phase under it."""
        h = _host()
        d = ChargerDecision(
            charger_id="c1", mode="min_plus_solar",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=6,
            budget_w=THIN_SUN_W, reason="Min floor engaged")
        out, _t = _cycles(h, d, _cp())
        assert all(o is d for o in out)
        h.hass.services.async_call.assert_not_awaited()

    def test_no_car_no_switch(self):
        h = _host()
        _cycles(h, _idle(), _cp(connected=False))
        h.hass.services.async_call.assert_not_awaited()

    def test_observer_mode_writes_nothing(self):
        h = _host(observer=True)
        _cycles(h, _idle(), _cp())
        h.hass.services.async_call.assert_not_awaited()

    def test_a_charger_with_phase_switching_off_is_untouched(self):
        h = _host({"ev_phase_switching_enabled": False})
        d = _idle()
        out, _t = _cycles(h, d, _cp())
        assert all(o is d for o in out)
        h.hass.services.async_call.assert_not_awaited()
        assert getattr(h, "_phase_planners", None) is None, (
            "no per-charger phase state is even made")

    def test_a_charger_without_a_switch_is_untouched(self):
        h = _host({"ev_phase_switch_entity": None,
                   "ev_phase_switching_enabled": False})
        d = _idle()
        out, _t = _cycles(h, d, _cp())
        assert all(o is d for o in out)
        h.hass.services.async_call.assert_not_awaited()

    def test_manual_three_phases_is_not_overruled(self):
        h = _host({"phase_mode": "3"})
        _cycles(h, _idle(), _cp())
        calls = h.hass.services.async_call.await_args_list
        assert calls and all(c.args[2]["value"] == 0.0 for c in calls), (
            "the owner's choice of three phases is the only thing written")


def _amps(amps, budget=THIN_SUN_W):
    return ChargerDecision(
        charger_id="c1", mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=budget, reason="solar")


class TestAmpsSizedForFewerPhasesAreStopped:
    """The decision's amps follow the phases SEM believes. When the charger
    turns out to run on more, those amps are too many: one cycle is stopped
    and the next decision is sized again."""

    def _on_one_phase(self):
        h = _host()
        _out, t = _cycles(h, _idle(), _cp(), start=0.0)       # idle start
        _out, t = _cycles(h, _idle(), _cp(), start=t + 10, seconds=120.0)
        assert h._phase_believed["c1"] == 1
        return h, t + 10

    def test_one_phase_as_set_passes(self):
        h, t = self._on_one_phase()
        d = _amps(8)
        assert _run(h, d, _cp(power_w=8 * 230.0, charging=True), t) is d
        assert h._phase_believed["c1"] == 1

    def test_one_phase_on_a_high_grid_voltage_is_still_one_phase(self):
        """245 V: 6.5 % over nameplate. No stop, and the belief stays."""
        h, t = self._on_one_phase()
        d = _amps(8)
        for i in range(3):
            assert _run(h, d, _cp(power_w=8 * 245.0, charging=True),
                        t + 10 * i) is d
        assert h._phase_believed["c1"] == 1

    def test_a_switch_the_charger_did_not_take_stops_the_charge(self):
        """SEM set one phase, the draw is three: 8 A is 5.5 kW, not 1.8 kW."""
        h, t = self._on_one_phase()
        d = _amps(8)
        out = _run(h, d, _cp(power_w=8 * 3 * 230.0, charging=True), t)
        assert out.intent is ChargerIntent.DISABLE
        assert h._phase_believed["c1"] == 3
        # sized again on three phases: nothing more to stop
        d3 = _amps(8, budget=6000.0)
        assert _run(h, d3, _cp(power_w=8 * 3 * 230.0, charging=True),
                    t + 10) is d3

    def test_a_part_draw_on_three_phases_stops_the_charge_too(self):
        """A car that takes less than the offer on three phases reads 2:
        more than one phase carries, so the amps are too many."""
        h, t = self._on_one_phase()
        out = _run(h, _amps(8), _cp(power_w=3300.0, charging=True), t)
        assert out.intent is ChargerIntent.DISABLE

    def test_a_switch_up_holds_one_more_cycle(self):
        """Settled on three phases: this cycle's amps were sized for one."""
        h, t = self._on_one_phase()
        up = _amps(16, budget=5000.0)
        outs, t2 = _cycles(h, up, _cp(power_w=16 * 230.0, charging=True),
                           start=t + AUTO_MIN_INTERVAL_S,   # the switch interval
                           seconds=400.0)                   # 5 min of headroom
        assert any(o.intent is ChargerIntent.DISABLE for o in outs), "stopping"
        outs, t3 = _cycles(h, up, _cp(), start=t2 + 10, seconds=120.0)
        assert h._phase_believed["c1"] == 3
        assert all(o.intent is ChargerIntent.DISABLE for o in outs
                   if o is not up), "held while settling"
        settled = [o for o in outs if "amps sized for 1" in o.reason]
        assert len(settled) == 1, "exactly the cycle the switch settled"
        d3 = _amps(7, budget=5000.0)
        assert _run(h, d3, _cp(), t3 + 10) is d3

    def test_a_first_measurement_of_the_configured_count_passes(self):
        h = _host({"ev_phases": 3})
        d = _amps(8, budget=6000.0)
        assert _run(h, d, _cp(power_w=8 * 3 * 230.0, charging=True), 0.0) is d
        assert h._phase_believed["c1"] == 3

    def test_fewer_phases_than_sized_for_passes(self):
        """A one-phase car on a three-phase setup draws less. No stop."""
        h = _host({"ev_phases": 3})
        d = _amps(8, budget=6000.0)
        assert _run(h, d, _cp(power_w=8 * 230.0, charging=True), 0.0) is d
        assert h._phase_believed["c1"] == 1

    def test_full_power_is_not_sized_by_phases(self):
        h, t = self._on_one_phase()
        d = ChargerDecision(
            charger_id="c1", mode="always_max",
            intent=ChargerIntent.CHARGE_MAX, budget_w=0.0, reason="max")
        out = _run(h, d, _cp(power_w=16 * 3 * 230.0, charging=True), t)
        assert out is d


# ── 2. the decision's minimum power ─────────────────────────────────────

def _view(charger_cfg, surplus_w, active_phases=None, mode="solar_only"):
    power = MagicMock()
    power.solar_power = surplus_w + 300.0
    power.home_consumption_power = 300.0
    power.battery_soc = None
    power.battery_power = 0.0
    power.grid_power = surplus_w
    power.ev_power = 0.0
    power.ev_power_per_charger = {}
    power.ev_connected_per_charger = {"wb": True}
    power.ev_charging_per_charger = {}
    fleet = FleetCycleState(
        power=power, config={}, is_night=False, tariff_level=None,
        forecast_remaining_kwh=0.0)
    kwargs = {}
    if active_phases is not None:
        kwargs["active_phases"] = active_phases
    return build_charger_view(
        fleet, charger_id="wb", charger_cfg=charger_cfg, mode=mode,
        daily_ev_kwh=0.0, **kwargs)


SWITCHING_CFG = {
    "id": "wb", "ev_phases": 3, "ev_min_current": 6, "ev_max_current": 16,
    "ev_voltage": 230, "ev_phase_switching_enabled": True,
    "ev_phase_switch_entity": SWITCH,
}


class TestDecisionUsesTheActivePhases:

    def test_the_view_carries_the_phases_sem_set(self):
        view = _view(SWITCHING_CFG, THIN_SUN_W, active_phases=1)
        assert view.config["ev_phases"] == 1

    def test_unknown_phases_keep_the_configured_count(self):
        view = _view(SWITCHING_CFG, THIN_SUN_W)
        assert view.config["ev_phases"] == 3

    def test_a_charger_that_cannot_switch_keeps_its_configured_count(self):
        cfg = {**SWITCHING_CFG, "ev_phase_switching_enabled": False}
        view = _view(cfg, THIN_SUN_W, active_phases=1)
        assert view.config["ev_phases"] == 3

    def test_a_count_that_is_no_phase_count_is_ignored(self):
        view = _view(SWITCHING_CFG, THIN_SUN_W, active_phases=2)
        assert view.config["ev_phases"] == 3

    def test_the_stored_config_is_not_changed(self):
        cfg = dict(SWITCHING_CFG)
        _view(cfg, THIN_SUN_W, active_phases=1)
        assert cfg["ev_phases"] == 3

    def test_one_phase_charges_on_thin_sun(self):
        """The report: on one phase the minimum is 1380 W, not 4140 W."""
        on_three = decide(_view(SWITCHING_CFG, THIN_SUN_W))
        assert on_three.intent is ChargerIntent.IDLE
        on_one = decide(_view(SWITCHING_CFG, THIN_SUN_W, active_phases=1))
        assert on_one.intent is ChargerIntent.CHARGE_AT_AMPS
        assert on_one.commanded_amps * 230 <= THIN_SUN_W


class TestEveryViewIsBuiltWithTheActivePhases:
    """A view built without them prices the minimum at the configured count
    again. Every ``build_charger_view`` call in the coordinator passes it."""

    def test_each_call_passes_active_phases(self):
        tree = ast.parse(inspect.getsource(coordinator_mod))
        calls = [n for n in ast.walk(tree)
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "build_charger_view"]
        assert len(calls) >= 3
        missing = [c.lineno for c in calls
                   if "active_phases" not in {k.arg for k in c.keywords}]
        assert missing == [], f"build_charger_view without active_phases: {missing}"

    def _coord(self, believed, contradictions=0, enabled=True):
        c = SimpleNamespace()
        c.config = {}
        c._phase_believed = {"wb": believed} if believed else {}
        c._phase_contradictions = {"wb": {"count": contradictions}}
        cfg = {**SWITCHING_CFG, "ev_phase_switching_enabled": enabled}
        c._ev_charger_cfg = lambda cid: cfg
        cls = coordinator_mod.SEMCoordinator
        c._active_phases_for = cls._active_phases_for.__get__(c)
        return c

    def test_the_belief_is_the_active_count(self):
        assert self._coord(1)._active_phases_for("wb") == 1
        assert self._coord(3)._active_phases_for("wb") == 3

    def test_no_belief_is_no_count(self):
        assert self._coord(None)._active_phases_for("wb") is None

    def test_a_disputed_switch_keeps_the_measured_count(self):
        """After a switch the box did not take, the belief IS the measured
        draw — the latest reading, so the decision keeps it."""
        assert self._coord(1, contradictions=1)._active_phases_for("wb") == 1

    def test_two_is_no_count(self):
        assert self._coord(2)._active_phases_for("wb") is None

    def test_a_charger_that_cannot_switch_has_no_active_count(self):
        assert self._coord(1, enabled=False)._active_phases_for("wb") is None


# ── 3. switch values the entity cannot take ─────────────────────────────

class TestSwitchValuesMustFitTheEntity:

    def test_the_reported_values_do_not_fit(self):
        why = switch_values_problem(SWITCH, "1000", "4000", (0.0, 32.0))
        assert why and "1000" in why and "0" in why and "32" in why

    def test_values_inside_the_range_fit(self):
        assert switch_values_problem(SWITCH, "32", "0", (0.0, 32.0)) is None

    def test_a_value_that_is_no_number_does_not_fit(self):
        assert switch_values_problem(SWITCH, "one", "0", (0.0, 32.0))

    def test_an_unknown_range_is_not_judged(self):
        assert switch_values_problem(SWITCH, "1000", "4000", None) is None

    def test_a_select_is_not_judged_by_a_range(self):
        assert switch_values_problem("select.phases", "1", "3", (0.0, 32.0)) is None

    def test_the_tick_never_writes_a_value_the_entity_cannot_take(self):
        h = _host({"ev_phase_switch_value_1p": "1000",
                   "ev_phase_switch_value_3p": "4000"})
        d = _idle()
        out, _t = _cycles(h, d, _cp())
        assert all(o is d for o in out)
        h.hass.services.async_call.assert_not_awaited()
        assert h._phase_switch_states["c1"] == "bad_values"

    def test_manual_mode_does_not_write_it_either(self):
        h = _host({"phase_mode": "1", "ev_phase_switch_value_1p": "1000",
                   "ev_phase_switch_value_3p": "4000"})
        _run(h, _idle(), _cp(), 0.0)
        h.hass.services.async_call.assert_not_awaited()
        assert h._phase_switch_states["c1"] == "bad_values"


class TestTheRepairNamesTheValue:
    """The owner is told: the charger's phase switch is marked not valid and
    the control-entity Repair names the entity and the value."""

    def _coord(self, monkeypatch, v1="1000", v3="4000", number_range=(0.0, 32.0),
               enabled=True, extra=None):
        from custom_components.solar_energy_management.coordinator import (
            repair_issues,
        )
        calls = {"raised": [], "cleared": []}
        monkeypatch.setattr(
            repair_issues, "raise_charger_control_entity_broken",
            lambda hass, cid, **kw: calls["raised"].append((cid, kw)))
        monkeypatch.setattr(
            repair_issues, "clear_charger_control_entity_broken",
            lambda hass, cid, eid: calls["cleared"].append((cid, eid)))
        monkeypatch.setattr(
            coordinator_mod, "charger_display_name", lambda hass, cfg: "Wallbox")
        state = MagicMock()
        state.attributes = ({"min": number_range[0], "max": number_range[1]}
                            if number_range else {})
        c = SimpleNamespace()
        c.hass = SimpleNamespace(states=SimpleNamespace(get=lambda eid: state))
        cls = coordinator_mod.SEMCoordinator
        c._CONTROL_CAPABILITIES = cls._CONTROL_CAPABILITIES
        c._PHASE_SWITCH_CAPABILITY = cls._PHASE_SWITCH_CAPABILITY
        c._check_phase_switch_values = cls._check_phase_switch_values.__get__(c)
        cfg = {"id": "wb", "ev_phase_switch_entity": SWITCH,
               "ev_phase_switching_enabled": enabled,
               "ev_phase_switch_value_1p": v1, "ev_phase_switch_value_3p": v3}
        cfg.update(extra or {})
        return c, cfg, calls

    def test_values_outside_the_range_raise_one_repair(self, monkeypatch):
        c, cfg, calls = self._coord(monkeypatch)
        result = {"charger_wb_phase_switch_valid": True}
        c._check_phase_switch_values("wb", cfg, result)
        c._check_phase_switch_values("wb", cfg, result)
        assert result["charger_wb_phase_switch_valid"] is False
        assert len(calls["raised"]) == 1
        cid, kw = calls["raised"][0]
        assert cid == "wb" and kw["entity_id"] == SWITCH
        assert "1000" in kw["reason"] and "32" in kw["reason"]

    def test_fitting_values_clear_it(self, monkeypatch):
        c, cfg, calls = self._coord(monkeypatch)
        result = {}
        c._check_phase_switch_values("wb", cfg, result)
        cfg["ev_phase_switch_value_1p"], cfg["ev_phase_switch_value_3p"] = "32", "0"
        result = {"charger_wb_phase_switch_valid": True}
        c._check_phase_switch_values("wb", cfg, result)
        assert result["charger_wb_phase_switch_valid"] is True
        assert calls["cleared"] == [("wb", SWITCH)]

    def test_a_repair_from_before_a_restart_is_cleared_once(self, monkeypatch):
        c, cfg, calls = self._coord(monkeypatch, v1="32", v3="0")
        c._check_phase_switch_values("wb", cfg, {})
        c._check_phase_switch_values("wb", cfg, {})
        assert calls["cleared"] == [("wb", SWITCH)] and not calls["raised"]

    def test_a_range_that_cannot_be_read_says_nothing(self, monkeypatch):
        c, cfg, calls = self._coord(monkeypatch, number_range=None)
        result = {"charger_wb_phase_switch_valid": True}
        c._check_phase_switch_values("wb", cfg, result)
        assert result["charger_wb_phase_switch_valid"] is True
        assert not calls["raised"] and not calls["cleared"]

    def test_phase_switching_off_is_not_checked(self, monkeypatch):
        c, cfg, calls = self._coord(monkeypatch, enabled=False)
        c._check_phase_switch_values("wb", cfg, {})
        assert not calls["raised"] and not calls["cleared"]

    def test_another_checks_repair_is_not_cleared(self, monkeypatch):
        """The same entity as the current control: that Repair has its owner."""
        c, cfg, calls = self._coord(
            monkeypatch, v1="32", v3="0",
            extra={"ev_current_control_entity": SWITCH})
        c._check_phase_switch_values("wb", cfg, {})
        assert not calls["cleared"]


class TestTheFormsRefuseValuesThatDoNotFit:
    """Where the values are typed: the add and the edit form of a charger."""

    def _flow(self, chargers, number_range=(0.0, 32.0)):
        from unittest.mock import patch
        from custom_components.solar_energy_management.config_flow import (
            OptionsFlowHandler,
        )
        entry = MagicMock()
        entry.data, entry.options = {}, {}
        flow = OptionsFlowHandler(entry)
        state = MagicMock()
        state.attributes = {"min": number_range[0], "max": number_range[1]}
        flow.hass = MagicMock()
        flow.hass.data = {}
        flow.hass.states.get = lambda eid: state
        flow._data = {"ev_chargers": chargers}
        flow._edit_charger_id = "c1"
        shown = {}
        flow.async_show_form = lambda **kw: shown.update(kw) or {"type": "form", **kw}
        ctx = patch.object(type(flow), "config_entry",
                           new_callable=lambda: property(lambda s: entry))
        return flow, shown, ctx

    BOX = {"id": "c1", "name": "Box", "ev_connected_sensor": "binary_sensor.x",
           "ev_phase_switch_entity": SWITCH,
           "ev_phase_switch_value_1p": "32", "ev_phase_switch_value_3p": "0"}

    def test_edit_refuses_and_saves_nothing(self):
        flow, shown, ctx = self._flow([dict(self.BOX)])
        with ctx:
            asyncio.run(flow.async_step_ev_charger_edit({
                "charger_name": "Box", "ev_phase_switch_entity": SWITCH,
                "ev_phase_switch_value_1p": "1000",
                "ev_phase_switch_value_3p": "4000"}))
        assert shown["errors"] == {"base": "phase_switch_value_out_of_range"}
        assert shown["step_id"] == "ev_charger_edit"
        saved = flow._data["ev_chargers"][0]
        assert saved["ev_phase_switch_value_1p"] == "32"
        assert saved["ev_phase_switch_value_3p"] == "0"

    def test_edit_takes_values_that_fit(self):
        flow, shown, ctx = self._flow([dict(self.BOX)])
        flow.async_step_ev_charger_menu = AsyncMock(return_value={"type": "menu"})
        with ctx:
            asyncio.run(flow.async_step_ev_charger_edit({
                "charger_name": "Box", "ev_phase_switch_entity": SWITCH,
                "ev_phase_switch_value_1p": "16",
                "ev_phase_switch_value_3p": "0"}))
        assert not shown
        assert flow._data["ev_chargers"][0]["ev_phase_switch_value_1p"] == "16"

    def test_add_refuses_and_adds_nothing(self, monkeypatch):
        from custom_components.solar_energy_management import hardware_detection
        monkeypatch.setattr(
            hardware_detection, "discover_all_ev_chargers_from_registry",
            lambda hass: [])
        flow, shown, ctx = self._flow([])
        with ctx:
            asyncio.run(flow.async_step_ev_charger_add({
                "charger_name": "Second", "ev_connected_sensor": "binary_sensor.y",
                "ev_phase_switch_entity": SWITCH,
                "ev_phase_switch_value_1p": "1000",
                "ev_phase_switch_value_3p": "4000"}))
        assert shown["errors"] == {"base": "phase_switch_value_out_of_range"}
        assert shown["step_id"] == "ev_charger_add"
        assert flow._data["ev_chargers"] == []

    def test_the_error_has_a_text(self):
        import json
        from pathlib import Path
        root = Path(ev_control.__file__).resolve().parent.parent
        strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))
        assert "phase_switch_value_out_of_range" in strings["options"]["error"]


class TestTheNightPlanSizesOnTheActivePhases:
    """One phase after a switch is 230 W per amp. The night plan and the
    deadline floor size the car by this number: left at three phases, they
    would plan 4.1 kW for a car that takes 1.4 kW."""

    def _coord(self, believed, ema=None):
        cls = coordinator_mod.SEMCoordinator
        c = cls.__new__(cls)
        c.config = {"ev_chargers": [SWITCHING_CFG]}
        c._ev_wpa_ema = dict(ema or {})
        c._last_commanded_amps_fleet = 0
        c._phase_believed = {"wb": believed} if believed else {}
        return c

    def test_one_phase_is_one_phase_of_nameplate(self):
        c = self._coord(1)
        assert c._ev_watts_per_amp("wb", SWITCHING_CFG) == 230.0

    def test_unknown_phases_keep_the_configured_nameplate(self):
        c = self._coord(None)
        assert c._ev_watts_per_amp("wb", SWITCHING_CFG) == 690.0

    def test_an_average_learned_on_three_phases_is_capped_on_one(self):
        c = self._coord(1, ema={"wb": 600.0})
        assert c._ev_watts_per_amp("wb", SWITCHING_CFG) == 230.0

    def test_a_charger_that_cannot_switch_is_unchanged(self):
        cfg = {**SWITCHING_CFG, "ev_phase_switching_enabled": False}
        c = self._coord(1, ema={"wb": 600.0})
        c.config = {"ev_chargers": [cfg]}
        assert c._ev_watts_per_amp("wb", cfg) == 600.0


class TestTheNightCountsOnTheActivePhases:
    """A charger the day left on one phase delivers a third at night. What
    the night can deliver, and the plan's watts per amp, follow it."""

    def _host(self, believed):
        from homeassistant.util import dt as dt_util
        from custom_components.solar_energy_management.utils.time_manager import (
            TimeManager,
        )
        now = dt_util.now()
        local = lambda h, m: now.replace(hour=h, minute=m, second=0, microsecond=0)
        sun = MagicMock()
        sun.attributes = {"next_setting": local(17, 0).isoformat(),
                          "next_rising": local(7, 15).isoformat()}
        sun.state = "below_horizon"
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=sun)
        host = SimpleNamespace(
            time_manager=TimeManager(hass=hass, config={}), config={})
        if believed:
            host._phase_believed = {"wb": believed}
        return host, local(12, 0)

    def _deliverable(self, believed, cfg=None):
        from unittest.mock import patch
        host, noon = self._host(believed)
        cfg = cfg or {**SWITCHING_CFG, "ev_target_time": "07:00"}
        with patch("homeassistant.util.dt.now", return_value=noon):
            return ev_control.EVControlMixin._night_deliverable_kwh(host, cfg)

    def test_one_phase_delivers_a_third(self):
        three = self._deliverable(None)
        one = self._deliverable(1)
        assert three > 0 and one == pytest.approx(three / 3)

    def test_three_phases_as_configured(self):
        assert self._deliverable(3) == pytest.approx(self._deliverable(None))

    def test_a_charger_that_cannot_switch_is_unchanged(self):
        cfg = {**SWITCHING_CFG, "ev_phase_switching_enabled": False,
               "ev_target_time": "07:00"}
        assert self._deliverable(1, cfg) == pytest.approx(
            self._deliverable(None, cfg))

    def test_the_helper_reads_one_function(self):
        """``_phases_now`` and the view answer from ``active_phases``."""
        host = SimpleNamespace(_phase_believed={"wb": 1})
        assert ev_control._phases_now(host, SWITCHING_CFG, 3) == 1
        assert ev_control._phases_now(SimpleNamespace(), SWITCHING_CFG, 3) == 3
        assert ev_control._phases_now(
            host, {**SWITCHING_CFG, "ev_phase_switching_enabled": False}, 3) == 3
        from .ast_contracts import calls
        assert calls(ev_control.EVControlMixin._compute_night_plan,
                     "_phases_now"), "the night plan sizes on the active phases"
