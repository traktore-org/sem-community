"""The capacity verdict must be fed the RECORDS, not the bound method.

Spotted from the dashboard on 30.08: the battery card read
"MEASURED PACK SIZE · Learning · 7 / 5 Nights" — seven qualifying nights
against a requirement of five, still learning. Seven is not less than five;
the two numbers came from different places.

`capacity_progress()` and `measured_capacity()` both filter the same records
through `_qualifying_ratios`, so with 7 qualifying nights the verdict cannot
be None... unless the two are handed different inputs. They were:

    cap    = measured_capacity(tracker.sealed)      # the BOUND METHOD
    sealed = tracker.sealed() if callable(...)      # the records
    ...    = capacity_progress(sealed)

Iterating a bound method raises TypeError, the surrounding `except Exception`
turned it into `cap = None`, and the pack size stayed "Learning" forever on
every install. The file already carries a comment describing this exact
mistake being fixed once before, 25 lines below where it survived.

This pins the contract at the seam that matters: whatever is handed to
`measured_capacity` must be iterable records, and progress and verdict must
agree — if progress says the samples are there, a verdict must exist.
"""
from __future__ import annotations

import inspect

from custom_components.solar_energy_management.coordinator.measured_capacity import (
    MIN_SAMPLES,
    capacity_progress,
    measured_capacity,
)


def _night(date, morning_soc, start_soc, drain_kwh):
    """A sealed-night record shaped as #800's recorder emits it."""
    return {"date": date, "soc_morning": morning_soc, "soc_start": start_soc,
            "house_kwh": drain_kwh, "drain_kwh": drain_kwh, "trainable": True}


def _seven_good_nights():
    # 30 % SOC span, 4.5 kWh drained → 0.15 kWh per SOC-point, well clear
    # of the span floor so every night qualifies.
    return [_night(f"2026-08-{10+i:02d}", 45.0, 75.0, 4.5) for i in range(7)]


class TestProgressAndVerdictAgree:
    def test_seven_qualifying_nights_produce_a_verdict(self):
        recs = _seven_good_nights()
        assert capacity_progress(recs) == 7
        cap = measured_capacity(recs)
        assert cap is not None, (
            "progress counted 7 qualifying nights; the verdict must exist "
            "— this is the '7 / 5 Nights, still Learning' the card showed"
        )
        assert cap.samples == 7
        assert cap.usable_kwh > 0

    def test_progress_never_exceeds_the_requirement_without_a_verdict(self):
        """The invariant the UI relies on: once progress reaches the
        requirement, 'Learning' must end."""
        recs = _seven_good_nights()
        if capacity_progress(recs) >= MIN_SAMPLES:
            assert measured_capacity(recs) is not None

    def test_a_bound_method_is_not_records(self):
        """What actually happened: the caller passed `tracker.sealed`
        (the method) instead of `tracker.sealed()` (the records)."""
        class _Tracker:
            def sealed(self):
                return _seven_good_nights()

        import pytest
        t = _Tracker()
        # It does not quietly return None — it RAISES, which is exactly why
        # the coordinator's blanket `except Exception: cap = None` buried it
        # and the card showed "Learning" instead of an error.
        with pytest.raises(TypeError):
            measured_capacity(t.sealed)
        assert measured_capacity(t.sealed()) is not None


class TestTheCoordinatorCallsIt:
    def test_the_coordinator_never_passes_the_uncalled_method(self):
        from custom_components.solar_energy_management.coordinator import (
            coordinator as cm,
        )
        src = inspect.getsource(cm)
        assert "measured_capacity(tracker.sealed)" not in src, (
            "measured_capacity was handed the BOUND METHOD `tracker.sealed`; "
            "`sealed` is a method on BatteryNightTracker and must be called. "
            "The TypeError was swallowed by the surrounding except, so the "
            "pack size read 'Learning' forever."
        )
