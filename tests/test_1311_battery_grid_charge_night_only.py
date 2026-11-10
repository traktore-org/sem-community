"""#1311 — the plan showed a battery grid charge SEM does not do.

SEM charges the battery from the grid at night only. A plan made by day put
the battery block in a cheap day hour; and it added the block when the
scheduler said "not profitable" or "already at target". Now a priced day
slot is closed to the battery demand (a sun slot stays open: the sun fills
the pack), and a scheduler that will not charge adds no battery demand.
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    SchedulerState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_self, _power,
)

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE


class _MiddayAndNightCheap:
    """Cheap 12:00-14:00 and 02:00-04:00."""

    def get_price_at(self, t):
        return 0.10 if t.hour in (12, 13, 2, 3) else 0.28

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (12, 13, 2, 3) else "normal"


def _scheduler(state, deficit=4.0):
    return SimpleNamespace(
        decision=SimpleNamespace(deficit_kwh=deficit, state=state),
        _config=SimpleNamespace(battery_max_charge_power_w=5000.0),
    )


def _plan_at(monkeypatch, hour, state, *, sun_kwh=None):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    fake.time_manager = _DayCapableTime()
    fake._tariff_provider = _MiddayAndNightCheap()
    if sun_kwh is not None:
        fake._forecast_reader = SimpleNamespace(forecast_data=SimpleNamespace(
            forecast_remaining_today_kwh=sun_kwh))
    fixed = datetime(2026, 7, 29, hour, 0, tzinfo=TZ)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(state), energy=MagicMock(), power=_power())
    return fake._energy_plan_shadow


def _battery_starts(plan):
    out = []
    for line in plan["allocations"]:
        if line.startswith("battery:") or line.startswith("battery "):
            out.append(line.split(" W ")[1].split("–")[0])
    return out


def _sun_hours(plan):
    return {s["start"][11:16] for s in plan["slots"] if s.get("sun")}


def test_a_day_plan_puts_the_battery_charge_in_night_hours(monkeypatch):
    plan = _plan_at(monkeypatch, 9, SchedulerState.SCHEDULED)
    starts = _battery_starts(plan)
    assert starts, plan["allocations"]
    # night 21:00-07:00 only: no cheap midday hour
    assert all(s >= "21:00" or s < "07:00" for s in starts), starts


def test_sun_hours_stay_open_to_the_battery(monkeypatch):
    plan = _plan_at(monkeypatch, 9, SchedulerState.SCHEDULED, sun_kwh=25.0)
    sun = _sun_hours(plan)
    assert sun
    for s in _battery_starts(plan):
        assert s in sun or s >= "21:00" or s < "07:00", s


@pytest.mark.parametrize("state", [
    SchedulerState.NOT_PROFITABLE, SchedulerState.NOT_NEEDED,
    SchedulerState.TARGET_REACHED])
def test_no_battery_demand_when_the_scheduler_will_not_charge(monkeypatch, state):
    plan = _plan_at(monkeypatch, 9, state)
    # nothing else to plan: no plan at all, or a quiet answer without a battery
    assert plan is None or not plan.get("allocations")
    assert plan is None or not any(
        ln.startswith("battery") for ln in plan.get("summary", []))
