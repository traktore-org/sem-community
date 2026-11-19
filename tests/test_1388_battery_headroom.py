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
CAP = 9.66                    # measured, not the configured 10.0


class _Prices:
    def get_price_at(self, t):
        return 0.30 if t.hour in (2, 3) else 0.41

    def get_price_level_at(self, t):
        return "cheap" if t.hour in (2, 3) else "expensive"


def _scheduler(deficit, target=95.0):
    return SimpleNamespace(
        decision=SimpleNamespace(deficit_kwh=deficit, state=SchedulerState.SCHEDULED,
                                 target_soc=target),
        _config=SimpleNamespace(battery_max_charge_power_w=2200.0),
    )


def _plan(monkeypatch, soc, deficit, hour=22):
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {})
    fake = _fake_self(devices=[])
    fake.time_manager = _DayCapableTime()
    fake.battery_capacity_kwh = CAP
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
    assert need == pytest.approx(0.03 * CAP, abs=0.02)   # ~0.3 kWh
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


def _why(prices, kwh=0.3, deadline=None):
    from custom_components.solar_energy_management.coordinator.energy_planner import demand_why
    led = _led(prices)
    d = _batt(kwh)
    if deadline:
        d = Demand(id="battery", kind="battery", energy_kwh=kwh,
                   max_power_w=2200, source="grid", deadline=deadline)
    plan = pack_night([d], led)
    return demand_why(plan.allocations, led, "grid")["code"]


def test_the_summary_follows_the_block_for_the_only_hour_left():
    dl = datetime(2026, 11, 19, 7, 0)       # the dearer slot lies past it
    assert _why([0.407, 0.407, 0.407, 0.407, 0.60], deadline=dl) == "no_cheaper_hour"


def test_the_summary_keeps_cheapest_hours_when_any_block_is_a_real_pick():
    # 0.3 kWh at 2.2 kW takes one slot; the 0.2 slot is the pick
    assert _why([0.407, 0.20, 0.45]) == "cheapest_hours"


def _draining_ledger(prices_by_hour, soc=9.0, cap=10.0, home_w=3000.0):
    t0 = datetime(2026, 11, 19, 21, 0)
    slots = [LedgerSlot(start=t0 + timedelta(hours=n),
                        end=t0 + timedelta(hours=n + 1),
                        price=prices_by_hour[n], home_w=home_w)
             for n in range(len(prices_by_hour))]
    return build_night_ledger(slots, soc_kwh=soc, floor_kwh=0.0,
                              max_discharge_w=5000.0, peak_limit_w=0.0,
                              capacity_kwh=cap)


def test_a_draining_night_charges_what_the_pack_has_room_for_then():
    # 90 % at 21:00, target 95 %: room now 0.5 kWh. The house empties the
    # pack by 03:00; the cheap hours 03:00-06:00 can take far more.
    prices = [0.40] * 6 + [0.10] * 3
    led = _draining_ledger(prices)
    d = Demand(id="battery", kind="battery", energy_kwh=9.0,
               max_power_w=2200, source="grid", room_kwh=0.5)
    plan = pack_night([d], led)
    planned = sum(a.energy_kwh for a in plan.allocations)
    assert planned > 5.0                      # was capped at 0.5 by the live SOC
    assert planned <= 9.5 + 1e-6              # never above the pack


def test_a_pack_with_no_drain_still_gets_only_its_room():
    led = _draining_ledger([0.40, 0.10, 0.40], home_w=0.0, soc=9.0)
    d = Demand(id="battery", kind="battery", energy_kwh=9.0,
               max_power_w=2200, source="grid", room_kwh=0.5)
    plan = pack_night([d], led)
    assert sum(a.energy_kwh for a in plan.allocations) == pytest.approx(0.5, abs=0.01)


def test_two_packs_of_different_size_are_summed_by_their_own_room():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        _battery_room_kwh,
    )
    big = SimpleNamespace(soc_pct=95.0)
    small = SimpleNamespace(soc_pct=50.0)
    caps = {"a": 10.0, "b": 2.0}
    coord = SimpleNamespace(_pack_share_kwh=lambda bid, power: caps[bid],
                            battery_capacity_kwh=12.0)
    power = SimpleNamespace(battery_soc=72.5, batteries={"a": big, "b": small})
    room = _battery_room_kwh(coord, SimpleNamespace(target_soc=95.0), None, power)
    assert room == pytest.approx(0.9)         # the plain average would say 2.7


def test_a_dearer_slot_that_is_full_is_not_a_choice():
    # the dearer hour's house load fills the grid limit: no real choice
    t0 = datetime(2026, 11, 19, 6, 0)
    slots = [LedgerSlot(start=t0, end=t0 + timedelta(hours=1), price=0.407),
             LedgerSlot(start=t0 + timedelta(hours=1),
                        end=t0 + timedelta(hours=2), price=0.60,
                        home_w=9000.0)]
    led = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                             max_discharge_w=0.0, peak_limit_w=5000.0)
    plan = pack_night([_batt()], led, max_discharge_w=0.0, peak_limit_w=5000.0)
    assert {a.code for a in plan.allocations} == {"no_cheaper_hour"}
