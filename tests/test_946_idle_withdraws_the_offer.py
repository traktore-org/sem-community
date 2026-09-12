"""#946 — a charge the car never took must not leave the offer standing.

PROD, 11.09.2026, charge mode Solar + battery: the evening battery-assist
budget started the KEBA at 8 A, the car was full and never drew, SEM went
idle twenty seconds later and night closed the mode entirely — and the box
still read ``CONNECTED (8 A)`` twelve hours later. The reconciler's idle row
returns NONE whenever the charger is not drawing ("THE spam fix"), which is
right about the log and wrong about the hardware: not drawing is not the
same as not offering. An enabled box hands its last current to whatever asks
next — the car waking up, the KEBA's own failsafe fallback, the next plug-in.

The contract here is #942's, one level down: SEM withdraws an offer IT made,
exactly once, and re-arms when it starts again. A box SEM never enabled is
left alone — a reconciler that opens its eyes in idle must not stop a charge
somebody else started.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
)


def _obs(charging=False, power=0.0, connected=True, stop_controllable=True,
         contactor_surface=False) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=0, self_charging=False,
                         power_w=power, connected=connected,
                         stop_controllable=stop_controllable,
                         contactor_surface=contactor_surface)


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="keba", heartbeat_s=5.0,
                             idle_disable_threshold=4)


def _kinds(actions):
    return [a.kind for a in actions]


class TestTheOfferIsWithdrawnOnce:

    def test_a_charge_the_car_never_took_is_withdrawn(self):
        """The PROD case: START 8 A, the car stays at 0 W, SEM goes idle."""
        rec = _rec()
        started = rec.reconcile(DesiredState.CHARGE, 8, _obs(), now=0.0)
        assert ActionKind.START_AND_WRITE in _kinds(started), started
        first = rec.reconcile(DesiredState.IDLE, 0, _obs(), now=10.0)
        assert ActionKind.DISABLE in _kinds(first), first

    def test_then_never_again(self):
        """One stop, not one per cycle — the spam fix must survive."""
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 8, _obs(), now=0.0)
        rec.reconcile(DesiredState.IDLE, 0, _obs(), now=10.0)
        for cycle in range(2, 200):
            actions = rec.reconcile(DesiredState.IDLE, 0, _obs(), now=cycle * 10.0)
            assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"

    def test_a_box_sem_never_started_is_left_alone(self):
        """#942's lesson one level down: a reconciler that wakes up in idle
        has made no offer, so it withdraws nothing — the charge running at
        the box is somebody else's."""
        rec = _rec()
        for cycle in range(100):
            actions = rec.reconcile(DesiredState.IDLE, 0, _obs(), now=cycle * 10.0)
            assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"

    def test_charging_again_re_arms_the_withdraw(self):
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 8, _obs(), now=0.0)
        assert ActionKind.DISABLE in _kinds(
            rec.reconcile(DesiredState.IDLE, 0, _obs(), now=10.0))
        # surplus returns: SEM starts again, and that is a fresh offer
        rec.reconcile(DesiredState.CHARGE, 8, _obs(), now=200.0)
        assert ActionKind.DISABLE in _kinds(
            rec.reconcile(DesiredState.IDLE, 0, _obs(), now=210.0))

    def test_a_stop_that_ended_a_real_draw_is_the_withdrawal(self):
        """When the car DID draw, the wind-down grace (#552, four cycles)
        runs first and the stop it ends already opened the contactor — the
        quiet cycles after it must stay silent, not withdraw a second time."""
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 8, _obs(), now=0.0)
        rec.reconcile(DesiredState.CHARGE, 8, _obs(charging=True, power=5500.0), now=10.0)
        stopped_at = None
        for cycle in range(2, 8):                      # the grace, then the stop
            actions = rec.reconcile(DesiredState.IDLE, 0,
                                    _obs(charging=True, power=5500.0), now=cycle * 10.0)
            if ActionKind.DISABLE in _kinds(actions):
                stopped_at = cycle
                break
        assert stopped_at is not None, "the drawing car was never stopped"
        for cycle in range(stopped_at + 1, stopped_at + 40):   # draw is over
            actions = rec.reconcile(DesiredState.IDLE, 0, _obs(), now=cycle * 10.0)
            assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"

    def test_an_unstoppable_charger_is_not_nagged(self):
        """#627: no mechanism can open this contactor. Saying so belongs to
        the drawing row; an idle box gets silence, not a repair per cycle."""
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 8, _obs(stop_controllable=False), now=0.0)
        for cycle in range(1, 20):
            actions = rec.reconcile(DesiredState.IDLE, 0,
                                    _obs(stop_controllable=False), now=cycle * 10.0)
            assert ActionKind.REPORT_STOP_UNENFORCEABLE not in _kinds(actions), actions

    def test_the_relay_floor_delays_the_withdraw_but_never_loses_it(self):
        """(#940) A relay surface keeps its minimum ON: the withdraw waits,
        and still happens — a held stop must not be a dropped stop."""
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 8, _obs(contactor_surface=True), now=0.0)
        for now in (10.0, 60.0, 110.0):
            actions = rec.reconcile(DesiredState.IDLE, 0,
                                    _obs(contactor_surface=True), now=now)
            assert ActionKind.DISABLE not in _kinds(actions), (now, actions)
        late = rec.reconcile(DesiredState.IDLE, 0,
                             _obs(contactor_surface=True), now=130.0)
        assert ActionKind.DISABLE in _kinds(late), late


class TestOffIsUnchanged:

    def test_off_still_issues_one_stop_then_nothing(self):
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 8, _obs(), now=0.0)
        rec.reconcile(DesiredState.CHARGE, 8, _obs(charging=True, power=5500.0), now=10.0)
        first = rec.reconcile(DesiredState.RELEASED, 0,
                              _obs(charging=True, power=5500.0), now=20.0)
        assert ActionKind.DISABLE in _kinds(first), first
        for cycle in range(3, 40):
            actions = rec.reconcile(DesiredState.RELEASED, 0,
                                    _obs(charging=True, power=5500.0), now=cycle * 10.0)
            assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"
