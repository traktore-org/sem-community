"""#778 — five nights must mean five NIGHTS.

Found on .175 while answering "can we simulate five nights?": the rig holds two
sealed records both dated 2026-08-21. The seal path can emit more than one
record for a date (a restart mid-night seals what it has, and the night seals
again later), and both consumers count RECORDS.

Two ways that hurts, and the second is the serious one:

1. the "N of 5 nights" a user watches over-counts, so the budget wakes earlier
   than the evidence justifies;
2. a partial night's drain is SMALLER than the whole night's. The need envelope
   is a high percentile precisely because being short is not symmetric with
   being generous — one costs a little export revenue, the other strands the
   house at its floor before dawn. Padding the sample with partial nights drags
   that percentile DOWN, in the unsafe direction.

So both readers collapse a date to its most complete record: a trainable one
beats an untrainable one, and among equals the larger drain wins — that is the
one that saw more of the night.
"""

import pytest

from custom_components.solar_energy_management.coordinator.measured_capacity import (
    expected_overnight_need,
    measured_capacity,
)


def _night(date, drain, *, soc_start=90.0, soc_morning=60.0, trainable=True):
    return {
        "date": date, "drain_kwh": drain, "soc_start": soc_start,
        "soc_morning": soc_morning, "trainable": trainable,
    }


class TestTheNeedEnvelope:
    def test_a_duplicated_date_counts_once(self):
        """Four dates, one of them recorded twice — five records, four nights.
        The gate is five nights, so this must still be None."""
        records = [
            _night("2026-08-18", 6.0), _night("2026-08-19", 7.0),
            _night("2026-08-20", 8.0),
            _night("2026-08-21", 9.0), _night("2026-08-21", 2.0),
        ]
        assert expected_overnight_need(records) is None

    def test_five_distinct_nights_still_answer(self):
        records = [_night(f"2026-08-1{i}", 6.0 + i) for i in range(5)]
        assert expected_overnight_need(records) is not None

    def test_the_partial_record_does_not_drag_the_percentile_down(self):
        """The unsafe direction. The 1.0 kWh record is the same night as the
        9.0 one, seen through a restart; keeping both would understate what
        the house needs."""
        full = [_night(f"2026-08-2{i}", 9.0) for i in range(5)]
        withPartial = full + [_night("2026-08-20", 1.0)]
        assert expected_overnight_need(withPartial) == expected_overnight_need(full)

    def test_a_trainable_record_beats_an_untrainable_one_for_the_same_night(self):
        """The untrainable 12.0 kWh fragment must not be what 2026-08-20
        contributes — the trainable 9.0 is. Asserted against the same set with
        the fragment absent, so the test states the property rather than a
        percentile arithmetic I would have to recompute whenever the sample
        shape changes."""
        base = [_night(f"2026-08-1{i}", 6.0) for i in range(4)]
        clean = base + [_night("2026-08-20", 9.0, trainable=True)]
        withFragment = base + [
            _night("2026-08-20", 12.0, trainable=False),
            _night("2026-08-20", 9.0, trainable=True),
        ]
        assert expected_overnight_need(withFragment) == expected_overnight_need(clean)
        assert expected_overnight_need(clean) is not None

    def test_records_without_a_date_are_not_collapsed_together(self):
        """A missing date is unknown, not 'the same night as every other
        undated record' — collapsing those would silently discard evidence."""
        records = [_night(None, 6.0 + i) for i in range(5)]
        assert expected_overnight_need(records) is not None


class TestMeasuredCapacity:
    def test_a_duplicated_date_counts_once(self):
        records = [
            _night("2026-08-18", 6.0), _night("2026-08-19", 6.0),
            _night("2026-08-20", 6.0), _night("2026-08-21", 6.0),
            _night("2026-08-21", 6.0),
        ]
        assert measured_capacity(records) is None

    def test_five_distinct_nights_measure(self):
        records = [_night(f"2026-08-1{i}", 6.0) for i in range(5)]
        assert measured_capacity(records) is not None


class TestTheRigsOwnRecords:
    """The exact two records read off .175 on 23.08 — one untrainable with a
    994 s gap, one trainable, both dated 2026-08-21."""

    RIG = [
        {"date": "2026-08-21", "drain_kwh": 0.016, "soc_start": 65.0,
         "soc_morning": 65.0, "trainable": False, "gap_s": 994.0},
        {"date": "2026-08-21", "drain_kwh": 8.789, "soc_start": 65.0,
         "soc_morning": 65.0, "trainable": True, "gap_s": 297.3},
    ]

    def test_the_rig_holds_one_night_not_two(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            distinct_nights,
        )
        assert len(distinct_nights(self.RIG)) == 1


class TestTheProgressCountIsTheGateCount:
    """"2 of 5 nights" must mean the five the gate is actually waiting for.

    Live on .175: the card published ``nights_sealed = 3`` — the raw length of
    the sealed list — while the need envelope, which dedupes by date and drops
    untrainable records, could see exactly **one** usable night. A user reading
    that card would wait two days for something that needed four.

    This is the same defect as counting records instead of nights, one layer
    up: fixed in the consumer, left wrong in the display. The rule the ledger
    already states for forecast days applies here too — the number a user
    watches and the evidence a decision uses may never be counted differently,
    which means ONE function counts and everyone else asks it.
    """

    def _rec(self, date, drain, trainable=True):
        return {"date": date, "drain_kwh": drain, "soc_start": 90.0,
                "soc_morning": 60.0, "trainable": trainable}

    def test_usable_nights_ignores_duplicates(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            usable_nights,
        )
        recs = [self._rec("2026-08-21", 5.0), self._rec("2026-08-21", 0.004),
                self._rec("2026-08-22", 6.0)]
        assert usable_nights(recs) == 2

    def test_usable_nights_ignores_untrainable_records(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            usable_nights,
        )
        recs = [self._rec("2026-08-20", 5.0, trainable=False),
                self._rec("2026-08-21", 6.0)]
        assert usable_nights(recs) == 1

    def test_the_rigs_own_records_count_as_one(self):
        """.175 on 23.08: three sealed records, one trainable, all one date."""
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            usable_nights,
        )
        rig = [
            {"date": "2026-08-21", "drain_kwh": 0.016, "trainable": False},
            {"date": "2026-08-21", "drain_kwh": 8.789, "trainable": True},
            {"date": "2026-08-21", "drain_kwh": 0.004, "trainable": True},
        ]
        assert usable_nights(rig) == 1

    def test_the_count_reaching_the_gate_unlocks_the_envelope(self):
        """The property that makes the number honest: when the published count
        hits the required number, the envelope must actually answer."""
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            MIN_NEED_SAMPLES, expected_overnight_need, usable_nights,
        )
        recs = [self._rec(f"2026-08-{d:02d}", 5.0 + d) for d in range(1, 6)]
        assert usable_nights(recs) == MIN_NEED_SAMPLES
        assert expected_overnight_need(recs) is not None

    def test_one_short_of_the_gate_still_answers_nothing(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            MIN_NEED_SAMPLES, expected_overnight_need, usable_nights,
        )
        recs = [self._rec(f"2026-08-{d:02d}", 5.0 + d)
                for d in range(1, MIN_NEED_SAMPLES)]
        assert usable_nights(recs) == MIN_NEED_SAMPLES - 1
        assert expected_overnight_need(recs) is None

    def test_the_coordinator_publishes_the_usable_count(self):
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        assert '"nights_sealed": len(sealed)' not in src, (
            "the card still publishes the raw record count, which over-states "
            "progress toward a gate that counts distinct trainable nights")
        assert "usable_nights(sealed)" in src
