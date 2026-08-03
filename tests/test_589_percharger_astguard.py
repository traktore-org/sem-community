"""#589 Surface-A structural guard — a reintroduced per-charger leak is
UNREPRESENTABLE, not just caught by the isolation tests.

The multi-charger "charger[0]'s state bleeds into charger[1]" class
(#284/#289/#315/#318) came from per-charger scalars swapped through the
coordinator's primary attributes in ``PerChargerContext.__enter__/__exit__``:
forget the write-back for a field and it leaks. Surface-A migrated all 7
leak-prone scalars onto the durable ``PerChargerState``/``_pcc_store`` (held by
reference — no write-back to forget). These AST guards lock that in:

1. ``__enter__``/``__exit__`` may assign NO ``coord._ev_*`` attribute at
   all — the swap surface is GONE (#589 swap retirement complete; even
   ``_ev_device`` is a pcc-dispatching property now). Any new
   ``coord._ev_<x> = …`` swap fails CI — add a ``PerChargerState`` field
   or a pcc-backed property instead (which cannot leak).
2. The retired parallel ``_ev_*_per_charger`` dicts must not reappear.
3. The 7 migrated fields must live on ``PerChargerState`` (their safe home).
"""
from __future__ import annotations

import ast
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PCC = _ROOT / "coordinator" / "per_charger_context.py"
_COORD = _ROOT / "coordinator" / "coordinator.py"

# NO ``coord._ev_*`` assignment is allowed in the context manager any more:
# the swap surface is fully retired (#589). ``_ev_device`` became a
# pcc-dispatching coordinator property; ``_ev_budget_history`` was DEAD state
# (consumer removed in #536) and was deleted, not migrated.
_ALLOWED_SWAP: set[str] = set()

_MIGRATED_FIELDS = {
    "stalled_since", "enable_surplus_since", "charge_started_at",
    "last_change_time", "reenable_attempts", "charge_refused", "last_set_amps_ts",
}
_RETIRED_DICTS = {f"_ev_{n}_per_charger" for n in (
    "stalled_since", "enable_surplus", "charge_started", "last_change",
    "reenable_attempts", "charge_refused", "last_set_amps_ts",
)}


def _method(tree: ast.AST, cls_name: str, fn_name: str) -> ast.FunctionDef:
    for cls in ast.walk(tree):
        if isinstance(cls, ast.ClassDef) and cls.name == cls_name:
            for fn in cls.body:
                if isinstance(fn, ast.FunctionDef) and fn.name == fn_name:
                    return fn
    raise AssertionError(f"{cls_name}.{fn_name} not found")


def _coord_ev_assign_targets(fn: ast.FunctionDef) -> set[str]:
    """``coord._ev_<x>`` attributes assigned (the swap surface)."""
    out: set[str] = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Assign):
            continue
        for t in node.targets:
            if (
                isinstance(t, ast.Attribute)
                and isinstance(t.value, ast.Name)
                and t.value.id == "coord"
                and t.attr.startswith("_ev_")
            ):
                out.add(t.attr)
    return out


class TestSwapSurfaceLocked:
    def test_enter_exit_only_swap_allowed_ev_attrs(self):
        tree = ast.parse(_PCC.read_text())
        assigned = set()
        assigned |= _coord_ev_assign_targets(_method(tree, "PerChargerContext", "__enter__"))
        assigned |= _coord_ev_assign_targets(_method(tree, "PerChargerContext", "__exit__"))
        illegal = assigned - _ALLOWED_SWAP
        assert not illegal, (
            "PerChargerContext.__enter__/__exit__ swaps a per-charger "
            f"coord._ev_* scalar that is NOT allowed: {sorted(illegal)}.\n"
            "The swap surface leaks charger[0] into charger[1] when a "
            "write-back is forgotten (#284/#315/#318). Add a field to "
            "PerChargerState instead (it's held by reference — cannot leak), "
            "and expose it via a coordinator property. See #589 Surface-A."
        )

    def test_retired_per_charger_dicts_do_not_reappear(self):
        # AST attribute references only — a doc COMMENT that names an old dict
        # (e.g. "migrated off _ev_stalled_since_per_charger") is fine; a real
        # code reference is the regression we forbid.
        refs: set[str] = set()
        for f in (_PCC, _COORD):
            for node in ast.walk(ast.parse(f.read_text())):
                if isinstance(node, ast.Attribute) and node.attr in _RETIRED_DICTS:
                    refs.add(node.attr)
        assert not refs, (
            f"retired per-charger swap dict(s) referenced in code: {sorted(refs)} "
            "— these were migrated to PerChargerState/_pcc_store (#589)."
        )

    def test_migrated_fields_live_on_per_charger_state(self):
        tree = ast.parse(_PCC.read_text())
        state = next(
            c for c in ast.walk(tree)
            if isinstance(c, ast.ClassDef) and c.name == "PerChargerState"
        )
        fields = {
            n.target.id for n in state.body
            if isinstance(n, ast.AnnAssign) and isinstance(n.target, ast.Name)
        }
        missing = _MIGRATED_FIELDS - fields
        assert not missing, f"PerChargerState is missing migrated field(s): {sorted(missing)}"
