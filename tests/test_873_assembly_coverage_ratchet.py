"""#873 — a large coordinator method must be RUN, and RUN means executed.

The gap this holds shut: SEM guards its big orchestration methods with AST /
``inspect.getsource`` assertions. Those catch a call site that stops existing.
They cannot catch a wrong formula, and all three defects the #778 arc shipped
were wrong formulas with every name correctly in scope — a bound method passed
instead of its result, headroom measured at sunset instead of dawn, a block
anchored to ``now`` that cancelled itself.

Two wrong ways to measure this were tried first, and both are worth naming
because each is comfortable in its own way:

* **Direct calls by name.** Too strict. One run of the main cycle genuinely
  exercises the six assemblies it calls; demanding a by-name test for each
  would produce shallow name-calling tests for code already covered.
* **Static reachability on the call graph.** Too loose, and dangerously so.
  ``async_initialize_energy_dashboard`` is reachable from
  ``_retry_energy_dashboard_resolution`` and is never executed — the branch
  is false under test. That measurement reports "all covered" over code
  nothing runs.

So this file INSTRUMENTS a real cycle and asserts what actually ran.
"""
from __future__ import annotations

import asyncio
import inspect
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from audit_assembly_coverage import BIG_METHOD_LINES, scan  # noqa: E402

from custom_components.solar_energy_management.coordinator import (  # noqa: E402
    coordinator as coordinator_module,
)

from .test_873_cycle_executes import (  # noqa: E402
    WIRED,
    _sensors,
    run_cycle,
    sealed_nights,
)

#: Big methods that a real cycle does NOT execute, with their size. Shrink
#: only. Each entry is a method where a wrong formula would reach a user
#: without a test noticing.
#:
#: ``_shadow_energy_plan`` is not here: it has eight direct tests that call it
#: by name. This ledger is only for methods nothing runs AT ALL.
KNOWN_UNEXECUTED: dict[str, int] = {
    # EMPTY, and that is the point: every coordinator method over
    # BIG_METHOD_LINES is now either executed by a real cycle or called
    # directly by a test. #873 closed the last one
    # (async_initialize_energy_dashboard, 152 lines — see
    # tests/test_873_energy_dashboard_init.py).
    #
    # An entry here is a method where a wrong formula reaches a user with no
    # test noticing. Adding one is a decision to accept that, so it belongs
    # in a commit message with a reason, not in a quiet edit.
}


def _executed_during_a_cycle() -> set[str]:
    """Method names that actually ran during one instrumented cycle."""
    cls = coordinator_module.SEMCoordinator
    seen: set[str] = set()
    originals: dict[str, object] = {}

    # Wrap EVERY method, not only the big ones: the assertion below names
    # `_build_system_status` (35 lines), and instrumenting only the >120-line
    # set made this test assert on something it never measured — it reported
    # that method as unexecuted because nothing was watching for it.
    # Plain instance methods only. ``vars(cls)`` also holds staticmethods,
    # classmethods and properties, and wrapping those with a ``self``-taking
    # wrapper raises (``_resolve_battery_cycles() takes 2 positional
    # arguments but 3 were given``). ``inspect.isfunction`` over the class
    # __dict__ is exactly the instance-method set.
    names = [n for n, v in vars(cls).items()
             if not n.startswith("__") and inspect.isfunction(v)]
    for name in names:
        original = vars(cls)[name]
        originals[name] = original

        def wrap(method_name, func):
            if asyncio.iscoroutinefunction(func):
                async def wrapper(self, *args, **kwargs):
                    seen.add(method_name)
                    return await func(self, *args, **kwargs)
            else:
                def wrapper(self, *args, **kwargs):
                    seen.add(method_name)
                    return func(self, *args, **kwargs)
            return wrapper

        setattr(cls, name, wrap(name, original))

    loop = asyncio.new_event_loop()
    try:
        loop.run_until_complete(
            run_cycle(WIRED, _sensors(6000, 2000, 1500, 100), sealed_nights())
        )
    finally:
        loop.close()
        # Restore unconditionally: a wrapped class leaking out of this
        # helper would follow every later test in the session.
        for name, original in originals.items():
            setattr(cls, name, original)
    return seen


def _directly_called() -> set[str]:
    """Big methods some test calls by name (the static roots)."""
    return {name for _, name, where, _ in scan(ROOT)
            if where and not str(where[0]).startswith("via ")}


@pytest.fixture(scope="module")
def uncovered() -> dict[str, int]:
    ran = _executed_during_a_cycle()
    direct = _directly_called()
    return {name: size for size, name, _, _ in scan(ROOT)
            if name not in ran and name not in direct}


def test_no_new_unexecuted_assembly(uncovered):
    new = set(uncovered) - set(KNOWN_UNEXECUTED)
    assert not new, (
        f"these coordinator methods are over {BIG_METHOD_LINES} lines and "
        f"nothing RUNS them: {sorted(new)}.\n"
        "A method this size is where arguments get derived and results get "
        "combined — the place every #778 defect lived. An AST guard proves a "
        "name is in scope; it cannot see a wrong formula. Give it a scenario "
        "test that runs it and asserts what it publishes (see "
        "tests/test_873_cycle_executes.py), or add it to KNOWN_UNEXECUTED "
        "with its size and a reason in the commit."
    )


def test_the_ledger_only_shrinks(uncovered):
    """An entry that is now covered must be REMOVED, so the ledger keeps
    describing today rather than the day it was written."""
    stale = set(KNOWN_UNEXECUTED) - set(uncovered)
    assert not stale, (
        f"{sorted(stale)} are executed now — delete them from "
        "KNOWN_UNEXECUTED. A stale allowance quietly re-permits the gap."
    )


def test_the_main_cycle_and_what_it_drives_are_executed():
    """The prize: 2236 lines publishing 325 values — every sensor SEM
    exposes, every card field, every decision input — plus the assemblies
    that cycle drives. Thirteen test files mentioned it before #873; all of
    them via ``inspect.getsource``."""
    ran = _executed_during_a_cycle()
    for name in ("_async_update_data", "_update_analytics_phases",
                 "_update_ev_intelligence", "_build_charging_context",
                 "_build_system_status", "_record_forecast_horizons"):
        assert name in ran, f"{name} did not execute during a real cycle"
