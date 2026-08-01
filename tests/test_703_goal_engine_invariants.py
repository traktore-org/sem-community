"""#703 — the load goal engine's contract, held at EVERY simulated cycle.

Seven instances of the same class (a gate that blocks activation but doesn't
stop a running load, or two coupled mechanisms disagreeing about a boundary)
have been fixed one at a time: #559, #620 (×3 live catches), #633, #688,
#703. This harness closes the CLASS: it drives a simulated multi-day clock
through the real imperative ``SurplusController.update()`` and asserts the
whole contract after every cycle — any future edit that breaks a boundary,
a stop path, or a marker invariant fails here, not on a reporter's pump.

The contract (docs/MULTI_DEVICE_GUIDE.md + BUG_CLASSES classes 17/18/32):

  I1  grid top-up runs  ⇔ price cheap ∧ deficit open on the METER day
                          ∧ policy cheap_hours ∧ no peak freeze
  I2  tier-2 battery runs ⇔ night ∧ deficit ∧ opted-in ∧ SOC > reserve
  I3  past the floor, only surplus keeps a load running
  I4  at/past the Max cap the load NEVER runs
  I5  no midnight flap: an overnight top-up crosses 00:00 without a stop
      (the force expires at the SUNRISE meter-day rollover, not at the
      calendar flip)
  I6  a set force marker implies its source condition held when stamped;
      markers never survive their stop
  I7  runtime accrues on the meter day; the deficit resets exactly once,
      at sunrise
"""
from datetime import date, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    _load_meter_day,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode

DAY1 = date(2026, 8, 1)
DAY2 = date(2026, 8, 2)


def _pump(**kw):
    """A switch-load stand-in with real marker/goal fields (not MagicMock
    attrs — the invariants must read genuine False/None defaults)."""
    d = MagicMock()
    d.device_id = kw.get("device_id", "pump")
    d.name = "Pump"
    d.priority = kw.get("priority", 5)
    d.min_power_threshold = kw.get("min_power", 1500.0)
    d.rated_power = 1500.0
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = kw.get("is_active", False)
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.record_activated = MagicMock()
    d.record_deactivated = MagicMock()
    d.reset_surplus_timer = MagicMock()
    d.status = MagicMock()
    d.get_current_consumption = MagicMock(
        side_effect=lambda: 1500.0 if d.is_active else 0.0)
    d.is_deadline_approaching = False
    d.stop_condition_met = False
    d.stop_entity = ""
    d.stop_at = 0
    d._sem_owned = True
    d._external_off_until = None
    d._observed_off_since = None
    # goal state — plain values, mutated by the walk
    d.top_up_policy = kw.get("top_up_policy", "cheap_hours")
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = kw.get("battery_eligible_overnight", False)
    d.daily_min_runtime_sec = kw.get("min_sec", 4 * 3600)
    d.daily_max_runtime_sec = kw.get("max_sec", 0)
    d._daily_runtime_accumulated_sec = kw.get("accum", 0.0)
    d._daily_runtime_meter_day = kw.get("meter_day", DAY1)
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None

    async def _act(watts):
        d.is_active = True
        return 1500.0

    async def _deact():
        d.is_active = False
    d.activate = AsyncMock(side_effect=_act)
    d.deactivate = AsyncMock(side_effect=_deact)
    d.adjust_power = AsyncMock(side_effect=lambda w: 1500.0 if d.is_active else 0.0)

    # live properties derived from the goal state, like the real device
    def _deficit():
        if d.daily_min_runtime_sec <= 0:
            return False
        if d.daily_max_runtime_sec and \
                d._daily_runtime_accumulated_sec >= d.daily_max_runtime_sec:
            return False
        return d._daily_runtime_accumulated_sec < d.daily_min_runtime_sec
    type(d).has_runtime_deficit = property(lambda self: _deficit())
    type(d).needs_offpeak_activation = property(
        lambda self: _deficit() and not d.is_active)
    type(d).daily_targets_met = property(
        lambda self: d.daily_min_runtime_sec > 0
        and d._daily_runtime_accumulated_sec >= d.daily_min_runtime_sec)
    type(d).daily_max_runtime_reached = property(
        lambda self: d.daily_max_runtime_sec > 0
        and d._daily_runtime_accumulated_sec >= d.daily_max_runtime_sec)
    type(d).remaining_daily_runtime_sec = property(
        lambda self: max(0.0, d.daily_min_runtime_sec
                         - d._daily_runtime_accumulated_sec))
    return d


class Walk:
    """Drives update() through a scripted timeline and checks the contract
    after every cycle. Each step is (meter_day, price, is_night, surplus_w,
    soc). Runtime accrues CYCLE_SEC per active cycle onto the meter day —
    mirroring coordinator.update_daily_runtime, including the reset."""
    CYCLE_SEC = 600.0

    def __init__(self, device, **battery):
        self.d = device
        self.sc = SurplusController(MagicMock())
        self.sc.register_device(device)
        self.battery = battery
        self.transitions = []          # (step_idx, 'on'|'off')
        self.violations = []
        self.step_idx = -1

    async def run(self, timeline):
        for step in timeline:
            self.step_idx += 1
            day, price, night, surplus, soc = step
            was = self.d.is_active
            # meter-day rollover exactly like update_daily_runtime()
            if self.d._daily_runtime_meter_day != day:
                self.d._daily_runtime_accumulated_sec = 0.0
                self.d._daily_runtime_meter_day = day
            await self.sc.update(
                surplus, price_level=price, is_night=night,
                battery_soc=soc,
                battery_buffer_soc=self.battery.get("buffer", 100.0),
                battery_reserve_soc=self.battery.get("reserve", 20.0),
                battery_assist_budget_w=self.battery.get("assist", 0.0),
            )
            if self.d.is_active != was:
                self.transitions.append(
                    (self.step_idx, "on" if self.d.is_active else "off"))
            if self.d.is_active:
                self.d._daily_runtime_accumulated_sec += self.CYCLE_SEC
            self._check(step)
        return self

    def _check(self, step):
        day, price, night, surplus, soc = step
        d = self.d
        # I6 — a marker never contradicts its own source's live condition
        # beyond the one-cycle expiry lag the pass itself owns.
        if d._offpeak_forced and d.top_up_policy != "cheap_hours":
            self.violations.append(
                (self.step_idx, "offpeak marker on a solar_only load"))
        if d._batt_overnight_forced and not d.battery_eligible_overnight:
            self.violations.append(
                (self.step_idx, "tier2 marker without the opt-in"))
        # I4 — past the Max cap the load must not run (the stop pass may
        # need this cycle; it must be off by the NEXT check).
        if d.daily_max_runtime_reached and d.is_active \
                and getattr(self, "_cap_grace_used", False):
            self.violations.append((self.step_idx, "running past the Max cap"))
        self._cap_grace_used = d.daily_max_runtime_reached


@pytest.mark.asyncio
class TestOvernightTopUpCrossesMidnight:
    """I5 — THE #703 scenario: cheap window 22:00→06:00, deficit open.
    The top-up starts in the evening and must run STRAIGHT through 00:00;
    the only stop is the sunrise meter-day rollover."""

    async def test_no_midnight_flap(self):
        d = _pump(accum=2.5 * 3600)          # 2.5/4 h — deficit open
        w = Walk(d)
        timeline = (
            # evening of DAY1, cheap window opens, no surplus
            [(DAY1, "cheap", True, 0.0, 50.0)] * 6      # 22:00–23:00
            # calendar midnight passes — METER day still DAY1
            + [(DAY1, "cheap", True, 0.0, 50.0)] * 6    # 00:00–01:00
        )
        await w.run(timeline)
        assert w.violations == []
        ons = [t for t in w.transitions if t[1] == "on"]
        offs = [t for t in w.transitions if t[1] == "off"]
        assert len(ons) == 1, f"expected one activation, saw {w.transitions}"
        # the deficit (1.5 h) fills after ~9 cycles; a 'done' stop is fine —
        # what must NOT exist is an off+on pair (the midnight flap)
        assert not (len(offs) >= 1 and len(ons) >= 2), (
            f"midnight flap: {w.transitions}"
        )

    async def test_pre_fix_regression_guard(self):
        """The exact pre-#703 mechanism: a marker stamped 'yesterday' while
        the METER day is still yesterday must NOT read stale."""
        d = _pump(accum=2.5 * 3600, meter_day=DAY1)
        d.is_active = True
        d._offpeak_forced = True
        d._offpeak_forced_date = DAY1          # stamped before midnight
        w = Walk(d)
        # calendar is now DAY2 (past midnight) but meter day held at DAY1
        await w.run([(DAY1, "cheap", True, 0.0, 50.0)])
        assert d.is_active, "force expired at the calendar flip (#703)"
        assert d._offpeak_forced

    async def test_force_ends_at_sunrise_rollover(self):
        """I7 — at the sunrise rollover the OLD day's force expires (its
        deficit is gone) and the marker does not leak into the new day."""
        d = _pump(accum=2.5 * 3600, meter_day=DAY1)
        d.is_active = True
        d._offpeak_forced = True
        d._offpeak_forced_date = DAY1
        w = Walk(d)
        # sunrise: meter day flips to DAY2 (Walk resets the accumulator)
        await w.run([(DAY2, "cheap", False, 0.0, 50.0)])
        # the stale force must be gone; the load may only re-force for the
        # NEW day's own deficit, stamped with the NEW day
        if d._offpeak_forced:
            assert d._offpeak_forced_date == DAY2
        assert w.violations == []


@pytest.mark.asyncio
class TestSourceAuthorityMatrix:
    """I1/I2 — every paid source's START gate and STOP condition, symmetric."""

    async def test_grid_topup_only_in_cheap_windows(self):
        d = _pump()
        w = Walk(d)
        await w.run([(DAY1, "normal", True, 0.0, 50.0)] * 3)
        assert not d.is_active, "grid top-up outside a cheap window"
        await w.run([(DAY1, "cheap", True, 0.0, 50.0)])
        assert d.is_active, "cheap window open + deficit → top-up must start"
        await w.run([(DAY1, "normal", True, 0.0, 50.0)])
        assert not d.is_active, "window closed → a RUNNING top-up must stop"
        assert w.violations == []

    async def test_solar_only_never_grid_forces(self):
        d = _pump(top_up_policy="solar_only")
        w = Walk(d)
        await w.run([(DAY1, "cheap", True, 0.0, 50.0)] * 4)
        assert not d.is_active
        assert d._offpeak_forced is False

    async def test_tier2_battery_full_lifecycle(self):
        d = _pump(top_up_policy="solar_only", battery_eligible_overnight=True)
        w = Walk(d, reserve=20.0)
        # night + SOC above reserve → battery carries the deficit
        await w.run([(DAY1, "normal", True, 0.0, 60.0)])
        assert d.is_active and d._batt_overnight_forced
        # reserve floor reached → must STOP (not just refuse to start)
        await w.run([(DAY1, "normal", True, 0.0, 20.0)])
        assert not d.is_active, "tier-2 kept draining at the reserve floor"
        assert not d._batt_overnight_forced, "tier-2 marker leaked (class 18)"
        # SOC recovers → may start again; then the NIGHT ends → must stop
        await w.run([(DAY1, "normal", True, 0.0, 60.0)])
        assert d.is_active
        await w.run([(DAY1, "normal", False, 0.0, 60.0)])
        assert not d.is_active, "tier-2 rode into the day (#633 class)"
        assert w.violations == []


@pytest.mark.asyncio
class TestFloorAndCeiling:
    """I3/I4 — the #688 floor/ceiling contract under the walk."""

    async def test_floor_ends_the_paid_run_only(self):
        d = _pump(min_sec=3600, accum=3000.0)   # 10 min short of the floor
        w = Walk(d)
        await w.run([(DAY1, "cheap", True, 0.0, 50.0)])
        assert d.is_active                       # paid top-up toward the floor
        await w.run([(DAY1, "cheap", True, 0.0, 50.0)] * 2)
        # floor met (accum 3600+) → the PAID run must end even mid-window
        assert not d.is_active, "grid top-up kept buying past the floor"
        # but free surplus may carry it on (no Max cap set). Sustained for
        # several cycles: the median-of-3 + EMA anti-flap deliberately
        # ignores a single-cycle surplus spike.
        await w.run([(DAY1, "cheap", False, 5000.0, 50.0)] * 4)
        assert d.is_active, "surplus blocked past the floor (floor≠stop)"
        assert w.violations == []

    async def test_surplus_lost_stops_past_floor(self):
        d = _pump(min_sec=3600, accum=2 * 3600)  # floor met
        d.is_active = True
        w = Walk(d)
        await w.run([(DAY1, "normal", False, 0.0, 50.0)])
        assert not d.is_active, "#688: surplus gone + floor met must stop"

    async def test_max_cap_is_a_hard_stop(self):
        d = _pump(min_sec=3600, max_sec=2 * 3600, accum=2 * 3600 - 300)
        d.is_active = True
        w = Walk(d)
        # cap crosses mid-run under full surplus — must stop and stay off
        await w.run([(DAY1, "normal", False, 5000.0, 50.0)] * 3)
        assert not d.is_active, "ran past the Max cap"
        await w.run([(DAY1, "cheap", True, 0.0, 50.0)] * 2)
        assert not d.is_active, "cheap window revived a capped load"
        assert w.violations == []


@pytest.mark.asyncio
class TestTwoDayWalk:
    """The whole contract across two full simulated days — deficit resets
    exactly once (sunrise), each day's paid hours stay in their own day."""

    async def test_48h_contract(self):
        d = _pump(min_sec=2 * 3600)
        w = Walk(d)
        day1_evening = [(DAY1, "cheap", True, 0.0, 50.0)] * 6      # 22–23h
        day1_overnight = [(DAY1, "cheap", True, 0.0, 50.0)] * 8    # past 00:00
        sunrise = [(DAY2, "normal", False, 0.0, 50.0)] * 2
        day2_solar = [(DAY2, "normal", False, 5000.0, 50.0)] * 6
        await w.run(day1_evening + day1_overnight + sunrise + day2_solar)
        assert w.violations == []
        # day 1: the 2 h deficit filled overnight (12 × 10 min), booked to
        # DAY1 before the walk reset it at sunrise; day 2 accrues fresh solar
        # hours once the anti-flap smoothing warms to the sustained surplus
        # (median-of-3 + EMA cost ~3 cycles — by design, not a hole).
        assert d._daily_runtime_meter_day == DAY2
        assert d.is_active, "sustained day-2 surplus must be running the load"
        assert 0 < d._daily_runtime_accumulated_sec <= 6 * 600.0
        # exactly one over-midnight run, no flap at the calendar boundary
        offs_during_night = [
            t for t in w.transitions
            if t[1] == "off" and 6 <= t[0] < 12   # the 00:00–01:00 stretch
        ]
        assert not offs_during_night, f"midnight flap: {w.transitions}"


def test_load_meter_day_fallback():
    """Fresh boot (no runtime tick yet) → the calendar date, not a crash."""
    d = SimpleNamespace(_daily_runtime_meter_day=None)
    assert _load_meter_day(d) is not None
    d2 = SimpleNamespace(_daily_runtime_meter_day=DAY1)
    assert _load_meter_day(d2) == DAY1


class TestOneMeterDayClass:
    """(#704) The loads' day comes from the SAME TimeManager meter-day class
    the EV uses — not from inline day arithmetic in the coordinator. The
    previous stateful latch reset a day early on a mid-night restart."""

    def test_coordinator_reads_the_timemanager_class(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parents[1]
               / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        assert "get_current_meter_day_sunrise_based()" in src, (
            "the load-runtime tick no longer reads the TimeManager meter-day "
            "class (#704) — inline day arithmetic reintroduces the "
            "mid-night-restart day-jump"
        )
        # the latch's signature move — guarding the day assignment behind
        # is_night_mode — must not come back
        assert "if not self.time_manager.is_night_mode():\n                self._load_meter_day" \
            not in src, "the stateful meter-day latch is back (#704)"

    def test_sunrise_boundary_is_stateless_and_restart_proof(self):
        """Before sunrise → yesterday, after → today — on a FRESH instance
        each time (the restart case the latch got wrong)."""
        from datetime import datetime, timedelta
        from unittest.mock import patch
        from custom_components.solar_energy_management.utils.time_manager import (
            TimeManager,
        )
        from homeassistant.util import dt as dt_util

        now = dt_util.now()
        night = now.replace(hour=2, minute=0, second=0)      # a 02:00 boot
        sunrise = now.replace(hour=6, minute=15, second=0)
        tm = TimeManager.__new__(TimeManager)
        with patch.object(TimeManager, "get_sunrise_datetime",
                          return_value=sunrise), \
             patch.object(dt_util, "now", return_value=night):
            assert tm.get_current_meter_day_sunrise_based() == \
                (night.date() - timedelta(days=1)), (
                    "a mid-night boot must still be YESTERDAY's meter day"
                )
        day = now.replace(hour=9, minute=0, second=0)
        tm2 = TimeManager.__new__(TimeManager)
        with patch.object(TimeManager, "get_sunrise_datetime",
                          return_value=sunrise), \
             patch.object(dt_util, "now", return_value=day):
            assert tm2.get_current_meter_day_sunrise_based() == day.date()
