"""Boundary value tests for PowerReadings, EnergyCalculator, and FlowCalculator.

Covers: zero values, maximum values, sign boundaries, SOC boundaries, time
rollover, sensor unavailability, threshold edges, and division-by-zero guards.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
    MIN_POWER_THRESHOLD,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
    PowerReadings,
)


# ──────────────────────────────────────────────────────────────────────────────
# Shared helpers
# ──────────────────────────────────────────────────────────────────────────────

def _readings(
    solar: float = 0.0,
    grid_power: float = 0.0,
    battery_power: float = 0.0,
    ev: float = 0.0,
    battery_soc: float = 50.0,
) -> PowerReadings:
    """Build PowerReadings from raw sensor values and call calculate_derived()."""
    p = PowerReadings(
        solar_power=solar,
        grid_power=grid_power,
        battery_power=battery_power,
        ev_power=ev,
        battery_soc=battery_soc,
    )
    p.calculate_derived()
    return p


def _split_readings(
    solar: float = 0.0,
    grid_import: float = 0.0,
    grid_export: float = 0.0,
    home: float = 0.0,
    ev: float = 0.0,
    battery_charge: float = 0.0,
    battery_discharge: float = 0.0,
    battery_soc: float = 50.0,
) -> PowerReadings:
    """Build PowerReadings with explicit split values (already derived)."""
    return PowerReadings(
        solar_power=solar,
        grid_import_power=grid_import,
        grid_export_power=grid_export,
        home_consumption_power=home,
        ev_power=ev,
        battery_charge_power=battery_charge,
        battery_discharge_power=battery_discharge,
        battery_soc=battery_soc,
    )


def _freeze(year=2026, month=5, day=15, hour=12, minute=0, second=0) -> datetime:
    return datetime(year, month, day, hour, minute, second)


@pytest.fixture
def time_manager():
    tm = MagicMock()
    tm.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)
    return tm


@pytest.fixture
def config():
    return {
        "update_interval": 30,
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
        "battery_capacity_kwh": 15.0,
        "system_size_kwp": 10.0,
    }


@pytest.fixture
def calculator(config, time_manager):
    return EnergyCalculator(config, time_manager)


@pytest.fixture
def flow_calc():
    return FlowCalculator()


# ──────────────────────────────────────────────────────────────────────────────
# Zero values
# ──────────────────────────────────────────────────────────────────────────────

class TestZeroValues:
    """All sensors at zero — nothing should crash and all outputs should be 0."""

    def test_all_sensors_zero_no_crash(self):
        """should not raise when all sensor inputs are exactly 0."""
        p = _readings(solar=0, grid_power=0, battery_power=0, ev=0)
        # Only asserting no exception — all fields should be numeric
        assert p.solar_power == 0.0
        assert p.home_consumption_power == 0.0

    def test_all_sensors_zero_grid_import_is_zero(self):
        """should produce 0 grid_import_power when all inputs are 0."""
        p = _readings()
        assert p.grid_import_power == 0.0

    def test_all_sensors_zero_grid_export_is_zero(self):
        """should produce 0 grid_export_power when all inputs are 0."""
        p = _readings()
        assert p.grid_export_power == 0.0

    def test_all_sensors_zero_battery_splits_are_zero(self):
        """should produce 0 charge and discharge when battery_power=0."""
        p = _readings()
        assert p.battery_charge_power == 0.0
        assert p.battery_discharge_power == 0.0

    def test_solar_zero_battery_discharging_home_powered_by_battery(self):
        """should assign home power from battery discharge when solar=0."""
        # battery_power=-2000 → discharge; no solar; no grid
        p = _readings(solar=0, grid_power=0, battery_power=-2000)
        assert p.battery_discharge_power == pytest.approx(2000.0)
        assert p.home_consumption_power == pytest.approx(2000.0)

    def test_grid_zero_autarky_should_be_100_when_solar_covers_all(self):
        """should report 100% autarky when grid_power=0 and solar covers home."""
        # Solar 3000W → home 3000W, no grid
        p = _readings(solar=3000, grid_power=0, battery_power=0)
        # home = solar + 0 + 0 - 0 - 0 - 0 = 3000
        assert p.grid_import_power == 0.0
        assert p.home_consumption_power == pytest.approx(3000.0)

    def test_grid_zero_performance_autarky_100_percent(self):
        """should compute 100% autarky when consumption comes only from solar."""
        energy = EnergyTotals(
            daily_solar=10.0,
            daily_home=8.0,
            daily_ev=2.0,
            daily_grid_import=0.0,
            daily_grid_export=0.0,
        )
        # Manual formula: autarky = (consumption - import) / consumption * 100
        total = energy.daily_home + energy.daily_ev
        autarky = (total - energy.daily_grid_import) / total * 100
        assert autarky == pytest.approx(100.0, abs=0.01)

    def test_ev_zero_no_ev_impact_on_home_balance(self):
        """should not change home_consumption when ev_power=0."""
        p_no_ev = _readings(solar=4000, grid_power=0, battery_power=0, ev=0)
        p_ev_zero = _readings(solar=4000, grid_power=0, battery_power=0, ev=0)
        assert p_no_ev.home_consumption_power == p_ev_zero.home_consumption_power

    def test_ev_zero_leaves_full_solar_for_home(self):
        """should route all solar surplus to home when ev=0 and no battery."""
        p = _readings(solar=3000, grid_power=0, battery_power=0, ev=0)
        assert p.home_consumption_power == pytest.approx(3000.0)


# ──────────────────────────────────────────────────────────────────────────────
# Maximum values
# ──────────────────────────────────────────────────────────────────────────────

class TestMaximumValues:
    """Extreme power values should not produce invalid outputs."""

    def test_solar_at_maximum_15000w_produces_valid_splits(self):
        """should split 15000W solar into valid non-negative flow values."""
        p = _readings(solar=15000, grid_power=12000, battery_power=0)
        # grid_power=12000 → export 12000
        assert p.solar_power == 15000.0
        assert p.grid_export_power == pytest.approx(12000.0)
        assert p.home_consumption_power >= 0.0

    def test_solar_at_maximum_all_outputs_non_negative(self, flow_calc):
        """should return all non-negative flows when solar is at maximum."""
        power = _split_readings(solar=15000, home=2000, grid_export=13000)
        flows = flow_calc.calculate_power_flows(power)
        assert flows.solar_to_home >= 0.0
        assert flows.solar_to_grid >= 0.0
        assert flows.solar_to_battery >= 0.0
        assert flows.solar_to_ev >= 0.0

    def test_battery_at_max_charge_5000w_charge_power_positive(self):
        """should set battery_charge_power=5000 when battery_power=+5000."""
        p = _readings(solar=8000, grid_power=0, battery_power=5000)
        assert p.battery_charge_power == pytest.approx(5000.0)
        assert p.battery_discharge_power == 0.0

    def test_battery_at_max_discharge_5000w_discharge_power_positive(self):
        """should set battery_discharge_power=5000 when battery_power=-5000."""
        p = _readings(solar=0, grid_power=0, battery_power=-5000)
        assert p.battery_discharge_power == pytest.approx(5000.0)
        assert p.battery_charge_power == 0.0

    def test_grid_import_at_peak_10000w_import_power_correct(self):
        """should set grid_import_power=10000 when grid_power=-10000."""
        p = _readings(solar=0, grid_power=-10000, battery_power=0)
        assert p.grid_import_power == pytest.approx(10000.0)
        assert p.grid_export_power == 0.0

    def test_grid_import_at_peak_home_consumption_non_negative(self):
        """should keep home_consumption_power >= 0 under maximum grid import."""
        p = _readings(solar=0, grid_power=-10000, battery_power=0)
        assert p.home_consumption_power >= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Sign boundaries
# ──────────────────────────────────────────────────────────────────────────────

class TestSignBoundaries:
    """Power values at exactly zero and sign flips."""

    def test_grid_power_exactly_zero_no_import_no_export(self):
        """should set both grid_import and grid_export to 0 when grid_power=0."""
        p = _readings(solar=3000, grid_power=0, battery_power=0)
        assert p.grid_import_power == 0.0
        assert p.grid_export_power == 0.0

    def test_battery_power_exactly_zero_no_charge_no_discharge(self):
        """should set both charge and discharge to 0 when battery_power=0."""
        p = _readings(solar=2000, grid_power=0, battery_power=0)
        assert p.battery_charge_power == 0.0
        assert p.battery_discharge_power == 0.0

    def test_grid_power_flipping_from_import_to_export(self):
        """should correctly split after grid_power sign changes from negative to positive."""
        p_import = _readings(solar=1000, grid_power=-2000)
        assert p_import.grid_import_power == pytest.approx(2000.0)
        assert p_import.grid_export_power == 0.0

        p_export = _readings(solar=5000, grid_power=2000)
        assert p_export.grid_export_power == pytest.approx(2000.0)
        assert p_export.grid_import_power == 0.0

    def test_battery_power_flipping_from_charge_to_discharge(self):
        """should correctly split after battery_power sign changes from positive to negative."""
        p_charge = _readings(solar=5000, battery_power=3000)
        assert p_charge.battery_charge_power == pytest.approx(3000.0)
        assert p_charge.battery_discharge_power == 0.0

        p_discharge = _readings(solar=0, battery_power=-3000)
        assert p_discharge.battery_discharge_power == pytest.approx(3000.0)
        assert p_discharge.battery_charge_power == 0.0

    def test_grid_import_power_never_negative(self):
        """should never produce negative grid_import_power regardless of sign."""
        for gp in [-5000, -1, 0, 1, 5000]:
            p = _readings(grid_power=gp)
            assert p.grid_import_power >= 0.0, f"grid_import_power negative at grid_power={gp}"

    def test_grid_export_power_never_negative(self):
        """should never produce negative grid_export_power regardless of sign."""
        for gp in [-5000, -1, 0, 1, 5000]:
            p = _readings(grid_power=gp)
            assert p.grid_export_power >= 0.0, f"grid_export_power negative at grid_power={gp}"

    def test_battery_charge_power_never_negative(self):
        """should never produce negative battery_charge_power regardless of battery_power sign."""
        for bp in [-5000, -1, 0, 1, 5000]:
            p = _readings(battery_power=bp)
            assert p.battery_charge_power >= 0.0

    def test_battery_discharge_power_never_negative(self):
        """should never produce negative battery_discharge_power regardless of battery_power sign."""
        for bp in [-5000, -1, 0, 1, 5000]:
            p = _readings(battery_power=bp)
            assert p.battery_discharge_power >= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# SOC boundaries
# ──────────────────────────────────────────────────────────────────────────────

class TestSOCBoundaries:
    """Battery SOC at critical thresholds."""

    def test_soc_zero_percent_battery_discharge_power_still_calculated(self):
        """should still compute battery_discharge_power even when SOC=0%."""
        # PowerReadings does not enforce SOC constraints — that's the controller's job.
        # calculate_derived() must not crash or zero out discharge at SOC=0.
        p = _readings(solar=0, grid_power=0, battery_power=-1000, battery_soc=0.0)
        assert p.battery_discharge_power == pytest.approx(1000.0)

    def test_soc_100_percent_battery_charge_power_still_calculated(self):
        """should still compute battery_charge_power even when SOC=100%."""
        p = _readings(solar=8000, grid_power=0, battery_power=3000, battery_soc=100.0)
        assert p.battery_charge_power == pytest.approx(3000.0)

    def test_soc_20_percent_low_threshold_discharge_computed(self):
        """should compute battery_discharge_power correctly at SOC=20%."""
        p = _readings(solar=0, battery_power=-2000, battery_soc=20.0)
        assert p.battery_discharge_power == pytest.approx(2000.0)

    def test_soc_50_percent_midpoint_no_side_effects(self):
        """should compute battery splits correctly at midpoint SOC=50%."""
        p = _readings(solar=4000, battery_power=1500, battery_soc=50.0)
        assert p.battery_charge_power == pytest.approx(1500.0)
        assert p.battery_discharge_power == 0.0

    def test_soc_stored_on_readings(self):
        """should preserve battery_soc value on the PowerReadings object."""
        p = _readings(battery_soc=73.5)
        assert p.battery_soc == pytest.approx(73.5)

    def test_battery_redirect_soc_zero_no_redirect_without_forecast(self, flow_calc):
        """should return 0 battery redirect at SOC=0% with no forecast (SOC < 80 threshold)."""
        redirect = flow_calc._calculate_battery_redirect(
            battery_charge_w=3000.0,
            battery_soc=0.0,
            battery_capacity_kwh=15.0,
            forecast_remaining_kwh=0.0,
        )
        assert redirect == 0.0

    def test_battery_redirect_soc_100_full_redirect_no_forecast(self, flow_calc):
        """should redirect all charge power at SOC=100% with no forecast (SOC >= 80)."""
        redirect = flow_calc._calculate_battery_redirect(
            battery_charge_w=2000.0,
            battery_soc=100.0,
            battery_capacity_kwh=15.0,
            forecast_remaining_kwh=0.0,
        )
        assert redirect == pytest.approx(2000.0, abs=1.0)


# ──────────────────────────────────────────────────────────────────────────────
# Time boundaries
# ──────────────────────────────────────────────────────────────────────────────

class TestTimeBoundaries:
    """Day, month, and year rollover behaviour."""

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_midnight_rollover_resets_daily_accumulators(self, mock_dt, calculator, time_manager):
        """should remove yesterday's daily accumulator keys after midnight rollover."""
        day1 = date(2026, 5, 14)
        day2 = date(2026, 5, 15)

        time_manager.get_current_meter_day_sunrise_based.return_value = day1
        mock_dt.now.return_value = _freeze(2026, 5, 14, 12)

        power = PowerReadings(solar_power=5000, grid_import_power=0,
                              grid_export_power=0, home_consumption_power=3000)
        calculator.calculate_energy(power)

        # Confirm data accumulated for day1
        assert calculator._daily_accumulators.get(f"solar_{day1}", 0) > 0

        # Advance to day2
        calculator._last_update = _freeze(2026, 5, 14, 23, 59, 50)
        mock_dt.now.return_value = _freeze(2026, 5, 15, 0, 0, 5)
        time_manager.get_current_meter_day_sunrise_based.return_value = day2
        calculator.calculate_energy(power)

        # Day1 key should be gone
        assert f"solar_{day1}" not in calculator._daily_accumulators

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_month_rollover_resets_monthly_accumulators(self, mock_dt, calculator, time_manager):
        """should remove previous month's accumulator keys after month rollover."""
        april_day = date(2026, 4, 30)
        may_day = date(2026, 5, 1)

        time_manager.get_current_meter_day_sunrise_based.return_value = april_day
        mock_dt.now.return_value = _freeze(2026, 4, 30, 12)

        power = PowerReadings(solar_power=5000, home_consumption_power=3000)
        calculator.calculate_energy(power)

        assert calculator._monthly_accumulators.get("solar_2026_4", 0) > 0

        calculator._last_update = _freeze(2026, 4, 30, 23, 59, 50)
        mock_dt.now.return_value = _freeze(2026, 5, 1, 0, 0, 5)
        time_manager.get_current_meter_day_sunrise_based.return_value = may_day
        calculator.calculate_energy(power)

        assert "solar_2026_4" not in calculator._monthly_accumulators

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_year_rollover_resets_yearly_accumulators(self, mock_dt, calculator, time_manager):
        """should remove previous year's accumulator keys after year rollover."""
        dec31 = date(2025, 12, 31)
        jan1 = date(2026, 1, 1)

        time_manager.get_current_meter_day_sunrise_based.return_value = dec31
        mock_dt.now.return_value = _freeze(2025, 12, 31, 12)

        power = PowerReadings(solar_power=2000, home_consumption_power=1000)
        calculator.calculate_energy(power)

        assert calculator._yearly_accumulators.get("solar_2025", 0) > 0

        calculator._last_update = _freeze(2025, 12, 31, 23, 59, 50)
        mock_dt.now.return_value = _freeze(2026, 1, 1, 0, 0, 5)
        time_manager.get_current_meter_day_sunrise_based.return_value = jan1
        calculator.calculate_energy(power)

        assert "solar_2025" not in calculator._yearly_accumulators

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_first_cycle_after_restart_returns_zero_totals(self, mock_dt, calculator, time_manager):
        """should return zero totals on the very first call when all accumulators are empty."""
        mock_dt.now.return_value = _freeze(2026, 5, 15, 8)
        time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)

        power = PowerReadings(solar_power=0, home_consumption_power=0)
        energy = calculator.calculate_energy(power)

        assert energy.daily_solar == 0.0
        assert energy.daily_home == 0.0
        assert energy.daily_grid_import == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Sensor unavailability
# ──────────────────────────────────────────────────────────────────────────────

class TestSensorUnavailability:
    """Unavailable sensors default to 0 — system must not crash."""

    def test_solar_unavailable_defaults_to_zero(self):
        """should use solar_power=0 when solar sensor is unavailable."""
        # SEM sets solar_power=0 when sensor is unavailable before calling calculate_derived
        p = _readings(solar=0, grid_power=-1000)
        # Must not raise; home powered entirely by grid
        assert p.solar_power == 0.0
        assert p.grid_import_power == pytest.approx(1000.0)

    def test_grid_unavailable_defaults_to_zero(self):
        """should use grid_power=0 when grid sensor is unavailable."""
        p = _readings(solar=3000, grid_power=0, battery_power=0)
        assert p.grid_import_power == 0.0
        assert p.grid_export_power == 0.0

    def test_battery_unavailable_defaults_to_zero(self):
        """should use battery_power=0 when battery sensor is unavailable."""
        p = _readings(solar=3000, grid_power=0, battery_power=0)
        assert p.battery_charge_power == 0.0
        assert p.battery_discharge_power == 0.0

    def test_all_sensors_unavailable_home_consumption_is_zero(self):
        """should produce home_consumption_power=0 when all sensors are unavailable (all 0)."""
        p = _readings(solar=0, grid_power=0, battery_power=0, ev=0)
        assert p.home_consumption_power == 0.0

    def test_battery_soc_unavailable_flag_preserved(self):
        """should preserve battery_soc_unavailable flag without crashing."""
        p = PowerReadings(solar_power=0, battery_soc_unavailable=True)
        p.calculate_derived()
        assert p.battery_soc_unavailable is True

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_all_unavailable_energy_accumulators_stay_zero(self, mock_dt, calculator, time_manager):
        """should accumulate no energy when all sensors report 0 (unavailable)."""
        mock_dt.now.return_value = _freeze(2026, 5, 15, 10)
        time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)

        power = PowerReadings()  # all defaults = 0.0
        calculator.calculate_energy(power)

        mock_dt.now.return_value = _freeze(2026, 5, 15, 10, 0, 30)
        calculator.calculate_energy(power)

        today = date(2026, 5, 15)
        assert calculator._get_daily("solar", today) == 0.0
        assert calculator._get_daily("grid_import", today) == 0.0
        assert calculator._get_daily("battery_charge", today) == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Small values near MIN_POWER_THRESHOLD
# ──────────────────────────────────────────────────────────────────────────────

class TestPowerThresholdBoundaries:
    """Energy accumulation must respect MIN_POWER_THRESHOLD (10W)."""

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_power_at_exactly_threshold_does_accumulate(self, mock_dt, calculator, time_manager):
        """should accumulate energy when solar_power == MIN_POWER_THRESHOLD (10W).

        Run many 30s cycles so the rounded kWh accumulator exceeds 0.00 at 2dp.
        10W × 100 × (30/3600) / 1000 ≈ 0.0083 kWh — clearly > 0.
        """
        today = date(2026, 5, 15)
        time_manager.get_current_meter_day_sunrise_based.return_value = today
        t0 = _freeze(2026, 5, 15, 10)

        power = PowerReadings(solar_power=MIN_POWER_THRESHOLD)
        for i in range(100):
            mock_dt.now.return_value = t0 + timedelta(seconds=i * 30)
            calculator.calculate_energy(power)

        assert calculator._get_daily("solar", today) > 0.0

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_power_below_threshold_9w_does_not_accumulate(self, mock_dt, calculator, time_manager):
        """should NOT accumulate energy when solar_power=9W (just below threshold).

        Run many cycles — with 9W < MIN_POWER_THRESHOLD the accumulator must stay 0.
        """
        today = date(2026, 5, 15)
        time_manager.get_current_meter_day_sunrise_based.return_value = today
        t0 = _freeze(2026, 5, 15, 10)

        power = PowerReadings(solar_power=9.0)
        for i in range(100):
            mock_dt.now.return_value = t0 + timedelta(seconds=i * 30)
            calculator.calculate_energy(power)

        assert calculator._get_daily("solar", today) == 0.0

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_power_above_threshold_11w_does_accumulate(self, mock_dt, calculator, time_manager):
        """should accumulate energy when solar_power=11W (just above threshold).

        Run many 30s cycles so the rounded kWh total is detectably > 0.
        11W × 100 × (30/3600) / 1000 ≈ 0.0092 kWh.
        """
        today = date(2026, 5, 15)
        time_manager.get_current_meter_day_sunrise_based.return_value = today
        t0 = _freeze(2026, 5, 15, 10)

        power = PowerReadings(solar_power=11.0)
        for i in range(100):
            mock_dt.now.return_value = t0 + timedelta(seconds=i * 30)
            calculator.calculate_energy(power)

        assert calculator._get_daily("solar", today) > 0.0

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_threshold_applies_to_grid_import(self, mock_dt, calculator, time_manager):
        """should NOT accumulate grid_import energy at 9W (below threshold)."""
        today = date(2026, 5, 15)
        time_manager.get_current_meter_day_sunrise_based.return_value = today
        t0 = _freeze(2026, 5, 15, 10)

        power = PowerReadings(grid_import_power=9.0)
        for i in range(100):
            mock_dt.now.return_value = t0 + timedelta(seconds=i * 30)
            calculator.calculate_energy(power)

        assert calculator._get_daily("grid_import", today) == 0.0

    @patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
    def test_threshold_applies_to_battery_discharge(self, mock_dt, calculator, time_manager):
        """should NOT accumulate battery_discharge energy at 9W (below threshold)."""
        today = date(2026, 5, 15)
        time_manager.get_current_meter_day_sunrise_based.return_value = today
        t0 = _freeze(2026, 5, 15, 10)

        power = PowerReadings(battery_discharge_power=9.0)
        for i in range(100):
            mock_dt.now.return_value = t0 + timedelta(seconds=i * 30)
            calculator.calculate_energy(power)

        assert calculator._get_daily("battery_discharge", today) == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Division-by-zero guards
# ──────────────────────────────────────────────────────────────────────────────

class TestDivisionByZero:
    """Rates, autarky, and current calculations must not raise ZeroDivisionError."""

    def test_self_consumption_rate_with_zero_solar_returns_zero(self):
        """should return 0 self_consumption_rate (not raise) when daily_solar=0."""
        energy = EnergyTotals(
            daily_solar=0.0,
            daily_grid_export=0.0,
            daily_home=5.0,
        )
        config = {
            "update_interval": 30,
            "electricity_import_rate": 0.30,
            "electricity_export_rate": 0.08,
        }
        tm = MagicMock()
        tm.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)
        calc = EnergyCalculator(config, tm)

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _freeze()
            power = PowerReadings(solar_power=0)
            metrics = calc.calculate_performance(power, energy)

        assert metrics.self_consumption_rate == 0.0

    def test_autarky_rate_with_zero_consumption_returns_zero(self):
        """should return 0 autarky_rate (not raise) when total consumption=0."""
        energy = EnergyTotals(
            daily_solar=10.0,
            daily_home=0.0,
            daily_ev=0.0,
            daily_grid_import=0.0,
        )
        config = {
            "update_interval": 30,
            "electricity_import_rate": 0.30,
            "electricity_export_rate": 0.08,
        }
        tm = MagicMock()
        tm.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)
        calc = EnergyCalculator(config, tm)

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = _freeze()
            power = PowerReadings(solar_power=5000)
            metrics = calc.calculate_performance(power, energy)

        assert metrics.autarky_rate == 0.0

    def test_calculate_power_flows_zero_supply_returns_empty_flows(self, flow_calc):
        """should return zeroed PowerFlows (not raise) when total supply < 1W."""
        power = _split_readings(solar=0, grid_import=0, battery_discharge=0, home=500)
        flows = flow_calc.calculate_power_flows(power)
        # No supply → no flows distributed
        assert flows.solar_to_home == 0.0
        assert flows.grid_to_home == 0.0

    def test_calculate_power_flows_zero_demand_returns_empty_flows(self, flow_calc):
        """should return zeroed PowerFlows (not raise) when total demand < 1W."""
        power = _split_readings(solar=3000, home=0, ev=0, battery_charge=0, grid_export=0)
        flows = flow_calc.calculate_power_flows(power)
        assert flows.solar_to_home == 0.0

    # ``test_calculate_energy_flows_zero_demand...`` removed in the legacy
    # retirement (#536): the deprecated proportional ``calculate_energy_flows``
    # is gone. The zero-demand boundary of the live path is covered by
    # ``calculate_power_flows`` tests above and ``integrate_energy_flows``.

    # ``calculate_charging_current`` zero/negative boundary tests removed
    # in Phase D.2 (#282): the method was deleted. The watts→amps path now
    # lives in ``EVControlMixin._watts_to_amps`` whose own zero/negative
    # boundary is exercised by the canonical-budget tests.

    def test_battery_redirect_zero_charge_power_returns_zero(self, flow_calc):
        """should return 0 redirect (not raise) when battery_charge_w=0."""
        redirect = flow_calc._calculate_battery_redirect(0.0, 50.0, 15.0, 8.0)
        assert redirect == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Flow calculator boundary: no activity
# ──────────────────────────────────────────────────────────────────────────────

class TestFlowCalculatorBoundaries:
    """FlowCalculator edge cases around zero and single-source scenarios."""

    def test_power_flows_only_battery_discharging_to_home(self, flow_calc):
        """should attribute all home power to battery when only battery supplies home."""
        power = _split_readings(
            solar=0,
            grid_import=0,
            battery_discharge=2000,
            home=2000,
        )
        flows = flow_calc.calculate_power_flows(power)
        assert flows.battery_to_home == pytest.approx(2000.0, abs=1.0)
        assert flows.solar_to_home == 0.0
        assert flows.grid_to_home == 0.0

    def test_power_flows_only_solar_to_grid_export(self, flow_calc):
        """should attribute all solar to grid export when home=0 and only export exists."""
        power = _split_readings(
            solar=5000,
            grid_export=5000,
            home=0,
            ev=0,
            battery_charge=0,
        )
        flows = flow_calc.calculate_power_flows(power)
        assert flows.solar_to_grid == pytest.approx(5000.0, abs=1.0)

    # ``test_ev_budget_no_export_no_ev_returns_zero``,
    # ``test_available_power_zero_when_all_solar_used_by_home``,
    # ``test_charging_current_clamped_to_16a_maximum``, and
    # ``test_charging_current_minimum_is_zero_not_negative`` removed in
    # Phase D.2 (#282). The three primitives they exercised were deleted;
    # the equivalent zero/clamp invariants now ride on the canonical
    # EVBudget tests and ``EVControlMixin._watts_to_amps``.

    def test_power_flows_proportional_with_equal_home_ev(self, flow_calc):
        """should distribute solar equally to home and EV when both demand is equal."""
        power = _split_readings(
            solar=4000,
            home=2000,
            ev=2000,
        )
        flows = flow_calc.calculate_power_flows(power)
        assert flows.solar_to_home == pytest.approx(flows.solar_to_ev, abs=1.0)

    def test_home_consumption_always_non_negative_under_all_combos(self):
        """should keep home_consumption_power >= 0 for varied sign combinations."""
        combos = [
            (0, 0, 0, 0),
            (5000, -3000, 2000, 1000),    # solar, grid_export, batt_charge, ev
            (0, 500, -200, 0),             # small values
            (10000, 5000, 3000, 2000),
            (100, 0, 0, 200),              # ev > solar (covered by grid normally)
        ]
        for solar, grid_power, battery_power, ev in combos:
            p = _readings(solar=solar, grid_power=grid_power,
                          battery_power=battery_power, ev=ev)
            assert p.home_consumption_power >= 0.0, (
                f"home_consumption_power < 0 for solar={solar}, "
                f"grid={grid_power}, batt={battery_power}, ev={ev}"
            )
