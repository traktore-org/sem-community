"""#904 — the plan overlay converts block power with the learned ladder,
never by dividing by one bucket's W/A.

PROD 02.09 20:30: plan block 5262 W; the overlay computed
``ceil(5262 / 389)`` = 14 A, because ``_ev_watts_per_amp()`` handed it the
16 A bucket's W/A (389 — a genuine car-side taper). PROD's own table says
14 A buys 8.7 kW. ``amps_that_fit`` on that table says 10 A (5.15 kW); the
slot guard already converts that way, the overlay did not.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    PlanGate,
    ev_overlay,
)

# PROD's learned table for the KEBA, 3-phase, 02.09 (W per A per setpoint).
PROD_TABLE = {8: 394.4, 10: 515.0, 12: 582.5, 14: 621.8, 16: 389.1}
NOMINAL = 690.0  # 3 × 230


def _in_block(power_w):
    return PlanGate(covered=True, in_block=True, block_power_w=power_w,
                    remaining_kwh=4.69)


@pytest.mark.unit
class TestTheOverlayWalksTheLadder:

    def test_prod_block_is_ten_amps_not_fourteen(self):
        wait, amps = ev_overlay(
            _in_block(5262.0), remaining_kwh=4.69, reachable=True,
            deadline_active=False, watts_per_amp=389.1,  # what PROD passed
            min_amps=6, max_amps=16, wpa_table=PROD_TABLE, nominal_wpa=NOMINAL,
        )
        assert wait is False
        assert amps == 10, "largest setpoint whose PREDICTED draw fits 5262 W"

    def test_the_single_number_is_only_a_fallback_without_a_table(self):
        # Legacy contract untouched when nothing has been learned yet.
        _, amps = ev_overlay(
            _in_block(5262.0), remaining_kwh=4.69, reachable=True,
            deadline_active=False, watts_per_amp=NOMINAL,
            min_amps=6, max_amps=16,
        )
        assert amps == 8  # ceil(5262 / 690)

    def test_a_block_the_ladder_cannot_fit_floors_at_min(self):
        _, amps = ev_overlay(
            _in_block(1000.0), remaining_kwh=1.0, reachable=True,
            deadline_active=False, watts_per_amp=NOMINAL,
            min_amps=6, max_amps=16, wpa_table=PROD_TABLE, nominal_wpa=NOMINAL,
        )
        assert amps == 6

    def test_never_above_the_charger_max(self):
        _, amps = ev_overlay(
            _in_block(20000.0), remaining_kwh=9.0, reachable=True,
            deadline_active=False, watts_per_amp=NOMINAL,
            min_amps=6, max_amps=16, wpa_table=PROD_TABLE, nominal_wpa=NOMINAL,
        )
        assert amps == 16
