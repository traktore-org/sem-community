"""#795 — a reconciliation delta is priced at the day it happened, not the
moment it was noticed.

`_reconcile_metered_energy` books the counter-vs-integrator drift into the
cost accumulators as `delta × rate`, with `rate` = the instantaneous tariff
of the cycle the reconciliation RUNS. The drift itself accumulated across
the day (cloud-poll dropouts, blind stretches), so on a dynamic tariff kWh
that flowed at 0.15 get priced at whatever spike is current — #416's class,
write-time attribution of an event-time quantity.

The honest price already exists in the accumulators themselves: today's
realized average, `daily_cost / daily_energy` for the same category — the
average of exactly what the live path booked all day. Static tariffs are
unchanged (realized == instantaneous); a day with no accumulation yet has
no realized average and keeps the instantaneous fallback. This also keeps
faith with #770 at the battery site: the day's realized savings rate IS
"the way the live path valued it", averaged.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)

D = date(2026, 8, 18)
MK, YK = "2026-08", "2026"


class _Counter:
    """A counter whose reading the test can move between cycles."""

    def __init__(self, value: float):
        self.value = value

    def state_for(self, _entity_id):
        st = Mock()
        st.state = str(self.value)
        st.attributes = {"unit_of_measurement": "kWh"}
        return st


def _calc(counter: _Counter, category: str) -> EnergyCalculator:
    calc = EnergyCalculator({"prefer_hardware_energy": True}, MagicMock())
    hass = MagicMock()
    hass.states.get = Mock(side_effect=counter.state_for)
    calc.configure_meter_counters(
        hass, {category: [f"sensor.p1_{category}"]}, True,
    )
    return calc


def _reconcile(calc, category, cost_key, rate):
    calc._reconcile_metered_energy(
        category, D, MK, YK, cost_key=cost_key, rate=rate,
    )


class TestDeltaPricedAtTheRealizedAverage:

    def test_the_regression_a_spike_does_not_reprice_the_day(self) -> None:
        # The day so far: 10 kWh imported, 1.50 CHF accumulated — the live
        # path priced the day at 0.15/kWh. The counter then reveals 2 kWh
        # the integrator missed while the CURRENT rate spikes to 0.32.
        counter = _Counter(100.0)
        calc = _calc(counter, "grid_import")
        calc._daily_accumulators[f"grid_import_{D}"] = 10.0
        calc._daily_cost_accumulators[f"cost_import_{D}"] = 1.50
        _reconcile(calc, "grid_import", "cost_import", 0.32)  # baseline cycle

        counter.value = 102.0                                 # +2 kWh drift
        _reconcile(calc, "grid_import", "cost_import", 0.32)

        booked = calc._daily_cost_accumulators[f"cost_import_{D}"]
        assert booked == pytest.approx(1.50 + 2.0 * 0.15)     # the day's rate
        assert booked != pytest.approx(1.50 + 2.0 * 0.32)     # NOT the spike

    def test_no_accumulation_yet_keeps_the_instantaneous_fallback(self) -> None:
        # Nothing integrated and nothing booked — no realized average
        # exists, the passed rate is the only information there is.
        counter = _Counter(50.0)
        calc = _calc(counter, "grid_import")
        _reconcile(calc, "grid_import", "cost_import", 0.30)  # baseline cycle

        counter.value = 53.0                                  # +3 kWh
        _reconcile(calc, "grid_import", "cost_import", 0.30)

        assert calc._daily_cost_accumulators[f"cost_import_{D}"] == (
            pytest.approx(3.0 * 0.30)
        )

    def test_a_downward_correction_removes_at_the_days_rate(self) -> None:
        # Export integrated 8 kWh at a realized 0.10; the meter proves only
        # 6 flowed. The 2 kWh removed give back what was booked for them —
        # 0.10 each — not the 0.25 of the correction moment.
        counter = _Counter(200.0)
        calc = _calc(counter, "grid_export")
        calc._daily_accumulators[f"grid_export_{D}"] = 6.0
        _reconcile(calc, "grid_export", "cost_export", 0.25)  # anchor at 6

        calc._daily_accumulators[f"grid_export_{D}"] = 8.0    # integrator ran on
        calc._daily_cost_accumulators[f"cost_export_{D}"] = 0.80
        _reconcile(calc, "grid_export", "cost_export", 0.25)  # target still 6

        assert calc._daily_accumulators[f"grid_export_{D}"] == pytest.approx(6.0)
        assert calc._daily_cost_accumulators[f"cost_export_{D}"] == (
            pytest.approx(0.80 - 2.0 * 0.10)
        )

    def test_a_static_tariff_is_unchanged(self) -> None:
        # realized == instantaneous → identical booking to the old code.
        counter = _Counter(100.0)
        calc = _calc(counter, "grid_import")
        calc._daily_accumulators[f"grid_import_{D}"] = 10.0
        calc._daily_cost_accumulators[f"cost_import_{D}"] = 3.0   # 0.30/kWh
        _reconcile(calc, "grid_import", "cost_import", 0.30)

        counter.value = 102.0
        _reconcile(calc, "grid_import", "cost_import", 0.30)

        assert calc._daily_cost_accumulators[f"cost_import_{D}"] == (
            pytest.approx(3.0 + 2.0 * 0.30)
        )
