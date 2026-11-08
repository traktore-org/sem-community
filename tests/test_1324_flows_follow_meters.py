"""(#1324) The day's flow split adds up to the meter-backed daily totals.

PROD, 08.11.2026 evening: the integrated split read home 14.28 kWh against
a metered 18.79, and 0.17 kWh battery-to-grid while the export meter counted
0.06 kWh all day. The totals balance (41.6 kWh in, 41.6 out); the split is
only how they divide.
"""
from __future__ import annotations

import ast
from datetime import date
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    MIDNIGHT_EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FLOW_COLS,
    FLOW_ROWS,
    fit_flows_to_totals,
)
from custom_components.solar_energy_management.coordinator.types import (
    ChargerEnergyFlows,
    EnergyFlows,
    StringEnergy,
)

ROOT = Path(__file__).resolve().parent.parent

PROD_FLOWS = dict(
    solar_to_home=4.41, solar_to_ev=0.0, solar_to_battery=8.31, solar_to_grid=0.08,
    grid_to_home=1.67, grid_to_ev=5.61, grid_to_battery=7.27,
    battery_to_home=8.2, battery_to_ev=0.41, battery_to_grid=0.17,
)
PROD_TOTALS = {
    "solar": 13.9, "grid_import": 16.68, "battery_discharge": 11.02,
    "home": 18.79, "ev": 7.46, "battery_charge": 15.29, "grid_export": 0.06,
}

ROW_ATTRS = {
    "solar": ("solar_to_home", "solar_to_ev", "solar_to_battery", "solar_to_grid"),
    "grid_import": ("grid_to_home", "grid_to_ev", "grid_to_battery"),
    "battery_discharge": ("battery_to_home", "battery_to_ev", "battery_to_grid"),
}
COL_ATTRS = {
    "home": ("solar_to_home", "grid_to_home", "battery_to_home"),
    "ev": ("solar_to_ev", "grid_to_ev", "battery_to_ev"),
    "battery_charge": ("solar_to_battery", "grid_to_battery"),
    "grid_export": ("solar_to_grid", "battery_to_grid"),
}


def _sum(f, attrs):
    return sum(getattr(f, a) for a in attrs)


@pytest.mark.unit
def test_prod_day_split_adds_up_to_the_meters():
    fitted = fit_flows_to_totals(EnergyFlows(**PROD_FLOWS), PROD_TOTALS)
    for name in FLOW_ROWS:
        assert _sum(fitted, ROW_ATTRS[name]) == pytest.approx(PROD_TOTALS[name], abs=0.01), name
    for name in FLOW_COLS:
        assert _sum(fitted, COL_ATTRS[name]) == pytest.approx(PROD_TOTALS[name], abs=0.01), name
    # The battery cannot have sent more to the grid than the meter exported.
    assert fitted.battery_to_grid <= 0.06
    # A flow that never ran is not invented.
    assert fitted.solar_to_ev == 0.0


@pytest.mark.unit
def test_shares_keep_their_order_and_flows_stay_positive():
    fitted = fit_flows_to_totals(EnergyFlows(**PROD_FLOWS), PROD_TOTALS)
    for attr in PROD_FLOWS:
        assert getattr(fitted, attr) >= 0.0
    assert fitted.battery_to_home > fitted.solar_to_home > fitted.grid_to_home


@pytest.mark.unit
def test_per_charger_follows_the_fleet_and_strings_stay_as_measured():
    flows = EnergyFlows(**PROD_FLOWS)
    flows.per_charger = {
        "a": ChargerEnergyFlows(solar_to_ev=0.0, grid_to_ev=4.0, battery_to_ev=0.41),
        "b": ChargerEnergyFlows(solar_to_ev=0.0, grid_to_ev=1.61, battery_to_ev=0.0),
    }
    flows.per_string = {"s1": StringEnergy(energy_kwh=12.8)}
    fitted = fit_flows_to_totals(flows, PROD_TOTALS)
    for attr in ("solar_to_ev", "grid_to_ev", "battery_to_ev"):
        assert sum(getattr(c, attr) for c in fitted.per_charger.values()) == pytest.approx(
            getattr(fitted, attr), abs=0.01)
    assert fitted.per_string["s1"].energy_kwh == 12.8
    # The input is not changed: the integrator keeps its raw sums.
    assert flows.grid_to_home == 1.67


def _calc(backed):
    calc = EnergyCalculator.__new__(EnergyCalculator)
    today = date(2026, 11, 8)
    calc.booking_day = today
    calc._counter_backed = set(backed)
    calc._daily_accumulators = {
        f"solar_{today}": 13.9, f"grid_import_{today}": 16.68,
        f"battery_discharge_{today}": 11.02, f"home_{today}": 18.79,
        f"{MIDNIGHT_EV_CATEGORY}_{today}": 7.46, f"ev_{today}": 99.0,
        f"battery_charge_{today}": 15.29, f"grid_export_{today}": 0.06,
    }
    return calc


@pytest.mark.unit
def test_totals_only_when_home_is_the_meters_balance():
    assert _calc({"grid_import", "grid_export"}).calendar_day_totals() is None
    totals = _calc({"home", "grid_import"}).calendar_day_totals()
    assert totals == PROD_TOTALS  # the EV column is the midnight mirror, not the EV day


@pytest.mark.unit
def test_coordinator_publishes_the_fitted_copy_right_after_integrating():
    src = (ROOT / "coordinator" / "coordinator.py").read_text()
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", getattr(n.func, "attr", "")) == "fit_flows_to_totals"]
    integrate = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
                 and getattr(n.func, "attr", "") == "integrate_energy_flows"]
    assert len(calls) == 1 and len(integrate) == 1
    assert 0 < calls[0].lineno - integrate[0].lineno < 12
