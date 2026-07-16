"""#598 structural guard — the user-facing "Remaining" tile must stay on the
SAME (raw) basis as the "Forecast today" tile beside it.

Root shape: a *corrected* quantity (the real-time dampened remaining solar,
used for surplus + best-window planning) was written back onto
``forecast_data.forecast_remaining_today_kwh`` — the field that feeds the
"Remaining" display sensor. ``forecast_today_kwh`` next to it is shown raw, so
at dawn (when the morning dampening factor sits near its 0.5 clamp floor) the
pair read as a contradiction: "Forecast today 70.8 kWh / Remaining 35 kWh" with
almost nothing produced yet, when remaining should ≈ today.

Closure: the dampened remaining is kept in a LOCAL variable
(``dampened_remaining``) that feeds surplus/window; the display field is written
exactly once — the raw copy from the forecast reader — and never re-derived.

This guard makes the regression UNREPRESENTABLE: it fails CI the moment
``_update_analytics_phases`` assigns ``forecast_data.forecast_remaining_today_kwh``
more than once, or assigns it anything other than the raw reader attribute.
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_COORD = _ROOT / "coordinator" / "coordinator.py"

_DISPLAY_FIELD = "forecast_remaining_today_kwh"
_TARGET_OBJ = "forecast_data"


def _method(tree: ast.AST, fn_name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == fn_name:
            return node
    raise AssertionError(f"{fn_name} not found in coordinator.py")


def _display_assignments(fn: ast.AST) -> list[ast.Assign]:
    """Every ``forecast_data.forecast_remaining_today_kwh = …`` in ``fn``."""
    out: list[ast.Assign] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if (
                isinstance(t, ast.Attribute)
                and t.attr == _DISPLAY_FIELD
                and isinstance(t.value, ast.Name)
                and t.value.id == _TARGET_OBJ
            ):
                out.append(node)
    return out


class TestDisplayRemainingStaysRaw:
    def test_display_field_assigned_exactly_once(self):
        tree = ast.parse(_COORD.read_text())
        fn = _method(tree, "_update_analytics_phases")
        assigns = _display_assignments(fn)
        assert len(assigns) == 1, (
            "_update_analytics_phases assigns "
            f"forecast_data.{_DISPLAY_FIELD} {len(assigns)} time(s); expected "
            "exactly 1 (the raw copy from the forecast reader). A second "
            "assignment re-derives the DISPLAY 'Remaining' — most likely the "
            "dampened value leaking back onto the user-facing tile, which "
            "contradicts the raw 'Forecast today' beside it (#598). Keep the "
            "dampened value in a LOCAL variable for surplus/window only."
        )

    def test_sole_assignment_is_the_raw_reader_value(self):
        tree = ast.parse(_COORD.read_text())
        fn = _method(tree, "_update_analytics_phases")
        assigns = _display_assignments(fn)
        assert assigns, "expected one display assignment (see sibling test)"
        rhs = assigns[0].value
        # The only legal RHS is a plain attribute read off the raw forecast
        # object (``forecast.forecast_remaining_today_kwh``). Anything computed
        # — a BinOp (``* dampening``), a Call (``round(...)`` / ``apply_dampening``)
        # — means a corrected value is being written to the display field.
        assert isinstance(rhs, ast.Attribute) and rhs.attr == _DISPLAY_FIELD, (
            "forecast_data.forecast_remaining_today_kwh must be assigned the RAW "
            f"reader value (an attribute read ending in .{_DISPLAY_FIELD}), not a "
            "computed/dampened expression. The 'Remaining' tile has to share the "
            "raw basis of the 'Forecast today' tile (#598)."
        )
