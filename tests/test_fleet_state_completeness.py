"""AST lint: every ``build_charger_view`` call must use ``fleet_state``.

The v1.7 prep PR shipped three patches for the same class of bug —
fleet-level info that the legacy ``_determine_charging_strategy`` had
access to wasn't getting plumbed into the new ``decide.py`` path.
``forecast_remaining_kwh`` (`eef65c2`), ``tariff_level`` (`b7cd903`),
and the night-plan ordering (`99288fb`) each landed as a one-off
patch on a single call site.

The structural fix: ``build_charger_view`` now takes a
:class:`FleetCycleState` positional arg as the SINGLE source of truth
for fleet inputs. Per-charger overrides stay as direct kwargs.

This lint enforces that contract — fails CI if any caller of
``build_charger_view`` either:

  1. Calls it without the ``fleet_state`` positional, OR
  2. Passes any of the deprecated fleet-level kwargs (``power_reading``,
     ``is_night``, ``config``, ``tariff_level``, ``forecast_remaining_kwh``)

Those kwargs no longer exist in the signature, so a caller that uses
them would also fail at runtime — but the AST lint catches it at PR
review time, with a clear error pointing at the offending file/line,
rather than waiting for a flaky import / silent type error.

The lint is the cheapest enforcement that structurally retires the
post-#358 plumbing-asymmetry bug class.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest


COORDINATOR_PKG = (
    Path(__file__).resolve().parent.parent / "coordinator"
)


# Field names that are NOW part of FleetCycleState. Passing any of
# these as a kwarg to build_charger_view bypasses the canonical
# state and re-introduces the asymmetry the refactor eliminated.
_FORBIDDEN_FLEET_KWARGS = frozenset({
    "power_reading",
    "is_night",
    "config",
    "tariff_level",
    "forecast_remaining_kwh",
})


def _find_build_charger_view_calls(path: Path) -> list[tuple[int, ast.Call]]:
    """Walk a Python file, return all (lineno, Call) for
    ``build_charger_view(...)`` invocations.
    """
    source = path.read_text()
    tree = ast.parse(source, filename=str(path))
    calls: list[tuple[int, ast.Call]] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Name):
            name = func.id
        elif isinstance(func, ast.Attribute):
            name = func.attr
        if name == "build_charger_view":
            calls.append((node.lineno, node))
    return calls


def _all_py_files() -> list[Path]:
    return [
        p for p in COORDINATOR_PKG.rglob("*.py")
        # Skip the function's own DEFINITION file. We only police
        # CALL SITES; the def is allowed (and required) to use the
        # canonical signature.
        if p.name != "build_view.py"
    ]


# ---------------------------------------------------------------------------
# Lint #1 — every call has fleet_state as first positional
# ---------------------------------------------------------------------------


def test_all_build_charger_view_calls_pass_fleet_state_positional() -> None:
    """Every call must supply ``fleet_state`` as the first positional
    arg. Catches callers that forget the canonical state and try to
    rely on the no-longer-existing default kwargs."""
    offending: list[str] = []
    for py in _all_py_files():
        for lineno, call in _find_build_charger_view_calls(py):
            # Need at least one positional arg, and it shouldn't be
            # an empty kwargs-only call.
            if not call.args:
                offending.append(
                    f"{py.relative_to(COORDINATOR_PKG.parent)}:{lineno} "
                    f"— build_charger_view() called without a positional "
                    f"fleet_state arg"
                )
    if offending:
        pytest.fail(
            "build_charger_view callers must pass FleetCycleState as the "
            "first positional arg. Offenders:\n  "
            + "\n  ".join(offending)
        )


# ---------------------------------------------------------------------------
# Lint #2 — no caller passes a forbidden fleet kwarg
# ---------------------------------------------------------------------------


def test_no_build_charger_view_call_uses_forbidden_fleet_kwargs() -> None:
    """No caller may pass ``power_reading=``, ``is_night=``, ``config=``,
    ``tariff_level=``, or ``forecast_remaining_kwh=`` to
    ``build_charger_view``. Those fields now live on FleetCycleState
    and are derived once per cycle. Passing them per-call re-introduces
    the asymmetry class the refactor eliminated (some callers
    remembered, some didn't, decide() saw different inputs)."""
    offending: list[str] = []
    for py in _all_py_files():
        for lineno, call in _find_build_charger_view_calls(py):
            forbidden_here = [
                kw.arg for kw in call.keywords
                if kw.arg in _FORBIDDEN_FLEET_KWARGS
            ]
            if forbidden_here:
                offending.append(
                    f"{py.relative_to(COORDINATOR_PKG.parent)}:{lineno} "
                    f"— forbidden fleet kwargs: {sorted(forbidden_here)}"
                )
    if offending:
        pytest.fail(
            "build_charger_view callers must not pass fleet-level kwargs "
            "directly — derive them from FleetCycleState. Offenders:\n  "
            + "\n  ".join(offending)
            + "\n\nFix: build the fleet state once via "
            "``coordinator._build_fleet_cycle_state(power, energy)``, "
            "then call ``build_charger_view(fleet_state, ...)``."
        )


# ---------------------------------------------------------------------------
# Lint #3 — production has at least N call sites (smoke check)
# ---------------------------------------------------------------------------


def test_build_charger_view_call_sites_exist() -> None:
    """Sanity: we still have at least 2 call sites (primary view +
    multi-charger loop). A future refactor that accidentally deletes
    all callers would silently break the test above; this catches
    that by requiring evidence of real callers."""
    all_calls = []
    for py in _all_py_files():
        all_calls.extend(_find_build_charger_view_calls(py))
    assert len(all_calls) >= 2, (
        f"Expected at least 2 build_charger_view call sites in "
        f"coordinator/, found {len(all_calls)}. Did the refactor "
        f"accidentally delete callers?"
    )
