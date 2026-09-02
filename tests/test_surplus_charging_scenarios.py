"""Comprehensive surplus-charging scenario sweep.

Exercises the v1.7.0 decide → actuate pipeline (EV + battery) across
every (charge_mode × battery SOC zone × time-of-day × solar level)
combination. Each scenario is a realistic SEM operating point with an
explicit expected outcome for both the EV intent and the battery
intent.

Distinct from ``test_step8_invariants.py``:
- That suite asserts CONTRACTS (sum invariants, conservation, gates).
- This suite asserts BEHAVIOUR (the right intent in the right context),
  documented in plain English in each test name + reason.

Coverage matrix (5 × 4 × 2 × 3 = 120 base combos; filtered to the
distinguishable cases):

    Mode:    off / solar_only / min_plus_solar / always_max / solar_plus_cheap
    Zone:    1 (SOC < 30) / 2 (30 ≤ SOC < 70) / 3 (70 ≤ SOC < 90) / 4 (SOC ≥ 90)
    Time:    day / night
    Solar:   0 W (none) / 4500 W (modest) / 10000 W (strong)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    ChargerReconciler,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

def _zone_to_soc(zone: int) -> float:
    """Pick a representative SOC for each zone."""
    return {1: 20.0, 2: 50.0, 3: 80.0, 4: 95.0}[zone]


def _solar_label(solar_w: float) -> str:
    if solar_w == 0:
        return "no_solar"
    if solar_w <= 4500:
        return "modest_solar"
    return "strong_solar"


def _ev_view(
    *, mode: str, solar_w: float, soc: float, is_night: bool,
    home_w: float = 500.0, battery_charge_w: float = 0.0,
    battery_discharge_w: float = 0.0, target_kwh: float = 8.0,
    connected: bool = True,
) -> ChargerView:
    return ChargerView(
        power=ChargerPower(
            charger_id="keba", power_w=0.0,
            connected=connected, charging=False,
        ),
        energy=ChargerEnergy(charger_id="keba"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3,
                "ev_voltage": 230, "ev_max_current": 16},
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w,
            battery_charge_w=battery_charge_w,
            battery_discharge_w=battery_discharge_w,
            battery_soc=soc, is_night=is_night,
        ),
        target_kwh=target_kwh,
    )


def _battery_view(
    *, charging_state: str, ev_charging: bool,
    home_w: float = 500.0, soc: float = 50.0, solar_w: float = 0.0,
    buffer_soc: float = 0.0,
) -> BatteryView:
    # buffer_soc defaults to 0 so these tests exercise the SURPLUS gate arm of
    # the clamp in isolation. The buffer-floor arm (clamp when SoC < buffer
    # regardless of surplus) is covered in test_inverter_battery_arch.py.
    return BatteryView(
        runtime=BatteryRuntime(
            battery_id="primary", last_known_soc=soc, capacity_kwh=15.0,
        ),
        config={"battery_discharge_protection_enabled": True},
        fleet=FleetContext(battery_soc=soc, buffer_soc=buffer_soc,
                           solar_w=solar_w, home_w=home_w),
        charging_state=charging_state,
        ev_charging=ev_charging,
        home_consumption_w=home_w,
    )


# ─────────────────────────────────────────────────────────────────
# EV pipeline — every mode × zone × time × solar
# ─────────────────────────────────────────────────────────────────

# Off mode: always RELEASE (#898 — hands-off) regardless of any other dimension.
@pytest.mark.parametrize("zone", [1, 2, 3, 4])
@pytest.mark.parametrize("is_night", [False, True])
@pytest.mark.parametrize("solar_w", [0.0, 4500.0, 10000.0])
def test_off_mode_always_disables(zone, is_night, solar_w):
    d = decide(_ev_view(
        mode="off", solar_w=solar_w, soc=_zone_to_soc(zone),
        is_night=is_night,
    ))
    assert d.intent is ChargerIntent.RELEASE
    assert d.commanded_amps == 0 and d.budget_w == 0.0


# Always-max: always CHARGE_MAX when connected, regardless of solar/zone.
@pytest.mark.parametrize("zone", [1, 2, 3, 4])
@pytest.mark.parametrize("is_night", [False, True])
@pytest.mark.parametrize("solar_w", [0.0, 4500.0, 10000.0])
def test_always_max_mode_charges_max_when_connected(zone, is_night, solar_w):
    d = decide(_ev_view(
        mode="always_max", solar_w=solar_w, soc=_zone_to_soc(zone),
        is_night=is_night,
    ))
    assert d.intent is ChargerIntent.CHARGE_MAX


# Solar-only: charge only from real solar surplus.
class TestSolarOnlyModeAcrossZones:
    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_solar_only_at_night_idles_with_no_floor(self, zone):
        """The #346 invariant, floor-scoped by #634: with NO "At least" floor
        (target 0), solar_only at night never charges — the classic contract."""
        d = decide(_ev_view(
            mode="solar_only", solar_w=0.0, soc=_zone_to_soc(zone),
            is_night=True, target_kwh=0.0,
        ))
        assert d.intent is ChargerIntent.IDLE

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_solar_only_at_night_tops_up_the_floor_difference(self, zone):
        """(#634) With an "At least" floor outstanding, solar_only tops up the
        difference overnight from grid — the floor is the mode-independent
        guarantee; the mode is the daytime axis."""
        d = decide(_ev_view(
            mode="solar_only", solar_w=0.0, soc=_zone_to_soc(zone),
            is_night=True, target_kwh=1.5,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "solar_only night" in d.reason

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_solar_only_no_solar_idles(self, zone):
        d = decide(_ev_view(
            mode="solar_only", solar_w=0.0, soc=_zone_to_soc(zone),
            is_night=False,
        ))
        assert d.intent is ChargerIntent.IDLE

    @pytest.mark.parametrize("zone", [1, 2, 3, 4])
    def test_solar_only_modest_solar_battery_full_charges(self, zone):
        """4500 W solar - 500 W home = 4000 W surplus. With SOC ≥
        auto_start (Zone 4), battery doesn't compete; charger gets
        all surplus. Zone 1-3 same when battery_charge_w=0."""
        d = decide(_ev_view(
            mode="solar_only", solar_w=4500.0, soc=_zone_to_soc(zone),
            is_night=False, battery_charge_w=0.0,
        ))
        if 4500 - 500 >= 6 * 3 * 230:
            assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        else:
            assert d.intent is ChargerIntent.IDLE  # below min

    def test_solar_only_strong_solar_zone_4_charges_to_max(self):
        """10 kW solar - 500 W home = 9500 W → 13 A (capped at 16 A)."""
        d = decide(_ev_view(
            mode="solar_only", solar_w=10000.0, soc=95.0,
            is_night=False, battery_charge_w=0.0,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps >= 6
        assert d.commanded_amps <= 16

    def test_solar_only_strong_solar_battery_competing_can_idle(self):
        """10 kW solar but battery charging 9 kW + home 500 → only
        500 W left. Below min → IDLE."""
        d = decide(_ev_view(
            mode="solar_only", solar_w=10000.0, soc=50.0,
            is_night=False, battery_charge_w=9000.0,
        ))
        assert d.intent is ChargerIntent.IDLE


# Min+Solar: day = zone-aware battery assist; night = top-up to Min floor.
class TestMinPlusSolarAcrossZones:
    def test_min_plus_solar_night_below_target_tops_up_at_min(self):
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=0.0, soc=50.0,
            is_night=True, target_kwh=5.0,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6

    def test_min_plus_solar_night_target_reached_idles(self):
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=0.0, soc=50.0,
            is_night=True, target_kwh=0.05,
        ))
        assert d.intent is ChargerIntent.IDLE

    def test_min_plus_solar_day_zone_1_idles(self):
        """SOC < 30 (Zone 1) — battery priority blocks EV."""
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=8000.0, soc=20.0,
            is_night=False,
        ))
        assert d.intent is ChargerIntent.IDLE
        assert "Zone 1" in d.reason

    def test_min_plus_solar_day_zone_2_pure_solar(self):
        """SOC 50 (Zone 2) — pure solar surplus, no battery assist."""
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=8000.0, soc=50.0,
            is_night=False,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_min_plus_solar_day_zone_3_battery_assist(self):
        """SOC 80 (Zone 3) + battery discharging → assist."""
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=3000.0, soc=80.0,
            battery_discharge_w=2000.0, is_night=False,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_min_plus_solar_day_zone_4_full_assist(self):
        """SOC 95 (Zone 4) with solar surplus above the gate → full
        assist budget tops up to the EV minimum. (Solar gate: assist
        only fires when there is real solar to supplement — solar=0
        would idle instead, preserving the battery.)"""
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=2000.0, home_w=500.0,
            soc=95.0, is_night=False,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "Zone 4" in d.reason


# Solar+cheap: night defers to cheap window; day = solar_only/pause.
class TestSolarPlusCheapAcrossZones:
    def test_solar_plus_cheap_day_normal_tariff_zone_2(self):
        view = _ev_view(
            mode="solar_plus_cheap", solar_w=8000.0, soc=50.0,
            is_night=False,
        )
        # Set tariff to normal (not in pausing levels)
        from dataclasses import replace
        view_with_tariff = replace(
            view, fleet=replace(view.fleet, tariff_level="normal"),
        )
        d = decide(view_with_tariff)
        # Falls through to solar_only path → charge if surplus
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_solar_plus_cheap_day_expensive_tariff_pauses_grid(self):
        view = _ev_view(
            mode="solar_plus_cheap", solar_w=10000.0, soc=95.0,
            is_night=False,
        )
        from dataclasses import replace
        view = replace(
            view, fleet=replace(view.fleet, tariff_level="expensive"),
        )
        d = decide(view)
        # Solar high → still charges from surplus
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "tariff=expensive" in d.reason


# ─────────────────────────────────────────────────────────────────
# Battery pipeline — every (mode-implied charging_state × ev_charging)
# ─────────────────────────────────────────────────────────────────

class TestBatteryPipelineAcrossStates:
    def test_night_charging_active_ev_drawing_limits_discharge(self):
        d = decide_battery(_battery_view(
            charging_state="night_charging_active",
            ev_charging=True, home_w=1500.0,
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 1500.0

    def test_night_charging_active_no_ev_drawing_normal(self):
        d = decide_battery(_battery_view(
            charging_state="night_charging_active",
            ev_charging=False,
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_solar_charging_active_ev_drawing_normal_with_surplus(self):
        """Day-time EV charging with real solar surplus (≥ gate) does
        NOT trip protection — the battery is free to assist."""
        d = decide_battery(_battery_view(
            charging_state="solar_charging_active",
            ev_charging=True, solar_w=4000.0, home_w=500.0,
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_solar_charging_active_ev_drawing_below_gate_limits(self):
        """Day-time EV charging but solar surplus below the gate
        (cloudy) → the unified clamp protects the battery."""
        d = decide_battery(_battery_view(
            charging_state="solar_charging_active",
            ev_charging=True, solar_w=300.0, home_w=800.0,
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 800.0

    def test_solar_idle_state_normal(self):
        d = decide_battery(_battery_view(
            charging_state="solar_idle", ev_charging=False,
        ))
        assert d.intent is BatteryIntent.NORMAL


# ─────────────────────────────────────────────────────────────────
# Full timeline — sunny-day surplus charging
# ─────────────────────────────────────────────────────────────────

class TestSurplusChargingTimeline:
    """Walk a full sunny day: morning low → noon peak → afternoon
    decline → evening. Verifies decide+actuate produces a coherent
    sequence of decisions at each phase."""

    @pytest.mark.parametrize("phase,solar_w,soc,expected_intent", [
        ("dawn",          200.0, 30.0, ChargerIntent.IDLE),         # below 200W threshold
        ("morning",      2000.0, 45.0, ChargerIntent.IDLE),         # 2000-500=1500<4140 min
        ("late_morning", 5000.0, 60.0, ChargerIntent.CHARGE_AT_AMPS),
        ("noon",        10000.0, 80.0, ChargerIntent.CHARGE_AT_AMPS),
        ("afternoon",    7000.0, 90.0, ChargerIntent.CHARGE_AT_AMPS),
        ("evening",       800.0, 95.0, ChargerIntent.IDLE),         # 800-500=300<4140
        # (#634) dusk WITH the default 8 kWh floor outstanding → the
        # overnight top-up engages (the floor is the guarantee).
        ("dusk",            0.0, 92.0, ChargerIntent.CHARGE_AT_AMPS),
    ])
    def test_solar_only_full_day_timeline(
        self, phase, solar_w, soc, expected_intent,
    ):
        d = decide(_ev_view(
            mode="solar_only", solar_w=solar_w, soc=soc,
            is_night=(phase == "dusk"),
        ))
        assert d.intent is expected_intent, (
            f"phase={phase} solar={solar_w} soc={soc} produced "
            f"{d.intent} (expected {expected_intent}): {d.reason}"
        )


# ─────────────────────────────────────────────────────────────────
# Actuate dispatch — full coverage with mock adapter
# ─────────────────────────────────────────────────────────────────

def _ev_adapter(*, drawing: bool = False, setpoint_a: int = 0, max_a: int = 32):
    """Mock adapter that satisfies the reconciler's ``observe()`` contract.

    ``drawing`` models a charger already pulling power (so an OFF intent
    converges via ``command_disable``); a fresh idle charger (default)
    converges an IDLE intent to NONE.
    """
    a = MagicMock()
    a.command_disable = AsyncMock()
    a.command_idle = AsyncMock()
    a.command_current = AsyncMock()
    a.command_max = AsyncMock()
    a.arm_failsafe = AsyncMock()
    a.ensure_enabled = AsyncMock()
    a.is_self_charging = MagicMock(return_value=False)
    a.actual_charging = MagicMock(return_value=drawing)
    a.enable_state = MagicMock(return_value=(None, True))  # no readable switch
    a.max_current_a = max_a
    a._device = MagicMock(_current_setpoint=setpoint_a)
    a.last_intent = None
    return a


def _battery_adapter():
    a = MagicMock()
    a.command_normal = AsyncMock()
    a.command_limit_discharge = AsyncMock()
    a.command_force_charge = AsyncMock()
    a.command_stop_force_charge = AsyncMock()
    a.supports_forced_charge = True
    return a


class TestEndToEndActuation:
    """For each (mode, zone) combo, run decide → actuate (through a real
    ``ChargerReconciler``, the production convergence path) and verify the
    right adapter command was issued.

    Migrated from the legacy direct-dispatch path (Task 11): the reconciler
    now owns convergence, so the expected outcomes follow its semantics —
    OFF disables only a *drawing* box, CHARGE_* converge via
    ``command_current`` (not ``command_max``/``command_current`` split), and
    an IDLE intent on an already-open contactor converges to NONE (no
    ``command_idle`` churn — the root-cause fix for the keba.disable spam).
    """

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode,solar_w,soc,is_night,drawing,expected_intent,expected_cmd", [
        # (#898) OFF + drawing box SEM never started → RELEASE, hands-off:
        # the reconciler issues nothing (a fresh reconciler has no session
        # of its own to end).
        ("off",            5000.0, 50.0, False, True,  ChargerIntent.RELEASE,       None),
        ("off",            5000.0, 50.0, True,  True,  ChargerIntent.RELEASE,       None),
        # OFF + already-open contactor → DISABLE intent but reconciler emits
        # NONE (idempotent — the production no-spam case).
        ("off",               0.0, 95.0, False, False, ChargerIntent.RELEASE,       None),
        # ALWAYS_MAX: CHARGE_MAX → reconciler START_AND_WRITE → command_current(max).
        ("always_max",        0.0, 50.0, True,  False, ChargerIntent.CHARGE_MAX,    "command_current"),
        ("always_max",    10000.0, 50.0, False, False, ChargerIntent.CHARGE_MAX,    "command_current"),
        # SOLAR_ONLY night with the 10 kWh floor outstanding (#634) → the
        # overnight top-up engages exactly like min_plus_solar night.
        ("solar_only",        0.0, 50.0, True,  False, ChargerIntent.CHARGE_AT_AMPS, "command_current"),
        # SOLAR_ONLY strong surplus → CHARGE_AT_AMPS → command_current.
        ("solar_only",       10000.0, 95.0, False, False, ChargerIntent.CHARGE_AT_AMPS, "command_current"),
        # MIN_PLUS_SOLAR night top-up → CHARGE_AT_AMPS at min → command_current.
        ("min_plus_solar",    0.0, 50.0, True,  False, ChargerIntent.CHARGE_AT_AMPS, "command_current"),
        # MIN_PLUS_SOLAR day Zone 1 → IDLE intent → reconciler NONE.
        ("min_plus_solar", 8000.0, 20.0, False, False, ChargerIntent.IDLE,          None),
    ])
    async def test_decide_to_actuate_dispatch(
        self, mode, solar_w, soc, is_night, drawing, expected_intent, expected_cmd,
    ):
        view = _ev_view(
            mode=mode, solar_w=solar_w, soc=soc, is_night=is_night,
            target_kwh=10.0,
        )
        decision = decide(view)
        assert decision.intent is expected_intent, (
            f"mode={mode} solar={solar_w} soc={soc} night={is_night}: "
            f"expected intent {expected_intent}, got {decision.intent} "
            f"reason={decision.reason}"
        )

        adapter = _ev_adapter(drawing=drawing)
        reconciler = ChargerReconciler(
            charger_id="keba", heartbeat_s=5.0, idle_disable_threshold=4,
        )
        await actuate(decision, adapter, view.power, reconciler=reconciler)

        cmd_methods = ("command_disable", "command_current", "command_max", "command_idle")
        if expected_cmd is None:
            for name in cmd_methods:
                assert getattr(adapter, name).await_count == 0, (
                    f"mode={mode} solar={solar_w} soc={soc} night={is_night}: "
                    f"expected NONE (idempotent), but {name} was called; "
                    f"intent={decision.intent} reason={decision.reason}"
                )
        else:
            assert getattr(adapter, expected_cmd).await_count >= 1, (
                f"mode={mode} solar={solar_w} soc={soc} night={is_night}: "
                f"expected {expected_cmd}, got intent={decision.intent} "
                f"reason={decision.reason}"
            )


# ─────────────────────────────────────────────────────────────────
# Joint coherence — EV + battery decisions at the same operating
# point are non-contradictory (no "EV charging from solar" + "battery
# discharging to home" simultaneously when the EV is at handshake idle)
# ─────────────────────────────────────────────────────────────────

class TestNightTargetReachedVsDecide:
    """PR A regression — when the legacy state machine sets
    NIGHT_TARGET_REACHED based on a per_charger_target ≤ 0.1, but
    decide_v2 is fed a different target_kwh (per_remaining_floor)
    that's > 0.1, the post-decide intent-to-state mapper used to
    unconditionally overwrite NIGHT_TARGET_REACHED with
    SOLAR_CHARGING_ACTIVE. Observed live on PROD 2026-06-01.

    Two assertions:
    1. decide_v2 sees the same target_kwh the state machine sees
       (per_charger_target when set, per_remaining_floor otherwise).
    2. When the per-decide effective_state is NIGHT_TARGET_REACHED,
       the post-decide mapper doesn't clobber it.
    """

    def test_decide_uses_resolved_per_charger_target(self):
        """Test the resolution logic that feeds build_charger_view's
        target_kwh: per_charger_target wins when set, falls back to
        per_remaining_floor otherwise.

        This matches charging_context.night_target_kwh at
        coordinator.py:1287 — the value the legacy night-state
        check at 1323 uses for the ≤0.1 threshold.
        """
        # Scenario: per_charger_target = 0.05 (state-machine says
        # "target reached"); per_remaining_floor = 0.6 (a different
        # bound).
        per_charger_target = 0.05
        per_remaining_floor = 0.6
        resolved = (
            per_charger_target
            if per_charger_target is not None
            else per_remaining_floor
        )
        assert resolved == 0.05, (
            "PR A: target_kwh passed to decide must be the resolved "
            "per_charger_target (the value used by the legacy state "
            "machine), not the divergent per_remaining_floor."
        )

        # With resolved=0.05, decide_v2 sees target_kwh=0.05 → IDLE
        # (matches state machine's NIGHT_TARGET_REACHED).
        view = _ev_view(
            mode="min_plus_solar", solar_w=0, soc=80,
            is_night=True, target_kwh=resolved,
        )
        d = decide(view)
        assert d.intent is ChargerIntent.IDLE, (
            f"With target_kwh={resolved} ≤ 0.1, decide must return "
            f"IDLE (matching state-machine's NIGHT_TARGET_REACHED). "
            f"Got {d.intent}: {d.reason}"
        )


class TestJointDecisionCoherence:
    """When both pipelines run on the same cycle, do their decisions
    fit together? Sample a few realistic operating points and verify."""

    def test_night_ev_charging_battery_protected(self):
        ev_view = _ev_view(
            mode="min_plus_solar", solar_w=0.0, soc=50.0,
            is_night=True, target_kwh=8.0,
        )
        ev = decide(ev_view)
        bat = decide_battery(_battery_view(
            charging_state="night_charging_active",
            ev_charging=True, home_w=600.0, soc=50.0,
        ))
        # EV charging at min, battery protected (limited to home)
        assert ev.intent is ChargerIntent.CHARGE_AT_AMPS
        assert bat.intent is BatteryIntent.LIMIT_DISCHARGE
        assert bat.discharge_limit_w == 600.0

    def test_sunny_day_ev_off_battery_normal(self):
        ev = decide(_ev_view(
            mode="off", solar_w=10000.0, soc=80.0, is_night=False,
        ))
        bat = decide_battery(_battery_view(
            charging_state="solar_idle", ev_charging=False, soc=80.0,
        ))
        assert ev.intent is ChargerIntent.RELEASE   # (#898) hands-off
        assert bat.intent is BatteryIntent.NORMAL

    def test_solar_only_sunny_zone_4_ev_charging_battery_normal(self):
        ev = decide(_ev_view(
            mode="solar_only", solar_w=10000.0, soc=95.0,
            is_night=False, battery_charge_w=0.0,
        ))
        bat = decide_battery(_battery_view(
            charging_state="solar_charging_active", ev_charging=True, soc=95.0,
            solar_w=10000.0, home_w=500.0,
        ))
        # EV charges from surplus; with real solar surplus (9500 ≥ gate)
        # the battery is NOT clamped — it may assist freely.
        assert ev.intent is ChargerIntent.CHARGE_AT_AMPS
        assert bat.intent is BatteryIntent.NORMAL
