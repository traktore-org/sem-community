"""EV flap fix (2026-07-10, Guido / KEBA P30): a UDP power blip must not
collapse the EV budget.

Root cause (proven): the KEBA charging-power sensor blips to ~0 for one
cycle while the car is really drawing 10 kW. ``ev_power`` feeds the home
energy balance (``home = solar + grid_import − ev − …``). While the fast
grid meter still shows the import, a 0 ev-read spikes ``home`` → the EV
self-consumption surplus crashes below the battery-assist solar gate
(1200 W) → the budget collapses to 0 → decide returns IDLE → the
reconciler drops the contactor → the ~15 s on/off flap.

Fix: median-of-3 on the fleet ``ev_power`` in the reader
(``SensorReader._smooth_ev_power``) kills the single-cycle blip at the
source. These tests drive the REAL home-balance (``PowerReadings.
calculate_derived``) and budget (``battery_assist_budget_w``) code.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.coordinator.decide import (
    battery_assist_budget_w,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerPower, ChargerEnergy, ChargerView, FleetContext,
)

SOLAR = 7700.0
DRAW = 10450.0          # car at 16 A, 3φ
# grid with the car drawing: import = draw + base_home − solar
BASE_HOME = 1355.0
GRID = SOLAR - BASE_HOME - DRAW    # = −4105 (import), SEM sign: neg = import


def _reader():
    hass = MagicMock()
    hass.states = MagicMock()
    return SensorReader(hass, {})


@pytest.mark.unit
class TestEvPowerStabilizer:
    def test_single_cycle_blip_is_filtered(self):
        r = _reader()
        seq = [DRAW, DRAW, 0.0, DRAW, DRAW]   # one UDP 0-blip mid-charge
        out = [r._smooth_ev_power(v) for v in seq]
        # warm-up (first two) pass raw; the blip at index 2 is filtered.
        assert out[2] == DRAW, f"blip not filtered: {out}"

    def test_real_stop_is_tracked(self):
        r = _reader()
        for v in (DRAW, DRAW, DRAW):
            r._smooth_ev_power(v)
        # a genuine stop (2+ zero cycles) must come through within one cycle
        assert r._smooth_ev_power(0.0) == DRAW      # 1st zero still held
        assert r._smooth_ev_power(0.0) == 0.0       # 2nd zero → real stop


def _budget_for(ev_reading):
    """Run the REAL home-balance + budget for a given ev sensor reading,
    with the grid meter fixed at the true (car-drawing) import."""
    p = PowerReadings(
        solar_power=SOLAR, grid_power=GRID, battery_power=0.0,
        battery_soc=100.0, ev_power=ev_reading,
    )
    p.calculate_derived()
    view = ChargerView(
        power=ChargerPower(charger_id="keba", power_w=ev_reading,
                           connected=True, charging=ev_reading > 500),
        energy=ChargerEnergy(charger_id="keba"), mode="min_plus_solar",
        config={"ev_min_current": 8, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(
            is_night=False, solar_w=SOLAR, min_solar_w=1000.0,
            battery_soc=100.0, buffer_soc=70.0, priority_soc=30.0,
            auto_start_soc=90.0, home_w=p.home_consumption_power,
            battery_assist_min_surplus_w=1200.0,
            battery_assist_max_power_w=11000.0,
        ),
    )
    return battery_assist_budget_w(view)


@pytest.mark.unit
class TestBudgetStableThroughBlip:
    def test_raw_blip_would_collapse_budget(self):
        # Documents the bug: a raw 0 ev-read (grid still shows the draw)
        # collapses the budget — this is what reached ``decide`` pre-fix.
        assert _budget_for(DRAW) > 5000      # accurate cycle: healthy budget
        assert _budget_for(0.0) == 0.0       # raw blip: budget collapses

    def test_smoothed_blip_keeps_budget_healthy(self):
        # With the reader's median-of-3, the blip is filtered to DRAW before
        # it hits the balance, so the budget stays healthy across the blip.
        r = _reader()
        raw_seq = [DRAW, DRAW, 0.0, DRAW]
        budgets = []
        for raw in raw_seq:
            smoothed = r._smooth_ev_power(raw)
            budgets.append(_budget_for(smoothed))
        # the blip cycle (index 2) must NOT collapse to 0
        assert budgets[2] > 5000, (
            f"budget collapsed on the smoothed blip cycle: {budgets}"
        )
