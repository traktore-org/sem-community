"""#898 — charge mode Off means SEM sends no commands to the charger.

DigitalOptics (Fronius, 2.0.0): with the charger in Off, a session started
elsewhere in HA was stopped by SEM within a cycle. The only way to prevent it
was global observer mode, which switches every other device routine off too.

The User Guide has said since 1.7: *"Off — EV charging is disabled. SEM
continues monitoring but does not send any commands to the charger. Use when
you want manual control or a charger is offline."* The code said the
opposite: ``OffMode`` produced ``DISABLE`` and the reconciler re-asserted it
on every rogue start (#315's KEBA auto-start guard applied to a session the
USER started).

The contract now: entering Off releases whatever SEM itself was holding —
one DISABLE if SEM's own session is running, so switching to Off still
stops SEM's charge — and from then on SEM issues nothing: no stop, no
park-on-disconnect, no failsafe, no stop-war. The VPP export pause, which
used to borrow mode ``off`` to stop the car, gets its own explicit stop.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
    desired_from_decision,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
    commanded_power_w,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.vpp_dispatch import (
    vpp_pause_override,
)


def _view(mode="off", *, connected=True, solar_w=5000.0, is_night=False,
          battery_soc=75.0):
    return ChargerView(
        power=ChargerPower(charger_id="fronius", power_w=0.0,
                           connected=connected, charging=False),
        energy=ChargerEnergy(charger_id="fronius"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(solar_w=solar_w, home_w=500.0, battery_soc=battery_soc,
                           is_night=is_night),
    )


def _obs(charging=False, power=0.0, connected=True) -> ObservedState:
    return ObservedState(charging=charging, setpoint_a=0, self_charging=False,
                         power_w=power, connected=connected)


def _rec() -> ChargerReconciler:
    return ChargerReconciler(charger_id="fronius", heartbeat_s=5.0,
                             idle_disable_threshold=4)


class TestOffDecidesRelease:
    @pytest.mark.parametrize("connected", [True, False])
    @pytest.mark.parametrize("is_night", [True, False])
    @pytest.mark.parametrize("solar_w", [0.0, 5000.0, 10000.0])
    def test_off_is_release_everywhere(self, connected, is_night, solar_w):
        d = decide(_view(connected=connected, is_night=is_night, solar_w=solar_w))
        assert d.intent is ChargerIntent.RELEASE, d.reason
        assert d.commanded_amps == 0 and d.budget_w == 0.0

    def test_release_commands_no_power(self):
        d = ChargerDecision(charger_id="f", mode="off", intent=ChargerIntent.RELEASE, reason="x")
        assert commanded_power_w(d, phases=3, voltage=230.0, max_current_a=16.0) == 0.0

    def test_release_maps_to_released(self):
        d = ChargerDecision(charger_id="f", mode="off", intent=ChargerIntent.RELEASE, reason="x")
        assert desired_from_decision(d) == (DesiredState.RELEASED, 0)


class TestReleasedIsHandsOff:
    def test_a_session_started_elsewhere_is_left_alone(self):
        """The report: the box draws 4 kW that SEM never started. Off must
        not touch it — for 300 cycles, not just the first."""
        rec = _rec()
        for cycle in range(300):
            actions = rec.reconcile(DesiredState.RELEASED, 0,
                                    _obs(charging=True, power=4000.0), now=cycle * 10.0)
            assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"

    def test_sems_own_session_is_released_once(self):
        """Switching to Off while SEM's charge runs: one DISABLE ends it —
        the user asked for Off, not for the car to finish — then nothing."""
        rec = _rec()
        rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=0.0)
        rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, power=4000.0), now=10.0)
        first = rec.reconcile(DesiredState.RELEASED, 0, _obs(charging=True, power=4000.0), now=20.0)
        assert Action(ActionKind.DISABLE) in first, first
        for cycle in range(3, 50):
            actions = rec.reconcile(DesiredState.RELEASED, 0,
                                    _obs(charging=True, power=4000.0), now=cycle * 10.0)
            assert actions == [Action(ActionKind.NONE)], f"cycle {cycle}: {actions}"

    def test_no_park_off_on_disconnect_while_released(self):
        rec = _rec()
        rec.reconcile(DesiredState.RELEASED, 0, _obs(charging=False, connected=True), now=0.0)
        for cycle in range(1, 6):
            actions = rec.reconcile(DesiredState.RELEASED, 0,
                                    _obs(charging=False, connected=False), now=cycle * 10.0)
            assert Action(ActionKind.PARK_OFF) not in actions, f"cycle {cycle}: {actions}"

    def test_leaving_off_charges_normally_again(self):
        rec = _rec()
        rec.reconcile(DesiredState.RELEASED, 0, _obs(charging=False), now=0.0)
        actions = rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=10.0)
        assert any(a.kind in (ActionKind.START_AND_WRITE, ActionKind.WRITE_CURRENT)
                   for a in actions), actions


class TestTheOtherProducersFollow:
    def test_night_gate_releases_an_off_charger(self):
        """ev_control's night gate policed an off charger with DISABLE."""
        import inspect
        from custom_components.solar_energy_management.coordinator import ev_control
        src = inspect.getsource(ev_control.EVControlMixin._police_opted_out_charger)
        assert "ChargerIntent.RELEASE if mode == \"off\"" in src

    def test_stability_and_phase_guard_pass_release_through(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import (
            charge_stability, active_phase_guard,
        )
        assert "ChargerIntent.RELEASE" in inspect.getsource(charge_stability)
        assert "ChargerIntent.RELEASE" in inspect.getsource(active_phase_guard)

    def test_phase_guard_never_converts_a_release(self):
        from custom_components.solar_energy_management.coordinator.active_phase_guard import (
            ActivePhaseGuard,
        )
        g = ActivePhaseGuard()
        g._enforcing = True
        g.control_authorized = False
        d = ChargerDecision(charger_id="f", mode="off", intent=ChargerIntent.RELEASE, reason="off")
        out = g.filter(d, adapter=None, power=None)
        assert out.intent is ChargerIntent.RELEASE


class TestVppPauseKeepsItsStop:
    """The VPP export event used ``mode = off`` to stop the car (#580). Off
    no longer stops anything, so the pause carries its own DISABLE."""

    def test_pause_overrides_a_charge_with_disable(self):
        d = ChargerDecision(charger_id="f", mode="solar_only",
                            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=10,
                            reason="solar")
        out = vpp_pause_override(d, True)
        assert out.intent is ChargerIntent.DISABLE and out.commanded_amps == 0
        assert "VPP" in out.reason

    def test_no_pause_is_a_no_op(self):
        d = ChargerDecision(charger_id="f", mode="solar_only",
                            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=10,
                            reason="solar")
        assert vpp_pause_override(d, False) is d

    def test_mode_resolution_no_longer_borrows_off(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator
        src = inspect.getsource(coordinator.SEMCoordinator._effective_charge_mode_for)
        assert 'return "off"' not in src
        assert "vpp_pause_override(" in inspect.getsource(coordinator)


class TestOffStopsACarThatSemDidNotStart:
    """(10.09.2026, PROD) Selecting Off must stop whatever is charging.

    #898 narrowed the one closing stop to sessions SEM believed it had
    started (``_charging_intent_active``), and the commit said what that
    meant: *"whatever draws, draws"*. On real hardware it meant this:

      16:13–17:48  the KEBA auto-restarts itself every ~10 min; SEM stops it
                   seven times, every stop taking within seconds
      18:29:41     the box restarts once more
      18:29:56     stop-war ceasefire — SEM stands down (intent now False)
      19:25        the owner selects Off to stop the car
      → the RELEASED row answered NONE, and the car charged on the house
        battery and the grid until 19:49, when it was stopped by hand.

    The rule that serves both reports: the TRANSITION into Off issues one
    stop for whatever is drawing, whoever started it; from then on SEM issues
    nothing, so #898's own case — a charge started at the box while Off was
    already set — is still left alone, across restarts too.
    """

    def test_off_stops_a_box_that_started_itself(self):
        """The PROD shape: SEM is not charging-intent-active (it had given
        up), the box is drawing, the user selects Off."""
        rec = _rec()
        # a cycle in some other state: this is what makes the next Off a
        # transition rather than a continuation
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=3100.0),
                      now=0.0)
        actions = rec.reconcile(DesiredState.RELEASED, 0,
                                _obs(charging=True, power=3100.0), now=10.0)
        assert [a.kind for a in actions] == [ActionKind.DISABLE], (
            "selecting Off left a drawing charger alone — the #898 regression "
            "that cost a live install 80 minutes of charging")

    def test_and_then_never_again(self):
        """#898's rule survives: after that one stop, nothing — including a
        charge the user starts at the box afterwards."""
        rec = _rec()
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=3100.0),
                      now=0.0)
        rec.reconcile(DesiredState.RELEASED, 0,
                      _obs(charging=True, power=3100.0), now=10.0)
        for i in range(6):
            actions = rec.reconcile(DesiredState.RELEASED, 0,
                                    _obs(charging=True, power=4000.0),
                                    now=20.0 + i * 10)
            assert [a.kind for a in actions] == [ActionKind.NONE]

    def test_a_reconciler_that_wakes_up_in_off_leaves_it_alone(self):
        """A restart while Off is already selected must not stop the user's
        charge — the reconciler cannot tell 'chosen just now' from 'chosen an
        hour ago', so it assumes the safe one."""
        rec = _rec()
        actions = rec.reconcile(DesiredState.RELEASED, 0,
                                _obs(charging=True, power=4000.0), now=0.0)
        assert [a.kind for a in actions] == [ActionKind.NONE]

    def test_leaving_off_re_arms_the_stop(self):
        """Off → charge → Off again is a second instruction to stop."""
        rec = _rec()
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=True, power=3100.0), now=0.0)
        assert [a.kind for a in rec.reconcile(
            DesiredState.RELEASED, 0, _obs(charging=True, power=3100.0), now=10.0)
        ] == [ActionKind.DISABLE]
        rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=False), now=20.0)
        rec.reconcile(DesiredState.CHARGE, 10, _obs(charging=True, power=4000.0), now=30.0)
        assert [a.kind for a in rec.reconcile(
            DesiredState.RELEASED, 0, _obs(charging=True, power=4000.0), now=40.0)
        ] == [ActionKind.DISABLE]
