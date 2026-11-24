"""#1415 — *Finish by departure* follows the plan's cheap hours.

@RVallen78 (Zaptec, Solar + cheapest hours, *Finish by departure* on,
departure 15:00, 80 %): the plan card showed the charge in the cheapest
hours before 15:00, but SEM charged at once, about 7.5 kW, spread evenly to
15:00 ("deadline floor 12A, remaining 28.4 kWh").

Cause: after the night end the departure floor is a forcing deadline
(``to_departure`` sets ``deadline_active``), and ``ev_overlay`` stood down
for every forcing deadline. So the plan's blocks never reached the charger:
no wait before them, no floor inside them.

Now the departure floor yields to a plan that covers the car: inside a
block the car charges at the block's power; before it the car waits, but
only while the even floor could still land from the block's start at the
most this car has been seen to draw (review: before a departure nothing
charges after the plan fails, and above the measured range the plan's
power is the nameplate — the reporter's 54 A read 37 kW), and only while
nothing but the car caps its rate (review 4: no peak limit, no phase guard
that acts; the reporter has neither). The sun still charges while it
waits. A forcing deadline at night is unchanged.

The chain is the real one: the reporter's prices and measured W/A table →
``pack_night`` → ``plan_blocks`` → the stamped dict → ``plan_gate`` →
``plan_night_charge`` → ``apply_ev_overlay`` (the coordinator's one helper)
→ ``verdict_from_night_plan`` → ``decide``.
"""
from __future__ import annotations

import ast
import math
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch
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
    DEPARTURE_WAIT_MARGIN,
    PlanGate,
    apply_ev_overlay,
    departure_wait_is_safe,
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
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    plan_night_charge,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    verdict_from_night_plan,
)
from custom_components.solar_energy_management.coordinator.watts_per_amp import (
    amps_that_fit,
    predict_watts,
)

from .ast_contracts import call_sites

AMS = ZoneInfo("Europe/Amsterdam")
DAY = datetime(2026, 11, 23, tzinfo=AMS)
STAMP = DAY.replace(hour=11, minute=15, second=3)    # the diagnostics' computed_at
DEPARTURE = DAY.replace(hour=15, minute=0)
WAITING = DAY.replace(hour=11, minute=20)
EV = "ev:zaptec_9330108264"
WPA = 3 * 230.0          # the nameplate W/A the even floor counts with
MIN_A = 6
#: the reporter's measured W/A table (3 phases) from the diagnostics
TABLE = {12: 625.0, 20: 529.6}
TOP_W = 20 * 529.6       # the most this car was seen to draw: 10.6 kW

#: the reporter's quarter-hour prices from the diagnostics (EUR/kWh)
PRICES = {
    (11, 15): 0.3985, (11, 30): 0.3948, (11, 45): 0.3953, (12, 0): 0.3902,
    (12, 15): 0.3883, (12, 30): 0.3876, (12, 45): 0.3875, (13, 0): 0.3886,
    (13, 15): 0.3935, (13, 30): 0.3900, (13, 45): 0.3975, (14, 0): 0.4008,
    (14, 15): 0.4129, (14, 30): 0.4418, (14, 45): 0.4633,
}


#: "the setup's own table" (a ``None`` table means "none measured")
_OWN = object()


class Setup:
    """One charger setting and one need, packed by the real packer."""

    def __init__(self, max_a, need, *, peak_w=math.inf, prices=None,
                 table=None, home=None):
        self.max_a, self.need = max_a, need
        #: what SEM has measured on this car (the reporter's by default)
        self.table = TABLE if table is None else table
        #: the reporter's peak limit is "unlimited"; a finite one caps the
        #: car (``_ev_rate_capped``)
        self.peak_w, self.capped = peak_w, math.isfinite(peak_w)
        #: the house load by the hour, as forecast and as it comes
        self.home = home or (lambda t: 700.0)
        #: what the peak limit leaves the car beside 700 W of house load
        self.room_w = peak_w - 700.0
        ledger = []
        for (h, m), price in sorted((prices or PRICES).items()):
            start = DAY.replace(hour=h, minute=m)
            ledger.append(LedgerSlot(start=max(start, STAMP),
                                     end=start + timedelta(minutes=15),
                                     price=price, home_w=self.home(start)))
        ledger = build_night_ledger(ledger, soc_kwh=0.0, floor_kwh=0.0,
                                    max_discharge_w=0.0, peak_limit_w=peak_w)
        demand = Demand(
            id=EV, kind="ev", energy_kwh=need,
            # (#846) the coordinator sizes the demand from the table
            max_power_w=predict_watts(self.table, max_a, WPA),
            min_power_w=predict_watts(self.table, MIN_A, WPA),
            deadline=DEPARTURE, priority=1, source="grid",
            min_run_s=900, min_gap_s=900)
        packed = pack_night([demand], ledger, peak_limit_w=peak_w)
        self.stamped = {
            "computed_at": STAMP.isoformat(),
            "demands": [{"id": r.demand_id, "status": r.status}
                        for r in packed.results],
            "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()}
                      for s in ledger],
            "blocks": plan_blocks(packed.allocations),
        }

    def blocks(self):
        return [(datetime.fromisoformat(b["start"]),
                 datetime.fromisoformat(b["end"]), float(b["power_w"]))
                for b in self.stamped["blocks"] if b["id"] == EV]

    def gap_plan(self, now, need, *, table=_OWN):
        """The coordinator's plan after the night end (``night_over``)."""
        table = self.table if table is _OWN else table
        return plan_night_charge(
            now=now, remaining_to_min_kwh=need, min_amps=MIN_A,
            max_amps=self.max_a, watts_per_amp=WPA, target_time="15:00",
            night_end="07:00", night_start="17:06", tariff_optimized=True,
            peak_managed_amps=self.max_a, deadline_at=DEPARTURE,
            finish_by_departure=True, night_over=True, wpa_table=table)

    def overlaid(self, now, need, *, table=_OWN):
        table = self.table if table is _OWN else table
        plan = self.gap_plan(now, need, table=table)
        gate = plan_gate(self.stamped, EV, now)
        apply_ev_overlay(plan, gate, remaining_kwh=need, watts_per_amp=WPA,
                         min_amps=MIN_A, max_amps=self.max_a,
                         wpa_table=table, nominal_wpa=WPA,
                         rate_capped=self.capped)
        return plan, gate

    def view(self, plan, need, *, mode="solar_plus_cheap", solar_w=0.0,
             tariff_level="normal"):
        return ChargerView(
            power=ChargerPower(charger_id="zaptec_9330108264", power_w=0.0,
                               connected=True, charging=False),
            energy=ChargerEnergy(charger_id="zaptec_9330108264"),
            mode=mode,
            config={"ev_min_current": MIN_A, "ev_phases": 3,
                    "ev_voltage": 230, "ev_max_current": self.max_a},
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

    def decide_at(self, now, need, *, table=_OWN, **view_kw):
        plan, gate = self.overlaid(now, need, table=table)
        return decide(self.view(plan, need, **view_kw)), plan, gate

    def run_to_departure(self, *, car_w, start=WAITING, old=False,
                         share=1.0, draw=None):
        """Minute by minute to 15:00: the car draws ``share`` of what the
        table says the commanded amps buy, at most ``car_w``. ``draw``
        (amps → W) replaces the table: what a real car takes. ``old`` =
        develop: the overlay stood down for the departure floor, and the
        floor counted 690 W/A. The peak limit caps the amps as the slot
        guard does: the largest setpoint that fits what the limit leaves
        beside this minute's house load, none below the minimum. kWh
        left."""
        now, need = start, self.need
        while now < DEPARTURE and need > 0.05:
            cap_a = amps_that_fit(self.table, self.peak_w - self.home(now),
                                  WPA, self.max_a)
            plan = self.gap_plan(now, need, table=None if old else _OWN)
            if not old:
                plan, _ = self.overlaid(now, need)
            d = decide(self.view(plan, need))
            amps = min(d.commanded_amps, cap_a)
            if d.intent is ChargerIntent.CHARGE_AT_AMPS and amps >= MIN_A:
                watts = (draw(amps) if draw is not None
                         else predict_watts(self.table, amps, WPA))
                need -= min(share * watts, car_w) / 1000.0 / 60.0
            now += timedelta(minutes=1)
        return max(0.0, need)


#: Max Amps set to the car's real 20 A; the car owes 12 kWh — the plan
#: books it in the cheapest hours, from 12:15.
FIXED = Setup(20, 12.0)
#: the diagnostics as reported: Max Amps 54 A, 30.22 kWh owed.
REPORTED = Setup(54, 30.22)
#: 20 kWh owed: the even floor (8 A) is above a 5 kW sun's 6 A.
SUN = Setup(20, 20.0)


def test_the_setups_are_what_the_diagnostics_say():
    assert FIXED.stamped["demands"] == [{"id": EV, "status": "fits"}]
    assert FIXED.blocks()[0][0] == DAY.replace(hour=12, minute=15)
    # the reporter's card: 12:15–13:15 at 37.26 kW (54 A × 690 W/A)
    assert REPORTED.blocks()[0][:2] == (DAY.replace(hour=12, minute=15),
                                        DAY.replace(hour=12, minute=30))
    assert REPORTED.blocks()[0][2] == pytest.approx(54 * WPA)
    assert REPORTED.blocks()[-1][1] == DAY.replace(hour=13, minute=15)


# ── the fix: the plan leads ────────────────────────────────────────


def test_before_the_block_the_car_waits_for_it():
    """11:20: the old floor charged at once; now the car waits, and the
    reason names the block's start."""
    d, plan, gate = FIXED.decide_at(WAITING, FIXED.need)
    assert plan.to_departure and plan.deadline_active
    assert gate.covered and not gate.in_block
    assert d.intent is ChargerIntent.IDLE
    assert d.reason_code == RC.CHARGER_PLAN_WAIT_UNTIL
    assert d.reason_params == {"time": "12:15"}


def test_the_old_wiring_charged_at_once():
    """Twin: with the overlay standing down for the departure's forcing
    deadline, the even floor charges from 11:20."""
    plan = FIXED.gap_plan(WAITING, FIXED.need)
    gate = plan_gate(FIXED.stamped, EV, WAITING)
    assert ev_overlay(gate, remaining_kwh=FIXED.need, reachable=True,
                      deadline_active=True, departure_floor=False,
                      watts_per_amp=WPA, min_amps=MIN_A,
                      max_amps=20) == (False, 0)
    d = decide(FIXED.view(plan, FIXED.need))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_DEADLINE


def test_inside_the_block_the_car_charges_at_the_blocks_power():
    """15 minutes into the block: the block's power, not the even spread."""
    start, _, power_w = FIXED.blocks()[0]
    now = start + timedelta(minutes=15)
    need = FIXED.need - power_w / 1000.0 * 0.25
    d, plan, gate = FIXED.decide_at(now, need)
    assert gate.in_block
    hours = (DEPARTURE - now).total_seconds() / 3600.0
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps == 20 > math.ceil(need * 1000 / hours / WPA)


@pytest.mark.parametrize("tariff_level", ["normal", "cheap", "expensive"])
def test_the_sun_still_charges_while_the_plan_waits(tariff_level):
    """A hold holds the GRID charge only. 5 kW of sun (6 A) keeps its
    offer in every price level; in a cheap hour it used to lose to the
    wait, and below the floor it used to lose to it."""
    assert SUN.blocks()[0][0] > WAITING
    d, plan, _ = SUN.decide_at(WAITING, SUN.need, solar_w=5000.0,
                               tariff_level=tariff_level)
    assert plan.should_wait_for_cheap
    assert 0 < d.commanded_amps < plan.deadline_amps
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code != RC.CHARGER_DEADLINE


MODES = ["solar_only", "min_plus_solar", "solar_plus_battery", "solar_plus_cheap"]


@pytest.mark.parametrize("mode", MODES)
def test_every_grid_mode_waits_without_sun(mode):
    d, _, _ = FIXED.decide_at(WAITING, FIXED.need, mode=mode)
    assert d.intent is ChargerIntent.IDLE
    assert d.reason_code == RC.CHARGER_PLAN_WAIT_UNTIL


@pytest.mark.parametrize("mode", MODES)
def test_every_grid_mode_charges_at_the_block(mode):
    start, _, power_w = FIXED.blocks()[0]
    now = start + timedelta(minutes=5)
    d, _, _ = FIXED.decide_at(now, FIXED.need - power_w / 1000.0 / 12.0,
                              mode=mode)
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps == 20


# ── review: a wait must never cost the departure ───────────────────


def test_the_reported_plan_is_not_waited_for():
    """54 A read as 37 kW; the car was seen at 10.6 kW at most. From 12:15
    that cannot land 30.22 kWh by 15:00, so the even floor charges at once,
    as before."""
    d, plan, gate = REPORTED.decide_at(WAITING, REPORTED.need)
    assert gate.covered and not gate.in_block
    assert not plan.should_wait_for_cheap
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_DEADLINE


def test_the_even_floor_counts_the_cars_measured_draw():
    """The log: "deadline floor 12A, remaining 28.4 kWh" at 11:30, and 12 A
    drew 7463 W. 8.1 kW over 3.5 h needs 14 A on this car (8.3 kW by its
    table), not 12. At night the floor is unchanged."""
    now = DAY.replace(hour=11, minute=30)
    need = 28.4
    assert REPORTED.gap_plan(now, need, table=None).deadline_amps == 12
    assert REPORTED.gap_plan(now, need).deadline_amps == 14
    assert predict_watts(TABLE, 14, WPA) * 3.5 >= need * 1000
    night = plan_night_charge(
        now=DAY.replace(hour=2, minute=0), remaining_to_min_kwh=need,
        min_amps=MIN_A, max_amps=54, watts_per_amp=WPA, night_end="07:00",
        night_start="17:06", deadline_at=DEPARTURE, finish_by_departure=True)
    assert not night.to_departure
    assert night.deadline_amps == plan_night_charge(
        now=DAY.replace(hour=2, minute=0), remaining_to_min_kwh=need,
        min_amps=MIN_A, max_amps=54, watts_per_amp=WPA, night_end="07:00",
        night_start="17:06", deadline_at=DEPARTURE, finish_by_departure=True,
        wpa_table=TABLE).deadline_amps


def test_the_coordinator_hands_the_planner_the_table():
    from custom_components.solar_energy_management.coordinator.ev_control import (
        EVControlMixin,
    )

    from .ast_contracts import call_kwargs
    kwargs = call_kwargs(EVControlMixin._compute_night_plan, "plan_night_charge")
    assert kwargs and all("wpa_table" in kw for kw in kwargs)


@pytest.mark.parametrize("car_w", [TOP_W, 10_000.0, 9_000.0, 0.8 * TOP_W])
def test_the_reported_plan_lands_as_well_as_the_old_floor(car_w):
    """The review's minute-by-minute run, down to a car at 80 % of its
    measured draw: never further from full than develop. (SEM counts
    0.1 kWh or less as done.)"""
    new = REPORTED.run_to_departure(car_w=car_w)
    old = REPORTED.run_to_departure(car_w=car_w, old=True)
    assert new <= max(old, 0.1)


@pytest.mark.parametrize("need", [8.0, 16.0, 24.0])
@pytest.mark.parametrize("share", [0.9, 0.8])
def test_a_slower_car_lands_as_well_as_the_old_floor(need, share):
    s = Setup(20, need)
    new = s.run_to_departure(car_w=share * TOP_W)
    old = s.run_to_departure(car_w=share * TOP_W, old=True)
    assert new <= max(old, 0.1)


@pytest.mark.parametrize("need", [4.0, 8.0, 12.0, 16.0, 20.0, 24.0, 28.4])
def test_any_need_lands_by_the_departure(need):
    """Max Amps right, the car at its seen 10.6 kW: whatever the plan
    books, the car is full at 15:00."""
    s = Setup(20, need)
    assert s.run_to_departure(car_w=TOP_W) <= 0.1


def test_a_car_slower_than_planned_still_lands():
    """The plan counts 10.6 kW; the car takes 8.5 kW (80 %): the even floor
    after a failed block still makes 15:00."""
    s = Setup(20, 12.0)
    assert s.run_to_departure(car_w=0.8 * TOP_W) <= 0.1


def test_the_wait_needs_room_for_the_even_floor_after_it():
    gate = PlanGate(covered=True, remaining_kwh=30.0,
                    next_block_start=DAY.replace(hour=12, minute=15))
    hours = 2.75
    room = TOP_W / 1000.0 * hours * DEPARTURE_WAIT_MARGIN
    kw = dict(wpa_table=TABLE, nominal_wpa=WPA, max_amps=20)
    assert departure_wait_is_safe(gate, room - 0.01, DEPARTURE, **kw)
    assert not departure_wait_is_safe(gate, room + 0.01, DEPARTURE, **kw)


def test_no_measured_draw_is_no_proof():
    """A car SEM never measured (or a disputed phase belief: an empty
    table) gets the even floor, the #1308 behaviour."""
    gate = PlanGate(covered=True, remaining_kwh=30.0,
                    next_block_start=DAY.replace(hour=12, minute=15))
    assert not departure_wait_is_safe(gate, 1.0, DEPARTURE, wpa_table={},
                                      nominal_wpa=WPA, max_amps=20)
    d, plan, _ = FIXED.decide_at(WAITING, FIXED.need, table={})
    assert not plan.should_wait_for_cheap
    assert d.reason_code == RC.CHARGER_DEADLINE


def test_only_setpoints_the_charger_may_use_count():
    """A 20 A reading does not prove a 16 A charger's draw."""
    gate = PlanGate(covered=True, remaining_kwh=10.0,
                    next_block_start=DAY.replace(hour=12, minute=15))
    kw = dict(nominal_wpa=WPA, max_amps=16)
    assert not departure_wait_is_safe(gate, 20.0, DEPARTURE,
                                      wpa_table={20: 529.6}, **kw)
    assert departure_wait_is_safe(gate, 10.0, DEPARTURE,
                                  wpa_table={12: 625.0, 20: 529.6}, **kw)


def test_no_next_block_or_no_end_is_no_proof():
    kw = dict(wpa_table=TABLE, nominal_wpa=WPA, max_amps=20)
    gate = PlanGate(covered=True, remaining_kwh=10.0)
    assert not departure_wait_is_safe(gate, 1.0, DEPARTURE, **kw)
    gate = PlanGate(covered=True, remaining_kwh=10.0,
                    next_block_start=DEPARTURE)
    assert not departure_wait_is_safe(gate, 1.0, DEPARTURE, **kw)
    assert not departure_wait_is_safe(gate, 1.0, None, **kw)


# ── review 2: the peak limit and the charger's own max ─────────────

#: 0.45 before noon, 0.30 from 12:00 to the departure
NOON_PRICES = {(h, m): (0.45 if h < 12 else 0.30)
               for h in range(11, 15) for m in (0, 15, 30, 45)
               if (h, m) >= (11, 15)}


def test_the_gate_reports_the_top_block_ahead():
    """A 5 kW limit beside 700 W of house load: no block may ask for more
    than 4.3 kW, so neither may the wait's rate."""
    s = Setup(20, 11.0, peak_w=5_000.0, prices=NOON_PRICES)
    gate = plan_gate(s.stamped, EV, WAITING)
    powers = [p for _, end, p in s.blocks() if end > WAITING]
    assert gate.covered and powers
    assert gate.top_block_w == pytest.approx(max(powers))
    assert 0.0 < gate.top_block_w <= s.room_w
    # without a peak limit the blocks run at the car's measured top, and
    # the last block's lower rest does not pull the rate down
    assert min(p for _, _, p in FIXED.blocks()) < TOP_W
    assert plan_gate(FIXED.stamped, EV, WAITING).top_block_w == (
        pytest.approx(TOP_W))


def test_a_past_block_and_a_sub_watt_rest_are_no_rate():
    stamped = dict(FIXED.stamped)
    first = DAY.replace(hour=11, minute=0)
    rest = DAY.replace(hour=14, minute=45)
    stamped["blocks"] = [
        {"id": EV, "start": first.isoformat(),
         "end": (first + timedelta(minutes=15)).isoformat(),
         "power_w": 20000.0},
        {"id": EV, "start": DAY.replace(hour=12, minute=15).isoformat(),
         "end": DAY.replace(hour=13, minute=15).isoformat(), "power_w": 9000.0},
        {"id": EV, "start": rest.isoformat(),
         "end": DEPARTURE.isoformat(), "power_w": 0.3},
    ]
    assert plan_gate(stamped, EV, WAITING).top_block_w == 9000.0
    # the rest alone ahead: no block asks for power, so no rate (0.0)
    stamped["blocks"] = [stamped["blocks"][0], stamped["blocks"][2]]
    gate = plan_gate(stamped, EV, WAITING)
    assert gate.covered and gate.next_block_start == rest
    assert gate.top_block_w == 0.0


def test_the_wait_check_counts_the_blocks_power():
    """The second line, on its own: 11 kWh, 4.3 kW blocks, cheap from
    12:00. At 10.6 kW the wait looked safe; at what the blocks run at it
    is not."""
    s = Setup(20, 11.0, peak_w=5_000.0, prices=NOON_PRICES)
    gate = plan_gate(s.stamped, EV, WAITING)
    hours = (DEPARTURE - gate.next_block_start).total_seconds() / 3600.0
    assert s.need <= TOP_W / 1000.0 * hours * DEPARTURE_WAIT_MARGIN
    kw = dict(wpa_table=TABLE, nominal_wpa=WPA, max_amps=20)
    assert not departure_wait_is_safe(gate, s.need, DEPARTURE, **kw)
    assert departure_wait_is_safe(
        PlanGate(covered=True, remaining_kwh=gate.remaining_kwh,
                 next_block_start=gate.next_block_start),
        s.need, DEPARTURE, **kw)


# ── review 3: a rate SEM measured, on the phases the floor runs on ──

#: a real car below the reporter's measured range: PROD's ladder in
#: ``watts_per_amp.py`` (8 A → 415 W/A, 0.6 of the nameplate)
REAL = {6: 415.0, 8: 415.0, 10: 513.0, 12: 625.0, 20: 529.6}
#: what SEM learns once the car has run at 6 A
LOW = {6: 415.0, 12: 625.0, 20: 529.6}


def _real_draw(amps):
    return predict_watts(REAL, amps, WPA)


def test_the_wait_check_wants_a_measured_setpoint_under_the_block():
    """The second line: a 4.3 kW block runs at 6 A, and SEM has measured
    nothing below 12 A. The nameplate's 4.14 kW there is no proof (this
    car takes 2.5 kW)."""
    s = Setup(20, 1.0, peak_w=5_000.0, prices=NOON_PRICES)
    gate = plan_gate(s.stamped, EV, WAITING)
    assert gate.next_block_start == DAY.replace(hour=12, minute=0)
    assert amps_that_fit(TABLE, gate.top_block_w, WPA, 20) < min(TABLE)
    assert not departure_wait_is_safe(gate, 1.0, DEPARTURE, wpa_table=TABLE,
                                      nominal_wpa=WPA, max_amps=20)


def test_the_wait_check_counts_a_measured_low_setpoint():
    """Once 6 A is measured (2.5 kW), 3 h from 12:00 hold 5.98 kWh at
    80 %: 5 kWh passes the second line, 8 kWh does not."""
    s = Setup(20, 5.0, peak_w=5_000.0, prices=NOON_PRICES, table=LOW)
    gate = plan_gate(s.stamped, EV, WAITING)
    kw = dict(wpa_table=LOW, nominal_wpa=WPA, max_amps=20)
    assert departure_wait_is_safe(gate, 5.0, DEPARTURE, **kw)
    assert not departure_wait_is_safe(gate, 8.0, DEPARTURE, **kw)


@pytest.mark.parametrize("table", [TABLE, LOW], ids=["from-12A", "from-6A"])
@pytest.mark.parametrize("need", [4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 11.0])
def test_under_a_peak_limit_a_real_car_lands_as_well_as_the_old_floor(
        table, need):
    """The car draws its real ladder, not SEM's table: 0.6 of the
    nameplate at 6–8 A. Never further from full than develop."""
    s = Setup(20, need, peak_w=5_000.0, prices=NOON_PRICES, table=table)
    new = s.run_to_departure(car_w=TOP_W, draw=_real_draw)
    old = s.run_to_departure(car_w=TOP_W, draw=_real_draw, old=True)
    assert new <= max(old, 0.1)


# ── review 4: a cap that changes by the hour ───────────────────────


@pytest.mark.parametrize("table", [TABLE, LOW], ids=["from-12A", "from-6A"])
@pytest.mark.parametrize("need", [4.0, 5.0, 8.0, 11.0])
def test_under_a_peak_limit_the_car_never_waits(table, need):
    """The limit leaves the car what the house leaves free, hour by hour,
    so no rate is proven: the even floor charges at once, as before.
    5 kWh on the measured 6 A passes the second line; the cap still
    holds it to the floor."""
    s = Setup(20, need, peak_w=5_000.0, prices=NOON_PRICES, table=table)
    d, plan, gate = s.decide_at(WAITING, s.need)
    assert gate.covered and not gate.in_block
    assert not plan.should_wait_for_cheap
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_DEADLINE


def _busy_noon(t):
    """2.5 kW of house load from 12:00 to 14:00, 0.7 kW else."""
    return 2500.0 if 12 <= t.hour < 14 else 700.0


@pytest.mark.parametrize("need", [12.0, 16.0, 18.0])
def test_a_busy_hour_under_the_limit_does_not_cost_the_departure(need):
    """The review's day: a 9 kW limit, 6.5 kW free from 12:00 to 14:00
    and 8.3 kW after. The best block ahead (8.3 kW) would prove 18 kWh,
    but 12:00 to 14:00 run at 9 A, which this car takes as 4.2 kW. With
    the cap the car does not wait, and lands as well as develop."""
    s = Setup(20, need, peak_w=9_000.0, prices=NOON_PRICES, home=_busy_noon)
    gate = plan_gate(s.stamped, EV, WAITING)
    assert gate.covered
    if need == 18.0:
        # the second line alone would let it wait: it counts the 8.3 kW
        assert gate.top_block_w > 6_500.0
        assert departure_wait_is_safe(gate, need, DEPARTURE, wpa_table=TABLE,
                                      nominal_wpa=WPA, max_amps=20)
    plan, _ = s.overlaid(WAITING, need)
    assert not plan.should_wait_for_cheap
    new = s.run_to_departure(car_w=TOP_W, draw=_real_draw)
    old = s.run_to_departure(car_w=TOP_W, draw=_real_draw, old=True)
    assert new <= max(old, 0.1)


def test_unknown_is_capped():
    """``apply_ev_overlay`` without the coordinator's word: no wait."""
    plan = FIXED.gap_plan(WAITING, FIXED.need)
    gate = plan_gate(FIXED.stamped, EV, WAITING)
    apply_ev_overlay(plan, gate, remaining_kwh=FIXED.need, watts_per_amp=WPA,
                     min_amps=MIN_A, max_amps=20, wpa_table=TABLE,
                     nominal_wpa=WPA)
    assert not plan.should_wait_for_cheap
    assert ev_overlay(gate, remaining_kwh=FIXED.need, reachable=True,
                      deadline_active=True, departure_floor=True,
                      watts_per_amp=WPA, min_amps=MIN_A, max_amps=20,
                      charge_end=DEPARTURE, departure_wpa_table=TABLE) == (
        False, 0)


class _CapHost(EVControlMixin):
    def __init__(self, peak_w, **config):
        self.config = config
        self._peak_w = peak_w

    def _get_peak_limit_w(self):
        if isinstance(self._peak_w, Exception):
            raise self._peak_w
        return self._peak_w


@pytest.mark.parametrize("peak_w, config, capped", [
    (math.inf, {}, False),
    # the reporter: unlimited, the guard watches but does not act
    (math.inf, {"phase_guard_enabled": True,
                "phase_guard_enforcement_enabled": False}, False),
    (math.inf, {"phase_guard_enabled": True,
                "phase_guard_enforcement_enabled": True}, True),
    (17_000.0, {}, True),
    # the grid operator's relay under an unlimited user setting
    (4_000.0, {"peak_limit_unlimited": True}, True),
    (RuntimeError("no load manager"), {}, True),
])
def test_what_caps_the_car(peak_w, config, capped):
    assert EVControlMixin._ev_rate_capped(_CapHost(peak_w, **config)) is capped


def test_each_site_says_whether_the_car_is_capped():
    """Both coordinator sites hand the helper the coordinator's own word;
    the default (capped) would switch the wait off for everyone."""
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "coordinator" / "coordinator.py").read_text(
        encoding="utf-8"))
    calls = [n for n in ast.walk(tree) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "apply_ev_overlay"]
    assert len(calls) >= 2
    for call in calls:
        kw = {k.arg: k.value for k in call.keywords}
        value = kw.get("rate_capped")
        assert (isinstance(value, ast.Call)
                and getattr(value.func, "attr", "") == "_ev_rate_capped"), (
            ast.unparse(call))


def test_the_plan_keeps_the_model_its_floor_used():
    plan = FIXED.gap_plan(WAITING, FIXED.need)
    assert plan.wpa_table == TABLE and plan.watts_per_amp == WPA
    assert FIXED.gap_plan(WAITING, FIXED.need, table=None).wpa_table is None


def test_the_wait_counts_with_the_floors_own_model():
    """The site's table is the charger's phases NOW (for the in-block
    floor). A plan sized without a table, because SEM measured on another
    phase count, gives no proof, whatever the site passes."""
    gate = plan_gate(FIXED.stamped, EV, WAITING)
    plan = FIXED.gap_plan(WAITING, FIXED.need, table=None)
    apply_ev_overlay(plan, gate, remaining_kwh=FIXED.need, watts_per_amp=WPA,
                     min_amps=MIN_A, max_amps=20, wpa_table=TABLE,
                     nominal_wpa=WPA, rate_capped=False)
    assert not plan.should_wait_for_cheap
    plan = FIXED.gap_plan(WAITING, FIXED.need)
    apply_ev_overlay(plan, gate, remaining_kwh=FIXED.need, watts_per_amp=WPA,
                     min_amps=MIN_A, max_amps=20, wpa_table=None,
                     nominal_wpa=WPA, rate_capped=False)
    assert plan.should_wait_for_cheap


#: SEM's one-phase table for a car it set to one phase in thin sun
ONE_PHASE = {8: 225.0, 12: 228.0, 16: 229.0}


class _PhaseHost(EVControlMixin):
    """A charger that switches phases: the grid charge runs on three, the
    W/A learner believes ``believed``."""

    def __init__(self, believed, ok=True):
        self.config = {"ev_target_time": "15:00"}
        tm = MagicMock()
        tm.is_night_mode.return_value = False
        tm.get_night_window.return_value = ("17:06", "07:00")
        tm.get_night_end_time.return_value = "07:00"
        tm.get_night_window_hours.return_value = 13.9
        self.time_manager = tm
        self._ev_device = None
        self._surplus_controller = None
        self._tariff_provider = None
        self._night_committed_w = 0.0
        self._phase_capable = {"zap": True}
        self._phase_grid_phases = {"zap": 3}
        self._phase_believed = {"zap": believed}
        self._belief = (believed, ok)
        self.tables = {1: ONE_PHASE, 3: TABLE}

    def _mode_allows_night_charging(self, charger_cfg):
        return True

    def _tariff_optimized_for(self, charger_cfg):
        return True

    def _planning_peak_w(self):
        return math.inf

    def _expected_night_home_w(self, energy, window_hours=8.0):
        return 300.0

    def _wpa_phases_for(self, cid, cfg=None):
        assert cid == "zap"
        return self._belief

    def _wpa_table_for(self, cid):
        # no check of its own here: the helper's ``ok`` clause must refuse
        phases, _ok = self._belief
        return dict(self.tables.get(phases) or {})


PHASE_CFG = {"id": "zap", "ev_target_time": "15:00",
             "finish_by_departure": True, "ev_max_current": 32,
             "ev_phases": 3, "ev_voltage": 230,
             "ev_phase_switching_enabled": True}


#: 30 kWh from 11:20 to 15:00: 8.2 kW
PHASE_NEED = 30.0


def _phase_plan(believed, ok=True):
    with patch("custom_components.solar_energy_management.coordinator."
               "ev_control.dt_util.now", return_value=WAITING):
        return EVControlMixin._compute_night_plan(
            _PhaseHost(believed, ok), PHASE_CFG, PHASE_NEED, night_over=True)


def test_a_table_from_another_phase_count_is_not_read():
    """The grid charge runs on three phases; the learner's table is the
    one-phase one. 8.2 kW is 12 A by the three-phase nameplate. Read at
    229 W/A against 690, the floor asked 32 A, the charger max: almost
    three times the power, at day price."""
    plan = _phase_plan(1)
    assert plan.to_departure and plan.watts_per_amp == WPA
    assert plan.wpa_table is None
    hours = (DEPARTURE - WAITING).total_seconds() / 3600.0
    assert plan.deadline_amps == math.ceil(
        PHASE_NEED * 1000 / hours / WPA) == 12


def test_a_table_on_the_plans_phase_count_is_read():
    """The same 8.2 kW by the three-phase table: 12 A buys 7.5 kW, so
    the floor is 14 A (8.27 kW)."""
    plan = _phase_plan(3)
    assert plan.wpa_table == TABLE
    assert plan.deadline_amps == 14
    assert predict_watts(TABLE, 13, WPA) < PHASE_NEED * 1000 / (
        (DEPARTURE - WAITING).total_seconds() / 3600.0)


def test_a_disputed_belief_is_no_table():
    assert _phase_plan(3, ok=False).wpa_table is None
    assert _phase_plan(None, ok=False).wpa_table is None


def test_the_wait_counts_the_plans_nameplate_not_the_sites():
    """The site's nominal W/A is the phases NOW (one phase in thin sun:
    230). The wait counts the plan's (three phases, 690): at 230 the
    20 A bucket would be capped to 4.6 kW and the car would not wait."""
    gate = plan_gate(FIXED.stamped, EV, WAITING)
    plan = FIXED.gap_plan(WAITING, FIXED.need)
    apply_ev_overlay(plan, gate, remaining_kwh=FIXED.need, watts_per_amp=WPA,
                     min_amps=MIN_A, max_amps=20, wpa_table=TABLE,
                     nominal_wpa=230.0, rate_capped=False)
    assert plan.should_wait_for_cheap


def test_the_night_floor_ignores_the_table():
    """At night the floor counts the nameplate, as before: 11.1 kW over
    the 4.5 h to a 06:30 Charge by is 17 A; by the table it would be
    21 A."""
    kw = dict(now=DAY.replace(hour=2, minute=0), remaining_to_min_kwh=50.0,
              min_amps=MIN_A, max_amps=54, watts_per_amp=WPA,
              night_end="07:00", night_start="17:06",
              deadline_at=DAY.replace(hour=6, minute=30))
    night = plan_night_charge(wpa_table=TABLE, **kw)
    assert not night.to_departure and night.deadline_active
    assert night.deadline_amps == plan_night_charge(**kw).deadline_amps == 17
    assert predict_watts(TABLE, 17, WPA) < 50_000.0 / 4.5


@pytest.mark.parametrize("need", [6.0, 8.0, 9.0, 10.5, 11.0])
@pytest.mark.parametrize("share", [1.0, 0.85, 0.8])
def test_under_a_peak_limit_the_car_lands_as_well_as_the_old_floor(
        need, share):
    """The car draws ``share`` of its table at every setpoint, inside the
    4.3 kW the limit leaves."""
    s = Setup(20, need, peak_w=5_000.0, prices=NOON_PRICES)
    new = s.run_to_departure(car_w=TOP_W, share=share)
    old = s.run_to_departure(car_w=TOP_W, share=share, old=True)
    assert new <= max(old, 0.1)


def test_the_wait_counts_the_chargers_own_max():
    """The night plan caps Max Amps at the charger's own rating. A 16 A
    box has not shown what 20 A buys, so the 20 A reading is no proof."""
    need = 18.0
    gate = PlanGate(covered=True, remaining_kwh=30.0,
                    next_block_start=DAY.replace(hour=12, minute=15))

    def overlaid(plan_max):
        plan = plan_night_charge(
            now=WAITING, remaining_to_min_kwh=need, min_amps=MIN_A,
            max_amps=plan_max, watts_per_amp=WPA, target_time="15:00",
            night_end="07:00", night_start="17:06", tariff_optimized=True,
            peak_managed_amps=plan_max, deadline_at=DEPARTURE,
            finish_by_departure=True, night_over=True, wpa_table=TABLE)
        apply_ev_overlay(plan, gate, remaining_kwh=need, watts_per_amp=WPA,
                         min_amps=MIN_A, max_amps=20, wpa_table=TABLE,
                         nominal_wpa=WPA, rate_capped=False)
        return plan
    # 2.75 h from 12:15 at 80 %: 20 A (10.6 kW) gives 23.3 kWh, 12 A
    # (7.5 kW) gives 16.5 kWh — under the 18 kWh owed
    assert overlaid(20).max_amps == 20
    assert overlaid(20).should_wait_for_cheap
    assert overlaid(16).max_amps == 16
    assert not overlaid(16).should_wait_for_cheap


# ── what still ends the wait ───────────────────────────────────────


def test_blocks_that_cannot_hold_the_need_give_back_the_even_floor():
    gate = plan_gate(FIXED.stamped, EV, WAITING)
    need = gate.remaining_kwh + 1.0
    d, plan, _ = FIXED.decide_at(WAITING, need)
    assert not plan.should_wait_for_cheap
    assert d.reason_code == RC.CHARGER_DEADLINE


def test_an_unreachable_departure_is_never_held():
    now = DAY.replace(hour=14, minute=0)
    plan, gate = FIXED.overlaid(now, 40.0)
    assert plan.reachable is False and gate.covered
    assert not plan.should_wait_for_cheap


def test_an_uncovered_gap_keeps_the_even_floor():
    """No plan (actuation off, a stale stamp): the #1308 floor, as before."""
    plan = FIXED.gap_plan(WAITING, FIXED.need)
    assert apply_ev_overlay(
        plan, plan_gate(None, EV, WAITING), remaining_kwh=FIXED.need,
        watts_per_amp=WPA, min_amps=MIN_A, max_amps=20,
        wpa_table=TABLE, nominal_wpa=WPA) == (False, 0)
    assert decide(FIXED.view(plan, FIXED.need)).reason_code == RC.CHARGER_DEADLINE


def test_a_forcing_deadline_at_night_still_outranks_the_plan():
    """Only the departure floor yields. A Charge by before the night end
    keeps its seniority (#638 G4)."""
    gate = plan_gate(FIXED.stamped, EV, WAITING)
    for kw in ({"departure_floor": False}, {}):
        assert ev_overlay(gate, remaining_kwh=FIXED.need, reachable=True,
                          deadline_active=True, watts_per_amp=WPA,
                          min_amps=MIN_A, max_amps=20, wpa_table=TABLE,
                          nominal_wpa=WPA, charge_end=DEPARTURE,
                          **kw) == (False, 0)


def test_the_helper_writes_what_the_night_path_reads():
    plan, gate = FIXED.overlaid(WAITING, FIXED.need)
    assert plan.should_wait_for_cheap is True
    assert plan.next_cheap_start == gate.next_block_start
    assert "outside the planned window" in plan.reason
    start, _, power_w = FIXED.blocks()[0]
    plan, _ = FIXED.overlaid(start + timedelta(minutes=5), FIXED.need - 1.0)
    assert plan.should_wait_for_cheap is False
    assert plan.deadline_amps == 20
    assert "floor 20A" in plan.reason


# ── the wiring ─────────────────────────────────────────────────────


def test_only_the_helper_calls_the_overlay():
    """One place reads the plan's flags: every coordinator site goes
    through ``apply_ev_overlay``."""
    direct = [(f, n) for f, n, _ in call_sites("ev_overlay")]
    assert direct and all(f.endswith("energy_plan_actuation.py")
                          for f, _ in direct), direct
    helper = [(f, n) for f, n, _ in call_sites("apply_ev_overlay")]
    assert len([f for f, _ in helper if f.endswith("coordinator.py")]) >= 2


def test_each_site_overlays_the_plan_it_just_computed():
    """The plan handed to the helper is the one the same function got from
    ``_compute_night_plan`` — never another charger's or a context copy."""
    root = Path(__file__).resolve().parent.parent
    tree = ast.parse((root / "coordinator" / "coordinator.py").read_text(
        encoding="utf-8"))
    seen = 0
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        computed = {
            t.id for n in ast.walk(fn) if isinstance(n, ast.Assign)
            and isinstance(n.value, ast.Call)
            and getattr(n.value.func, "attr", "") == "_compute_night_plan"
            for t in n.targets if isinstance(t, ast.Name)}
        for n in ast.walk(fn):
            if (isinstance(n, ast.Call)
                    and getattr(n.func, "id", "") == "apply_ev_overlay"):
                arg = n.args[0]
                assert isinstance(arg, ast.Name) and arg.id in computed, (
                    fn.name, ast.unparse(arg), computed)
                seen += 1
    assert seen >= 2
