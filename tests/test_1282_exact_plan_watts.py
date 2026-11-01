"""#1282 — the plan keeps exact watts; only what a person reads is rounded.

@Elmardus (SEM 2.2.0-beta.29, SmartEVSE): a full plan let the car charge for
about two minutes between its blocks, at the quarter-hour re-plans.

``_shadow_energy_plan`` wrote each block as ``round(a.power_w, 0)``. The
gates add those watts up again (``plan_gate``) and compare the sum with the
exact need, to within 0.000001 kWh (``ev_overlay``, ``load_verdict``). A
5283.4 W block became 5283 W, so a plan that held the whole 5.2834 kWh read
5.2830 kWh: 0.4 Wh short. The wait ended and the reactive floor started
the car. Once it had drawn 0.4 Wh the plan covered it again — the 30-second
flip the reporter recorded.

The plan now keeps the packer's watts. The card and the battery schedule
entity round for display, as before, and the setpoint a block asks for stays
whole watts, as before.
"""
from __future__ import annotations

import ast
import copy
import inspect
import textwrap
from datetime import datetime, timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coord_mod,
)
from custom_components.solar_energy_management.coordinator import (
    energy_plan_actuation,
)
from custom_components.solar_energy_management.coordinator import ev_night_targets
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    schedule_view_from_plan,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay,
    merge_load_gates,
    plan_gate,
)
from custom_components.solar_energy_management.sensor import _energy_plan_attrs

from .test_638_shadow_mode import _fake_self, _power, _scheduler

TZ = coord_mod.dt_util.DEFAULT_TIME_ZONE
STAMP = datetime(2026, 7, 29, 22, 0, tzinfo=TZ)
NEED_KWH = 5.2834
#: the learned draw at 16 A — 330.2125 W/A, not a whole watt
MAX_W = 5283.4
WPA = MAX_W / 16
EV = "ev:ev_charger"


@pytest.fixture
def plan(monkeypatch):
    """The reporter's night through the REAL packer and serializer: 5.2834
    kWh at a learned 5283.4 W, packed into the one cheap hour 02:00–03:00."""
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: STAMP)
    monkeypatch.setattr(ev_night_targets, "build_night_target_map",
                        lambda coord, energy: {"ev_charger": NEED_KWH})
    fake = _fake_self(devices=[])
    fake._get_peak_limit_w = lambda: 11000.0     # the cap never binds
    fake._ev_watts_for_amps = lambda cid, cfg, amps: float(amps) * WPA
    assert SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(deficit=0.0), energy=MagicMock(), power=_power())
    out = fake._energy_plan_shadow
    ev_blocks = [b for b in out["blocks"] if b["id"] == EV]
    assert [(b["start"][11:16], b["end"][11:16]) for b in ev_blocks] == [
        ("02:00", "03:00")], "the scenario needs one full-power hour"
    assert next(d for d in out["demands"] if d["id"] == EV)["status"] == "fits"
    return out


def _at(h, m=0):
    return STAMP.replace(hour=h, minute=m) + timedelta(days=1 if h < 12 else 0)


def _overlay(gate, need=NEED_KWH, **kw):
    args = dict(remaining_kwh=need, reachable=True, deadline_active=False,
                watts_per_amp=WPA, min_amps=6, max_amps=16)
    args.update(kw)
    return ev_overlay(gate, **args)


def _rounded(plan_dict):
    """The plan as the old serializer wrote it."""
    old = copy.deepcopy(plan_dict)
    for b in old["blocks"]:
        b["power_w"] = round(b["power_w"], 0)
    return old


# ── The reported fault ──

def test_the_plan_keeps_the_packers_watts(plan):
    ev = next(b for b in plan["blocks"] if b["id"] == EV)
    assert ev["power_w"] == pytest.approx(MAX_W, abs=1e-9), (
        "the plan rounded its watts — the gates add them up again")


def test_a_full_plan_keeps_the_car_waiting_between_blocks(plan):
    gate = plan_gate(plan, EV, _at(0, 15))
    assert gate.covered and not gate.in_block
    assert gate.remaining_kwh == pytest.approx(NEED_KWH, abs=1e-6)
    assert _overlay(gate) == (True, 0), (
        "the plan holds the whole need, yet the wait ended — the car "
        "starts outside its block (#1282)")


def test_the_old_rounding_did_release_the_wait(plan):
    """Twin: the same night with whole watts is what the reporter saw.
    Without it the test above could pass for another reason."""
    gate = plan_gate(_rounded(plan), EV, _at(0, 15))
    assert gate.covered
    assert _overlay(gate) == (False, 0)


# ── What must still release the wait (the reporter's own list) ──

def test_a_real_shortage_still_releases(plan):
    gate = plan_gate(plan, EV, _at(0, 15))
    assert _overlay(gate, need=NEED_KWH + 0.1) == (False, 0)


def test_a_forcing_deadline_still_releases(plan):
    gate = plan_gate(plan, EV, _at(0, 15))
    assert _overlay(gate, deadline_active=True) == (False, 0)


def test_an_unreachable_target_still_releases(plan):
    gate = plan_gate(plan, EV, _at(0, 15))
    assert _overlay(gate, reachable=False) == (False, 0)


# ── Inside the block nothing changes ──

def test_the_block_still_asks_for_whole_watts(plan):
    gate = plan_gate(plan, EV, _at(2, 30))
    assert gate.in_block
    assert gate.block_power_w == 5283.0, (
        "a setpoint goes out in whole watts, as before")
    assert _overlay(gate) == _overlay(plan_gate(_rounded(plan), EV, _at(2, 30)))


# ── The load gate reads the same blocks ──

def _load_plan(power_w):
    """A grid load's two blocks around a gap, the shape the serializer
    writes: 22:00–23:00 and 01:00–02:00 at the calibrated draw."""
    def _iso(h):
        return _at(h).isoformat()
    return {
        "computed_at": STAMP.isoformat(),
        "demands": [{"id": "load:boiler", "status": "fits"}],
        "slots": [{"start": STAMP.isoformat(), "end": _iso(7)}],
        "blocks": [
            {"id": "load:boiler", "start": _iso(22), "end": _iso(23),
             "power_w": power_w},
            {"id": "load:boiler", "start": _iso(1), "end": _iso(2),
             "power_w": power_w},
        ],
    }


def test_a_load_keeps_its_hold_on_exact_watts():
    rated = 800.4
    # One hour ran in the first block; one hour of deficit is left — the
    # coordinator's own formula (deficit hours × rated W).
    deficit_kwh = 1.0 * rated / 1000.0
    absent = plan_gate(None, "comfort:boiler", _at(23, 30))
    held = merge_load_gates(plan_gate(_load_plan(rated), "load:boiler",
                                      _at(23, 30)),
                            absent, deficit_kwh=deficit_kwh)
    assert held is not None and held.hold, (
        "the second block holds the whole deficit — the load must wait")
    # twin: the whole-watt block the old serializer wrote ran it early
    early = merge_load_gates(plan_gate(_load_plan(round(rated, 0)),
                                       "load:boiler", _at(23, 30)),
                             absent, deficit_kwh=deficit_kwh)
    assert early is None


# ── What a person reads stays whole watts ──

def test_the_card_still_shows_whole_watts(plan):
    blocks = _energy_plan_attrs(plan)["blocks"]
    assert [b["power_w"] for b in blocks if b["id"] == EV] == [5283.0]


def test_the_card_rounding_passes_odd_values_through():
    odd = {"demands": [1], "blocks": [
        {"id": "a", "start": "s", "end": "e", "power_w": None},
        {"id": "b", "start": "s", "end": "e", "power_w": "junk"},
    ]}
    shown = [b["power_w"] for b in _energy_plan_attrs(odd)["blocks"]]
    assert shown == [None, "junk"]


def test_two_runs_that_differ_below_a_watt_still_merge_on_the_card():
    """The card merges back-to-back runs of one power. Rounding before the
    merge keeps the bars it drew before #1282."""
    def _iso(h):
        return _at(h).isoformat()
    plan_dict = {"demands": [1], "blocks": [
        {"id": EV, "start": _iso(1), "end": _iso(2), "power_w": 5283.4},
        {"id": EV, "start": _iso(2), "end": _iso(3), "power_w": 5283.2},
    ]}
    blocks = _energy_plan_attrs(plan_dict)["blocks"]
    assert len(blocks) == 1 and blocks[0]["power_w"] == 5283.0


def test_the_battery_schedule_entity_shows_whole_watts():
    plan_dict = {"blocks": [{"id": "battery", "start": _at(1).isoformat(),
                             "end": _at(2).isoformat(), "power_w": 2345.678,
                             "price": 0.1}]}
    view = schedule_view_from_plan(plan_dict, _at(0))
    row = view["slots"][0]
    assert row["battery_w"] == 2346.0 and row["total_w"] == 2346.0
    assert view["total_battery_kwh"] == 2.35


# ── Guard: no field a plan gate reads is rounded where the plan is written ──

def _gate_block_keys():
    """Every key ``plan_gate`` reads from a block row (``b.get("…")``)."""
    tree = ast.parse(textwrap.dedent(inspect.getsource(plan_gate)))
    keys = {n.args[0].value for n in ast.walk(tree)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
            and n.func.attr == "get" and isinstance(n.func.value, ast.Name)
            and n.func.value.id == "b" and n.args
            and isinstance(n.args[0], ast.Constant)}
    assert {"id", "start", "end", "power_w"} <= keys, keys
    return keys


_CUTS = {"round", "int", "floor", "ceil", "trunc"}


def _rounded_gate_fields(source):
    """(key, line) for each gate-read field of a block dict that the source
    writes through a rounding call."""
    keys = _gate_block_keys()
    tree = ast.parse(textwrap.dedent(source))
    found, bad = 0, []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        names = {k.value for k in node.keys if isinstance(k, ast.Constant)}
        if not keys <= names:
            continue
        found += 1
        for k, v in zip(node.keys, node.values, strict=True):
            if not (isinstance(k, ast.Constant) and k.value in keys):
                continue
            for sub in ast.walk(v):
                if (isinstance(sub, ast.Call)
                        and ((isinstance(sub.func, ast.Name)
                              and sub.func.id in _CUTS)
                             or (isinstance(sub.func, ast.Attribute)
                                 and sub.func.attr in _CUTS))):
                    bad.append((k.value, node.lineno))
    return found, bad


def test_the_plan_writer_rounds_no_field_a_gate_reads():
    found, bad = _rounded_gate_fields(
        inspect.getsource(energy_plan_actuation.plan_blocks))
    assert found, "no block dict found in plan_blocks — fix the guard"
    assert "plan_blocks(" in inspect.getsource(SEMCoordinator._shadow_energy_plan)
    assert not bad, (
        f"plan_blocks rounds {bad} — a gate adds these up and "
        "compares them with the exact need (#1282). Round in the sensor.")


def test_the_guard_finds_the_old_rounding():
    """Vacuity twin: the guard must catch the line #1282 removed."""
    old = '''
def f(plan):
    return [{"id": a.demand_id, "start": a.start.isoformat(),
             "end": a.end.isoformat(), "power_w": round(a.power_w, 0),
             "price": a.price} for a in plan.allocations]
'''
    found, bad = _rounded_gate_fields(old)
    assert found == 1 and bad == [("power_w", 3)]


def test_the_gate_compares_at_the_tolerance_this_test_assumes():
    """If the gate's margin grows to hide a rounding, this file proves less."""
    assert energy_plan_actuation._EPS_KWH <= 1e-6


# ── Review: a float rest under half a watt is no block to run in ──

def test_a_sub_watt_rest_does_not_force_the_battery_at_full_power():
    """The packer places a float rest as its own block: a 5.0003 kWh pack
    charge at 5000 W puts 0.3 W in the dearer hour. Its setpoint is 0 W,
    and ``decide_battery`` reads 0 W as "no cap" — so inside that hour
    the gate must not say "in block", or the pack charges at full power
    in the wrong hour. Its energy still counts."""
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryIntent,
    )
    from custom_components.solar_energy_management.coordinator.decide_battery import (
        decide_battery,
    )
    from custom_components.solar_energy_management.coordinator.energy_planner import (
        Demand, LedgerSlot, pack_night,
    )

    from .test_638_c4_battery_seam import _sched, _view

    ledger = [LedgerSlot(start=_at(23), end=_at(0), price=0.11),
              LedgerSlot(start=_at(0), end=_at(1), price=0.10)]
    packed = pack_night([Demand(id="battery", kind="battery",
                                energy_kwh=5.0003, max_power_w=5000.0)],
                        ledger)
    rest = [a for a in packed.allocations if a.power_w < 0.5]
    assert rest and rest[0].start == _at(23), "the scenario needs the rest"
    plan_dict = {
        "computed_at": (STAMP + timedelta(minutes=55)).isoformat(),
        "demands": [{"id": "battery", "status": r.status}
                    for r in packed.results],
        "slots": [{"start": _at(23).isoformat(), "end": _at(1).isoformat()}],
        "blocks": [{"id": a.demand_id, "start": a.start.isoformat(),
                    "end": a.end.isoformat(), "power_w": a.power_w}
                   for a in packed.allocations],
    }
    gate = plan_gate(plan_dict, "battery", _at(23, 30))
    assert gate.covered and not gate.in_block
    assert gate.next_block_start == _at(0)
    assert gate.remaining_kwh == pytest.approx(5.00015, abs=1e-6)
    d = decide_battery(_view(sched=_sched(power=5000.0), gate=gate))
    assert d.intent != BatteryIntent.FORCE_CHARGE
    # the real block still charges at its planned power
    inside = plan_gate(plan_dict, "battery", _at(0, 30))
    assert inside.in_block and inside.block_power_w == 5000.0
    d = decide_battery(_view(sched=_sched(power=5000.0), gate=inside))
    assert d.intent == BatteryIntent.FORCE_CHARGE and d.charge_power_w == 5000.0
