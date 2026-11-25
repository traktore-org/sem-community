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
  stop and a resume every few minutes). A switch at rest does not wait.
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import logging
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
    charger_blind,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    BLIND_RETRY_S, MIN_SWITCH_GAP_S, SETTLE_S, STOP_WAIT_S,
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


# ── 2. the per-charger tick ─────────────────────────────────────────────


def _host(**cfg_over):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = False
    h._surplus_controller = None
    h.config = {}
    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: MagicMock()),
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


def _cp(power_w, charging=True, known=True):
    return ChargerPower(charger_id="c1", power_w=power_w, connected=True,
                        charging=charging, power_known=known)


DARK = _cp(0.0, charging=False, known=False)


def _tick(h, decision, cp, t, blind=False, **kw):
    return asyncio.run(h._phase_switch_tick("c1", h.cfg, decision, cp, t,
                                            setpoint_a=16, blind=blind, **kw))


def _calls(h):
    return h.hass.services.async_call.await_count


class TestTick:

    def test_the_issue_a_dark_charger_is_not_switched(self):
        """Manual one phase on a charger SEM cannot see: before, the dark
        0 W read as at rest and the switch went out with no stop."""
        h = _host()
        for i in range(20):
            d = _tick(h, _max(), DARK, 10.0 * i, blind=True)
            assert d.intent is ChargerIntent.CHARGE_MAX, (
                "a blind charger is neither switched nor held")
        assert _calls(h) == 0
        assert h._phase_switch_states["c1"] == "idle"

    def test_the_twin_a_live_0_w_is_switched_at_rest(self):
        h = _host()
        _tick(h, _max(), _cp(0.0, charging=False), 0.0)
        assert _calls(h) == 1

    def test_a_draw_wins_over_a_blind_word(self):
        """The power still shows a draw: stop first, as before."""
        h = _host()
        d = _tick(h, _max(), _cp(11000.0), 0.0, blind=True)
        assert d.intent is ChargerIntent.DISABLE
        assert h._phase_switch_states["c1"] == "stopping"
        assert _calls(h) == 0

    def test_a_stop_that_goes_dark_is_dropped_without_blame(self, caplog):
        h = _host()
        assert _tick(h, _max(), _cp(11000.0), 0.0).intent is ChargerIntent.DISABLE
        t = 10.0
        with caplog.at_level(logging.INFO):
            while t <= STOP_WAIT_S:
                d = _tick(h, _max(), DARK, t, blind=True)
                t += 10.0
        assert _calls(h) == 0, "switched with no reading that the stop took"
        assert d.intent is ChargerIntent.CHARGE_MAX, "the hold ended"
        assert h._phase_switch_states["c1"] == "idle"
        assert h._phase_contradictions["c1"]["count"] == 0, "blamed the box"
        assert not any("gave up" in r.getMessage() for r in caplog.records)
        assert any("#1423" in r.getMessage() and "dropped" in r.getMessage()
                   for r in caplog.records)

    def test_a_drop_holds_the_next_stop_for_the_retry_time(self):
        h = _host()
        _tick(h, _max(), _cp(11000.0), 0.0)
        t = 10.0
        while t <= STOP_WAIT_S:
            _tick(h, _max(), DARK, t, blind=True)
            t += 10.0
        t_drop = t - 10.0
        # the reading comes back with the car drawing: no new stop yet
        t = t_drop + 10.0
        while t < t_drop + BLIND_RETRY_S:
            d = _tick(h, _max(), _cp(11000.0), t)
            assert d.intent is ChargerIntent.CHARGE_MAX
            t += 60.0
        d = _tick(h, _max(), _cp(11000.0), t_drop + BLIND_RETRY_S)
        assert d.intent is ChargerIntent.DISABLE

    def test_a_stop_that_takes_after_a_dark_spell_switches(self):
        h = _host()
        _tick(h, _max(), _cp(11000.0), 0.0)
        for t in (10.0, 20.0, 30.0):
            d = _tick(h, _max(), DARK, t, blind=True)
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
            _tick(h, top_up, DARK, 10.0 * i, blind=True, is_night=True)
        assert _calls(h) == 0
        h = _own_one_phase()
        _tick(h, top_up, _cp(0.0, charging=False), 0.0, is_night=True)
        assert _calls(h) == 1, "the twin: a live 0 W goes back to three"


# ── 3. the one blind: the reconciler's ─────────────────────────────────


def _adapter(status=None, enabled=None):
    a = MagicMock()
    a.actual_charging = MagicMock(return_value=bool(status))
    a.is_self_charging = MagicMock(return_value=False)
    a.status_answer = MagicMock(return_value=status)
    a.enable_state = MagicMock(return_value=(enabled, True))
    a.resume_pressable = MagicMock(return_value=False)
    a._device = MagicMock(_current_setpoint=0, contactor_surface=False)
    a._device.can_stop_charging = MagicMock(return_value=True)
    return a


def _power(*, known=False, connected=True, plug_known=True, charging=False):
    return ChargerPower(charger_id="c1", power_w=0.0, connected=connected,
                        charging=charging, plug_known=plug_known,
                        power_known=known)


class TestChargerBlind:

    def test_dark_with_no_status_is_blind(self):
        assert charger_blind(_adapter(), _power()) is True

    def test_answers_that_are_not_blind(self):
        assert charger_blind(_adapter(), _power(known=True)) is False
        assert charger_blind(_adapter(status=False), _power()) is False
        assert charger_blind(_adapter(status=True), _power()) is False
        # a readable switch that reads off: that box cannot draw
        assert charger_blind(_adapter(enabled=False), _power()) is False
        # a car known gone
        assert charger_blind(_adapter(), _power(connected=False)) is False
        # the brand's own flag says it charges: a draw, not blindness
        assert charger_blind(_adapter(), _power(charging=True)) is False

    def test_an_unknown_plug_is_still_blind(self):
        """No plug sensor and no draw: the car is not known gone."""
        p = _power(connected=False, plug_known=False)
        assert charger_blind(_adapter(), p) is True

    def test_an_adapter_that_cannot_be_read_counts_a_dark_read_as_blind(self):
        a = _adapter()
        a.actual_charging = MagicMock(side_effect=RuntimeError("boom"))
        assert charger_blind(a, _power()) is True
        assert charger_blind(a, _power(known=True)) is False


def test_the_cycle_passes_the_reconcilers_blind_to_the_tick():
    """AST pin: the one call of ``_phase_switch_tick`` in the cycle passes
    ``blind=_charger_blind(adapter, view.power)`` — the same word the
    reconciler acts on, for the same charger."""
    tree = ast.parse(inspect.getsource(coordinator_mod))
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Attribute)
             and n.func.attr == "_phase_switch_tick"]
    assert len(calls) == 1
    kw = {k.arg: k.value for k in calls[0].keywords}
    assert "blind" in kw, "the cycle does not tell the tick it is blind"
    v = kw["blind"]
    assert isinstance(v, ast.Call) and getattr(v.func, "id", "") == "_charger_blind"
    assert [ast.unparse(a) for a in v.args] == ["adapter", "view.power"]


# ── 4. the issue's case through the real cycle ──────────────────────────

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


def _values(box_power):
    return {
        "sensor.solar": 0.0, "sensor.batt": 0.0, "sensor.soc": 40.0,
        "sensor.grid": -11000.0, "sensor.ev": 11000.0,
        "sensor.box_power": box_power,
        "binary_sensor.box_connected": "on",
        "switch.box_enable": "on",
        "number.box_current": 16,
        SWITCH: (3, {"min": 1, "max": 3, "step": 1}),
    }


def _switches(rig):
    return [c for c in rig.calls
            if (c[2] or {}).get("entity_id") == SWITCH]


T0 = datetime(2026, 11, 25, 12, 0, tzinfo=timezone.utc).timestamp()


async def _run(rig, freezer, box_power, cycles):
    t = T0
    for _ in range(cycles):
        freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))
        for eid, val in _values(box_power).items():
            rig.hass.states.set(eid, val)
        await rig.coord._async_update_data()
        t += 10


@pytest.mark.asyncio
async def test_the_dark_box_gets_no_phase_switch_in_the_real_cycle(freezer):
    """The box's power sensor is "unavailable" and it has no status
    sensor. Before: the dark 0 W read as at rest and the one-phase write
    went out with no stop first."""
    rig = _rig()
    await _run(rig, freezer, "unavailable", cycles=6)
    assert _switches(rig) == [], _switches(rig)
    assert rig.coord._phase_switch_states.get("box") == "idle"


@pytest.mark.asyncio
async def test_the_twin_a_live_0_w_box_is_switched_at_rest(freezer):
    rig = _rig()
    await _run(rig, freezer, 0.0, cycles=6)
    assert len(_switches(rig)) == 1, rig.calls
