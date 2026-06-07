"""Verify the #432 heat-pump 'NOT registered' log is INFO not DEBUG.

Pre-#432 the failure path at __init__.py:1137 logged at DEBUG, so the
user had no surface that told them WHY their heat pump didn't register
without enabling debug logging for the SEM domain. Now it's INFO,
symmetric with the success-path INFO log at __init__.py:1130.

AST-walk __init__.py:
  1. Find the success branch and confirm it calls ``_LOGGER.info``.
  2. Find the failure branch and confirm it calls ``_LOGGER.info``
     too — NOT ``_LOGGER.debug``.
"""
import ast
import pathlib


_INIT_PATH = pathlib.Path(__file__).parent.parent / "__init__.py"


def _find_heat_pump_log_block(tree: ast.AST) -> ast.If | None:
    """Find the if/else block that registers the heat pump (the ``if has_sg_ready or
    has_climate`` branch). Returns the If node containing both branches."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Heuristic: find ``if has_sg_ready or has_climate:`` blocks
        test = node.test
        if isinstance(test, ast.BoolOp) and isinstance(test.op, ast.Or):
            names = [
                v.id for v in test.values
                if isinstance(v, ast.Name)
            ]
            if "has_sg_ready" in names and "has_climate" in names:
                return node
    return None


def _logger_call_methods(branch: list[ast.stmt]) -> list[str]:
    """Return the list of ``_LOGGER.<method>`` calls in a branch."""
    methods = []
    for node in ast.walk(ast.Module(body=branch, type_ignores=[])):
        if isinstance(node, ast.Call):
            func = node.func
            if (
                isinstance(func, ast.Attribute)
                and isinstance(func.value, ast.Name)
                and func.value.id == "_LOGGER"
            ):
                methods.append(func.attr)
    return methods


def test_heat_pump_failure_log_is_info_not_debug():
    """The 'NOT registered' branch must log at INFO so the user sees it
    without enabling debug logging for the SEM domain (#432)."""
    assert _INIT_PATH.exists(), f"__init__.py not at {_INIT_PATH}"
    tree = ast.parse(_INIT_PATH.read_text())
    block = _find_heat_pump_log_block(tree)
    assert block is not None, (
        "Could not find the ``if has_sg_ready or has_climate:`` heat-pump "
        "registration block in __init__.py — has the registration path "
        "moved? Update the AST search heuristic."
    )

    failure_methods = _logger_call_methods(block.orelse)
    assert "info" in failure_methods, (
        f"#432: the heat-pump NOT-registered branch must log at INFO so "
        f"the user sees it without enabling SEM debug logging. Got: "
        f"{failure_methods!r}."
    )
    assert "debug" not in failure_methods, (
        f"#432: the heat-pump NOT-registered branch still logs at DEBUG "
        f"on at least one path. Pre-#432 this is exactly the silence the "
        f"user was complaining about. Got: {failure_methods!r}."
    )
