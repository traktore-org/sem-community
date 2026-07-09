"""#573 — lifetime solar production sensor.

Reporter (@hrdilshan, Deye/Sunsynk): SEM's Monthly/Yearly production
(57.2 kWh) didn't match the inverter's ``TotalActiveProduction`` lifetime
counter (71.2 kWh). Monthly/Yearly are period-scoped and correctly cannot
include production from before SEM/HA was tracking. SEM already tracks a
lifetime accumulator (seeded from the hardware counter, reconciled
upward) — it just wasn't exposed. This surfaces it as
``sensor.sem_lifetime_solar_yield_energy`` so users have an apples-to-apples
figure that matches the inverter.
"""
from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings

_NOW = datetime(2026, 7, 9, 12, 0, 0)
_DT = "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"


@pytest.fixture
def calc():
    return EnergyCalculator({"system_size_kwp": 10}, MagicMock())


def _power(solar=0.0):
    return PowerReadings(
        solar_power=solar,
        grid_import_power=0,
        grid_export_power=0,
        home_consumption_power=0,
        ev_power=0,
        battery_charge_power=0,
        battery_discharge_power=0,
        battery_power=0,
        battery_soc=50,
    )


@pytest.mark.unit
class TestLifetimeSolarSensor:

    def test_main_path_exposes_lifetime_solar(self, calc):
        """calculate_energy() surfaces the lifetime accumulator on energy."""
        # Simulate a hardware-seeded lifetime (the reporter's 71.2 kWh).
        calc._lifetime_accumulators["lifetime_solar"] = 71.2
        with patch(_DT) as dt:
            dt.now.return_value = _NOW
            energy = calc.calculate_energy(_power(solar=0))
        assert energy.lifetime_solar == pytest.approx(71.2)

    def test_throttled_path_exposes_lifetime_solar(self, calc):
        """The gap/throttle path (_build_current_totals) exposes it too."""
        calc._lifetime_accumulators["lifetime_solar"] = 71.2
        energy = calc._build_current_totals(date(2026, 7, 9), "2026_7", "2026")
        assert energy.lifetime_solar == pytest.approx(71.2)

    def test_to_dict_carries_lifetime_solar_key(self, calc):
        """The coordinator payload exposes lifetime_solar_yield_energy for
        the sensor (state_class TOTAL_INCREASING)."""
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
            EnergyTotals,
        )
        data = SEMData()
        data.energy = EnergyTotals()
        data.energy.lifetime_solar = 71.2
        payload = data.to_dict()
        assert payload["lifetime_solar_yield_energy"] == pytest.approx(71.2)

    def test_lifetime_distinct_from_period_totals(self, calc):
        """Lifetime > yearly > monthly when tracking started mid-year:
        the exact scenario the reporter saw (lifetime 71.2, period 57.2)."""
        calc._lifetime_accumulators["lifetime_solar"] = 71.2
        calc._yearly_accumulators["solar_2026"] = 57.2
        calc._monthly_accumulators["solar_2026_7"] = 57.2
        with patch(_DT) as dt:
            dt.now.return_value = _NOW
            energy = calc.calculate_energy(_power(solar=0))
        assert energy.lifetime_solar == pytest.approx(71.2)
        assert energy.yearly_solar == pytest.approx(57.2)
        assert energy.monthly_solar == pytest.approx(57.2)
        assert energy.lifetime_solar > energy.yearly_solar

    def test_lifetime_survives_restore(self, calc):
        """Lifetime accumulator persists (get_state/restore_state) so the
        sensor is durable across restarts."""
        calc._lifetime_accumulators["lifetime_solar"] = 71.2
        state = calc.get_state()
        fresh = EnergyCalculator({"system_size_kwp": 10}, MagicMock())
        fresh.restore_state(state)
        assert fresh._get_lifetime("solar") == pytest.approx(71.2)
