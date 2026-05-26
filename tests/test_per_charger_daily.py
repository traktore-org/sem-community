"""Per-charger daily EV energy consistency.

The per-charger accumulator resets on restart while the global daily_ev persists; for a
single charger they're the same quantity, so the report mirrors the global. Multiple
chargers report their own (now-persisted) accumulators.
"""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator


@pytest.mark.unit
class TestPerChargerDailyReport:
    def _coord(self, chargers, accum):
        c = MagicMock()
        c.config = {"ev_chargers": chargers}
        c._daily_ev_per_charger = accum
        return c

    def test_single_charger_reports_global(self):
        # accumulator reset on restart (0.37), global persisted (8.93) -> report global
        c = self._coord([{"id": "ev_charger"}], {"ev_charger": 0.37})
        out = SEMCoordinator._per_charger_daily_report(c, MagicMock(daily_ev=8.93))
        assert out["ev_charger"] == 8.93

    def test_single_charger_no_accum_yet(self):
        c = self._coord([{"id": "ev_charger"}], {})
        out = SEMCoordinator._per_charger_daily_report(c, MagicMock(daily_ev=5.0))
        assert out["ev_charger"] == 5.0

    def test_multi_charger_keeps_per_charger_accumulators(self):
        c = self._coord([{"id": "a"}, {"id": "b"}], {"a": 3.0, "b": 2.0})
        out = SEMCoordinator._per_charger_daily_report(c, MagicMock(daily_ev=5.0))
        assert out == {"a": 3.0, "b": 2.0}

    def test_no_chargers_safe(self):
        c = self._coord([], {})
        out = SEMCoordinator._per_charger_daily_report(c, MagicMock(daily_ev=5.0))
        assert out == {}
