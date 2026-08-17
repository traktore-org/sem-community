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
        """HA-PROD 2026-06-01 second sample: a complete flow picture.
        Pure-flow formula:
        own_supply  = solar_to_home + battery_to_home (+ EV slices)
        grid_supply = grid_to_home + grid_to_ev
        total       = own + grid
        autarky     = own / total

        Numbers from PROD's actual flow accumulators:
            solar_to_home   = 4.277
            battery_to_home = 2.607
            grid_to_home    = 3.164
            grid_to_ev      = 6.225  (pre-sunrise EV charging)
        ⇒ own=6.884, grid=9.389, total=16.273 → autarky 42.3 %"""
        calc = self._calc()
        energy = EnergyTotals(daily_home=10.32, daily_ev=0.0)
        flows = EnergyFlows(
            solar_to_home=4.277, solar_to_ev=0.0,
            battery_to_home=2.607, battery_to_ev=0.0,
            grid_to_home=3.164, grid_to_ev=6.225,
            grid_to_battery=0.112,
        )
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        # autarky = 6.884 / 16.273 = 42.3 %
        assert metrics.autarky_rate == pytest.approx(42.3, abs=0.1)

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

    def test_autarky_100_when_all_consumption_from_own(self):
        """All consumption from solar + battery; grid only charged
        battery → autarky pinned at 100 %."""
        calc = self._calc()
        energy = EnergyTotals(daily_home=5.0, daily_ev=0.0)
        flows = EnergyFlows(
            solar_to_home=3.0, battery_to_home=2.0,
            grid_to_home=0.0, grid_to_ev=0.0,
            grid_to_battery=2.0,
        )
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        assert metrics.autarky_rate == pytest.approx(100.0)

    def test_autarky_zero_when_no_own_supply(self):
        """All consumption from grid → autarky 0 %."""
        calc = self._calc()
        flows = EnergyFlows(
            solar_to_home=0.0, battery_to_home=0.0,
            grid_to_home=5.0, grid_to_ev=2.0,
        )
        metrics = calc.calculate_performance(PowerReadings(), EnergyTotals(), flows)
        assert metrics.autarky_rate == 0.0

    def test_autarky_temporal_alignment_with_ev(self):
        """Pure-flow formula handles the EV-sunrise-reset case
        correctly: pre-sunrise grid → EV is included in both numerator's
        denominator (via grid_to_ev) and the consumption total. The
        legacy formula would have used daily_ev=0 (sunrise reset) and
        flow_grid_to_ev=6 (calendar reset), drowning autarky."""
        calc = self._calc()
        # Simulate pre-sunrise EV charging: 6 kWh grid → EV before today's
        # sunrise window, plus 4 kWh of solar → home after sunrise.
        flows = EnergyFlows(
            solar_to_home=4.0, solar_to_ev=0.0,
            battery_to_home=0.0, battery_to_ev=0.0,
            grid_to_home=0.0, grid_to_ev=6.0,
        )
        # daily_ev is sunrise-reset = 0; daily_home is calendar = 4.
        # The pure-flow formula doesn't care — uses flows only.
        energy = EnergyTotals(daily_home=4.0, daily_ev=0.0)
        metrics = calc.calculate_performance(PowerReadings(), energy, flows)
        # total=10, own=4, autarky=40 %.
        assert metrics.autarky_rate == pytest.approx(40.0, abs=0.1)

    def test_autarky_battery_to_home_counted_as_own(self):
        """battery_to_home counts as own supply — battery is "mine"."""
        calc = self._calc()
        flows = EnergyFlows(
            solar_to_home=0.0, battery_to_home=8.0,
            grid_to_home=2.0, grid_to_ev=0.0,
        )
        metrics = calc.calculate_performance(PowerReadings(), EnergyTotals(), flows)
        # total=10, own=8, autarky=80 %.
        assert metrics.autarky_rate == pytest.approx(80.0, abs=0.1)

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
