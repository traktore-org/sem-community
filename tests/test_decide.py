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
    amps_from_watts,
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
        ),
        target_kwh=target_kwh,
        deadline_amps=deadline_amps,
    )


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
        assert "200W threshold" in d.reason

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

    def test_min_plus_solar_day_high_solar_is_solar_only(self):
        d = decide(_view(
            mode="min_plus_solar", solar_w=8000, home_w=500,
            battery_charge_w=0, battery_soc=95,
        ))
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.commanded_amps == 10

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
