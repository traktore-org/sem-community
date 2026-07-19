"""Regression test for the v1.6.7 bug surfaced on HA-TEST 2026-05-31.

The bug: ``PerChargerContext.__enter__`` snapshots a fixed set of
coordinator attributes into ``_saved`` before pushing this charger's
view. If ANY of those attributes is missing from
``SEMCoordinator.__init__``, the very first cycle of the
multi-charger loop blows up with ``AttributeError`` and the
integration stops updating.

How it slipped through. Every unit test mocks the coordinator via
``MagicMock`` and explicitly stubs the swap attributes (see
``tests/test_per_charger_context.py:_make_coord``). Single-charger
deployments never enter ``PerChargerContext`` so they never trigger
the missing-attribute path either. The bug only surfaces against a
real ``SEMCoordinator`` instance with two or more chargers.

This test parses ``coordinator.py``'s ``SEMCoordinator.__init__``
AST and asserts every attribute ``PerChargerContext.__enter__``
snapshots is initialized. It does NOT instantiate the coordinator
(too heavy for unit-test scope) — the AST check is fast, robust to
import-time HA dependencies, and would have caught the original
v1.6.7 ship.
"""
from __future__ import annotations

import ast
from pathlib import Path


COORDINATOR_PY = (
    Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"
)

# Attributes ``PerChargerContext.__enter__`` reads from ``coord``. If
# you add a new swap field to PerChargerContext, add it here AND to
# ``SEMCoordinator.__init__``. The lint above is mechanical; this
# list is the human review point.
REQUIRED_SWAP_ATTRS = {
    "_ev_device",
    # All 7 Surface-A scalars migrated off the swap to the durable _pcc_store
    # (#589 Surface-A) — they are coordinator PROPERTIES now, not snapshotted:
    #   _ev_stalled_since, _ev_enable_surplus_since, _ev_charge_started_at,
    #   _ev_last_change_time, _ev_reenable_attempts, _ev_charge_refused,
    #   _ev_last_set_amps_ts.
    # _current_charger_budget was deleted outright (#589 swap retirement —
    # dead scalar; budget flows through pcc.budget_w → build_charger_view).
    "_cycle_vehicle_soc",
    # v1.6.14 cache pointer for ``_this_charger_power`` shim.
    "_current_pcc",
    # v1.6.9 per-charger effective-state dict consumed by
    # ``_send_notifications``.
    "_effective_states_per_charger",
}


def _attributes_assigned_in_init(source: str, class_name: str) -> set[str]:
    """Return the set of ``self.<name>`` attributes assigned anywhere in
    ``class_name.__init__``.

    Walks the ``__init__`` body looking for ``Assign`` and ``AnnAssign``
    nodes whose target is a ``self.<name>`` ``Attribute``. Annotated
    assignments (``self._x: T = …``) count too — that's the form
    introduced by the v1.6.14 hotfix.
    """
    tree = ast.parse(source)
    assigned: set[str] = set()

    for cls in ast.walk(tree):
        if not isinstance(cls, ast.ClassDef) or cls.name != class_name:
            continue
        for fn in cls.body:
            if not isinstance(fn, ast.FunctionDef) or fn.name != "__init__":
                continue
            for node in ast.walk(fn):
                targets: list[ast.AST] = []
                if isinstance(node, ast.Assign):
                    targets.extend(node.targets)
                elif isinstance(node, ast.AnnAssign):
                    targets.append(node.target)
                for t in targets:
                    if (
                        isinstance(t, ast.Attribute)
                        and isinstance(t.value, ast.Name)
                        and t.value.id == "self"
                    ):
                        assigned.add(t.attr)
    return assigned


class TestPerChargerSwapAttrsInitialized:
    """Every attribute ``PerChargerContext.__enter__`` snapshots
    must be initialized in ``SEMCoordinator.__init__``. The actual
    PROD bug pattern: the v1.6.7 PerChargerContext refactor added
    ``_current_charger_budget`` (since deleted, #589) to the swap
    snapshot but never initialized it on the coordinator — every
    multi-charger setup crashed its first cycle until v1.6.14
    (HA-TEST 2026-05-31)."""

    def test_required_attrs_assigned_in_init(self):
        source = COORDINATOR_PY.read_text()
        assigned = _attributes_assigned_in_init(source, "SEMCoordinator")
        missing = REQUIRED_SWAP_ATTRS - assigned
        assert not missing, (
            "SEMCoordinator.__init__ does NOT initialize the following "
            "attributes that PerChargerContext.__enter__ snapshots:\n  "
            + "\n  ".join(sorted(missing))
            + "\n\nWithout an initial value, the snapshot read in "
            "PerChargerContext.__enter__ raises AttributeError on the "
            "very first cycle of the multi-charger loop — every "
            "multi-charger setup stops updating. (See HA-TEST repro "
            "2026-05-31; v1.6.7 PerChargerContext refactor missed the "
            "init for _current_charger_budget.)\n\n"
            "Fix: add ``self.<attr> = None`` (or appropriate default) "
            "to SEMCoordinator.__init__ for each missing attribute."
        )

    def test_required_list_matches_pcc_snapshot(self):
        """The ``REQUIRED_SWAP_ATTRS`` set is the human-maintained
        contract. If PerChargerContext starts snapshotting a new field,
        add it here AND to SEMCoordinator.__init__. This sub-test
        cross-checks that every attribute we require IS actually
        referenced by PerChargerContext — guards against the list
        going stale.
        """
        pcc_py = (
            Path(__file__).resolve().parent.parent
            / "coordinator" / "per_charger_context.py"
        )
        pcc_source = pcc_py.read_text()
        for attr in REQUIRED_SWAP_ATTRS:
            assert attr in pcc_source, (
                f"REQUIRED_SWAP_ATTRS contains {attr!r} but "
                "per_charger_context.py never references it. Either "
                "remove it from REQUIRED_SWAP_ATTRS or fix the "
                "snapshot."
            )
