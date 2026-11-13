"""(#1321) Tomorrow's preview names a car and a load like tonight's plan.

PROD 13.11: tonight's plan called the car "ev:ev_charger" and the preview
called it "ev:0", so the chart drew one charger as two rows.
"""
from __future__ import annotations

import ast
import inspect

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator


@pytest.mark.unit
def test_every_ask_carries_tonights_id():
    src = inspect.getsource(SEMCoordinator._compose_tomorrow_preview)
    tree = ast.parse(src.replace("\n    ", "\n").lstrip())
    keys = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "attr", "") == "append":
            for arg in node.args:
                if isinstance(arg, ast.Dict):
                    keys.append({k.value for k in arg.keys if isinstance(k, ast.Constant)})
    asks = [k for k in keys if "kind" in k]
    assert asks, "no asks found"
    assert all("id" in k for k in asks), asks
