"""Unit tests for the night-charge threshold alignment (#282 follow-up).

Reported live on PROD 2026-05-29 evening while exercising the night
charging cycle: with Min=8.5 and daily=8.03 (remaining 0.47 kWh) the
dashboard label said "Night charging active" while the strategy text
said "idle, night target reached (8.0 kWh)" — same display/decision
disagreement class as #282, with two different thresholds:

  _determine_charging_strategy (coordinator.py:2200): ``< 0.5``
  _night_state_machine        (charging_control.py:280): ``<= 0.1``

Fix: align both on ``<= 0.1`` — Min is the GUARANTEED floor (#245
contract); deliver it exactly. At 6 A × 3-phase × 230 V min current,
going from 0.47 → 0.1 takes ~90 s, so no realistic flapping risk.

Drive-by fix: ``_canonical_strategy_from_legacy`` was missing the
``"night_grid"`` case and would raise ``ValueError`` on the first
real night-charge cycle with non-trivial remaining_need. Now maps to
``EVBudgetStrategy.MIN_PV``.
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    EVBudgetStrategy,
)


def _build_coord_min_for_strategy_test(daily_ev: float, daily_ev_target: float):
    """Minimal SEMCoordinator stub for exercising _determine_charging_strategy."""
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {
        "ev_chargers": [{
            "id": "ev_charger",
            "daily_ev_target": daily_ev_target,
            "ev_charging_mode": "auto",
        }],
        "ev_target_type": "kwh",
    }
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=True)
    coord.hass = MagicMock()
    coord.hass.states.is_state = MagicMock(return_value=False)
    coord._cycle_vehicle_soc = None
    coord._cycle_forecast = MagicMock(available=False)
    coord._forecast_tracker = MagicMock(dampening_factor=1.0)
    coord._tariff_provider = None
    coord._night_plan_per_charger = {}

    power = MagicMock()
    power.ev_connected = True
    power.solar_power = 0  # night
    power.battery_soc = 50
    power.battery_charge_power = 0
    power.battery_discharge_power = 0
    power.home_consumption_power = 0

    energy = MagicMock()
    energy.daily_ev = daily_ev

    return coord, power, energy


# ──────────────────────────────────────────────────────────────────────
# Threshold alignment — the smoking-gun PROD repro
# ──────────────────────────────────────────────────────────────────────

class TestNightThreshold:
    def test_remaining_above_strict_threshold_returns_night_grid(self):
        """The PROD repro: Min=8.5, daily=8.03 → remaining=0.47 → strategy
        MUST be ``night_grid`` (not ``idle``). Both 0.47 > 0.1 (strict
        threshold) and 0.47 < 0.5 (pre-fix sloppy threshold) — these
        bracket the bug regime."""
        coord, power, energy = _build_coord_min_for_strategy_test(
            daily_ev=8.03, daily_ev_target=8.5,
        )
        primary_cfg = coord.config["ev_chargers"][0]
        strategy, reason = coord._determine_charging_strategy(
            power, energy, primary_cfg,
        )
        assert strategy == "night_grid", (
            f"With remaining=0.47 kWh, strategy must keep charging "
            f"toward Min. Got {strategy!r} (reason: {reason!r}). "
            f"Pre-fix this was 'idle' because of the 0.5 threshold; "
            f"now 0.1 means we deliver to Min exactly."
        )

    def test_remaining_at_strict_threshold_returns_idle(self):
        """At exactly remaining=0.1 (the new alignment), strategy returns
        idle. This pins the new threshold so a future refactor can't drift
        it back to 0.5 without the test failing."""
        coord, power, energy = _build_coord_min_for_strategy_test(
            daily_ev=8.4, daily_ev_target=8.5,
        )
        # remaining = 0.5 - 0.4 = 0.1, the strict boundary
        primary_cfg = coord.config["ev_chargers"][0]
        strategy, reason = coord._determine_charging_strategy(
            power, energy, primary_cfg,
        )
        assert strategy == "idle"
        assert "target reached" in reason

    def test_remaining_below_strict_threshold_returns_idle(self):
        """Below 0.1 — clearly done."""
        coord, power, energy = _build_coord_min_for_strategy_test(
            daily_ev=8.45, daily_ev_target=8.5,
        )
        primary_cfg = coord.config["ev_chargers"][0]
        strategy, _ = coord._determine_charging_strategy(
            power, energy, primary_cfg,
        )
        assert strategy == "idle"


# ──────────────────────────────────────────────────────────────────────
# Canonical mapper — night_grid case must NOT crash
# ──────────────────────────────────────────────────────────────────────

class TestCanonicalMapperNightGrid:
    def test_night_grid_maps_to_min_pv(self):
        """``night_grid`` is the legacy strategy name for "deliver Min from
        grid at night." Canonical MIN_PV has the same semantic
        (``max(min_power_floor, surplus + redirect)``) — at night surplus
        is ~0 so net_w = floor. Mapping was missing pre-fix and would
        raise ValueError on every cycle of a real night charge."""
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        result = coord._canonical_strategy_from_legacy(
            "night_grid", "night mode, remaining=0.5kWh",
        )
        assert result == EVBudgetStrategy.MIN_PV

    def test_canonical_mapper_does_not_crash_on_night_grid(self):
        """The defining property: any reason string with night_grid as
        strategy must produce a valid EVBudgetStrategy, not raise."""
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        # Pre-fix this raised ValueError("unknown legacy strategy ...")
        result = coord._canonical_strategy_from_legacy("night_grid", "")
        assert result in (
            EVBudgetStrategy.IDLE, EVBudgetStrategy.SELF_CONSUMPTION,
            EVBudgetStrategy.SOLAR_ONLY, EVBudgetStrategy.BATTERY_ASSIST,
            EVBudgetStrategy.MIN_PV, EVBudgetStrategy.NOW,
        )
