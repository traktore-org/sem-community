"""#825 — publish the number HA's Energy Dashboard is actually showing.

`sensor.sem_daily_home_energy` EXCLUDES the EV by design. HA's Energy
Dashboard "Home" figure includes it — individually-tracked devices are drawn
as a slice of that total, not subtracted from it. Both are correct; they are
not the same question, and SEM published nothing that answered HA's version
of it. So the only comparison a user could make was the wrong one, and it
looked like a bug every single time:

  * #802 (FENECON + Wattpilot): house tile 672 W beside a 10.3 kW session
    while the dashboard total read 10.94 kW. Filed as "values are off from
    Energy Dashboard". The 10.3 kW "gap" was the car.
  * #628 (SMA + Garo): a month of investigation into a daily divergence, on
    an install that charges an EV, where nobody — us included — checked
    whether the two numbers meant the same thing.

SEM had the answer internally the whole time: `energy_calculator` already
computes `daily_home + daily_ev` for the autarky rate. It just never
published it.

The EV term MUST be the calendar-day mirror. `EV_CATEGORY` rolls at the
charge deadline (#279), so composing a midnight row out of a deadline row is
the bug class closed in #703/#704 — and this sensor is a midnight row by
definition.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EV_CATEGORY,
    MIDNIGHT_EV_CATEGORY,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
    SEMData,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager

DAY = date(2026, 8, 17)


def _calc(**rows):
    calc = EnergyCalculator({"update_interval": 10}, TimeManager(MagicMock()))
    for key, kwh in rows.items():
        calc._daily_accumulators[f"{key}_{DAY}"] = kwh
    return calc


@pytest.mark.unit
class TestTheTotalIsHomePlusTheCar:

    def test_it_adds_the_car_back_in(self):
        """@jappish84's 17 Aug: SEM home 17.4, HA 71.6. If the car took the
        difference, these are two right answers to two questions."""
        calc = _calc(home=17.4, **{MIDNIGHT_EV_CATEGORY: 54.2})
        assert calc.daily_total_consumption(DAY) == pytest.approx(71.6)

    def test_no_car_means_the_two_agree(self):
        """On an install without a wallbox — the maintainer's own, which is
        why this never showed up here — home IS the total."""
        calc = _calc(home=17.17, **{MIDNIGHT_EV_CATEGORY: 0.0})
        assert calc.daily_total_consumption(DAY) == pytest.approx(17.17)

    def test_an_empty_day_is_zero_not_an_error(self):
        assert _calc().daily_total_consumption(DAY) == 0.0

    def test_it_uses_the_calendar_day_mirror_not_the_deadline_row(self):
        """#279's EV row rolls at the charge deadline; #703/#704 is what
        composing a midnight row out of it costs. Give the two rows
        different values and the midnight one must win."""
        calc = _calc(home=10.0, **{MIDNIGHT_EV_CATEGORY: 4.0, EV_CATEGORY: 99.0})
        assert calc.daily_total_consumption(DAY) == pytest.approx(14.0)


@pytest.mark.unit
class TestItReachesTheUser:

    def test_the_totals_carry_it(self):
        e = EnergyTotals(daily_home=17.4, daily_total_consumption=71.6)
        assert e.daily_total_consumption == 71.6

    def test_it_is_published_to_the_dashboard(self):
        data = SEMData(energy=EnergyTotals(
            daily_home=17.4, daily_total_consumption=71.6)).to_dict()
        assert data["daily_home_energy"] == 17.4
        assert data["daily_total_consumption"] == 71.6

    def test_there_is_a_sensor_for_it(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "sensor.py").read_text()
        assert 'key="daily_total_consumption"' in src, (
            "the number exists but no entity publishes it — which is exactly "
            "the state that cost #628 a month"
        )

    def test_the_calculator_fills_it(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent / "coordinator"
               / "energy_calculator.py").read_text()
        assert "energy.daily_total_consumption" in src, (
            "nothing assigns the row, so the sensor would publish 0.0 forever"
        )

    def test_both_entities_are_named_in_every_language(self):
        """A sensor whose name only exists in English is not reachable for
        most of the people this is meant to help."""
        import json
        from pathlib import Path
        root = Path(__file__).resolve().parent.parent
        missing = []
        for f in sorted((root / "translations").glob("*.json")):
            names = json.loads(f.read_text(encoding="utf-8")).get(
                "entity", {}).get("sensor", {})
            if "daily_total_consumption" not in names:
                missing.append(f.name)
        assert not missing, f"no entity name for the new sensor in: {missing}"
