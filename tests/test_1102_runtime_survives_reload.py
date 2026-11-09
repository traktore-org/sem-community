"""(#1102) A load's run time today survives a restart or a settings change.

The heat pump and the hot-water tank are registered after the registry's
runtime restore, so their minutes went back to 0 on every reload (reporter:
"restarting HA, or changing some settings will lose the daily runtime
counters"; .175 09.11: 23 min → 0 with 1,350 s still in storage). Setup must
restore once more after the LAST load is registered.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _setup_entry() -> ast.AST:
    tree = ast.parse((ROOT / "__init__.py").read_text())
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.AsyncFunctionDef) and n.name == "async_setup_entry")


def _call_lines(fn: ast.AST, attr: str) -> list:
    return [n.lineno for n in ast.walk(fn)
            if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute) and n.func.attr == attr]


@pytest.mark.unit
def test_the_last_restore_comes_after_the_last_registered_load():
    fn = _setup_entry()
    registers = _call_lines(fn, "register_device")
    restores = _call_lines(fn, "_restore_device_runtimes")
    assert registers and restores
    assert max(restores) > max(registers), (
        "a load registered after the last runtime restore starts the day at 0 min")


@pytest.mark.unit
def test_a_second_restore_leaves_a_filled_device_alone():
    from types import SimpleNamespace
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator

    dev = SimpleNamespace(_daily_runtime_accumulated_sec=1350.0)
    store = SimpleNamespace(get_device_runtimes=lambda: {"hot_water": {"runtime_sec": 999.0}})
    fake = SimpleNamespace(_storage=store, _surplus_controller=SimpleNamespace(get_device=lambda i: dev),
                           _runtimes_restored=False)
    SEMCoordinator._restore_device_runtimes(fake)
    assert dev._daily_runtime_accumulated_sec == 1350.0
