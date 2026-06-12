"""#461 — evcc-style enable/disable delays between decide() and actuate().

The v1.7 arch rewrite orphaned the v1.7.1-beta.14 stability layer in
``ev_control.py`` (``ev_enable_delay_seconds`` / ``ev_disable_delay_seconds``
were read by a code path the new pipeline no longer calls), so surplus
flapping returned: solar hovering around the 6 A minimum cycled the
contactor every ~20 s in RienduPre's beta.10 logs.

``coordinator/charge_stability.py`` reconnects the delays. Semantics:

* enable — a CHARGE decision on a non-charging EV must hold
  continuously for ``enable_delay_s`` before it passes.
* disable — an IDLE decision against a charging EV holds minimum
  current until the deficit has persisted ``disable_delay_s``
  (evcc deficit-persistence, deliberately NOT the legacy
  min-run-time which let an old session die on a 1-cycle dip).
"""
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
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


def _view(mode="solar_only", *, connected=True, power_w=0.0, is_night=False,
          cid="wb"):
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=connected, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=is_night),
    )


def _charge(cid="wb", amps=6):
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps, budget_w=4500.0,
        reason="solar_only: surplus ok",
    )


def _idle(cid="wb"):
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.IDLE,
        reason="solar_only: surplus below min",
    )


@pytest.mark.unit
class TestEnableDelay:
    def test_charge_held_until_delay_elapses(self):
        st = ChargeStability()
        adapter = FakeAdapter()
        view = _view()
        d0 = st.filter(_charge(), view, adapter,
                       enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d0.intent is ChargerIntent.IDLE
        assert d0.reason.startswith("stability:")
        d30 = st.filter(_charge(), view, adapter,
                        enable_delay_s=60, disable_delay_s=300, now_ts=30.0)
        assert d30.intent is ChargerIntent.IDLE
        d61 = st.filter(_charge(), view, adapter,
                        enable_delay_s=60, disable_delay_s=300, now_ts=61.0)
        assert d61.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d61.commanded_amps == 6

    def test_single_dip_does_not_reset_enable_window(self):
        # Layer 1: the median absorbs a 1-cycle flicker BEFORE the
        # timers see it — the qualification window keeps counting.
        st = ChargeStability()
        adapter = FakeAdapter()
        view = _view()
        st.filter(_charge(), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=10.0)
        assert d.intent is ChargerIntent.IDLE  # still waiting, not charging
        d = st.filter(_charge(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=61.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_sustained_dip_resets_enable_window(self):
        # Two consecutive sub-threshold cycles flip the median — a
        # real loss of surplus restarts the qualification window.
        st = ChargeStability()
        adapter = FakeAdapter()
        view = _view()
        st.filter(_charge(), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        st.filter(_idle(), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=10.0)
        st.filter(_idle(), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=20.0)
        # Surplus returns at t=30; median needs a warm window again and
        # the enable window restarts — no start at t=61.
        st.filter(_charge(), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=30.0)
        d = st.filter(_charge(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=61.0)
        assert d.intent is ChargerIntent.IDLE

    def test_start_is_gentle_at_min_current(self):
        # Cold start commands min current first (PROD 2026-05-31 grid
        # overshoot) and announces the ramp target.
        st = ChargeStability()
        d = None
        for t in (0.0, 30.0, 61.0):
            d = st.filter(_charge(amps=16), _view(), FakeAdapter(),
                          enable_delay_s=60, disable_delay_s=300, now_ts=t)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6
        assert "ramping toward 16A" in d.reason

    def test_zero_delay_starts_immediately(self):
        st = ChargeStability()
        d = st.filter(_charge(), _view(), FakeAdapter(),
                      enable_delay_s=0, disable_delay_s=0, now_ts=5.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS


@pytest.mark.unit
class TestDisableDelay:
    def test_idle_holds_min_current_until_deficit_persists(self):
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        view = _view(power_w=4500.0)
        d0 = st.filter(_idle(), view, adapter,
                       enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d0.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d0.commanded_amps == 6
        assert "holding 6A" in d0.reason
        d150 = st.filter(_idle(), view, adapter,
                         enable_delay_s=60, disable_delay_s=300, now_ts=150.0)
        assert d150.intent is ChargerIntent.CHARGE_AT_AMPS
        d301 = st.filter(_idle(), view, adapter,
                         enable_delay_s=60, disable_delay_s=300, now_ts=301.0)
        assert d301.intent is ChargerIntent.IDLE

    def test_surplus_recovery_resets_deficit_window(self):
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        view = _view(power_w=4500.0)
        st.filter(_idle(), view, adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        # Cloud passes at t=120 — CHARGE resumes and clears the deficit
        # timer; the ramp limiter climbs from the held 6 A (+2 A).
        d = st.filter(_charge(amps=10), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=120.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 8
        # New deficit at t=200 → fresh 300 s window (stop at 500+, not 300).
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=200.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=499.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=501.0)
        assert d.intent is ChargerIntent.IDLE

    def test_restart_mid_session_counts_as_charging(self):
        # Coordinator restart: adapter.last_intent is None but the EV is
        # measurably drawing → the deficit hold must still protect it.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        view = _view(power_w=4500.0)
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_hold_respects_vehicle_min_current(self):
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        view = ChargerView(
            power=ChargerPower(charger_id="wb", power_w=6000.0,
                               connected=True, charging=True),
            energy=ChargerEnergy(charger_id="wb"),
            mode="solar_only",
            config={"ev_min_current": 6, "vehicle_min_current": 9,
                    "ev_max_current": 16},
            fleet=FleetContext(is_night=False),
        )
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.commanded_amps == 9


@pytest.mark.unit
class TestMidSessionSmoothing:
    """The reporter's car ended sessions itself because the commanded
    current bounced cycle-by-cycle. Layers 1-3 + ramp must keep the
    setpoint calm while a session runs."""

    def _charging_setup(self):
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        view = _view(power_w=7000.0)
        return st, adapter, view

    def test_single_cycle_dip_never_reaches_the_car(self):
        # 8 kW → 0 W → 8 kW inverter flicker: decide() says IDLE for one
        # cycle, but the median erases it — the car keeps its setpoint
        # and no deficit window even starts.
        st, adapter, view = self._charging_setup()
        st.filter(_charge(amps=10), view, adapter, now_ts=0.0)
        st.filter(_charge(amps=10), view, adapter, now_ts=10.0)
        d = st.filter(_idle(), view, adapter, now_ts=20.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 10
        assert not st._deficit_since

    def test_ramp_limits_step_size(self):
        # A surplus jump from 10 A to 16 A worth of sun moves the
        # setpoint by at most ramp_amps per change.
        st, adapter, view = self._charging_setup()
        st.filter(_charge(amps=10), view, adapter, now_ts=0.0)
        st.filter(_charge(amps=10), view, adapter, now_ts=10.0)
        d = st.filter(_charge(amps=16), view, adapter, now_ts=40.0)
        # median of [10, 10, 16] = 10 → still 10; feed another 16.
        d = st.filter(_charge(amps=16), view, adapter, now_ts=80.0)
        assert d.commanded_amps == 12  # 10 + ramp(2), not 16

    def test_debounce_one_change_per_interval(self):
        st, adapter, view = self._charging_setup()
        st.filter(_charge(amps=10), view, adapter, now_ts=0.0)   # adopt 10
        st.filter(_charge(amps=16), view, adapter, now_ts=10.0)
        d = st.filter(_charge(amps=16), view, adapter, now_ts=20.0)
        # Median has reached 16 by t=20, but the last change was at
        # t=0 — within the 30 s debounce the setpoint must not move.
        assert d.commanded_amps == 10
        assert "debounce" in d.reason
        d = st.filter(_charge(amps=16), view, adapter, now_ts=45.0)
        assert d.commanded_amps == 12  # debounce expired → one ramp step

    def test_steady_state_is_untouched(self):
        st, adapter, view = self._charging_setup()
        st.filter(_charge(amps=10), view, adapter, now_ts=0.0)
        d = st.filter(_charge(amps=10), view, adapter, now_ts=40.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 10
        assert d.reason == "solar_only: surplus ok"  # pass-through


@pytest.mark.unit
class TestScope:
    def test_night_passes_through(self):
        st = ChargeStability()
        d = st.filter(_charge(), _view(is_night=True), FakeAdapter(),
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_always_max_passes_through(self):
        st = ChargeStability()
        d = st.filter(_charge(), _view(mode="always_max"), FakeAdapter(),
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_disconnect_passes_and_resets(self):
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        # Charging, deficit starts at t=0.
        st.filter(_idle(), _view(power_w=4500.0), adapter,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        # EV unplugs — the stop must NOT be delayed.
        d = st.filter(_idle(), _view(connected=False, power_w=4500.0), adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=10.0)
        assert d.intent is ChargerIntent.IDLE

    def test_disable_intent_never_delayed(self):
        # DISABLE = user OFF / self-resume guard — a safety transition.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        decision = ChargerDecision(
            charger_id="wb", mode="off",
            intent=ChargerIntent.DISABLE, reason="off mode",
        )
        d = st.filter(decision, _view(power_w=4500.0), adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.DISABLE

    def test_timers_independent_per_charger(self):
        # Pinned for the legacy path by test_multi_charger_control —
        # same contract on the new filter.
        st = ChargeStability()
        a1, a2 = FakeAdapter(), FakeAdapter()
        st.filter(_charge(cid="a"), _view(cid="a"), a1,
                  enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        st.filter(_charge(cid="b"), _view(cid="b"), a2,
                  enable_delay_s=60, disable_delay_s=300, now_ts=50.0)
        da = st.filter(_charge(cid="a"), _view(cid="a"), a1,
                       enable_delay_s=60, disable_delay_s=300, now_ts=61.0)
        db = st.filter(_charge(cid="b"), _view(cid="b"), a2,
                       enable_delay_s=60, disable_delay_s=300, now_ts=61.0)
        assert da.intent is ChargerIntent.CHARGE_AT_AMPS
        assert db.intent is ChargerIntent.IDLE  # only 11 s held


@pytest.mark.unit
class TestWiring:
    def test_coordinator_filters_both_pipeline_branches(self) -> None:
        body = (Path(__file__).parent.parent / "coordinator"
                / "coordinator.py").read_text()
        assert body.count("self._charge_stability.filter(") >= 2, (
            "#461 anchor — the stability filter must wrap decide() in "
            "BOTH the multi-charger loop and the single-charger branch."
        )

    def test_config_card_exposes_the_delays(self) -> None:
        body = (Path(__file__).parent.parent / "dashboard" / "card" / "src"
                / "cards" / "sem-config-card.js").read_text()
        assert "number.sem_ev_enable_delay_seconds" in body
        assert "number.sem_ev_disable_delay_seconds" in body

