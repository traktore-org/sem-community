"""#681 — a second install's night, reproduced deterministically.

A second reporter confirmed the phantom on their own hardware, in these words:

    sensor.sem_daily_solar_energy went from 0 at midnight to 6.03 by 04:48 —
    about 45 minutes before our 04:54 sunrise — while both
    sensor.sem_pv_string_pv1_daily_energy and _pv2_daily_energy correctly
    stayed near zero over the same window. Same shape as your SUN2000 case,
    larger phantom (6+ kWh vs. 3.06 kWh), consistent with our larger overnight
    battery discharge. Confirms this is still live pre-update; will recheck
    after the beta.

Read the last sentence carefully: they were on a build from BEFORE the fix.
This is a second independent sighting of the original bug, NOT evidence that
the fix failed — and their size difference is itself evidence for the
mechanism, since the counter measures the inverter's AC OUTPUT and a larger
overnight battery discharge therefore writes a larger phantom.

An attempt to reproduce this on the simulation rig FAILED, and instructively.
The rig republishes its own entities every cycle, so the injected darkness and
zero PV never held — the run produced a plausible +6.30 kWh that was an
artifact of the injected counter, not the phantom. A deterministic test cannot
lose that race, which is why the reproduction lives here.

What this file pins:

* with the gate, their night books ZERO — the shipped fix covers their case,
  which is the answer to "will it still be there after the beta";
* without a ``sun.sun`` entity the gate deliberately fails open, and their
  exact phantom returns. That is the remaining exposure, and it is not
  hypothetical: an install without the sun integration still has this bug.

The reporter also handed over a signal SEM does not yet use — their PER-STRING
counters stayed near zero while the aggregate climbed. Two measurements of the
same quantity disagreeing, which needs no sun entity, no clock, and no
assumption about DC vs AC coupling. That is the natural second gate for the
fails-open case; it is NOT built here (#681 is closed and parked).
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)

TODAY = date(2026, 8, 24)
MONTH = "2026_8"
YEAR = "2026"
COUNTER = "sensor.inverter_gesamtenergieertrag"

#: Their night: 0 -> 6.03 kWh between midnight and 04:48, sunrise 04:54.
#: Modelled as the AC-yield counter climbing while PV power is flat at zero.
NIGHT_CLIMB_KWH = 6.03
BASE_COUNTER = 41250.0


def _state(value, unit="kWh"):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _calc(states):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    calc = EnergyCalculator(config={"system_size_kwp": 12}, time_manager=MagicMock())
    calc.configure_solar_counters(hass, [COUNTER], True)
    return calc


def _walk_their_night(states, calc, steps=6):
    """Advance the counter across the pre-dawn hours, as their inverter did."""
    calc._reconcile_solar_energy(TODAY, MONTH, YEAR)
    for i in range(1, steps + 1):
        states[COUNTER] = _state(BASE_COUNTER + NIGHT_CLIMB_KWH * i / steps)
        calc._reconcile_solar_energy(TODAY, MONTH, YEAR)
    return calc._daily_accumulators.get(f"solar_{TODAY}", 0.0)


class TestTheirNightWithTheGate:
    def test_their_6kwh_night_books_zero_solar(self):
        states = {COUNTER: _state(BASE_COUNTER),
                  "sun.sun": SimpleNamespace(state="below_horizon", attributes={})}
        booked = _walk_their_night(states, _calc(states))
        assert booked == pytest.approx(0.0, abs=0.01), (
            f"their night booked {booked:.2f} kWh of solar before sunrise")

    def test_the_day_after_is_not_poisoned(self):
        """Adoption is upward-only, so a phantom adopted overnight is not
        merely a bad night — daytime integration accumulates ON TOP of it and
        the whole day stays wrong. Their 6.03 would have ridden along all day."""
        states = {COUNTER: _state(BASE_COUNTER),
                  "sun.sun": SimpleNamespace(state="below_horizon", attributes={})}
        calc = _calc(states)
        _walk_their_night(states, calc)
        states["sun.sun"] = SimpleNamespace(state="above_horizon", attributes={})
        states[COUNTER] = _state(BASE_COUNTER + NIGHT_CLIMB_KWH + 4.0)
        calc._reconcile_solar_energy(TODAY, MONTH, YEAR)
        booked = calc._daily_accumulators.get(f"solar_{TODAY}", 0.0)
        assert booked == pytest.approx(4.0, abs=0.05), (
            f"the day booked {booked:.2f} kWh — the night's phantom rode along")


class TestTheRemainingExposure:
    """Without a sun entity the gate fails open, by design — and their exact
    phantom comes back. Recorded so the size of the remaining hole is a
    measured number rather than a footnote."""

    def test_no_sun_entity_reproduces_their_phantom(self):
        states = {COUNTER: _state(BASE_COUNTER)}          # no sun.sun at all
        booked = _walk_their_night(states, _calc(states))
        assert booked == pytest.approx(NIGHT_CLIMB_KWH, abs=0.05), (
            "the fails-open path no longer reproduces the reported phantom — "
            "if that is deliberate, this test should be rewritten rather than "
            "deleted, because it is the only record of the exposure's size")

    @pytest.mark.parametrize("sun_state", ["unknown", "unavailable"])
    def test_an_unusable_sun_state_reproduces_it_too(self, sun_state):
        states = {COUNTER: _state(BASE_COUNTER),
                  "sun.sun": SimpleNamespace(state=sun_state, attributes={})}
        booked = _walk_their_night(states, _calc(states))
        assert booked == pytest.approx(NIGHT_CLIMB_KWH, abs=0.05)
