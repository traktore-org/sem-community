"""#815 — recover the battery's night history from statistics already on disk.

#778's need envelope wants five trainable nights before it will offer a
figure. Live recording produces one per day, so a fresh install waits a
working week — and on .175 it waited longer than that, because #837's
day-phase pollution was refusing nights outright.

The forecast half of #778 does not have this problem: ``ledger_backfill``
recovers it from long-term statistics in one pass (139 days on the dev rig).
The night half had no equivalent, which is the whole reason it was the
bottleneck.

**Why a backfilled night is not merely faster but SOUNDER.** Live recording
integrates battery POWER over time, so every dropped sample destroys that
energy permanently — the failure mode behind #837. A cumulative energy counter
is a different kind of measurement: the inverter keeps counting while nobody is
looking, so a night's discharge is just ``counter(dawn) - counter(dusk)`` and
missing hours in between change nothing. The gap problem cannot exist here.

**What it cannot know.** The counter reports the pack's TOTAL discharge, while
``drain_kwh`` means the part that went to the house — total also carries EV
assist and battery export. Statistics cannot separate them, so a backfilled
drain is an UPPER BOUND. That is the safe direction and deliberately so: a
larger drain means a larger reserve and less spending, and of the two ways to
be wrong that is the one that cannot strand anyone (the same reasoning
``_bridge_hole`` already uses).
"""
from __future__ import annotations

from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.night_backfill import (
    nights_from_statistics,
)

NIGHT_START = 21
NIGHT_END = 6


def _series(start_day: str, days: int, *, per_night: float, per_day: float = 3.0):
    """A monotonic discharge counter: `per_night` kWh each night, `per_day` by day."""
    d0 = datetime.fromisoformat(start_day)
    out, total = {}, 100.0
    for i in range(days * 24):
        t = d0 + timedelta(hours=i)
        out[t] = round(total, 3)
        total += (per_night / 9.0) if (t.hour >= NIGHT_START or t.hour < NIGHT_END) \
            else (per_day / 15.0)
    return out


def _run(disch, soc=None, **kw):
    return nights_from_statistics(
        disch, soc,
        night_start_hour=NIGHT_START, night_end_hour=NIGHT_END,
        reserve_soc=kw.pop("reserve_soc", 20.0),
        capacity_kwh=kw.pop("capacity_kwh", 15.0),
        known_dates=kw.pop("known_dates", set()),
        **kw,
    )


class TestItRecoversNights:
    def test_it_finds_one_record_per_night(self):
        nights = _run(_series("2026-08-01", 5, per_night=6.0))
        assert len(nights) >= 3, f"only recovered {len(nights)} nights"
        assert len({n["date"] for n in nights}) == len(nights), "duplicate dates"

    def test_the_drain_is_the_counter_delta(self):
        nights = _run(_series("2026-08-01", 4, per_night=6.0))
        for n in nights:
            assert abs(n["drain_kwh"] - 6.0) < 0.2, n

    def test_missing_hours_in_the_middle_do_not_matter(self):
        """The point of using a counter: the inverter keeps counting while
        nobody is looking, so a hole between the endpoints costs nothing."""
        s = _series("2026-08-01", 4, per_night=6.0)
        holed = {t: v for t, v in s.items() if not (t.day == 2 and 1 <= t.hour <= 4)}
        nights = _run(holed)
        night2 = [n for n in nights if n["date"] == "2026-08-01"]
        assert night2 and abs(night2[0]["drain_kwh"] - 6.0) < 0.2, night2

    def test_records_are_marked_as_backfilled(self):
        for n in _run(_series("2026-08-01", 4, per_night=6.0)):
            assert n["source"] == "backfill", "provenance must be on the record"

    def test_they_are_trainable_so_the_envelope_can_use_them(self):
        assert all(n["trainable"] for n in _run(_series("2026-08-01", 4, per_night=6.0)))


class TestItRefusesWhatItCannotKnow:
    def test_a_counter_reset_invalidates_its_night(self):
        """A replaced inverter or a counter rollover makes the delta a
        fiction. Refuse rather than book a negative or absurd night."""
        s = _series("2026-08-01", 4, per_night=6.0)
        for t in list(s):
            if t.day >= 2:
                s[t] = s[t] - 100.0          # counter restarts partway
        dates = {n["date"] for n in _run(s) if n["trainable"]}
        assert "2026-08-01" not in dates, "a night spanning the reset was booked"

    def test_a_missing_endpoint_refuses_the_night(self):
        """Beyond ENDPOINT_TOLERANCE_H there is nothing to measure between.

        Note the tolerance is real and wanted: a single missing 06:00 row is
        still a describable night via 05:00 or 07:00, and an earlier draft of
        this test asserted otherwise and failed against correct code. Only a
        hole wider than the tolerance leaves the night unmeasurable."""
        s = _series("2026-08-01", 4, per_night=6.0)
        s = {t: v for t, v in s.items()
             if not (t.day == 2 and 3 <= t.hour <= 9)}
        assert "2026-08-01" not in {n["date"] for n in _run(s) if n["trainable"]}

    def test_an_impossible_drain_is_refused(self):
        """More than the pack holds did not come out of the pack."""
        s = _series("2026-08-01", 3, per_night=90.0)
        assert not [n for n in _run(s, capacity_kwh=15.0) if n["trainable"]]


class TestItNeverOverwritesLiveEvidence:
    def test_a_night_already_recorded_is_left_alone(self):
        nights = _run(_series("2026-08-01", 5, per_night=6.0),
                      known_dates={"2026-08-01", "2026-08-02"})
        got = {n["date"] for n in nights}
        assert "2026-08-01" not in got and "2026-08-02" not in got, (
            "backfill overwrote a night SEM measured live — live always wins"
        )


class TestReserveCensoring:
    def test_a_night_that_hit_reserve_is_flagged(self):
        """The censoring flag #778 relies on: such a night observed LESS than
        the house wanted, so its drain is a floor, not a measurement."""
        s = _series("2026-08-01", 3, per_night=6.0)
        soc = {t: (18.0 if (t.day == 2 and t.hour == 3) else 80.0) for t in s}
        flagged = [n for n in _run(s, soc, reserve_soc=20.0)
                   if n["date"] == "2026-08-01"]
        assert flagged and flagged[0]["reserve_hit"] is True

    def test_a_night_that_stayed_above_reserve_is_not(self):
        s = _series("2026-08-01", 3, per_night=6.0)
        soc = {t: 80.0 for t in s}
        clear = [n for n in _run(s, soc, reserve_soc=20.0)
                 if n["date"] == "2026-08-01"]
        assert clear and clear[0]["reserve_hit"] is False


class TestItFeedsTheEnvelope:
    def test_backfilled_nights_satisfy_expected_overnight_need(self):
        """End to end: the whole point is that #778 can answer immediately
        instead of waiting five days."""
        from custom_components.solar_energy_management.coordinator.measured_capacity import (  # noqa: E501
            expected_overnight_need,
        )
        varied = _series("2026-08-01", 10, per_night=6.0)
        nights = _run(varied)
        assert len(nights) >= 5
        need = expected_overnight_need(nights)
        assert need is not None, "the envelope still says 'not enough evidence'"
        assert 5.0 < need < 7.5, need


class TestTheTrackerAcceptsTheHistory:
    def test_replace_sealed_keeps_the_window_and_spares_the_night_in_flight(self):
        from custom_components.solar_energy_management.coordinator.battery_night import (  # noqa: E501
            BatteryNightTracker, Sample,
        )
        tr = BatteryNightTracker(reserve_soc=20.0, capacity_kwh=15.0, max_nights=5)
        tr.start("2026-08-20", outdoor_temp_c=18.0)
        tr.tick(1_000_010.0, True, Sample(battery_to_home_w=500.0, soc=90.0))

        tr.replace_sealed([{"date": f"2026-07-{d:02d}", "drain_kwh": 5.0,
                            "trainable": True, "source": "backfill"}
                           for d in range(1, 11)])

        got = tr.sealed()
        assert len(got) == 5, f"window not applied: {len(got)}"
        assert got[-1]["date"] == "2026-07-10", "kept the oldest, not the newest"
        assert tr.phase == "night", "the night in flight was disturbed"
