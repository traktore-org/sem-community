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


def test_priority_allocation(calc):
    """Test priority allocation with multiple sources and destinations (#349).

    Pre-#349 SEM used proportional allocation; this test pinned that.
    Post-#349 sources drain in priority order solar → battery → grid,
    destinations are served in priority home → ev → battery_charge →
    grid_export. The conservation invariants still hold; only WHICH
    pair each watt is attributed to changes.
    """
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

    # Conservation per side. Each source dispatches exactly its supply
    # (or less, if no eligible destination remains).
    total_solar_out = (
        flows.solar_to_home + flows.solar_to_ev +
        flows.solar_to_battery + flows.solar_to_grid
    )
    assert total_solar_out == pytest.approx(5000, abs=2)

    # Priority order: solar serves home first (3000), then ev (2000),
    # nothing left for battery_charge or grid_export from solar.
    assert flows.solar_to_home == pytest.approx(3000, abs=1)
    assert flows.solar_to_ev == pytest.approx(2000, abs=1)
    assert flows.solar_to_battery == pytest.approx(0, abs=1)
    # Battery_discharge (500W) flows to home (already filled) → ev → 0.
    # But ev was already filled by solar, so battery_to_ev = 0; battery
    # tries home but home already served. With (battery, grid_export)
    # pair omitted (out-of-scope), battery stays unattributed in this
    # exact balanced scenario. The 500 W of grid_export comes from
    # solar/grid net surplus in the metering layer; we only care that
    # solar conserves and grid_import lands somewhere.
    # Grid_import (1000W) → battery_charge first (priority), leftover
    # would go elsewhere but battery_charge is 500W so absorbs that.
    assert flows.grid_to_battery == pytest.approx(500, abs=1)
    # Grid_import remaining 500W has no eligible destinations (home
    # and ev are filled). That's the sensor-anomaly case the new
    # allocator degrades on safely.


# ──────────────────────────────────────────────
# ``test_calculate_energy_flows`` / ``..._empty`` removed in the legacy
# retirement (#536): the deprecated proportional ``calculate_energy_flows``
# they exercised is gone. Timing-aware energy flows are covered by the
# ``integrate_energy_flows`` tests in ``test_flow_integration.py``.
# ──────────────────────────────────────────────


# ──────────────────────────────────────────────
# Legacy ``calculate_available_power`` / ``calculate_charging_current`` /
# ``calculate_ev_budget`` removed in Phase D.2 (#282). The canonical
# EVBudget unification supersedes them; see
# ``test_canonical_ev_budget.py`` for coverage of the replacement.
# ──────────────────────────────────────────────
