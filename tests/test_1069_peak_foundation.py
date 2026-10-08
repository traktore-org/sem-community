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


# ─── Finding 1: a forced grid charge of the battery stays under the limit ───


def _charge_view(*, allowed_w=4200.0, home_w=500.0, solar_w=0.0,
                 ev_committed_w=0.0, mode="auto", batteries=1, charge_w=3000.0):
    cfg = {"battery_max_discharge_power": 9000, "battery_mode": mode,
           "battery_reserve_soc": 20.0, "battery_max_charge_power_w": charge_w}
    fleet = FleetContext(
        solar_w=solar_w, home_w=home_w, battery_soc=40.0,
        battery_soc_known=True, battery_count=batteries,
        peak_slot_allowed_w=allowed_w, peak_committed_w=ev_committed_w,
    )
    sched = SimpleNamespace(state="scheduled", charge_power_w=charge_w,
                            target_soc=90.0, duration_min=60,
                            price_forced=False)
    gate = SimpleNamespace(covered=True, in_block=True, block_power_w=charge_w)
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=40.0),
        config=cfg, fleet=fleet, charging_state="idle", ev_charging=False,
        ev_connected=False, home_consumption_w=home_w,
        scheduler_decision=sched, plan_gate=gate,
        sem_forced_charge=True,
    )


@pytest.mark.unit
class TestFinding1TheForcedChargeAnswersToTheLimit:
    """Reviewer's scenario: a 4.2 kW limit, the car offered 4.0 kW this
    cycle, and the planned battery block charging 3 kW from the grid — 7 kW
    on the meter while every sensor read "under the limit"."""

    def test_the_cars_claim_leaves_no_room_so_the_charge_stops(self):
        d = decide_battery(_charge_view(ev_committed_w=4000.0))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE, d.reason
        assert "limit" in d.reason

    def test_the_charge_takes_only_the_room_left(self):
        # 4200 − 500 house − 2000 car = 1700 W, in 250 W steps.
        d = decide_battery(_charge_view(ev_committed_w=2000.0))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == pytest.approx(1500.0), d.reason

    def test_sun_on_top_is_room_too(self):
        # The limit is on the meter: 2 kW of sun past the house adds room.
        d = decide_battery(_charge_view(ev_committed_w=4000.0, solar_w=2500.0))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == pytest.approx(2000.0), d.reason

    def test_two_batteries_share_the_room(self):
        d = decide_battery(_charge_view(ev_committed_w=2000.0, batteries=2))
        assert d.charge_power_w == pytest.approx(750.0), d.reason

    def test_a_manual_force_charge_answers_to_the_limit_too(self):
        d = decide_battery(_charge_view(ev_committed_w=2000.0,
                                        mode="force_charge"))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == pytest.approx(1500.0), d.reason

    def test_no_limit_leaves_the_charge_alone(self):
        d = decide_battery(_charge_view(allowed_w=None, ev_committed_w=4000.0))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == pytest.approx(3000.0)


@pytest.mark.unit
class TestFinding1TheCarComesBeforeTheBattery:
    """The battery runs after the cars. Its running forced charge sits in
    the meter reading, so the car's clamp read it as somebody else's draw
    and shrank — the battery kept the room the car should have had. The
    car's clamp counts SEM's own forced charge as room (the battery yields
    next cycle)."""

    def _v(self, forced_w):
        v = _clamp_view(allowed_w=6000.0, grid_import_w=500.0 + 3000.0,
                        this_w=0.0)
        v.fleet.battery_forced_grid_w = forced_w
        return v

    def test_without_a_forced_charge_the_draw_is_somebody_elses(self):
        out = clamp_to_peak_slot(_ask(), self._v(0.0))
        assert out.intent is ChargerIntent.IDLE      # 2500 W < 6 A + hyst

    def test_sems_own_forced_charge_yields_to_the_car(self):
        out = clamp_to_peak_slot(_ask(), self._v(3000.0))
        assert out.intent is ChargerIntent.CHARGE_AT_AMPS, out.reason
        assert out.commanded_amps == 7      # 5500 W of room → 7 A


# ─── Finding 4: the battery planner keeps no copy of the limit ──────────────

@pytest.mark.unit
class TestFinding4NoCopyOfTheLimit:
    """``SchedulerConfig`` snapshot the limit once at setup, never refreshed,
    and nothing read it — a planner that looked peak-aware and was not."""

    def test_the_scheduler_config_has_no_peak_fields(self):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            SchedulerConfig,
        )
        cfg = SchedulerConfig.from_config({"target_peak_limit": 4.2,
                                           "battery_max_grid_import_w": 3000})
        assert not hasattr(cfg, "peak_limit_w")
        assert not hasattr(cfg, "max_grid_import_w")

    def test_a_lowered_limit_reaches_the_forced_charge_in_the_same_cycle(self):
        # The live allowance is the only number the cap reads: change it and
        # the very next decision follows, no restart, no options reload.
        high = decide_battery(_charge_view(allowed_w=11000.0))
        low = decide_battery(_charge_view(allowed_w=2000.0))
        assert high.charge_power_w == pytest.approx(3000.0)
        assert low.charge_power_w == pytest.approx(1500.0)


# ─── Finding 3: the monthly peak is booked on the utility's clock slots ─────

from datetime import datetime, timedelta  # noqa: E402

from custom_components.solar_energy_management.coordinator.peak_guard import (  # noqa: E402
    PeakSlotTracker,
)


def _feed(tracker, start, minutes_w, step_s=10):
    """Feed ``[(minutes, watts), …]`` at ``step_s``; collect closed slots."""
    closed, t = [], start
    for minutes, w in minutes_w:
        for _ in range(int(minutes * 60 / step_s)):
            tracker.update(t, w)
            c = tracker.pop_closed()
            if c is not None:
                closed.append(c)
            t += timedelta(seconds=step_s)
    tracker.update(t, 0.0)
    c = tracker.pop_closed()
    if c is not None:
        closed.append(c)
    return closed


@pytest.mark.unit
class TestFinding3OneTrackerClockSlots:
    """Reviewer's scenario: 8 kW from 14:10 to 14:20 straddles the 14:15
    boundary. The bill sees two slots of ~2.7 kW; the sliding window booked
    ~5.3 kW as it slid through."""

    def test_the_tracker_closes_each_clock_slot_with_its_average(self):
        tr = PeakSlotTracker()
        closed = _feed(tr, datetime(2026, 10, 8, 14, 0, 0),
                       [(10, 0.0), (10, 8000.0), (11, 0.0)])
        by_start = {s.strftime("%H:%M"): kw for s, kw in closed}
        assert by_start["14:00"] == pytest.approx(8.0 / 3, abs=0.05)
        assert by_start["14:15"] == pytest.approx(8.0 / 3, abs=0.05)

    def test_a_slot_the_tracker_saw_only_partly_is_not_booked(self):
        # Started at 14:07: the 14:00 slot was not watched from its start,
        # so its average is unknown — never booked as a peak.
        tr = PeakSlotTracker()
        closed = _feed(tr, datetime(2026, 10, 8, 14, 7, 0),
                       [(8, 6000.0), (16, 1000.0)])
        starts = [s.strftime("%H:%M") for s, _ in closed]
        assert "14:00" not in starts
        assert "14:15" in starts

    def test_the_monthly_peak_takes_closed_slots_only(self, lm):
        # The rolling average alone never books a monthly peak now.
        for _ in range(100):
            lm._update_peak_tracking(8000.0)
        assert lm._monthly_consecutive_peak == 0.0
        assert lm.record_closed_slot(datetime(2026, 10, 8, 14, 0), 2.667)
        assert lm.record_closed_slot(datetime(2026, 10, 8, 14, 15), 2.0) is False
        assert lm._monthly_consecutive_peak == pytest.approx(2.667)

    def test_a_new_month_starts_from_its_first_slot(self, lm):
        lm.record_closed_slot(datetime(2026, 10, 31, 23, 45), 6.0)
        lm.record_closed_slot(datetime(2026, 11, 1, 0, 0), 1.5)
        assert lm._monthly_consecutive_peak == pytest.approx(1.5)


@pytest.fixture
def lm(mock_hass):
    from unittest.mock import AsyncMock, MagicMock, patch

    from custom_components.solar_energy_management.load_management import (
        LoadManagementCoordinator,
    )
    entry = MagicMock()
    entry.options = {"load_management_enabled": True, "target_peak_limit": 5.0,
                     "warning_peak_level": 4.5, "emergency_peak_level": 6.0,
                     "peak_hysteresis": 0.3}
    entry.entry_id = "test_entry"
    base = "custom_components.solar_energy_management.features.load_management"
    with patch(f"{base}.LoadDeviceDiscovery") as disc, patch(f"{base}.Store") as store:
        disc.return_value = MagicMock()
        st = MagicMock()
        st.async_load = AsyncMock(return_value=None)
        st.async_save = AsyncMock()
        store.return_value = st
        coordinator = LoadManagementCoordinator(mock_hass, entry)
        coordinator._store = st
        yield coordinator


# ─── Finding 5: a restart does not reset the current slot ───────────────────

from custom_components.solar_energy_management.coordinator.peak_guard import (  # noqa: E402
    slot_allowed_import_w, tracker_from_state,
)


@pytest.mark.unit
class TestFinding5TheSlotSurvivesARestart:
    """A restart mid-slot set the slot's import back to 0, so the guard
    granted up to three times the limit for the rest of a slot that may
    already have been spent."""

    def _spent(self):
        tr = PeakSlotTracker()
        _feed(tr, datetime(2026, 10, 8, 14, 0, 0), [(7, 8000.0)])
        return tr

    def test_the_same_slot_comes_back_spent(self):
        tr = self._spent()
        state = tr.to_state()
        back = tracker_from_state(state, datetime(2026, 10, 8, 14, 8, 30))
        assert back.imported_kwh == pytest.approx(tr.imported_kwh)
        # 4 kW limit: 1.0 kWh budget, ~0.93 kWh spent — the room is small,
        # not three times the limit.
        allowed = slot_allowed_import_w(4.0, back.imported_kwh, 510.0)
        assert allowed < 1000.0

    def test_a_new_slot_starts_fresh(self):
        back = tracker_from_state(self._spent().to_state(),
                                  datetime(2026, 10, 8, 14, 20, 0))
        assert back.imported_kwh == 0.0

    def test_the_restart_gap_is_a_hole_the_monthly_peak_does_not_book(self):
        back = tracker_from_state(self._spent().to_state(),
                                  datetime(2026, 10, 8, 14, 9, 0))
        closed = _feed(back, datetime(2026, 10, 8, 14, 10, 0), [(6, 1000.0)])
        assert [s.strftime("%H:%M") for s, _ in closed] == []

    def test_a_broken_state_is_a_fresh_tracker(self):
        for bad in (None, {}, {"slot_start": "garbage"}, "x"):
            tr = tracker_from_state(bad, datetime(2026, 10, 8, 14, 0, 0))
            assert tr.imported_kwh == 0.0


@pytest.mark.unit
def test_every_ledger_in_the_coordinator_sizes_against_the_planning_limit():
    """(#1069) The tomorrow preview packed against the raw cap while the
    real night packs against cap − hysteresis: one forecast, two answers.
    The coordinator reads the raw cap for no ledger."""
    from .ast_contracts import call_sites

    raw = [s for s in call_sites("_get_peak_limit_w")
           if s[0].endswith("coordinator/coordinator.py")]
    assert raw == []
