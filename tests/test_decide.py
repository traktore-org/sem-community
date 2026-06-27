"""Tests for the pure decide(view) → ChargerDecision module
(Step 3 of arch/multi-charger-primary).

Each mode has its own test class. Tests pin:

1. **Intent correctness** — the right ChargerIntent for each
   (mode, environment) combination
2. **Commanded amps correctness** — for CHARGE_AT_AMPS,
   the right number of amps
3. **No grid for solar_only** — the #346 invariant, pinned for
   day and night
4. **Reason carries enough detail** — non-empty, mentions key
   values
5. **Purity** — calling decide twice with the same view
   returns equal decisions
"""
import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    MODE_STRATEGIES,
    _idle_bridgeable,
    amps_from_watts,
    battery_assist_budget_w,
    decide,
    self_consumption_surplus_w,
    soc_zone,
)


def _view(
    mode: str = "solar_only",
    *,
    connected: bool = True,
    charging: bool = False,
    power_w: float = 0.0,
    solar_w: float = 5000.0,
    home_w: float = 500.0,
    battery_charge_w: float = 0.0,
    battery_discharge_w: float = 0.0,
    battery_soc: float = 75.0,
    is_night: bool = False,
    tariff_level: str | None = None,
    target_kwh: float | None = None,
    deadline_amps: int = 0,
    night_deliverable_kwh: float = float("inf"),
    soc_ceiling_reached: bool = False,
    battery_assist_max_power_w: float = 4500.0,
    battery_assist_min_surplus_w: float = 1200.0,
    config: dict | None = None,
) -> ChargerView:
    return ChargerView(
        power=ChargerPower(
            charger_id="keba", power_w=power_w,
            connected=connected, charging=charging,
        ),
        energy=ChargerEnergy(charger_id="keba"),
        mode=mode,
        config=config or {"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                          "ev_max_current": 32},
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w,
            battery_charge_w=battery_charge_w,
            battery_discharge_w=battery_discharge_w,
            battery_soc=battery_soc,
            is_night=is_night, tariff_level=tariff_level,
            battery_assist_max_power_w=battery_assist_max_power_w,
            battery_assist_min_surplus_w=battery_assist_min_surplus_w,
        ),
        target_kwh=target_kwh,
        deadline_amps=deadline_amps,
        night_deliverable_kwh=night_deliverable_kwh,
        soc_ceiling_reached=soc_ceiling_reached,
    )


class TestMaxOutTillSelfConsumption545:
    """#545 — at high SOC, offer the FULL battery-assist potential so the
    battery empties into the car down to the buffer (self-consumption
    floor), not just enough to reach the EV minimum. ("Max out till
    self-consumption", user 2026-06-26.)
    """

    def test_zone4_offers_full_potential(self):
        # SOC 95 (Zone 4), surplus 4500 >= gate → surplus + FULL potential.
        v = _view(battery_soc=95, solar_w=5000, home_w=500,
                  battery_assist_max_power_w=4500,
                  battery_assist_min_surplus_w=1200)
        # surplus = 4500 (>= auto_start, no battery-charge subtract);
        # potential at >= auto_start = full 4500.
        assert battery_assist_budget_w(v) == pytest.approx(9000)

    def test_zone3_also_offers_full_ramped_potential(self):
        # SOC 80 (Zone 3) — used to cap at the EV min; now offers the
        # ramped potential (no min-gap cap).
        v = _view(battery_soc=80, solar_w=5000, home_w=500,
                  battery_assist_max_power_w=4500,
                  battery_assist_min_surplus_w=1200)
        # surplus 4500; potential at 80% = 4500*(0.5+0.5*0.5)=3375.
        assert battery_assist_budget_w(v) == pytest.approx(7875)

    def test_solar_gate_still_protects(self):
        # Zone 4 but surplus below the gate → surplus only, no battery drain.
        v = _view(battery_soc=95, solar_w=900, home_w=500,
                  battery_assist_min_surplus_w=1200)
        # surplus = 400 < 1200 gate.
        assert battery_assist_budget_w(v) == pytest.approx(400)

    def test_below_buffer_no_assist(self):
        # SOC 65 (< buffer 70) → zone < 3 → surplus only (self-consumption
        # floor protects the battery).
        v = _view(battery_soc=65, solar_w=5000, home_w=500)
        assert battery_assist_budget_w(v) == pytest.approx(4500)


class TestMaxSocCeiling548:
    """#548 — the max-SOC ceiling stops charging in EVERY mode.

    Regression: the ceiling (`soc_limit_active`) only reached the retired
    ChargingStateMachine, which the per-charger decision clobbered, so the
    EV charged past the configured max SOC during solar surplus. ``decide()``
    now honours ``view.soc_ceiling_reached`` before mode dispatch.
    """

    @pytest.mark.parametrize("mode", [
        "solar_only", "min_plus_solar", "always_max", "solar_plus_cheap",
    ])
    def test_ceiling_reached_idles_every_mode(self, mode):
        # Plenty of surplus (would otherwise charge), but max SOC reached.
        d = decide(_view(mode=mode, solar_w=8000, home_w=500,
                         battery_soc=80, soc_ceiling_reached=True))
        assert d.intent is ChargerIntent.IDLE, (
            f"{mode}: must stop at max SOC, got {d.intent}"
        )
        assert "max SOC" in d.reason or "target reached" in d.reason.lower()

    def test_below_ceiling_still_charges(self):
        # Same surplus, ceiling NOT reached → charges as normal.
        d = decide(_view(mode="always_max", solar_w=8000, home_w=500,
                         soc_ceiling_reached=False))
        assert d.intent is not ChargerIntent.IDLE

    def test_ceiling_ignored_when_disconnected(self):
        # A stale ceiling must not mask the "disconnected" reason.
        d = decide(_view(mode="solar_only", connected=False,
                         soc_ceiling_reached=True))
        assert d.intent is ChargerIntent.IDLE
        assert "disconnect" in d.reason.lower()

    def test_default_view_does_not_block(self):
        # Default soc_ceiling_reached=False — kWh users (effectively
        # unlimited max) keep surplus-charging freely.
        d = decide(_view(mode="solar_only", solar_w=8000, home_w=500))
        assert d.intent is not ChargerIntent.IDLE


class TestHelpers:
    def test_soc_zone_boundaries(self):
        assert soc_zone(95, 90, 70, 30) == 4
        assert soc_zone(90, 90, 70, 30) == 4
        assert soc_zone(89.9, 90, 70, 30) == 3
        assert soc_zone(70, 90, 70, 30) == 3
        assert soc_zone(69.9, 90, 70, 30) == 2
        assert soc_zone(30, 90, 70, 30) == 2
        assert soc_zone(29.9, 90, 70, 30) == 1

    def test_self_consumption_surplus_below_auto_start(self):
        """Below auto_start_soc the battery charges first."""
        v = _view(solar_w=8000, home_w=500, battery_charge_w=5000,
                  battery_soc=75)  # Zone 3 < 90
        assert self_consumption_surplus_w(v) == pytest.approx(2500, abs=1)

    def test_self_consumption_surplus_zone_4_redirects(self):
        """At/above auto_start_soc the battery does not get priority."""
        v = _view(solar_w=8000, home_w=500, battery_charge_w=0,
                  battery_soc=95)
        assert self_consumption_surplus_w(v) == pytest.approx(7500, abs=1)

    def test_amps_from_watts_rounds_down(self):
        assert amps_from_watts(4140, 3, 230) == 6
        assert amps_from_watts(5000, 3, 230) == 7   # 7.246
        assert amps_from_watts(0, 3, 230) == 0


class TestOffMode:
    """`off` always → DISABLE. Mirrors #315 fix at the strategy level."""

    def test_off_disconnected(self):
        d = decide(_view(mode="off", connected=False))
        assert d.intent is ChargerIntent.DISABLE

    def test_off_connected_no_solar(self):
        d = decide(_view(mode="off", solar_w=0))
        assert d.intent is ChargerIntent.DISABLE

    def test_off_connected_high_solar(self):
        d = decide(_view(mode="off", solar_w=10000))
        assert d.intent is ChargerIntent.DISABLE

    def test_off_at_night(self):
        d = decide(_view(mode="off", is_night=True))
        assert d.intent is ChargerIntent.DISABLE


class TestAlwaysMaxMode:
    def test_always_max_connected(self):
        d = decide(_view(mode="always_max"))
        assert d.intent is ChargerIntent.CHARGE_MAX

    def test_always_max_disconnected_is_idle(self):
        d = decide(_view(mode="always_max", connected=False))
        assert d.intent is ChargerIntent.IDLE

    def test_always_max_at_night(self):
        d = decide(_view(mode="always_max", is_night=True, solar_w=0))
        assert d.intent is ChargerIntent.CHARGE_MAX


class TestSolarOnlyMode:
    """The #346 invariant — solar_only must NEVER produce grid import.

    Day: charge when surplus >= min. Night/cloudy: idle.
    """

    def test_solar_only_at_night_is_idle(self):
        """#346 root cause: pre-fix this returned night_grid."""
        d = decide(_view(mode="solar_only", is_night=True, solar_w=0))
        assert d.intent is ChargerIntent.IDLE

    def test_solar_only_disconnected_is_idle(self):
        d = decide(_view(mode="solar_only", connected=False))
        assert d.intent is ChargerIntent.IDLE

    def test_solar_only_low_solar_is_idle(self):
        d = decide(_view(mode="solar_only", solar_w=100))
        assert d.intent is ChargerIntent.IDLE
        # Default min_solar_w now matches the seeded DEFAULT_MIN_SOLAR_POWER
        # (1000 W) — was 200 W before the keyless-fallback fix (#536).
        assert "1000W threshold" in d.reason

    def test_solar_only_high_solar_charges(self):
        """Solar = 8 kW, home = 500 W, no battery charge → surplus
        7500 W. 7500 / 690 = 10A."""
        d = decide(_view(
            mode="solar_only", solar_w=8000, home_w=500,
            battery_charge_w=0, battery_soc=95,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 10
        assert d.budget_w == pytest.approx(7500, abs=1)

    def test_solar_only_battery_charging_eats_surplus(self):
        """Solar = 5 kW, home = 500 W, battery_charge = 4 kW (Zone 3)
        → EV surplus = 5000 - 500 - 4000 = 500 W < min (4140 W) → idle.
        The #353 PROD scenario in miniature."""
        d = decide(_view(
            mode="solar_only", solar_w=5000, home_w=500,
            battery_charge_w=4000, battery_soc=75,
        ))
        assert d.intent is ChargerIntent.IDLE
        assert "min=4140" in d.reason

    def test_solar_only_zone_4_redirects_to_ev(self):
        """At SOC >= auto_start, battery doesn't get priority,
        so even when sensors report battery_charge_w > 0 (transient),
        the surplus calc ignores it."""
        d = decide(_view(
            mode="solar_only", solar_w=8000, home_w=500,
            battery_charge_w=0, battery_soc=95,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        # Full 7500 W reaches the EV
        assert d.commanded_amps == 10


class TestMinPlusSolarMode:
    """Day path = same as solar_only. Night path = top-up to Min."""

    def test_min_plus_solar_day_zone4_adds_full_battery_assist(self):
        # #545 — Zone 4 (SOC 95) now offers surplus + FULL assist potential,
        # not surplus only. surplus 7500 + potential 4500 = 12000W → 17A
        # (was 10A pre-#545, surplus-only).
        d = decide(_view(
            mode="min_plus_solar", solar_w=8000, home_w=500,
            battery_charge_w=0, battery_soc=95,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 17

    def test_min_plus_solar_night_below_target_charges_at_min(self):
        d = decide(_view(
            mode="min_plus_solar", is_night=True, solar_w=0,
            target_kwh=5.0,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6   # min_amps default

    def test_min_plus_solar_night_target_reached_is_idle(self):
        d = decide(_view(
            mode="min_plus_solar", is_night=True, target_kwh=0.05,
        ))
        assert d.intent is ChargerIntent.IDLE
        assert "target reached" in d.reason

    def test_min_plus_solar_night_deadline_floor(self):
        """#246 deadline: planner pre-computed required current → use it."""
        d = decide(_view(
            mode="min_plus_solar", is_night=True, target_kwh=10.0,
            deadline_amps=14,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 14

    def test_min_plus_solar_disconnected_is_idle(self):
        d = decide(_view(mode="min_plus_solar", connected=False, is_night=True))
        assert d.intent is ChargerIntent.IDLE


class TestMinPlusSolarZoneAssist:
    """min_plus_solar day-path uses Zone-aware battery assist
    (Zone 3/4 = surplus + capped SOC-based assist potential (#501);
    Zone 2 = pure solar; Zone 1 = idle). The min-current floor is
    need-gated: it engages only when the remaining Min exceeds what
    tonight's window can deliver.
    """

    def test_zone_4_no_battery_assist_without_solar(self):
        """Solar gate: SOC = 95 (Zone 4) but solar = 0 (evening) →
        the battery is NOT drained into the EV. Below the 1200 W solar
        surplus gate the day path collapses to self-consumption-only
        and idles. (Pre-gate this charged at 6 A from the battery — the
        overnight-drain bug.)"""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=0, home_w=500, battery_discharge_w=4500,
            battery_soc=95,
        ))
        assert d.intent is ChargerIntent.IDLE
        assert "Zone 4" in d.reason

    def test_zone_4_battery_assist_with_solar_surplus(self):
        """Solar surplus above the gate (2500 W) → battery assist still
        tops up to the EV minimum (the intended supplement-solar case)."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=3000, home_w=500, battery_soc=95,
        ))
        # surplus 2500 ≥ 1200 gate → assist tops up to ≥6 A
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps >= 6
        assert "Zone 4" in d.reason

    def test_zone_4_gate_zero_allows_overnight_battery_assist(self):
        """Gate = 0 → user opt-in: battery supports the EV even with no
        solar (surplus 0 clears a 0 threshold)."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=0, home_w=500, battery_discharge_w=4500,
            battery_soc=95, battery_assist_min_surplus_w=0.0,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6   # full 4500 W assist / 690 = 6 A
        assert "Zone 4" in d.reason

    def test_zone_4_default_gate_blocks_low_surplus(self):
        """DEFAULT gate (1200 W), Zone 4, daytime, surplus 300 W (< gate) →
        no battery assist → idle. Pins the default-gate blocking path
        (the other gate tests zero the gate to isolate other behavior)."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=800, home_w=500, battery_soc=95,
        ))
        # surplus = 300 < 1200 default gate → assist blocked → below 6A → idle
        assert d.intent is ChargerIntent.IDLE
        assert "Zone 4" in d.reason

    def test_zone_3_battery_assist_when_battery_discharging(self):
        """SOC = 75 (Zone 3), some solar + battery → EV charges."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=3000, home_w=500, battery_discharge_w=2000,
            battery_soc=75,
        ))
        # surplus = 3000 - 500 - battery_charge(0) = 2500
        # + battery_dis 2000 = 4500 → 6A
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "Zone 3" in d.reason

    def test_zone_2_falls_back_to_solar_only(self):
        """SOC = 50 (Zone 2), solar high → pure solar surplus."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=8000, home_w=500, battery_soc=50,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        # Zone 2 → solar_only path; surplus = 7500 → 10A
        assert d.commanded_amps == 10

    def test_zone_1_idle(self):
        """SOC = 20 (Zone 1), battery priority — EV blocked."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=8000, home_w=500, battery_soc=20,
        ))
        assert d.intent is ChargerIntent.IDLE
        assert "Zone 1" in d.reason


class TestMinPlusSolarSelfMax:
    """#501 — daytime min_plus_solar is self-consumption-maximizing.

    The Zone 3/4 min-current floor is need-gated (engages only when
    the night window can't deliver the remaining Min) and the assist
    budget is the capped SOC-based POTENTIAL — never the battery's
    measured total discharge (which included the house's share and
    ratcheted the commanded current on home-load spikes).
    """

    def test_cloudy_zone3_no_floor_idles(self):
        """Cloudy day, Zone 3, Min comfortably covered by tonight's
        window → NO forced 6 A; the charger idles (pre-#501 it pulled
        ≥4.1 kW from battery+grid all afternoon)."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=300, home_w=800, battery_soc=75,
            target_kwh=7.0, night_deliverable_kwh=26.0,
        ))
        # budget = surplus(0) + assist_potential(75) = 0.625*4500 = 2812 W < 6 A
        assert d.intent is ChargerIntent.IDLE
        assert "night window" in d.reason

    def test_floor_engages_when_night_cannot_cover(self):
        """Remaining Min exceeds the night window's deliverable —
        the commit-then-measure floor (#439/ADR 0010) engages."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=300, home_w=800, battery_soc=75,
            target_kwh=30.0, night_deliverable_kwh=12.0,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6
        assert "floor engaged" in d.reason

    def test_no_floor_after_min_met(self):
        """Min already reached today → never force the floor, even if
        night_deliverable is tiny ('Up to Full never forces grid')."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=300, home_w=800, battery_soc=75,
            target_kwh=0.05, night_deliverable_kwh=0.0,
        ))
        assert d.intent is ChargerIntent.IDLE

    def test_home_load_spike_does_not_ratchet_amps(self):
        """Regression for the misattribution ratchet: the battery
        covering a HOME load spike must not inflate the EV budget.
        Same solar/SOC, discharge jumps 0 → 6 kW (house turned on the
        oven) → commanded amps unchanged."""
        base = decide(_view(
            mode="min_plus_solar",
            solar_w=6000, home_w=500, battery_soc=80,
            battery_discharge_w=0.0,
        ))
        spike = decide(_view(
            mode="min_plus_solar",
            solar_w=6000, home_w=500, battery_soc=80,
            battery_discharge_w=6000.0,
        ))
        assert base.intent is ChargerIntent.CHARGE_AT_AMPS
        assert spike.commanded_amps == base.commanded_amps

    def test_assist_capped_at_configured_max(self):
        """Zone 4: the assist budget is the configured
        battery_assist_max_power, not the battery's nameplate. Gate set
        to 0 to isolate the cap from the solar gate."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=0, home_w=500, battery_soc=95,
            battery_assist_max_power_w=3000.0,
            battery_assist_min_surplus_w=0.0,
            target_kwh=30.0, night_deliverable_kwh=12.0,
        ))
        # potential = 3000 W → 4 A, floor raises to 6 A (floor engaged);
        # budget itself must reflect the cap
        assert d.budget_w == pytest.approx(3000.0, abs=1)

    def test_zone4_assist_potential_charges_without_flowing_discharge(self):
        """#439 stays fixed: battery NOT yet discharging, Zone 4 →
        the POTENTIAL still funds the budget and charging starts
        (no chicken-and-egg gate on measured discharge). Gate set to 0
        to isolate #439 from the solar gate."""
        d = decide(_view(
            mode="min_plus_solar",
            solar_w=0, home_w=500, battery_soc=95,
            battery_discharge_w=0.0,
            battery_assist_min_surplus_w=0.0,
        ))
        # potential = 4500 W → 6 A
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6


class TestSolarPlusCheapMode:
    """Daytime: solar_only behaviour, paused during expensive.
    Night: cheap-window top-up (defers to night planner)."""

    def test_solar_plus_cheap_day_normal_tariff_solar_only(self):
        d = decide(_view(
            mode="solar_plus_cheap", solar_w=8000, home_w=500,
            battery_soc=95, tariff_level="normal",
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS

    def test_solar_plus_cheap_day_expensive_pauses_grid(self):
        """During expensive windows, falls through to pure
        self-consumption — the #247 daytime pause."""
        # Solar high enough to still charge from surplus
        d = decide(_view(
            mode="solar_plus_cheap", solar_w=8000, home_w=500,
            battery_soc=95, tariff_level="expensive",
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS  # still charging from solar
        assert "tariff=expensive" in d.reason

        # Low solar + expensive → idle (no grid pull)
        d2 = decide(_view(
            mode="solar_plus_cheap", solar_w=100, home_w=500,
            tariff_level="expensive",
        ))
        assert d2.intent is ChargerIntent.IDLE

    def test_solar_plus_cheap_night_tariff_wait(self):
        """Night planner says wait for cheap → idle even with target remaining."""
        d = decide(_view(
            mode="solar_plus_cheap", is_night=True, solar_w=0,
            target_kwh=10.0,
            config={"ev_min_current": 6, "_tariff_wait": True},
        ))
        assert d.intent is ChargerIntent.IDLE
        assert "waiting for cheaper" in d.reason

    def test_solar_plus_cheap_night_in_cheap_window_charges(self):
        d = decide(_view(
            mode="solar_plus_cheap", is_night=True, solar_w=0,
            target_kwh=10.0,
            config={"ev_min_current": 6, "_tariff_wait": False},
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 6


class TestUnknownMode:
    """Unknown mode → fail safe to OFF (loud)."""

    def test_unknown_mode_falls_back_to_off(self):
        d = decide(_view(mode="some_typo_mode"))
        assert d.intent is ChargerIntent.DISABLE


class TestPurity:
    """Decide is pure — same view twice returns equal decisions."""

    def test_same_view_twice_same_decision(self):
        view = _view(mode="solar_only", solar_w=8000, home_w=500, battery_soc=95)
        d1 = decide(view)
        d2 = decide(view)
        assert d1 == d2

    def test_no_mutation_of_view(self):
        view = _view(mode="solar_only", solar_w=8000)
        original_solar = view.fleet.solar_w
        decide(view)
        assert view.fleet.solar_w == original_solar


class TestModeRegistryComplete:
    """Every charge mode in EV_CHARGE_MODES has a strategy."""

    def test_all_five_modes_registered(self):
        from custom_components.solar_energy_management.consts.ev_charge_modes import (
            EV_CHARGE_MODES,
        )
        for mode in EV_CHARGE_MODES:
            assert mode in MODE_STRATEGIES, f"mode {mode!r} missing strategy"


@pytest.mark.unit
class TestIdleBridgeable:
    """decide() is the SINGLE source of truth (#461) for whether an IDLE is a
    TRANSIENT dip (bridge it) or a STRUCTURAL stop (don't grid-hold). The
    stability bridge reads ``decision.bridgeable`` instead of re-deriving
    solar/surplus/SoC/tariff. These pin the classification.

    (_view defaults: buffer_soc=70, min_solar_w=1000, min charge at 6A/3ph =
    6*3*230 = 4140 W.)
    """

    def test_sun_gone_is_structural(self):
        ok, why = _idle_bridgeable(_view(solar_w=500))  # < 1000 min_solar
        assert ok is False
        assert "sun gone" in why

    def test_not_cheap_tariff_is_structural(self):
        ok, why = _idle_bridgeable(_view(solar_w=5000, tariff_level="normal"))
        assert ok is False
        assert "not-cheap tariff" in why

    def test_no_assist_no_surplus_is_structural(self):
        # solar 3000, home 2500 → real surplus 500 < 4140 min charge; battery
        # 33% < buffer 70% → can't assist → structural.
        ok, why = _idle_bridgeable(_view(
            solar_w=3000, home_w=2500, battery_soc=33, tariff_level="cheap"))
        assert ok is False
        assert "no battery assist" in why

    def test_real_surplus_present_is_transient(self):
        # Big real surplus (9000 − 300 = 8700 ≥ 4140) → worth bridging.
        ok, why = _idle_bridgeable(_view(
            solar_w=9000, home_w=300, battery_soc=33, tariff_level="cheap"))
        assert ok is True
        assert why == ""

    def test_battery_can_assist_is_transient(self):
        # Thin surplus (500 < 4140) BUT battery 80% ≥ buffer 70% → assist
        # available → bridgeable.
        ok, why = _idle_bridgeable(_view(
            solar_w=3000, home_w=2500, battery_soc=80, tariff_level="cheap"))
        assert ok is True

    def test_cheap_tariff_does_not_trip_not_cheap(self):
        ok, _ = _idle_bridgeable(_view(
            solar_w=9000, home_w=300, battery_soc=80, tariff_level="cheap"))
        assert ok is True

    def test_decide_stamps_structural_idle_with_reason(self):
        # Integration: a solar_only idle in deep darkness comes back IDLE,
        # bridgeable=False, with the structural cause appended to the reason.
        d = decide(_view(mode="solar_only", solar_w=500))
        assert d.intent is ChargerIntent.IDLE
        assert d.bridgeable is False
        assert "[structural:" in d.reason

    def test_decide_charge_decision_defaults_bridgeable_true(self):
        d = decide(_view(mode="solar_only", solar_w=9000, home_w=300,
                         battery_soc=95))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.bridgeable is True  # default, irrelevant to CHARGE

    def test_decide_soc_ceiling_idle_is_structural(self):
        d = decide(_view(mode="min_plus_solar", soc_ceiling_reached=True,
                         solar_w=8000, home_w=500))
        assert d.intent is ChargerIntent.IDLE
        assert d.bridgeable is False
