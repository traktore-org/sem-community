"""(#1086 / #1022) AST lint: a missing measured value is not 0.

In the forecast, ledger and analytics modules a stored or live reading read
with ``.get("<measured key>", 0)`` turns "no reading" into a real 0 kWh day
that a learner, a score or a sum then trusts. Use ``None`` and skip it. A
justified exception carries ``# ZERO-OK: <reason>`` on the line or above.
"""
from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TOKENS = ("actual", "forecast", "accuracy", "kwh", "soc", "temperature",
          "yield")
MARK = "# ZERO-OK:"
GLOBS = ("coordinator/forecast_*.py", "coordinator/*ledger*.py",
         "analytics/*.py")


def violations(source: str) -> list[tuple[int, str]]:
    """(line, key) for every unexcused ``.get(<measured key>, 0)``."""
    lines = source.splitlines()
    found = []
    for node in ast.walk(ast.parse(source)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get" and len(node.args) == 2):
            continue
        key, dflt = node.args
        if not (isinstance(key, ast.Constant) and isinstance(key.value, str)
                and isinstance(dflt, ast.Constant)
                and isinstance(dflt.value, (int, float))
                and not isinstance(dflt.value, bool) and dflt.value == 0):
            continue
        if not any(t in key.value.lower() for t in TOKENS):
            continue
        n = node.lineno
        near = lines[n - 1] + " " + (lines[n - 2] if n >= 2 else "")
        if MARK not in near:
            found.append((n, key.value))
    return found


def test_no_measured_zero_default_in_the_tree():
    bad = []
    for pattern in GLOBS:
        for path in sorted(ROOT.glob(pattern)):
            for line, key in violations(path.read_text()):
                bad.append(f"{path.relative_to(ROOT)}:{line} .get({key!r}, 0)")
    assert not bad, "a missing reading read as 0:\n" + "\n".join(bad)


def test_lint_catches_a_planted_zero_default():
    assert violations('x = row.get("actual", 0)\n') == [(1, "actual")]
    assert violations('x = row.get("accuracy_pct", 0.0)\n')
    assert violations('x = row.get("weather", 0)\n') == []
    assert violations('x = row.get("actual")\n') == []


def test_lint_honours_the_excuse():
    ok = 'x = row.get("actual", 0)  # ZERO-OK: a counter that starts at 0\n'
    assert violations(ok) == []
    above = '# ZERO-OK: why\nx = row.get("kwh", 0)\n'
    assert violations(above) == []
