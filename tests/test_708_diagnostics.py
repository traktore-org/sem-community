"""#708 — the taper/stability internals reach the diagnostics download,
and the full-charge announcement reports what was OBSERVED.

Azlinon's promised build debt: the diagnostics carried none of the
give-up streak, the declining-phase latch, or the SOC anchor and its
age — every report of this shape needed someone reading the source to
guess what should have happened. And "SOC anchored at 100%" asserts
something SEM cannot know; the observation is: the charge completed."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)


def _full_charge(det):
    """Drive the detector to its full-charge detection."""
    det._current_session_energy_kwh = 5.0
    det._session_peak_w = 7000.0
    det._declining_phase = True
    det._analyze_full(  # helper added below if needed — else direct fields
    ) if hasattr(det, "_analyze_full") else None
    return det


@pytest.mark.unit
class TestTheDiagnosticsView:
    def test_the_view_carries_the_promised_fields(self):
        det = EVTaperDetector({})
        det._declining_phase = True
        det._session_peak_w = 7100.0
        det._soc_anchored = True
        det._soc_anchor_value = 80.0
        det._soc_anchor_session_kwh = 3.2
        det._last_full_timestamp = "2026-08-12T10:00:00+00:00"
        v = det.diagnostics_view()
        assert v["declining_phase"] is True
        assert v["session_peak_w"] == 7100.0
        assert v["soc_anchored"] is True
        assert v["soc_anchor_value"] == 80.0
        assert v["soc_anchor_session_kwh"] == 3.2
        assert v["last_full_at"] == "2026-08-12T10:00:00+00:00"

    def test_a_fresh_detector_reads_empty_not_crashing(self):
        v = EVTaperDetector({}).diagnostics_view()
        assert v["declining_phase"] is False
        assert v["soc_anchored"] is False


@pytest.mark.unit
class TestTheAnnouncementReportsTheObservation:
    def test_the_log_says_charge_complete_not_anchored(self):
        import inspect
        src = inspect.getsource(EVTaperDetector)
        assert "SOC anchored at 100" not in src, (
            "the announcement asserts something SEM cannot know — report "
            "the observation: the charge completed")
        assert "charge complete" in src.lower()


@pytest.mark.unit
class TestDiagnosticsWiring:
    def test_the_download_carries_the_ev_stability_block(self):
        import inspect
        from custom_components.solar_energy_management import diagnostics
        src = inspect.getsource(diagnostics)
        assert "ev_stability" in src
        assert "diagnostics_view" in src
        assert "snapshot_timers" in src
