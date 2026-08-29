"""#755 pillar 1 — the per-demand outcome recorder.

The plan already captures what each demand ASKED for and what the packer
PROMISED it. Nothing captures what it actually DID. Without that record the
learning layer has nothing to read, the morning report has nothing to compare,
and "fits" is a claim nobody ever checks.

Two properties this file pins hardest:

* **The night is one unit, not two days.** A night spans midnight, and SEM's
  per-device runtime accumulators are in the daily bucket that empties there
  (the #753 wart). The recorder therefore accumulates its own energy and lives
  in the durable store.

* **An estimate may never be recorded as a measurement.** Feeding a derived or
  guessed number into a model that later teaches decisions is the bug class we
  shipped three fixes for in one week (#743 curtailed days poisoning dampening,
  #744 an energy-tick estimate teaching the rated-power ratchet, #753 a warm-up
  sensor teaching a disconnect). The recorder keeps the flag; the learner is
  required to honour it.
"""

from datetime import datetime, timezone

import pytest

from custom_components.solar_energy_management.coordinator.demand_outcome import (
    DemandOutcomeRecorder,
)


UTC = timezone.utc

# These tests sample 30 minutes apart so the energy arithmetic is readable by
# eye (4 kW x 30 min = 2 kWh). Production samples every coordinator cycle, so
# the default gap guard sits far below that. Widen it here rather than sprinkle
# ten-second samples through every test — the guard has its own test, at its
# own default, further down.
COARSE_GAP_S = 3600


def _at(h, m=0, day=12):
    return datetime(2026, 8, day, h, m, tzinfo=UTC)


def _rec(**kw):
    kw.setdefault("max_gap_s", COARSE_GAP_S)
    return DemandOutcomeRecorder(**kw)


def _rec_for(rec, demand_id):
    """One open record, through the recorder's public door.

    The recorder used to expose a ``record_for`` accessor that only its own
    tests ever called — the #653 orphan shape — so it was deleted and the
    lookup lives here instead."""
    return next((r for r in rec.open_records()
                 if r.demand_id == demand_id), None)


def _open(rec, night="2026-08-12"):
    """Seed a night the way the stamp does: ask, promise, verdict."""
    rec.open_night(
        night,
        demands=[
            {"id": "ev:keba", "kind": "ev", "needed_kwh": 10.0,
             "planned_kwh": 10.0, "status": "fits"},
            {"id": "load:heizband", "kind": "load", "needed_kwh": 2.0,
             "planned_kwh": 1.6, "status": "partial"},
        ],
    )


class TestAccumulation:
    def test_energy_accumulates_from_power_samples(self):
        rec = _rec()
        _open(rec)
        # 4 kW for 30 minutes = 2 kWh
        rec.observe(_at(23, 0), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(23, 30), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        out = _rec_for(rec, "ev:keba")
        assert out.actual_kwh == pytest.approx(2.0, abs=0.01)

    def test_night_spans_midnight_without_losing_energy(self):
        """The daily bucket empties at midnight. The night does not."""
        rec = _rec()
        _open(rec)
        rec.observe(_at(23, 30), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(0, 0, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(0, 30, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        out = _rec_for(rec, "ev:keba")
        # 23:30->00:30 at 4 kW = 4 kWh, straight through the rollover
        assert out.actual_kwh == pytest.approx(4.0, abs=0.01)

    def test_energy_inside_and_outside_the_block_are_separated(self):
        """'It ran' and 'it ran WHEN WE SAID' are different questions."""
        rec = _rec()
        _open(rec)
        # Each interval is attributed to the state that held DURING it, i.e.
        # the flags of the sample that opened it.
        rec.observe(_at(23, 0), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(23, 30), "ev:keba", power_w=4000, measured=True,
                    in_block=True)   # 23:00-23:30 in-block  = 2 kWh
        rec.observe(_at(0, 0, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=False)  # 23:30-00:00 in-block  = 2 kWh
        rec.observe(_at(0, 30, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=False)  # 00:00-00:30 out       = 2 kWh
        out = _rec_for(rec, "ev:keba")
        assert out.actual_kwh == pytest.approx(6.0, abs=0.01)
        assert out.in_block_kwh == pytest.approx(4.0, abs=0.01)

    def test_a_long_gap_does_not_integrate_a_stale_sample(self):
        """A restart leaves a hole. Integrating across it invents energy."""
        rec = DemandOutcomeRecorder()   # the shipped default guard
        _open(rec)
        rec.observe(_at(23, 0), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        # ...HA was down for two hours...
        rec.observe(_at(1, 0, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        out = _rec_for(rec, "ev:keba")
        assert out.actual_kwh == pytest.approx(0.0, abs=0.01)
        assert out.gap_s >= 7200


class TestEstimateGuard:
    def test_an_estimated_sample_marks_the_record_unmeasured(self):
        rec = _rec()
        _open(rec)
        rec.observe(_at(23, 0), "load:heizband", power_w=1000, measured=True,
                    in_block=True)
        rec.observe(_at(23, 30), "load:heizband", power_w=1000, measured=False,
                    in_block=True)
        out = _rec_for(rec, "load:heizband")
        assert out.measured is False

    def test_unmeasured_records_are_excluded_from_training(self):
        rec = _rec()
        _open(rec)
        rec.observe(_at(23, 0), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(23, 30), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(23, 0), "load:heizband", power_w=1000, measured=False,
                    in_block=True)
        closed = rec.close_night()
        trainable = [r for r in closed if r.trainable]
        assert [r.demand_id for r in trainable] == ["ev:keba"]

    def test_a_record_with_no_samples_at_all_is_not_trainable(self):
        """Silence is not a measurement of zero."""
        rec = _rec()
        _open(rec)
        closed = rec.close_night()
        heiz = next(r for r in closed if r.demand_id == "load:heizband")
        assert heiz.actual_kwh == 0.0
        assert heiz.trainable is False


class TestRoundTrip:
    def test_the_record_carries_ask_promise_and_outcome(self):
        rec = _rec()
        _open(rec)
        rec.observe(_at(23, 0), "load:heizband", power_w=1000, measured=True,
                    in_block=True)
        rec.observe(_at(0, 0, day=13), "load:heizband", power_w=1000,
                    measured=True, in_block=True)
        out = _rec_for(rec, "load:heizband")
        assert out.asked_kwh == 2.0        # what the device wanted
        assert out.planned_kwh == 1.6      # what the packer promised
        assert out.status == "partial"     # the verdict it was given
        assert out.actual_kwh == pytest.approx(1.0, abs=0.01)  # what it got

    def test_survives_a_serialise_restore_cycle(self):
        """A reboot mid-night must not erase the night's record so far."""
        rec = _rec()
        _open(rec)
        rec.observe(_at(23, 0), "ev:keba", power_w=4000, measured=True,
                    in_block=True)
        rec.observe(_at(23, 30), "ev:keba", power_w=4000, measured=True,
                    in_block=True)

        revived = _rec()
        revived.restore_state(rec.get_state())

        # and it keeps accumulating from where it left off
        revived.observe(_at(0, 0, day=13), "ev:keba", power_w=4000,
                        measured=True, in_block=True)
        out = _rec_for(revived, "ev:keba")
        assert out.actual_kwh == pytest.approx(4.0, abs=0.01)

    def test_history_is_bounded(self):
        rec = _rec(max_nights=3)
        for d in range(1, 8):
            rec.open_night(
                f"2026-08-{d:02d}",
                demands=[{"id": "ev:keba", "kind": "ev", "needed_kwh": 5.0,
                          "planned_kwh": 5.0, "status": "fits"}],
            )
            rec.observe(datetime(2026, 8, d, 23, 0, tzinfo=UTC), "ev:keba",
                        power_w=4000, measured=True, in_block=True)
            rec.observe(datetime(2026, 8, d, 23, 30, tzinfo=UTC), "ev:keba",
                        power_w=4000, measured=True, in_block=True)
            rec.close_night()
        assert len(rec.history()) == 3
        assert rec.history()[-1].night == "2026-08-07"


class TestCoverageAttribution:
    def test_records_how_long_the_gate_covered_the_demand(self):
        """The morning question 'did the plan actually drive this?' needs the
        covered/uncovered split, not just the energy."""
        rec = _rec()
        _open(rec)
        rec.observe(_at(23, 0), "ev:keba", power_w=4000, measured=True,
                    in_block=True, covered=True)
        rec.observe(_at(23, 30), "ev:keba", power_w=4000, measured=True,
                    in_block=True, covered=True)
        rec.observe(_at(0, 0, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=False, covered=False)
        rec.observe(_at(0, 30, day=13), "ev:keba", power_w=4000, measured=True,
                    in_block=False, covered=False)
        # 23:00-23:30 and 23:30-00:00 covered; 00:00-00:30 not
        assert _rec_for(rec, "ev:keba").covered_s == pytest.approx(3600, abs=1)
        assert _rec_for(rec, "ev:keba").uncovered_s == pytest.approx(1800, abs=1)
