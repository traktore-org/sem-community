"""#1282 — a complete plan must not turn short through whole-watt rounding.

The coordinator stored each block as ``round(power_w, 0)``. ``plan_gate``
rebuilds the deliverable kWh from those watts and ``ev_overlay`` compares it
with the unrounded need (tolerance 1e-6 kWh). A 5.2834 kWh need packed at
5283.4 W came back as 5.2830 kWh, a false 0.4 Wh shortage, and the wait
released: the car charged between its blocks.

The test walks the real chain: ``pack_night`` -> ``plan_blocks`` (the one
serializer the coordinator calls) -> ``plan_gate`` -> ``ev_overlay``.
"""
import ast
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay, plan_blocks, plan_gate,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)

TZ = ZoneInfo("Europe/Zurich")
DAY = datetime(2026, 10, 31, tzinfo=TZ)
NOW = DAY.replace(hour=0, minute=15)
END = DAY.replace(hour=7)
NEED = 5.2834
MAX_W = 5283.4


def _plan(need=NEED, max_w=MAX_W):
    slots, t = [], DAY.replace(hour=1)
    while t < END:
        slots.append(LedgerSlot(start=t, end=t + timedelta(hours=1),
                                price=0.30 if t.hour != 3 else 0.10,
                                level_cheap=(t.hour == 3), home_w=400.0))
        t += timedelta(hours=1)
    ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                max_discharge_w=0.0, peak_limit_w=20000.0)
    demand = Demand(id="ev:ev_charger", kind="ev", energy_kwh=need,
                    max_power_w=max_w, min_power_w=1380.0,
                    deadline=DAY.replace(hour=6), priority=1, source="grid",
                    min_run_s=900, min_gap_s=900)
    return pack_night([demand], ledger, peak_limit_w=20000.0), ledger


def _stamp(plan, ledger):
    return {
        "computed_at": NOW.isoformat(),
        "fits": plan.fits,
        "demands": [{"id": r.demand_id, "status": r.status}
                    for r in plan.results],
        "slots": [{"start": s.start.isoformat(), "end": s.end.isoformat()}
                  for s in ledger],
        "blocks": plan_blocks(plan.allocations),
    }


def _overlay(shadow, remaining):
    gate = plan_gate(shadow, "ev:ev_charger", NOW)
    return gate, ev_overlay(gate, remaining_kwh=remaining, reachable=True,
                            deadline_active=False, watts_per_amp=690.0,
                            min_amps=6, max_amps=32)


class TestAPlanThatFitsKeepsItsWait:
    def test_a_complete_plan_holds_the_wait_outside_its_block(self):
        plan, ledger = _plan()
        assert plan.fits
        gate, (wait, floor) = _overlay(_stamp(plan, ledger), NEED)
        assert gate.covered and not gate.in_block
        assert wait is True and floor == 0

    def test_the_gate_sees_what_the_planner_placed(self):
        plan, ledger = _plan()
        gate = plan_gate(_stamp(plan, ledger), "ev:ev_charger", NOW)
        placed = sum(a.energy_kwh for a in plan.allocations)
        assert gate.remaining_kwh == pytest.approx(placed, abs=1e-6)

    @pytest.mark.parametrize("need", [1.5013, 1.7777, 3.14159, 5.2834, 7.9999])
    def test_odd_needs_never_fall_short_by_rounding(self, need):
        plan, ledger = _plan(need=need, max_w=need * 1000.0)
        assert plan.fits
        _, (wait, _) = _overlay(_stamp(plan, ledger), need)
        assert wait is True


class TestARealShortageStillReleases:
    def test_a_tenth_of_a_kwh_short_releases_the_wait(self):
        plan, ledger = _plan()
        _, (wait, _) = _overlay(_stamp(plan, ledger), NEED + 0.1)
        assert wait is False

    def test_an_urgent_deadline_releases_the_wait(self):
        plan, ledger = _plan()
        gate = plan_gate(_stamp(plan, ledger), "ev:ev_charger", NOW)
        assert ev_overlay(gate, remaining_kwh=NEED, reachable=True,
                          deadline_active=True, watts_per_amp=690.0,
                          min_amps=6, max_amps=32) == (False, 0)

    def test_an_unreachable_target_releases_the_wait(self):
        plan, ledger = _plan()
        gate = plan_gate(_stamp(plan, ledger), "ev:ev_charger", NOW)
        assert ev_overlay(gate, remaining_kwh=NEED, reachable=False,
                          deadline_active=False, watts_per_amp=690.0,
                          min_amps=6, max_amps=32) == (False, 0)


class TestTheCoordinatorUsesTheOneSerializer:
    def test_no_whole_watt_rounding_of_block_power_is_left(self):
        src = Path(coord.__file__).read_text(encoding="utf-8")
        tree = ast.parse(src)
        bad = [n.lineno for n in ast.walk(tree)
               if isinstance(n, ast.Call) and getattr(n.func, "id", "") == "round"
               and n.args and isinstance(n.args[0], ast.Attribute)
               and n.args[0].attr == "power_w"
               and len(n.args) > 1 and isinstance(n.args[1], ast.Constant)
               and n.args[1].value == 0]
        assert not bad, f"block power rounded to whole watts at {bad}"

    def test_the_blocks_row_keeps_the_late_flag_and_the_price(self):
        plan, _ = _plan()
        row = plan_blocks(plan.allocations)[0]
        assert set(row) >= {"id", "start", "end", "power_w", "price"}
