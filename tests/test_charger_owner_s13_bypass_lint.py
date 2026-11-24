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

(#1381 D34) What these readings do NOT catch, on purpose: a function held in
a plain name (``f = co.resolve; f(...)``), ``functools.partial(co.stamp, …)``,
``importlib.import_module``, a star import, a keyword splat
(``rewrite(d, **{"source": …})``) and ``object.__setattr__`` on a decision.
Following those would mean data-flow analysis, which an AST lint cannot do
without false alarms. Each of them is a deliberate trick, not an accident,
and the review of every change to the charger path is where it is caught.
The hardware-facing bypass — a new place that commands a charger — stays
fully covered by the S0 inventory, whatever name it hides behind.
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


# ── (#1381 D26) the relabel guard cannot be fooled by aliasing ────────────

_OWNER_VERBS = {"stamp", "resolve"}
#: Every place outside the owner that stamps a decision's source today, by
#: (file, source). Each is a step ``resolve()`` lists; a new one fails here
#: until someone decides it belongs in the owner's step list.
_ALLOWED_RELABELS = {
    ("coordinator/active_phase_guard.py", "phase_guard"),
    ("coordinator/actuate.py", "phase_guard"),
    ("coordinator/plan_override.py", "plan_skip"),
    ("coordinator/decide.py", "peak_emergency"),
    ("coordinator/vpp_dispatch.py", "vpp_pause"),
}


def _owner_offences(tree) -> list:
    """Every way ``tree`` reaches the owner's stamp/resolve: an import of
    them (any alias), the owner module under any name with the verb called or
    fetched by ``getattr``, and a call through any of those names."""
    out = []
    mod_aliases, fn_aliases = set(), set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            mod = node.module or ""
            for a in node.names:
                if mod.endswith("charger_owner") and a.name in _OWNER_VERBS:
                    fn_aliases.add(a.asname or a.name)
                    out.append(node.lineno)
                if a.name == "charger_owner":
                    mod_aliases.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name.endswith("charger_owner"):
                    mod_aliases.add(a.asname or a.name.split(".")[-1])
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        f = node.func
        if isinstance(f, ast.Name) and f.id in fn_aliases:
            out.append(node.lineno)
        elif isinstance(f, ast.Attribute) and f.attr in _OWNER_VERBS:
            chain = _attr_chain(f.value)
            if chain.split(".")[-1] in mod_aliases or "_owner" in chain:
                out.append(node.lineno)
        elif (isinstance(f, ast.Name) and f.id == "getattr" and len(node.args) >= 2
              and isinstance(node.args[1], ast.Constant)
              and node.args[1].value in _OWNER_VERBS
              and _attr_chain(node.args[0]).split(".")[-1] in mod_aliases):
            out.append(node.lineno)
    return sorted(set(out))


def _relabels(tree) -> set:
    """``(source)`` of every ``rewrite``/``replace`` call that sets a
    decision's ``source`` or ``klass`` (a bare string, any alias)."""
    out = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _attr_chain(node.func).split(".")[-1]
        if name not in ("rewrite", "replace", "_replace"):
            continue
        kws = {k.arg: k.value for k in node.keywords if k.arg}
        if "source" in kws or "klass" in kws:
            v = kws.get("source")
            out.add(v.value if isinstance(v, ast.Constant) else ast.unparse(v) if v else "?")
    return out


def _package_files():
    for path in PKG.rglob("*.py"):
        rel = path.relative_to(PKG)
        if rel.parts and rel.parts[0] in EXCLUDE:
            continue
        yield path, rel


def test_no_module_reaches_the_owners_verbs_under_any_name():
    offenders = []
    for path, rel in _package_files():
        if path in (OWNER, COORD):
            continue
        for line in _owner_offences(ast.parse(path.read_text())):
            offenders.append(f"{rel}:{line}")
    assert offenders == [], offenders


def test_every_relabel_outside_the_owner_is_a_known_step():
    found = set()
    for path, rel in _package_files():
        if path in (OWNER, COORD):
            continue
        for src in _relabels(ast.parse(path.read_text())):
            found.add((str(rel), src))
    assert found <= _ALLOWED_RELABELS, sorted(found - _ALLOWED_RELABELS)


def test_the_lint_sees_every_fooling_form():
    """The guards work: each way a reviewer used to slip past is caught."""
    fooling = {
        "from_import_alias": "from .charger_owner import resolve as r\nr(d, [])\n",
        "module_alias": "from . import charger_owner as co\nco.stamp(d, 'x', 1)\n",
        "plain_import": "import custom.coordinator.charger_owner as cx\ncx.resolve(d, [])\n",
        "getattr_string": "from . import charger_owner as m\ngetattr(m, 'stamp')(d)\n",
    }
    for name, code in fooling.items():
        assert _owner_offences(ast.parse(code)), name
    relabel = {
        "rewrite_kw": "rewrite(d, source='sneaky', klass=2)\n",
        "dataclass_replace": "dataclasses.replace(d, source='sneaky')\n",
        "replace_alias": "replace(d, klass=1)\n",
    }
    for name, code in relabel.items():
        assert _relabels(ast.parse(code)), name
    # and an honest file is clean
    assert _owner_offences(ast.parse("from .charger_owner import is_guard_stop\n")) == []
