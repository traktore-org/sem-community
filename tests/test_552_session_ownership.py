"""#552 — session ownership: SEM never bridges/holds/starts a charge it
didn't command.

PROD 2026-07-02 (v1.7.4-beta.7, solar_only, after sunset, battery 99%):
the KEBA P30 auto-started at its stored 10 A setpoint every ~10 minutes
(car retry, #315 device behavior). ``decide()`` correctly said IDLE all
evening (surplus ≈ 250 W < 6900 W min), but ``charge_stability``'s
deficit-hold ENGAGED FOR THE UN-OWNED DRAW — reason literally
``stability: deficit 0s/180s — holding 10A before stop`` entered from
idle — rewriting IDLE into CHARGE_AT_AMPS 10 A. The reconciler then
faithfully logged ``reconcile(ev_charger): START 10A``: SEM formally
enabled + failsafe-armed + wrote 10 A for a charge nobody decided,
draining the home battery at ~4.9 kW in 90 s–4 min bursts all evening.
HA-TEST was conclusively excluded (fresh burst with TEST's core fully
stopped).

Root fix (ownership, expressed at each layer with its own knowledge):

* ``ChargeStability`` tracks the sessions IT started (``_commit_amps`` is
  the single point every charge-commit flows through). The deficit
  bridge/hold only engages for owned sessions.
* ``ChargerReconciler``: the idle flicker-grace applies only while
  winding down SEM's own stop; once idle has settled, a newly-appearing
  draw is rogue → DISABLE immediately (parity with the OFF row).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
)
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    Action,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)


class FakeAdapter:
    def __init__(self, last_intent=None, min_current_a=6):
        self.last_intent = last_intent
        self.min_current_a = min_current_a

    def actual_charging(self, power):
        return power.power_w > 500.0


def _view(*, power_w=0.0, solar_w=250.0, cid="ev_charger"):
    """The PROD scene: after sunset, surplus far below the 10 A min."""
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=True, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode="solar_only",
        config={"ev_min_current": 10, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=False, solar_w=solar_w, min_solar_w=200.0,
                           battery_soc=99.0, buffer_soc=85.0),
    )


def _idle(cid="ev_charger", bridgeable=False):
    return ChargerDecision(
        charger_id=cid, mode="solar_only", intent=ChargerIntent.IDLE,
        bridgeable=bridgeable,
        reason="solar_only: surplus=252W < min=6900W (=10A) — idle",
    )


def _charge(cid="ev_charger", amps=10):
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=7000.0, reason="solar_only: surplus ok",
    )


@pytest.mark.unit
class TestStabilityOwnership:
    def test_unowned_draw_is_never_held(self):
        """THE PROD bug: box self-starts, decide says idle → IDLE must pass
        through untouched (no 'holding NA before stop' rewrite)."""
        st = ChargeStability()
        # KEBA auto-start: SEM's last command was DISABLE, box draws anyway.
        adapter = FakeAdapter(last_intent=ChargerIntent.DISABLE)
        d = st.filter(_idle(), _view(power_w=4870.0), adapter,
                      enable_delay_s=60, disable_delay_s=180,
                      deep_deficit_grace_s=45, now_ts=0.0)
        assert d.intent is ChargerIntent.IDLE
        assert "holding" not in d.reason

    def test_stale_charge_last_intent_is_not_ownership(self):
        """adapter.last_intent can go stale (a stability stop that lands
        while the car blips 0 W never reaches the adapter). A stale CHARGE
        intent alone must not re-open the bridge."""
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        d = st.filter(_idle(), _view(power_w=4870.0), adapter,
                      enable_delay_s=60, disable_delay_s=180, now_ts=0.0)
        assert d.intent is ChargerIntent.IDLE

    def test_owned_session_still_bridges(self):
        """The bridge's real job is untouched: a session stability started
        keeps its deficit hold through a transient dip. (Two idle cycles are
        needed before the 5-window upper-median drops charge_wanted and the
        DEFICIT bridge — not the charge-path delta guard — engages.)"""
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        # SEM starts the session legitimately (surplus, drawing).
        st.filter(_charge(), _view(power_w=6900.0, solar_w=8000.0), adapter,
                  enable_delay_s=0, disable_delay_s=180, now_ts=0.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        # Transient dip (bridgeable=True): first idle cycle is absorbed by
        # the median; the second reaches the deficit bridge.
        dip = _view(power_w=6900.0, solar_w=8000.0)
        st.filter(_idle(bridgeable=True), dip, adapter,
                  enable_delay_s=0, disable_delay_s=180, now_ts=10.0)
        d = st.filter(_idle(bridgeable=True), dip, adapter,
                      enable_delay_s=0, disable_delay_s=180, now_ts=20.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "deficit" in d.reason and "holding" in d.reason

    def test_no_reentry_after_stability_stop(self):
        """After stability ends its own session, ownership ends WITH it —
        the bridge must not re-enter from the stale state (the ~10-min
        burst loop)."""
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        view_drawing = _view(power_w=6900.0, solar_w=8000.0)
        st.filter(_charge(), view_drawing, adapter,
                  enable_delay_s=0, disable_delay_s=180, now_ts=0.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        # Structural deficit → short grace → stability stop. (The 5-window
        # upper-median keeps charge_wanted alive for one idle cycle, so the
        # deficit anchors on the SECOND idle cycle.)
        dark = _view(power_w=6900.0, solar_w=0.0)
        st.filter(_idle(bridgeable=False), dark, adapter,
                  enable_delay_s=0, disable_delay_s=180,
                  deep_deficit_grace_s=45, now_ts=10.0)
        st.filter(_idle(bridgeable=False), dark, adapter,
                  enable_delay_s=0, disable_delay_s=180,
                  deep_deficit_grace_s=45, now_ts=20.0)  # deficit anchors here
        d_stop = st.filter(_idle(bridgeable=False), dark, adapter,
                           enable_delay_s=0, disable_delay_s=180,
                           deep_deficit_grace_s=45, now_ts=70.0)
        assert d_stop.intent is ChargerIntent.IDLE
        # Car winds down; box later self-starts again (last_intent still a
        # stale CHARGE — the adapter never saw the stop). Must stay IDLE.
        st.filter(_idle(bridgeable=False), _view(power_w=0.0, solar_w=0.0),
                  adapter, enable_delay_s=0, disable_delay_s=180,
                  deep_deficit_grace_s=45, now_ts=100.0)
        d_rogue = st.filter(_idle(bridgeable=False), dark, adapter,
                            enable_delay_s=0, disable_delay_s=180,
                            deep_deficit_grace_s=45, now_ts=700.0)
        assert d_rogue.intent is ChargerIntent.IDLE
        assert "holding" not in d_rogue.reason

    def test_rogue_draw_during_stop_settle_stays_idle(self):
        """A rogue draw arriving DURING the post-stop settle window (before
        the wind-down finished) must also pass IDLE through — the settle
        block honours the IDLE as-is and the ownership gate keeps the
        bridge shut afterwards (ruflo L2)."""
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        st.filter(_charge(), _view(power_w=6900.0, solar_w=8000.0), adapter,
                  enable_delay_s=0, disable_delay_s=180, now_ts=0.0)
        adapter.last_intent = ChargerIntent.CHARGE_AT_AMPS
        dark = _view(power_w=6900.0, solar_w=0.0)
        for t in (10.0, 20.0):  # median drop + deficit anchor
            st.filter(_idle(bridgeable=False), dark, adapter,
                      enable_delay_s=0, disable_delay_s=180,
                      deep_deficit_grace_s=45, now_ts=t)
        d_stop = st.filter(_idle(bridgeable=False), dark, adapter,
                           enable_delay_s=0, disable_delay_s=180,
                           deep_deficit_grace_s=45, now_ts=70.0)
        assert d_stop.intent is ChargerIntent.IDLE
        # Settle window: car STILL drawing (actuator lag or rogue) → IDLE.
        d_settle = st.filter(_idle(bridgeable=False), dark, adapter,
                             enable_delay_s=0, disable_delay_s=180,
                             deep_deficit_grace_s=45, now_ts=85.0)
        assert d_settle.intent is ChargerIntent.IDLE
        assert "holding" not in d_settle.reason

    def test_restart_mid_surplus_still_adopts(self):
        """Coordinator restart with REAL surplus: the charge path adopts the
        running session (unchanged behavior — ownership re-established)."""
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        d = st.filter(_charge(), _view(power_w=6900.0, solar_w=8000.0),
                      adapter, enable_delay_s=60, disable_delay_s=180,
                      now_ts=0.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS


def _obs(*, charging: bool, power: float = 0.0, setpoint: int = 0,
         self_charging: bool = False):
    return ObservedState(charging=charging, setpoint_a=setpoint,
                         self_charging=self_charging, power_w=power)


def _rec():
    return ChargerReconciler("ev_charger", heartbeat_s=60.0,
                             idle_disable_threshold=3)


@pytest.mark.unit
class TestReconcilerRogueDraw:
    def test_settled_idle_new_draw_disables_first_cycle(self):
        rec = _rec()
        # Idle, converged (settled).
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=0.0)
        # KEBA auto-start appears → immediate DISABLE, no flicker grace.
        actions = rec.reconcile(DesiredState.IDLE, 0,
                                _obs(charging=True, power=4870.0), now=10.0)
        assert actions == [Action(ActionKind.DISABLE)]

    def test_wind_down_after_own_stop_keeps_grace(self):
        rec = _rec()
        # SEM charges, then stability stops it → desired flips to IDLE while
        # the car is still drawing (actuator lag): the grace applies.
        rec.reconcile(DesiredState.CHARGE, 10,
                      _obs(charging=True, power=4870.0, setpoint=10), now=0.0)
        a1 = rec.reconcile(DesiredState.IDLE, 0,
                           _obs(charging=True, power=4870.0), now=10.0)
        a2 = rec.reconcile(DesiredState.IDLE, 0,
                           _obs(charging=True, power=4870.0), now=20.0)
        assert a1 == [Action(ActionKind.NONE)]
        assert a2 == [Action(ActionKind.NONE)]
        a3 = rec.reconcile(DesiredState.IDLE, 0,
                           _obs(charging=True, power=4870.0), now=30.0)
        assert a3 == [Action(ActionKind.DISABLE)]

    def test_rogue_disable_reasserts_at_the_dwell(self):
        # (#763 round 3) The re-assert now floors at the evcc-parity 60 s
        # dwell — the per-cycle hammering this test used to pin was
        # redundant bridge writes, each a fresh chance to abort the car's
        # handshake mid-negotiation. The INTENT stands every cycle; the
        # WRITE lands once per dwell.
        rec = _rec()
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=0.0)
        actions = rec.reconcile(DesiredState.IDLE, 0,
                                _obs(charging=True, power=4870.0), now=10.0)
        assert actions == [Action(ActionKind.DISABLE)]
        for t in (20.0, 30.0):
            actions = rec.reconcile(DesiredState.IDLE, 0,
                                    _obs(charging=True, power=4870.0), now=t)
            assert Action(ActionKind.DISABLE) not in actions, f"at t={t}"
        actions = rec.reconcile(DesiredState.IDLE, 0,
                                _obs(charging=True, power=4870.0), now=71.0)
        assert actions == [Action(ActionKind.DISABLE)]

    def test_settle_after_rogue_then_new_rogue_still_immediate(self):
        rec = _rec()
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=0.0)
        rec.reconcile(DesiredState.IDLE, 0,
                      _obs(charging=True, power=4870.0), now=10.0)  # DISABLE
        rec.reconcile(DesiredState.IDLE, 0, _obs(charging=False), now=20.0)
        actions = rec.reconcile(DesiredState.IDLE, 0,
                                _obs(charging=True, power=4870.0), now=630.0)
        assert actions == [Action(ActionKind.DISABLE)]
