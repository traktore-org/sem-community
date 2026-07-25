"""Pin the minimum scenario coverage set for v1.7.

Walks ``tests/scenarios/*.yaml``, extracts each scenario's declared
``coverage:`` tags, and asserts that every entry in :data:`MUST_COVER`
has at least one scenario carrying its tag.

How scenarios declare coverage
------------------------------
Each YAML file adds a top-level ``coverage:`` block listing one or
more ``(mode, regime)`` cells the scenario exercises::

    coverage:
      - mode: solar_only
        regime: zone3_day
        issue: "#284"

The matrix test only requires the keys ``mode`` and ``regime``.
``issue`` is a free-form trace (which closed GitHub issue this
scenario is the regression test for) and surfaces in the failure
message to help find context.

Why this lives in code, not docs
--------------------------------
A docs-only matrix rots silently — a new mode lands, the table
isn't updated, the gap goes undetected for months. The failure
message lists every uncovered cell with the issue that should
drive the scenario YAML, so the gap-fixing loop is::

    pytest tests/test_scenario_coverage.py
        → "cell X uncovered, see issue Y"
    gh issue view Y
        → grab PROD trace conditions
    create tests/scenarios/<date>_<descriptor>.yaml
        → re-run, cell now covered

See ``tests/test_scenario_coverage.py::MUST_COVER`` for the
intentionally short list. The bar is "core invariant per cell",
not "every possible input combination" — property-based tests in
``tests/test_budget_invariants.py`` carry the input-space coverage.
"""
from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest
import yaml


SCENARIOS_DIR = Path(__file__).parent / "scenarios"


@dataclasses.dataclass(frozen=True)
class Cell:
    """One must-cover (mode, regime) cell."""

    mode: str
    regime: str
    issue_hint: str = ""
    """Free-form pointer to the closed issue or PROD trace this cell
    should be the regression test for. Surfaced in the failure
    message — the user mining issues for scenarios should land here
    knowing exactly what to look for."""

    def key(self) -> tuple[str, str]:
        return (self.mode, self.regime)


# The minimum required coverage matrix. Intentionally compact — the
# property-based suite ``tests/test_budget_invariants.py`` covers the
# combinatorial input space; this matrix locks in one *narrative*
# scenario per regime so a future arch change re-breaks the
# behavioural contract loudly.
#
# When you add a new ev_charge_mode or regime: add the cell here +
# write the YAML. CI will tell you what's missing if you forget the
# YAML.
MUST_COVER: tuple[Cell, ...] = (
    # ─── off mode ─────────────────────────────────────────────
    Cell("off", "any", "#315 — off-mode reactive only; KEBA can auto-start on plug-in"),

    # ─── solar_only mode ──────────────────────────────────────
    Cell("solar_only", "zone3_day_surplus_leak",
         "#284 — car charged partly from grid in solar_only"),
    Cell("solar_only", "zone3_day_redirect",
         "#282 Phase B/D unification — forecast-aware battery redirect"),
    Cell("solar_only", "night_must_idle",
         "#346 — EV charges overnight in charge_mode=solar_only; strategy/state-machine disagreement"),
    # ``keba_zero_amps_self_charge`` (#353) — adapter-level quirk
    # covered structurally at the unit level in
    # ``tests/test_keba_zero_amps_353.py``. Not a YAML scenario
    # because the bug class is brand-specific actuator behaviour,
    # not a strategy/state-machine contract.

    # ─── min_plus_solar mode ──────────────────────────────────
    Cell("min_plus_solar", "zone3_day_battery_assist",
         "#282 Phase B/D — battery_assist regime"),
    Cell("min_plus_solar", "zone4_day_assist_drain",
         "#268 follow-up — Zone 4 full assist territory"),
    Cell("min_plus_solar", "night_top_up_at_min",
         "#268 — night charging exceeds peak limit when min current too high"),
    Cell("min_plus_solar", "night_deadline_floor",
         "#246 — target-time deadline (Phase 2)"),

    # ─── solar_plus_cheap mode ────────────────────────────────
    Cell("solar_plus_cheap", "day_normal_tariff_solar_only_like",
         "#247 — Phase 3 tariff-optimized; normal tariff = no boost"),
    Cell("solar_plus_cheap", "night_cheap_window_charges",
         "#247 — Phase 3 tariff-optimized; cheap window triggers night charge"),
    # ``night_expensive_skips`` (#280) is currently blocked at the
    # scenario level — the harness's stub tariff_provider doesn't
    # implement ``find_cheapest_hours`` so ``_compute_night_plan``
    # never sets ``should_wait_for_cheap=True``. Unit-level
    # coverage exists at ``tests/test_ev_tariff_planner.py``;
    # surface a scenario when the harness grows real tariff
    # lookahead support.

    # ─── always_max mode ──────────────────────────────────────
    Cell("always_max", "ignores_zone_and_tariff",
         "always_max contract — charge at max regardless of regime"),

    # ─── multi-charger ────────────────────────────────────────
    Cell("multi_charger", "fleet_cycle_with_multiple_chargers",
         "2+ chargers run a full cycle and land on the right "
         "canonical strategy"),
    Cell("multi_charger", "off_plus_solar_only_per_charger_state",
         "#315/#316 — per-charger effective state isolation"),
    Cell("multi_charger", "priority_cascade_mixed_modes",
         "#462/#464 — per-charger flow isolation under mixed modes "
         "(@RienduPre dual-Wallbox replay)"),

    # Retired in #651: ``split_canonical_total_equals_sum`` and
    # ``priority_cascade_with_mixed_modes``. Both named invariants of
    # ``SurplusController.distribute_ev_budget``, whose output
    # production wrote to ``pcc.budget_w`` and never read — so the
    # cells claimed coverage of an allocator no install ran.
    #
    # State this plainly rather than quietly renaming: there is NO
    # scenario-level coverage of the allocator that DOES run (the
    # per-charger loop threading ``_solar_committed_w_per_cycle`` into
    # each charger's view). The harness never drove it. Unit coverage
    # is tests/test_step6_multi_charger_surplus_sharing.py. Teaching
    # the harness the real loop is worth doing; it is a bigger job than
    # deleting the dead one, and it is not done.
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _load_coverage_tags() -> dict[tuple[str, str], list[str]]:
    """Walk YAML scenarios and return {(mode, regime): [yaml_paths]}."""
    found: dict[tuple[str, str], list[str]] = {}
    for path in SCENARIOS_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text())
        cov = (data.get("coverage") or []) if isinstance(data, dict) else []
        if not isinstance(cov, list):
            continue
        for tag in cov:
            if not isinstance(tag, dict):
                continue
            mode = tag.get("mode")
            regime = tag.get("regime")
            if not (isinstance(mode, str) and isinstance(regime, str)):
                continue
            found.setdefault((mode, regime), []).append(path.name)
    return found


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_every_must_cover_cell_has_a_scenario() -> None:
    """Every cell in MUST_COVER must be exercised by at least one YAML.

    Failure message lists the missing cells + their issue hints so the
    next step (mine the issue, write the YAML) is unambiguous.

    The v1.7 prep PR closed all 14 backlog cells across the 5 EV
    charge modes + multi-charger surface. Two cells deliberately do
    NOT appear in MUST_COVER:

    * ``solar_only/keba_zero_amps_self_charge`` (#353) — covered at
      adapter-unit level in ``tests/test_keba_zero_amps_353.py``.
    * ``solar_plus_cheap/night_expensive_skips`` (#280) — blocked
      at the YAML scenario level by the harness's stub tariff
      provider not implementing ``find_cheapest_hours``. Unit
      coverage lives in ``tests/test_ev_tariff_planner.py``.

    Both have comment-form placeholders in MUST_COVER. If either
    grows scenario-level coverage in the future, uncomment the
    relevant Cell entry.
    """
    found = _load_coverage_tags()
    missing: list[Cell] = [c for c in MUST_COVER if c.key() not in found]
    if missing:
        lines = ["", "Uncovered scenario cells (write a YAML for each):", ""]
        for c in missing:
            lines.append(f"  • {c.mode}/{c.regime}")
            if c.issue_hint:
                lines.append(f"      issue hint: {c.issue_hint}")
        lines.append("")
        lines.append(
            "Add a coverage tag block to a new or existing scenario YAML::"
        )
        lines.append(
            "    coverage:"
        )
        lines.append(
            "      - mode: <mode>"
        )
        lines.append(
            "        regime: <regime>"
        )
        lines.append(
            "        issue: \"#NNNN\""
        )
        pytest.fail("\n".join(lines))


def test_coverage_tags_only_use_known_modes() -> None:
    """A typo in a YAML coverage tag should fail loudly.

    Catches the case where someone writes ``mode: solor_only`` and the
    matrix test silently passes (no MUST_COVER cell to match it).
    """
    from custom_components.solar_energy_management.consts.ev_charge_modes import (
        EV_CHARGE_MODES,
    )

    valid_modes = set(EV_CHARGE_MODES.keys()) | {"multi_charger"}
    found = _load_coverage_tags()
    bad = [(mode, regime) for (mode, regime) in found if mode not in valid_modes]
    if bad:
        pytest.fail(
            "Unknown 'mode' values in scenario coverage tags: "
            f"{bad} — valid: {sorted(valid_modes)}"
        )


def test_every_yaml_has_at_least_one_coverage_tag() -> None:
    """No silent scenarios. Every YAML must declare what it covers.

    Untagged scenarios are 'I'll come back to this later' — that's how
    we ended up here in the first place.
    """
    untagged: list[str] = []
    for path in SCENARIOS_DIR.glob("*.yaml"):
        data = yaml.safe_load(path.read_text())
        cov = (data.get("coverage") or []) if isinstance(data, dict) else []
        if not cov:
            untagged.append(path.name)
    if untagged:
        pytest.fail(
            "Scenario YAMLs without a coverage tag block: "
            + ", ".join(untagged)
            + ". Add a 'coverage:' list at the top level — see "
            "tests/test_scenario_coverage.py docstring for the shape."
        )
