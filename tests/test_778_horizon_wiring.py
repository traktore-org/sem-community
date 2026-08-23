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
        src = (REPO / "coordinator" / "coordinator.py").read_text()
        i = src.index("def _record_forecast_horizons")
        body = src[i:i + 2200]
        assert "if value:" in body, (
            "a 0.0 / absent far-horizon forecast must be skipped, not recorded"
        )
