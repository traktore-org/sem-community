"""(#1382) A daily counter never steps back within its day.

PROD 23.11.2026 10:27:49 UTC: the daily grid import read 11.45 kWh, then
11.40; the house row (9.46 → 9.42) and grid to house (9.23 → 9.18) with it.
The integrator books power between two meter steps and ran 0.05 kWh ahead of
a lagging meter; the counter correction then pulled the row back. The
recorder reads a step back as a reset and counts the day again. Ten such
steps on PROD from 20.11 to 25.11, after the first #1382 fix (one base per
day), which had left this cause open.

The rule: a correction may hold a row at what was published, never set it
below; ahead of the meter it waits until the meter passes it. The fitted
flows follow the same rule, and their record survives a restart.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    hold_published_flows,
)
from custom_components.solar_energy_management.coordinator.types import EnergyFlows

from .ast_contracts import calls

TODAY = date(2026, 11, 23)
MONTH, YEAR = "2026_11", "2026"
IMPORT_METER = "sensor.power_meter_bezug"
KEY = f"grid_import_{TODAY}"


def _state(value):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": "kWh"})


def _calc(states):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    calc = EnergyCalculator(config={}, time_manager=MagicMock())
    calc.configure_meter_counters(hass, {"grid_import": [IMPORT_METER]}, True)
    return calc


def _cycle(calc, integrated_kwh):
    """One cycle: snapshot as published, the integrator books, the meter corrects."""
    calc._note_published_rows()
    calc._daily_accumulators[KEY] = integrated_kwh
    calc._reconcile_metered_energy("grid_import", TODAY, MONTH, YEAR)
    return calc._daily_accumulators[KEY]


@pytest.mark.unit
class TestTheRowHolds:
    def test_prod_23_11_the_row_does_not_go_back(self):
        # The meter's day started at 10000.00 when the row stood at 0.
        states = {IMPORT_METER: _state(10000.00)}
        calc = _calc(states)
        assert _cycle(calc, 0.0) == pytest.approx(0.0)
        # Up to 10:27:29: row and meter agree at 11.43.
        states[IMPORT_METER] = _state(10011.43)
        assert _cycle(calc, 11.43) == pytest.approx(11.43)
        # 10:27:39: the integrator books ahead of the lagging meter (11.45),
        # inside the drift band: published as 11.45.
        assert _cycle(calc, 11.45) == pytest.approx(11.45)
        # 10:27:49: the meter still 11.43, the integrator at 11.50. Before:
        # corrected to 11.43 — back from the published 11.45. Now it holds.
        assert _cycle(calc, 11.50) == pytest.approx(11.45)
        # While the meter lags it may rise inside the drift band, never fall.
        assert _cycle(calc, 11.47) >= 11.45
        # The meter passes it: the row follows the meter again.
        states[IMPORT_METER] = _state(10011.52)
        assert _cycle(calc, 11.46) == pytest.approx(11.52)

    def test_the_month_and_year_move_with_the_day(self):
        states = {IMPORT_METER: _state(10000.0)}
        calc = _calc(states)
        _cycle(calc, 0.0)
        states[IMPORT_METER] = _state(10011.43)
        _cycle(calc, 11.43)
        calc._monthly_accumulators[f"grid_import_{MONTH}"] = 100.0
        month_before = 100.0
        _cycle(calc, 11.50)
        # the day held at 11.43: the month gave back only this cycle's +0.07
        assert calc._daily_accumulators[KEY] == pytest.approx(11.43)
        assert calc._monthly_accumulators.get(f"grid_import_{MONTH}", 0.0) == pytest.approx(
            month_before + (11.43 - 11.50))

    def test_without_a_published_value_the_meter_wins(self):
        """The first cycle of a day (or a direct call) has nothing to hold."""
        calc = EnergyCalculator(config={}, time_manager=MagicMock())
        assert calc._not_below_published("x_2026-11-23", 1.0) == 1.0


@pytest.mark.unit
class TestTheFlowsHold:
    def test_a_fit_that_drifts_down_holds(self):
        flows = EnergyFlows(grid_to_home=7.79, solar_to_home=1.0)
        flows, record = hold_published_flows(flows, None, TODAY)
        drift = EnergyFlows(grid_to_home=7.78, solar_to_home=1.02)
        out, record = hold_published_flows(drift, record, TODAY)
        assert out.grid_to_home == pytest.approx(7.79)
        assert out.solar_to_home == pytest.approx(1.02)
        assert drift.grid_to_home == pytest.approx(7.78), "the input is not touched"

    def test_a_new_day_starts_fresh(self):
        _, record = hold_published_flows(EnergyFlows(grid_to_home=9.0), None, TODAY)
        out, _ = hold_published_flows(EnergyFlows(grid_to_home=0.1), record,
                                      date(2026, 11, 24))
        assert out.grid_to_home == pytest.approx(0.1)

    def test_the_record_survives_a_restart(self):
        calc = EnergyCalculator(config={}, time_manager=MagicMock())
        _, calc.published_flows = hold_published_flows(
            EnergyFlows(grid_to_home=8.18), None, TODAY)
        fresh = EnergyCalculator(config={}, time_manager=MagicMock())
        fresh.restore_state(calc.get_state())
        out, _ = hold_published_flows(EnergyFlows(grid_to_home=8.05),
                                      fresh.published_flows, TODAY)
        assert out.grid_to_home == pytest.approx(8.18)


def test_every_row_correction_goes_through_the_floor():
    """Every meter correction that may move a row down takes the floor first.
    The EV row is the exception by design (#1049): its counter owns the day,
    and a high read the charger later takes back must come out."""
    assert calls(EnergyCalculator._reconcile_metered_energy, "_not_below_published")
    assert calls(EnergyCalculator._reconcile_home_energy, "_not_below_published")

