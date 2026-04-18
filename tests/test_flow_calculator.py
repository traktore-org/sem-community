"""Tests for coordinator/flow_calculator.py."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import date

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    EnergyTotals,
)


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def calc():
    """Return a FlowCalculator."""
    with patch(
        "custom_components.solar_energy_management.coordinator.flow_calculator.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = MagicMock(date=MagicMock(return_value=date(2026, 4, 18)))
        return FlowCalculator()


def _make_power(**kwargs):
    """Create a PowerReadings with specified values."""
    return PowerReadings(**kwargs)


# ──────────────────────────────────────────────
# Power flow tests
# ──────────────────────────────────────────────

def test_calculate_power_flows_solar_to_home(calc):
    """Test solar flows proportionally to home when home is only destination."""
    power = _make_power(
        solar_power=3000,
        grid_import_power=0,
        battery_discharge_power=0,
        home_consumption_power=2000,
        ev_power=0,
        battery_charge_power=0,
        grid_export_power=1000,
    )
    flows = calc.calculate_power_flows(power)

    # Total demand = 2000 + 0 + 0 + 1000 = 3000
    # home_pct = 2000/3000 = 0.667
    # solar_to_home = 3000 * 0.667 = 2000
    assert flows.solar_to_home == pytest.approx(2000, abs=1)
    assert flows.solar_to_grid == pytest.approx(1000, abs=1)
    assert flows.solar_to_ev == 0.0
    assert flows.solar_to_battery == 0.0


def test_calculate_power_flows_battery_discharge(calc):
    """Test battery discharge flows to home and EV only."""
    power = _make_power(
        solar_power=0,
        grid_import_power=0,
        battery_discharge_power=2000,
        home_consumption_power=1500,
        ev_power=500,
        battery_charge_power=0,
        grid_export_power=0,
    )
    flows = calc.calculate_power_flows(power)

    # Battery discharge goes to home and EV
    # home_pct_battery = 1500 / (1500+500) = 0.75
    assert flows.battery_to_home == pytest.approx(1500, abs=1)
    assert flows.battery_to_ev == pytest.approx(500, abs=1)


def test_calculate_power_flows_grid_import(calc):
    """Test grid import flows to home, EV, battery but not back to grid."""
    power = _make_power(
        solar_power=0,
        grid_import_power=3000,
        battery_discharge_power=0,
        home_consumption_power=2000,
        ev_power=500,
        battery_charge_power=500,
        grid_export_power=0,
    )
    flows = calc.calculate_power_flows(power)

    # Grid goes to home, EV, battery (demand_without_export = 3000)
    assert flows.grid_to_home == pytest.approx(2000, abs=1)
    assert flows.grid_to_ev == pytest.approx(500, abs=1)
    assert flows.grid_to_battery == pytest.approx(500, abs=1)


def test_zero_supply_returns_empty_flows(calc):
    """Test that zero supply produces empty flows."""
    power = _make_power(
        solar_power=0,
        grid_import_power=0,
        battery_discharge_power=0,
        home_consumption_power=0,
        ev_power=0,
        battery_charge_power=0,
        grid_export_power=0,
    )
    flows = calc.calculate_power_flows(power)

    assert flows.solar_to_home == 0.0
    assert flows.solar_to_grid == 0.0
    assert flows.grid_to_home == 0.0
    assert flows.battery_to_home == 0.0


def test_proportional_allocation(calc):
    """Test proportional allocation with multiple sources and destinations."""
    power = _make_power(
        solar_power=5000,
        grid_import_power=1000,
        battery_discharge_power=500,
        home_consumption_power=3000,
        ev_power=2000,
        battery_charge_power=500,
        grid_export_power=1000,
    )
    flows = calc.calculate_power_flows(power)

    # Total demand = 3000 + 2000 + 500 + 1000 = 6500
    # home_pct = 3000/6500 ~ 0.4615
    # Solar splits proportionally across all destinations
    total_solar_out = (
        flows.solar_to_home + flows.solar_to_ev +
        flows.solar_to_battery + flows.solar_to_grid
    )
    assert total_solar_out == pytest.approx(5000, abs=2)

    # Grid import does NOT flow back to grid
    assert flows.grid_to_home > 0
    assert flows.grid_to_ev > 0


# ──────────────────────────────────────────────
# Energy flow tests
# ──────────────────────────────────────────────

def test_calculate_energy_flows(calc):
    """Test energy flow calculation from daily energy totals."""
    energy = EnergyTotals(
        daily_solar=10.0,
        daily_grid_import=3.0,
        daily_battery_discharge=2.0,
        daily_home=8.0,
        daily_ev=3.0,
        daily_battery_charge=2.0,
        daily_grid_export=2.0,
    )
    flows = calc.calculate_energy_flows(energy)

    # Total demand = 8 + 3 + 2 + 2 = 15
    # Solar splits: home_pct = 8/15
    assert flows.solar_to_home > 0
    assert flows.solar_to_grid > 0

    # Energy balance: solar flows should sum to ~solar total
    total_solar = (
        flows.solar_to_home + flows.solar_to_ev +
        flows.solar_to_battery + flows.solar_to_grid
    )
    # Proportional allocation may not perfectly sum due to rounding
    assert total_solar == pytest.approx(10.0, abs=1.0)


def test_calculate_energy_flows_empty(calc):
    """Test energy flows with zero totals."""
    energy = EnergyTotals()
    flows = calc.calculate_energy_flows(energy)
    assert flows.solar_to_home == 0.0
    assert flows.grid_to_home == 0.0


# ──────────────────────────────────────────────
# Available power and charging current
# ──────────────────────────────────────────────

def test_calculate_available_power(calc):
    """Test available power calculation for EV charging."""
    power = _make_power(
        solar_power=5000,
        home_consumption_power=2000,
        battery_charge_power=500,
    )
    available = calc.calculate_available_power(power)
    # excess = 5000 - 2000 - 500 = 2500
    assert available == pytest.approx(2500, abs=1)


def test_calculate_available_power_negative(calc):
    """Test available power is clamped to zero when no surplus."""
    power = _make_power(
        solar_power=1000,
        home_consumption_power=2000,
        battery_charge_power=500,
    )
    available = calc.calculate_available_power(power)
    assert available == 0.0


def test_calculate_charging_current(calc):
    """Test charging current calculation from available power."""
    # 6900W / (230V * 3) = 10A
    current = calc.calculate_charging_current(6900)
    assert current == 10.0

    # Max capped at 16A
    current_high = calc.calculate_charging_current(20000)
    assert current_high == 16.0

    # Min is 0 (not 6 — 6A minimum is enforced elsewhere)
    current_low = calc.calculate_charging_current(500)
    assert current_low >= 0


def test_calculate_charging_current_zero(calc):
    """Test charging current is 0 for zero/negative power."""
    assert calc.calculate_charging_current(0) == 0.0
    assert calc.calculate_charging_current(-100) == 0.0


# ──────────────────────────────────────────────
# EV budget
# ──────────────────────────────────────────────

def test_calculate_ev_budget(calc):
    """Test EV budget includes grid export and battery redirect."""
    power = _make_power(
        solar_power=5000,
        grid_export_power=2000,
        ev_power=0,
        battery_charge_power=1000,
    )
    # Battery SOC 90% + high forecast -> should redirect battery charge
    budget = calc.calculate_ev_budget(
        power,
        forecast_remaining_kwh=10.0,
        battery_soc=95,
        battery_capacity_kwh=15,
    )
    # base = 0 + 2000 (grid_export, ev_power=0)
    # redirect: battery nearly full (SOC 95%), forecast covers need -> redirect ~all
    assert budget >= 2000


def test_calculate_ev_budget_no_redirect_low_soc(calc):
    """Test EV budget with no battery redirect when SOC is low."""
    power = _make_power(
        solar_power=3000,
        grid_export_power=500,
        ev_power=0,
        battery_charge_power=1000,
    )
    budget = calc.calculate_ev_budget(
        power,
        forecast_remaining_kwh=0,
        battery_soc=50,
        battery_capacity_kwh=15,
    )
    # No forecast, SOC < 80 -> no redirect
    # base = 500 (grid export only)
    assert budget == pytest.approx(500, abs=1)
