"""#743 (1.8 half) — a curtailed day must not TEACH the forecast pessimism.

The day ledger's ``day_kwh`` is already the raw forecast (#598), so the
packer sees the sky's own number. What poisons planning is the LEARNING:
under an export limit the measured production is clamped to consumption,
and ``forecast_tracker.update(forecast, daily_solar, …)`` reads that as
"the forecast over-promised" — the dampening factor sinks, and every
dampened consumer (the fleet's remaining-solar, the forecast night
target) under-plans exactly the hidden kilowatts the probe exists to
reveal.

A day the probe CONFIRMED curtailment on (state ``harvest`` — production
followed the probe, the signature was real) is a poisoned sample: the
tracker skips it. A failed probe (plain clouds) still teaches."""

from datetime import date

import pytest

from custom_components.solar_energy_management.coordinator.curtailment import (
    marks_day_curtailed,
)


@pytest.mark.unit
class TestThePoisonedSamplePredicate:
    def test_harvest_marks_the_day(self):
        assert marks_day_curtailed("harvest") is True

    def test_unconfirmed_states_do_not(self):
        for state in ("off", "idle", "suspect", "probing", "cooldown", None, ""):
            assert marks_day_curtailed(state) is False


@pytest.mark.unit
class TestTheTrackerSkipsCurtailedDays:
    def test_the_update_gate_is_wired(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator)
        assert "_curtailment_day" in src
        assert "marks_day_curtailed" in src
        # The gate sits ON the tracker update call.
        upd = src.index("self._forecast_tracker.update(")
        gate = src.rindex("_curtailment_day", 0, upd)
        assert upd - gate < 600, "the skip must guard the update call itself"
