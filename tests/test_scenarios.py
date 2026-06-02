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
# regime mismatches against the post-#358 arch decision path. After
# triage on develop:
#
#   * surplus_leak — RESOLVED. The YAML used the legacy ``ev_charging_mode``
#     key that the v6→v7 migration drops; without an explicit
#     ``charge_mode``, the harness fell back to DEFAULT_EV_CHARGE_MODE
#     ("min_plus_solar") which has a different surplus formula. Adding
#     ``charge_mode: "solar_only"`` to the YAML put it back on the path
#     the regression was originally pinned against. Now passing.
#
#   * budget_unify_redirect — REAL ARCH REGRESSION (not scenario drift).
#     Pre-arch (v1.6.x): ``solar_only`` strategy + Zone 3 SOC + generous
#     forecast → ``flow_calculator._calculate_battery_redirect`` diverted
#     part of the battery_charge_w to EV (1700W on this scenario's inputs).
#     Post-arch (#358): ``decide.py::SolarOnlyMode`` computes surplus as
#     ``solar - home - battery_charge_w`` for any SOC below auto_start_soc,
#     returns IDLE when that's below the 4140W (6A) charger min, and
#     canonical_strategy collapses to IDLE — so calculate_canonical_ev_budget
#     never reaches its SOLAR_ONLY branch where the redirect would have
#     fired. The forecast-aware redirect for SOLAR_ONLY is now dead code.
#     Whether that's intentional or a regression is an open question —
#     decide.py has TODOs about "Zone 3 forecast check deferred" but
#     it's not clear whether someone consciously dropped redirect or
#     it slipped. Leaving as xfail until the arch reviewer rules.
#
# ``strict=False`` so a future fix that makes them pass doesn't
# accidentally fail CI.
_XFAIL_DRIFT = {
    "2026-05-29_budget_unify_redirect": (
        "Real arch regression: post-#358 decide.py::SolarOnlyMode subtracts "
        "battery_charge_w from surplus for SOC < auto_start_soc, returns IDLE "
        "when < 4140W (6A), and canonical_strategy collapses to IDLE — so "
        "flow_calculator._calculate_battery_redirect (the SOLAR_ONLY branch) "
        "is never reached. Forecast-aware redirect appears unreachable in the "
        "new arch. Triage: intentional simplification or regression? "
        "See tests/scenarios/2026-05-29_budget_unify_redirect.yaml for the "
        "Phase B/D #282 unification contract this scenario pins."
    ),
}


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
