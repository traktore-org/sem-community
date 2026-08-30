#!/usr/bin/env python3
"""(#873) Which large coordinator methods do tests EXECUTE, and which do they
only READ?

NOTE: this file deliberately does NOT scan for orphaned/unwired methods.
``tests/test_653_orphan_methods.py`` already does that, as a CI gate with a
reviewed baseline and a specimen test — strictly better than the duplicate
that briefly lived here, whose raw output was mostly HA-dispatched entity
methods (``async_turn_on`` and friends) that HA core calls, not SEM.

SEM guards its big orchestration methods with AST/source inspection —
`inspect.getsource(...)` plus an `ast` walk asserting that a name is in
scope, that a method is called and not merely referenced, that a marker is
set only after success. Those are real guarantees, and they are blind to a
wrong FORMULA: every one of #778's three defects was valid code with every
name correctly in scope.

This script measures the gap. A method is EXECUTED if any file under
``tests/`` calls it (``coord._name(``, ``await X._name(``); otherwise, if a
test only mentions it, it is READ-ONLY.

Scan every file under ``tests/`` — not just ``test_*.py``. ``scenario_harness.py``
and ``conftest.py`` drive real coordinator methods, and globbing ``test_*.py``
alone under-reports: it wrongly listed ``_build_charging_context`` as never
executed when the harness calls it.
"""
from __future__ import annotations

import ast
import pathlib
import re
import sys

#: Below this a method is small enough to read and reason about directly.
BIG_METHOD_LINES = 120


def _methods_and_calls(tree: ast.AST):
    """Every method with its line span, and the set of ``self.X(...)`` calls
    it makes."""
    spans: dict[str, int] = {}
    calls: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for item in node.body:
            if not isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            spans[item.name] = (item.end_lineno or item.lineno) - item.lineno + 1
            out: set[str] = set()
            for sub in ast.walk(item):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Attribute):
                    val = sub.func.value
                    if isinstance(val, ast.Name) and val.id == "self":
                        out.add(sub.func.attr)
            calls[item.name] = out
    return spans, calls


def scan(root: pathlib.Path) -> list[tuple[int, str, list[str], int]]:
    """Which big coordinator methods does the suite reach — STATICALLY?

    This is an UPPER BOUND, and the difference matters. A method can be
    reachable on the call graph and still never run, because the branch that
    calls it is false under test: ``async_initialize_energy_dashboard`` is
    statically reachable via ``_retry_energy_dashboard_resolution`` and was
    NOT executed by an instrumented cycle. Treating static reachability as
    coverage would report "all covered" over a method nothing runs — a worse
    failure than the gap it replaced, because it is comfortable.

    The RATCHET (tests/test_873_assembly_coverage_ratchet.py) therefore
    instruments a real cycle and asserts what actually executed. This
    function stays as the reporting view.

    Coverage is REACHABILITY, not a direct call by name. A test that runs
    ``_async_update_data`` genuinely exercises the six assemblies that cycle
    calls; demanding a direct call for each would push people to write
    shallow name-calling tests for code already covered — the opposite of
    what #873 is for. Measured empirically before this was written: one run
    of tests/test_873_cycle_executes.py reaches _update_analytics_phases,
    _update_ev_intelligence, _build_charging_context, _build_system_status,
    _record_forecast_horizons and _run_battery_pipeline.

    So: roots are the methods a test file calls by name, and a method is
    covered if it is a root or is reachable from one through ``self.X(...)``
    inside coordinator.py.

    Real line spans come from ``ast``. An earlier version found boundaries by
    regex for the next ``def _...`` — private only — so a private method
    absorbed every public method after it and reported ``_build_system_status``
    as 258 lines when it is 35.

    Every file under ``tests/`` counts, not just ``test_*.py``:
    ``scenario_harness.py`` drives real coordinator methods.
    """
    tree = ast.parse((root / "coordinator" / "coordinator.py").read_text())
    spans, calls = _methods_and_calls(tree)

    blob = {p.name: p.read_text() for p in sorted((root / "tests").glob("*.py"))}
    roots: dict[str, list[str]] = {}
    for name in spans:
        pattern = re.compile(r"(?:await\s+)?\w+\." + re.escape(name) + r"\s*\(")
        callers = [f for f, t in blob.items() if name in t and pattern.search(t)]
        if callers:
            roots[name] = callers

    # transitive closure from the roots, through coordinator.py's own calls
    reached: dict[str, str] = {n: "direct" for n in roots}
    frontier = list(roots)
    while frontier:
        cur = frontier.pop()
        for callee in calls.get(cur, ()):
            if callee in spans and callee not in reached:
                reached[callee] = f"via {cur}"
                frontier.append(callee)

    rows = []
    for name, size in spans.items():
        if size < BIG_METHOD_LINES:
            continue
        how = reached.get(name)
        where = roots.get(name, [])[:2] if how == "direct" else ([how] if how else [])
        mentions = sum(1 for f, t in blob.items() if name in t and f not in roots.get(name, []))
        rows.append((size, name, where, mentions))
    rows.sort(reverse=True)
    return rows


def main() -> int:
    root = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else ".")
    rows = scan(root)
    print(f"{'lines':>6}  {'method':40} {'reached':>8} {'mentions':>9}  how")
    print("-" * 92)
    for size, name, callers, mentions in rows:
        flag = "" if callers else "  <-- NEVER REACHED"
        where = ", ".join(callers[:2])[:38]
        print(f"{size:>6}  {name:40} {('yes' if callers else 'no'):>8} {mentions:>9}  {where}{flag}")
    never = [r for r in rows if not r[2]]
    print(f"\n{len(never)} of {len(rows)} methods over {BIG_METHOD_LINES} lines are "
          f"never reached by any test; {sum(r[0] for r in never)} lines total.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
