"""Tests for SOC zone strategy: _determine_charging_strategy() and _calculate_solar_ev_budget().

Codified from real-world scenario on 2026-03-22 where battery drained to 20% SOC.
Investigation confirmed zones held correctly: battery assist stopped at 70% (Zone 2 boundary),
remaining drain was evening home consumption.

Real-world data:
  Solar: 36.65 kWh, Home: 29.98 kWh, EV: 15.52 kWh
  Battery charge: 13.55 kWh, discharge: 9.54 kWh → SOC ended at 20%
  PROD config: battery_priority_soc=90, buffer/auto_start/floor at defaults (70/90/60)
"""
import pytest
from unittest.mock import MagicMock, patch
from dataclasses import dataclass

from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator.charging_control import ChargingContext


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_power(
    solar_power=3000.0,
    battery_soc=50.0,
    ev_connected=True,
    battery_discharge_power=0.0,
    **kwargs,
) -> PowerReadings:
    """Create PowerReadings with sensible defaults for zone strategy tests."""
    p = PowerReadings(
        solar_power=solar_power,
        battery_soc=battery_soc,
        ev_connected=ev_connected,
        battery_discharge_power=battery_discharge_power,
        **kwargs,
    )
    return p


@dataclass
class _MockEnergy:
    """Minimal stand-in for energy data passed to _determine_charging_strategy."""
    daily_ev: float = 0.0


class _MockForecast:
    """Stand-in for forecast reader result."""
    def __init__(self, available=False, remaining=0.0):
        self.available = available
        self.forecast_remaining_today_kwh = remaining


def _build_coordinator(config_overrides=None, current_state=ChargingState.SOLAR_IDLE):
    """Build a minimal coordinator with only what _determine_charging_strategy needs."""
    from custom_components.solar_energy_management.coordinator import SEMCoordinator

    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)

    coord.config = {
        "daily_ev_target": 10,
        "ev_charging_mode": "pv",
        "battery_auto_start_soc": 90,
        "battery_buffer_soc": 70,
        "battery_priority_soc": 30,
        "battery_assist_floor_soc": 60,
        "battery_capacity_kwh": 15,
        "battery_assist_max_power": 4500,
    }
    if config_overrides:
        coord.config.update(config_overrides)

    # time_manager
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=False)

    # state machine
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = current_state

    # forecast reader (default: unavailable)
    coord._forecast_reader = MagicMock()
    coord._forecast_reader.read_forecast = MagicMock(
        return_value=_MockForecast(available=False)
    )
    coord._cycle_forecast = _MockForecast(available=False)
    coord._cycle_vehicle_soc = None

    # flow calculator (for _calculate_solar_ev_budget)
    coord._flow_calculator = MagicMock()
    coord._flow_calculator.calculate_ev_budget = MagicMock(return_value=2000)

    return coord


# ===========================================================================
# Tests for _determine_charging_strategy
# ===========================================================================


class TestDetermineChargingStrategy:
    """Zone transition tests."""

    # --- Zone transitions (tests 1-5) ---

    def test_zone4_full_assist(self):
        """Zone 4: SOC >= auto_start_soc (90%) → battery_assist."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "Zone 4" in reason

    def test_zone3_discharge_assist(self):
        """Zone 3: SOC 70-89% → battery_assist (no forecast)."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "Zone 3" in reason

    def test_zone3_good_forecast_solar_only(self):
        """Zone 3 with good forecast → solar_only (enough solar ahead)."""
        coord = _build_coordinator()
        # remaining_need = 10 - 0 = 10 kWh
        # needs estimated_surplus >= 10 * 1.5 = 15 kWh
        # surplus = forecast_remaining * 0.5, so forecast_remaining >= 30
        coord._forecast_reader.read_forecast.return_value = _MockForecast(
            available=True, remaining=35.0
        )
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert "forecast surplus" in reason

    def test_zone2_surplus_only(self):
        """Zone 2: SOC 30-69% → solar_only."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=50), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert "Zone 2" in reason

    def test_zone1_battery_priority(self):
        """Zone 1: SOC < 30% → idle (battery priority, EV blocked)."""
        coord = _build_coordinator()
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=20), _MockEnergy()
        )
        assert strategy == "idle"
        assert "Zone 1" in reason

    # --- Zone 2 hysteresis (tests 6-7) ---

    def test_hysteresis_stays_battery_assist_above_floor(self):
        """Already SOLAR_SUPER_CHARGING, SOC 65% >= floor 60% → stays battery_assist."""
        coord = _build_coordinator(current_state=ChargingState.SOLAR_SUPER_CHARGING)
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=65), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "hysteresis" in reason.lower()

    def test_hysteresis_drops_below_floor(self):
        """Already SOLAR_SUPER_CHARGING, SOC 55% < floor 60% → solar_only."""
        coord = _build_coordinator(current_state=ChargingState.SOLAR_SUPER_CHARGING)
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=55), _MockEnergy()
        )
        assert strategy == "solar_only"
        assert "Zone 2" in reason

    # --- Edge cases & mode overrides (tests 8-13) ---

    def test_ev_disconnected_returns_idle(self):
        """EV disconnected → idle regardless of SOC."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95, ev_connected=False), _MockEnergy()
        )
        assert strategy == "idle"

    def test_daily_target_reached_solar_continues(self):
        """Daily target reached during day → solar continues (free surplus)."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95, solar_power=3000), _MockEnergy(daily_ev=10.0)
        )
        # Solar keeps charging past target — target only limits night (grid) charging
        assert strategy == "battery_assist"

    def test_daily_target_reached_night_idle(self):
        """Daily target reached during night → idle (don't charge from grid)."""
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy(daily_ev=10.0)
        )
        assert strategy == "idle"

    def test_night_mode_returns_night_grid(self):
        """Night mode active → night_grid regardless of SOC."""
        coord = _build_coordinator()
        coord.time_manager.is_night_mode.return_value = True
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy()
        )
        assert strategy == "night_grid"

    def test_charging_mode_off_returns_idle(self):
        """Charging mode = 'off' → idle."""
        coord = _build_coordinator(config_overrides={"ev_charging_mode": "off"})
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=95), _MockEnergy()
        )
        assert strategy == "idle"

    def test_charging_mode_minpv_returns_min_pv(self):
        """Charging mode = 'minpv' → min_pv."""
        coord = _build_coordinator(config_overrides={"ev_charging_mode": "minpv"})
        strategy, _ = coord._determine_charging_strategy(
            _make_power(battery_soc=50), _MockEnergy()
        )
        assert strategy == "min_pv"

    def test_low_solar_returns_idle(self):
        """Solar < 200W → idle (not enough sun)."""
        coord = _build_coordinator()
        strategy, _ = coord._determine_charging_strategy(
            _make_power(solar_power=150, battery_soc=80), _MockEnergy()
        )
        assert strategy == "idle"
        assert "200W" in _

    # --- Real-world: PROD config (priority_soc=90, collapsed Zone 2) (tests 14-15) ---

    def test_prod_config_soc80_battery_assist(self):
        """PROD: priority_soc=90 → SOC 80% is Zone 3 (>= buffer 70%), battery_assist."""
        coord = _build_coordinator(config_overrides={"battery_priority_soc": 90})
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=80), _MockEnergy()
        )
        assert strategy == "battery_assist"
        assert "Zone 3" in reason

    def test_prod_config_soc65_idle(self):
        """PROD: priority_soc=90 → SOC 65% < buffer 70%, Zone 2 empty → falls to Zone 2 solar_only.

        With priority_soc=90, Zone 2 is [90%..70%) which is empty since 90 > 70.
        SOC 65% < buffer_soc 70% AND < priority_soc 90%, so it's Zone 1 → idle.
        """
        coord = _build_coordinator(config_overrides={"battery_priority_soc": 90})
        # SOC 65% < buffer_soc 70%, so Zone 3 check fails
        # SOC 65% < priority_soc 90%, so Zone 2 check also fails
        # Falls to Zone 1 → idle
        strategy, reason = coord._determine_charging_strategy(
            _make_power(battery_soc=65), _MockEnergy()
        )
        assert strategy == "idle"
        assert "Zone 1" in reason


# ===========================================================================
# Tests for _calculate_solar_ev_budget
# ===========================================================================


class TestCalculateSolarEvBudget:
    """Budget calculation by zone."""

    def _make_context(self):
        """Create a minimal ChargingContext."""
        return ChargingContext()

    # --- Budget by zone (tests 16-20) ---

    def test_super_charging_zone4_full_assist(self):
        """SOLAR_SUPER_CHARGING, SOC 95% (Zone 4) → base + full max_assist (4500W)."""
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 2000
        power = _make_power(battery_soc=95, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_SUPER_CHARGING, power, self._make_context()
        )

        assert budget == 2000 + 4500  # base + full Zone 4 assist

    def test_super_charging_zone3_proportional_ramp(self):
        """SOLAR_SUPER_CHARGING, SOC 80% (Zone 3) → base + proportional ramp.

        ratio = (80 - 70) / (90 - 70) = 0.5
        assist = 4500 * (0.5 + 0.5 * 0.5) = 4500 * 0.75 = 3375
        """
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 2000
        power = _make_power(battery_soc=80, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_SUPER_CHARGING, power, self._make_context()
        )

        assert budget == 2000 + 3375  # base + proportional assist

    def test_super_charging_below_floor_no_assist(self):
        """SOLAR_SUPER_CHARGING, SOC 55% (< floor_soc 60%) → base only, no assist."""
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 2000
        power = _make_power(battery_soc=55, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_SUPER_CHARGING, power, self._make_context()
        )

        assert budget == 2000  # base only

    def test_non_super_charging_no_assist(self):
        """SOLAR_CHARGING_ACTIVE (not super) → base only, no battery assist added."""
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 2000
        power = _make_power(battery_soc=95, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_CHARGING_ACTIVE, power, self._make_context()
        )

        assert budget == 2000  # base only — not in super charging state

    def test_super_charging_measured_discharge(self):
        """SOLAR_SUPER_CHARGING, battery discharging 2000W → base + measured value."""
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 1500
        power = _make_power(battery_soc=80, battery_discharge_power=2000)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_SUPER_CHARGING, power, self._make_context()
        )

        # Measured discharge (2000W) >= 100W threshold, so use it instead of estimate
        assert budget == 1500 + 2000

    # --- Additional edge cases ---

    def test_super_charging_zone3_bottom_boundary(self):
        """SOLAR_SUPER_CHARGING, SOC exactly at buffer_soc (70%) → minimum ramp.

        ratio = (70 - 70) / (90 - 70) = 0
        assist = 4500 * (0.5 + 0.5 * 0) = 4500 * 0.5 = 2250
        """
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 1000
        power = _make_power(battery_soc=70, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_SUPER_CHARGING, power, self._make_context()
        )

        assert budget == 1000 + 2250

    def test_super_charging_zone4_boundary(self):
        """SOLAR_SUPER_CHARGING, SOC exactly at auto_start_soc (90%) → full assist."""
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = 1000
        power = _make_power(battery_soc=90, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_SUPER_CHARGING, power, self._make_context()
        )

        assert budget == 1000 + 4500

    def test_negative_base_clamped_to_zero(self):
        """Negative base budget is clamped to 0."""
        coord = _build_coordinator()
        coord._flow_calculator.calculate_ev_budget.return_value = -500
        power = _make_power(battery_soc=50, battery_discharge_power=0)

        budget = coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_CHARGING_ACTIVE, power, self._make_context()
        )

        assert budget == 0

    def test_forecast_passed_to_flow_calculator(self):
        """Forecast remaining is read and passed to flow_calculator.calculate_ev_budget."""
        coord = _build_coordinator()
        coord._forecast_reader.read_forecast.return_value = _MockForecast(
            available=True, remaining=12.5
        )
        coord._flow_calculator.calculate_ev_budget.return_value = 3000
        power = _make_power(battery_soc=50)

        coord._calculate_solar_ev_budget(
            ChargingState.SOLAR_CHARGING_ACTIVE, power, self._make_context()
        )

        # Verify forecast_remaining was passed through
        call_args = coord._flow_calculator.calculate_ev_budget.call_args
        assert call_args[0][1] == 12.5  # forecast_remaining positional arg
