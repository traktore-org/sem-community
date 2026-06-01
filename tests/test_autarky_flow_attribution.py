"""Tests for v1.7.0 flow-attributed autarky + cost-savings (#PROD-2026-06-01).

Background. SEM v1.6.x pinned ``autarky_rate`` at 0 % on HA-PROD
whenever the battery had been overnight-grid-charged: the formula
``(home - daily_grid_import) / home`` treats every imported kWh as a
penalty against own-supply, but the grid-to-battery slice doesn't
displace any home consumption. Symmetric bug in the cost-savings
accumulator inside ``calculate_energy``.

v1.7.0 fixes both by piping flow-attributed values from
``FlowCalculator`` into the metric calculators.
"""
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyFlows,
    EnergyTotals,
    PowerFlows,
    PowerReadings,
)


class TestAutarkyFlowAttribution:
    """``calculate_performance`` autarky uses
    ``energy_flows.grid_to_home + grid_to_ev`` when supplied."""

    def _calc(self):
        from unittest.mock import MagicMock
        return EnergyCalculator(config={}, time_manager=MagicMock())

    def test_prod_scenario_autarky_no_longer_zero(self):
        """HA-PROD 2026-06-01: home 9.25 kWh, grid_import 9.38 kWh,
        of which 2.9 went to battery. Pre-fix the formula gave
        autarky=0 % because raw grid_import > home. With flow
        attribution the battery-bound slice is excluded."""
        calc = self._calc()
        energy = EnergyTotals(
            daily_home=9.25, daily_ev=0.0,
            daily_grid_import=9.38, daily_grid_export=0.12,
            daily_battery_charge=2.9, daily_battery_discharge=3.42,
            daily_solar=6.18,
        )
        flows = EnergyFlows(
            grid_to_home=6.48, grid_to_ev=0.0,
            grid_to_battery=2.9,
        )
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        # autarky = (9.25 - 6.48) / 9.25 = 29.9 %
        assert metrics.autarky_rate == pytest.approx(29.9, abs=0.1)

    def test_legacy_call_still_works_no_flows(self):
        """Two-arg call without ``energy_flows`` → legacy formula."""
        calc = self._calc()
        energy = EnergyTotals(
            daily_home=10.0, daily_ev=0.0,
            daily_grid_import=3.0, daily_solar=8.0,
        )
        metrics = calc.calculate_performance(PowerReadings(), energy)
        # legacy: (10 - 3) / 10 = 70 %
        assert metrics.autarky_rate == pytest.approx(70.0, abs=0.1)

    def test_autarky_100_when_no_grid_to_consumption(self):
        """All grid import went to battery — autarky pinned at 100 %."""
        calc = self._calc()
        energy = EnergyTotals(
            daily_home=5.0, daily_ev=0.0,
            daily_grid_import=2.0, daily_solar=8.0,
        )
        flows = EnergyFlows(grid_to_home=0.0, grid_to_ev=0.0, grid_to_battery=2.0)
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        assert metrics.autarky_rate == pytest.approx(100.0)

    def test_autarky_clamps_to_zero_on_negative(self):
        """Edge: if grid_to_home > home (sensor lag, rounding), clamp to 0."""
        calc = self._calc()
        energy = EnergyTotals(daily_home=5.0, daily_ev=0.0)
        flows = EnergyFlows(grid_to_home=7.0, grid_to_ev=0.0)
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        assert metrics.autarky_rate == 0.0

    def test_autarky_includes_ev_grid_consumption(self):
        """EV charged from grid counts as grid_to_consumption too."""
        calc = self._calc()
        energy = EnergyTotals(
            daily_home=5.0, daily_ev=10.0,
            daily_grid_import=12.0,
        )
        flows = EnergyFlows(
            grid_to_home=4.0, grid_to_ev=6.0, grid_to_battery=2.0,
        )
        # total_consumption=15, grid_to_consumption=10 → autarky=33.3 %
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        assert metrics.autarky_rate == pytest.approx(33.3, abs=0.1)

    def test_self_consumption_unaffected_by_flows(self):
        """self_consumption_rate is (solar - export) / solar; flow
        attribution should not change it."""
        calc = self._calc()
        energy = EnergyTotals(daily_solar=10.0, daily_grid_export=2.0)
        m_with = calc.calculate_performance(
            PowerReadings(), energy, EnergyFlows(grid_to_home=0.0),
        )
        m_without = calc.calculate_performance(PowerReadings(), energy)
        assert m_with.self_consumption_rate == pytest.approx(80.0)
        assert m_without.self_consumption_rate == pytest.approx(80.0)


class TestCostSavingsFlowAttribution:
    """``calculate_energy`` solar-self-consumption savings use
    flow-attributed solar_to_home + solar_to_ev when supplied."""

    def _calc(self):
        from unittest.mock import MagicMock
        calc = EnergyCalculator(config={}, time_manager=MagicMock())
        calc._import_rate = 0.25
        return calc

    def _make_power(self, **kw):
        p = PowerReadings()
        for k, v in kw.items():
            setattr(p, k, v)
        return p

    def test_flow_path_credits_solar_during_grid_to_battery(self):
        """The motivating case: grid charges battery (4 kW) while
        solar covers home (500 W). Legacy heuristic gives 0 savings
        (500 − 4000 < 0); flow path credits the 500 W correctly."""
        from datetime import date
        calc_legacy = self._calc()
        calc_flow = self._calc()
        # Configure for a 10 s update interval so the first-cycle
        # branch in ``calculate_energy`` derives a known kWh delta
        # without us having to fake datetime.
        calc_legacy.config["update_interval"] = 10
        calc_flow.config["update_interval"] = 10
        power = self._make_power(
            solar_power=4500.0, home_consumption_power=500.0,
            grid_import_power=4000.0, battery_charge_power=8000.0,
            battery_discharge_power=0.0, ev_power=0.0,
        )
        flows = PowerFlows(
            solar_to_home=500.0, solar_to_ev=0.0,
            grid_to_home=0.0, grid_to_ev=0.0,
            grid_to_battery=4000.0,
        )
        calc_legacy.calculate_energy(power)
        calc_flow.calculate_energy(power, flows)
        today_key = f"cost_savings_{date.today()}"
        legacy = calc_legacy._daily_cost_accumulators.get(today_key, 0.0)
        flowed = calc_flow._daily_cost_accumulators.get(today_key, 0.0)
        # legacy = 0 (the bug — 500 − 4000 clamps to 0).
        assert legacy == 0.0
        # flow-attributed > 0 (500 W × 10s / 3600 / 1000 × 0.25 ≈ 0.000347).
        assert flowed > 0.0
        # Sanity: the flow value matches the expected math.
        expected = 500.0 * (10.0 / 3600.0) / 1000.0 * 0.25
        assert flowed == pytest.approx(expected, rel=1e-2)

    def test_legacy_fallback_works_without_flows(self):
        """No ``power_flows`` → subtraction heuristic still runs."""
        from datetime import date
        calc = self._calc()
        calc.config["update_interval"] = 10
        power = self._make_power(
            solar_power=5000.0, home_consumption_power=2000.0,
            grid_import_power=0.0, battery_charge_power=3000.0,
            battery_discharge_power=0.0, ev_power=0.0,
        )
        calc.calculate_energy(power)
        today_key = f"cost_savings_{date.today()}"
        savings = calc._daily_cost_accumulators.get(today_key, 0.0)
        # legacy: home + ev − import − discharge = 2000 − 0 − 0 = 2000 W
        # → 2000 × 10/3600/1000 × 0.25 ≈ 0.00139
        expected = 2000.0 * (10.0 / 3600.0) / 1000.0 * 0.25
        assert savings == pytest.approx(expected, rel=1e-2)
