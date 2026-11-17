"""(#1306) AST lint: one answer for a battery pack's size.

``SensorReader._unit_size_kwh`` (setting, then the pack's own size sensor)
fills ``BatteryPower.capacity_kwh``; everyone else reads that. The sensor
scan (``_unit_size_sensor_kwh`` / ``_auto_detect_unit_capacity``) may be
called only from ``_unit_size_kwh``. An exception carries
``# SIZE-ASK: <reason>`` on the same line or the line above.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCAN = frozenset({"_unit_size_sensor_kwh", "_auto_detect_unit_capacity"})
OWNER = "_unit_size_kwh"
MARK = "# SIZE-ASK:"


def violations(source: str) -> list[tuple[int, str, bool]]:
    lines = source.splitlines()
    found: list[tuple[int, str, bool]] = []

    def visit(node: ast.AST, in_owner: bool) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            in_owner = node.name in (OWNER, *SCAN)   # the scan may call itself
        if (isinstance(node, ast.Attribute) and node.attr in SCAN
                and isinstance(getattr(node, "ctx", None), ast.Load) and not in_owner):
            n = node.lineno
            here = lines[n - 1]
            above = lines[n - 2].strip() if n >= 2 else ""
            found.append((n, node.attr, MARK in here or above.startswith(MARK)))
        for child in ast.iter_child_nodes(node):
            visit(child, in_owner)

    visit(ast.parse(source), False)
    return found


def test_only_the_size_owner_calls_the_sensor_scan():
    bad = []
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if rel.startswith(("tests/", "node_modules/", ".git")) or "/tests/" in rel:
            continue
        bad += [f"{rel}:{n}: {w}" for n, w, ok in violations(
            p.read_text(encoding="utf-8")) if not ok]
    assert not bad, ("read BatteryPower.capacity_kwh, or call _unit_size_kwh "
                     "(#1306):\n" + "\n".join(bad))


def test_lint_catches_a_planted_reader_and_honours_the_marker():
    src = (
        "class R:\n"
        "    def _unit_size_kwh(self, e, i):\n"
        "        return self._unit_size_sensor_kwh(e)\n"
        "    def other(self, e):\n"
        "        a = self._unit_size_sensor_kwh(e)\n"
        "        # SIZE-ASK: why\n"
        "        b = self._auto_detect_unit_capacity(e)\n"
        "        return a, b\n"
    )
    assert [(n, ok) for n, _, ok in violations(src)] == [(5, False), (7, True)]
