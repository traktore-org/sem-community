"""#1321 — every plan block says why it is there, and the plan says what it saves.

The packer already decides each block for one reason (cheapest hours, a
deadline, the late top-up, the sun, the battery). It now publishes that
reason as a code the card turns into words. The plan also publishes
``cost_if_now`` (the same grid energy bought from the first slot on at full
power) and ``saved`` = cost_if_now − total_cost.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.energy_planner import (
    REASON_CODES, Demand, LedgerSlot, build_night_ledger, pack_night,
    plan_savings,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    plan_blocks,
)
from custom_components.solar_energy_management.sensor import _energy_plan_attrs

T0 = datetime(2026, 11, 10, 22, 0)
ROOT = Path(__file__).resolve().parent.parent


def _ledger(prices, sun=()):
    """Hourly slots from 22:00, no house load, no peak limit — the way the
    coordinator builds them (no per-slot cap unless it is a sun slot)."""
    slots = [LedgerSlot(start=T0 + timedelta(hours=n),
                        end=T0 + timedelta(hours=n + 1), price=p,
                        level_cheap=p is not None and p <= 0.12,
                        tariff_cheap=p is not None and p <= 0.12,
                        cap_override_w=(5000.0 if n in sun else None))
             for n, p in enumerate(prices)]
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                              max_discharge_w=5000.0, peak_limit_w=0.0)


def _ev(kwh=8.0, **kw):
    return Demand(id="ev:1", kind="ev", energy_kwh=kwh, max_power_w=4000,
                  min_power_w=1400, **kw)


def _published(plan, ledger_house_cost=0.0):
    """What the coordinator stamps, projected the way the sensor does."""
    total = (None if plan.total_cost is None
             else round(plan.total_cost + ledger_house_cost, 4))
    stash = {"computed_at": T0.isoformat(), "fits": plan.fits,
             "total_cost": total, "blocks": plan_blocks(plan.allocations),
             **plan_savings(total, plan.cost_if_now, ledger_house_cost,
                            bool(plan.allocations))}
    return _energy_plan_attrs(stash)


def _en_keys():
    tr = json.loads((ROOT / "dashboard" / "translations.json").read_text(
        encoding="utf-8"))
    return tr["en"]


class TestReasonPerBlock:
    def test_cheap_window_blocks_carry_a_known_code(self):
        plan = pack_night([_ev()], _ledger([0.30, 0.30, 0.10, 0.10, 0.30]))
        attrs = _published(plan)
        assert attrs["blocks"], "the EV must be planned"
        for b in attrs["blocks"]:
            assert b["reason"] == "cheapest_hours"
            assert b["reason_params"]["price"] == pytest.approx(0.10)

    def test_every_code_has_words(self):
        en = _en_keys()
        missing = [c for c in REASON_CODES if f"next_reason_{c}" not in en]
        assert not missing, missing

    def test_deadline_pick_says_before_deadline(self):
        plan = pack_night([_ev(4.0, deadline=T0 + timedelta(hours=2))],
                          _ledger([0.30, 0.28, 0.10, 0.08]))
        codes = {a.code for a in plan.allocations}
        assert codes == {"before_deadline"}
        assert all(a.params["deadline"] == (T0 + timedelta(hours=2)).isoformat()
                   for a in plan.allocations)

    def test_late_top_up_says_so(self):
        plan = pack_night(
            [_ev(6.0, deadline=T0 + timedelta(hours=4), late_s=3600)],
            _ledger([0.10, 0.10, 0.30, 0.30]))
        late = [a for a in plan.allocations if a.late]
        assert late and all(a.code == "top_up_late" for a in late)
        assert {a.code for a in plan.allocations if not a.late} == {"cheapest_hours"}

    def test_one_block_sun_and_battery(self):
        block = Demand(id="load:p", kind="load", energy_kwh=2.0,
                       max_power_w=1000, min_power_w=1000, contiguous=True)
        plan = pack_night([block], _ledger([0.30, 0.10, 0.10, 0.30]))
        assert {a.code for a in plan.allocations} == {"one_block"}

        plan = pack_night([_ev(4.0)], _ledger([0.30, 0.05, 0.30], sun=(1,)))
        assert {a.code for a in plan.allocations} == {"solar"}

        batt = Demand(id="load:h", kind="load", energy_kwh=1.0,
                      max_power_w=1000, source="battery")
        led = [LedgerSlot(start=T0, end=T0 + timedelta(hours=1), price=0.3)]
        led = build_night_ledger(led, soc_kwh=5.0, floor_kwh=0.0,
                                 max_discharge_w=5000.0, peak_limit_w=0.0)
        plan = pack_night([batt], led, max_discharge_w=5000.0)
        assert {a.code for a in plan.allocations} == {"from_battery"}

    def test_cheap_level_load_says_cheap_hours(self):
        load = Demand(id="load:w", kind="load", energy_kwh=1.0,
                      max_power_w=1000, min_power_w=1000,
                      needs_cheap_level=True)
        plan = pack_night([load], _ledger([0.30, 0.10, 0.30]))
        assert {a.code for a in plan.allocations} == {"cheap_hours"}


class TestSavings:
    def test_waiting_for_cheap_hours_saves(self):
        plan = pack_night([_ev()], _ledger([0.30, 0.30, 0.10, 0.10, 0.30]))
        # now: 4 kWh at 0.30 in each of the first two hours = 2.40
        assert plan.cost_if_now == pytest.approx(2.40)
        attrs = _published(plan, ledger_house_cost=0.50)
        assert attrs["cost_if_now"] == pytest.approx(2.90)
        assert attrs["saved"] == pytest.approx(1.60)
        assert attrs["saved"] == pytest.approx(
            attrs["cost_if_now"] - attrs["total_cost"])

    def test_flat_tariff_saves_nothing(self):
        plan = pack_night([_ev()], _ledger([0.20] * 5))
        attrs = _published(plan)
        assert attrs["saved"] == 0.0
        assert attrs["cost_if_now"] == pytest.approx(attrs["total_cost"])

    def test_no_prices_no_savings(self):
        # nothing priced: the grid demand cannot be placed, total unknown
        plan = pack_night([_ev(unpriced_ok=True)], _ledger([None] * 4))
        attrs = _published(plan)
        assert "saved" not in attrs and "cost_if_now" not in attrs

    def test_unpriced_hour_now_leaves_both_out(self):
        # the plan is priced, but buying NOW would hit an hour with no price
        plan = pack_night([_ev(4.0)], _ledger([None, 0.10, 0.20]))
        assert plan.total_cost is not None
        assert plan.cost_if_now is None
        attrs = _published(plan)
        assert "saved" not in attrs and "cost_if_now" not in attrs

    def test_no_grid_blocks_leave_both_out(self):
        assert plan_savings(0.5, 0.0, 0.5, False) == {
            "cost_if_now": None, "saved": None}
        assert plan_savings(None, 1.0, 0.0, True)["saved"] is None
        assert plan_savings(1.0, 1.0, None, True)["saved"] is None


def test_merged_run_keeps_one_reason_and_shared_params():
    plan = pack_night([_ev(12.0)], _ledger([0.30, 0.10, 0.11, 0.12, 0.30]))
    attrs = _published(plan)
    runs = attrs["blocks"]
    assert len(runs) == 1                      # three hours, one bar
    assert runs[0]["reason"] == "cheapest_hours"
    assert "price" not in runs[0].get("reason_params", {})  # prices differ
