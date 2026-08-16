"""#638 one-gate — the ONE-SELECTOR ratchet.

The unification's standing pin: cheap-window SELECTION belongs to the joint
planner alone. `tariff_provider.find_cheapest_hours` may only be called from
inside `tariff/tariff_provider.py` itself (its own rate estimator) and from
the files still on the shrinking allowlist below.

The allowlist starts at the pre-build reality and must SHRINK with the
retirement commits: C3 removes `ev_control.py`, C4 removes
`battery_charge_scheduler.py`, until the list is empty and the guard is the
permanent "no second selector" pin. Additions are impossible (test 1);
removals are forced (test 2 fails when an allowlisted file no longer calls
it, so a stale entry cannot linger).

House pattern: tests/test_ev_control_fleet_reads.py (AST lint at CI).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

# The selector's home — its own internal use is legitimate.
SELECTOR_HOME = "tariff/tariff_provider.py"

# EMPTY since C4 — the joint planner is the one selector left. This is the
# permanent pin: any new find_cheapest_hours caller anywhere fails CI.
# (C3 removed ev_control's pick; C4 removed the battery scheduler's.)
ALLOWLIST: frozenset[str] = frozenset()


def _python_files():
    for p in REPO.rglob("*.py"):
        rel = p.relative_to(REPO).as_posix()
        if rel.startswith(("tests/", "tmp/", ".", "node_modules/")):
            continue
        yield rel, p


def _calls_selector(path: Path) -> bool:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "find_cheapest_hours"):
            return True
    return False


@pytest.mark.unit
class TestOneSelector:
    def test_no_selector_calls_outside_the_allowlist(self):
        """Additions are impossible: a new caller anywhere fails CI."""
        offenders = [
            rel for rel, p in _python_files()
            if rel != SELECTOR_HOME and rel not in ALLOWLIST
            and _calls_selector(p)
        ]
        assert not offenders, (
            "cheap-window selection belongs to the joint planner alone; "
            f"unexpected find_cheapest_hours callers: {offenders}")

    def test_the_allowlist_matches_reality_exactly(self):
        """Removals are forced: retiring a caller without shrinking the
        allowlist fails, so the list can only ratchet down."""
        actual = {
            rel for rel, p in _python_files()
            if rel != SELECTOR_HOME and _calls_selector(p)
        }
        assert actual == set(ALLOWLIST), (
            f"allowlist is stale — update it. actual callers: {sorted(actual)}")
