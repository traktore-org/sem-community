"""#461 — hysteresis enable/disable delays between decide() and actuate().

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
  (deficit-persistence, deliberately NOT the legacy
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
          cid="wb", solar_w=3000.0, min_solar_w=200.0, tariff_level=None,
          battery_soc=90.0, buffer_soc=70.0, home_w=0.0):
    # ``solar_w`` defaults to a MEANINGFUL value (3 kW > the 200 W
    # min_solar_w) so a deficit on this view reads as TRANSIENT — a
    # passing cloud, the case the disable hold is meant to bridge.
    # Deep-deficit tests (#461 part 2) pass ``solar_w=0`` explicitly.
    # INVARIANT: ``battery_soc`` MUST default ≥ ``buffer_soc`` so the
    # default deficit is bridgeable by the battery → TestDisableDelay keeps
    # testing the "assist available → full 300 s bridge" path, NOT the
    # no_assist_deficit short-grace escape. Drop it below buffer here and
    # every transient-bridge test silently flips to a 45 s stop. The
    # no-assist tests pass a below-buffer SoC explicitly.
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w,
                           connected=connected, charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=is_night, solar_w=solar_w,
                           min_solar_w=min_solar_w, tariff_level=tariff_level,
                           battery_soc=battery_soc, buffer_soc=buffer_soc,
                           home_w=home_w),
    )


def _charge(cid="wb", amps=6):
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps, budget_w=4500.0,
        reason="solar_only: surplus ok",
    )


def _idle(cid="wb", bridgeable=True):
    # bridgeable is now decide()'s call (single source of truth): True = a
    # transient dip the bridge should hold through; False = a structural idle
    # (sun gone / battery can't assist / not-cheap tariff) the bridge must NOT
    # grid-hold. The bridge reads this flag instead of re-deriving it.
    return ChargerDecision(
        charger_id=cid, mode="solar_only",
        intent=ChargerIntent.IDLE, bridgeable=bridgeable,
        reason="solar_only: surplus below min",
    )


def _idle_structural(cid="wb"):
    """A structural IDLE (decide set bridgeable=False)."""
    return _idle(cid=cid, bridgeable=False)


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
        assert "starting at 6A" in d.reason and "auto-raises" in d.reason

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

    def test_full_bridge_in_assist_band_below_auto_start(self):
        # Pin the [buffer, auto_start) band explicitly (M1): SoC 75 ≥ buffer
        # 70 → battery can assist → the thin-surplus deficit still gets the
        # full 300 s bridge, NOT the no_assist_deficit short grace.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)
        view = _view(power_w=4500.0, solar_w=3000.0, home_w=2500.0,
                     battery_soc=75.0, buffer_soc=70.0)
        for t in (0.0, 150.0, 290.0):
            d = st.filter(_idle(), view, adapter, enable_delay_s=60,
                          disable_delay_s=300, deep_deficit_grace_s=45, now_ts=t)
            assert d.intent is ChargerIntent.CHARGE_AT_AMPS, f"stopped early at {t}"

    def test_deficit_timer_survives_charging_blip(self):
        # Regression (PROD 2026-06-26): a bursty car (Zoe) blips power to 0
        # between pulses. With ``last_intent`` not a charge intent, a blip
        # flipped ``charging`` False and RESET the deficit timer — so the
        # disable-bridge never reached its stop, the contactor stayed on, and
        # the battery drained below the buffer floor. The latch (refreshed on
        # every real draw) must hold the deficit through the blips so the
        # bridge still stops at disable_delay.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)  # charging follows actual draw
        drawing = _view(power_w=4500.0)
        blip = _view(power_w=0.0)
        st.filter(_idle(), drawing, adapter,
                  enable_delay_s=0, disable_delay_s=300, now_ts=0.0)
        # Blip at t=30 (car drew at t=0, within LATCH_HOLD_S) — must NOT reset.
        st.filter(_idle(), blip, adapter,
                  enable_delay_s=0, disable_delay_s=300, now_ts=30.0)
        # Draw again (latch refreshed), blip again — still no reset.
        st.filter(_idle(), drawing, adapter,
                  enable_delay_s=0, disable_delay_s=300, now_ts=60.0)
        st.filter(_idle(), blip, adapter,
                  enable_delay_s=0, disable_delay_s=300, now_ts=90.0)
        # Still holding just before the window (timer anchored at t=0, blips
        # didn't reset it).
        d290 = st.filter(_idle(), drawing, adapter,
                         enable_delay_s=0, disable_delay_s=300, now_ts=290.0)
        assert d290.intent is ChargerIntent.CHARGE_AT_AMPS
        # Stops at the window — the blips did NOT push the stop out.
        d301 = st.filter(_idle(), drawing, adapter,
                         enable_delay_s=0, disable_delay_s=300, now_ts=301.0)
        assert d301.intent is ChargerIntent.IDLE

    def test_deficit_resets_after_sustained_no_draw(self):
        # The latch must NOT keep a genuinely-stopped car alive: no draw for
        # longer than LATCH_HOLD_S → the deficit resets and it idles.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        drawing = _view(power_w=4500.0)
        stopped = _view(power_w=0.0)
        st.filter(_idle(), drawing, adapter,
                  enable_delay_s=0, disable_delay_s=300, now_ts=0.0)
        # No draw since t=0; at t=70 (> LATCH_HOLD_S=60) the blip resets → idle.
        d70 = st.filter(_idle(), stopped, adapter,
                        enable_delay_s=0, disable_delay_s=300, now_ts=70.0)
        assert d70.intent is ChargerIntent.IDLE

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
            fleet=FleetContext(is_night=False, solar_w=3000.0),
        )
        d = st.filter(_idle(), view, adapter,
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.commanded_amps == 9


@pytest.mark.unit
class TestStructuralIdleBridge:
    """The bridge HOLDS a transient dip (``bridgeable=True``) but must NOT keep
    the contactor closed for a STRUCTURAL idle (``bridgeable=False``).

    RienduPre's PROD logs: the hold commanding 9 A, the car flapping 4.35 kW↔
    0.12 kW while the home battery drained and the grid imported — the full
    window, every window. The structural-vs-transient call is now decide()'s
    (single source of truth, ``decision.bridgeable``); the bridge just honours
    it — short grace for structural, full bridge for transient. decide()'s
    classification (sun gone / not-cheap tariff / battery-can't-assist) is
    tested in ``test_decide.py::TestIdleBridgeable``.
    """

    def _charging(self):
        return FakeAdapter(last_intent=ChargerIntent.CHARGE_AT_AMPS)

    def test_structural_idle_stops_after_grace_not_full_window(self):
        # bridgeable=False: the hold lasts only the short grace, NOT 300 s.
        st = ChargeStability()
        adapter = self._charging()
        view = _view(power_w=4500.0)
        d0 = st.filter(_idle_structural(), view, adapter, enable_delay_s=60,
                       disable_delay_s=300, deep_deficit_grace_s=45, now_ts=0.0)
        assert d0.intent is ChargerIntent.CHARGE_AT_AMPS  # grace not elapsed
        d30 = st.filter(_idle_structural(), view, adapter, enable_delay_s=60,
                        disable_delay_s=300, deep_deficit_grace_s=45, now_ts=30.0)
        assert d30.intent is ChargerIntent.CHARGE_AT_AMPS
        d50 = st.filter(_idle_structural(), view, adapter, enable_delay_s=60,
                        disable_delay_s=300, deep_deficit_grace_s=45, now_ts=50.0)
        assert d50.intent is ChargerIntent.IDLE  # stopped well before 300 s
        assert "structural idle" in d50.reason
        assert "not bridging" in d50.reason

    def test_transient_idle_gets_full_bridge(self):
        # bridgeable=True (the default): the cloud-bridge hold survives past
        # the short grace — full disable-delay behaviour.
        st = ChargeStability()
        adapter = self._charging()
        view = _view(power_w=4500.0)
        for t in (0.0, 50.0, 150.0, 290.0):
            d = st.filter(_idle(), view, adapter, enable_delay_s=60,
                          disable_delay_s=300, deep_deficit_grace_s=45, now_ts=t)
            assert d.intent is ChargerIntent.CHARGE_AT_AMPS, f"stopped early at {t}"
        d = st.filter(_idle(), view, adapter, enable_delay_s=60,
                      disable_delay_s=300, deep_deficit_grace_s=45, now_ts=301.0)
        assert d.intent is ChargerIntent.IDLE

    def test_single_cycle_structural_flicker_does_not_trip_stop(self):
        # A one-cycle bridgeable=False blip inside an otherwise transient
        # deficit must NOT end the session: the grace outlives it and a
        # bridgeable=True cycle clears the short timer.
        st = ChargeStability()
        adapter = self._charging()
        view = _view(power_w=4500.0)
        st.filter(_idle(), view, adapter, deep_deficit_grace_s=45, now_ts=0.0)
        st.filter(_idle_structural(), view, adapter, deep_deficit_grace_s=45, now_ts=10.0)
        d = st.filter(_idle(), view, adapter, deep_deficit_grace_s=45, now_ts=20.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        d = st.filter(_idle(), view, adapter, deep_deficit_grace_s=45, now_ts=80.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_structural_holds_at_vehicle_min_then_stops(self):
        # vehicle_min_current (9 A) > ev_min (6 A): the in-grace hold
        # respects the vehicle floor, then the structural stop drops to 0 A.
        st = ChargeStability()
        adapter = self._charging()
        view = ChargerView(
            power=ChargerPower(charger_id="wb", power_w=6000.0,
                               connected=True, charging=True),
            energy=ChargerEnergy(charger_id="wb"),
            mode="solar_only",
            config={"ev_min_current": 6, "vehicle_min_current": 9,
                    "ev_max_current": 16},
            fleet=FleetContext(is_night=False, solar_w=0.0, min_solar_w=200.0),
        )
        d0 = st.filter(_idle_structural(), view, adapter, deep_deficit_grace_s=45, now_ts=0.0)
        assert d0.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d0.commanded_amps == 9  # vehicle floor during the grace
        d = st.filter(_idle_structural(), view, adapter, deep_deficit_grace_s=45, now_ts=50.0)
        assert d.intent is ChargerIntent.IDLE
        assert d.commanded_amps == 0

    def test_night_flag_still_bypasses_entirely(self):
        # is_night already stops immediately (filter is transparent); the
        # bridge is the DAY guard for the dusk/overcast window.
        st = ChargeStability()
        adapter = self._charging()
        view = _view(power_w=4500.0, is_night=True)
        d = st.filter(_idle(), view, adapter, deep_deficit_grace_s=45, now_ts=0.0)
        assert d.intent is ChargerIntent.IDLE  # decide()'s IDLE passes straight through


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

    # These pin the mechanism at the classic 3-window / 30 s / 1 A timing
    # so they stay meaningful independent of the production defaults (now
    # tuned steadier: 5-window / 90 s / 2 A).
    _G = dict(smooth_window=3, min_change_amps=1, min_change_interval_s=30)

    def test_ramp_limits_step_size(self):
        # A surplus jump from 10 A to 16 A worth of sun moves the
        # setpoint by at most ramp_amps per change.
        st, adapter, view = self._charging_setup()
        st.filter(_charge(amps=10), view, adapter, now_ts=0.0, **self._G)
        st.filter(_charge(amps=10), view, adapter, now_ts=10.0, **self._G)
        d = st.filter(_charge(amps=16), view, adapter, now_ts=40.0, **self._G)
        # median of [10, 10, 16] = 10 → still 10; feed another 16.
        d = st.filter(_charge(amps=16), view, adapter, now_ts=80.0, **self._G)
        assert d.commanded_amps == 12  # 10 + ramp(2), not 16

    def test_debounce_one_change_per_interval(self):
        st, adapter, view = self._charging_setup()
        st.filter(_charge(amps=10), view, adapter, now_ts=0.0, **self._G)   # adopt 10
        st.filter(_charge(amps=16), view, adapter, now_ts=10.0, **self._G)
        d = st.filter(_charge(amps=16), view, adapter, now_ts=20.0, **self._G)
        # Median has reached 16 by t=20, but the last change was at
        # t=0 — within the 30 s debounce the setpoint must not move.
        assert d.commanded_amps == 10
        assert "debounce" in d.reason
        d = st.filter(_charge(amps=16), view, adapter, now_ts=45.0, **self._G)
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
    def test_night_is_processed_and_starts_immediately(self):
        # Night is no longer skipped — it shares the day latch/hold/escalation
        # and starts at once (no surplus enable-delay to wait on).
        st = ChargeStability()
        d = st.filter(_charge(), _view(is_night=True), FakeAdapter(),
                      enable_delay_s=60, disable_delay_s=300, now_ts=0.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6

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

    def test_fleet_tariff_level_uses_get_price_level(self) -> None:
        # #524 — the fleet cycle state must read the tariff level via the
        # provider's ``get_price_level()`` API. The old
        # ``getattr(provider, "current_level", None)`` referenced a
        # non-existent attribute and silently left tariff_level None,
        # killing every tariff-aware EV decision.
        body = (Path(__file__).parent.parent / "coordinator"
                / "coordinator.py").read_text()
        assert "provider.get_price_level()" in body, (
            "#524 anchor — fleet tariff_level must come from "
            "provider.get_price_level()."
        )
        assert 'getattr(provider, "current_level"' not in body, (
            "#524 — the dead current_level read must not return."
        )



@pytest.mark.unit
class TestDurableStop:
    """Once the bridge STOPS a structural idle it must STAY stopped. The PROD
    2026-06-27 history showed it re-engaging forever (hold → stop → "holding
    8A" again) because the draw-latch survived the wind-down and the next
    cycle re-entered the hold, re-offering min current — self-sustaining.
    Covers the durable stop (latch clear) + the post-stop settle that survives
    actuator lag, and that a real CHARGE still resumes."""

    def test_stop_is_durable_no_reengage_loop(self):
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)  # charging follows draw
        drawing = _view(power_w=4500.0)
        stopped = _view(power_w=0.0)
        # Hold then stop on the short grace (structural idle).
        st.filter(_idle_structural(), drawing, adapter, enable_delay_s=60,
                  disable_delay_s=300, deep_deficit_grace_s=45, now_ts=0.0)
        d46 = st.filter(_idle_structural(), drawing, adapter, enable_delay_s=60,
                        disable_delay_s=300, deep_deficit_grace_s=45, now_ts=46.0)
        assert d46.intent is ChargerIntent.IDLE  # short-grace stop
        # Car wound down; 10 s later (< LATCH_HOLD_S) it must STAY stopped,
        # not re-offer 8 A. Pre-fix this returned "holding 8A".
        d56 = st.filter(_idle_structural(), stopped, adapter, enable_delay_s=60,
                        disable_delay_s=300, deep_deficit_grace_s=45, now_ts=56.0)
        assert d56.intent is ChargerIntent.IDLE
        assert "holding" not in d56.reason

    def test_stop_survives_actuator_lag(self):
        # After the stop clears the latch, a car STILL drawing on the very next
        # cycle (KEBA hasn't cut the contactor yet) must not re-stamp the latch
        # and re-open the hold. The post-stop settle honours the IDLE through
        # the wind-down — no re-offer.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        drawing = _view(power_w=4500.0)
        st.filter(_idle_structural(), drawing, adapter, enable_delay_s=60,
                  disable_delay_s=300, deep_deficit_grace_s=45, now_ts=0.0)
        d46 = st.filter(_idle_structural(), drawing, adapter, enable_delay_s=60,
                        disable_delay_s=300, deep_deficit_grace_s=45, now_ts=46.0)
        assert d46.intent is ChargerIntent.IDLE  # short-grace stop
        # T+1: car STILL drawing (actuator lag) — must NOT re-offer.
        d47 = st.filter(_idle_structural(), drawing, adapter, enable_delay_s=60,
                        disable_delay_s=300, deep_deficit_grace_s=45, now_ts=47.0)
        assert d47.intent is ChargerIntent.IDLE
        assert "holding" not in d47.reason
        # Wound down later — stays stopped.
        d100 = st.filter(_idle_structural(), _view(power_w=0.0), adapter,
                         enable_delay_s=60, disable_delay_s=300,
                         deep_deficit_grace_s=45, now_ts=100.0)
        assert d100.intent is ChargerIntent.IDLE

    def test_charge_resumes_after_stop_when_surplus_returns(self):
        # The settle must NOT trap the charger off: once decide wants to charge
        # again (surplus returned → CHARGE), charging resumes normally.
        st = ChargeStability()
        adapter = FakeAdapter(last_intent=None)
        drawing = _view(power_w=4500.0)
        st.filter(_idle_structural(), drawing, adapter, enable_delay_s=0,
                  disable_delay_s=300, deep_deficit_grace_s=45, now_ts=0.0)
        st.filter(_idle_structural(), drawing, adapter, enable_delay_s=0,
                  disable_delay_s=300, deep_deficit_grace_s=45, now_ts=46.0)
        good = _view(power_w=4500.0, solar_w=9000.0)
        d = st.filter(_charge(amps=10), good, adapter, enable_delay_s=0,
                      disable_delay_s=300, deep_deficit_grace_s=45, now_ts=60.0)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS


@pytest.mark.unit
class TestEvccAlignedDefaults:
    """#546 — defaults aligned to evcc: track surplus on a ~30 s cadence (NOT a
    multi-minute freeze) with a 2 A deadband, and 1-min start / 3-min stop
    delays. evcc proves a steady-needing car charges THROUGH smooth current
    changes once the box holds the offer (Phase A: persisted failsafe, no 6 A
    revert). The 30 s-debounce mechanism itself is covered by
    ``test_debounce_one_change_per_interval``; this locks the chosen DEFAULTS."""

    def test_cadence_and_delay_defaults(self):
        from custom_components.solar_energy_management.coordinator import (
            charge_stability as cs,
        )
        assert cs.DEFAULT_MIN_CHANGE_INTERVAL_S == 30   # evcc cadence (was 90)
        assert cs.DEFAULT_MIN_CHANGE_AMPS == 2          # deadband = anti-flap
        assert cs.DEFAULT_ENABLE_DELAY_S == 60          # evcc enable.delay 1 min
        assert cs.DEFAULT_DISABLE_DELAY_S == 180        # evcc disable.delay 3 min (was 300)

    def test_consts_delay_defaults(self):
        from custom_components.solar_energy_management.consts import core as C
        assert C.DEFAULT_EV_ENABLE_DELAY_SEC == 60
        assert C.DEFAULT_EV_DISABLE_DELAY_SEC == 180    # was 300
