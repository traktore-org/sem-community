"""#653 — structural guard for the designed-but-unwired half-feature class.

Every finding in the coherence-audit sweep that was an *unwired* feature had
the same fingerprint: a public method with a docstring describing when it
runs, a full unit test proving it works, and no production caller. #653's
``ApplianceScheduler.update_schedules`` ("called during coordinator update")
is the type specimen; #663's ``set_ev_daily_energy_sensor`` was found by this
scan while the guard was being written.

Unit tests cannot catch this. They call the method directly, so they assert
the method's *behaviour* and are silent about the *edge* — whether anything
in production reaches it. That is the meta-class in ``docs/BUG_CLASSES.md``:
spec-vs-reality gap.

The guard is a ratchet, not a clean-room rule. The baseline below is the set
of orphans that existed when it was written; the assertion is that the set
must not GROW. Adding a public method with no caller now fails CI. Wiring or
deleting a baseline entry means removing it from the list — the baseline only
shrinks.

Detection is deliberately generous, because a false positive here costs a
developer real time:

* ``.name`` attribute access anywhere in production code, and
* ``"name"`` as a string literal in Python, dashboard JS, or YAML — SEM
  dispatches through ``getattr(obj, "method", None)`` in several adapters
  (``KebaAdapter`` calls ``ensure_energy_guard_released`` exactly that way),
  and service handlers are reached by name from ``services.yaml``.

Both were learned the hard way while writing this: the first version of the
scan reported ``ensure_energy_guard_released`` as dead code, and it is not.

That generosity leaks in one known direction, and the trade is deliberate: a
method whose name happens to match an unrelated string literal — a service
name in ``__init__.py``'s teardown tuple, a config key, a translation key —
is suppressed even if it has no caller. So the ratchet under-reports rather
than over-reports. A false positive blocks CI and burns a developer's
afternoon proving the code is reachable; a false negative just means this
guard misses one orphan, which is where we already were before it existed.
"""
from __future__ import annotations

import ast
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_PACKAGES = ("devices", "coordinator", "features")

# Public methods with no production call site as of 2026-07-25.
#
# NOT an approval list — a debt list. Entries fall into three groups:
#
#   generic-accessor  — ``storage.py``'s symmetric get/set/clear API. Written
#                       as a complete surface; the callers use a subset. Low
#                       value to chase, real value to keep symmetric.
#   compat-alias      — kept for an older call shape or an external consumer.
#   UNTRIAGED         — genuinely unknown. Each one is a candidate #653/#663.
#                       Triaging these is follow-up work, not a blocker for
#                       the ratchet: locking the set stops the bleeding now.
_BASELINE = {
    # (#778) `spendable_budget` LEFT this list when phase 3 wired it to the
    # refill estimate — the guard's staleness check is what forced the removal,
    # which is the behaviour that keeps a baseline from rotting into a rubber
    # stamp. `forecast_for` / `actual_for` remain the ledger's read accessors,
    # used by its tests and by the phase-4 planner feed; remove them when that
    # lands.
    "forecast_for", "actual_for",
    # generic-accessor (coordinator/storage.py)
    "clear_daily_accumulators", "clear_monthly_accumulators", "get_accumulator",
    "get_baseline", "get_daily_accumulator", "get_flow_accumulator",
    "get_last_update", "get_monthly_accumulator", "get_previous_value",
    "get_session_history", "set_accumulator", "set_baseline",
    "set_daily_accumulator", "set_flow_accumulator", "set_monthly_accumulator",
    "set_previous_value",
    # compat-alias / public API kept deliberately
    "deactivate_all",                          # thin wrapper; #656 wired the
                                               # module-level deactivate_devices
    "create_dashboard",                        # generator entry point, service-driven
    # UNTRIAGED — each is a candidate finding
    "add_update_callback", "remove_update_callback",
    "get_diagnostics",
    "get_peak_margin",
    # TRIAGED, KEPT (#659): ``get_status`` is abstract on
    # BatteryChargeAdapter, implemented three times, and has ZERO production
    # callers — it computes a TARGET_REACHED nobody reads (the live
    # target-reached verdict is the scheduler's own SOC comparison). Unlike
    # its ``should_stop`` sibling, which #659 deleted, removing this is an
    # interface decision rather than a cleanup, so it is deliberately
    # deferred. Known-dead, not unknown.
    "get_status",
    # ``set_ev_daily_energy_sensor`` left this allowlist in #658 because it was
    # DELETED and replaced by a live one (``configure_ev_counters``), not
    # because it grew a caller. It was the setter for a reconciliation that was
    # written, parked, and never wired — the orphan scan is what found it. Do
    # not re-add.
    # HeatPumpController.block/unblock were baselined here waiting on #664 to
    # grow them a caller. #664 closed the other way — SEM does not support
    # ripple control / Sperrzeiten, so the actuator was deleted rather than
    # wired, and config_flow no longer advertises a 4th state SEM can't drive.
    # Nothing to allow: there is no orphan left.
    # ``validate_dependencies`` left this allowlist in #662 because the
    # method is deleted, not because it grew a caller. Cycles are now
    # rejected at the write path (DeviceRegistry._dependency_would_cycle)
    # instead of reported after the fact to nobody. Do not re-add.
    #
    # ``check_phase_switch``, ``should_stop`` and ``set_anticipated_surplus``
    # left in #659 for the same reason: all three are deleted, not wired.
    # Each was a whole feature that could never execute — 1p/3p switching
    # (no caller AND no config key), the force-charge stop rule (the
    # scheduler decides), and the #106 pre-warm hint (never called, never
    # read). If one of them reappears here, something re-added dead code.
}


def _public_methods() -> dict[str, str]:
    """name → ``file:line`` of the first definition."""
    found: dict[str, str] = {}
    for pkg in _PACKAGES:
        for path in sorted((_ROOT / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text())
            for cls in ast.walk(tree):
                if not isinstance(cls, ast.ClassDef):
                    continue
                for node in cls.body:
                    if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                        continue
                    if node.name.startswith("_"):
                        continue
                    # Properties and their setters are attribute reads, not
                    # calls — ``obj.x`` never looks like ``obj.x()``.
                    if any(
                        (isinstance(d, ast.Name) and d.id in
                         ("property", "staticmethod", "classmethod"))
                        or (isinstance(d, ast.Attribute) and
                            d.attr in ("setter", "getter", "deleter"))
                        for d in node.decorator_list
                    ):
                        continue
                    found.setdefault(
                        node.name,
                        f"{path.relative_to(_ROOT)}:{node.lineno}",
                    )
    return found


def _public_functions() -> dict[str, str]:
    """name → ``file:line`` for MODULE-LEVEL public functions.

    (#758) The scan above walks ``ClassDef`` bodies only, so a public
    function at module scope was invisible to it — which is how
    ``energy_planner.plan_overnight`` survived: a flat-slot adapter with
    no production caller and a large test corpus pointed straight at it,
    exactly the #653 fingerprint one indentation level out.

    Reachability is a different question here. A method is reached as
    ``obj.name(...)``, so the dotted-name search finds it; a function is
    imported and then called bare, so it needs a bare-name search with its
    own ``def`` removed — otherwise every function looks like it calls
    itself into existence.
    """
    found: dict[str, str] = {}
    for pkg in _PACKAGES:
        for path in sorted((_ROOT / pkg).rglob("*.py")):
            tree = ast.parse(path.read_text())
            for node in tree.body:
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if node.name.startswith("_"):
                    continue
                found.setdefault(
                    node.name, f"{path.relative_to(_ROOT)}:{node.lineno}",
                )
    return found


def _production_text() -> str:
    parts = []
    for path in _ROOT.rglob("*.py"):
        if "tests" in path.parts or "node_modules" in path.parts:
            continue
        parts.append(path.read_text())
    for pattern in ("dashboard/**/*.js", "*.yaml", "dashboard/*.yaml"):
        for path in _ROOT.glob(pattern):
            if "node_modules" in path.parts:
                continue
            parts.append(path.read_text(errors="ignore"))
    return "\n".join(parts)


def _orphans() -> dict[str, str]:
    blob = _production_text()
    out = {}
    methods = _public_methods()
    for name, where in methods.items():
        if re.search(r"\.%s\b" % re.escape(name), blob):
            continue
        if re.search(r"""['"]%s['"]""" % re.escape(name), blob):
            continue
        out[name] = where
    for name, where in _public_functions().items():
        if name in methods:      # also a method somewhere — judged above
            continue
        # Strip the definition itself; anything left is a reference.
        rest = re.sub(r"\bdef\s+%s\b" % re.escape(name), "", blob)
        if re.search(r"\b%s\b" % re.escape(name), rest):
            continue
        out[name] = where
    return out


@pytest.mark.unit
class TestNoNewOrphanMethods653:

    def test_the_orphan_set_does_not_grow(self):
        new = {n: w for n, w in _orphans().items() if n not in _BASELINE}
        assert not new, (
            "these public methods have no production call site — they are "
            "unreachable in the shipped integration and their unit tests "
            "prove only that the code works, not that anything runs it "
            "(#653). Wire them, delete them, or add them to _BASELINE with "
            "a reason:\n"
            + "\n".join(f"  {n}  ({w})" for n, w in sorted(new.items()))
        )

    def test_the_baseline_does_not_go_stale(self):
        """A wired-up or deleted entry must come OFF the list.

        Otherwise the baseline slowly turns into a list of names that mean
        nothing, and the next real orphan hides behind one of them.
        """
        orphans = _orphans()
        stale = sorted(_BASELINE - set(orphans))
        assert not stale, (
            "these are on the #653 orphan baseline but now have a caller "
            f"(or no longer exist) — remove them from _BASELINE: {stale}"
        )

    def test_the_scan_finds_the_specimen(self):
        """Meta-guard: if the detector silently stops working, both tests
        above pass forever. Prove it can still see an orphan."""
        assert _orphans(), "the orphan scan returned nothing — it is broken"
        assert "update_schedules" not in _orphans(), (
            "the #653 specimen is orphaned again"
        )
