"""Regression tests for #346 — solar_only mode must not charge at night.

PROD incident 2026-05-31 22:07 → 00:48: a KEBA charger configured with
``charge_mode = solar_only`` drew ~1.5 kW from the home battery + grid
overnight despite solar being 0 W. ``sensor.sem_charging_state``
correctly reported "Night charging disabled" the whole time, but the
EV charged anyway.

Root cause: ``_determine_charging_strategy`` returned ``"night_grid"``
unconditionally when ``is_night_mode()`` was True, regardless of the
per-charger ``charge_mode``. The named-mode dispatch (``mode ==
"solar_only"`` etc.) only ran in the day branch. The legacy mapper
then converted ``"night_grid"`` → ``EVBudgetStrategy.MIN_PV`` (≈1380 W
floor). With the state machine in NIGHT_DISABLED in parallel, the
actuator's terminal branch couldn't kill the self-resumed KEBA
session — same disagreement-class bug #282 was supposed to retire.

Fix: gate the night branch on ``MODE_NIGHT_ALLOWED`` first. Also
extend the #315 self-resume guard from {"disabled"} to
{"disabled", "idle"} so future strategy bugs land safely.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.consts.states import (
    ChargingState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


def _coord(charge_mode="solar_only", is_night=True):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        c = SEMCoordinator.__new__(SEMCoordinator)
    charger = {
        "id": "keba", "ev_min_current": 6,
        "ev_night_initial_current": 10, "charge_mode": charge_mode,
    }
    c.config = {
        "ev_chargers": [charger],
        "ev_max_current": 32,
        "target_peak_limit": 6.0,
        "ev_ramp_rate_amps": 2,
        "ev_stall_cooldown": 120,
        "battery_capacity_kwh": 15,
    }
    c._load_manager = None
    c.time_manager = MagicMock()
    c.time_manager.is_night_mode = MagicMock(return_value=is_night)
    c.time_manager.get_night_end_time = MagicMock(return_value="07:00")
    c.hass = MagicMock()
    c.hass.states.is_state = MagicMock(return_value=False)
    c._tariff_provider = MagicMock()
    c._cycle_vehicle_soc = None
    c._cycle_forecast = MagicMock(available=False)
    c._forecast_reader = MagicMock()
    c._forecast_reader.read_forecast = MagicMock(return_value=MagicMock(available=False))
    c._forecast_tracker = MagicMock(dampening_factor=1.0)
    c._state_machine = MagicMock()
    c._state_machine.current_state = ChargingState.SOLAR_IDLE
    c._ev_device = None
    return c, charger


def _power_night():
    """PROD snapshot 2026-05-31 22:07: solar zero, battery discharging,
    home consuming, EV connected and SEM thinks it should be idle."""
    return PowerReadings(
        solar_power=0.0,
        grid_power=-353.0,
        battery_power=-4474.0,
        home_consumption_power=1045.0,
        ev_power=0.0,
        ev_connected=True,
        ev_charging=False,
    )


class TestStrategyHonorsModeAtNight:
    """``_determine_charging_strategy`` must consult the per-charger
    ``charge_mode`` before defaulting to ``night_grid``."""

    def test_solar_only_at_night_returns_idle_not_night_grid(self):
        coord, cfg = _coord(charge_mode="solar_only")
        strategy, reason = coord._determine_charging_strategy(
            _power_night(), MagicMock(daily_ev=0.0), cfg,
        )
        assert strategy == "idle", (
            f"solar_only at night must NOT return night_grid (got "
            f"{strategy!r} / {reason!r}). This is the #346 PROD bug "
            f"that caused 4 kWh of overnight grid charging."
        )
        assert "solar_only" in reason

    def test_off_mode_at_night_returns_disabled(self):
        coord, cfg = _coord(charge_mode="off")
        strategy, _ = coord._determine_charging_strategy(
            _power_night(), MagicMock(daily_ev=0.0), cfg,
        )
        # off mode keeps the explicit ``disabled`` strategy so the
        # actuator's #315 terminal branch can self-resume-guard.
        assert strategy == "disabled"

    @pytest.mark.parametrize(
        "mode", ["min_plus_solar", "always_max", "solar_plus_cheap"],
    )
    def test_night_allowed_modes_still_return_night_grid(self, mode):
        """Modes in ``MODE_NIGHT_ALLOWED`` must keep the legacy
        ``night_grid`` behaviour — the fix only narrows, doesn't
        change min_plus_solar / always_max / solar_plus_cheap."""
        coord, cfg = _coord(charge_mode=mode)
        # solar_plus_cheap also needs a tariff stub
        coord._tariff_provider.get_price_level = MagicMock(return_value=None)
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=[])
        coord._night_plan_per_charger = {}
        strategy, _ = coord._determine_charging_strategy(
            _power_night(), MagicMock(daily_ev=0.0), cfg,
        )
        # In all three the legacy path produces "night_grid"
        # when remaining_need > 0.1 kWh. Mock daily_ev=0 so
        # remaining_need is positive.
        assert strategy == "night_grid", (
            f"mode={mode} (in MODE_NIGHT_ALLOWED) must still produce "
            f"night_grid at night (got {strategy!r})"
        )


class TestStrategyDayBehaviourUnchanged:
    """The fix only gates the NIGHT branch — day behaviour must be
    pixel-identical to today for all modes."""

    def test_solar_only_during_day_unchanged(self):
        coord, cfg = _coord(charge_mode="solar_only", is_night=False)
        strategy, _ = coord._determine_charging_strategy(
            PowerReadings(
                solar_power=3000.0, battery_soc=50.0,
                ev_connected=True,
            ),
            MagicMock(daily_ev=0.0), cfg,
        )
        # solar_only day → self_consumption strategy (returns "solar_only")
        assert strategy == "solar_only"
