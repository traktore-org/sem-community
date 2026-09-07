"""AST lint (#924): every day-slot builder in production is handed a
feed-in rate.

``day_ledger.build_day_slots`` prices a surplus slot at ``export_rate``
because consuming a kWh here costs what it would have earned leaving
(#755). The parameter defaults to ``0.0`` — the free sun the packer
prefers by fiat.

#755 shipped a guard for this, and the guard read the source of ONE
named function::

    src = inspect.getsource(SEMCoordinator._shadow_energy_plan)
    assert "export_rate=" in src

A source-inspection guard can only ever pin the site it was written for.
Three sibling call sites kept the free sun for a month, and one of them
PACKS: ``_compose_tomorrow_preview`` ran the real ``pack_night`` over
unpriced slots, so the Tomorrow card showed a plan the night would not
execute. That is bug class 76.

The rule here is written so it cannot have that shape. It does not name
a function. It derives the set of *pricing surfaces* — every function in
the package that accepts an ``export_rate`` parameter — and then requires
every production call to one of them to pass the rate. A new wrapper is
covered on the day it is written; a new call site fails on the commit
that adds it.

Opt-out, for a call that genuinely must not price::

    build_day_slots(..., )   # UNPRICED: <why this one reads no price>

Typed and visible, in the shape of ``# FLEET-READ:``. There are none
today, and adding one should feel like a decision.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

_ROOT = Path(__file__).resolve().parent.parent
_SKIP_DIRS = {"tests", "scripts", "node_modules", "dashboard", ".git"}
_UNPRICED = re.compile(r"#\s*UNPRICED:\s*\S")
_PARAM = "export_rate"


def _production_files() -> list[Path]:
    out = []
    for p in sorted(_ROOT.rglob("*.py")):
        rel = p.relative_to(_ROOT)
        if set(rel.parts) & _SKIP_DIRS:
            continue
        out.append(p)
    assert out, "no production python found — the walker is broken"
    return out


def _pricing_surfaces(trees: dict) -> set[str]:
    """Every MODULE-LEVEL function in the package that takes a feed-in rate.

    Module-level on purpose. The first draft walked the whole tree and
    swept up every ``__init__`` that happens to take an ``export_rate``
    (the tariff provider, the battery adapters), which made the lint
    demand a feed-in rate at every constructor call in SEM. The slot
    builders and their wrappers are free functions; a constructor that
    stores a rate is a different thing and is not this rule's business.
    """
    names = set()
    for tree in trees.values():
        for node in tree.body:
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name.startswith("__"):
                continue
            a = node.args
            params = list(a.args) + list(a.kwonlyargs) + list(a.posonlyargs)
            if any(x.arg == _PARAM for x in params):
                names.add(node.name)
    return names


def _callee_name(node: ast.Call) -> str:
    f = node.func
    if isinstance(f, ast.Name):
        return f.id
    if isinstance(f, ast.Attribute):
        return f.attr
    return ""


def _span_text(src_lines: list[str], node: ast.Call) -> str:
    lo = max(0, node.lineno - 2)          # include the line above
    hi = min(len(src_lines), node.end_lineno or node.lineno)
    return "\n".join(src_lines[lo:hi])


def _handoffs(node: ast.Call, surfaces: set[str]) -> bool:
    """The call hands a pricing surface to somebody else as a value —
    ``today_remaining_slots(builder=build_day_slots, ...)``. The rate has
    to travel with it or the receiver builds at zero."""
    vals = list(node.args) + [k.value for k in node.keywords]
    for v in vals:
        if isinstance(v, ast.Name) and v.id in surfaces:
            return True
        if isinstance(v, ast.Attribute) and v.attr in surfaces:
            return True
    return False


def _trees() -> dict:
    return {p: ast.parse(p.read_text(encoding="utf-8")) for p in
            _production_files()}


class TestEveryDaySlotBuilderIsPriced:

    def test_the_lint_finds_the_surfaces_it_is_meant_to_police(self):
        """A lint that policed an empty set would pass forever."""
        surfaces = _pricing_surfaces(_trees())
        for expected in ("build_day_slots", "tomorrow_preview",
                         "today_remaining_slots"):
            assert expected in surfaces, (
                f"{expected} no longer declares an '{_PARAM}' parameter — "
                "either it was renamed (update this list) or the rate was "
                "dropped, which is the #755 defect returning")

    def test_every_production_call_passes_the_rate(self):
        trees = _trees()
        surfaces = _pricing_surfaces(trees)
        offenders = []
        for path, tree in trees.items():
            lines = path.read_text(encoding="utf-8").splitlines()
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                direct = _callee_name(node) in surfaces
                if not (direct or _handoffs(node, surfaces)):
                    continue
                if any(k.arg == _PARAM for k in node.keywords):
                    continue
                if _UNPRICED.search(_span_text(lines, node)):
                    continue
                offenders.append(
                    f"{path.relative_to(_ROOT)}:{node.lineno} "
                    f"{_callee_name(node) or '<builder handoff>'}()")
        assert not offenders, (
            "a day-slot builder is called without a feed-in rate, so its "
            "surplus slots price at 0 and the sun wins by fiat (#755/#924):"
            "\n  " + "\n  ".join(offenders)
            + "\nPass export_rate=..., or annotate the call "
              "'# UNPRICED: <reason>' if this surface truly reads no price.")

    def test_a_planning_call_site_never_reads_the_config_key_itself(self):
        """(#924) The key is read in several honest places — the schema,
        the tariff provider, the cost calculator. What must NOT happen
        again is a PLANNING call site reading it directly: that is how
        four builders came to hold four opinions, three of them stale.
        A pricing call asks ``self._configured_export_rate()``; it does
        not fetch the config itself."""
        trees = _trees()
        surfaces = _pricing_surfaces(trees)
        offenders = []
        for path, tree in trees.items():
            for node in ast.walk(tree):
                if not isinstance(node, ast.Call):
                    continue
                if not (_callee_name(node) in surfaces
                        or _handoffs(node, surfaces)):
                    continue
                for kw in node.keywords:
                    if kw.arg != _PARAM:
                        continue
                    arg = ast.unparse(kw.value)
                    if "electricity_export_rate" in arg:
                        offenders.append(
                            f"{path.relative_to(_ROOT)}:{node.lineno} "
                            f"export_rate={arg}")
        assert not offenders, (
            "a planning call site reads the export-rate config key "
            "directly instead of calling _configured_export_rate(); that "
            "is the shape #755 left behind and #924 removed:\n  "
            + "\n  ".join(offenders))
