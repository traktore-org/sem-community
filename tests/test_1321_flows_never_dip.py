"""(#1321) A published daily flow counter never steps down inside a day.

.175, 18.11.2026: flow_grid_to_home_energy flipped between 7.85 and 7.27
every few minutes while the grid-import meter only rose. The published
split is fitted to the meters only while the home row is counter-backed;
the cycles where it is not publish the raw sums, 0.5 kWh lower. A dip reads
as a counter reset downstream and was booked as 6 kWh of use.
"""
from __future__ import annotations

from datetime import date

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import EnergyFlows


def _calc() -> FlowCalculator:
    return FlowCalculator.__new__(FlowCalculator)


def _init(calc: FlowCalculator, day: date) -> FlowCalculator:
    calc._current_date = day
    calc._published_floor = {}
    return calc


def test_a_lower_value_holds_the_day_high():
    calc = _init(_calc(), date(2026, 11, 18))
    day = date(2026, 11, 18)
    high = calc.hold_published(EnergyFlows(grid_to_home=7.85, solar_to_home=0.7), day)
    low = calc.hold_published(EnergyFlows(grid_to_home=7.27, solar_to_home=0.7), day)
    assert high.grid_to_home == 7.85
    assert low.grid_to_home == 7.85
    assert calc.hold_published(EnergyFlows(grid_to_home=7.9), day).grid_to_home == 7.9


def test_a_new_day_starts_from_zero():
    calc = _init(_calc(), date(2026, 11, 17))
    calc.hold_published(EnergyFlows(grid_to_home=18.0), date(2026, 11, 17))
    out = calc.hold_published(EnergyFlows(grid_to_home=1.1), date(2026, 11, 18))
    assert out.grid_to_home == 1.1
