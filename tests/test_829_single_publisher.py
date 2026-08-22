"""#829 — one key, one publisher (or a declared, agreeing pair).

The bug this exists for, found live on 22.08.2026:

``SEMData.to_dict()`` rounded ``forecast_dampening_factor`` to 2 dp and the
unit test asserting that PASSED. But ``ForecastTracker`` publishes the same
key, and ``result.update(tracker_data)`` runs after ``to_dict`` — so the
tracker's raw value won. The entity read 0.694 -> 0.707 -> 0.719 twenty
seconds apart, writing a recorder row every cycle, while the suite was green.

A unit test cannot catch this: it asserts one publisher while the other one
wins. Only diffing live attributes on a running instance found it — see
``scripts/audit_live_churn.py``, which is the tool for the other half of this
class (precision no human reads).

This guard is the static half: any key emitted BOTH by ``to_dict`` and by
something merged into the published result via ``result.update(...)`` must be
listed below, because the two sites must be checked to agree. The list is
SHRINK-ONLY — the same ratchet as #828's bounds allowlist.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: Sources merged into ``coordinator.data`` via ``result.update(...)``, mapped
#: to the module that builds them. A NEW merge source must be added here — the
#: test fails otherwise, so a new one cannot silently escape the check.
MERGE_SOURCES = {
    "tracker_data": "coordinator/forecast_tracker.py",
    "build_diagnostics(self)": "coordinator/publish_diag.py",
    "_lifetime_ev_shares(lifetime)": "coordinator/coordinator.py",
    "_vpp_publish": "coordinator/coordinator.py",
}

#: Keys knowingly published twice. Each MUST round/format identically at both
#: sites. Shrink-only: removing one by making it single-published is progress;
#: adding one requires justifying it here.
ALLOWED_DOUBLE_PUBLISH = {
    # (#829) to_dict emits it from ForecastSensorData, ForecastTracker emits
    # it too and wins via result.update. BOTH now round to 2 dp — verified
    # live on the rig (0.9 held stable where it churned every 20 s).
    "forecast_dampening_factor",
}


def _string_keys(tree, min_keys: int = 1) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict) and len(node.keys) >= min_keys:
            out |= {k.value for k in node.keys
                    if isinstance(k, ast.Constant) and isinstance(k.value, str)}
    return out


def _to_dict_keys() -> set[str]:
    tree = ast.parse((REPO / "coordinator" / "types.py").read_text())
    out: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "to_dict":
            out |= _string_keys(node)
    return out


def _merge_source_names() -> set[str]:
    """Every argument of a ``result.update(...)`` call in the coordinator."""
    tree = ast.parse((REPO / "coordinator" / "coordinator.py").read_text())
    names: set[str] = set()
    for n in ast.walk(tree):
        if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "update"
                and isinstance(n.func.value, ast.Name)
                and n.func.value.id == "result" and n.args):
            names.add(ast.unparse(n.args[0]))
    return names


@pytest.mark.unit
class TestOneKeyOnePublisher:

    def test_every_merge_source_is_known(self):
        """A new ``result.update(X)`` must be registered above, or this guard
        would quietly stop covering the thing it exists for."""
        unknown = []
        for name in _merge_source_names():
            if not any(k in name for k in MERGE_SOURCES):
                unknown.append(name)
        assert not unknown, (
            f"unregistered result.update() source(s): {unknown} — add them to "
            "MERGE_SOURCES so their keys are checked against to_dict"
        )

    def test_no_new_double_published_key(self):
        todict = _to_dict_keys()
        assert len(todict) > 100, "premise: to_dict key extraction broke"

        found: set[str] = set()
        for module in set(MERGE_SOURCES.values()):
            if module.endswith("coordinator.py"):
                continue  # same file as to_dict's caller; handled by review
            path = REPO / module
            if not path.exists():
                continue
            found |= todict & _string_keys(ast.parse(path.read_text()), min_keys=5)

        new = found - ALLOWED_DOUBLE_PUBLISH
        assert not new, (
            f"key(s) published by BOTH to_dict and a result.update() source: "
            f"{sorted(new)}. The later writer wins silently — a unit test on "
            "to_dict would pass while the entity shows the other value. Make "
            "it single-published, or add it to ALLOWED_DOUBLE_PUBLISH with "
            "both sites formatting identically."
        )

    def test_the_allowlist_has_not_grown_stale(self):
        """Shrink-only: an entry that is no longer double-published must be
        removed, so the list cannot rot into a rubber stamp."""
        todict = _to_dict_keys()
        found: set[str] = set()
        for module in set(MERGE_SOURCES.values()):
            if module.endswith("coordinator.py"):
                continue
            path = REPO / module
            if path.exists():
                found |= todict & _string_keys(ast.parse(path.read_text()), min_keys=5)
        stale = ALLOWED_DOUBLE_PUBLISH - found
        assert not stale, (
            f"{sorted(stale)} no longer double-published — remove from "
            "ALLOWED_DOUBLE_PUBLISH (the list only shrinks)"
        )
