"""#628 — a silently skipped reconciliation must say so, somewhere.

The all-or-nothing rule is right: a partial counter read must not adopt.
But the SKIP was invisible — no log, no diagnostic — so a category whose
counter never resolves (unavailable entity, wrong ID, a whole-day
integration outage) runs as a pure stopwatch indefinitely, and the first
symptom is a numbers-don't-match report weeks later that costs a
19-comment thread to localize (jappish84's #628).

Two surfaces, both cheap:
- one transition-gated log line per category when it flips
  backed ↔ unbacked (the #762 alternation pattern), and
- per-category tallies in the diagnostics download: how many cycles
  today were counter-backed vs skipped-partial. One look answers "was
  export ever reconciled on this install?".
"""
from __future__ import annotations

import logging
from datetime import date
from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.utils.log_gate import (
    reset_log_gate,
)


@pytest.fixture(autouse=True)
def _clean_gate():
    reset_log_gate()
    yield
    reset_log_gate()


def _state(value: str) -> Mock:
    st = Mock()
    st.state = value
    st.attributes = {"unit_of_measurement": "kWh"}
    return st


def _calc_with_counter(counter_value) -> EnergyCalculator:
    calc = EnergyCalculator({"prefer_hardware_energy": True}, MagicMock())
    hass = MagicMock()
    hass.states.get = Mock(
        return_value=_state(counter_value) if counter_value is not None else None
    )
    calc.configure_meter_counters(
        hass, {"grid_export": ["sensor.p1_export"]}, True,
    )
    return calc


class TestBackingTallies:

    def test_a_complete_read_tallies_backed(self) -> None:
        calc = _calc_with_counter("5.0")
        calc._reconcile_metered_energy("grid_export", date(2026, 8, 13), "2026-08", "2026")
        t = calc.counter_backing_today()
        assert t["grid_export"]["backed"] == 1
        assert t["grid_export"]["skipped"] == 0

    def test_a_partial_read_tallies_skipped(self) -> None:
        calc = _calc_with_counter(None)   # counter never resolves
        calc._reconcile_metered_energy("grid_export", date(2026, 8, 13), "2026-08", "2026")
        calc._reconcile_metered_energy("grid_export", date(2026, 8, 13), "2026-08", "2026")
        t = calc.counter_backing_today()
        assert t["grid_export"]["backed"] == 0
        assert t["grid_export"]["skipped"] == 2

    def test_an_unconfigured_category_is_absent_not_zero(self) -> None:
        """No counters configured = the integrator is the design, not a
        failure — it must not read as an endless skip."""
        calc = _calc_with_counter("5.0")
        calc._reconcile_metered_energy("battery_charge", date(2026, 8, 13), "2026-08", "2026")
        assert "battery_charge" not in calc.counter_backing_today()


class TestBackingTransitionsLog:

    def test_the_flip_to_unbacked_logs_once(self, caplog) -> None:
        calc = _calc_with_counter("5.0")
        d = date(2026, 8, 13)
        lg = "custom_components.solar_energy_management.coordinator.energy_calculator"
        with caplog.at_level(logging.INFO, logger=lg):
            calc._reconcile_metered_energy("grid_export", d, "2026-08", "2026")
            calc._hass.states.get = Mock(return_value=None)   # counter vanishes
            for _ in range(5):
                calc._reconcile_metered_energy("grid_export", d, "2026-08", "2026")
        assert caplog.text.count("no longer counter-backed") == 1

    def test_the_recovery_logs_once_and_rearms(self, caplog) -> None:
        calc = _calc_with_counter(None)
        d = date(2026, 8, 13)
        lg = "custom_components.solar_energy_management.coordinator.energy_calculator"
        with caplog.at_level(logging.INFO, logger=lg):
            calc._reconcile_metered_energy("grid_export", d, "2026-08", "2026")
            calc._hass.states.get = Mock(return_value=_state("5.0"))
            for _ in range(3):
                calc._reconcile_metered_energy("grid_export", d, "2026-08", "2026")
        assert caplog.text.count("counter-backed again") == 1
