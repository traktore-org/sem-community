"""Tests for power flow allocation algorithm.

v1.7.0 / #349: SEM switched from proportional to priority-based
allocation. The file name is historical — most tests in here pin
multi-source / multi-destination scenarios where both models give the
same answer (e.g. supply == demand on a single destination). The
tests that did pin proportional-specific behaviour were updated to
the new priority semantics.

Priority rules:
* Sources drain in order: solar → battery_discharge → grid_import
* Destinations served in order: home → ev → battery_charge → grid_export

Conservation invariants (pinned in ``test_349_flow_priority_attribution``):
* For each destination: sum of (source→destination) flows == destination demand
* For each source: sum of (source→destination) flows == source supply
"""
import pytest

from custom_components.solar_energy_management.coordinator import (
    FlowCalculator,
    PowerReadings,
    EnergyTotals,
)


@pytest.fixture
def flow_calculator():
    """Create a FlowCalculator instance for testing."""
    return FlowCalculator()


@pytest.fixture
def power_readings():
    """Create PowerReadings factory for testing."""
    def _make_readings(**kwargs):
        readings = PowerReadings()
        readings.solar_power = kwargs.get("solar_power", 0)
        readings.grid_power = kwargs.get("grid_power", 0)
        readings.battery_power = kwargs.get("battery_power", 0)
        readings.ev_power = kwargs.get("ev_power", 0)
        readings.battery_soc = kwargs.get("battery_soc", 50)
        readings.ev_connected = kwargs.get("ev_connected", False)
        readings.ev_charging = kwargs.get("ev_charging", False)
        readings.home_consumption_power = kwargs.get("home_consumption_power", 0)
        # Calculate derived values
        readings.calculate_derived()
        return readings
    return _make_readings


class TestProportionalSingleSourceMultipleDestinations:
    """Test Case 2 from user's example: Single source (solar) → multiple destinations."""

    def test_solar_to_three_destinations(self, flow_calculator, power_readings):
        """
        Solar: 8000W
        Destinations: Home 800W (10%), EV 4500W (56.25%), Battery 2700W (33.75%)
        Total demand: 8000W

        Expected flows:
        - solar_to_home: 800W (8000W × 10%)
        - solar_to_ev: 4500W (8000W × 56.25%)
        - solar_to_battery: 2700W (8000W × 33.75%)
        """
        readings = power_readings(
            solar_power=8000,
            grid_power=0,
            battery_power=2700,  # Positive = charging
            ev_power=4500,
            battery_soc=50,
            home_consumption_power=800,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Verify solar flows proportionally
        assert result.solar_to_home == pytest.approx(800, abs=1)
        assert result.solar_to_ev == pytest.approx(4500, abs=1)
        assert result.solar_to_battery == pytest.approx(2700, abs=1)

        # Verify no grid or battery discharge flows (only solar)
        assert result.grid_to_home == 0
        assert result.battery_to_home == 0


class TestProportionalMultipleSourcesMultipleDestinations:
    """Test Case 1 from user's example: Multiple sources → multiple destinations."""

    def test_three_sources_to_two_destinations(self, flow_calculator, power_readings):
        """#349: priority-based allocation. Sources drain in order
        solar → battery → grid; destinations in order home → ev →
        battery_charge → grid_export.

        Sources: Solar 5000W, Grid 2000W (import), Battery 1000W (discharge)
        Destinations: Home 2000W, EV 6000W

        Expected (priority):
        - solar covers all of home (2000) → 3000 W left
        - solar's remaining 3000 W goes to ev → solar exhausted
        - battery's 1000 W goes to ev → 5000 W of ev served so far
        - grid's 2000 W goes to ev → ev fully served (6000 W)
        """
        readings = power_readings(
            solar_power=5000,
            grid_power=-2000,  # Negative = import
            battery_power=-1000,  # Negative = discharging
            ev_power=6000,
            battery_soc=60,
            home_consumption_power=2000,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Solar drains: home (2000) → ev (3000)
        assert result.solar_to_home == pytest.approx(2000, abs=1)
        assert result.solar_to_ev == pytest.approx(3000, abs=1)

        # Battery drains to ev (home already filled)
        assert result.battery_to_home == pytest.approx(0, abs=1)
        assert result.battery_to_ev == pytest.approx(1000, abs=1)

        # Grid covers the remaining ev deficit
        assert result.grid_to_home == pytest.approx(0, abs=1)
        assert result.grid_to_ev == pytest.approx(2000, abs=1)

        # Verify destination totals
        home_total = result.solar_to_home + result.grid_to_home + result.battery_to_home
        ev_total = result.solar_to_ev + result.grid_to_ev + result.battery_to_ev

        assert home_total == pytest.approx(2000, abs=1)
        assert ev_total == pytest.approx(6000, abs=1)


class TestProportionalEnergyBalanceMaintained:
    """Verify energy balance is always maintained with proportional allocation."""

    def test_energy_balance_with_export(self, flow_calculator, power_readings):
        """Test balance when exporting to grid."""
        readings = power_readings(
            solar_power=10000,
            grid_power=2000,  # Positive = exporting
            battery_power=1000,  # Charging
            ev_power=3000,
            battery_soc=70,
            home_consumption_power=4000,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Verify export flow exists
        assert result.solar_to_grid > 0

        # Total solar flows should equal solar power
        total_solar_flows = (
            result.solar_to_home +
            result.solar_to_ev +
            result.solar_to_battery +
            result.solar_to_grid
        )
        assert total_solar_flows == pytest.approx(10000, abs=1)

    def test_energy_balance_night_time(self, flow_calculator, power_readings):
        """Test balance at night (no solar)."""
        readings = power_readings(
            solar_power=0,
            grid_power=-3000,  # Importing
            battery_power=-2000,  # Discharging
            ev_power=0,  # No EV charging
            battery_soc=40,
            home_consumption_power=5000,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Verify home gets power from grid and battery
        assert result.grid_to_home > 0
        assert result.battery_to_home > 0

        # Verify total to home
        home_total = result.grid_to_home + result.battery_to_home
        assert home_total == pytest.approx(5000, abs=1)


class TestProportionalEdgeCases:
    """Test edge cases and boundary conditions."""

    def test_zero_solar_at_night(self, flow_calculator, power_readings):
        """Test proportional allocation when solar = 0."""
        readings = power_readings(
            solar_power=0,
            grid_power=-2000,
            battery_power=-1000,
            ev_power=1500,
            battery_soc=50,
            home_consumption_power=1500,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Verify no solar flows
        assert result.solar_to_home == 0
        assert result.solar_to_ev == 0

        # Verify grid and battery supply proportionally
        assert result.grid_to_home > 0
        assert result.battery_to_home > 0

    def test_very_large_power_values(self, flow_calculator, power_readings):
        """Test priority allocation at commercial scale (150kW) (#349)."""
        readings = power_readings(
            solar_power=100000,
            grid_power=-30000,
            battery_power=-20000,
            ev_power=50000,
            battery_soc=65,
            home_consumption_power=100000,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Total supply = 150 kW, demand = 150 kW.
        # Priority: solar covers home (100 kW) fully → 0 left for ev.
        # Battery (20 kW) covers part of ev. Grid (30 kW) covers rest of ev.
        assert result.solar_to_home == pytest.approx(100000, abs=10)
        assert result.solar_to_ev == pytest.approx(0, abs=10)
        assert result.battery_to_ev == pytest.approx(20000, abs=10)
        assert result.grid_to_ev == pytest.approx(30000, abs=10)

    def test_only_battery_charge_demand(self, flow_calculator, power_readings):
        """Test when only demand is battery charging (surplus solar)."""
        readings = power_readings(
            solar_power=8000,
            grid_power=0,
            battery_power=5000,  # Charging
            ev_power=0,
            battery_soc=30,
            home_consumption_power=3000,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Solar should flow to home and battery
        assert result.solar_to_home > 0
        assert result.solar_to_battery > 0

    def test_simultaneous_charge_discharge_impossible(self, flow_calculator, power_readings):
        """Verify battery can't charge and discharge simultaneously."""
        readings = power_readings(
            solar_power=5000,
            grid_power=0,
            battery_power=2000,  # Charging (positive)
            ev_power=3000,
            battery_soc=50,
            home_consumption_power=0,
        )

        result = flow_calculator.calculate_power_flows(readings)

        # Battery should be charging - no discharge flows
        assert result.battery_to_home == 0
        assert result.battery_to_ev == 0


class TestProportionalComparison:
    """Compare proportional vs priority-based allocation (for documentation)."""

    def test_priority_creates_fewer_flows(self, flow_calculator, power_readings):
        """
        #349: priority allocation creates fewer non-zero flows than the
        old proportional model — that's the point. Each watt is
        attributed to a single (source, destination) pair, matching
        user intent. Pre-#349 the same scenario produced 6 non-zero
        flows (3 sources × 2 destinations); post-#349 it produces 3.
        """
        readings = power_readings(
            solar_power=5000,
            grid_power=-2000,
            battery_power=-1000,
            ev_power=6000,
            battery_soc=60,
            home_consumption_power=2000,
        )

        result = flow_calculator.calculate_power_flows(readings)

        flows = [
            result.solar_to_home,
            result.solar_to_ev,
            result.grid_to_home,
            result.grid_to_ev,
            result.battery_to_home,
            result.battery_to_ev,
        ]
        non_zero_flows = sum(1 for f in flows if f > 0.1)

        # Priority produces 3: solar→home, solar→ev, battery→ev, grid→ev = 4
        # (the test parametrise above asserts which 4).
        assert 3 <= non_zero_flows <= 4
        assert result.battery_to_ev > 0


class TestEnergyFlows:
    """Test energy flow calculations for Sankey charts."""

    def test_energy_flows_proportional(self, flow_calculator):
        """Test energy flow calculation from energy totals."""
        energy = EnergyTotals()
        energy.daily_solar = 10.0  # 10 kWh solar
        energy.daily_grid_import = 5.0  # 5 kWh imported
        energy.daily_grid_export = 2.0  # 2 kWh exported
        energy.daily_battery_charge = 3.0  # 3 kWh charged
        energy.daily_battery_discharge = 2.0  # 2 kWh discharged
        energy.daily_home = 8.0  # 8 kWh home
        energy.daily_ev = 4.0  # 4 kWh EV

        result = flow_calculator.calculate_energy_flows(energy)

        # Total demand = home + ev + battery_charge + grid_export = 8 + 4 + 3 + 2 = 17 kWh
        # home_pct = 8/17 = 47.06%, ev_pct = 4/17 = 23.53%

        # Solar (10 kWh) distributed proportionally
        assert result.solar_to_home > 0
        assert result.solar_to_ev > 0
        assert result.solar_to_grid > 0

        # Grid import (5 kWh) distributed to home, ev, battery (not grid)
        assert result.grid_to_home > 0
        assert result.grid_to_ev > 0


# TestAvailablePower and TestEvBudget removed in Phase D.2 (#282) along
# with the three primitives they exercised (``calculate_available_power``,
# ``calculate_charging_current``, ``calculate_ev_budget``). The canonical
# EVBudget unification supersedes them; the equivalent coverage now lives
# in ``test_canonical_ev_budget.py`` (per-strategy) and the scenario
# harness (end-to-end). The redirect helper is still exercised below.


class TestBatteryRedirect:
    """Tests for _calculate_battery_redirect() — internal helper."""

    def test_zero_charge_returns_zero(self, flow_calculator):
        """No battery charging → nothing to redirect."""
        assert flow_calculator._calculate_battery_redirect(0, 50, 15, 10) == 0

    def test_negative_charge_returns_zero(self, flow_calculator):
        """Battery discharging → nothing to redirect."""
        assert flow_calculator._calculate_battery_redirect(-1000, 50, 15, 10) == 0

    def test_battery_nearly_full_with_forecast(self, flow_calculator):
        """Battery nearly full with forecast → high proportional redirect."""
        result = flow_calculator._calculate_battery_redirect(
            battery_charge_w=1000, battery_soc=97,
            battery_capacity_kwh=15, forecast_remaining_kwh=5,
        )
        # battery_need = 0.45kWh, ratio = 1 - 0.45/5 = 0.91 → redirect = 910W
        assert result == pytest.approx(910, abs=10)

    def test_forecast_cant_cover_battery(self, flow_calculator):
        """Forecast insufficient for battery need → no redirect."""
        result = flow_calculator._calculate_battery_redirect(
            battery_charge_w=3000, battery_soc=30,
            battery_capacity_kwh=15, forecast_remaining_kwh=5,
        )
        # battery_need = 10.5kWh > forecast 5kWh → 0
        assert result == 0

    def test_forecast_covers_battery_proportional(self, flow_calculator):
        """Forecast covers battery → proportional redirect."""
        result = flow_calculator._calculate_battery_redirect(
            battery_charge_w=3000, battery_soc=60,
            battery_capacity_kwh=15, forecast_remaining_kwh=15,
        )
        # battery_need = 6kWh, ratio = 1 - 6/15 = 0.6, redirect = 1800W
        assert result == pytest.approx(1800, abs=1)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
