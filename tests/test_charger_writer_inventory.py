"""(#1381, charger owner S0) Every call site that can command a charger, counted.

The charger-owner map (``docs/ARCHITECTURE.md``, "Charger command owner")
found 16 code paths that can change what a charger does. Three of them
bypassed the decision chain and the reconciler, and each time one more path
was added, a fix on one side opened a gap on the other (#1381, #1402,
#1403, #1407, #1412).

This test lists every call of a charger-commanding verb in the files on the
charger path, by ``file::function::verb``. The list is a shrink-only
baseline: a NEW site fails here until it is either moved behind the owner or
declared on purpose (``tests/charger_writer_inventory_baseline.json.loosen``,
the repo's ratchet rule, #1304). Moving a site behind the owner removes it
from the list, and the baseline shrinks with it.
"""
from __future__ import annotations

import ast
import json
import pathlib
from collections import Counter

ROOT = pathlib.Path(__file__).resolve().parent.parent
BASELINE = ROOT / "tests" / "charger_writer_inventory_baseline.json"

#: Verbs that reach a charger: the one seam, the adapter verbs below it, the
#: device's own writes, and a raw service call.
VERBS = frozenset({
    "send", "switch_phases", "_send_phase_shape", "set_current",
    "_set_current", "start_session", "stop_session", "park_off",
    "arm_failsafe", "arm_failsafe_off", "release_to_user", "async_call",
    "command_start", "command_stop", "command_set_current", "press_resume",
})


def charger_path_files() -> list[pathlib.Path]:
    return [
        *sorted((ROOT / "coordinator").glob("*.py")),
        *sorted((ROOT / "coordinator" / "charger_adapters").glob("*.py")),
        ROOT / "devices" / "base.py",
        ROOT / "features" / "load_management.py",
        ROOT / "__init__.py",
    ]


def sites() -> Counter:
    """``{"file::function::verb": count}`` for every verb call."""
    out: Counter = Counter()
    for path in charger_path_files():
        tree = ast.parse(path.read_text(encoding="utf-8"))
        owner: dict[int, str] = {}
        for scope in ast.walk(tree):
            if isinstance(scope, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for node in ast.walk(scope):
                    owner.setdefault(id(node), scope.name)
        rel = path.relative_to(ROOT).as_posix()
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr in VERBS):
                fn = owner.get(id(node), "<module>")
                out[f"{rel}::{fn}::{node.func.attr}"] += 1
    return out


def _baseline() -> dict:
    return json.loads(BASELINE.read_text(encoding="utf-8"))


def test_no_new_charger_writer_site():
    """A call site not in the baseline, or one more call at a known site,
    is a new way to command a charger. Put it behind the owner, or declare
    it in the baseline with an issue."""
    known = _baseline()["sites"]
    grown = {k: v for k, v in sites().items() if v > known.get(k, 0)}
    assert not grown, (
        "new charger-commanding call sites (file::function::verb → count): "
        f"{grown}. Route them through the charger owner, or add them to "
        "tests/charger_writer_inventory_baseline.json with a "
        "RATCHET-LOOSENED declaration.")


def test_baseline_total_matches_its_sites():
    data = _baseline()
    assert data["total"] == sum(data["sites"].values())


def test_baseline_is_not_stale():
    """A site that is gone must leave the baseline too, so the count only
    ever shrinks to the truth."""
    live = sites()
    stale = {k: v for k, v in _baseline()["sites"].items() if live.get(k, 0) < v}
    assert not stale, (
        f"baseline lists sites the code no longer has: {stale}. "
        "Shrink tests/charger_writer_inventory_baseline.json.")


def test_baseline_only_shrinks():
    from .ratchet_guard import assert_not_loosened
    assert_not_loosened(BASELINE, lambda d: d["total"], "charger writer inventory")


if __name__ == "__main__":  # regenerate: python tests/test_charger_writer_inventory.py
    s = sites()
    BASELINE.write_text(json.dumps(
        {"total": sum(s.values()), "sites": dict(sorted(s.items()))},
        indent=1) + "\n", encoding="utf-8")
    print(f"{sum(s.values())} sites written")
