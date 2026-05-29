"""Pytest entry for the scenario replay harness (#282).

Discovers every ``tests/scenarios/*.yaml`` file and runs it through the
harness, asserting per the scenario's ``expect`` block. The harness
implementation lives in ``tests/scenario_harness.py``.

Each scenario captures a behaviour we want SEM to lock in — typically a
real-world trace where SEM did the wrong thing, used as a regression
test that fails until the bug is fixed.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from custom_components.solar_energy_management.tests.scenario_harness import (
    assert_expectations,
    load_scenario,
    run_scenario,
)


SCENARIO_DIR = Path(__file__).parent / "scenarios"


def _discover_scenarios():
    """Yield (id, path) tuples for every YAML in tests/scenarios/."""
    if not SCENARIO_DIR.is_dir():
        return []
    return sorted(SCENARIO_DIR.glob("*.yaml"))


@pytest.mark.parametrize(
    "yaml_path",
    _discover_scenarios(),
    ids=lambda p: p.stem if isinstance(p, Path) else str(p),
)
def test_scenario(yaml_path: Path):
    """Run one scenario file through the harness + assert its expectations.

    Failure messages from the harness name the specific cycle and the
    violated assertion (actuator amps over surplus ceiling, cumulative
    grid_to_ev exceeded budget, etc.) so a fix has a target to hit.
    """
    scenario = load_scenario(yaml_path)
    run = asyncio.new_event_loop().run_until_complete(run_scenario(yaml_path))
    assert_expectations(run, scenario)
