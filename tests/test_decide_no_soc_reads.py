"""AST lint — ``coordinator/decide.py`` never reads SOC fields (#446).

The EV charging decision is pure ``decide.py`` logic that operates on
``view.target_kwh`` (computed upstream in ``_calculate_remaining_need``).
SOC reads — ``view.target_soc``, ``view.estimated_soc``,
``view.vehicle_soc``, or anything that retrieves estimated SOC from a
detector — must NEVER appear in this module. The invariant has been true
since #440 but was unpinned; this test locks it.
"""
import ast
import pathlib


_BANNED_ATTRS = {
    "target_soc",
    "estimated_soc",
    "vehicle_soc",
    "_estimated_soc",
}
_BANNED_CALLS = {"get_virtual_soc"}


def test_decide_py_never_reads_soc_fields():
    """AST-walk ``decide.py`` and assert no banned SOC field is read."""
    source = (
        pathlib.Path(__file__).parent.parent
        / "coordinator"
        / "decide.py"
    )
    assert source.exists(), f"decide.py not at expected path: {source}"
    tree = ast.parse(source.read_text())

    for node in ast.walk(tree):
        # ``view.target_soc`` / ``view.estimated_soc`` / ``view.vehicle_soc``
        # ``getattr(self, "_estimated_soc")`` — both covered.
        if isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRS:
            raise AssertionError(
                f"decide.py reads attribute {node.attr!r} at line "
                f"{node.lineno}. EV charging decisions must be pure kWh — "
                "SOC fields are upstream-only (#446 invariant)."
            )
        # ``detector.get_virtual_soc(...)``
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _BANNED_CALLS:
                raise AssertionError(
                    f"decide.py calls {func.attr!r} at line {node.lineno}. "
                    "The taper detector's virtual SOC must not enter "
                    "decision logic (#446 invariant)."
                )
