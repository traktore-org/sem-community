"""YAML scenario suite — wires ``tests/scenarios/*.yaml`` into pytest discovery.

Each YAML file is one parametrized test. The scenario goes through
``scenario_harness.run_scenario`` which now drives the production
``coordinator._build_charging_context`` path (PR for framework adoption,
v1.7 prep). Failures here are real production-vs-scenario drift, not
harness noise.

Historical context: before the framework adoption, this file did not
exist. The 5 scenario YAMLs were a library that nothing called from CI.
The harness silently swallowed the AttributeError from the long-removed
``_determine_charging_strategy`` (PR #358) and every scenario "passed"
on the null outputs that fell out. Wiring into pytest closes that gap
— a failure now means there is genuinely a divergence between what the
scenario asserts and what production does, and one of:

  1. The scenario is outdated against the new arch and the YAML needs
     updating (most common when the failure is the symptom side of a
     known v1.7 cleanup).
  2. Production has regressed against the scenario's invariant (rare
     but the whole reason this suite exists — catches the v1.6.2 class).
  3. The harness setup is missing some config the scenario assumed.

Triage flow: ``pytest -k <stem> -v`` for the failing scenario, look at
``c.result`` from the cycles, file an issue.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from .scenario_harness import (
    assert_expectations,
    load_scenario,
    run_scenario,
)


SCENARIOS_DIR = Path(__file__).parent / "scenarios"
_YAML_PATHS = sorted(SCENARIOS_DIR.glob("*.yaml"))


# Scenarios that drift from current production behaviour. When the
# framework adoption first wired these scenarios into CI, 2 of 5 surfaced
# regime mismatches against the post-#358 arch decision path. Both have
# now been triaged + resolved:
#
#   * surplus_leak — RESOLVED. YAML drift. Missing ``charge_mode``
#     after the v6→v7 migration retired ``ev_charging_mode``.
#
#   * budget_unify_redirect — RESOLVED. Real arch regression where
#     decide.py::SolarOnlyMode skipped the forecast-aware battery
#     redirect, collapsing viable SOLAR_ONLY cycles to IDLE. Fix:
#     extracted ``flow_calculator.battery_redirect_w`` as a module-
#     level helper, added ``FleetContext.forecast_remaining_kwh``,
#     plumbed through ``build_charger_view``, and SolarOnlyMode now
#     computes ``effective_surplus = bare_surplus + redirect_w``
#     before the min-vs-surplus check. YAML inputs updated so the
#     redirect kicks in over the charger min (verifies the new
#     code path).
#
# Empty for now — but keep the structure so future drift can be
# tracked cleanly. ``strict=False`` so a future YAML/prod fix that
# makes any new xfail entry pass turns it green silently.
_XFAIL_DRIFT: dict[str, str] = {}


def _id_with_xfail(p: Path) -> str:
    return p.stem


def _params() -> list:
    out = []
    for p in _YAML_PATHS:
        reason = _XFAIL_DRIFT.get(p.stem)
        marks = [pytest.mark.xfail(reason=reason, strict=False)] if reason else []
        out.append(pytest.param(p, id=p.stem, marks=marks))
    return out


@pytest.mark.parametrize("yaml_path", _params())
@pytest.mark.asyncio
async def test_scenario(yaml_path: Path) -> None:
    """Execute one YAML scenario through the harness and check expectations."""
    scenario = load_scenario(yaml_path)
    run = await run_scenario(yaml_path)
    assert_expectations(run, scenario)
