"""(#1395) A heat pump allowed to buy in cheap hours heats BEFORE the room
reaches its too-cold limit, not in the night's cheapest hours after it.

Reporter, 18.11: Keep at 22 °C, Never colder than 21 °C, "Yes, in cheap
hours". From 15:00 the room read 21.1 °C; cheap slots came before 16:30. The
Keep at goal carried no deadline, so the plan put it in the night's very cheap
hours (23:00–02:00). At 16:30 the room fell below 21 °C and SEM heated at a
normal price until 00:17 — the cost the cheap hours were meant to avoid.

Now the goal carries the time the room reaches its limit, from the learned
cooling rate, and the plan takes it as the deadline when it comes first.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import (
    comfort_deadline,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import _Hass

NOW = datetime(2026, 11, 18, 15, 0, tzinfo=timezone.utc)
ROOM = "sensor.room"


def _pump(temp=21.1, *, cooling_c_per_h=0.07, policy="cheap_hours"):
    """The reporter's shape: an SG-Ready pump on two relays, a room sensor,
    Keep at 22, Never colder than 21, a cooling rate learned while off."""
    hass = _Hass()
    hass.set("switch.sg1", "off")
    hass.set("switch.sg2", "off")
    hass.set(ROOM, str(temp), unit_of_measurement="°C")
    dev = HeatPumpController(hass=hass, relay1_entity_id="switch.sg1",
                             relay2_entity_id="switch.sg2", rated_power=3400.0)
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity = ROOM
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 22.0, 1.0, 21.0
    dev.top_up_policy = policy
    if cooling_c_per_h is not None:
        dev._comfort_off_samples = deque(
            (NOW - timedelta(minutes=60 - m), temp + cooling_c_per_h * (60 - m) / 60)
            for m in range(0, 61, 10))
    return dev


def test_the_goal_says_when_the_room_reaches_its_limit():
    ask = _pump().comfort_plan_demand(NOW, goal=True)
    assert ask and ask["energy_kwh"] > 0
    # 0.1 °C above the limit, cooling 0.07 °C/h: about 1.4 h
    lead_h = (ask["limit_at"] - NOW).total_seconds() / 3600
    assert 1.0 < lead_h < 2.0
    assert ask["deadline"] is None, "the goal keeps no deadline of its own (#1369)"


def test_without_a_learned_cooling_rate_the_goal_is_as_before():
    ask = _pump(cooling_c_per_h=None).comfort_plan_demand(NOW, goal=True)
    assert ask and "limit_at" not in ask


def test_solar_only_still_asks_for_nothing():
    assert _pump(policy="solar_only").comfort_plan_demand(NOW, goal=True) is None


def test_the_plan_takes_the_limit_when_it_comes_before_the_night_end():
    night_end = NOW + timedelta(hours=15)
    limit_at = NOW + timedelta(hours=1, minutes=30)
    assert comfort_deadline({"deadline": None, "limit_at": limit_at}, night_end) == limit_at
    assert comfort_deadline({"deadline": None}, night_end) == night_end
    later = NOW + timedelta(hours=20)
    assert comfort_deadline({"deadline": None, "limit_at": later}, night_end) == night_end
    naive = datetime(2026, 11, 18, 16, 30)
    assert comfort_deadline({"deadline": None, "limit_at": naive}, night_end) == night_end


def _day_ledger():
    """15:00 → 03:00: two cheap afternoon hours, dearer evening, the night
    cheapest — the reporter's 18.11 in shape."""
    prices = [0.20, 0.21, 0.30, 0.31, 0.32, 0.30, 0.29, 0.28, 0.12, 0.11, 0.10, 0.12]
    slots = [LedgerSlot(start=NOW + timedelta(hours=n), end=NOW + timedelta(hours=n + 1),
                        price=p, level_cheap=p < 0.25, home_w=300.0)
             for n, p in enumerate(prices)]
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=5000.0, peak_limit_w=0.0)


def _packed(ask):
    night_end = NOW + timedelta(hours=12)
    d = Demand(id="comfort:heat_pump", kind="comfort", energy_kwh=float(ask["energy_kwh"]),
               max_power_w=3400.0, min_power_w=3400.0,
               deadline=comfort_deadline(ask, night_end), needs_cheap_level=True)
    plan = pack_night([d], _day_ledger())
    return [a for a in plan.allocations if a.demand_id == d.id]


def test_the_run_lands_before_the_limit_not_in_the_night():
    ask = _pump().comfort_plan_demand(NOW, goal=True)
    runs = _packed(ask)
    assert runs, "the goal is planned"
    assert all(a.start < ask["limit_at"] for a in runs)
    assert min(a.start for a in runs) < NOW + timedelta(hours=2)


def test_twin_without_the_limit_the_night_wins():
    ask = dict(_pump().comfort_plan_demand(NOW, goal=True))
    ask.pop("limit_at")
    runs = _packed(ask)
    assert runs and min(a.start for a in runs) >= NOW + timedelta(hours=8)


def test_the_diagnostics_show_the_band_and_why_no_ask():
    from custom_components.solar_energy_management.diagnostics import _comfort_devices
    pump = _pump(policy="solar_only")
    ctl = SimpleNamespace(get_devices_sorted=lambda: [pump])
    rows = _comfort_devices(SimpleNamespace(_surplus_controller=ctl))
    row = rows[str(pump.device_id)]
    assert row["keep_at"] == 22.0 and row["never_colder_than"] == 21.0
    assert row["purchase_policy"] == "solar_only"
    assert row["comfort_state"] == "willing"
    assert row["learned_cooling"] is True
    assert row["no_ask_because"]                     # solar only: a named reason
    assert _comfort_devices(SimpleNamespace(_surplus_controller=None)) == {}
