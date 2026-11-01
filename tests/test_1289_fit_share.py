"""#1289 — the wait before a planned block accepts what the planner calls "fits".

The planner calls a demand "fits" at 99.9 % of the need; the wait ended unless
the blocks held the whole need (to 1e-6 kWh). One 11 kW hour and a need of
11.008 kWh: the plan said "fits", the wait ended, the car charged outside its
block. The wait now accepts the same 99.9 %.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coord_mod,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay,
    plan_blocks,
    plan_gate,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
)
from custom_components.solar_energy_management.tests.synthetic_night import (
    PriceSlot, pack_flat_night,
)

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE
STAMP = datetime(2026, 7, 29, 22, 0, tzinfo=TZ)
T0 = datetime(2026, 7, 29, 22, 0, tzinfo=TZ)
EV = "ev:ev_charger"
NEED_KWH = 11.008          # the issue's example: one 11 kW hour, 8 Wh more
MAX_W = 11000.0
WPA = MAX_W / 16


def _at(h, m=0):
    return STAMP.replace(hour=h, minute=m) + timedelta(days=1 if h < 12 else 0)


@pytest.fixture
def plan():
    """The real packer and serializer: 11.008 kWh, one 11 kW hour (23:00)
    before the deadline. The packer places 11.0 kWh and says "fits"."""
    ev = Demand(id=EV, kind="ev", energy_kwh=NEED_KWH, max_power_w=MAX_W,
                min_power_w=MAX_W / 2, priority=0,
                deadline=T0 + timedelta(hours=2))
    slots = [PriceSlot(start=T0 + timedelta(hours=n),
                       end=T0 + timedelta(hours=n + 1),
                       price=0.30 if n == 0 else 0.10,
                       cap_w=0.0 if n == 0 else MAX_W) for n in range(3)]
    packed = pack_flat_night([ev], slots)
    row = next(r for r in packed.results if r.demand_id == EV)
    assert row.status == "fits"
    assert row.planned_kwh == pytest.approx(11.0)
    blocks = plan_blocks(packed.allocations)
    assert [(b["start"][11:16], b["end"][11:16]) for b in blocks] == [
        ("23:00", "00:00")], "the scenario needs one full-power hour"
    return {
        "computed_at": T0.isoformat(),
        "demands": [{"id": EV, "status": row.status}],
        "slots": [{"start": slots[0].start.isoformat(),
                   "end": slots[-1].end.isoformat()}],
        "blocks": blocks,
    }


def _overlay(gate, need=NEED_KWH, **kw):
    args = dict(remaining_kwh=need, reachable=True, deadline_active=False,
                watts_per_amp=WPA, min_amps=6, max_amps=16)
    args.update(kw)
    return ev_overlay(gate, **args)


# ── #1289 ──

def test_a_plan_the_planner_calls_fits_keeps_the_car_waiting(plan):
    gate = plan_gate(plan, EV, T0.replace(hour=22, minute=15))
    assert gate.covered and not gate.in_block
    assert _overlay(gate) == (True, 0), (
        "the plan says fits, yet the wait ended and the car charges "
        "outside its block (#1289)")


def test_a_real_shortage_still_releases(plan):
    gate = plan_gate(plan, EV, T0.replace(hour=22, minute=15))
    assert _overlay(gate, need=11.5) == (False, 0)


def test_a_shortage_just_past_the_planner_share_releases(plan):
    gate = plan_gate(plan, EV, T0.replace(hour=22, minute=15))
    assert _overlay(gate, need=11.0 / 0.998) == (False, 0)


def test_the_wait_and_the_planner_share_one_number():
    from custom_components.solar_energy_management.coordinator import (
        energy_plan_actuation as act,
        energy_planner as planner,
    )
    assert act.FIT_EPS is planner.FIT_EPS
