"""(#1330) The plan put a "Grid" load's daily minimum in a cheap day hour.

"Finish overnight via: Grid" is a finish source: by day, execution buys the
grid only once the sun is out of time (#953, kept for boilers in #1102). It
waits while ``sunset + 10 min - max(now, sunrise)`` still covers the run time
owed. The joint plan did not know that rule. A plan made by day (every plan
from sunrise on) put the load in the cheapest cheap hour, a midday low tariff
too, and the Energy Plan card showed a run there that SEM never did.

Now the load demand carries ``sun_waits_until``: the time the live wait ends,
``sunset - deficit``, from the same sun reader (``_daylight_frame``). The
packer uses a priced slot only from that time on. A sun slot stays open:
the sun runs the load there, with no wait (review finding).
"""
from __future__ import annotations

import ast
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    LedgerSlot,
    build_night_ledger,
    pack_night,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    grid_top_up_defers_to_sun,
    grid_top_up_waits_until,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_self, _power, _scheduler, freeze_targets,
)

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE
ROOT = Path(__file__).resolve().parent.parent


def _t(h, m=0, day=29):
    return datetime(2026, 7, day, h, m, tzinfo=TZ)


class _MiddayAndNightCheap:
    """Cheap 12:00-14:00 and 02:00-04:00, the same price."""

    def get_price_at(self, t):
        return 0.10 if t.hour in (12, 13, 2, 3) else 0.28

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (12, 13, 2, 3) else "normal"


class _EveningCheap:
    """Cheap 18:00-20:00 only (before tonight's 21:00 window)."""

    def get_price_at(self, t):
        return 0.10 if t.hour in (18, 19) else 0.28

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (18, 19) else "normal"


class _MiddayCheapOnly:
    def get_price_at(self, t):
        return 0.10 if t.hour in (12, 13) else 0.28

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (12, 13) else "normal"


class _SunTime(_DayCapableTime):
    """Night 21:00-07:00, sunrise 06:00, sunset + 10 min 20:10, measured."""

    _last_sunset_source = "sun_integration"

    def get_sunrise_datetime(self):
        return _t(6)


class _FallbackSunTime(_SunTime):
    """The sun integration did not answer: 20:10 is the made-up default."""

    _last_sunset_source = "fallback_default"


def _grid_load(owed_h=2.0, *, state="", tier2=False):
    return SimpleNamespace(
        device_id="pool", name="Pool", has_runtime_deficit=True,
        battery_eligible_overnight=tier2, top_up_policy="cheap_hours",
        daily_min_runtime_sec=int(owed_h * 3600),
        _daily_runtime_accumulated_sec=0,
        remaining_daily_runtime_sec=owed_h * 3600,
        rated_power=800.0, priority=4, comfort_state=state,
    )


def _plan_at(monkeypatch, hour, dev, *, tariff=None, tm=None, sun_kwh=None,
             day=29):
    fake = _fake_self(devices=[dev])
    fake.time_manager = tm or _SunTime()
    fake._tariff_provider = tariff or _MiddayAndNightCheap()
    if sun_kwh is not None:
        fake._forecast_reader = SimpleNamespace(forecast_data=SimpleNamespace(
            forecast_remaining_today_kwh=sun_kwh))
    fixed = _t(hour, day=day)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(0.0), energy=MagicMock(), power=_power())
    return fake, fake._energy_plan_shadow


def _load_starts(plan):
    """Start times of the pool's blocks, from the plan's own lines."""
    out = []
    for line in plan["allocations"]:
        if not line.startswith("load:pool:"):
            continue
        hhmm = line.split(" W ")[1].split("–")[0]
        out.append(hhmm)
    return out


def _summary(plan, did="load:pool"):
    return next(ln for ln in plan["summary"] if ln.startswith(did))


def _sun_hours(plan):
    """Start hours ("HH:00") of the plan's sun slots."""
    return {s["start"][11:16] for s in plan["slots"] if s.get("sun")}


class _CheapFiveToSeven:
    def get_price_at(self, t):
        return 0.10 if t.hour in (17, 18) else 0.28

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (17, 18) else "normal"


class TestTheDayPlanWaitsForTheSun:
    """The issue's day: a 2 h minimum, cheap at noon and at night."""

    def test_no_block_while_the_sun_still_has_time(self, freeze_targets,
                                                   monkeypatch):
        _, plan = _plan_at(monkeypatch, 9, _grid_load())
        starts = _load_starts(plan)
        assert starts, plan["allocations"]
        # sunset + 10 min is 20:10, 2 h owed: the live wait ends at 18:10.
        assert all(s < "07:00" for s in starts), starts
        assert "fits" in _summary(plan)

    def test_a_cheap_hour_after_the_wait_is_still_used(self, freeze_targets,
                                                       monkeypatch):
        """3 h owed: the wait ends at 17:10, so 18:00-20:00 is open."""
        _, plan = _plan_at(monkeypatch, 9, _grid_load(3.0),
                           tariff=_EveningCheap())
        starts = _load_starts(plan)
        assert starts and set(starts) <= {"18:00", "19:00"}, starts

    def test_only_a_midday_cheap_hour_says_it_waits_for_the_sun(
            self, freeze_targets, monkeypatch):
        """Execution never buys at noon here, so the plan books nothing and
        its note says why — not "fits" with a block that does not run, and
        not "no cheap window" beside a cheap band on the card."""
        _, plan = _plan_at(monkeypatch, 9, _grid_load(),
                           tariff=_MiddayCheapOnly())
        assert _load_starts(plan) == []
        line = _summary(plan)
        assert "YIELDS" in line and "waits for the sun until 18:10" in line

    def test_the_hour_that_holds_the_end_of_the_wait_is_used_from_it(
            self, freeze_targets, monkeypatch):
        """2.5 h owed: the wait ends at 17:40, inside the cheap 17:00 hour.
        Execution starts at 17:40, so the plan's block does too. No car:
        it would take the 17:00 headroom first."""
        monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                            lambda coord, energy: {})
        _, plan = _plan_at(monkeypatch, 9, _grid_load(2.5),
                           tariff=_CheapFiveToSeven())
        starts = _load_starts(plan)
        assert starts and starts[0] == "17:40", starts
        assert all(s >= "17:40" for s in starts), starts

    def test_sun_hours_stay_open(self, freeze_targets, monkeypatch):
        """A sunny day: the sun runs the load by day with no wait (the solar
        clause), so the plan keeps it in the sun hours."""
        _, plan = _plan_at(monkeypatch, 9, _grid_load(), sun_kwh=25.0)
        sun = _sun_hours(plan)
        starts = _load_starts(plan)
        assert sun, "the forecast must give sun slots"
        assert starts and all(s in sun for s in starts), (starts, sun)

    def test_a_plan_made_after_midnight_is_unchanged(self, freeze_targets,
                                                    monkeypatch):
        """At 01:00 "today's" sunset is 20:10 the coming evening. The plan
        has no day part, so no wait applies to its night slots."""
        _, plan = _plan_at(monkeypatch, 1, _grid_load(), day=30)
        _, no_wait = _plan_at(monkeypatch, 1, _grid_load(), day=30,
                              tm=_FallbackSunTime())
        assert _load_starts(plan)
        assert _load_starts(plan) == _load_starts(no_wait)

    def test_no_measured_sunset_no_wait(self, freeze_targets, monkeypatch):
        """Execution does not wait on a sunset nobody measured (#953), so
        the plan does not either: noon stays usable."""
        _, plan = _plan_at(monkeypatch, 9, _grid_load(),
                           tm=_FallbackSunTime())
        assert "12:00" in _load_starts(plan) or "13:00" in _load_starts(plan)

    def test_a_forced_band_does_not_wait(self, freeze_targets, monkeypatch):
        """Too cold now: execution skips the wait, so the plan does too."""
        _, plan = _plan_at(monkeypatch, 9, _grid_load(state="forced"))
        assert any(s in ("12:00", "13:00") for s in _load_starts(plan))

    def test_a_plan_made_in_the_night_is_unchanged(self, freeze_targets,
                                                   monkeypatch):
        """No day hours: the same blocks as a plan with no wait at all."""
        _, plan = _plan_at(monkeypatch, 23, _grid_load())
        _, no_wait = _plan_at(monkeypatch, 23, _grid_load(),
                              tm=_FallbackSunTime())
        assert _load_starts(plan)
        assert _load_starts(plan) == _load_starts(no_wait)


class TestEveryBlockIsOneExecutionWouldStart:
    """The oracle: at each planned block's start, the live wait — fed by
    the coordinator's real daylight reader — lets the grid start."""

    @pytest.mark.parametrize("hour", [7, 9, 12, 15, 17, 19])
    @pytest.mark.parametrize("owed_h", [0.5, 1.0, 2.0, 2.5, 3.0, 5.0])
    @pytest.mark.parametrize("tariff", [_MiddayAndNightCheap, _EveningCheap,
                                        _CheapFiveToSeven])
    @pytest.mark.parametrize("sun_kwh", [None, 6.0])
    def test_no_block_where_the_wait_holds(self, freeze_targets, monkeypatch,
                                           hour, owed_h, tariff, sun_kwh):
        dev = _grid_load(owed_h)
        fake, plan = _plan_at(monkeypatch, hour, dev, tariff=tariff(),
                              sun_kwh=sun_kwh)
        stamp = _t(hour)
        sun = _sun_hours(plan)
        for hhmm in _load_starts(plan):
            if hhmm in sun:
                continue            # the sun runs it there, no wait
            h, m = (int(x) for x in hhmm.split(":"))
            start = stamp.replace(hour=h, minute=m)
            if start < stamp:
                start += timedelta(days=1)
            night = start >= _t(21)
            # one cycle in: at the very end of the wait the live gate still
            # holds, and starts on its next cycle
            start += timedelta(seconds=30)
            monkeypatch.setattr(coord_mod.dt_util, "now",
                                lambda *a, _s=start, **k: _s)
            daylight = SEMCoordinator._daylight_remaining_s_now(fake)
            assert not grid_top_up_defers_to_sun(
                dev, daylight_remaining_s=daylight, is_night=night), (
                f"block at {hhmm} waits for the sun "
                f"({daylight / 3600:.1f} h of daylight, {owed_h} h owed)")


class TestTheWaitEndsWhereTheLiveGateSaysSo:
    """``grid_top_up_waits_until`` against ``grid_top_up_defers_to_sun``,
    minute by minute over the whole day."""

    @pytest.mark.parametrize("owed_h", [0.25, 1.0, 2.5, 8.0, 13.0, 15.0])
    def test_minute_by_minute(self, owed_h):
        dev = _grid_load(owed_h)
        sunrise, sunset = _t(6), _t(20, 10)
        until = grid_top_up_waits_until(dev, sunrise=sunrise, sunset=sunset)
        t = _t(0)
        while t < _t(23, 59):
            daylight = max(0.0, (sunset - max(t, sunrise)).total_seconds())
            waits = grid_top_up_defers_to_sun(
                dev, daylight_remaining_s=daylight, is_night=False)
            planned_wait = until is not None and t < until
            if until is None or t != until:
                assert waits is planned_wait, (t, until)
            t += timedelta(minutes=1)

    def test_a_day_shorter_than_the_need_never_waits(self):
        assert grid_top_up_waits_until(
            _grid_load(15.0), sunrise=_t(6), sunset=_t(20, 10)) is None

    def test_nothing_owed_never_waits(self):
        assert grid_top_up_waits_until(
            _grid_load(0.0), sunrise=_t(6), sunset=_t(20, 10)) is None

    def test_a_forced_band_never_waits(self):
        assert grid_top_up_waits_until(
            _grid_load(2.0, state="forced"),
            sunrise=_t(6), sunset=_t(20, 10)) is None


class TestThePacker:
    """``Demand.sun_waits_until`` in the pure packer."""

    def _night(self):
        start = _t(10)
        slots = [LedgerSlot(start=start + timedelta(hours=i),
                            end=start + timedelta(hours=i + 1),
                            price=0.10, level_cheap=True, tariff_cheap=True,
                            home_w=0.0)
                 for i in range(6)]
        return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                  max_discharge_w=0.0, peak_limit_w=0.0)

    def _demand(self, **kw):
        args = dict(id="load:x", kind="load", energy_kwh=1.6,
                    max_power_w=800.0, min_power_w=800.0, source="grid",
                    needs_cheap_level=True)
        args.update(kw)
        return Demand(**args)

    def test_no_slot_before_it(self):
        plan = pack_night([self._demand(sun_waits_until=_t(13))], self._night())
        assert [a.start.hour for a in plan.allocations] == [13, 14]

    def test_the_slot_that_holds_it_is_used_from_it(self):
        plan = pack_night([self._demand(sun_waits_until=_t(13, 30))],
                          self._night())
        starts = [a.start for a in plan.allocations]
        assert starts[0] == _t(13, 30), starts
        assert all(s >= _t(13, 30) for s in starts)
        assert plan.results[0].status == "fits"

    def test_a_sun_slot_does_not_wait(self):
        ledger = self._night()
        ledger[0].cap_override_w = 2000.0      # a sun slot, as build_day_slots
        plan = pack_night([self._demand(sun_waits_until=_t(15))], ledger)
        assert _t(10) in [a.start for a in plan.allocations]

    def test_none_is_the_old_shape(self):
        plan = pack_night([self._demand()], self._night())
        assert [a.start.hour for a in plan.allocations] == [10, 11]

    def test_one_block_respects_it(self):
        plan = pack_night([self._demand(sun_waits_until=_t(14), contiguous=True)],
                          self._night())
        assert [a.start.hour for a in plan.allocations] == [14, 15]

    def test_one_block_is_not_split_by_it(self):
        """A sun slot before a priced slot that holds the end of the wait is
        not back-to-back with what follows: the block cannot join them."""
        ledger = self._night()
        ledger[2].cap_override_w = 2000.0      # 12:00 is sun
        plan = pack_night([self._demand(sun_waits_until=_t(13, 30),
                                        contiguous=True, energy_kwh=1.6)],
                          ledger)
        a = sorted(plan.allocations, key=lambda x: x.start)
        for x, y in zip(a, a[1:], strict=False):
            assert x.end == y.start, a

    def test_the_late_part_respects_it(self):
        d = self._demand(kind="ev", needs_cheap_level=False,
                         deadline=_t(16), late_s=3 * 3600,
                         sun_waits_until=_t(14, 30), energy_kwh=0.8)
        plan = pack_night([d], self._night())
        assert plan.allocations
        assert all(a.start >= _t(14, 30) for a in plan.allocations)

    def test_the_note_says_it_waits_for_the_sun(self):
        plan = pack_night([self._demand(sun_waits_until=_t(17))], self._night())
        assert plan.results[0].status == "yields"
        assert plan.results[0].note == "waits for the sun until 17:00"


class TestOneReader:
    """The live wait and the plan read the sun through one function."""

    def _tree(self):
        return ast.parse(
            (ROOT / "coordinator" / "coordinator.py").read_text(encoding="utf-8"))

    def test_every_load_demand_carries_its_start_limit(self):
        found = 0
        for node in ast.walk(self._tree()):
            if not (isinstance(node, ast.Call)
                    and getattr(node.func, "id", None) == "Demand"):
                continue
            kinds = [k.value.value for k in node.keywords
                     if k.arg == "kind" and isinstance(k.value, ast.Constant)]
            if kinds != ["load"]:
                continue
            found += 1
            assert any(k.arg == "sun_waits_until" for k in node.keywords), \
                "a load Demand without sun_waits_until (#1330)"
        assert found >= 1

    def test_the_plan_and_the_live_wait_share_the_sun_reader(self):
        funcs = {n.name: n for n in ast.walk(self._tree())
                 if isinstance(n, ast.FunctionDef)}

        def _called(fn):
            return {getattr(c.func, "id", None) or getattr(c.func, "attr", None)
                    for c in ast.walk(funcs[fn]) if isinstance(c, ast.Call)}

        assert "_daylight_frame" in _called("_daylight_remaining_s_now")
        assert "_daylight_frame" in _called("_shadow_energy_plan")
        assert "grid_top_up_waits_until" in _called("_shadow_energy_plan")
        assert "_plan_day_end" in _called("_shadow_energy_plan")
