"""#551 — hardware energy counters must be unit-converted when seeding.

Fronius Gen24/Verto lifetime energy sensors report **Wh**;
``seed_lifetime_from_hardware`` read the raw state as kWh, inflating the
lifetime accumulators ×1000. A 2-day-old install showed
``battery_cycles_estimated: 21350.7`` (real: ~21.35) and a health score
pinned at the 70% floor. The same class hit the EV daily-energy
reconciliation read.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)


def _state(value, unit):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _hass_with(states: dict):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    return hass


def _ed():
    return SimpleNamespace(
        solar_energy="sensor.pv_e",
        grid_import_energy="sensor.gi_e",
        grid_export_energy="sensor.ge_e",
        battery_charge_energy="sensor.bc_e",
        battery_discharge_energy="sensor.bd_e",
        device_consumption=[],
    )


@pytest.mark.unit
class TestUnitAwareCounterReads:
    def test_energy_state_kwh_units(self):
        f = EnergyCalculator._energy_state_kwh
        assert f(_state(320262, "Wh")) == pytest.approx(320.262)
        assert f(_state(320.262, "kWh")) == pytest.approx(320.262)
        assert f(_state(0.320262, "MWh")) == pytest.approx(320.262)
        # unknown/missing unit keeps the previous assume-kWh behavior
        assert f(_state(42, None)) == pytest.approx(42)
        assert f(_state("garbage", "kWh")) == 0.0

    def test_fronius_wh_lifetime_seed_produces_sane_cycles(self):
        """THE reporter scenario: Fronius Wh lifetime counters. Before the
        fix the battery accumulators seeded ×1000 too large → 21,350
        'cycles' on a 2-day-old install."""
        calc = EnergyCalculator(config={}, time_manager=MagicMock())
        # Real-world-ish Fronius values, all in Wh
        states = {
            "sensor.pv_e": _state(8_500_000, "Wh"),   # 8.5 MWh lifetime solar
            "sensor.gi_e": _state(2_100_000, "Wh"),
            "sensor.ge_e": _state(3_900_000, "Wh"),
            "sensor.bc_e": _state(320_262, "Wh"),     # ~320 kWh charged
            "sensor.bd_e": _state(320_262, "Wh"),
        }
        calc.seed_lifetime_from_hardware(_hass_with(states), _ed())
        charge = calc._get_lifetime("battery_charge")
        discharge = calc._get_lifetime("battery_discharge")
        assert charge == pytest.approx(320.262, rel=1e-3)
        assert discharge == pytest.approx(320.262, rel=1e-3)
        # cycles as the coordinator computes them: throughput/2 ÷ capacity
        cycles = round(((charge + discharge) / 2) / 15.0, 1)
        assert cycles == pytest.approx(21.4, abs=0.1)  # not 21,350!

    def test_kwh_counters_unchanged(self):
        """Existing kWh installs (Huawei PROD) seed identically to before."""
        calc = EnergyCalculator(config={}, time_manager=MagicMock())
        states = {
            "sensor.pv_e": _state(12_000, "kWh"),
            "sensor.gi_e": _state(3_000, "kWh"),
            "sensor.ge_e": _state(5_000, "kWh"),
            "sensor.bc_e": _state(2_400, "kWh"),
            "sensor.bd_e": _state(2_200, "kWh"),
        }
        calc.seed_lifetime_from_hardware(_hass_with(states), _ed())
        assert calc._get_lifetime("solar") == pytest.approx(12_000)
        assert calc._get_lifetime("battery_charge") == pytest.approx(2_400)

    def test_corrupted_wh_seed_self_heals_downward(self):
        """Installs that seeded pre-fix carry ×1000 accumulators — the
        seeder must re-seed DOWNWARD from the corrected counters."""
        calc = EnergyCalculator(config={}, time_manager=MagicMock())
        # simulate the corrupted persisted state (Wh read as kWh)
        calc._lifetime_accumulators.update({
            "lifetime_solar": 8_500_000.0,
            "lifetime_grid_import": 2_100_000.0,
            "lifetime_grid_export": 3_900_000.0,
            "lifetime_battery_charge": 320_262.0,
            "lifetime_battery_discharge": 320_262.0,
        })
        states = {
            "sensor.pv_e": _state(8_500_000, "Wh"),
            "sensor.gi_e": _state(2_100_000, "Wh"),
            "sensor.ge_e": _state(3_900_000, "Wh"),
            "sensor.bc_e": _state(320_262, "Wh"),
            "sensor.bd_e": _state(320_262, "Wh"),
        }
        calc.seed_lifetime_from_hardware(_hass_with(states), _ed())
        assert calc._get_lifetime("battery_charge") == pytest.approx(320.262, rel=1e-3)
        assert calc._get_lifetime("solar") == pytest.approx(8_500.0, rel=1e-3)

