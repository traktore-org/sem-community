"""(#1321) The charging-strategy reason travels as a code next to its text.

The SEM Next Now screen says the primary charger's reason in the user's
language (``why_reason_<code>``); the text is SEM's log wording. These pin
that the code and its numbers reach the published data, and that the
coordinator copies them from the very decision whose text it publishes.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.charging_control import ChargingContext
from custom_components.solar_energy_management.coordinator.types import SEMData

ROOT = Path(__file__).resolve().parent.parent


@pytest.mark.unit
def test_published_data_carries_code_and_params():
    data = SEMData(
        charging_strategy_reason="solar_plus_battery day Zone 3: budget=0W below 8A min",
        charging_strategy_reason_code="charger_low_sun",
        charging_strategy_reason_params={"time": "06:00"},
    ).to_dict()
    assert data["charging_strategy_reason_code"] == "charger_low_sun"
    assert data["charging_strategy_reason_params"] == {"time": "06:00"}


@pytest.mark.unit
def test_defaults_are_empty_not_none():
    ctx = ChargingContext()
    assert ctx.charging_strategy_reason_code == ""
    assert ctx.charging_strategy_reason_params == {}
    data = SEMData().to_dict()
    assert data["charging_strategy_reason_code"] == ""
    assert data["charging_strategy_reason_params"] == {}


@pytest.mark.unit
def test_code_is_copied_where_the_text_is():
    """The code is set in the same block as the text, from the same decision."""
    src = (ROOT / "coordinator" / "coordinator.py").read_text()
    tree = ast.parse(src)
    targets = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            t = node.targets[0]
            if isinstance(t, ast.Attribute) and isinstance(t.value, ast.Name) and t.value.id == "charging_context":
                targets.setdefault(t.attr, []).append(node.lineno)
    assert "charging_strategy_reason" in targets
    assert "charging_strategy_reason_code" in targets
    assert "charging_strategy_reason_params" in targets
    text_line = targets["charging_strategy_reason"][0]
    for name in ("charging_strategy_reason_code", "charging_strategy_reason_params"):
        assert any(abs(line - text_line) <= 3 for line in targets[name]), name
