"""#1423 — no phase switch while SEM cannot see whether the charger draws.

Found while fixing #1422. The phase switch asks "is the charger at rest?"
from its charging flag and its power. A dark power sensor reads 0 W, so a
charging box with no status sensor looked at rest: the switch went out with
no stop first, maybe under load.

Now the tick asks the reconciler's own "blind" (no power reading, no status
answer, a car not known gone, no switch reading off). While blind:

* no switch starts — not at rest, not with a stop first;
* a switch already waiting for its stop holds the stop and never fires;
  when the wait runs out still blind, it is dropped without the "gave up"
  warning, and the target is not marked as one the box does not take;
* after such a drop, a switch that needs a stop waits ``BLIND_RETRY_S``
  (a sensor that goes dark whenever the box stops would otherwise get a
  stop and a resume every few minutes), and after ``BLIND_DROPS_MAX`` drops
  in a row none is asked for until the target changes or a new car comes.
  A switch at rest does not wait.

Review: the reader's median kept the dark 0.0 fills, so the first live read
after a dark spell gave 0 W as a reading (``[0, 0, 11040]``): the switch
fired under load one cycle after the sensor came back. ``power_known`` now
stays False while the median stands on dark fills. A status that says
"charging" is a draw (the reader's 500 W floor had turned the flag off), and
a plug sensor that does not read now is no "car gone".
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import logging
from collections import deque
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coordinator_mod,
    ev_control,
)
from custom_components.solar_energy_management.coordinator import (
    reason_codes as RC,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    charger_draws,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    BLIND_DROPS_MAX, BLIND_RETRY_S, MIN_SWITCH_GAP_S, SETTLE_S, STOP_WAIT_S,
    PhaseSwitchSequencer,
)

from .cycle_rig import CycleRig


# ── 1. the sequencer ────────────────────────────────────────────────────


def _seq_tick(seq, t, *, charging=False, blind=False, desired=1, believed=3):
    return seq.tick(now=t, desired_phases=desired, believed_phases=believed,
                    charging=charging, capability_ready=True, blind=blind)


class TestSequencer:

    def test_a_blind_charger_gets_no_switch_at_rest(self):
        seq = PhaseSwitchSequencer()
        for i in range(30):
            r = _seq_tick(seq, 10.0 * i, blind=True)
            assert r.issue_switch is None and r.hold_charging is False
        assert seq._state == "idle"

    def test_the_twin_with_a_reading_switches_at_rest(self):
        seq = PhaseSwitchSequencer()
        r = _seq_tick(seq, 0.0)
        assert r.issue_switch == 1 and r.at_rest is True

    def test_a_draw_seen_wins_over_blind(self):
        """A caller that says both: the draw is the reading. Stop first."""
        seq = PhaseSwitchSequencer()
        r = _seq_tick(seq, 0.0, charging=True, blind=True)
        assert r.state == "stopping" and r.hold_charging is True
        assert r.issue_switch is None

    def test_blind_defaults_to_false(self):
        """A caller that says nothing keeps today's answer."""
        seq = PhaseSwitchSequencer()
        r = seq.tick(now=0.0, desired_phases=1, believed_phases=3,
                     charging=False, capability_ready=True)
        assert r.issue_switch == 1

    def test_a_stop_that_goes_dark_holds_and_never_fires(self):
        seq = PhaseSwitchSequencer()
        assert _seq_tick(seq, 0.0, charging=True).state == "stopping"
        t = 10.0
        while t < STOP_WAIT_S:
            r = _seq_tick(seq, t, blind=True)
            assert r.issue_switch is None, f"fired blind at {t} s"
            assert r.hold_charging is True and r.state == "stopping"
            t += 10.0

    def test_a_reading_after_the_dark_fires_the_switch(self):
        seq = PhaseSwitchSequencer()
        _seq_tick(seq, 0.0, charging=True)
        for t in (10.0, 20.0, 30.0):
            _seq_tick(seq, t, blind=True)
        r = _seq_tick(seq, 40.0)                 # a live 0 W: the stop took
        assert r.issue_switch == 1 and r.at_rest is False

    def test_still_blind_when_the_wait_ends_drops_without_blame(self):
        seq = PhaseSwitchSequencer()
        _seq_tick(seq, 0.0, charging=True)
        t = 10.0
        r = None
        while t <= STOP_WAIT_S:
            r = _seq_tick(seq, t, blind=True)
            t += 10.0
        assert r.blind_drop is True
        assert r.gave_up is False, "no reading said the box drew"
        assert r.hold_charging is False and r.issue_switch is None
        assert seq._state == "idle"

    def test_a_draw_at_the_end_of_the_wait_is_still_gave_up(self):
        """The control: a box that a reading shows drawing after the wait
        is still named, as before."""
        seq = PhaseSwitchSequencer()
        _seq_tick(seq, 0.0, charging=True)
        for t in (10.0, 20.0):
            _seq_tick(seq, t, blind=True)
        r = _seq_tick(seq, STOP_WAIT_S, charging=True)
        assert r.gave_up is True and r.blind_drop is False

    def _dropped(self):
        seq = PhaseSwitchSequencer()
        _seq_tick(seq, 0.0, charging=True)
        t = 10.0
        while t <= STOP_WAIT_S:
            r = _seq_tick(seq, t, blind=True)
            t += 10.0
        assert r.blind_drop is True
        return seq, t - 10.0

    def test_after_a_drop_a_stop_first_switch_waits(self):
        seq, t_drop = self._dropped()
        t = t_drop + 10.0
        while t < t_drop + BLIND_RETRY_S:
            r = _seq_tick(seq, t, charging=True)
            assert r.hold_charging is False and r.state == "idle", (
                f"stopped the charger again {t - t_drop:.0f} s after a drop")
            t += 60.0
        r = _seq_tick(seq, t_drop + BLIND_RETRY_S, charging=True)
        assert r.state == "stopping" and r.hold_charging is True

    def test_after_a_drop_a_switch_at_rest_does_not_wait(self):
        seq, t_drop = self._dropped()
        r = _seq_tick(seq, t_drop + MIN_SWITCH_GAP_S)
        assert r.issue_switch == 1 and r.at_rest is True

    def test_a_switch_sent_settles_while_blind(self):
        """Once the switch went out, blind changes nothing: it settles and
        says its belief once."""
        seq = PhaseSwitchSequencer()
        assert _seq_tick(seq, 0.0).issue_switch == 1
        r = _seq_tick(seq, 10.0, blind=True)
        assert r.state == "settling" and r.hold_charging is True
        r = _seq_tick(seq, SETTLE_S + 10.0, blind=True)
        assert r.believed_phases == 1




class TestTheCap:

    def _drop(self, seq, t, desired=1):
        """A stop, then dark until the wait runs out. Returns the end time."""
        assert _seq_tick(seq, t, charging=True, desired=desired).state == "stopping"
        t += 10.0
        start = t - 10.0
        while t - start <= STOP_WAIT_S:
            r = _seq_tick(seq, t, blind=True, desired=desired)
            t += 10.0
        assert r.blind_drop is True
        return t - 10.0

    def test_after_the_last_drop_no_stop_is_asked_for(self):
        seq = PhaseSwitchSequencer()
        t = 0.0
        for _ in range(BLIND_DROPS_MAX):
            t = self._drop(seq, t) + BLIND_RETRY_S
        assert seq.blind_capped
        for k in range(10):
            r = _seq_tick(seq, t + k * BLIND_RETRY_S, charging=True)
            assert r.state == "idle" and r.hold_charging is False

    def test_a_new_target_counts_again(self):
        seq = PhaseSwitchSequencer()
        t = 0.0
        for _ in range(BLIND_DROPS_MAX):
            t = self._drop(seq, t) + BLIND_RETRY_S
        r = _seq_tick(seq, t, charging=True, desired=3, believed=1)
        assert r.state == "stopping"
        assert not seq.blind_capped

    def test_a_new_car_counts_again(self):
        seq = PhaseSwitchSequencer()
        t = 0.0
        for _ in range(BLIND_DROPS_MAX):
            t = self._drop(seq, t) + BLIND_RETRY_S
        seq.forgive_blind()
        assert _seq_tick(seq, t, charging=True).state == "stopping"

    def test_a_switch_that_goes_out_counts_again(self):
        seq = PhaseSwitchSequencer()
        t = self._drop(seq, 0.0)
        assert seq._blind_drops == 1
        r = _seq_tick(seq, t + MIN_SWITCH_GAP_S)        # at rest, live
        assert r.issue_switch == 1
        assert seq._blind_drops == 0


# ── 2. the per-charger tick ─────────────────────────────────────────────


def _adapter(status=None, enabled=None):
    """A charger adapter with no status sensor (``status`` None), or one
    whose status answers."""
    a = MagicMock()
    a.actual_charging = MagicMock(return_value=bool(status))
    a.is_self_charging = MagicMock(return_value=False)
    a.status_answer = MagicMock(return_value=status)
    a.enable_state = MagicMock(return_value=(enabled, True))
    a.resume_pressable = MagicMock(return_value=False)
    a._device = MagicMock(_current_setpoint=0, contactor_surface=False)
    a._device.can_stop_charging = MagicMock(return_value=True)
    return a


def _host(states=None, **cfg_over):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = False
    h._surplus_controller = None
    h.config = {}
    states = states or {}

    def _get(eid):
        if eid in states:
            return SimpleNamespace(state=states[eid], attributes={})
        return MagicMock()

    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=_get),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    h.cfg = {
        "ev_phase_switch_entity": "number.box_phases",
        "ev_phase_switching_enabled": True,
        "phase_mode": "1",
        "ev_voltage": 230.0, "ev_min_current": 6, "ev_max_current": 16,
    }
    h.cfg.update(cfg_over)
    return h


def _max():
    return ChargerDecision(charger_id="c1", mode="always_max",
                           intent=ChargerIntent.CHARGE_MAX, commanded_amps=0,
                           budget_w=0.0, reason="max")


def _cp(power_w, charging=True, known=True, connected=True):
    return ChargerPower(charger_id="c1", power_w=power_w, connected=connected,
                        charging=charging, power_known=known)


DARK = _cp(0.0, charging=False, known=False)
NO_STATUS = _adapter()


def _tick(h, decision, cp, t, adapter=NO_STATUS, **kw):
    return asyncio.run(h._phase_switch_tick("c1", h.cfg, decision, cp, t,
                                            setpoint_a=16, adapter=adapter,
                                            **kw))


def _calls(h):
    return h.hass.services.async_call.await_count


def _drop(h, t=0.0):
    """A stop under load, then dark until the wait runs out."""
    assert _tick(h, _max(), _cp(11000.0), t).intent is ChargerIntent.DISABLE
    t += 10.0
    end = t + STOP_WAIT_S
    while t < end:
        d = _tick(h, _max(), DARK, t)
        t += 10.0
    return d, t - 10.0


class TestTick:

    def test_the_issue_a_dark_charger_is_not_switched(self):
        """Manual one phase on a charger SEM cannot see: before, the dark
        0 W read as at rest and the switch went out with no stop."""
        h = _host()
        for i in range(20):
            d = _tick(h, _max(), DARK, 10.0 * i)
            assert d.intent is ChargerIntent.CHARGE_MAX, (
                "a blind charger is neither switched nor held")
        assert _calls(h) == 0
        assert h._phase_switch_states["c1"] == "idle"

    def test_the_twin_a_live_0_w_is_switched_at_rest(self):
        h = _host()
        _tick(h, _max(), _cp(0.0, charging=False), 0.0)
        assert _calls(h) == 1

    def test_without_an_adapter_the_power_decides_as_before(self):
        h = _host()
        _tick(h, _max(), DARK, 0.0, adapter=None)
        assert _calls(h) == 1

    def test_a_status_that_says_charging_is_a_draw(self):
        """Review: the power is dark and the status says charging. The
        reader's 500 W floor turned the flag off, so the tick took the box
        as at rest and switched it with no stop."""
        h = _host()
        d = _tick(h, _max(), DARK, 0.0, adapter=_adapter(status=True))
        assert d.intent is ChargerIntent.DISABLE, "stop first"
        assert h._phase_switch_states["c1"] == "stopping"
        assert _calls(h) == 0

    def test_a_live_0_w_keeps_deciding_beside_a_charging_status(self):
        """Review 2: the status counts only while the power is dark. A
        status stuck on charging beside a live 0 W changes nothing."""
        h = _host()
        _tick(h, _max(), _cp(0.0, charging=False), 0.0,
              adapter=_adapter(status=True))
        assert _calls(h) == 1

    def test_a_status_that_says_not_charging_is_at_rest(self):
        h = _host()
        _tick(h, _max(), DARK, 0.0, adapter=_adapter(status=False))
        assert _calls(h) == 1

    def test_a_dark_plug_sensor_is_no_car_gone(self):
        """Review: a whole integration drops out — power and plug both
        "unavailable". The plug sensor is configured, so the reading said
        "no car known", and the box was switched with no stop."""
        h = _host(states={"binary_sensor.box_plug": "unavailable"},
                  ev_connected_sensor="binary_sensor.box_plug")
        cp = _cp(0.0, charging=False, known=False, connected=False)
        for i in range(10):
            _tick(h, _max(), cp, 10.0 * i)
        assert _calls(h) == 0

    def test_a_plug_sensor_that_says_no_car_is_at_rest(self):
        h = _host(states={"binary_sensor.box_plug": "off"},
                  ev_connected_sensor="binary_sensor.box_plug")
        cp = _cp(0.0, charging=False, known=False, connected=False)
        _tick(h, _max(), cp, 0.0)
        assert _calls(h) == 1

    def test_a_stop_that_goes_dark_is_dropped_without_blame(self, caplog):
        h = _host()
        with caplog.at_level(logging.INFO):
            d, _t = _drop(h)
        assert _calls(h) == 0, "switched with no reading that the stop took"
        assert d.intent is ChargerIntent.CHARGE_MAX, "the hold ended"
        assert h._phase_switch_states["c1"] == "idle"
        assert h._phase_contradictions["c1"]["count"] == 0, "blamed the box"
        assert not any("gave up" in r.getMessage() for r in caplog.records)
        assert any("#1423" in r.getMessage() and "dropped" in r.getMessage()
                   for r in caplog.records)

    def test_a_drop_holds_the_next_stop_for_the_retry_time(self):
        h = _host()
        _d, t_drop = _drop(h)
        t = t_drop + 10.0
        while t < t_drop + BLIND_RETRY_S:
            d = _tick(h, _max(), _cp(11000.0), t)
            assert d.intent is ChargerIntent.CHARGE_MAX
            t += 60.0
        d = _tick(h, _max(), _cp(11000.0), t_drop + BLIND_RETRY_S)
        assert d.intent is ChargerIntent.DISABLE

    def test_the_cap_is_said_once_and_shown(self, caplog):
        h = _host()
        t = 0.0
        with caplog.at_level(logging.INFO):
            for _ in range(BLIND_DROPS_MAX):
                _d, t = _drop(h, t)
                t += BLIND_RETRY_S
        warn = [r for r in caplog.records if r.levelno == logging.WARNING
                and "#1423" in r.getMessage()]
        assert len(warn) == 1, [r.getMessage() for r in caplog.records]
        for k in range(5):
            d = _tick(h, _max(), _cp(11000.0), t + k * BLIND_RETRY_S)
            assert d.intent is ChargerIntent.CHARGE_MAX
        assert h._phase_switch_states["c1"] == "no_reading"
        assert _calls(h) == 0

    def test_a_known_unplug_counts_again(self):
        """In auto mode no target is set without a car, so only the known
        unplug clears the count (review 2: manual mode cleared it by the
        switch that then went out at rest)."""
        h = _host(states={"binary_sensor.box_plug": "off"},
                  ev_connected_sensor="binary_sensor.box_plug",
                  phase_mode="auto")
        _tick(h, _max(), DARK, 0.0)
        seq = h._phase_sequencers["c1"]
        seq._blind_drops, seq._blind_target = BLIND_DROPS_MAX, 1
        gone = _cp(0.0, charging=False, connected=False)
        for k in range(2):
            _tick(h, _max(), gone, 10.0 + 10.0 * k, adapter=None)
        assert seq.blind_capped, "not yet: the unplug must hold 30 s"
        for k in range(2, 6):
            _tick(h, _max(), gone, 10.0 + 10.0 * k, adapter=None)
        assert not seq.blind_capped
        assert _calls(h) == 0, "cleared by the unplug, not by a switch"

    def test_observer_mode_drops_do_not_count(self, caplog):
        """Review 2: observer mode sends no stop, so a drop says nothing
        about the sensor: no cap, no warning."""
        h = _host()
        h._observer_mode = True
        t = 0.0
        with caplog.at_level(logging.INFO):
            for _ in range(BLIND_DROPS_MAX + 1):
                _d, t = _drop(h, t)
                t += BLIND_RETRY_S
        assert not h._phase_sequencers["c1"].blind_capped
        assert not [r for r in caplog.records
                    if r.levelno == logging.WARNING and "#1423" in r.getMessage()]

    def test_a_stop_that_takes_after_a_dark_spell_switches(self):
        h = _host()
        _tick(h, _max(), _cp(11000.0), 0.0)
        for t in (10.0, 20.0, 30.0):
            d = _tick(h, _max(), DARK, t)
            assert d.intent is ChargerIntent.DISABLE, "the stop holds"
        _tick(h, _max(), _cp(0.0, charging=False), 40.0)
        assert _calls(h) == 1

    def test_the_night_return_waits_for_a_reading(self):
        """SEM's own one phase goes back to three before a grid charge —
        at rest only, and a dark 0 W is not at rest."""
        def _own_one_phase():
            h = _host(phase_mode="auto", ev_phases=3)
            h._phase_sequencers, h._phase_planners = {}, {}
            h._phase_conn_memo = {"c1": True}
            h._phase_switch_states = {}
            h._phase_believed = {"c1": 1}
            h._phase_set_by_sem = {"c1": 1}
            return h

        top_up = ChargerDecision(
            charger_id="c1", mode="solar_plus_cheap",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=6,
            budget_w=0.0, reason="top up", reason_code=RC.CHARGER_TOP_UP)
        h = _own_one_phase()
        for i in range(10):
            _tick(h, top_up, DARK, 10.0 * i, is_night=True)
        assert _calls(h) == 0
        h = _own_one_phase()
        _tick(h, top_up, _cp(0.0, charging=False), 0.0, is_night=True)
        assert _calls(h) == 1, "the twin: a live 0 W goes back to three"

    def test_a_charger_set_by_current_is_not_switched_blind(self, monkeypatch):
        """The same gate for a charger that sets its phases by one current
        per phase (no switch entity): no ``switch_phases`` while blind."""
        h = _host()
        del h.cfg["ev_phase_switch_entity"]
        dev = SimpleNamespace(
            switch_phases=AsyncMock(return_value=True),
            phase_service="x.set_circuit", external_yield=False,
            phase_readback=lambda: None)
        monkeypatch.setattr(ev_control, "_phase_by_current_ready",
                            lambda *a, **k: True)
        for i in range(10):
            asyncio.run(h._phase_switch_tick(
                "c1", h.cfg, _max(), DARK, 10.0 * i, setpoint_a=16,
                device=dev, adapter=NO_STATUS))
        assert dev.switch_phases.await_count == 0
        asyncio.run(h._phase_switch_tick(
            "c1", h.cfg, _max(), _cp(0.0, charging=False), 200.0,
            setpoint_a=16, device=dev, adapter=NO_STATUS))
        assert dev.switch_phases.await_count == 1, "the twin"


# ── 3. the one reading: the reconciler's ───────────────────────────────


def _power(*, known=False, connected=True, plug_known=True, charging=False):
    return ChargerPower(charger_id="c1", power_w=0.0, connected=connected,
                        charging=charging, plug_known=plug_known,
                        power_known=known)


class TestChargerDraws:

    def test_dark_with_no_status_is_no_reading(self):
        assert charger_draws(_adapter(), _power()) is None

    def test_answers(self):
        assert charger_draws(_adapter(), _power(known=True)) is False
        assert charger_draws(_adapter(status=False), _power()) is False
        assert charger_draws(_adapter(status=True), _power()) is True
        # a readable switch that reads off: that box cannot draw
        assert charger_draws(_adapter(enabled=False), _power()) is False
        # a car known gone
        assert charger_draws(_adapter(), _power(connected=False)) is False
        # the brand's own flag says it charges
        assert charger_draws(_adapter(), _power(charging=True)) is True

    def test_a_plug_that_does_not_read_is_no_answer(self):
        p = _power(connected=False)
        assert charger_draws(_adapter(), p, plug_reading_known=False) is None
        # …but a status that answers still does
        assert charger_draws(_adapter(status=False), p,
                             plug_reading_known=False) is False

    def test_an_unknown_plug_is_no_reading(self):
        """No plug sensor and no draw: the car is not known gone."""
        p = _power(connected=False, plug_known=False)
        assert charger_draws(_adapter(), p) is None

    def test_an_adapter_that_cannot_be_read(self):
        a = _adapter()
        a.actual_charging = MagicMock(side_effect=RuntimeError("boom"))
        assert charger_draws(a, _power()) is None
        assert charger_draws(a, _power(known=True)) is False


def test_the_cycle_passes_the_adapter_to_the_tick():
    """AST pin: the one call of ``_phase_switch_tick`` in the cycle passes
    this charger's adapter, so the tick asks the reconciler's reading."""
    tree = ast.parse(inspect.getsource(coordinator_mod))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_phase_switch_tick"]
    assert len(calls) == 1
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "adapter" in kw, "the cycle does not give the tick its adapter"
    assert ast.unparse(kw["adapter"]) == "adapter"
    assert ast.unparse(calls[0].args[3]) == "view.power"


# ── 4. the reader: a median on dark fills is no reading ─────────────────


def _reader():
    from custom_components.solar_energy_management.coordinator.sensor_reader import (
        SensorReader,
    )
    r = SensorReader.__new__(SensorReader)
    r._ev_power_hist, r._ev_power_last, r._ev_power_hold = {}, {}, {}
    return r


class TestReaderKnown:

    def _feed(self, r, seq, key="c1"):
        out = []
        for raw in seq:
            w = r._smooth_ev_power(0.0 if raw is None else raw, key=key,
                                   live=raw is not None)
            out.append((w, r._ev_power_known(key, raw)))
        return out

    def test_the_first_live_read_after_two_dark_is_no_reading(self):
        r = _reader()
        out = self._feed(r, [11040.0, None, None, 11040.0, 11040.0])
        assert out[3] == (0.0, False), "median of [0, 0, 11040] is no reading"
        assert out[4] == (11040.0, True)

    def test_one_dark_blip_keeps_the_live_median(self):
        r = _reader()
        out = self._feed(r, [11040.0, 11040.0, None, 11040.0])
        assert out[2] == (11040.0, False), "this cycle's read was dark"
        assert out[3] == (11040.0, True)

    def test_a_real_stop_is_a_reading(self):
        r = _reader()
        out = self._feed(r, [11040.0, 11040.0, 0.0, 0.0])
        assert out[3] == (0.0, True)

    def test_two_live_0_beside_a_dark_fill_are_a_reading(self):
        r = _reader()
        out = self._feed(r, [11040.0, None, 0.0, 0.0])
        assert out[3] == (0.0, True), "two live 0 W reads: a stop"

    def test_a_0_w_blip_right_after_a_dark_spell_is_no_reading(self):
        """Review 2: ``[0, 0, 0]`` with one live 0 W — the blip the median
        is for (#910) — read as a stop while the box drew 11 kW."""
        r = _reader()
        out = self._feed(r, [11040.0, 11040.0, None, None, 0.0, 11040.0,
                             11040.0])
        assert out[4] == (0.0, False)
        assert out[5] == (0.0, False)
        assert out[6] == (11040.0, True)

    def test_a_history_made_elsewhere_counts_as_read(self):
        r = _reader()
        r._ev_power_hist["c1"] = deque([0.0, 0.0], maxlen=3)
        out = self._feed(r, [0.0])
        assert out[0] == (0.0, True)

    def test_the_reader_flags_a_median_on_dark_fills(self):
        """Through the per-charger read: the flag the view reads."""
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        r = _reader()
        seen = []
        r._read_binary_sensor = lambda *a, **k: None
        for cur in [11040.0, None, None, 11040.0, 11040.0]:
            r._read_sensor = lambda *a, _c=cur, **k: _c
            pr = PowerReadings()
            r._read_ev_fleet_power(pr, [{
                "id": "c1", "ev_charging_power_sensor": "sensor.c1"}])
            seen.append((pr.ev_power_per_charger["c1"],
                         pr.ev_power_per_charger_read["c1"]))
        assert seen[3] == (0.0, False)
        assert seen[4] == (11040.0, True)

    def test_the_fleet_sensor_flags_a_median_on_dark_fills(self):
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        r = _reader()
        r.config = SimpleNamespace(ev_charging_sensor=None)
        seen = []
        for cur in [11040.0, None, None, 11040.0, 11040.0]:
            r._read_sensor = lambda *a, _c=cur, **k: _c
            pr = PowerReadings()
            w = r._smoothed_fleet_ev_sensor(pr, "sensor.ev")
            seen.append((w, pr.ev_power_fleet_read))
        assert seen[3] == (0.0, False)
        assert seen[4] == (11040.0, True)


# ── 5. the issue's case through the real cycle ──────────────────────────

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 10.0,
    "battery_reserve_soc": 20,
}

SWITCH = "number.box_phases"


def _rig():
    """One charger SEM steers, phase switching on, one phase by hand, no
    status sensor."""
    charger = {
        "id": "box", "name": "box", "ev_min_current": 6,
        "ev_max_current": 16, "ev_phases": 3, "ev_voltage": 230,
        "ev_current_control_entity": "number.box_current",
        "ev_connected_sensor": "binary_sensor.box_connected",
        "ev_power_sensor": "sensor.box_power",
        "ev_charging_power_sensor": "sensor.box_power",
        "charge_mode": "always_max", "priority": 1,
        "ev_target_type": "kwh", "daily_ev_target": 10,
        "ev_phase_switch_entity": SWITCH,
        "ev_phase_switching_enabled": True,
        "phase_mode": "1",
    }
    rig = CycleRig(config=dict(WIRED), chargers=[charger])
    rig.coord._ev_devices["box"].start_stop_entity = "switch.box_enable"
    return rig


def _values(box_power, plug="on"):
    return {
        "sensor.solar": 0.0, "sensor.batt": 0.0, "sensor.soc": 40.0,
        "sensor.grid": -11000.0, "sensor.ev": 11000.0,
        "sensor.box_power": box_power,
        "binary_sensor.box_connected": plug,
        "switch.box_enable": "on",
        "number.box_current": 16,
        SWITCH: (3, {"min": 1, "max": 3, "step": 1}),
    }


def _switches(rig):
    return [c for c in rig.calls
            if (c[2] or {}).get("entity_id") == SWITCH]


T0 = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc).timestamp()


async def _run(rig, freezer, powers, plug="on"):
    """One cycle per entry of ``powers``, 10 s apart."""
    t = T0
    for p in powers:
        freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))
        for eid, val in _values(p, plug).items():
            rig.hass.states.set(eid, val)
        await rig.coord._async_update_data()
        t += 10


@pytest.mark.asyncio
async def test_the_dark_box_gets_no_phase_switch_in_the_real_cycle(freezer):
    """The box's power sensor is "unavailable" and it has no status
    sensor. Before: the dark 0 W read as at rest and the one-phase write
    went out with no stop first."""
    rig = _rig()
    await _run(rig, freezer, ["unavailable"] * 6)
    assert _switches(rig) == [], _switches(rig)
    assert rig.coord._phase_switch_states.get("box") == "idle"


@pytest.mark.asyncio
async def test_the_twin_a_live_0_w_box_is_switched_at_rest(freezer):
    rig = _rig()
    await _run(rig, freezer, [0.0] * 6)
    assert len(_switches(rig)) == 1, rig.calls


@pytest.mark.asyncio
async def test_the_sensor_comes_back_drawing(freezer):
    """Review: dark for six cycles while the box draws 11 kW, then the
    sensor is back. The median of ``[0, 0, 11040]`` gave 0 W as a reading
    and the switch went out under load. Now the box is stopped first, and
    while it draws nothing is switched."""
    rig = _rig()
    await _run(rig, freezer, ["unavailable"] * 6 + [11040.0] * 6)
    assert _switches(rig) == [], _switches(rig)
    assert rig.coord._phase_switch_states.get("box") == "stopping"


@pytest.mark.asyncio
async def test_a_stop_that_goes_dark_and_comes_back_drawing(freezer):
    """Review: the stop is held, the sensor goes dark, then comes back
    with the box still drawing. Nothing is switched under load."""
    rig = _rig()
    await _run(rig, freezer,
               [11040.0] * 3 + ["unavailable"] * 4 + [11040.0] * 4)
    assert _switches(rig) == [], _switches(rig)


@pytest.mark.asyncio
async def test_a_0_w_blip_after_the_dark_spell(freezer):
    """Review 2: one 0 W read right after the dark spell, then the box
    draws 11 kW again. Before, that 0 W read as a stop and the switch went
    out with the box drawing."""
    rig = _rig()
    await _run(rig, freezer,
               ["unavailable"] * 6 + [0.0] + [11040.0] * 4)
    assert _switches(rig) == [], _switches(rig)


@pytest.mark.asyncio
async def test_power_and_plug_both_dark(freezer):
    """Review: the whole integration drops out. A plug sensor that does not
    read is no "car gone": no switch."""
    rig = _rig()
    await _run(rig, freezer, ["unavailable"] * 6, plug="unavailable")
    assert _switches(rig) == [], _switches(rig)
