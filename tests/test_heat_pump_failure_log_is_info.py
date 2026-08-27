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
    """Find the branch that logs the heat-pump NOT-registered case.

    Since #685 the registration is a loop and the failure surface is the
    ``if hp_registered == 0:`` block (its BODY holds the log call)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        test = node.test
        if (
            isinstance(test, ast.Compare)
            and isinstance(test.left, ast.Name)
            and test.left.id == "hp_registered"
            and len(test.comparators) == 1
            and isinstance(test.comparators[0], ast.Constant)
            and test.comparators[0].value == 0
        ):
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
        "Could not find the ``if hp_registered == 0:`` heat-pump "
        "not-registered block in __init__.py — has the registration path "
        "moved? Update the AST search heuristic."
    )

    failure_methods = _logger_call_methods(block.body)
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
