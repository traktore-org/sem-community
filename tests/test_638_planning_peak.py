"""#638 one-gate — ONE planning peak number for ledger and EV alike.

Finding #6 (TEST night 2026-07-30) taught the ledger to plan at the level
execution actually holds: the shed threshold MINUS hysteresis, because an
allocation booked at the cap is exactly the one the LoadManager kills. The
EV's peak-managed rate never learned that — it sized night amps against the
raw cap (ev_control.py:199), so plan and EV silently disagreed by the
hysteresis band.

`_planning_peak_w()` is the one accessor both sides read. Semantics carried
over from the ledger inline block (coordinator.py:6692-6711):

* unlimited (`math.inf`) passes through — hysteresis on infinity is nothing;
* 0 stays 0 — it is the packer's "no limit configured" sentinel;
* a cap smaller than the hysteresis clamps at 1 W, never 0 — collapsing to
  the sentinel would flip a TIGHT house into an unlimited one.
"""

from __future__ import annotations

import inspect
import math
from unittest.mock import Mock

import pytest

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)


def _host(peak_w, config=None):
    obj = Mock()
    obj._get_peak_limit_w = Mock(return_value=peak_w)
    obj.config = config if config is not None else {}
    return obj


@pytest.mark.unit
class TestPlanningPeak:
    def test_hysteresis_is_subtracted(self):
        host = _host(5000.0, {"peak_hysteresis": 0.2})
        assert EVControlMixin._planning_peak_w(host) == pytest.approx(4800.0)

    def test_default_hysteresis_applies_when_unset(self):
        # DEFAULT_PEAK_HYSTERESIS is 0.2 kW (consts/core.py) — the same
        # default the ledger block used.
        host = _host(5000.0, {})
        assert EVControlMixin._planning_peak_w(host) == pytest.approx(4800.0)

    def test_unlimited_passes_through(self):
        host = _host(math.inf, {})
        assert EVControlMixin._planning_peak_w(host) == math.inf

    def test_zero_sentinel_is_preserved(self):
        host = _host(0.0, {})
        assert EVControlMixin._planning_peak_w(host) == 0.0

    def test_tiny_cap_clamps_at_one_watt_never_zero(self):
        host = _host(100.0, {"peak_hysteresis": 0.5})
        assert EVControlMixin._planning_peak_w(host) == 1.0


@pytest.mark.unit
class TestBothCallersReadTheSameNumber:
    """Structural parity — the two planning surfaces read the ONE accessor."""

    def test_the_ledger_reads_planning_peak(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._shadow_energy_plan)
        assert "_planning_peak_w(" in src, (
            "the night-ledger build must size headroom from _planning_peak_w")
        assert "peak_hysteresis" not in src, (
            "the inline hysteresis subtraction must live ONLY in "
            "_planning_peak_w — a second copy is how the numbers drift apart")

    def test_the_ev_peak_managed_rate_reads_planning_peak(self):
        src = inspect.getsource(EVControlMixin._compute_night_plan)
        assert "_planning_peak_w(" in src, (
            "the EV night rate must size against the same hysteresis-adjusted "
            "peak the ledger plans with")
