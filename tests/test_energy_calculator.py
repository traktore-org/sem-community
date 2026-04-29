"""Tests for coordinator/energy_calculator.py."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import datetime, date, timedelta

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
    MIN_POWER_THRESHOLD,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    EnergyTotals,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def time_manager():
    """Return a mocked TimeManager."""
    tm = MagicMock()
    tm.get_current_meter_day_sunrise_based.return_value = date(2026, 4, 18)
    return tm


@pytest.fixture
def config():
    """Return a default config dict."""
    return {
        "update_interval": 30,
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
    }


@pytest.fixture
def calculator(config, time_manager):
    """Return an EnergyCalculator with mocked dependencies."""
    return EnergyCalculator(config, time_manager)


def _make_power(solar=0, grid_import=0, grid_export=0, home=0, ev=0,
                battery_charge=0, battery_discharge=0, battery_power=0,
                battery_soc=50):
    """Create a PowerReadings with specified values."""
    p = PowerReadings(
        solar_power=solar,
        grid_import_power=grid_import,
        grid_export_power=grid_export,
        home_consumption_power=home,
        ev_power=ev,
        battery_charge_power=battery_charge,
        battery_discharge_power=battery_discharge,
        battery_power=battery_power,
        battery_soc=battery_soc,
    )
    return p


def _freeze_now(year=2026, month=4, day=18, hour=12, minute=0, second=0):
    """Return a datetime for patching dt_util.now."""
    return datetime(year, month, day, hour, minute, second)


# ──────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────

@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_energy_basic(mock_dt, calculator):
    """Test basic power * time = energy calculation."""
    now = _freeze_now(hour=12, minute=0)
    mock_dt.now.return_value = now

    power = _make_power(solar=5000, home=2000, grid_import=0, grid_export=0)

    # First call sets _last_update, uses config interval (30s = 1/120 hour)
    energy = calculator.calculate_energy(power)
    # solar_increment = 5000 * (30/3600) / 1000 = 0.0417 kWh
    assert energy.daily_solar > 0
    assert energy.daily_home > 0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_energy_zero_power(mock_dt, calculator):
    """Test that zero power produces zero energy."""
    now = _freeze_now()
    mock_dt.now.return_value = now

    power = _make_power()  # all zeros
    energy = calculator.calculate_energy(power)
    assert energy.daily_solar == 0.0
    assert energy.daily_home == 0.0
    assert energy.daily_grid_import == 0.0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_daily_reset_at_midnight(mock_dt, calculator):
    """Test that daily accumulators reset on date change."""
    # First update at 23:59
    now1 = _freeze_now(hour=23, minute=59)
    mock_dt.now.return_value = now1
    power = _make_power(solar=3000, home=1000)
    calculator.calculate_energy(power)

    # Second update next day at 00:01
    now2 = _freeze_now(day=19, hour=0, minute=1)
    mock_dt.now.return_value = now2
    energy = calculator.calculate_energy(power)

    # Daily solar should only contain the second update's increment
    # The rollover should have cleared yesterday's data
    assert energy.daily_solar >= 0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_monthly_reset(mock_dt, calculator):
    """Test that monthly accumulators reset on month change."""
    # First update at end of month
    now1 = _freeze_now(month=3, day=31, hour=12)
    mock_dt.now.return_value = now1
    power = _make_power(solar=5000, home=2000)
    calculator.calculate_energy(power)

    # Accumulate some monthly data
    now2 = _freeze_now(month=3, day=31, hour=13)
    mock_dt.now.return_value = now2
    calculator.calculate_energy(power)

    monthly_before = calculator._get_monthly("solar", "2026_3")
    assert monthly_before > 0

    # New month — reset _last_update to avoid gap protection
    calculator._last_update = None
    now3 = _freeze_now(month=4, day=1, hour=0)
    mock_dt.now.return_value = now3
    energy = calculator.calculate_energy(power)

    # Old month data should be gone after rollover
    old_monthly = calculator._get_monthly("solar", "2026_3")
    assert old_monthly == 0.0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_trapezoidal_integration(mock_dt, calculator):
    """Test energy integration over two updates with different time deltas."""
    # First update
    now1 = _freeze_now(hour=12, minute=0)
    mock_dt.now.return_value = now1
    power = _make_power(solar=6000, home=2000)
    calculator.calculate_energy(power)

    # Second update 60 seconds later
    now2 = _freeze_now(hour=12, minute=1)
    mock_dt.now.return_value = now2
    energy = calculator.calculate_energy(power)

    # With 60s interval: solar_increment = 6000 * (60/3600) / 1000 = 0.1 kWh
    # Plus the first update at config interval (30/3600)
    assert energy.daily_solar > 0.1


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_min_power_threshold(mock_dt, calculator):
    """Test that power below MIN_POWER_THRESHOLD does not accumulate energy."""
    now = _freeze_now()
    mock_dt.now.return_value = now

    # Power below threshold (10W)
    power = _make_power(solar=5, home=5)
    energy = calculator.calculate_energy(power)
    assert energy.daily_solar == 0.0
    assert energy.daily_home == 0.0

    # First reading above threshold (establishes baseline)
    power2 = _make_power(solar=1000, home=500)
    now2 = _freeze_now(minute=1)
    mock_dt.now.return_value = now2
    calculator.calculate_energy(power2)

    # Second reading above threshold (should accumulate)
    power3 = _make_power(solar=1000, home=500)
    now3 = _freeze_now(minute=2)
    mock_dt.now.return_value = now3
    energy3 = calculator.calculate_energy(power3)
    assert energy3.daily_solar > 0


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_restore_state_roundtrip(mock_dt, calculator):
    """Test get_state / restore_state round-trip."""
    now = _freeze_now()
    mock_dt.now.return_value = now

    power = _make_power(solar=5000, home=2000, grid_import=500)
    calculator.calculate_energy(power)

    state = calculator.get_state()
    assert "daily_accumulators" in state
    assert "monthly_accumulators" in state
    assert "lifetime_accumulators" in state
    assert "last_update" in state

    # Create new calculator and restore
    new_calc = EnergyCalculator(calculator.config, MagicMock())
    new_calc.restore_state(state)

    assert new_calc._daily_accumulators == calculator._daily_accumulators
    assert new_calc._monthly_accumulators == calculator._monthly_accumulators
    assert new_calc._lifetime_accumulators == calculator._lifetime_accumulators
    assert new_calc._last_update is not None


def test_restore_state_none(calculator):
    """Test restoring None state is safe."""
    calculator.restore_state(None)
    assert calculator._daily_accumulators == {}


def test_calculate_costs(calculator):
    """Test cost calculation from energy totals."""
    energy = EnergyTotals(
        daily_solar=10.0,
        daily_home=8.0,
        daily_ev=2.0,
        daily_grid_import=3.0,
        daily_grid_export=2.0,
        daily_battery_discharge=1.5,
        monthly_solar=200.0,
        monthly_home=150.0,
        monthly_grid_import=60.0,
        monthly_grid_export=40.0,
        yearly_solar=2000.0,
        yearly_home=1500.0,
        yearly_grid_import=600.0,
        yearly_grid_export=400.0,
        yearly_ev=100.0,
        yearly_battery_charge=300.0,
        yearly_battery_discharge=280.0,
    )

    costs = calculator.calculate_costs(energy)

    # daily_costs = 3.0 * 0.30 = 0.90
    assert costs.daily_costs == pytest.approx(0.90)
    # daily_export_revenue = 2.0 * 0.08 = 0.16
    assert costs.daily_export_revenue == pytest.approx(0.16)
    # daily_net_cost = 0.90 - 0.16 = 0.74
    assert costs.daily_net_cost == pytest.approx(0.74)
    # daily_savings = (8+2 - 3) * 0.30 = 2.10
    assert costs.daily_savings == pytest.approx(2.10)
    # daily_battery_savings = 1.5 * 0.30 = 0.45
    assert costs.daily_battery_savings == pytest.approx(0.45)
    # monthly
    assert costs.monthly_costs == pytest.approx(60.0 * 0.30)


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_calculate_performance_autarky(mock_dt, calculator):
    """Test performance metrics: self-consumption and autarky rates."""
    mock_dt.now.return_value = _freeze_now()

    power = _make_power(solar=5000, battery_power=0)
    energy = EnergyTotals(
        daily_solar=10.0,
        daily_home=8.0,
        daily_ev=2.0,
        daily_grid_import=2.0,
        daily_grid_export=1.0,
    )

    metrics = calculator.calculate_performance(power, energy)

    # self_consumption = (10 - 1) / 10 * 100 = 90%
    assert metrics.self_consumption_rate == pytest.approx(90.0)
    # autarky = (8+2 - 2) / (8+2) * 100 = 80%
    assert metrics.autarky_rate == pytest.approx(80.0)

    # Clamped to [0, 100]
    assert 0 <= metrics.self_consumption_rate <= 100
    assert 0 <= metrics.autarky_rate <= 100


# ──────────────────────────────────────────────
# Integration gap protection (#123)
# ──────────────────────────────────────────────

@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_integration_gap_skips_accumulation(mock_dt, calculator, time_manager):
    """Test that a large time gap skips energy integration to prevent spikes."""
    from custom_components.solar_energy_management.coordinator.energy_calculator import (
        MAX_INTEGRATION_GAP_SECONDS,
    )

    time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 4, 29)

    # First update at T=0
    t0 = datetime(2026, 4, 29, 12, 0, 0)
    mock_dt.now.return_value = t0
    power = _make_power(solar=5000, home=3000, grid_export=2000)
    energy1 = calculator.calculate_energy(power)
    solar_after_first = energy1.daily_solar

    # Second update at T+10s (normal) — should accumulate
    t1 = t0 + timedelta(seconds=10)
    mock_dt.now.return_value = t1
    energy2 = calculator.calculate_energy(power)
    assert energy2.daily_solar > solar_after_first

    # Third update at T+5min (gap > MAX) — should NOT accumulate
    t2 = t1 + timedelta(seconds=MAX_INTEGRATION_GAP_SECONDS + 60)
    mock_dt.now.return_value = t2
    solar_before_gap = energy2.daily_solar
    energy3 = calculator.calculate_energy(power)
    assert energy3.daily_solar == solar_before_gap  # No change

    # Fourth update at T+5min+10s (normal again) — should accumulate
    t3 = t2 + timedelta(seconds=10)
    mock_dt.now.return_value = t3
    energy4 = calculator.calculate_energy(power)
    assert energy4.daily_solar > solar_before_gap


@patch("custom_components.solar_energy_management.coordinator.energy_calculator.dt_util")
def test_normal_interval_accumulates(mock_dt, calculator, time_manager):
    """Test that normal intervals accumulate energy correctly."""
    time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 4, 29)

    # First update uses config interval (30s) as default
    t0 = datetime(2026, 4, 29, 12, 0, 0)
    mock_dt.now.return_value = t0
    power = _make_power(solar=10000, battery_discharge=5000, home=15000)
    energy0 = calculator.calculate_energy(power)
    solar_after_first = energy0.daily_solar

    # 30 seconds later — accumulates another interval
    t1 = t0 + timedelta(seconds=30)
    mock_dt.now.return_value = t1
    energy = calculator.calculate_energy(power)

    # First update: 10000W * 30s/3600 / 1000 = 0.0833 kWh
    # Second update: another 0.0833 kWh → total ~0.167
    assert energy.daily_solar == pytest.approx(solar_after_first + 0.0833, abs=0.01)
    assert energy.daily_battery_discharge == pytest.approx(energy0.daily_battery_discharge + 0.0417, abs=0.01)
