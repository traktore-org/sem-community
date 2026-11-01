"""#1291 — the yearly seed asks the recorder the way the recorder allows.

``statistics_during_period`` is sync database work. The seed awaited it, so on
a real recorder the call failed, the error was caught and a new install
started its year at zero. The seed now goes through ``_recorder_stats``.
"""

import sys
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.tests import ast_contracts

from custom_components.solar_energy_management.coordinator import energy_calculator
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)


def _rows(first, last):
    return [{"start": "2026-01-01T00:00:00", "sum": first},
            {"start": "2026-08-01T00:00:00", "sum": last}]


def _calc():
    return EnergyCalculator(
        {"electricity_import_rate": 0.30, "electricity_export_rate": 0.08},
        MagicMock())


def test_the_seed_never_awaits_the_recorder_function_itself():
    fn = EnergyCalculator.seed_yearly_from_statistics
    assert not ast_contracts.calls(fn, "statistics_during_period")
    assert ast_contracts.calls(fn, "_recorder_stats")


@pytest.mark.asyncio
async def test_a_plain_recorder_function_seeds_the_year():
    """A real recorder function is sync; awaiting its dict raised TypeError."""
    calls = []

    def _stats(hass, start, end, ids, period, units, types):
        calls.append(set(ids))
        return {"sensor.solar_total": _rows(10.0, 510.0)}

    fake_mod = SimpleNamespace(statistics_during_period=_stats)
    ed = MagicMock()
    ed.solar_energy = "sensor.solar_total"
    ed.grid_import_energy = None
    ed.grid_export_energy = None
    ed.battery_charge_energy = None
    ed.battery_discharge_energy = None
    ed.device_consumption = []
    calc = _calc()
    with patch.dict(sys.modules, {
        "homeassistant.components.recorder": MagicMock(),
        "homeassistant.components.recorder.statistics": fake_mod,
    }):
        await calc.seed_yearly_from_statistics(MagicMock(), ed)
    assert calls, "the recorder was never asked"
    year = str(energy_calculator.dt_util.now().year)
    assert calc._yearly_accumulators.get(f"solar_{year}") == pytest.approx(500.0)
    assert calc._yearly_seeded is True
