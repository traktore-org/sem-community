"""#1069 — battery and monthly peak must respect the grid limit.

A review of peak and load management (08.10.2026) found six faults that
exist on develop without any new feature. Each class below is one of them,
written from the reviewer's own scenario.
"""
from __future__ import annotations

from types import SimpleNamespace

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

# 6 A on 3 × 230 V, nameplate (no learned table): 4140 W.
_MIN_W = 6 * 3 * 230.0
# The user's own delays — deliberately NOT the defaults (60 / 180 s), so a
# constant hiding in the code cannot pass these tests.
_ENABLE_S = 90.0
_DISABLE_S = 240.0
_HYST_KW = 0.3
# The 3-sample median lags a change by two 10 s cycles before any timer
# starts — the same lag a surplus deficit has.
_LAG = 20.0


class _Adapter:
    def __init__(self, last_intent=ChargerIntent.CHARGE_AT_AMPS):
        self.last_intent = last_intent
        self.min_current_a = 6
        self.max_current_a = 16

    def actual_charging(self, power):
        return power.power_w > 500.0


def _cfg():
    return {"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
            "ev_max_current": 16, "peak_hysteresis": _HYST_KW}


def _clamp_view(*, allowed_w, grid_import_w, this_w):
    return SimpleNamespace(
        fleet=SimpleNamespace(peak_slot_allowed_w=allowed_w,
                              grid_import_w=grid_import_w,
                              peak_committed_w=0.0),
        power=SimpleNamespace(power_w=this_w),
        config=_cfg(),
        wpa_table=None,
    )


def _ask(amps=16, mode="always_max"):
    return ChargerDecision(
        charger_id="wb", mode=mode, intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=amps, budget_w=amps * 690.0, reason=f"{mode} {amps}A")


@pytest.mark.unit
class TestFinding6TheClampPausesWhenSixAmpsDoNotFit:
    """A 4.2 kW limit sits at the car's 6 A minimum (≈ 4.1 kW). The clamp
    floored at 6 A, so a car over the limit was never paused; the next
    cycle's room flipped it back — on/off every cycle."""

    def test_a_running_car_without_room_for_six_amps_pauses(self):
        # House 500 W + car 4140 W on the meter; 3500 W left for the car.
        v = _clamp_view(allowed_w=4000.0, grid_import_w=500.0 + _MIN_W,
                        this_w=_MIN_W)
        out = clamp_to_peak_slot(_ask(), v)
        assert out.intent is ChargerIntent.IDLE, out.reason
        assert out.peak_paused is True
        # Transient by nature: the stability gate bridges it for the
        # user's disable delay before the car really stops.
        assert out.bridgeable is True

    def test_a_running_car_with_room_for_six_amps_keeps_charging(self):
        v = _clamp_view(allowed_w=4700.0, grid_import_w=500.0 + _MIN_W,
                        this_w=_MIN_W)
        out = clamp_to_peak_slot(_ask(), v)
        assert out.intent is ChargerIntent.CHARGE_AT_AMPS
        assert out.commanded_amps == 6
        assert out.peak_paused is False

    def test_a_restart_needs_room_for_six_amps_plus_the_hysteresis(self):
        # Paused car: room 4300 W fits 6 A (4140 W) but not 4140 + 300.
        v = _clamp_view(allowed_w=4800.0, grid_import_w=500.0, this_w=0.0)
        out = clamp_to_peak_slot(_ask(), v)
        assert out.intent is ChargerIntent.IDLE, out.reason
        assert out.peak_paused is True

    def test_a_restart_with_clear_room_is_offered(self):
        v = _clamp_view(allowed_w=5000.0, grid_import_w=500.0, this_w=0.0)
        out = clamp_to_peak_slot(_ask(), v)
        assert out.intent is ChargerIntent.CHARGE_AT_AMPS
        assert out.commanded_amps == 6

    def test_no_allowance_is_no_clamp(self):
        v = _clamp_view(allowed_w=None, grid_import_w=500.0, this_w=0.0)
        out = clamp_to_peak_slot(_ask(), v)
        assert out.commanded_amps == 16 and out.peak_paused is False


def _view(mode, *, power_w, night=False):
    return ChargerView(
        power=ChargerPower(charger_id="wb", power_w=power_w, connected=True,
                           charging=power_w > 500),
        energy=ChargerEnergy(charger_id="wb"),
        mode=mode,
        config=_cfg(),
        fleet=FleetContext(is_night=night, solar_w=3000.0 if not night else 0.0,
                           min_solar_w=200.0, battery_soc=90.0,
                           buffer_soc=70.0),
    )


def _paused(mode):
    return ChargerDecision(
        charger_id="wb", mode=mode, intent=ChargerIntent.IDLE,
        commanded_amps=0, bridgeable=True, peak_paused=True,
        capped_by_limit=True,
        reason=f"{mode} [peak slot guard: no room for 6A — pausing]")


def _run(st, decision_fn, view_fn, adapter, t0, t1, step=10.0):
    out, t = None, t0
    while t <= t1:
        out = st.filter(decision_fn(), view_fn(), adapter,
                        enable_delay_s=_ENABLE_S, disable_delay_s=_DISABLE_S,
                        min_change_interval_s=0.0, now_ts=t)
        t += step
    return out


@pytest.mark.unit
@pytest.mark.parametrize("mode,night", [
    ("solar_only", False),       # a surplus mode by day
    ("always_max", False),       # outside the surplus filter until #1069
    ("min_plus_solar", True),    # a night floor, outside it too
])
class TestFinding6OneStabilityRuleForSurplusAndPeak:
    """Guido (08.10): the peak pause goes through the same gate as surplus —
    stop only after the user's disable delay, restart only after the user's
    enable delay and with clear room."""

    def _charging_session(self, st, mode, night):
        # A session SEM is running at 6 A.
        ad = _Adapter()
        _run(st, lambda: _ask(6, mode), lambda: _view(mode, power_w=_MIN_W,
             night=night), ad, 0.0, 30.0)
        return ad

    def test_the_stop_waits_for_the_users_disable_delay(self, mode, night):
        st = ChargeStability()
        ad = self._charging_session(st, mode, night)
        held = _run(st, lambda: _paused(mode),
                    lambda: _view(mode, power_w=_MIN_W, night=night),
                    ad, 40.0, 40.0 + _DISABLE_S - 20.0)
        assert held.intent is ChargerIntent.CHARGE_AT_AMPS, held.reason
        assert held.commanded_amps == 6
        stop = _run(st, lambda: _paused(mode),
                    lambda: _view(mode, power_w=_MIN_W, night=night),
                    ad, 40.0 + _DISABLE_S + _LAG, 40.0 + _DISABLE_S + _LAG + 10.0)
        assert stop.intent is ChargerIntent.IDLE, stop.reason

    def test_the_restart_waits_for_the_users_enable_delay(self, mode, night):
        st = ChargeStability()
        ad = self._charging_session(st, mode, night)
        _run(st, lambda: _paused(mode),
             lambda: _view(mode, power_w=_MIN_W, night=night),
             ad, 40.0, 40.0 + _DISABLE_S + _LAG + 10.0)
        ad.last_intent = ChargerIntent.IDLE      # the stop landed
        t0 = 40.0 + _DISABLE_S + _LAG + 20.0
        # Car stopped; still no room for a while.
        _run(st, lambda: _paused(mode),
             lambda: _view(mode, power_w=0.0, night=night), ad, t0, t0 + 30.0)
        # Room returns: the clamp offers a charge again.
        t1 = t0 + 40.0
        early = _run(st, lambda: _ask(6, mode),
                     lambda: _view(mode, power_w=0.0, night=night),
                     ad, t1, t1 + _ENABLE_S - 20.0)
        assert early.intent is ChargerIntent.IDLE, early.reason
        late = _run(st, lambda: _ask(6, mode),
                    lambda: _view(mode, power_w=0.0, night=night),
                    ad, t1 + _ENABLE_S + _LAG, t1 + _ENABLE_S + _LAG)
        assert late.intent is ChargerIntent.CHARGE_AT_AMPS, late.reason


# ─── Finding 2: the peak cover never drains the pack below its reserve ──────

from custom_components.solar_energy_management.coordinator.charger_types import (  # noqa: E402
    BatteryIntent, BatteryRuntime, BatteryView,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (  # noqa: E402
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (  # noqa: E402
    HELD, SinkVerdict,
)


def _bview(*, soc, reserve=20.0, available=True, allowed_w=4200.0,
           home_w=5000.0, held=True, grid_funded_w=0.0, ev=False):
    cfg = {"battery_max_discharge_power": 9000, "battery_mode": "auto",
           "battery_reserve_soc": reserve}
    fleet = FleetContext(
        solar_w=0.0, home_w=home_w, battery_soc=soc, battery_soc_known=True,
        battery_count=1, peak_slot_allowed_w=allowed_w, buffer_soc=70.0,
    )
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc,
                               available=available),
        config=cfg, fleet=fleet, charging_state="idle", ev_charging=ev,
        ev_connected=ev, home_consumption_w=home_w, scheduler_decision=None,
        grid_funded_load_w=grid_funded_w,
        sink_verdicts=({"house": SinkVerdict("house", HELD, "cheap hour")}
                       if held else {}),
    )


@pytest.mark.unit
class TestFinding2TheCoverStopsAtTheReserve:
    """Reviewer's scenario: SOC 15 %, the house over a 4.2 kW limit, no sun.
    The cover raised the discharge limit no matter how empty the pack was."""

    def test_above_the_reserve_the_pack_covers_the_excess(self):
        d = decide_battery(_bview(soc=50.0))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(800.0)

    def test_below_the_reserve_the_hold_stays_at_zero(self):
        d = decide_battery(_bview(soc=15.0))
        assert d.discharge_limit_w == 0.0, d.reason
        assert "reserve" in d.reason

    def test_at_the_reserve_the_hold_stays_at_zero(self):
        d = decide_battery(_bview(soc=20.0))
        assert d.discharge_limit_w == 0.0, d.reason

    def test_an_unreadable_soc_is_not_spent(self):
        d = decide_battery(_bview(soc=50.0, available=False))
        assert d.discharge_limit_w == 0.0, d.reason

    def test_the_grid_funded_clamp_is_not_raised_below_the_reserve(self):
        d = decide_battery(_bview(soc=15.0, held=False, grid_funded_w=4500.0))
        # home 5000 − grid-funded 4500 = 500 W; the 800 W excess over the
        # limit would have raised it — not from a pack below its reserve.
        assert d.discharge_limit_w == pytest.approx(500.0), d.reason
