"""#1243 — the daily cap cut the day but the month kept the kWh.

The cap at the end of ``calculate_energy`` wrote the day alone. The month,
year and lifetime kept what the cap removed, so the day read less than the
sum it belonged to. The cap now takes the removed kWh from all four.
"""
from __future__ import annotations

from datetime import date

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager
from unittest.mock import MagicMock

DAY = date(2026, 10, 28)
NOON = "2026-10-28 12:00:00"
MONTH = f"{DAY.year}_{DAY.month}"
YEAR = str(DAY.year)
CAPACITY = 10.0     # kWh → a 30 kWh battery cap
KWP = 10.0          # kWp → a 160 kWh solar cap
EARLIER = 70.0      # kWh the month, year and lifetime hold from other days


def _calc() -> EnergyCalculator:
    return EnergyCalculator(
        {"update_interval": 60, "battery_capacity_kwh": CAPACITY,
         "system_size_kwp": KWP},
        TimeManager(MagicMock()))


def _cycle(calc: EnergyCalculator, power: PowerReadings):
    calc._last_update = None
    return calc.calculate_energy(
        power, FlowCalculator().calculate_power_flows(power))


def _seed(calc: EnergyCalculator, category: str, today_kwh: float) -> None:
    calc._daily_accumulators[f"{category}_{DAY}"] = today_kwh
    calc._monthly_accumulators[f"{category}_{MONTH}"] = EARLIER + today_kwh
    calc._yearly_accumulators[f"{category}_{YEAR}"] = EARLIER + today_kwh
    calc._lifetime_accumulators[f"lifetime_{category}"] = EARLIER + today_kwh


def _rows(calc: EnergyCalculator, category: str) -> tuple:
    return (calc._daily_accumulators.get(f"{category}_{DAY}", 0.0),
            calc._monthly_accumulators.get(f"{category}_{MONTH}", 0.0),
            calc._yearly_accumulators.get(f"{category}_{YEAR}", 0.0),
            calc._lifetime_accumulators.get(f"lifetime_{category}", 0.0))


def _power(category: str) -> PowerReadings:
    if category == "solar":
        p = PowerReadings(solar_power=4000.0, battery_power=0.0, grid_power=3500.0)
    elif category == "battery_charge":
        p = PowerReadings(solar_power=4000.0, battery_power=1500.0, grid_power=2000.0)
    else:
        p = PowerReadings(solar_power=0.0, battery_power=-1500.0, grid_power=-1000.0)
    p.calculate_derived()
    p.home_consumption_power = 500.0 if category != "battery_discharge" else 2500.0
    return p


CEILING = {"solar": KWP * 16, "battery_charge": CAPACITY * 3,
           "battery_discharge": CAPACITY * 3}


@pytest.mark.unit
@pytest.mark.parametrize("category", ["solar", "battery_charge", "battery_discharge"])
class TestTheCapMovesEveryPeriod:
    def test_the_longer_rows_lose_what_the_day_lost(self, category):
        with freeze_time(NOON):
            calc = _calc()
            _seed(calc, category, CEILING[category] + 12.0)
            _cycle(calc, _power(category))
            day, month, year, lifetime = _rows(calc, category)
        assert day == pytest.approx(CEILING[category])
        assert month == pytest.approx(EARLIER + day)
        assert year == pytest.approx(EARLIER + day)
        assert lifetime == pytest.approx(EARLIER + day)

    def test_a_cut_is_taken_once_not_every_cycle(self, category):
        with freeze_time(NOON):
            calc = _calc()
            _seed(calc, category, CEILING[category] + 12.0)
            for _ in range(20):
                _cycle(calc, _power(category))
            day, month, year, lifetime = _rows(calc, category)
        assert day == pytest.approx(CEILING[category])
        assert month == pytest.approx(EARLIER + day)
        assert year == pytest.approx(EARLIER + day)
        assert lifetime == pytest.approx(EARLIER + day)

    def test_a_day_under_the_ceiling_is_left_alone(self, category):
        with freeze_time(NOON):
            calc = _calc()
            _seed(calc, category, 5.0)
            _cycle(calc, _power(category))
            day, month, year, lifetime = _rows(calc, category)
        assert month == pytest.approx(EARLIER + day)
        assert year == pytest.approx(EARLIER + day)
        assert lifetime == pytest.approx(EARLIER + day)

    def test_a_longer_row_never_goes_below_zero(self, category):
        with freeze_time(NOON):
            calc = _calc()
            _seed(calc, category, CEILING[category] + 12.0)
            calc._monthly_accumulators[f"{category}_{MONTH}"] = 3.0
            _cycle(calc, _power(category))
        assert calc._monthly_accumulators[f"{category}_{MONTH}"] == 0.0
