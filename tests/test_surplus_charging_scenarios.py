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
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    ChargerDecision,
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
    home_w: float = 500.0, soc: float = 50.0,
) -> BatteryView:
    return BatteryView(
        runtime=BatteryRuntime(
            battery_id="primary", last_known_soc=soc, capacity_kwh=15.0,
        ),
        config={"battery_discharge_protection_enabled": True},
        fleet=FleetContext(battery_soc=soc),
        charging_state=charging_state,
        ev_charging=ev_charging,
        home_consumption_w=home_w,
    )


# ─────────────────────────────────────────────────────────────────
# EV pipeline — every mode × zone × time × solar
# ─────────────────────────────────────────────────────────────────

# Off mode: always DISABLE regardless of any other dimension.
@pytest.mark.parametrize("zone", [1, 2, 3, 4])
@pytest.mark.parametrize("is_night", [False, True])
@pytest.mark.parametrize("solar_w", [0.0, 4500.0, 10000.0])
def test_off_mode_always_disables(zone, is_night, solar_w):
    d = decide(_ev_view(
        mode="off", solar_w=solar_w, soc=_zone_to_soc(zone),
        is_night=is_night,
    ))
    assert d.intent is ChargerIntent.DISABLE


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
    def test_solar_only_at_night_always_idles(self, zone):
        """The #346 invariant — solar_only at night must never charge."""
        d = decide(_ev_view(
            mode="solar_only", solar_w=0.0, soc=_zone_to_soc(zone),
            is_night=True,
        ))
        assert d.intent is ChargerIntent.IDLE

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
        """SOC 95 (Zone 4) + battery dischargeing → full assist budget."""
        d = decide(_ev_view(
            mode="min_plus_solar", solar_w=0.0, home_w=500.0,
            battery_discharge_w=4500.0, soc=95.0, is_night=False,
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

    def test_solar_charging_active_ev_drawing_normal_by_default(self):
        """Day-time EV charging does NOT trip protection unless
        battery_hold_solar_ev is on (opt-in)."""
        d = decide_battery(_battery_view(
            charging_state="solar_charging_active",
            ev_charging=True,
        ))
        assert d.intent is BatteryIntent.NORMAL

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
        ("dusk",            0.0, 92.0, ChargerIntent.IDLE),
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

def _ev_adapter():
    a = MagicMock()
    a.command_disable = AsyncMock()
    a.command_idle = AsyncMock()
    a.command_current = AsyncMock()
    a.command_max = AsyncMock()
    a.is_self_charging = MagicMock(return_value=False)
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
    """For each (mode, zone) combo, run decide → actuate and verify
    the right adapter method was called."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize("mode,solar_w,soc,is_night,expected_method", [
        # OFF: always command_disable
        ("off",            5000.0, 50.0, False, "command_disable"),
        ("off",            5000.0, 50.0, True,  "command_disable"),
        ("off",               0.0, 95.0, False, "command_disable"),
        # ALWAYS_MAX: always command_max
        ("always_max",        0.0, 50.0, True,  "command_max"),
        ("always_max",    10000.0, 50.0, False, "command_max"),
        # SOLAR_ONLY: command_idle when no surplus; command_current when surplus
        ("solar_only",        0.0, 50.0, True,  "command_idle"),
        ("solar_only",       10000.0, 95.0, False, "command_current"),
        # MIN_PLUS_SOLAR: night top-up → command_current at min
        ("min_plus_solar",    0.0, 50.0, True,  "command_current"),
        # MIN_PLUS_SOLAR day Zone 1: idle
        ("min_plus_solar", 8000.0, 20.0, False, "command_idle"),
    ])
    async def test_decide_to_actuate_dispatch(
        self, mode, solar_w, soc, is_night, expected_method,
    ):
        view = _ev_view(
            mode=mode, solar_w=solar_w, soc=soc, is_night=is_night,
            target_kwh=10.0,
        )
        decision = decide(view)
        adapter = _ev_adapter()
        await actuate(decision, adapter, view.power)

        method = getattr(adapter, expected_method)
        assert method.await_count >= 1, (
            f"mode={mode} solar={solar_w} soc={soc} night={is_night}: "
            f"expected {expected_method}, got intent={decision.intent} "
            f"reason={decision.reason}"
        )


# ─────────────────────────────────────────────────────────────────
# Joint coherence — EV + battery decisions at the same operating
# point are non-contradictory (no "EV charging from solar" + "battery
# discharging to home" simultaneously when the EV is at handshake idle)
# ─────────────────────────────────────────────────────────────────

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
        assert ev.intent is ChargerIntent.DISABLE
        assert bat.intent is BatteryIntent.NORMAL

    def test_solar_only_sunny_zone_4_ev_charging_battery_normal(self):
        ev = decide(_ev_view(
            mode="solar_only", solar_w=10000.0, soc=95.0,
            is_night=False, battery_charge_w=0.0,
        ))
        bat = decide_battery(_battery_view(
            charging_state="solar_charging_active", ev_charging=True, soc=95.0,
        ))
        # EV charges from surplus; battery NOT in protection (day path,
        # no opt-in for solar hold).
        assert ev.intent is ChargerIntent.CHARGE_AT_AMPS
        assert bat.intent is BatteryIntent.NORMAL
