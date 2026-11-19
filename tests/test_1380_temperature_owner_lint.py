"""(#1380) AST lint: one place reads a device's temperature.

Outside ``devices/temperature.py`` no module reads ``current_temperature``
from an attribute dict or looks up a ``temperature_entity_id`` state itself:
it asks the owner. A justified exception carries ``# TEMP-ASK: <reason>`` on
the same line or the line above.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ALLOWED = {"devices/temperature.py"}
MARK = "# TEMP-ASK:"


def _mentions_sensor_field(node: ast.AST) -> bool:
    for n in ast.walk(node):
        if isinstance(n, ast.Attribute) and n.attr == "temperature_entity_id":
            return True
        if (isinstance(n, ast.Constant) and n.value == "temperature_entity_id"):
            return True
    return False


def violations(source: str) -> list[tuple[int, str, bool]]:
    """(line, what, excused) for every direct device-temperature read."""
    lines = source.splitlines()
    found: list[tuple[int, str, bool]] = []

    def add(node: ast.AST, what: str) -> None:
        n = node.lineno
        here = lines[n - 1] if n <= len(lines) else ""
        above = lines[n - 2].strip() if n >= 2 else ""
        found.append((n, what, MARK in here or above.startswith(MARK)))

    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Subscript) and isinstance(node.slice, ast.Constant)
                and node.slice.value == "current_temperature"):
            add(node, "['current_temperature']")
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and node.args):
            continue
        first = node.args[0]
        if isinstance(first, ast.Constant) and first.value == "current_temperature":
            add(node, ".get('current_temperature')")
        elif (isinstance(node.func.value, ast.Attribute)
              and node.func.value.attr == "states" and _mentions_sensor_field(first)):
            add(node, "states.get(temperature_entity_id)")
    return found


def test_no_direct_device_temperature_reads_outside_the_owner():
    bad, excused = [], 0
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if (rel.startswith(("tests/", "node_modules/", ".git", "scripts/"))
                or "/tests/" in rel or rel in ALLOWED):
            continue
        for line, what, ok in violations(p.read_text(encoding="utf-8")):
            if ok:
                excused += 1
            else:
                bad.append(f"{rel}:{line}: {what}")
    print(f"TEMP-ASK exceptions: {excused}")
    assert not bad, (
        "ask devices/temperature.py, or mark the line "
        "'# TEMP-ASK: <reason>' (#1380):\n" + "\n".join(bad))


def test_lint_catches_a_planted_violation_and_honours_the_marker():
    src = (
        "def f(hass, dev, st):\n"
        "    a = st.attributes.get('current_temperature')\n"
        "    b = hass.states.get(dev.temperature_entity_id)\n"
        "    c = st.attributes['current_temperature']\n"
        "    # TEMP-ASK: a reason\n"
        "    d = st.attributes.get('current_temperature')\n"
        "    e = hass.states.get(dev.other)\n"
        "    return a, b, c, d, e\n"
    )
    found = violations(src)
    assert [(n, ok) for n, _, ok in found if not ok] == [(2, False), (3, False), (4, False)]
    assert sum(ok for _, _, ok in found) == 1
