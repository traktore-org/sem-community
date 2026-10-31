"""#1184 — a plan rebuild could move the battery's sale times unseen.

When a rebuild reached the same decision, SEM kept the old plan and its
stamp (#775). The check for "the same decision" (``plan_decision_core``)
did not compare the forecast-led sale blocks (``forecast_sell``), and with
the intraday flag on the keep step copied the NEW build's sale blocks in
(``TRAJECTORY_KEYS``, #1068). ``forecast_sell_gate`` acts on those blocks,
so the battery could sell at a time or rate the stamped plan never showed.
With the flag off the new sale answer was dropped without a word instead.
The arbitrage sale had the same hole one level down: its block's kWh (the
rate ``arbitrage_sell_gate`` sells at) was not compared either.

The guard is a rule over every field the plan's controls read:
* same decision ⇒ same acts, at every moment of the period;
* a kept plan acts exactly as the plan whose stamp it keeps;
* every field a gate reads has a case below (AST), so a new field cannot
  join a gate without joining this check.
"""
import ast
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import (
    coordinator as coord_mod,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    TRAJECTORY_KEYS, SEMCoordinator, keep_decision_take_trajectory,
    plan_decision_core,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    arbitrage_sell_gate, forecast_sell_gate, plan_gate,
)

TZ = timezone(timedelta(hours=2))
DAY = datetime(2026, 10, 24, tzinfo=TZ)


def _iso(h, m=0, day=0):
    return (DAY + timedelta(days=day, hours=h, minutes=m)).isoformat()


def _sell(start_h, start_m, kwh):
    """A forecast-led sale block, the shape ``_shadow_energy_plan`` writes."""
    return {"enabled": True, "kwh": kwh,
            "blocks": [{"start": _iso(start_h, start_m), "end": _iso(19),
                        "kwh": kwh}]}


BASE = {
    "computed_at": _iso(9, 2),
    "replan_cause": "initial",
    "fits": True,
    "total_cost": 1.2,
    "takeover": None,
    "battery_fleet_partial": None,
    "demands": [{"id": "ev:k", "status": "fits",
                 "planned_kwh": 6.0, "needed_kwh": 6.0}],
    "blocks": [{"id": "ev:k", "start": _iso(23), "end": _iso(2, day=1),
                "power_w": 2000.0}],
    "not_scheduled": [],
    "slots": [
        {"start": _iso(9, 2), "end": _iso(10), "price": 0.0,
         "soc_kwh": 9.0, "home_grid_w": 0.0},
        {"start": _iso(6, day=1), "end": _iso(7, day=1), "price": 0.3,
         "soc_kwh": 2.0, "home_grid_w": 400.0},
    ],
    "summary": ["the morning answer"],
    "allocations": ["ev:k: 2000 W 23:00-02:00"],
    "arbitrage": {"opportunity": True, "charge_kwh": 3.0,
                  "est_profit": 0.4, "reason": "buy 3.0 kWh",
                  "charge_blocks": [{"start": _iso(2, day=1),
                                     "end": _iso(3, day=1), "kwh": 3.0}],
                  "discharge_blocks": [{"start": _iso(6, day=1),
                                        "end": _iso(7, day=1),
                                        "kwh": 2.76}]},
    # 24.10: 4.0 kWh to sell before the 19:00 night, at 5 kW → 18:12.
    "forecast_sell": _sell(18, 12, 4.0),
    "self_consumption": {"share": 0.8},
}

# Every 5 minutes from the stamp to past the night end.
GRID = [DAY + timedelta(hours=9, minutes=5 * k) for k in range(12 * 24)]


def _acts(plan):
    """Everything the stamped plan makes SEM do, at every moment."""
    return [(plan_gate(plan, "ev:k", t), arbitrage_sell_gate(plan, t),
             forecast_sell_gate(plan, t)) for t in GRID]


def _with(path, value):
    """BASE with one field replaced. ``path`` walks dicts and list rows."""
    import copy
    plan = copy.deepcopy(BASE)
    node = plan
    for step in path[:-1]:
        node = node[step]
    if value is _DROP:
        node.pop(path[-1])
    else:
        node[path[-1]] = value
    return plan


_DROP = object()

# (gate, field it reads, case). Each case changes what that gate does at
# some moment — a rebuild that lands on it has a new decision.
DECISION_CASES = [
    ("plan_gate", "demands", ("demands",), []),
    ("plan_gate", "status", ("demands", 0, "status"), "partial"),
    ("plan_gate", "id", ("blocks", 0, "id"), "ev:other"),
    ("plan_gate", "blocks", ("blocks",), []),
    ("plan_gate", "start", ("blocks", 0, "start"), _iso(23, 30)),
    ("plan_gate", "end", ("blocks", 0, "end"), _iso(1, day=1)),
    ("plan_gate", "power_w", ("blocks", 0, "power_w"), 1400.0),
    ("arbitrage_sell_gate", "arbitrage", ("arbitrage",), None),
    ("arbitrage_sell_gate", "discharge_blocks",
     ("arbitrage", "discharge_blocks"), []),
    ("arbitrage_sell_gate", "start",
     ("arbitrage", "discharge_blocks", 0, "start"), _iso(6, 30, day=1)),
    ("arbitrage_sell_gate", "end",
     ("arbitrage", "discharge_blocks", 0, "end"), _iso(6, 45, day=1)),
    # the same hour, a different rate: 2.76 kWh/h became 1.5 kWh/h
    ("arbitrage_sell_gate", "kwh",
     ("arbitrage", "discharge_blocks", 0, "kwh"), 1.5),
    ("forecast_sell_gate", "forecast_sell", ("forecast_sell",), None),
    ("forecast_sell_gate", "blocks", ("forecast_sell", "blocks"), []),
    # a forecast swing: 6.5 kWh to sell → the block opens at 17:42
    ("forecast_sell_gate", "start",
     ("forecast_sell", "blocks", 0, "start"), _iso(17, 42)),
    ("forecast_sell_gate", "end",
     ("forecast_sell", "blocks", 0, "end"), _iso(18, 30)),
    ("forecast_sell_gate", "kwh",
     ("forecast_sell", "blocks", 0, "kwh"), 2.5),
]

# A new build's trajectory: what the sky changed, never what SEM does.
# One case per TRAJECTORY_KEYS entry; ``slots`` keeps its span (first
# start, last end), the only part of it a gate reads.
TRAJECTORY_CASES = {
    "slots": [{**BASE["slots"][0], "home_grid_w": 950.0, "soc_kwh": 4.0},
              {**BASE["slots"][1], "soc_kwh": 0.5}],
    "self_consumption": {"share": 0.3},
    "summary": ["a grey afternoon"],
}


def _case_id(case):
    return f"{case[0]}:{case[1]}"


@pytest.mark.parametrize("case", DECISION_CASES, ids=_case_id)
def test_a_field_the_controls_read_is_the_decision(case):
    _gate, _field, path, value = case
    moved = _with(path, value)
    assert _acts(moved) != _acts(BASE), (
        f"case {_case_id(case)} must change what SEM does, or it proves "
        "nothing")
    assert plan_decision_core(moved) != plan_decision_core(BASE), (
        f"{_case_id(case)} changed what SEM does, but the rebuild would "
        "count as the same decision and keep the old stamp (#1184)")


# Changes below the check's step: the same decision, yet each one changes
# an act (a rate). Copied into a kept plan, it would act unseen.
NOISE_CASES = [
    ("plan_gate:power_w", ("blocks", 0, "power_w"), 2000.3),
    ("arbitrage_sell_gate:kwh",
     ("arbitrage", "discharge_blocks", 0, "kwh"), 2.764),
    ("forecast_sell_gate:kwh", ("forecast_sell", "blocks", 0, "kwh"), 4.004),
    ("forecast_sell_gate:start", ("forecast_sell", "blocks", 0, "start"),
     (DAY + timedelta(hours=18, minutes=12, seconds=3)).isoformat()),
]


@pytest.mark.parametrize("case", NOISE_CASES, ids=lambda c: c[0])
def test_a_kept_plan_acts_as_its_stamp_says(case):
    """Whatever a same-decision rebuild copies in must not change an act."""
    _name, path, value = case
    fresh = {**_with(path, value), "computed_at": _iso(13)}
    assert _acts(fresh) != _acts(BASE), "the case proves nothing"
    assert plan_decision_core(fresh) == plan_decision_core(BASE)
    kept = keep_decision_take_trajectory(BASE, fresh, _iso(13))
    assert _acts(kept) == _acts(BASE)


def test_every_trajectory_key_is_only_the_sky():
    assert set(TRAJECTORY_KEYS) <= set(TRAJECTORY_CASES), (
        "a new TRAJECTORY_KEYS entry needs a case here")
    for key in TRAJECTORY_KEYS:
        fresh = {**BASE, key: TRAJECTORY_CASES[key],
                 "computed_at": _iso(13)}
        assert plan_decision_core(fresh) == plan_decision_core(BASE), key
        kept = keep_decision_take_trajectory(BASE, fresh, _iso(13))
        assert kept[key] == TRAJECTORY_CASES[key], key
        assert kept["computed_at"] == BASE["computed_at"]
        assert _acts(kept) == _acts(BASE), (
            f"{key} is copied into a kept plan but changes what SEM does")


def test_no_trajectory_key_holds_a_sale():
    assert "forecast_sell" not in TRAJECTORY_KEYS
    assert "arbitrage" not in TRAJECTORY_KEYS


def test_the_prod_morning_swing_restamps():
    """24.10 shape on a full battery: the 09:02 build sells 4.0 kWh from
    18:12; a 13:00 forecast swing makes it 6.5 kWh from 17:42."""
    fresh = {**BASE, "computed_at": _iso(13),
             "forecast_sell": _sell(17, 42, 6.5)}
    assert plan_decision_core(fresh) != plan_decision_core(BASE)


def test_float_noise_is_not_a_new_sale():
    """The block is anchored to the night start and sized from a float;
    a few watt-hours and seconds are the same sale."""
    noisy = _sell(18, 12, 4.004)
    noisy["blocks"][0]["start"] = (
        DAY + timedelta(hours=18, minutes=12, seconds=3)).isoformat()
    fresh = {**BASE, "computed_at": _iso(13), "forecast_sell": noisy}
    assert plan_decision_core(fresh) == plan_decision_core(BASE)
    kept = keep_decision_take_trajectory(BASE, fresh, _iso(13))
    assert kept["forecast_sell"] == BASE["forecast_sell"]


# ── Every field a gate reads has a case (AST) ──

_SRC = (Path(__file__).resolve().parents[1] / "coordinator"
        / "energy_plan_actuation.py")
_GATES = ("plan_gate", "arbitrage_sell_gate", "forecast_sell_gate")


def _keys_read(fn):
    """String keys read with ``.get("k")`` or ``x["k"]``."""
    keys = set()
    for n in ast.walk(fn):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "get" and n.args
                and isinstance(n.args[0], ast.Constant)
                and isinstance(n.args[0].value, str)):
            keys.add(n.args[0].value)
        elif (isinstance(n, ast.Subscript)
                and isinstance(n.slice, ast.Constant)
                and isinstance(n.slice.value, str)):
            keys.add(n.slice.value)
    return keys


def _gate_fns():
    tree = ast.parse(_SRC.read_text())
    return {n.name: n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name in _GATES}


def test_every_field_a_gate_reads_has_a_case():
    fns = _gate_fns()
    assert set(fns) == set(_GATES)
    covered = {(g, f) for g, f, _p, _v in DECISION_CASES}
    for name, fn in fns.items():
        # ``computed_at`` IS the stamp; ``slots`` is read for its span only
        # (pinned below), and every build of one period ends it at the
        # same night end.
        for key in _keys_read(fn) - {"computed_at", "slots"}:
            assert (name, key) in covered, (
                f"{name} reads {key!r}, but no case proves a change to it "
                "is a new decision (#1184)")


def test_slots_are_read_for_their_span_only():
    """``plan_gate`` reads ``slots[0]['start']`` and ``slots[-1]['end']``
    and nothing else of a slot; no other gate reads slots."""
    fns = _gate_fns()
    for name in ("arbitrage_sell_gate", "forecast_sell_gate"):
        assert "slots" not in _keys_read(fns[name]), name
    uses = [n for n in ast.walk(fns["plan_gate"])
            if isinstance(n, ast.Name) and n.id == "slots"
            and isinstance(n.ctx, ast.Load)]
    subs = [n for n in ast.walk(fns["plan_gate"])
            if isinstance(n, ast.Subscript)
            and isinstance(n.value, ast.Name) and n.value.id == "slots"]
    assert subs, "plan_gate no longer reads slots — drop this pin"
    for sub in subs:
        idx = ast.literal_eval(sub.slice)
        assert idx in (0, -1), f"plan_gate reads slots[{idx}]"
    # each read is ``slots[0]``/``slots[-1]`` or the ``if slots`` guard
    # beside it — never a loop over the slots
    assert not [n for n in ast.walk(fns["plan_gate"])
                if isinstance(n, (ast.For, ast.comprehension))
                and isinstance(n.iter, ast.Name) and n.iter.id == "slots"]
    assert len(uses) <= 2 * len(subs), "plan_gate reads slots another way"


# ── Through the tick: what the user sees after the rebuild ──

def _tick_fake(seq, intraday):
    plans = [dict(p) for p in seq]
    calls = []

    def _compute(scheduler, energy, power=None, replan_cause="initial"):
        calls.append(replan_cause)
        fake._energy_plan_shadow = plans.pop(0)
        return True

    fake = SimpleNamespace(
        _battery_charge_scheduler=SimpleNamespace(),
        time_manager=SimpleNamespace(get_night_end_time=lambda: "07:00"),
        config={"battery_capacity_kwh": 0, "intraday_forecast": intraday},
        _energy_plan_demand_signature=lambda power, energy=None: fake._sig,
        _shadow_energy_plan=_compute,
        _shadow_plan_date=None,
        _plan_ev_conn_sig=None,
        _energy_plan_shadow=None,
        _sig=("ask",),
        _compute_calls=calls,
    )
    return fake


@pytest.fixture
def _at_1300(monkeypatch):
    fixed = DAY + timedelta(hours=13)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    return fixed


@pytest.mark.parametrize("intraday", [True, False])
def test_a_moved_sale_restamps_the_plan(_at_1300, intraday):
    revised = {**BASE, "computed_at": _iso(13),
               "replan_cause": "ask changed",
               "forecast_sell": _sell(17, 42, 6.5)}
    fake = _tick_fake([BASE, revised], intraday)
    SEMCoordinator._energy_plan_tick(fake, power=None, energy=None)
    fake._sig = ("ask", "forecast swing")
    SEMCoordinator._energy_plan_tick(fake, power=None, energy=None)
    plan = fake._energy_plan_shadow
    assert fake._compute_calls == ["initial", "ask changed"]
    assert plan["computed_at"] == _iso(13), (
        "the sale moved: the plan must say it changed")
    assert plan["forecast_sell"] == revised["forecast_sell"]
    assert forecast_sell_gate(plan, DAY + timedelta(hours=17, minutes=50)
                              )[0] is True


@pytest.mark.parametrize("intraday", [True, False])
def test_an_unmoved_sale_keeps_the_stamp_and_its_blocks(_at_1300, intraday):
    noisy = _sell(18, 12, 4.004)
    revised = {**BASE, "computed_at": _iso(13),
               "replan_cause": "ask changed", "forecast_sell": noisy,
               "slots": TRAJECTORY_CASES["slots"]}
    fake = _tick_fake([BASE, revised], intraday)
    SEMCoordinator._energy_plan_tick(fake, power=None, energy=None)
    fake._sig = ("ask", "forecast swing")
    SEMCoordinator._energy_plan_tick(fake, power=None, energy=None)
    plan = fake._energy_plan_shadow
    assert plan["computed_at"] == BASE["computed_at"]
    assert plan["forecast_sell"] == BASE["forecast_sell"], (
        "a kept plan sells as its stamp says")
    assert _acts(plan) == _acts(BASE)


# ── A rebuild while the sale runs keeps it running ──

from custom_components.solar_energy_management.coordinator.forecast_sell import (  # noqa: E402
    MIN_SPEND_KWH, forecast_sell_blocks,
)

NIGHT_START = DAY + timedelta(hours=19)
AT_1700 = DAY + timedelta(hours=17)


def _plan_with(blocks):
    return {"computed_at": AT_1700.isoformat(),
            "forecast_sell": {"enabled": True, "blocks": [
                {**b, "start": b["start"].isoformat(),
                 "end": b["end"].isoformat()} for b in blocks]}}


def test_a_running_sale_keeps_its_block_open():
    """20 kWh at 5 kW opened 15:00–19:00. A 17:00 rebuild reads 9.9 kWh
    left (the pack fell a little faster than the sale): anchored, the
    block would open again at 17:01:12 and the sale would stop."""
    idle = forecast_sell_blocks(AT_1700, NIGHT_START, 9.9, 5000.0)
    assert idle[0]["start"] > AT_1700        # what paused the sale
    got = forecast_sell_blocks(AT_1700, NIGHT_START, 9.9, 5000.0,
                               selling=True)
    assert got[0]["start"] == AT_1700 and got[0]["end"] == NIGHT_START
    assert got[0]["kwh"] == 9.9
    is_open, rate = forecast_sell_gate(
        _plan_with(got), AT_1700 + timedelta(seconds=30))
    assert is_open and rate == pytest.approx(4950.0)


def test_a_running_sale_with_more_left_keeps_its_anchor():
    got = forecast_sell_blocks(AT_1700, NIGHT_START, 12.0, 5000.0,
                               selling=True)
    assert got == forecast_sell_blocks(AT_1700, NIGHT_START, 12.0, 5000.0)
    assert got[0]["start"] < AT_1700


def test_a_running_sale_still_ends():
    assert forecast_sell_blocks(AT_1700, NIGHT_START, MIN_SPEND_KWH - 0.05,
                                5000.0, selling=True) == []
    assert forecast_sell_blocks(NIGHT_START, NIGHT_START, 5.0, 5000.0,
                                selling=True) == []


def test_the_plan_tells_the_builder_a_sale_runs():
    """``_shadow_energy_plan`` passes ``selling`` from the live sale flag."""
    tree = ast.parse((Path(__file__).resolve().parents[1] / "coordinator"
                      / "coordinator.py").read_text())
    build = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and n.name == "_shadow_energy_plan")
    calls = [n for n in ast.walk(build) if isinstance(n, ast.Call)
             and getattr(n.func, "id", "") == "forecast_sell_blocks"]
    assert len(calls) == 1
    kw = {k.arg: ast.unparse(k.value) for k in calls[0].keywords}
    assert "_forecast_sell_active" in kw.get("selling", "")
