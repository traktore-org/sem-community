"""#837 — a night's counters must describe the night, not the day after it.

Found on .175 while checking how #778 was progressing: the need envelope sat
at 1 usable night of the 5 it requires, and was not going to get there.

The nights were refused on ``gap_s`` — 761 s and 2640 s against a 300 s
budget. The obvious suspects were all wrong:

* not restarts — the rig had 18 days of uptime and no HA restart;
* not overnight sensor dropouts — the battery power sensor was down 2-4 times
  a night, 87-360 s in total, longest 162 s, so every outage fits inside the
  zero-order-hold budget and none can become ``gap_s``;
* not a stalled coordinator — 10,563 state rows in 3 days with no interval
  over 300 s.

The cause is in ``tick()``. ``gap_s`` and ``held_s`` are accumulated BEFORE
the phase branch, so they keep counting all day; and a record is not sealed at
the morning flip but when the NEXT night opens. Every sealed night therefore
carried its own gaps plus the whole following day's.

The arithmetic matches exactly: that sensor is unavailable ~2,750 s per day,
nearly all of it in daylight, and ``held_s`` on the sealed records reads
2,590 / 2,480 / 2,950 — the DAILY total, not the night's.

So daytime sensor flakiness refused nights it never touched, on hardware where
daytime flakiness is normal. Left alone, #778 would sit at "learning" forever
on exactly the installs it was built for, and look like nothing was wrong.

``soc_morning`` had the same disease: it is overwritten on every night-phase
tick, but the day phase kept running past dawn, so it ended up holding a
daytime value. On the three oldest records it reads identical to ``soc_start``
(65.0) beside drains of 8.8 and 12.1 kWh — physically impossible, and the
reason the SOC cross-check could not be used.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.battery_night import (
    BatteryNightTracker,
    Sample,
)

CAP = 15.0


def _tracker():
    return BatteryNightTracker(reserve_soc=20.0, capacity_kwh=CAP)


def _run(tr, t0, seconds, *, in_night, measured=True, soc=None,
         to_home_w=0.0, home_w=0.0, step=10.0):
    """Tick a stretch of wall time, returning the new clock."""
    t = t0
    for _ in range(int(seconds // step)):
        t += step
        tr.tick(t, in_night, Sample(
            battery_to_home_w=to_home_w,
            home_w=home_w,
            soc=soc,
            soc_available=soc is not None,
            measured=measured,
        ))
    return t


def _clean_night(tr, t0):
    """A well-measured 10-hour night: 97% -> 57%, ~6 kWh to the house."""
    t = t0
    tr.start("2026-08-23", outdoor_temp_c=18.0)
    t = _run(tr, t, 5 * 3600, in_night=True, soc=97.0, to_home_w=600.0)
    t = _run(tr, t, 5 * 3600, in_night=True, soc=57.0, to_home_w=600.0)
    return t


class TestTheDayAfterCannotRefuseTheNight:
    def test_a_clean_night_survives_a_flaky_day(self):
        """The reported case: night fine, following day drops the sensor for
        the better part of an hour, night refused."""
        tr = _tracker()
        t = _clean_night(tr, 1_000_000.0)
        t = _run(tr, t, 600, in_night=False, soc=57.0)          # dawn
        # the day the .175 hardware actually has: ~45 min unmeasured
        t = _run(tr, t, 2700, in_night=False, measured=False, soc=60.0)
        t = _run(tr, t, 600, in_night=False, soc=70.0)
        tr.tick(t + 10, True, Sample(soc=70.0))                 # next night seals it

        rec = tr.sealed()[-1]
        assert rec["gap_s"] <= 300.0, (
            f"the night sealed with gap_s={rec['gap_s']} — it absorbed the "
            "following day's sensor dropouts (#837)"
        )
        assert rec["trainable"] is True, (
            "a well-measured night was refused because the day after it was "
            "flaky — the gate is a claim about the NIGHT"
        )

    def test_the_night_still_owns_its_own_gaps(self):
        """The fix must not make the gate toothless: a night with a real hole
        in IT is still refused."""
        tr = _tracker()
        t = 1_000_000.0
        tr.start("2026-08-23", outdoor_temp_c=18.0)
        t = _run(tr, t, 3600, in_night=True, soc=97.0, to_home_w=600.0)
        # a genuine 40-minute hole inside the night, no SOC to bridge with
        t = _run(tr, t, 2400, in_night=True, measured=False, soc=None)
        t = _run(tr, t, 3600, in_night=True, soc=70.0, to_home_w=600.0)
        t = _run(tr, t, 600, in_night=False, soc=70.0)
        tr.tick(t + 10, True, Sample(soc=70.0))

        rec = tr.sealed()[-1]
        assert rec["gap_s"] > 300.0
        assert rec["trainable"] is False


class TestSocMorningIsTakenAtDawn:
    def test_soc_morning_is_not_overwritten_by_the_day(self):
        """The three oldest .175 records read soc_start == soc_morning == 65.0
        beside 8.8 and 12.1 kWh of drain, because the day kept writing over
        the morning value. That is what made the SOC cross-check unusable."""
        tr = _tracker()
        t = _clean_night(tr, 1_000_000.0)
        t = _run(tr, t, 6 * 3600, in_night=False, soc=99.0)     # sunny day, pack refills
        tr.tick(t + 10, True, Sample(soc=99.0))

        rec = tr.sealed()[-1]
        assert rec["soc_morning"] == 57.0, (
            f"soc_morning={rec['soc_morning']} — the day overwrote dawn's "
            "reading, so the night's SOC delta is unrecoverable (#837)"
        )
        assert rec["soc_start"] == 97.0

    def test_the_soc_delta_then_corroborates_the_integral(self):
        """Why it matters: with honest endpoints the pack's own SOC is an
        independent check on the integrated drain — a state survives a
        dropout, a flow does not."""
        tr = _tracker()
        t = _clean_night(tr, 1_000_000.0)
        t = _run(tr, t, 3600, in_night=False, soc=99.0)
        tr.tick(t + 10, True, Sample(soc=99.0))

        rec = tr.sealed()[-1]
        soc_kwh = (rec["soc_start"] - rec["soc_morning"]) / 100.0 * CAP
        assert abs(rec["drain_kwh"] - soc_kwh) / soc_kwh < 0.20, (
            f"integral {rec['drain_kwh']} vs SOC-implied {soc_kwh}"
        )


class TestDayMetricsAreUnaffected:
    def test_day_home_energy_still_accrues_after_dawn(self):
        """The day phase exists to measure the refill day. Ending the NIGHT's
        counters at dawn must not stop the DAY's."""
        tr = _tracker()
        t = _clean_night(tr, 1_000_000.0)
        t = _run(tr, t, 3600, in_night=False, soc=80.0, home_w=1000.0)
        tr.tick(t + 10, True, Sample(soc=80.0))

        rec = tr.sealed()[-1]
        assert rec["day_home_kwh"] > 0.9, (
            f"day_home_kwh={rec['day_home_kwh']} — the day's own measurement "
            "was collateral damage"
        )


class TestRestoreIntoTheDayPhase:
    """The live rig is mid-day when this ships, holding a night that already
    flipped without freezing anything. Without a migration its record would
    still absorb the rest of today, and the first proof of the fix would have
    to wait an extra day."""

    def test_a_day_phase_restore_freezes_what_it_has(self):
        tr = _tracker()
        t = _clean_night(tr, 1_000_000.0)
        t = _run(tr, t, 600, in_night=False, soc=57.0)
        state = tr.to_dict()
        state.pop("night_gap_s", None)          # as written by the old code
        state.pop("night_held_s", None)

        fresh = _tracker()
        fresh.from_dict(state)
        t = _run(fresh, t, 2700, in_night=False, measured=False, soc=60.0)
        fresh.tick(t + 10, True, Sample(soc=60.0))

        rec = fresh.sealed()[-1]
        assert rec["gap_s"] <= 300.0, (
            f"gap_s={rec['gap_s']} — a record restored mid-day still ate the "
            "rest of the day (#837)"
        )
        assert rec["trainable"] is True

    def test_a_night_phase_restore_keeps_counting(self):
        """The mirror: restoring INTO the night must not freeze anything —
        the night is still running and its gaps still count."""
        tr = _tracker()
        t = 1_000_000.0
        tr.start("2026-08-23", outdoor_temp_c=18.0)
        t = _run(tr, t, 3600, in_night=True, soc=97.0, to_home_w=600.0)
        state = tr.to_dict()

        fresh = _tracker()
        fresh.from_dict(state)
        t = _run(fresh, t, 2400, in_night=True, measured=False, soc=None)
        t = _run(fresh, t, 600, in_night=False, soc=80.0)
        fresh.tick(t + 10, True, Sample(soc=80.0))

        rec = fresh.sealed()[-1]
        assert rec["gap_s"] > 300.0, "a real in-night hole stopped counting"
        assert rec["trainable"] is False
