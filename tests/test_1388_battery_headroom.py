"""#1388 — the battery plan never asks for more than the pack can take.

Reporter: 2 x Sessy, 9.66 kWh measured, 92 % full, target 95 %. The scheduler
said "Charge 0.3 kWh", but its day deficit (23.66 kWh) went to the energy plan
as the battery demand: "needed 23.7 kWh", plan does not fit. A deficit above
the room is house demand the grid covers, not battery charge. And a block in
an hour that was the only one left must not say "cheapest hours".
"""
from __future__ import annotations

from datetime import datetime, timedelta
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
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_self, _power,
)

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE
USABLE = 9.66 * 0.95          # what the scheduler plans with (measured x 0.95)


class _Prices:
    def get_price_at(self, t):
        return 0.30 if t.hour in (2, 3) else 0.41

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (2, 3) else "expensive"


def _scheduler(deficit, target=95.0):
    return SimpleNamespace(
        decision=SimpleNamespace(deficit_kwh=deficit, state=SchedulerState.SCHEDULED,
                                 target_soc=target),
        _config=SimpleNamespace(battery_max_charge_power_w=2200.0,
                                battery_usable_capacity_kwh=USABLE),
    )


def _plan(monkeypatch, soc, deficit, hour=22):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    fake.time_manager = _DayCapableTime()
    fake._tariff_provider = _Prices()
    fixed = datetime(2026, 7, 29, hour, 0, tzinfo=TZ)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(deficit), energy=MagicMock(), power=_power(soc))
    return fake._energy_plan_shadow


def _battery_kwh(plan):
    return sum(d["needed_kwh"] for d in plan["demands"] if d["id"] == "battery")


def test_the_reporters_deficit_is_capped_to_the_room(monkeypatch):
    plan = _plan(monkeypatch, soc=92.0, deficit=23.66)
    need = _battery_kwh(plan)
    assert need == pytest.approx(0.03 * USABLE, abs=0.02)   # ~0.3 kWh
    assert plan["fits"] is True


def test_a_small_deficit_is_left_alone(monkeypatch):
    plan = _plan(monkeypatch, soc=50.0, deficit=2.0)
    assert _battery_kwh(plan) == pytest.approx(2.0, abs=0.01)


def test_a_full_pack_asks_for_nothing(monkeypatch):
    plan = _plan(monkeypatch, soc=95.0, deficit=23.66)
    assert plan is None or _battery_kwh(plan) == 0


def _led(prices):
    t0 = datetime(2026, 11, 19, 6, 45)
    slots = [LedgerSlot(start=t0 + timedelta(minutes=15 * n),
                        end=t0 + timedelta(minutes=15 * (n + 1)), price=p)
             for n, p in enumerate(prices)]
    return build_night_ledger(slots, soc_kwh=8.9, floor_kwh=0.0,
                              max_discharge_w=5000.0, peak_limit_w=0.0)


def _batt(kwh=0.3):
    return Demand(id="battery", kind="battery", energy_kwh=kwh,
                  max_power_w=2200, source="grid")


def test_the_only_hour_left_does_not_say_cheapest_hours():
    plan = pack_night([_batt()], _led([0.407]))
    assert plan.allocations
    assert {a.code for a in plan.allocations} == {"no_cheaper_hour"}


def test_a_real_pick_still_says_cheapest_hours():
    plan = pack_night([_batt()], _led([0.407, 0.20, 0.45]))
    assert {a.code for a in plan.allocations} == {"cheapest_hours"}
