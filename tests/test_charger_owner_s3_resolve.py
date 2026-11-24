"""(#1381, charger owner S3) The per-charger chain is ONE ``resolve`` call.

The coordinator used to run decide → VPP → plan override → stability/yield →
phase guard → phase sequencer as six assignments in a 19 000-line file, in
an order nobody wrote down. ``charger_owner.resolve`` runs the same steps in
the same order and keeps a trail of who changed the decision. These tests
prove it changes nothing but the trail and the provenance stamp.
"""
from __future__ import annotations

import ast
import pathlib
from dataclasses import replace

import pytest

from custom_components.solar_energy_management.coordinator import charger_owner as owner
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent


def _d(intent=ChargerIntent.CHARGE_AT_AMPS, amps=10):
    return ChargerDecision(charger_id="c", mode="pv", intent=intent,
                           commanded_amps=amps, budget_w=amps * 690.0,
                           reason="base")


def _matrix():
    """Step functions of every shape: pass-through, rewrite, self-stamped
    rewrite, async, returns None."""
    keep = lambda d: d  # noqa: E731
    clamp = lambda d: replace(d, commanded_amps=min(d.commanded_amps, 8))  # noqa: E731
    stop = lambda d: replace(d, intent=ChargerIntent.DISABLE, commanded_amps=0,  # noqa: E731
                             source="phase_guard", klass=1)

    async def hold(d):
        if d.intent is ChargerIntent.DISABLE:
            return d
        return replace(d, intent=ChargerIntent.IDLE, commanded_amps=0)

    none = lambda d: None  # noqa: E731
    return {"keep": keep, "clamp": clamp, "stop": stop, "hold": hold, "none": none}


async def _explicit(d, fns):
    for fn in fns:
        out = fn(d)
        if hasattr(out, "__await__"):
            out = await out
        d = d if out is None else out
    return d


@pytest.mark.asyncio
@pytest.mark.parametrize("names", [
    ("keep", "keep", "keep"),
    ("clamp", "keep", "stop", "hold"),
    ("clamp", "hold"),
    ("keep", "stop", "hold"),
    ("none", "clamp", "none"),
    ("hold", "clamp"),
])
@pytest.mark.parametrize("amps", [6, 10, 16])
async def test_resolve_equals_the_explicit_chain(names, amps):
    m = _matrix()
    fns = [m[n] for n in names]
    base = _d(amps=amps)
    want = await _explicit(base, fns)
    got, trail = await owner.resolve(base, [
        (f"s{i}", owner.CommandClass.SUN, fn) for i, fn in enumerate(fns)])
    assert got == want                      # same decision, field for field
    assert got.reason == want.reason
    assert [s for s, _ in trail] == [f"s{i}" for i in range(len(fns))]


@pytest.mark.asyncio
async def test_a_rewrite_is_named_and_a_self_stamp_is_kept():
    m = _matrix()
    got, trail = await owner.resolve(_d(amps=16), [
        ("clamp_src", owner.CommandClass.HARD_LIMIT, m["clamp"]),
        ("guard_src", owner.CommandClass.SAFETY, m["stop"]),
        ("seq", owner.CommandClass.HARD_LIMIT, m["hold"]),
    ])
    assert got.intent is ChargerIntent.DISABLE
    assert got.source == "phase_guard" and got.klass == 1   # its own stamp
    assert trail == [("clamp_src", True), ("guard_src", True), ("seq", False)]


@pytest.mark.asyncio
async def test_an_unchanged_decision_is_not_restamped():
    base = _d()
    got, trail = await owner.resolve(base, [("x", owner.CommandClass.SUN, lambda d: d)])
    assert got is base and got.source == "" and trail == [("x", False)]


def _chain_sources(tree):
    """Source constants of every ``_owner.resolve(decision, [...])`` call."""
    out = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "resolve" and len(node.args) == 2
                and isinstance(node.args[1], ast.List)):
            out.append([e.elts[0].attr for e in node.args[1].elts
                        if isinstance(e, ast.Tuple)
                        and isinstance(e.elts[0], ast.Attribute)])
    return out


def test_the_coordinator_keeps_the_order_it_always_had():
    tree = ast.parse((ROOT / "coordinator" / "coordinator.py").read_text())
    chains = _chain_sources(tree)
    assert ["SRC_VPP_PAUSE", "SRC_PLAN_SKIP", "SRC_STABILITY",
            "SRC_PHASE_GUARD", "SRC_PHASE_SEQUENCER"] in chains
    assert ["SRC_STABILITY", "SRC_PHASE_GUARD"] in chains   # single-charger path


def test_note_trail_survives_a_bare_coordinator():
    from types import SimpleNamespace
    c = SimpleNamespace()
    owner.note_trail(c, "a", [("x", True)])
    assert c._owner_trail == {"a": [("x", True)]}
