"""AST lint — ``_calculate_remaining_need`` never reads ``estimated_soc`` (#446).

Pre-#446 the function had a rescue path that pulled the taper detector's
``estimated_soc`` (a.k.a. ``virtual_soc``) into the kWh budget when the
saved ``ev_target_type`` was ``"soc"`` but no real vehicle SOC sensor was
configured. That leak idled the EV on PROD 2026-06-06 against a
fictitious SOC. The fix removed the rescue path; this test pins the
invariant so a future refactor doesn't accidentally reintroduce it.
"""
import ast
import pathlib


_BANNED_ATTRS = {"_estimated_soc", "estimated_soc"}
_BANNED_NAMES = {"_estimated_soc", "estimated_soc"}
_BANNED_CALLS = {"get_virtual_soc"}
_BANNED_DETECTOR_ATTRS = {"_ev_taper_detector", "_ev_taper_detectors"}


def _find_function(tree: ast.AST, name: str) -> ast.FunctionDef:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    raise AssertionError(f"Could not find function {name!r} in source")


def test_calculate_remaining_need_never_reads_estimated_soc():
    """AST-walk ``_calculate_remaining_need`` and assert no banned name appears."""
    source = (
        pathlib.Path(__file__).parent.parent
        / "coordinator"
        / "coordinator.py"
    )
    assert source.exists(), f"coordinator.py not at expected path: {source}"
    tree = ast.parse(source.read_text())
    fn = _find_function(tree, "_calculate_remaining_need")

    for node in ast.walk(fn):
        # ``x.estimated_soc`` or ``x._estimated_soc``
        if isinstance(node, ast.Attribute) and node.attr in _BANNED_ATTRS:
            raise AssertionError(
                f"_calculate_remaining_need reads attribute {node.attr!r} at "
                f"line {node.lineno}. The EV target budget must never read "
                "estimated SOC — it leaks a fictitious SOC into kWh-mode "
                "decisions (#446)."
            )
        # ``estimated_soc`` as a bare name
        if isinstance(node, ast.Name) and node.id in _BANNED_NAMES:
            raise AssertionError(
                f"_calculate_remaining_need references name {node.id!r} at "
                f"line {node.lineno}. See #446."
            )
        # ``x.get_virtual_soc(...)``
        if isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Attribute) and func.attr in _BANNED_CALLS:
                raise AssertionError(
                    f"_calculate_remaining_need calls {func.attr!r} at "
                    f"line {node.lineno}. The taper detector's virtual SOC "
                    "must not enter the budget calculation (#446)."
                )
        # ``self._ev_taper_detector`` / ``self._ev_taper_detectors``
        if (
            isinstance(node, ast.Attribute)
            and node.attr in _BANNED_DETECTOR_ATTRS
        ):
            raise AssertionError(
                f"_calculate_remaining_need reads {node.attr!r} at "
                f"line {node.lineno}. The taper detector is not load-bearing "
                "for the kWh budget — only the saved config drives the mode "
                "(#446)."
            )
