"""Tests for energy flow accumulation logic.

These tests verify that energy values accumulate correctly using the
EnergyCalculator module's power integration approach.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import Mock, patch
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator import (
    EnergyCalculator,
    PowerReadings,
    EnergyTotals,
)


@pytest.fixture
def config():
    """Create a test configuration."""
    return {
        "update_interval": 30,
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
    }


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.states = Mock()
    hass.states.get = Mock(return_value=None)  # sun.sun unavailable → 06:00 fallback
    return hass


@pytest.fixture
def energy_calculator(config, mock_hass):
    """Create an EnergyCalculator instance."""
    from custom_components.solar_energy_management.utils.time_manager import TimeManager
    return EnergyCalculator(config, TimeManager(mock_hass))


@pytest.fixture
def power_readings_factory():
    """Create PowerReadings factory for testing."""
    def _make_readings(**kwargs):
        readings = PowerReadings()
        readings.solar_power = kwargs.get("solar_power", 0)
        readings.grid_power = kwargs.get("grid_power", 0)
        readings.battery_power = kwargs.get("battery_power", 0)
        readings.ev_power = kwargs.get("ev_power", 0)
        readings.battery_soc = kwargs.get("battery_soc", 50)
        readings.home_consumption_power = kwargs.get("home_consumption_power", 0)
        readings.calculate_derived()
        return readings
    return _make_readings


class TestEnergyCalculatorBasics:
    """Test basic EnergyCalculator functionality."""

    def test_initialization(self, energy_calculator):
        """Test calculator initializes with empty accumulators."""
        assert energy_calculator._daily_accumulators == {}
        assert energy_calculator._monthly_accumulators == {}

    @freeze_time("2025-11-01 16:20:00")
    def test_first_update_creates_accumulators(self, energy_calculator, power_readings_factory):
        """Test that first update creates accumulator entries."""
        readings = power_readings_factory(
            solar_power=5000,
            grid_power=-1000,
            battery_power=0,
            ev_power=0,
            home_consumption_power=4000,
        )

        energy = energy_calculator.calculate_energy(readings)

        # Should have created daily accumulators
        assert len(energy_calculator._daily_accumulators) > 0
        assert energy.daily_solar >= 0

    @freeze_time("2025-11-01 16:20:00")
    def test_solar_energy_accumulation(self, energy_calculator, power_readings_factory):
        """Test solar energy accumulates from power over time."""
        # 5000W for 30 seconds = 0.0417 kWh
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=5000,
        )

        energy = energy_calculator.calculate_energy(readings)

        # Should have some solar energy (depends on interval)
        assert energy.daily_solar >= 0


class TestEnergyAccumulation:
    """Test that flow values accumulate on every update cycle."""

    def test_accumulates_every_update_cycle(self, energy_calculator, power_readings_factory):
        """Test that energy values accumulate on EVERY update cycle."""
        readings = power_readings_factory(
            solar_power=5000,
            grid_power=-2000,
            battery_power=0,
            ev_power=0,
            home_consumption_power=3000,
        )

        with freeze_time("2025-11-01 16:20:00"):
            energy_1 = energy_calculator.calculate_energy(readings)
            solar_1 = energy_1.daily_solar

        with freeze_time("2025-11-01 16:20:30"):
            energy_2 = energy_calculator.calculate_energy(readings)
            solar_2 = energy_2.daily_solar

        # Values should increase (accumulation happens every cycle)
        assert solar_2 > solar_1, (
            f"Energy should accumulate on every update: "
            f"{solar_1} kWh should be < {solar_2} kWh"
        )

    def test_accumulates_across_minutes(self, energy_calculator, power_readings_factory):
        """Test that energy values accumulate across different minutes."""
        readings = power_readings_factory(
            solar_power=4000,
            home_consumption_power=2500,
        )

        with freeze_time("2025-11-01 16:20:00"):
            energy_1 = energy_calculator.calculate_energy(readings)
            solar_1 = energy_1.daily_solar

        with freeze_time("2025-11-01 16:26:00"):
            energy_2 = energy_calculator.calculate_energy(readings)
            solar_2 = energy_2.daily_solar

        # Values should increase (accumulation continues)
        assert solar_2 > solar_1, (
            f"Energy should accumulate across updates: "
            f"{solar_1} kWh should be < {solar_2} kWh"
        )


class TestDayRollover:
    """Test that accumulators reset at day boundaries."""

    def test_resets_accumulators_on_new_day(self, energy_calculator, power_readings_factory):
        """Test that accumulators reset at sunrise (sunrise-based meter day).

        Daily reset happens at sunrise, not midnight, so we must freeze time
        to after sunrise on the next calendar day to trigger rollover.
        With sun.sun unavailable the fallback sunrise is 06:00, so 08:00 is safe.
        """
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
        )

        with freeze_time("2025-11-01 16:20:00"):
            energy_day1 = energy_calculator.calculate_energy(readings)
            solar_day1 = energy_day1.daily_solar

        # After sunrise on Nov 2 (fallback 06:00 → use 08:00) to trigger rollover
        with freeze_time("2025-11-02 08:00:00"):
            energy_day2 = energy_calculator.calculate_energy(readings)

        # Old day's accumulators should be cleaned up
        # Check that no keys contain "2025-11-01"
        for key in energy_calculator._daily_accumulators:
            assert "2025-11-01" not in key, (
                f"Old day accumulator {key} should be cleaned up"
            )

    def test_daily_energy_never_decreases_within_day(self, energy_calculator, power_readings_factory):
        """Test energy values never decrease within the same day."""
        readings = power_readings_factory(
            solar_power=3000,
            home_consumption_power=2000,
        )

        previous_solar = 0

        with freeze_time("2025-11-01 16:00:00") as frozen_time:
            for minute in range(0, 60, 5):
                frozen_time.move_to(f"2025-11-01 16:{minute:02d}:00")
                energy = energy_calculator.calculate_energy(readings)
                current_solar = energy.daily_solar

                assert current_solar >= previous_solar, (
                    f"Energy decreased from {previous_solar} to {current_solar} "
                    f"at 16:{minute:02d}"
                )
                previous_solar = current_solar


class TestMonthlyAccumulation:
    """Test monthly energy accumulation."""

    def test_monthly_energy_accumulates(self, energy_calculator, power_readings_factory):
        """Test that monthly energy totals accumulate correctly."""
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
            ev_power=2000,
        )

        with freeze_time("2025-11-15 12:00:00"):
            energy_1 = energy_calculator.calculate_energy(readings)
            monthly_solar_1 = energy_1.monthly_solar

        with freeze_time("2025-11-15 12:30:00"):
            energy_2 = energy_calculator.calculate_energy(readings)
            monthly_solar_2 = energy_2.monthly_solar

        assert monthly_solar_2 > monthly_solar_1

    def test_monthly_resets_on_new_month(self, energy_calculator, power_readings_factory):
        """Test that monthly accumulators reset on new month.

        Uses post-sunrise time (>=06:00) because EnergyCalculator uses
        sunrise-based meter days — before sunrise is still "yesterday".
        """
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
        )

        with freeze_time("2025-11-30 12:00:00"):
            energy_nov = energy_calculator.calculate_energy(readings)

        with freeze_time("2025-12-01 08:00:00"):
            energy_dec = energy_calculator.calculate_energy(readings)

        # Check that November keys are cleaned up
        for key in energy_calculator._monthly_accumulators:
            assert "2025_11" not in key, (
                f"November accumulator {key} should be cleaned up"
            )


class TestCostCalculations:
    """Test cost and savings calculations."""

    def test_daily_cost_calculation(self, energy_calculator):
        """Test daily cost calculation from energy totals."""
        energy = EnergyTotals()
        energy.daily_grid_import = 10.0  # 10 kWh imported
        energy.daily_grid_export = 2.0  # 2 kWh exported
        energy.daily_home = 8.0
        energy.daily_ev = 4.0

        costs = energy_calculator.calculate_costs(energy)

        # Costs = 10 * 0.30 = 3.00
        assert costs.daily_costs == pytest.approx(3.0, abs=0.01)

        # Export revenue = 2 * 0.08 = 0.16
        assert costs.daily_export_revenue == pytest.approx(0.16, abs=0.01)

        # Net cost = 3.00 - 0.16 = 2.84
        assert costs.daily_net_cost == pytest.approx(2.84, abs=0.01)

    def test_savings_calculation(self, energy_calculator):
        """Test savings calculation (self-consumption value)."""
        energy = EnergyTotals()
        energy.daily_grid_import = 5.0  # 5 kWh from grid
        energy.daily_home = 10.0  # 10 kWh total home
        energy.daily_ev = 2.0  # 2 kWh EV

        costs = energy_calculator.calculate_costs(energy)

        # Total consumption = 10 + 2 = 12 kWh
        # Self-consumed = 12 - 5 = 7 kWh
        # Savings = 7 * 0.30 = 2.10
        assert costs.daily_savings == pytest.approx(2.10, abs=0.01)


class TestPerformanceMetrics:
    """Test performance metric calculations."""

    def test_self_consumption_rate(self, energy_calculator, power_readings_factory):
        """Test self-consumption rate calculation."""
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
        )

        energy = EnergyTotals()
        energy.daily_solar = 10.0  # 10 kWh solar
        energy.daily_grid_export = 2.0  # 2 kWh exported

        performance = energy_calculator.calculate_performance(readings, energy)

        # Self consumption = (10 - 2) / 10 = 80%
        assert performance.self_consumption_rate == pytest.approx(80.0, abs=1)

    def test_autarky_rate(self, energy_calculator, power_readings_factory):
        """Test autarky rate calculation."""
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
        )

        energy = EnergyTotals()
        energy.daily_home = 10.0  # 10 kWh home
        energy.daily_ev = 2.0  # 2 kWh EV
        energy.daily_grid_import = 3.0  # 3 kWh from grid

        performance = energy_calculator.calculate_performance(readings, energy)

        # Total consumption = 12 kWh
        # Own supply = 12 - 3 = 9 kWh
        # Autarky = 9 / 12 = 75%
        assert performance.autarky_rate == pytest.approx(75.0, abs=1)

    def test_zero_solar_metrics(self, energy_calculator, power_readings_factory):
        """Test metrics when solar is zero (night time)."""
        readings = power_readings_factory(
            solar_power=0,
            home_consumption_power=2000,
        )

        energy = EnergyTotals()
        energy.daily_solar = 0
        energy.daily_home = 5.0
        energy.daily_grid_import = 5.0

        performance = energy_calculator.calculate_performance(readings, energy)

        # Self consumption is 0% when no solar
        assert performance.self_consumption_rate == 0

        # Autarky is 0% when all from grid
        assert performance.autarky_rate == 0


class TestStatePersistence:
    """Test calculator state persistence and restoration."""

    def test_get_state_returns_accumulators(self, energy_calculator, power_readings_factory):
        """Test that get_state returns current accumulators."""
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
        )

        with freeze_time("2025-11-01 16:00:00"):
            energy_calculator.calculate_energy(readings)

        state = energy_calculator.get_state()

        assert "daily_accumulators" in state
        assert "monthly_accumulators" in state
        assert "last_update" in state

    def test_restore_state_recovers_accumulators(self, config, mock_hass, power_readings_factory):
        """Test that restore_state recovers accumulators."""
        from custom_components.solar_energy_management.utils.time_manager import TimeManager
        # Create and populate first calculator
        calc1 = EnergyCalculator(config, TimeManager(mock_hass))
        readings = power_readings_factory(
            solar_power=5000,
            home_consumption_power=3000,
        )

        with freeze_time("2025-11-01 16:00:00"):
            energy1 = calc1.calculate_energy(readings)
            state = calc1.get_state()
            solar_before = energy1.daily_solar

        # Create second calculator and restore state
        calc2 = EnergyCalculator(config, TimeManager(mock_hass))
        calc2.restore_state(state)

        with freeze_time("2025-11-01 16:30:00"):
            energy2 = calc2.calculate_energy(readings)
            solar_after = energy2.daily_solar

        # Should continue from where we left off
        assert solar_after > solar_before


class TestPowerThresholds:
    """Test minimum power threshold behavior."""

    def test_ignores_ghost_power(self, energy_calculator, power_readings_factory):
        """Test that very small power values don't accumulate."""
        # Power below MIN_POWER_THRESHOLD (10W) should be ignored
        readings = power_readings_factory(
            solar_power=5,  # 5W - below threshold
            home_consumption_power=5,
        )

        with freeze_time("2025-11-01 16:00:00"):
            energy_1 = energy_calculator.calculate_energy(readings)

        with freeze_time("2025-11-01 16:30:00"):
            energy_2 = energy_calculator.calculate_energy(readings)

        # Solar should not have accumulated (below threshold)
        assert energy_2.daily_solar == 0

    def test_accumulates_above_threshold(self, energy_calculator, power_readings_factory):
        """Test that power above threshold does accumulate."""
        # Power above MIN_POWER_THRESHOLD (10W) should accumulate
        readings = power_readings_factory(
            solar_power=1000,
            home_consumption_power=800,
        )

        with freeze_time("2025-11-01 16:00:00"):
            energy_1 = energy_calculator.calculate_energy(readings)

        with freeze_time("2025-11-01 16:30:00"):
            energy_2 = energy_calculator.calculate_energy(readings)

        # Solar should have accumulated
        assert energy_2.daily_solar > energy_1.daily_solar


class TestEnergyBalanceEquation:
    """Test energy balance equation holds."""

    def test_energy_balance_all_components(self, energy_calculator, power_readings_factory):
        """Test that all energy components are calculated correctly."""
        readings = power_readings_factory(
            solar_power=5000,
            grid_power=-1500,  # Importing 1500W
            battery_power=500,  # Charging 500W
            ev_power=2000,
            home_consumption_power=2000,
        )

        with freeze_time("2025-11-01 16:00:00"):
            energy = energy_calculator.calculate_energy(readings)

        # All values should be non-negative
        assert energy.daily_solar >= 0
        assert energy.daily_home >= 0
        assert energy.daily_ev >= 0
        assert energy.daily_grid_import >= 0
        assert energy.daily_grid_export >= 0
        assert energy.daily_battery_charge >= 0
        assert energy.daily_battery_discharge >= 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
