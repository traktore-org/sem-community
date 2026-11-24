"""(#1381 charger owner S13) Nothing goes around the owner.

Three structural guards, each a reading of the source (AST), so a new path
cannot slip in unnoticed:

1. Every ``resolve()`` step names its producer from the owner's own vocabulary:
   a ``SRC_*`` constant and a ``CommandClass`` member — never a bare string, so
   the trail and the ledger always say who decided.
2. The safety gate (the phase guard) is the LAST rewriter that may strengthen
   a stop, and only the sequencer (which can only weaken a charge) follows it:
   a new step added after the guard fails here until someone decides its place.
3. ``stamp()`` and ``resolve()`` are called only by the owner and the per-charger
   loop; no other module re-labels a decision.

The verb inventory (S0, ``test_charger_writer_inventory.py``) and the load
manager's charger fence (S7) cover the other two bypasses: a new command site
anywhere in the package, and the load manager writing a charger's entity.
"""
from __future__ import annotations

import ast
import pathlib

PKG = pathlib.Path(__file__).resolve().parent.parent
COORD = PKG / "coordinator" / "coordinator.py"
OWNER = PKG / "coordinator" / "charger_owner.py"
EXCLUDE = {"tests", "tools", "scripts", "dashboard", "docs", "node_modules",
           "graphify-out", "__pycache__", ".git", ".github"}


def _resolve_calls(tree):
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "resolve" and node.args
                and len(node.args) == 2 and isinstance(node.args[1], ast.List)):
            yield node


def _attr_chain(node) -> str:
    parts = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    return ".".join(reversed(parts))


def test_every_step_names_its_source_and_class_from_the_owner():
    tree = ast.parse(COORD.read_text())
    calls = list(_resolve_calls(tree))
    assert len(calls) == 2, "the fleet loop and the legacy single-charger branch"
    for call in calls:
        for step in call.args[1].elts:
            assert isinstance(step, ast.Tuple) and len(step.elts) == 3, ast.unparse(step)
            src, klass = _attr_chain(step.elts[0]), _attr_chain(step.elts[1])
            assert src.split(".")[-1].startswith("SRC_"), (
                f"line {step.lineno}: a step's source must be an owner SRC_* "
                f"constant, got {ast.unparse(step.elts[0])}")
            assert ".CommandClass." in "." + klass + ".", (
                f"line {step.lineno}: a step's class must be a CommandClass "
                f"member, got {ast.unparse(step.elts[1])}")


def test_nothing_strengthens_a_charge_after_the_safety_gate():
    tree = ast.parse(COORD.read_text())
    for call in _resolve_calls(tree):
        names = [_attr_chain(s.elts[0]).split(".")[-1] for s in call.args[1].elts]
        assert "SRC_PHASE_GUARD" in names
        after = names[names.index("SRC_PHASE_GUARD") + 1:]
        assert set(after) <= {"SRC_PHASE_SEQUENCER"}, (
            "only the phase sequencer (which can only weaken a charge) may run "
            f"after the safety gate; found {after}")


def test_only_the_owner_and_the_charger_loop_relabel_a_decision():
    offenders = []
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG)
        if rel.parts and rel.parts[0] in EXCLUDE:
            continue
        if path in (OWNER, COORD):
            continue
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("stamp", "resolve")
                    and "_owner" in _attr_chain(node.func)):
                offenders.append(f"{rel}:{node.lineno}")
    assert offenders == [], offenders


def test_the_lint_sees_a_seeded_bare_string_source():
    """The guard works: a step with a bare-string source is caught."""
    bad = ast.parse(
        "async def f():\n"
        "    await _owner.resolve(d, [('stability', _owner.CommandClass.SUN, g)])\n")
    step = next(_resolve_calls(bad)).args[1].elts[0]
    assert not _attr_chain(step.elts[0]).split(".")[-1].startswith("SRC_")
