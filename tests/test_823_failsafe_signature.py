"""#823 — a charger that re-enables itself on a failsafe timeout is NAMED.

Split out of #763. @onkelfu went to the Modbus-register level to discover
that his own wallbox — not SEM — was undoing every stop: a KEBA P30 C driven
over plain Modbus, whose failsafe configuration read

    Curr FS: 6000      # fall back to 6 A
    Tmo FS:  600       # if the controller goes quiet for 600 s

SEM commanded DISABLE, wrote nothing further, and exactly 600 seconds later
the box enabled itself at 6 A. Every time. On the official KEBA integration
SEM arms a non-tripping failsafe (#546) so this cannot happen; on the generic
path there is no failsafe concept, no service to call, and no register SEM
may guess at.

What SEM CAN do is recognise the signature and say it out loud instead of
silently fighting it:

* commanded stop, no write since, the box came back — that edge already
  exists (#763's war round);
* the discriminator is the CONSTANT interval. A car retrying or a human
  pressing start is not periodic; a failsafe timeout is, to the second;
* two matching intervals before speaking — one could be anything, and a
  warning that cries wolf gets ignored (#611);
* SEM must NOT stop faster in response. That is the war #763's ceasefire
  exists to prevent. The fix is a one-time change on the box, so the output
  is a Repair naming the interval and pointing at the failsafe settings.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
)

HEARTBEAT_S = 5.0


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="ev_charger", heartbeat_s=HEARTBEAT_S,
                             idle_disable_threshold=4)


def _obs(charging=False, power=0.0) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=0,
                         self_charging=False, power_w=power)


def _stop_then_reenable(rec, stop_at: float, reenable_after: float) -> list:
    """One failsafe cycle: SEM's DISABLE lands, the box comes back later."""
    a = rec.reconcile(DesiredState.OFF, 0, _obs(charging=True, power=4100.0),
                      now=stop_at)
    assert Action(ActionKind.DISABLE) in a, f"stop did not land at {stop_at}: {a}"
    # box settles…
    rec.reconcile(DesiredState.OFF, 0, _obs(charging=False), now=stop_at + 30.0)
    # …and re-enables itself after the failsafe timeout
    return rec.reconcile(DesiredState.OFF, 0,
                         _obs(charging=True, power=4100.0),
                         now=stop_at + reenable_after)


class TestTheSignatureIsRecognised:
    def test_two_matching_intervals_name_the_failsafe(self):
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        acts2 = _stop_then_reenable(rec, 3000.0, 600.0)
        kinds = [a.kind for a in acts2]
        assert ActionKind.REPORT_FAILSAFE_SUSPECTED in kinds, (
            f"two 600 s stop→re-enable cycles, to the second, and SEM did "
            f"not name the failsafe: {acts2} (#823)"
        )

    def test_the_learned_interval_rides_the_action(self):
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        acts = _stop_then_reenable(rec, 3000.0, 600.0)
        rep = [a for a in acts if a.kind is ActionKind.REPORT_FAILSAFE_SUSPECTED]
        assert rep and abs(rep[0].interval_s - 600.0) < 1.0, (
            "the Repair cannot point at 'Tmo FS: 600' without the number"
        )

    def test_one_occurrence_says_nothing(self):
        """One could be anything — a car retry, a human, an app."""
        rec = _rec()
        acts = _stop_then_reenable(rec, 1000.0, 600.0)
        assert ActionKind.REPORT_FAILSAFE_SUSPECTED not in [a.kind for a in acts]

    def test_jittery_intervals_are_not_a_failsafe(self):
        """A retrying car is aperiodic; the constancy IS the discriminator."""
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        acts = _stop_then_reenable(rec, 3000.0, 780.0)   # 30% off
        assert ActionKind.REPORT_FAILSAFE_SUSPECTED not in [a.kind for a in acts]


class TestSemDoesNotEscalate:
    def test_the_stop_cadence_is_unchanged(self):
        """Recognising the failsafe must not make SEM stop harder — that is
        the war (#763). Same reassert dwell before and after the report."""
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        acts = _stop_then_reenable(rec, 3000.0, 600.0)
        disables = [a for a in acts if a.kind is ActionKind.DISABLE]
        assert len(disables) <= 1, (
            f"SEM escalated to {len(disables)} DISABLEs on recognising the "
            "failsafe — the box always wins that war (#823/#763)"
        )

    def test_it_reports_once_not_every_cycle(self):
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        _stop_then_reenable(rec, 3000.0, 600.0)
        # further cycles inside the same episode do not re-report
        acts = rec.reconcile(DesiredState.OFF, 0,
                             _obs(charging=True, power=4100.0), now=3610.0)
        assert ActionKind.REPORT_FAILSAFE_SUSPECTED not in [a.kind for a in acts]


class TestRecovery:
    """The repair must be able to RETIRE: the fix is a one-time change on the
    box, and once a stop finally holds past the learned interval the user has
    made it — the notice should go, and the recogniser re-arm so a relapse is
    named again rather than absorbed by a spent flag."""

    def test_a_stop_that_holds_clears_the_report(self):
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        _stop_then_reenable(rec, 3000.0, 600.0)          # reported here
        # a later stop…
        rec.reconcile(DesiredState.OFF, 0,
                      _obs(charging=True, power=4100.0), now=5000.0)
        # …that HOLDS: quiet past 2× the learned interval
        acts = rec.reconcile(DesiredState.OFF, 0, _obs(charging=False),
                             now=5000.0 + 1300.0)
        assert ActionKind.CLEAR_FAILSAFE_SUSPECTED in [a.kind for a in acts]

    def test_a_relapse_after_recovery_is_named_again(self):
        rec = _rec()
        _stop_then_reenable(rec, 1000.0, 600.0)
        _stop_then_reenable(rec, 3000.0, 600.0)
        rec.reconcile(DesiredState.OFF, 0,
                      _obs(charging=True, power=4100.0), now=5000.0)
        rec.reconcile(DesiredState.OFF, 0, _obs(charging=False),
                      now=5000.0 + 1300.0)               # cleared
        # the box regresses (a firmware reset restores the failsafe)
        acts1 = _stop_then_reenable(rec, 10000.0, 600.0)
        assert ActionKind.REPORT_FAILSAFE_SUSPECTED not in [a.kind for a in acts1]
        acts2 = _stop_then_reenable(rec, 13000.0, 600.0)
        assert ActionKind.REPORT_FAILSAFE_SUSPECTED in [a.kind for a in acts2]
