"""(#1321) What SEM paid per bought kWh against the hours' average price.

Insights shows both on a dynamic tariff: paid = import cost ÷ bought kWh;
the hours' price = the price time-weighted over the period. On a fixed
tariff there is nothing to compare, so neither is published.
"""
from __future__ import annotations

from datetime import date

import pytest

from custom_components.solar_energy_management.coordinator import energy_calculator as ec
from custom_components.solar_energy_management.coordinator.types import EnergyTotals


def _book(c, today, mk, yk, rate, hours, kwh):
    c._accumulate_cost(ec.PRICE_HOURS, today, mk, yk, hours)
    c._accumulate_cost(ec.PRICE_X_HOURS, today, mk, yk, rate * hours)
    c._accumulate_cost("cost_import", today, mk, yk, rate * kwh)


def _real(mode):
    from unittest.mock import MagicMock
    return ec.EnergyCalculator({"tariff_mode": mode}, MagicMock())


@pytest.mark.unit
@pytest.mark.parametrize("mode, published", [("dynamic", True), ("static", False)])
def test_buying_in_cheap_hours_pays_less_than_the_hours_average(mode, published):
    from homeassistant.util import dt as dt_util
    c = _real(mode)
    today = dt_util.now().date()
    mk, yk = f"{today.year}_{today.month}", str(today.year)
    _book(c, today, mk, yk, rate=0.10, hours=4, kwh=8.0)    # bought cheap
    _book(c, today, mk, yk, rate=0.40, hours=4, kwh=0.0)    # dear hours, nothing bought
    energy = EnergyTotals(daily_grid_import=8.0, monthly_grid_import=8.0,
                          yearly_grid_import=8.0)
    costs = c.calculate_costs(energy)
    assert costs.price_comparison is published
    if published:
        assert costs.daily_avg_price_paid == pytest.approx(0.10)
        assert costs.daily_avg_price_hours == pytest.approx(0.25)
        assert costs.monthly_avg_price_hours == pytest.approx(0.25)
    else:
        assert costs.daily_avg_price_paid is None and costs.daily_avg_price_hours is None


@pytest.mark.unit
def test_calculate_costs_publishes_only_on_a_dynamic_tariff():
    from .ast_contracts import reads_attribute
    src_fn = ec.EnergyCalculator.calculate_costs
    assert reads_attribute(src_fn, "self", "config")


@pytest.mark.unit
def test_the_rows_are_pruned_with_the_cost_rows():
    # same day/month/year suffix as every cost row, so rollover drops them
    c = _real("dynamic")
    today = date(2026, 11, 13)
    c._accumulate_cost(ec.PRICE_HOURS, today, "2026_11", "2026", 1.0)
    assert f"{ec.PRICE_HOURS}_{today}" in c._daily_cost_accumulators
    assert f"{ec.PRICE_HOURS}_2026_11" in c._monthly_cost_accumulators
