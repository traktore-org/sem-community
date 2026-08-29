"""#778 phase 1 — the horizon ledger actually gets fed.

The failure this pins is the one that has bitten SEM repeatedly (#819's inert
picker, the two-publisher forecast factor): a component that exists, has tests,
and is never called. A ledger nobody writes to accrues nothing, and the
emptiness looks exactly like "not enough evidence yet" — the most expensive
possible way to fail, because it is silent for a season.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent


@pytest.mark.unit
class TestTheLedgerIsWiredNotJustWritten:

    def test_the_coordinator_calls_the_recorder(self):
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        assert "_record_forecast_horizons(" in src
        tree = ast.parse(src)
        names = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
        assert "_record_forecast_horizons" in names, "the method does not exist"
        # …and it is CALLED, not merely defined.
        called = any(
            isinstance(n, ast.Call)
            and getattr(n.func, "attr", None) == "_record_forecast_horizons"
            for n in ast.walk(tree)
        )
        assert called, "the recorder is defined but never invoked — an inert half"

    def test_it_runs_on_the_per_cycle_path(self):
        """Not on a rarely-run branch: #819's picker passed a 'the call exists'
        test while sitting on a path that ran on reload only."""
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        i = src.index("self._forecast_tracker.get_data()")
        window = src[i:i + 1200]
        assert "_record_forecast_horizons(" in window, (
            "the ledger update is not adjacent to the per-cycle forecast read"
        )

    def test_it_persists_through_the_store(self):
        store = (REPO / "coordinator" / "storage.py").read_text()
        assert "get_forecast_ledger_state" in store
        assert "set_forecast_ledger_state" in store
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        assert "set_forecast_ledger_state" in src, "recorded but never saved"
        assert "get_forecast_ledger_state" in src, "saved but never restored"

    def test_a_missing_far_forecast_is_not_recorded_as_zero(self):
        """Sources that stop at tomorrow publish 0.0 for d2. Recording that as
        a forecast would teach the ledger that the sun does not rise."""
        import ast
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_record_forecast_horizons")
        # AST-bounded, not a character count: the first version windowed 2200
        # chars and started failing the moment the method grew — the same
        # mistake this file already made once.
        body = ast.get_source_segment(src, fn) or ""
        assert "if value:" in body, (
            "a 0.0 / absent far-horizon forecast must be skipped, not recorded"
        )


@pytest.mark.unit
class TestTheCallSiteActuallyResolves:
    """Caught live on .175, not by the suite: the call passed `now_time`, which
    is not in scope there. A broad `except Exception` turned the NameError into
    a DEBUG line, so 7885 tests stayed green while six sensors sat
    `unavailable` on a real instance for two hours.

    Two lessons, both pinned here: the arguments must resolve, and a
    programming error must not be swallowed into the same channel as a missing
    sensor reading."""

    def test_every_argument_at_the_call_site_is_in_scope(self):
        import ast
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        tree = ast.parse(src)

        call = None
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "attr", None) == "_record_forecast_horizons"):
                call = node
                break
        assert call is not None, "the recorder is no longer called"

        # Find the enclosing function and collect every name bound in it.
        enclosing = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if node.lineno <= call.lineno <= (node.end_lineno or node.lineno):
                    if enclosing is None or node.lineno > enclosing.lineno:
                        enclosing = node
        assert enclosing is not None

        bound = {a.arg for a in enclosing.args.args}
        for n in ast.walk(enclosing):
            if isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store):
                bound.add(n.id)
            elif isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    bound.add((al.asname or al.name).split(".")[0])
        # module-level names are fine too
        for n in tree.body:
            if isinstance(n, (ast.Import, ast.ImportFrom)):
                for al in n.names:
                    bound.add((al.asname or al.name).split(".")[0])
            elif isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                bound.add(n.name)

        for arg in call.args:
            for nm in ast.walk(arg):
                if isinstance(nm, ast.Name) and isinstance(nm.ctx, ast.Load):
                    assert nm.id in bound or nm.id in dir(__builtins__), (
                        f"'{nm.id}' is passed to _record_forecast_horizons but is "
                        "not bound in the enclosing scope — this is exactly the "
                        "NameError that shipped to .175"
                    )

    def test_the_handler_does_not_swallow_programming_errors(self):
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        i = src.index("self._record_forecast_horizons(")
        window = src[i:i + 700]
        import re
        # Match the STATEMENT, not the word — the comment above the handler
        # explains why a broad catch is wrong and must not trip its own guard.
        assert not re.search(r"^\s*except Exception", window, re.M), (
            "a broad handler here hid a NameError as a DEBUG line while the "
            "suite stayed green"
        )
        assert "_LOGGER.warning" in window, (
            "a skipped ledger update must be visible, not debug-only"
        )


@pytest.mark.unit
class TestTheNightRecordsAreActuallyRead:
    """Second live-only failure in the same wiring: `BatteryNightTracker.sealed`
    is a METHOD, not a property. Reading it without calling handed
    measured_capacity a bound method — 'method' object is not iterable — and
    every planning sensor went unavailable.

    Only visible because the handler had just been narrowed to WARNING. As the
    original DEBUG line it would have shipped."""

    def test_sealed_is_invoked_not_merely_referenced(self):
        import ast
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        tree = ast.parse(src)
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_record_forecast_horizons")
        # Bound by the real method, not a guessed character count — the first
        # version of this test windowed 3000 chars and missed the line it was
        # written to catch.
        body = ast.get_source_segment(src, fn) or ""
        assert "tracker.sealed()" in body, (
            "sealed is a method; referencing it yields a bound method and the "
            "capacity reader silently produces nothing"
        )

    def test_the_tracker_still_exposes_it_as_a_method(self):
        """If this ever becomes a property, the call above breaks — so pin the
        premise rather than let the two drift."""
        src = (REPO / "coordinator" / "battery_night.py").read_text()
        i = src.index("def sealed(")
        preceding = src[max(0, i - 120):i]
        assert "@property" not in preceding, (
            "sealed became a property — update the call site in coordinator.py"
        )


@pytest.mark.unit
class TestTheAttributesActuallyRender:
    """Third live-only failure in this wiring, and the worst of the three: the
    attributes branch used `d` without binding it, so extra_state_attributes
    raised UnboundLocalError on EVERY cycle. HA surfaced that as "Unexpected
    error updating listener" and aborted the whole coordinator listener update
    — so it did not merely blank one attribute, it took down the state write
    for the batch.

    A unit test that calls the property with a real coordinator would have
    caught it; a test that only checks the key exists would not."""

    def test_every_branch_binds_what_it_reads(self):
        import ast
        src = (REPO / "sensor.py").read_text()
        tree = ast.parse(src)
        fn = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "extra_state_attributes"), None)
        assert fn is not None, "premise: the property exists"

        # Walk each `elif` branch body and require that any use of `d` is
        # preceded by an assignment to `d` inside that same branch.
        for node in ast.walk(fn):
            if not isinstance(node, ast.If):
                continue
            body = node.body
            assigns_d = any(
                isinstance(st, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "d" for t in st.targets)
                for st in body
            )
            uses_d = any(
                isinstance(nm, ast.Name) and nm.id == "d" and isinstance(nm.ctx, ast.Load)
                for st in body for nm in ast.walk(st)
            )
            if uses_d:
                assert assigns_d, (
                    "a branch of extra_state_attributes reads `d` without "
                    "binding it — this raises UnboundLocalError every cycle and "
                    "aborts HA's whole listener update"
                )


@pytest.mark.unit
class TestOncePerDayMeansOnceSuccessfully:
    """Found on .175: the ledger held a settled actual for the day with
    `horizons=[]`. The recorder marked the day done BEFORE checking whether
    anything had been recorded, so a restart on a cycle where the forecast was
    not yet populated burned that day permanently — and the failure is
    invisible, because an empty horizon looks exactly like "no source publishes
    that far"."""

    def test_the_day_marker_is_set_only_after_a_successful_record(self):
        import ast
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        fn = next(n for n in ast.walk(ast.parse(src))
                  if isinstance(n, ast.FunctionDef)
                  and n.name == "_record_forecast_horizons")
        body = ast.get_source_segment(src, fn) or ""
        assert "if recorded:" in body, (
            "the day marker must be guarded by an actual record, or a restart "
            "at the wrong moment silently loses a day of evidence"
        )
        # …and the marker assignment must come after the loop, not before it.
        assert body.index("recorded += 1") < body.index("self._forecast_ledger_day = today_s"), (
            "the marker is set before the loop can record anything"
        )
