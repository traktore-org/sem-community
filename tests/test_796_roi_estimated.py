"""#796 — a guessed install date must not present as a measurement.

When install-date autodetection has not (yet) succeeded,
`calculate_costs` falls back to `dt_util.now().year` — "installed
January 1 of this year" — and the age-dependent ROI figures
(annual savings, payback) are published exactly like measured ones.
The figures may stay (a degraded answer beats none, and detection
retries every cycle), but they must CARRY the flag so the sensors can
say so. Detection succeeding clears it.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    EnergyTotals,
)


def _calc(install_year=None) -> EnergyCalculator:
    calc = EnergyCalculator(
        {
            "electricity_import_rate": 0.30,
            "electricity_export_rate": 0.08,
            "system_investment_cost": 10000,
        },
        MagicMock(),
    )
    calc._install_year_decimal = install_year
    # Enough lifetime savings that the age-dependent branch computes.
    calc._accumulated_savings = 2000.0
    return calc


def _costs(calc):
    return calc.calculate_costs(EnergyTotals())


class TestTheGuessCarriesItsFlag:

    def test_undetected_install_date_marks_roi_estimated(self) -> None:
        costs = _costs(_calc(install_year=None))
        assert costs.roi_install_date_estimated is True
        # The figures themselves still compute — degraded, not absent.
        assert costs.roi_annual_savings > 0

    def test_a_detected_date_publishes_as_measured(self) -> None:
        costs = _costs(_calc(install_year=2024.5))
        assert costs.roi_install_date_estimated is False

    def test_the_flag_reaches_the_published_result(self) -> None:
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        data = SEMData()
        data.costs = _costs(_calc(install_year=None))
        assert data.to_dict()["roi_install_date_estimated"] is True


class TestTheFlagRidesTheSensors:

    def _attrs(self, key, estimated):
        from unittest.mock import MagicMock
        from homeassistant.components.sensor import SensorEntityDescription
        from custom_components.solar_energy_management.sensor import (
            SEMSolarSensor,
        )
        coordinator = MagicMock()
        coordinator.data = {
            key: 1234, "roi_install_date_estimated": estimated,
        }
        sensor = SEMSolarSensor(
            coordinator=coordinator,
            description=SensorEntityDescription(key=key, name=key),
            entry_id="test_entry_id",
        )
        return sensor.extra_state_attributes

    @pytest.mark.parametrize("key", ["roi_payback_years", "roi_annual_savings"])
    def test_age_dependent_roi_sensors_carry_the_flag(self, key) -> None:
        assert self._attrs(key, True)["install_date_estimated"] is True
        assert self._attrs(key, False)["install_date_estimated"] is False

    def test_other_sensors_do_not_grow_the_attribute(self) -> None:
        assert "install_date_estimated" not in self._attrs("solar_power", True)
