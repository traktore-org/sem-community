"""#905 — a limit-driven DOWNWARD clamp lands in one cycle.

PROD 02.09 20:45: the slot guard said 10 A, the stability layer answered
"delta guard — holding 14A", then "ramping 12A", then "debounce guard —
holding 12A", then a dropout hold — 10 A reached the wire two minutes later,
while the billed 15-min average went 5.6 → 6.6 kW of a 6.0 limit. The shed
order (6 A) at 20:53 was smoothed the same way. Smoothing is right for the
car's sake on the way UP and on budget wobble; a limit is not a preference.
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
from custom_components.solar_energy_management.coordinator.decide import (
    clamp_to_peak_slot,
)

from .test_decide import _view as _decide_view


class _Adapter:
    def __init__(self, last_intent=ChargerIntent.CHARGE_AT_AMPS):
        self.last_intent = last_intent
        self.min_current_a = 6
        self.max_current_a = 16

    def actual_charging(self, power):
        return power.power_w > 500.0


def _view(*, inputs_degraded=False, night=True, power_w=8500.0, solar_w=0.0, cid="wb"):
    return ChargerView(
        power=ChargerPower(charger_id=cid, power_w=power_w, connected=True,
                           charging=True),
        energy=ChargerEnergy(charger_id=cid),
        mode="min_plus_solar",
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16},
        fleet=FleetContext(is_night=night, solar_w=solar_w, min_solar_w=200.0,
                           battery_soc=90.0, buffer_soc=70.0,
                           inputs_degraded=inputs_degraded),
    )


def _charge(amps, *, capped=False, cid="wb"):
    return ChargerDecision(
        charger_id=cid, mode="min_plus_solar",
        intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=amps,
        budget_w=amps * 600.0, reason=f"night: deadline floor {amps}A",
        capped_by_limit=capped,
    )


def _settle(st, amps, t=0.0, **view_kw):
    for i in range(6):
        st.filter(_charge(amps), _view(**view_kw), _Adapter(),
                  min_change_interval_s=0.0, now_ts=t + i)
    assert st._last_amps["wb"] == amps
    return t + 6


@pytest.mark.unit
class TestALimitClampLandsInOneCycle:

    def test_the_slot_guard_clamp_is_not_ramped(self):
        st = ChargeStability()
        t = _settle(st, 14)
        out = st.filter(_charge(10, capped=True), _view(), _Adapter(),
                        min_change_interval_s=30.0, now_ts=t + 1)
        assert out.intent is ChargerIntent.CHARGE_AT_AMPS
        assert out.commanded_amps == 10, "14 → 10 in ONE cycle, no 12 step"
        assert "limit clamp" in out.reason

    def test_the_clamp_is_not_debounced_either(self):
        st = ChargeStability()
        t = _settle(st, 14)
        # A change just happened; the debounce window is wide open.
        st._last_change_ts["wb"] = t
        out = st.filter(_charge(10, capped=True), _view(), _Adapter(),
                        min_change_interval_s=300.0, now_ts=t + 1)
        assert out.commanded_amps == 10

    def test_an_uncapped_target_still_ramps(self):
        # Today's behaviour, kept: budget wobble is smoothed.
        st = ChargeStability()
        t = _settle(st, 14)
        out = st.filter(_charge(10), _view(), _Adapter(),
                        min_change_interval_s=0.0, now_ts=t + 1)
        assert out.commanded_amps == 12
        assert "ramping" in out.reason

    def test_a_capped_target_above_the_last_value_still_ramps_up(self):
        # The bypass is for the DOWN direction only — the way back up after a
        # clamp stays gentle for the car.
        st = ChargeStability()
        t = _settle(st, 6)
        out = st.filter(_charge(12, capped=True), _view(), _Adapter(),
                        min_change_interval_s=0.0, now_ts=t + 1)
        assert out.commanded_amps == 8

    def test_a_degraded_hold_never_holds_above_a_capped_target(self):
        # 20:46:14: "inputs degraded — holding 12A" while the guard said 10.
        # The hold is a DAY device (#907) — settle by day with real sun.
        st = ChargeStability()
        t = _settle(st, 12, night=False, solar_w=3000.0, power_w=6900.0)
        out = st.filter(_charge(10, capped=True),
                        _view(inputs_degraded=True, night=False, solar_w=0.0,
                              power_w=6900.0),
                        _Adapter(), min_change_interval_s=30.0, now_ts=t + 1)
        assert out.commanded_amps == 10, out.reason


@pytest.mark.unit
class TestTheClampsStampTheFlag:

    def _mk(self, allowed_w, *, peak_state="normal", grid_import_w=0.0):
        v = _decide_view("min_plus_solar")
        f = v.fleet
        object.__setattr__(f, "peak_slot_allowed_w", allowed_w)
        object.__setattr__(f, "grid_import_w", grid_import_w)
        object.__setattr__(f, "peak_state", peak_state)
        return v

    def _charge16(self):
        return ChargerDecision(
            charger_id="ch1", mode="min_plus_solar",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=16,
            budget_w=11040.0, reason="deadline floor 16A",
        )

    def test_default_is_unflagged(self):
        assert ChargerDecision(charger_id="x", mode="m",
                               intent=ChargerIntent.IDLE).capped_by_limit is False

    def test_the_slot_guard_flags_its_clamp(self):
        out = clamp_to_peak_slot(self._charge16(), self._mk(3000.0))
        assert out.commanded_amps < 16
        assert out.capped_by_limit is True

    def test_no_clamp_no_flag(self):
        out = clamp_to_peak_slot(self._charge16(), self._mk(None))
        assert out.capped_by_limit is False
