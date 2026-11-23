"""#1415 — *Finish by departure* follows the plan's cheap hours.

@RVallen78 (Zaptec, Solar + cheapest hours, *Finish by departure* on,
departure 15:00, 80 %): the plan card showed the charge in the cheapest
hours before 15:00, but SEM charged at once, about 7.5 kW, spread evenly to
15:00 ("deadline floor 12A, remaining 28.4 kWh").

Cause: after the night end the departure floor is a forcing deadline
(``to_departure`` sets ``deadline_active``), and ``ev_overlay`` stood down
for every forcing deadline. So the plan's blocks never reached the charger:
no wait before them, no floor inside them.

Now the departure floor yields to a plan that covers the car: the car
waits for its block while the blocks still hold the need, and charges at
the block's power inside it. The sun still charges while it waits. The
even floor comes back the moment the blocks cannot hold the need, and for
an unreachable floor. A forcing deadline at night is unchanged.

The chain is the real one: the reporter's prices → ``pack_night`` →
``plan_blocks`` → the stamped dict → ``plan_gate`` → ``plan_night_charge``
→ ``ev_overlay`` → the coordinator's write onto the plan →
``verdict_from_night_plan`` → ``decide``.
"""
from __future__ import annotations

import ast
import math
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay,
    plan_blocks,
    plan_gate,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    LedgerSlot,
    build_night_ledger,
    pack_night,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    plan_night_charge,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    verdict_from_night_plan,
)

from .ast_contracts import call_sites

AMS = ZoneInfo("Europe/Amsterdam")
DAY = datetime(2026, 11, 23, tzinfo=AMS)
STAMP = DAY.replace(hour=11, minute=15, second=3)    # the diagnostics' computed_at
DEPARTURE = DAY.replace(hour=15, minute=0)
EV = "ev:zaptec_9330108264"
WPA = 3 * 230.0          # the nameplate W/A the floor counts with
MIN_A, MAX_A = 6, 54      # "Zaptec Charger Max Amps" 54 A in the diagnostics
NEED_KWH = 30.22         # the plan row's needed_kwh at 11:15

#: the reporter's quarter-hour prices from the diagnostics (EUR/kWh)
PRICES = {
    (11, 15): 0.3985, (11, 30): 0.3948, (11, 45): 0.3953, (12, 0): 0.3902,
    (12, 15): 0.3883, (12, 30): 0.3876, (12, 45): 0.3875, (13, 0): 0.3886,
    (13, 15): 0.3935, (13, 30): 0.3900, (13, 45): 0.3975, (14, 0): 0.4008,
    (14, 15): 0.4129, (14, 30): 0.4418, (14, 45): 0.4633,
}


def _ledger():
    slots = []
    for (h, m), price in sorted(PRICES.items()):
        start = DAY.replace(hour=h, minute=m)
        slots.append(LedgerSlot(start=max(start, STAMP),
                                end=start + timedelta(minutes=15),
                                price=price, home_w=700.0))
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=0.0, peak_limit_w=40_000.0)


def _stamped():
    """The dict ``_shadow_energy_plan`` stores, packed by the real packer."""
    ledger = _ledger()
    demand = Demand(id=EV, kind="ev", energy_kwh=NEED_KWH,
                    max_power_w=MAX_A * WPA, min_power_w=MIN_A * WPA,
                    deadline=DEPARTURE, priority=1, source="grid",
                    min_run_s=900, min_gap_s=900)
    plan = pack_night([demand], ledger, peak_limit_w=40_000.0)
    return {
        "computed_at": STAMP.isoformat(),
        "demands": [{"id": r.demand_id, "status": r.status} for r in plan.results],
        "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()}
                  for s in ledger],
        "blocks": plan_blocks(plan.allocations),
    }


@pytest.fixture(scope="module")
def stamped():
    p = _stamped()
    assert p["demands"] == [{"id": EV, "status": "fits"}]
    return p


def _blocks(p):
    return [(datetime.fromisoformat(b["start"]), datetime.fromisoformat(b["end"]),
             float(b["power_w"])) for b in p["blocks"] if b["id"] == EV]


def _gap_plan(now, need):
    """The coordinator's plan after the night end (``night_over``)."""
    return plan_night_charge(
        now=now, remaining_to_min_kwh=need, min_amps=MIN_A, max_amps=MAX_A,
        watts_per_amp=WPA, target_time="15:00", night_end="07:00",
        night_start="17:06", tariff_optimized=True, peak_managed_amps=MAX_A,
        deadline_at=DEPARTURE, finish_by_departure=True, night_over=True)


def _overlay(gate, plan, need, *, departure_floor=None):
    """``ev_overlay`` exactly as both coordinator sites call it."""
    return ev_overlay(
        gate, remaining_kwh=need, reachable=plan.reachable,
        deadline_active=plan.deadline_active,
        departure_floor=(bool(getattr(plan, "to_departure", False))
                         if departure_floor is None else departure_floor),
        watts_per_amp=WPA, min_amps=MIN_A, max_amps=MAX_A,
        nominal_wpa=WPA)


def _apply(plan, gate, wait, floor):
    """The coordinator's write of the overlay onto the plan (both sites)."""
    if wait:
        plan.should_wait_for_cheap = True
        plan.next_cheap_start = gate.next_block_start
        plan.reason = "joint energy plan: outside the planned window — waiting"
    elif floor > 0:
        plan.should_wait_for_cheap = False
        plan.deadline_amps = max(plan.deadline_amps, floor)
        plan.reason = f"joint energy plan: in planned window — floor {floor}A"
    return plan


def _view(plan, need, *, mode="solar_plus_cheap", solar_w=0.0,
          tariff_level="normal"):
    return ChargerView(
        power=ChargerPower(charger_id="zaptec_9330108264", power_w=0.0,
                           connected=True, charging=False),
        energy=ChargerEnergy(charger_id="zaptec_9330108264"),
        mode=mode,
        config={"ev_min_current": MIN_A, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": MAX_A},
        fleet=FleetContext(
            solar_w=solar_w, home_w=700.0, battery_charge_w=0.0,
            battery_discharge_w=0.0, battery_soc=0.0,
            is_night=False, tariff_level=tariff_level,
            battery_assist_max_power_w=0.0,
            battery_assist_min_surplus_w=1200.0,
        ),
        target_kwh=need,
        deadline_amps=plan.deadline_amps,
        departure_floor=bool(plan.to_departure),
        top_up_amps=plan.top_up_amps,
        plan=verdict_from_night_plan(plan),
    )


def _decide_at(stamped, now, need, **view_kw):
    plan = _gap_plan(now, need)
    gate = plan_gate(stamped, EV, now)
    _apply(plan, gate, *_overlay(gate, plan, need))
    return decide(_view(plan, need, **view_kw)), plan, gate


# ── the reporter's morning ─────────────────────────────────────────


def test_the_plan_books_the_cheap_hours_not_now(stamped):
    first = _blocks(stamped)[0][0]
    assert first > STAMP + timedelta(minutes=30), (
        "the packer must leave the dear first hour free for this test")


def test_before_the_block_the_car_waits_for_it(stamped):
    """11:20: before the plan's first block. The old floor charged at
    once; now the car waits, and the reason names the block's start."""
    now = DAY.replace(hour=11, minute=20)
    first = _blocks(stamped)[0][0]
    d, plan, gate = _decide_at(stamped, now, NEED_KWH)
    assert plan.to_departure and plan.deadline_active
    assert gate.covered and not gate.in_block
    assert d.intent is ChargerIntent.IDLE
    assert d.reason_code == RC.CHARGER_PLAN_WAIT_UNTIL
    assert d.reason_params == {"time": f"{first:%H:%M}"}


def test_the_old_wiring_charged_at_once(stamped):
    """Twin: without the flag the overlay stands down for the departure's
    forcing deadline, and the even floor charges from 11:20."""
    now = DAY.replace(hour=11, minute=20)
    plan = _gap_plan(now, NEED_KWH)
    gate = plan_gate(stamped, EV, now)
    assert _overlay(gate, plan, NEED_KWH, departure_floor=False) == (False, 0)
    d = decide(_view(plan, NEED_KWH))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_DEADLINE
    hours = (DEPARTURE - now).total_seconds() / 3600.0
    assert d.commanded_amps == math.ceil(NEED_KWH * 1000 / hours / WPA)


def test_inside_the_block_the_car_charges_at_the_blocks_power(stamped):
    """15 minutes into the first block: the floor is the block's power,
    not the even spread to 15:00."""
    start, end, power_w = _blocks(stamped)[0]
    now = start + timedelta(minutes=15)
    need = NEED_KWH - power_w / 1000.0 * 0.25
    d, plan, gate = _decide_at(stamped, now, need)
    assert gate.in_block
    hours = (DEPARTURE - now).total_seconds() / 3600.0
    even = math.ceil(need * 1000 / hours / WPA)
    block = min(MAX_A, math.ceil(gate.block_power_w / WPA))
    assert block > even
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps == block


# ── the sun while it waits ─────────────────────────────────────────


@pytest.mark.parametrize("tariff_level", ["normal", "cheap", "expensive"])
def test_the_sun_still_charges_while_the_plan_waits(stamped, tariff_level):
    """A hold holds the GRID charge only. 5 kW of sun (6 A, below the 12 A
    even floor) keeps its offer in every price level."""
    now = DAY.replace(hour=11, minute=20)
    d, plan, _ = _decide_at(stamped, now, NEED_KWH, solar_w=5000.0,
                            tariff_level=tariff_level)
    assert plan.should_wait_for_cheap
    assert 0 < d.commanded_amps < plan.deadline_amps
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code != RC.CHARGER_DEADLINE


@pytest.mark.parametrize("mode", ["solar_only", "min_plus_solar",
                                  "solar_plus_battery", "solar_plus_cheap"])
def test_every_grid_mode_waits_without_sun(stamped, mode):
    now = DAY.replace(hour=11, minute=20)
    d, _, _ = _decide_at(stamped, now, NEED_KWH, mode=mode)
    assert d.intent is ChargerIntent.IDLE
    assert d.reason_code == RC.CHARGER_PLAN_WAIT_UNTIL


@pytest.mark.parametrize("mode", ["solar_only", "min_plus_solar",
                                  "solar_plus_battery", "solar_plus_cheap"])
def test_every_grid_mode_charges_at_the_block(stamped, mode):
    start, _, power_w = _blocks(stamped)[0]
    now = start + timedelta(minutes=5)
    need = NEED_KWH - power_w / 1000.0 / 12.0
    d, _, gate = _decide_at(stamped, now, need, mode=mode)
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps == min(MAX_A, math.ceil(gate.block_power_w / WPA))


# ── what still ends the wait ───────────────────────────────────────


def test_blocks_that_cannot_hold_the_need_give_back_the_even_floor(stamped):
    """The car drew less than planned: the blocks left cannot deliver what
    is owed. The even floor to 15:00 charges at once."""
    now = DAY.replace(hour=11, minute=20)
    gate = plan_gate(stamped, EV, now)
    need = gate.remaining_kwh + 1.0
    d, plan, _ = _decide_at(stamped, now, need)
    assert not plan.should_wait_for_cheap
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_DEADLINE


def test_an_unreachable_departure_is_never_held():
    now = DAY.replace(hour=14, minute=0)
    plan = _gap_plan(now, 40.0)
    assert plan.reachable is False
    gate = plan_gate(_stamped(), EV, now)
    assert gate.covered
    assert _overlay(gate, plan, 40.0) == (False, 0)


def test_an_uncovered_gap_keeps_the_even_floor():
    """No plan (actuation off, a stale stamp): the #1308 floor, as before."""
    now = DAY.replace(hour=11, minute=20)
    plan = _gap_plan(now, NEED_KWH)
    assert _overlay(plan_gate(None, EV, now), plan, NEED_KWH) == (False, 0)
    d = decide(_view(plan, NEED_KWH))
    assert d.reason_code == RC.CHARGER_DEADLINE


def test_a_forcing_deadline_at_night_still_outranks_the_plan(stamped):
    """Only the departure floor yields. A Charge by before the night end
    keeps its seniority (#638 G4)."""
    now = DAY.replace(hour=11, minute=20)
    gate = plan_gate(stamped, EV, now)
    assert ev_overlay(gate, remaining_kwh=NEED_KWH, reachable=True,
                      deadline_active=True, departure_floor=False,
                      watts_per_amp=WPA, min_amps=MIN_A,
                      max_amps=MAX_A) == (False, 0)
    assert ev_overlay(gate, remaining_kwh=NEED_KWH, reachable=True,
                      deadline_active=True, watts_per_amp=WPA,
                      min_amps=MIN_A, max_amps=MAX_A) == (False, 0)


# ── the wiring ─────────────────────────────────────────────────────


def test_every_overlay_call_passes_the_departure_flag():
    sites = call_sites("ev_overlay")
    assert len(sites) >= 2, sites
    missing = [(f, n) for f, n, kws in sites if "departure_floor" not in kws]
    assert not missing, f"ev_overlay without departure_floor at {missing}"


def test_the_flag_comes_from_the_same_plan_as_the_deadline():
    """Each coordinator site reads ``to_departure`` off the plan whose
    ``deadline_active`` it passes — never a fleet or a context copy."""
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "coordinator" / "coordinator.py").read_text(
        encoding="utf-8"))
    seen = 0
    for n in ast.walk(tree):
        if not (isinstance(n, ast.Call)
                and getattr(n.func, "id", getattr(n.func, "attr", "")) == "ev_overlay"):
            continue
        kw = {k.arg: k.value for k in n.keywords}
        dl = kw["deadline_active"]
        assert isinstance(dl, ast.Attribute) and isinstance(dl.value, ast.Name)
        flag = ast.unparse(kw["departure_floor"])
        assert "to_departure" in flag and dl.value.id in flag, flag
        seen += 1
    assert seen >= 2
