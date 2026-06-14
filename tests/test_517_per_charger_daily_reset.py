"""#517 — per-charger daily EV energy must roll over even when idle.

RienduPre (dual Wallbox) saw "Vandaag" (today) = 81.5 kWh on a charger
that wasn't even connected, while the fleet total correctly showed 0.

Root cause: in ``SEMCoordinator._update_ev_intelligence`` the per-charger
daily ROLLOVER (``self._daily_ev_per_charger[cid] = 0.0`` + date stamp)
was nested inside ``if charger_power > 0:`` together with the increment.
A charger that drew no power for a day never executed that block, so its
"today" counter never reset and carried yesterday's value forward,
growing across idle days.

The fix moves the date-check / reset OUT of the power guard so it runs
every cycle for every charger; only the INCREMENT stays gated on power.

This is an AST guard (matching the repo's other source lints) — it pins
that the reset is present AND not gated on ``charger_power > 0``, so the
regression can't silently return.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

_COORD = Path(__file__).resolve().parents[1] / "coordinator" / "coordinator.py"


def _method_node(name: str) -> ast.FunctionDef:
    tree = ast.parse(_COORD.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"{name} not found in coordinator.py")


def _is_per_charger_daily_reset(node: ast.AST) -> bool:
    """Match ``self._daily_ev_per_charger[<...>] = 0.0`` / ``= 0``."""
    if not isinstance(node, ast.Assign):
        return False
    for tgt in node.targets:
        if (
            isinstance(tgt, ast.Subscript)
            and isinstance(tgt.value, ast.Attribute)
            and tgt.value.attr == "_daily_ev_per_charger"
        ):
            v = node.value
            if isinstance(v, ast.Constant) and v.value in (0, 0.0):
                return True
    return False


def _is_power_guard(node: ast.AST) -> bool:
    """Match ``if charger_power > 0:``."""
    if not isinstance(node, ast.If) or not isinstance(node.test, ast.Compare):
        return False
    left = node.test.left
    return isinstance(left, ast.Name) and left.id == "charger_power"


@pytest.mark.unit
class TestPerChargerDailyRollover:
    def test_reset_exists_in_method(self):
        method = _method_node("_update_ev_intelligence")
        assert any(_is_per_charger_daily_reset(n) for n in ast.walk(method)), (
            "the per-charger daily reset (_daily_ev_per_charger[cid] = 0.0) "
            "vanished from _update_ev_intelligence"
        )

    def test_reset_not_nested_under_charger_power_guard(self):
        method = _method_node("_update_ev_intelligence")
        offenders = []
        for guard in ast.walk(method):
            if not _is_power_guard(guard):
                continue
            for child in guard.body:
                for sub in ast.walk(child):
                    if _is_per_charger_daily_reset(sub):
                        offenders.append(getattr(sub, "lineno", "?"))
        assert not offenders, (
            "#517 regression: the per-charger daily reset is nested inside "
            f"`if charger_power > 0:` (line(s) {offenders}). An idle/unplugged "
            "charger would never roll over and its 'today' counter would carry "
            "yesterday's value forward. Move the date-check/reset OUT of the "
            "power guard; gate only the increment on power."
        )
