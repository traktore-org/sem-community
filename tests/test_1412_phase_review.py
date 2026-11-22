"""(#1412, review 22.11) What the independent review refuted on the first
build of the idle one-phase start.

1. Night: a charger the day left on one phase stayed there all night — the
   planner sees no spare sun at night, so nothing switched it back, and a
   grid charge ran at a third of the power.
2. The phase belief was never cleared: a car swap started sized for the car
   before.
3. Switches from a known belief trusted the charging flag alone.
4. A charger with switching on but no working switch was sized on the
   measured phases — it cannot switch, so it must read as on develop.
5. The value check had no debounce and judged a placeholder range.
6. The dashboard saved the two values unchecked.

The charger is a fixture: a number entity with a range. No brand.
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coordinator_mod,
    ev_control,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    AUTO_DOWN_DELAY_S, AUTO_START_DELAY_S, SETTLE_S,
)
from custom_components.solar_energy_management.coordinator.ev_phases import (
    PHASE_VALUES_STRIKES, active_phases, changed_switch_values_problem,
    entity_bounds,
)

from .ast_contracts import calls

SWITCH = "number.wallbox_phase_threshold"
THIN_SUN_W = 2000.0
ONE_PHASE_VALUE, THREE_PHASE_VALUE = 32.0, 0.0


def _host(cfg_over=None, number_range=(0.0, 32.0), entity_state=True):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = False
    h._surplus_controller = None
    h.config = {}
    h.range = number_range

    def _get(eid):
        if not entity_state:
            return None
        st = MagicMock()
        st.state = "0"
        st.attributes = ({"min": h.range[0], "max": h.range[1]}
                         if h.range else {})
        return st

    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=_get),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    h.cfg = {
        "id": "c1",
        "ev_phase_switch_entity": SWITCH,
        "ev_phase_switching_enabled": True,
        "phase_mode": "auto",
        "ev_phase_switch_value_1p": "32",
        "ev_phase_switch_value_3p": "0",
        "ev_voltage": 230, "ev_min_current": 6, "ev_max_current": 16,
        "ev_phases": 3,
    }
    h.cfg.update(cfg_over or {})
    return h


def _idle(budget=0.0):
    return ChargerDecision(
        charger_id="c1", mode="min_plus_solar", intent=ChargerIntent.IDLE,
        budget_w=budget, reason="idle")


def _amps(amps, budget=0.0):
    return ChargerDecision(
        charger_id="c1", mode="min_plus_solar",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=budget, reason="charge")


def _cp(power_w=0.0, charging=False, connected=True):
    return ChargerPower(charger_id="c1", power_w=power_w,
                        connected=connected, charging=charging)


def _run(h, decision, cp, t, night=False):
    return asyncio.run(h._phase_switch_tick(
        "c1", h.cfg, decision, cp, t, is_night=night))


def _cycles(h, decision, cp, start, seconds, night=False):
    t, out = start, []
    while t <= start + seconds:
        out.append(_run(h, decision, cp, t, night=night))
        t += 10.0
    return out, t - 10.0


def _values(h):
    return [c.args[2]["value"] for c in h.hass.services.async_call.await_args_list]


def _on_one_phase_by_sems_choice(h=None):
    """The day: thin sun, an idle car, auto sets one phase."""
    h = h or _host()
    _out, t = _cycles(h, _idle(THIN_SUN_W), _cp(), 0.0, AUTO_START_DELAY_S + 60)
    _out, t = _cycles(h, _idle(THIN_SUN_W), _cp(), t + 10, SETTLE_S + 30)
    assert h._phase_believed["c1"] == 1 and _values(h) == [ONE_PHASE_VALUE]
    return h, t + 10


def _on_three_phases_measured(h=None):
    h = h or _host()
    _run(h, _amps(8, budget=6000.0), _cp(8 * 3 * 230.0, True), 0.0)
    assert h._phase_believed["c1"] == 3
    return h, 10.0


# ── 1. the night ─────────────────────────────────────────────────────────

class TestTheNightGoesBackToTheConfiguredPhases:

    def test_an_idle_charger_is_set_back_when_the_night_starts(self):
        h, t = _on_one_phase_by_sems_choice()
        _out, t = _cycles(h, _idle(), _cp(), t, 60.0, night=True)
        assert _values(h) == [ONE_PHASE_VALUE, THREE_PHASE_VALUE], (
            "no half hour of waiting: the night's grid charge needs it")
        _out, t = _cycles(h, _idle(), _cp(), t + 10, SETTLE_S + 30, night=True)
        assert h._phase_believed["c1"] == 3

    def test_by_day_an_idle_charger_stays_on_one_phase(self):
        """Thin sun may come back: one phase is what lets the car use it."""
        h, t = _on_one_phase_by_sems_choice()
        _cycles(h, _idle(500.0), _cp(), t, 900.0, night=False)
        assert _values(h) == [ONE_PHASE_VALUE]

    def test_the_night_never_scales_down(self):
        """No sun at night is no starvation. On develop a three-phase
        charger was set to one phase ten minutes into the night."""
        h, t = _on_three_phases_measured()
        _cycles(h, _idle(), _cp(), t, AUTO_DOWN_DELAY_S + 300, night=True)
        assert _values(h) == []

    def test_a_grid_charge_is_not_starved_down(self):
        h, t = _on_three_phases_measured()
        d = _amps(6)                       # grid pays: no sun in the budget
        outs, _t = _cycles(h, d, _cp(6 * 3 * 230.0, True), t,
                           AUTO_DOWN_DELAY_S + 300, night=True)
        assert all(o is d for o in outs) and _values(h) == []

    def test_a_one_phase_car_is_not_fought(self):
        """One phase measured, not chosen by SEM: the car is the reason."""
        h = _host()
        _run(h, _amps(8, budget=6000.0), _cp(8 * 230.0, True), 0.0)
        assert h._phase_believed["c1"] == 1
        _cycles(h, _idle(), _cp(), 10.0, 600.0, night=True)
        assert _values(h) == []

    def test_manual_one_phase_stays_one_phase_at_night(self):
        h = _host({"phase_mode": "1"})
        _cycles(h, _idle(), _cp(), 0.0, SETTLE_S + 60)
        assert _values(h) == [ONE_PHASE_VALUE]
        _cycles(h, _idle(), _cp(), 200.0, 900.0, night=True)
        assert _values(h) == [ONE_PHASE_VALUE]

    def _plan(self, h, remaining_kwh, hours):
        h._night_plan_per_charger = {"c1": SimpleNamespace(
            remaining_kwh=remaining_kwh, hours_to_deadline=hours)}

    def test_a_night_charge_on_one_phase_that_cannot_make_it_switches_up(self):
        """The block began before the charger was at rest. 30 kWh in 6 h is
        5 kW; one phase at 16 A gives 3.7 kW."""
        h, t = _on_one_phase_by_sems_choice()
        self._plan(h, 30.0, 6.0)
        d = _amps(16)
        out = _run(h, d, _cp(16 * 230.0, True), t, night=True)
        assert out.intent is ChargerIntent.DISABLE, "stop first, never under load"
        assert _values(h) == [ONE_PHASE_VALUE]
        _run(h, d, _cp(0.0, False), t + 10, night=True)
        assert _values(h) == [ONE_PHASE_VALUE, THREE_PHASE_VALUE]

    def test_a_night_charge_one_phase_can_deliver_is_left_alone(self):
        """10 kWh in 6 h is 1.7 kW: one phase does it. No stop for nothing."""
        h, t = _on_one_phase_by_sems_choice()
        self._plan(h, 10.0, 6.0)
        d = _amps(8)
        outs, _t = _cycles(h, d, _cp(8 * 230.0, True), t, 600.0, night=True)
        assert all(o is d for o in outs) and _values(h) == [ONE_PHASE_VALUE]

    def test_the_night_is_sized_on_the_phases_it_will_run_on(self):
        """By day, on SEM's own one phase: tonight runs on three. While a
        grid charge runs on one phase: on one."""
        h, t = _on_one_phase_by_sems_choice()
        assert ev_control._phases_now(h, h.cfg, 3) == 3, "tonight: three"
        assert active_phases(h.cfg, h._phase_believed["c1"]) == 1, "now: one"
        self._plan(h, 10.0, 6.0)
        _run(h, _amps(8), _cp(8 * 230.0, True), t, night=True)
        assert ev_control._phases_now(h, h.cfg, 3) == 1

    def test_day_start_evening_night_meets_the_target(self):
        """The whole day: thin sun starts the car on one phase; at night the
        charger is back on three before the grid block; 6 A then gives
        4.1 kW, and 20 kWh in 8 h (2.5 kW) is met. On one phase 6 A gives
        1.4 kW: 11 kWh by the morning."""
        h, t = _on_one_phase_by_sems_choice()
        # evening: the sun is gone, still day
        _out, t = _cycles(h, _idle(), _cp(), t, 600.0, night=False)
        # night starts, the car idle (waiting for its block)
        _out, t = _cycles(h, _idle(), _cp(), t + 10, SETTLE_S + 120, night=True)
        assert h._phase_believed["c1"] == 3
        assert ev_control._phases_now(h, h.cfg, 3) == 3
        phases = active_phases(h.cfg, h._phase_believed["c1"])
        d = _amps(6)
        outs, _t = _cycles(h, d, _cp(6 * phases * 230.0, True), t + 10, 900.0,
                           night=True)
        assert all(o is d for o in outs), "the block runs, nothing stops it"
        delivered_kwh = 6 * phases * 230.0 * 8 / 1000.0
        assert delivered_kwh >= 20.0
        assert _values(h) == [ONE_PHASE_VALUE, THREE_PHASE_VALUE]


# ── 2. the belief lives for one plug-in ──────────────────────────────────

class TestTheBeliefEndsWithThePlugIn:

    def test_unplugging_clears_what_sem_set(self):
        h, t = _on_one_phase_by_sems_choice()
        _cycles(h, _idle(), _cp(connected=False), t, 120.0)
        assert h._phase_believed.get("c1") is None
        assert active_phases(h.cfg, h._phase_believed.get("c1")) is None

    def test_unplugging_clears_a_measured_count_too(self):
        """A one-phase car leaves, a three-phase car comes: 6 A sized for one
        phase would be 4.1 kW."""
        h = _host()
        _run(h, _amps(8, budget=6000.0), _cp(8 * 230.0, True), 0.0)
        assert h._phase_believed["c1"] == 1
        _cycles(h, _idle(), _cp(connected=False), 10.0, 120.0)
        assert h._phase_believed.get("c1") is None

    def test_a_blink_of_the_plug_sensor_keeps_it(self):
        h, t = _on_one_phase_by_sems_choice()
        _run(h, _idle(), _cp(connected=False), t)
        _run(h, _idle(THIN_SUN_W), _cp(), t + 10)
        assert h._phase_believed["c1"] == 1

    def test_a_long_absence_clears_it(self):
        """The tick did not run for an hour (the charger was away, or another
        system drove it): what SEM knew then is not known now."""
        h, t = _on_one_phase_by_sems_choice()
        _run(h, _idle(), _cp(), t + 3600.0)
        assert h._phase_believed.get("c1") is None


# ── 3. no switch while power flows ───────────────────────────────────────

class TestEverySwitchWaitsForThePowerToRest:

    def test_auto_down_waits_for_the_draw_the_flag_misses(self):
        h, t = _on_three_phases_measured()
        lagging = _cp(power_w=2000.0, charging=False)
        _cycles(h, _idle(500.0), lagging, t, AUTO_DOWN_DELAY_S + 100)
        assert _values(h) == [], "the car still draws: no switch"

    def test_manual_waits_too(self):
        h, t = _on_three_phases_measured(_host({"phase_mode": "1"}))
        _cycles(h, _idle(), _cp(power_w=2000.0, charging=False), t, 120.0)
        assert _values(h) == []

    def test_at_rest_the_switch_goes_out(self):
        h, t = _on_three_phases_measured(_host({"phase_mode": "1"}))
        _run(h, _idle(), _cp(power_w=2000.0, charging=False), t)
        _run(h, _idle(), _cp(power_w=0.0, charging=False), t + 10)
        assert _values(h) == [ONE_PHASE_VALUE]


# ── 4. a charger that cannot switch reads as on develop ──────────────────

class TestNoWorkingSwitchNoActivePhases:

    def _coord(self, h):
        c = SimpleNamespace(
            config={}, _phase_believed=h._phase_believed,
            _phase_capable=getattr(h, "_phase_capable", {}))
        c._ev_charger_cfg = lambda cid: h.cfg
        cls = coordinator_mod.SEMCoordinator
        c._active_phases_for = cls._active_phases_for.__get__(c)
        return c

    def test_a_missing_entity_keeps_the_configured_count(self):
        h = _host(entity_state=False)
        _run(h, _amps(8, budget=6000.0), _cp(8 * 230.0, True), 0.0)
        assert h._phase_believed["c1"] == 1, "the draw is still measured"
        assert self._coord(h)._active_phases_for("c1") is None
        assert ev_control._phases_now(h, h.cfg, 3) == 3

    def test_a_select_without_its_two_values_keeps_the_configured_count(self):
        h = _host({"ev_phase_switch_entity": "select.wallbox_phases",
                   "ev_phase_switch_value_1p": None,
                   "ev_phase_switch_value_3p": None})
        _run(h, _amps(8, budget=6000.0), _cp(8 * 230.0, True), 0.0)
        assert self._coord(h)._active_phases_for("c1") is None

    def test_a_working_switch_gives_the_measured_count(self):
        h = _host()
        _run(h, _amps(8, budget=6000.0), _cp(8 * 230.0, True), 0.0)
        assert self._coord(h)._active_phases_for("c1") == 1

    def test_no_stop_for_amps_sized_on_the_configured_count(self):
        """No switch, so nothing was sized on a belief: the tick's one-cycle
        stop must not fire either."""
        h = _host(entity_state=False)
        d = _amps(8, budget=6000.0)
        assert _run(h, d, _cp(8 * 230.0, True), 0.0) is d
        assert _run(h, d, _cp(8 * 3 * 230.0, True), 10.0) is d


# ── 5. the value check waits for a real range and a steady misfit ────────

class TestTheValueCheckIsSteady:

    BAD = {"ev_phase_switch_value_1p": "1000", "ev_phase_switch_value_3p": "4000"}

    def test_a_range_of_nothing_is_no_range(self):
        for attrs in ({"min": 0, "max": 0}, {"min": 5, "max": 1}, {},
                      {"min": "x", "max": 3}, {"min": None, "max": 32}):
            st = MagicMock()
            st.attributes = attrs
            assert entity_bounds(st) is None, attrs
        st = MagicMock()
        st.attributes = {"min": 0, "max": 32}
        assert entity_bounds(st) == (0.0, 32.0)

    def test_one_bad_cycle_says_nothing(self):
        h = _host(self.BAD)
        _run(h, _idle(), _cp(), 0.0)
        assert h._phase_switch_states["c1"] != "bad_values"
        assert not (getattr(h, "_phase_values_problem", None) or {}).get("c1")

    def test_a_steady_misfit_is_said(self):
        h = _host(self.BAD)
        for i in range(PHASE_VALUES_STRIKES + 1):
            _run(h, _idle(), _cp(), 10.0 * i)
        assert h._phase_switch_states["c1"] == "bad_values"
        assert "1000" in h._phase_values_problem["c1"]
        assert _values(h) == []

    def test_a_placeholder_range_at_startup_raises_nothing(self):
        """The entity answers 0 to 1 until its first poll; the values 32 and
        0 are right for its real range."""
        h = _host(number_range=(0.0, 1.0))
        for i in range(PHASE_VALUES_STRIKES - 1):
            _run(h, _idle(), _cp(), 10.0 * i)
        h.range = (0.0, 32.0)
        for i in range(PHASE_VALUES_STRIKES + 2):
            _run(h, _idle(), _cp(), 100.0 + 10.0 * i)
        assert h._phase_switch_states["c1"] != "bad_values"
        assert not h._phase_values_problem.get("c1")
        assert h._phase_values_ok["c1"] is True

    def test_a_placeholder_cycle_does_not_drop_a_switch_that_settles(self):
        h = _host({"phase_mode": "1"})
        _run(h, _idle(), _cp(), 0.0)                    # the switch goes out
        assert _values(h) == [ONE_PHASE_VALUE]
        h.range = (0.0, 1.0)
        _run(h, _idle(), _cp(), 20.0)                   # one odd reading
        h.range = (0.0, 32.0)
        _cycles(h, _idle(), _cp(), 30.0, SETTLE_S + 30)
        assert h._phase_believed["c1"] == 1, "the settle was not aborted"

    def test_it_clears_by_itself(self):
        h = _host(self.BAD)
        for i in range(PHASE_VALUES_STRIKES + 1):
            _run(h, _idle(), _cp(), 10.0 * i)
        h.cfg.update({"ev_phase_switch_value_1p": "32",
                      "ev_phase_switch_value_3p": "0"})
        _run(h, _idle(), _cp(), 500.0)
        assert not h._phase_values_problem.get("c1")
        assert h._phase_values_ok["c1"] is True

    def _coord(self, monkeypatch, problem, ok):
        from custom_components.solar_energy_management.coordinator import (
            repair_issues,
        )
        calls_ = {"raised": [], "cleared": []}
        monkeypatch.setattr(
            repair_issues, "raise_charger_control_entity_broken",
            lambda hass, cid, **kw: calls_["raised"].append((cid, kw)))
        monkeypatch.setattr(
            repair_issues, "clear_charger_control_entity_broken",
            lambda hass, cid, eid: calls_["cleared"].append((cid, eid)))
        monkeypatch.setattr(
            coordinator_mod, "charger_display_name", lambda hass, cfg: "Wallbox")
        c = SimpleNamespace(hass=MagicMock())
        c._phase_values_problem = {"c1": problem} if problem else {}
        c._phase_values_ok = {"c1": ok}
        cls = coordinator_mod.SEMCoordinator
        c._CONTROL_CAPABILITIES = cls._CONTROL_CAPABILITIES
        c._PHASE_SWITCH_CAPABILITY = cls._PHASE_SWITCH_CAPABILITY
        c._check_phase_switch_values = cls._check_phase_switch_values.__get__(c)
        cfg = {"id": "c1", "ev_phase_switch_entity": SWITCH,
               "ev_phase_switching_enabled": True}
        return c, cfg, calls_

    def test_the_repair_follows_the_ticks_steady_word(self, monkeypatch):
        c, cfg, calls_ = self._coord(
            monkeypatch, "given 1000 for 1 phase, outside its range 0 to 32", False)
        result = {"charger_c1_phase_switch_valid": True}
        c._check_phase_switch_values("c1", cfg, result)
        c._check_phase_switch_values("c1", cfg, result)
        assert len(calls_["raised"]) == 1
        assert result["charger_c1_phase_switch_valid"] is False

    def test_no_word_from_the_tick_no_repair_and_no_clear(self, monkeypatch):
        c, cfg, calls_ = self._coord(monkeypatch, None, None)
        c._check_phase_switch_values("c1", cfg, {})
        assert not calls_["raised"] and not calls_["cleared"]

    def test_fitting_values_clear_it(self, monkeypatch):
        c, cfg, calls_ = self._coord(monkeypatch, None, True)
        c._check_phase_switch_values("c1", cfg, {})
        c._check_phase_switch_values("c1", cfg, {})
        assert calls_["cleared"] == [("c1", SWITCH)]


# ── 6. one check where the values are written ────────────────────────────

class TestOneCheckForFormsAndCard:

    def _get(self, low=0.0, high=32.0):
        st = MagicMock()
        st.attributes = {"min": low, "max": high}
        return lambda eid: st

    STORED = {"id": "c1", "ev_phase_switch_entity": SWITCH,
              "ev_phase_switch_value_1p": "32", "ev_phase_switch_value_3p": "0"}

    def test_a_typed_value_outside_the_range_is_refused(self):
        after = {**self.STORED, "ev_phase_switch_value_1p": "1000"}
        why = changed_switch_values_problem(self._get(), self.STORED, after)
        assert why and "1000" in why

    def test_the_card_saves_one_value_at_a_time(self):
        """A stored 4000 must not block the fix of the other value."""
        stored = {**self.STORED, "ev_phase_switch_value_1p": "1000",
                  "ev_phase_switch_value_3p": "4000"}
        after = {**stored, "ev_phase_switch_value_1p": "32"}
        assert changed_switch_values_problem(self._get(), stored, after) is None
        after = {**stored, "ev_phase_switch_value_3p": "5000"}
        assert changed_switch_values_problem(self._get(), stored, after)

    def test_an_edit_of_something_else_is_not_blocked(self):
        stored = {**self.STORED, "ev_phase_switch_value_1p": "1000"}
        after = {**stored, "name": "Garage"}
        assert changed_switch_values_problem(self._get(), stored, after) is None

    def test_a_new_charger_is_checked_whole(self):
        after = {**self.STORED, "ev_phase_switch_value_3p": "4000"}
        assert changed_switch_values_problem(self._get(), {}, after)

    def test_no_real_range_no_verdict(self):
        after = {**self.STORED, "ev_phase_switch_value_1p": "1000"}
        assert changed_switch_values_problem(
            self._get(0, 0), self.STORED, after) is None
        assert changed_switch_values_problem(
            lambda eid: None, self.STORED, after) is None

    def test_the_service_and_the_forms_call_the_one_check(self):
        from custom_components.solar_energy_management import config_flow
        import custom_components.solar_energy_management as sem
        assert calls(config_flow._phase_switch_values_misfit,
                     "changed_switch_values_problem")
        assert calls(sem._phase_values_refusal, "changed_switch_values_problem")

    def test_the_service_refuses_by_charger(self):
        import custom_components.solar_energy_management as sem
        hass = SimpleNamespace(states=SimpleNamespace(get=self._get()))
        existing = [dict(self.STORED), {"id": "c2", "name": "Other"}]
        merged = [{**self.STORED, "ev_phase_switch_value_1p": "1000"},
                  {"id": "c2", "name": "Other"}]
        assert sem._phase_values_refusal(hass, existing, merged)
        merged_ok = [{**self.STORED, "ev_phase_switch_value_1p": "16"},
                     {"id": "c2", "name": "Other"}]
        assert sem._phase_values_refusal(hass, existing, merged_ok) is None

    def test_the_refusal_has_a_text(self):
        import json
        from pathlib import Path
        root = Path(ev_control.__file__).resolve().parent.parent
        strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))
        assert "phase_switch_value_out_of_range" in strings["exceptions"]


def test_pytest_is_used():
    assert pytest
