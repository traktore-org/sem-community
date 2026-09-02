"""#907 — the #818 degraded-inputs hold may not resurrect a night idle.

PROD 02.09 21:26: the night top-up reached its target, decide() said idle
every cycle, and "inputs degraded (sensor unavailable) — holding 8A" rewrote
that idle into a charge on every modbus dropout. The reconciler's 4-cycle
idle grace reset each time, the stop was never issued, and the car drew from
the grid for seven minutes past its target in a mode that never grid-charges
at night. The hold exists for the DAY surplus path — a blind cycle reads
"no sun" and would wind the car down. A night verdict comes from the
charger's own counter and the planner; no blind sensor can move it.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charge_stability import (
    ChargeStability,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)


class _Adapter:
    def __init__(self, last_intent=ChargerIntent.CHARGE_AT_AMPS):
        self.last_intent = last_intent
        self.min_current_a = 6
        self.max_current_a = 16

    def actual_charging(self, power):
        return power.power_w > 500.0


def _view(*, night, inputs_degraded, power_w=3100.0, solar_w=0.0, cid="wb"):
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w, connected=True,
                           charging=power_w > 500),
        energy=ChargerEnergy(charger_id=cid),
        mode="min_plus_solar",
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=night, solar_w=solar_w, min_solar_w=200.0,
                           battery_soc=85.0, buffer_soc=75.0,
                           inputs_degraded=inputs_degraded),
    )


def _charge(amps=8, cid="wb"):
    return ChargerDecision(
        charger_id=cid, mode="min_plus_solar",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=4000.0, reason="min_plus_solar night: deadline floor 8A",
    )


def _target_reached(cid="wb"):
    return ChargerDecision(
        charger_id=cid, mode="min_plus_solar",
        intent=ChargerIntent.IDLE, commanded_amps=0, budget_w=0.0,
        reason="min_plus_solar night: target reached (remaining=0.00 kWh)",
    )


def _settle_night(st, amps=8, t=0.0):
    for i in range(6):
        st.filter(_charge(amps), _view(night=True, inputs_degraded=False),
                  _Adapter(), min_change_interval_s=0.0, now_ts=t + i)
    assert st._last_amps["wb"] == amps
    return t + 6


@pytest.mark.unit
class TestANightIdleIsNeverHeld:

    def test_target_reached_passes_through_a_blind_cycle(self):
        st = ChargeStability()
        t = _settle_night(st)
        out = st.filter(_target_reached(),
                        _view(night=True, inputs_degraded=True),
                        _Adapter(), now_ts=t + 1)
        assert out.intent is ChargerIntent.IDLE, out.reason
        assert "holding" not in out.reason

    def test_the_planners_charge_still_passes_through_blind(self):
        # No hold, no rewrite: the night planner's own amps are honoured.
        st = ChargeStability()
        t = _settle_night(st)
        out = st.filter(_charge(10), _view(night=True, inputs_degraded=True),
                        _Adapter(), min_change_interval_s=0.0, now_ts=t + 1)
        assert out.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "inputs degraded" not in out.reason

    def test_the_day_hold_is_untouched(self):
        # The #818 contract by day stays exactly as test_818 pins it.
        st = ChargeStability()
        for i in range(6):
            st.filter(_charge(10), _view(night=False, inputs_degraded=False,
                                         power_w=4000.0, solar_w=3000.0),
                      _Adapter(), min_change_interval_s=0.0, now_ts=float(i))
        out = st.filter(
            ChargerDecision(charger_id="wb", mode="min_plus_solar",
                            intent=ChargerIntent.IDLE, reason="surplus 0W"),
            _view(night=False, inputs_degraded=True, power_w=4000.0),
            _Adapter(), now_ts=7.0)
        assert out.intent is ChargerIntent.CHARGE_AT_AMPS
        assert "inputs degraded" in out.reason
