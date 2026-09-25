"""(#1008) Always (max) must be able to ask for three phases.

coppe218, Zaptec + Phase mode Auto: the car charged on ONE phase at 16 A
(~3.3 kW) and stayed there. ``AlwaysMaxMode`` sets ``budget_w = 0.0``
because the mode is not budget-limited — the field says "not
applicable", not "no power". The phase auto planner read it as watts, so
it saw no headroom: it never scaled up, and a three-phase session would
have scaled DOWN ten minutes in.

The planner now asks what the charger may DRAW. Under ``CHARGE_MAX``
that is the charger's own ceiling, priced at three phases, with the grid
paying for whatever the sun does not.
"""
import ast
import asyncio
import inspect
import textwrap
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import ev_control
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision, ChargerIntent, ChargerPower,
)
from custom_components.solar_energy_management.coordinator.ev_phase_sequencer import (
    AUTO_DOWN_DELAY_S, AUTO_MIN_INTERVAL_S, AUTO_UP_DELAY_S, SETTLE_S,
)

from . import ast_contracts

VOLTS = 230.0


def _host(**cfg_over):
    h = SimpleNamespace()
    h._phase_switch_tick = ev_control.EVControlMixin._phase_switch_tick.__get__(h)
    h._observer_mode = False
    h._surplus_controller = None
    h.config = {}
    sun = MagicMock()
    h.hass = SimpleNamespace(
        states=SimpleNamespace(get=lambda eid: sun),
        services=SimpleNamespace(async_call=AsyncMock()),
    )
    h.cfg = {
        "ev_phase_switch_entity": "number.wallbox_phases",
        "ev_phase_switching_enabled": True,   # woken (#804)
        "phase_mode": "auto",
        "ev_voltage": VOLTS,
        "ev_min_current": 6,
        "ev_max_current": 16,
    }
    h.cfg.update(cfg_over)
    return h


def _max_decision():
    return ChargerDecision(
        charger_id="c1", mode="always_max",
        intent=ChargerIntent.CHARGE_MAX,
        commanded_amps=0,
        budget_w=0.0,          # the mode is not budget-limited
        reason="always_max mode — charge at hardware maximum",
    )


def _amps_decision(budget_w):
    return ChargerDecision(
        charger_id="c1", mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=10, budget_w=budget_w, reason="surplus",
    )


def _cp(power_w, charging=True):
    return ChargerPower(charger_id="c1", power_w=power_w,
                        connected=True, charging=charging)


def _tick(h, decision, cp, t, setpoint_a=16, peak_allowed_w=None):
    return asyncio.run(h._phase_switch_tick(
        "c1", h.cfg, decision, cp, t, setpoint_a=setpoint_a,
        peak_allowed_w=peak_allowed_w))


def _idle_decision():
    return ChargerDecision(
        charger_id="c1", mode="always_max",
        intent=ChargerIntent.IDLE, commanded_amps=0, budget_w=0.0,
        reason="always_max mode but EV disconnected",
    )


class TestAlwaysMaxAsksForThreePhases:

    def test_one_phase_scales_up(self):
        """The reported case: 16 A on one phase, Auto, and it stayed."""
        h = _host()
        # 3680 W at a 16 A offer → the W/A estimate reads one phase.
        _tick(h, _max_decision(), _cp(3680.0), 0.0)
        assert h._phase_believed["c1"] == 1
        d = _tick(h, _max_decision(), _cp(3680.0), AUTO_UP_DELAY_S + 1)
        assert d.intent is ChargerIntent.DISABLE, (
            "sustained headroom → the sequencer stops before switching")
        # draw gone → the switch fires, to three
        _tick(h, _max_decision(), _cp(0.0, charging=False),
              AUTO_UP_DELAY_S + 11)
        h.hass.services.async_call.assert_awaited_once()
        call = h.hass.services.async_call.await_args
        assert call.args[2] == {
            "entity_id": "number.wallbox_phases", "value": 3.0}

    def test_three_phases_are_not_scaled_back_down(self):
        h = _host()
        # 11040 W at 16 A → three phases
        _tick(h, _max_decision(), _cp(11040.0), 0.0)
        assert h._phase_believed["c1"] == 3
        for t in (60.0, AUTO_DOWN_DELAY_S + 1, AUTO_DOWN_DELAY_S + 300):
            d = _tick(h, _max_decision(), _cp(11040.0), t)
            assert d.intent is ChargerIntent.CHARGE_MAX, (
                f"always_max was scaled down at t={t}")
        h.hass.services.async_call.assert_not_awaited()

    def test_a_ceiling_that_buys_no_headroom_stays_on_one_phase(self):
        """6 A max is exactly the three-phase minimum — no margin, no switch."""
        h = _host(ev_max_current=6)
        _tick(h, _max_decision(), _cp(1380.0), 0.0, setpoint_a=6)
        assert h._phase_believed["c1"] == 1
        _tick(h, _max_decision(), _cp(1380.0), AUTO_UP_DELAY_S + 1,
              setpoint_a=6)
        h.hass.services.async_call.assert_not_awaited()


class TestTheSolarBudgetStillGoverns:

    def test_a_small_surplus_does_not_switch_up(self):
        h = _host()
        _tick(h, _amps_decision(1000.0), _cp(2300.0), 0.0, setpoint_a=10)
        assert h._phase_believed["c1"] == 1
        _tick(h, _amps_decision(1000.0), _cp(2300.0), AUTO_UP_DELAY_S + 1,
              setpoint_a=10)
        h.hass.services.async_call.assert_not_awaited()

    def test_a_peak_clamped_always_max_reads_the_clamp(self):
        """The peak guard turns CHARGE_MAX into amps + a real budget, so the
        planner reads the clamp and not the ceiling. 6 A on a 3-phase config
        prices at 4140 W — under the 4554 W the switch needs."""
        h = _host()
        clamped = ChargerDecision(
            charger_id="c1", mode="always_max",
            intent=ChargerIntent.CHARGE_AT_AMPS,
            commanded_amps=6, budget_w=4140.0,
            reason="always_max [peak slot guard: 4200W headroom → 6A]",
        )
        _tick(h, clamped, _cp(1380.0), 0.0, setpoint_a=6)
        assert h._phase_believed["c1"] == 1
        _tick(h, clamped, _cp(1380.0), AUTO_UP_DELAY_S + 1, setpoint_a=6)
        h.hass.services.async_call.assert_not_awaited()

    def test_a_slot_the_meter_cannot_pay_for_does_not_switch_up(self):
        """CHARGE_MAX survives the guard when the clamp is priced with a
        1-phase config, so the slot allowance caps the offer here."""
        h = _host()
        _tick(h, _max_decision(), _cp(3680.0), 0.0, peak_allowed_w=3000.0)
        assert h._phase_believed["c1"] == 1
        for t in (AUTO_UP_DELAY_S + 1, AUTO_UP_DELAY_S + 600):
            d = _tick(h, _max_decision(), _cp(3680.0), t,
                      peak_allowed_w=3000.0)
            # CHARGE_MAX, not DISABLE: the sequencer was never even asked to
            # stop. Waiting for the service call would pass either way — the
            # call comes a cycle later, after the draw has gone.
            assert d.intent is ChargerIntent.CHARGE_MAX, (
                f"asked for three phases the meter cannot pay for (t={t})")
        h.hass.services.async_call.assert_not_awaited()
        # a slot that CAN pay still switches
        base = AUTO_UP_DELAY_S + 601
        _tick(h, _max_decision(), _cp(3680.0), base, peak_allowed_w=9000.0)
        d = _tick(h, _max_decision(), _cp(3680.0), base + AUTO_UP_DELAY_S + 1,
                  peak_allowed_w=9000.0)
        assert d.intent is ChargerIntent.DISABLE

    def test_an_absent_slot_limit_does_not_cap(self):
        """No peak target configured → the allowance is None, not zero."""
        got = ev_control._power_on_offer_w(
            _max_decision(), {"ev_max_current": 16}, {}, VOLTS,
            peak_allowed_w=None)
        assert got == pytest.approx(11040.0)
        capped = ev_control._power_on_offer_w(
            _max_decision(), {"ev_max_current": 16}, {}, VOLTS,
            peak_allowed_w=3000.0)
        assert capped == pytest.approx(3000.0)

    def test_a_large_surplus_still_switches_up(self):
        h = _host()
        _tick(h, _amps_decision(9000.0), _cp(2300.0), 0.0, setpoint_a=10)
        d = _tick(h, _amps_decision(9000.0), _cp(2300.0),
                  AUTO_UP_DELAY_S + 1, setpoint_a=10)
        assert d.intent is ChargerIntent.DISABLE


class TestPowerOnOffer:

    @pytest.mark.parametrize("max_a,expected", [(16, 11040.0), (6, 4140.0),
                                                (32, 22080.0)])
    def test_charge_max_is_the_ceiling_at_three_phases(self, max_a, expected):
        got = ev_control._power_on_offer_w(
            _max_decision(), {"ev_max_current": max_a}, {}, VOLTS)
        assert got == pytest.approx(expected)

    def test_the_charger_row_wins_over_the_global_one(self):
        got = ev_control._power_on_offer_w(
            _max_decision(), {"ev_max_current": 16}, {"ev_max_current": 32},
            VOLTS)
        assert got == pytest.approx(11040.0)

    def test_an_unconfigured_charger_falls_back(self):
        got = ev_control._power_on_offer_w(_max_decision(), {}, {}, VOLTS)
        assert got > 0.0, "no ceiling configured must not read as no power"

    def test_amps_decisions_keep_their_budget(self):
        got = ev_control._power_on_offer_w(
            _amps_decision(4600.0), {"ev_max_current": 16}, {}, VOLTS)
        assert got == pytest.approx(4600.0)


class TestNoCarNoQuestion:
    """(#1008 review) A parked charger is not starving — it is parked."""

    def test_an_unplugged_three_phase_charger_is_left_alone(self):
        h = _host()
        _tick(h, _max_decision(), _cp(11040.0), 0.0)
        assert h._phase_believed["c1"] == 3
        gone = ChargerPower(charger_id="c1", power_w=0.0,
                            connected=False, charging=False)
        for t in (100.0, AUTO_DOWN_DELAY_S + 1, AUTO_DOWN_DELAY_S + 1200):
            _tick(h, _idle_decision(), gone, t)
        h.hass.services.async_call.assert_not_awaited()
        assert h._phase_believed["c1"] == 3, "the parked belief is not changed"

    def test_a_replug_starts_the_sustain_window_over(self):
        """A window that filled while the last car was here is not this
        car's evidence — it must not switch on the first cycle."""
        h = _host()
        _tick(h, _max_decision(), _cp(3680.0), 0.0)
        gone = ChargerPower(charger_id="c1", power_w=0.0,
                            connected=False, charging=False)
        _tick(h, _idle_decision(), gone, 10.0)
        d = _tick(h, _max_decision(), _cp(3680.0), AUTO_UP_DELAY_S + 20)
        assert d.intent is ChargerIntent.CHARGE_MAX, "switched on evidence "\
            "collected before this car arrived"


class TestABoxThatDoesNotSwitch:
    """(#1008 review) Auto gets the same give-up manual already had."""

    def test_two_tries_then_it_stops_asking(self):
        h = _host()
        run = lambda d, cp, t: _tick(h, d, cp, t)
        t = 0.0
        run(_max_decision(), _cp(3680.0), t)        # belief 1
        switches = 0
        for _attempt in range(4):
            t += AUTO_UP_DELAY_S + 1
            d = run(_max_decision(), _cp(3680.0), t)
            if d.intent is not ChargerIntent.DISABLE:
                continue
            t += 10
            run(_max_decision(), _cp(0.0, charging=False), t)   # fires
            switches += 1
            t += SETTLE_S + 5
            run(_max_decision(), _cp(0.0, charging=False), t)   # settle → 3
            t += 20
            run(_max_decision(), _cp(3680.0), t)    # measurement says 1 again
            t += AUTO_MIN_INTERVAL_S + 5           # the between-switches cap
        assert switches == 2, f"expected 2 tries then give-up, got {switches}"
        assert h._phase_switch_states["c1"] == "not_taking"


class TestTheGuard:
    """The planner must never be handed the raw field again."""

    def test_the_planner_is_asked_through_the_helper(self):
        assert ast_contracts.calls(
            ev_control.EVControlMixin._phase_switch_tick,
            "_power_on_offer_w"), (
            "_phase_switch_tick must price the offer through "
            "_power_on_offer_w (#1008)")

    def test_the_tick_does_not_read_budget_w(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(
            ev_control.EVControlMixin._phase_switch_tick)))
        reads = [
            n for n in ast.walk(tree)
            if isinstance(n, ast.Attribute) and n.attr == "budget_w"
            and isinstance(n.value, ast.Name) and n.value.id == "decision"
        ]
        assert not reads, (
            "_phase_switch_tick read decision.budget_w — it is 0.0 under "
            "CHARGE_MAX by construction; ask _power_on_offer_w (#1008)")
