"""#681 — a solar production counter is not credited in the dark.

Live catch on HA-PROD (Huawei SUN2000 10 kW + LUNA2000), 26.07.2026.
``sensor.inverter_gesamtenergieertrag`` ticked +0.01 kWh every ~70 s straight
through the night — 356 consecutive points, 22:00Z → 05:30Z, +3.55 kWh — with
``sensor.inverter_eingangsleistung`` (PV power) at 0 W the whole way. 0.51 kWh/h
is ≈ 510 W: the overnight house load, served by the *battery*. The counter
measures the inverter's AC output, not PV.

``sensor.sem_daily_solar_energy`` followed it 1:1 and reported 3.06 kWh of
solar produced before sunrise::

    23:10Z 0.000→0.510  00:11Z →1.020  01:20Z →1.530
    02:29Z →2.040       03:30Z →2.550  04:31Z →3.060

Because adoption is upward-only, the phantom is adopted while integration is
still ~0 and daytime integration then accumulates ON TOP of it — the day is
permanently wrong. The mirror error (counter UNDER-reports by day, because PV
routed DC→battery never leaves as AC yield) would have cancelled it, but
upward-only keeps the maximum, so the two ratchet instead of cancelling.

The fix withholds counter credit while ``sun.sun`` is ``below_horizon`` and
rolls the baseline forward instead. #556's motivating case is untouched: the
Deye-cloud install whose *power* sensor sits at 0 DURING THE DAY still gets
its counter delta credited.
"""
from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)

TODAY = date(2026, 7, 26)
MONTH = "2026_7"
YEAR = "2026"
COUNTER = "sensor.inverter_gesamtenergieertrag"


def _state(value, unit="kWh"):
    return SimpleNamespace(state=str(value), attributes={"unit_of_measurement": unit})


def _calc(states):
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    calc = EnergyCalculator(config={"system_size_kwp": 10}, time_manager=MagicMock())
    calc.configure_solar_counters(hass, [COUNTER], True)
    return calc


def _reconcile(calc):
    calc._reconcile_solar_energy(TODAY, MONTH, YEAR)


def _daily(calc):
    return calc._daily_accumulators.get(f"solar_{TODAY}", 0.0)


def _night(states):
    states["sun.sun"] = SimpleNamespace(state="below_horizon", attributes={})


def _day(states):
    states["sun.sun"] = SimpleNamespace(state="above_horizon", attributes={})


@pytest.mark.unit
class TestTheNightIsNotSolar:
    """THE regression: the PROD trace, replayed."""

    def test_the_prod_night_books_zero_solar(self):
        # 22:00Z rollover baseline, then the real overnight climb.
        states = {COUNTER: _state(20675.17)}
        _night(states)
        calc = _calc(states)
        _reconcile(calc)

        for value in (20675.60, 20676.11, 20677.00, 20677.97, 20678.72):
            states[COUNTER] = _state(value)
            _reconcile(calc)

        # +3.55 kWh of counter movement, PV power 0 W → 0.0 kWh of "solar".
        assert _daily(calc) == 0.0
        assert calc._monthly_accumulators.get(f"solar_{MONTH}", 0.0) == 0.0
        assert calc._yearly_accumulators.get(f"solar_{YEAR}", 0.0) == 0.0
        assert calc._lifetime_accumulators.get("lifetime_solar", 0.0) == 0.0

    def test_the_night_does_not_poison_the_following_day(self):
        """Sunrise anchors on the integrator, not on the night's movement."""
        states = {COUNTER: _state(20675.17)}
        _night(states)
        calc = _calc(states)
        _reconcile(calc)
        states[COUNTER] = _state(20678.72)  # +3.55 overnight
        _reconcile(calc)

        _day(states)
        calc._daily_accumulators[f"solar_{TODAY}"] = 0.0
        _reconcile(calc)  # first daylight cycle: re-anchor here
        states[COUNTER] = _state(20690.72)  # +12.0 of real production
        _reconcile(calc)

        assert _daily(calc) == pytest.approx(12.0)

    def test_a_midnight_counter_reset_in_the_dark_is_absorbed(self):
        """A daily-type counter resetting at midnight must not re-anchor."""
        states = {COUNTER: _state(71.15)}
        _night(states)
        calc = _calc(states)
        _reconcile(calc)
        states[COUNTER] = _state(0.0)  # daily counter rolls over
        _reconcile(calc)
        states[COUNTER] = _state(0.35)  # night discharge ticks again
        _reconcile(calc)

        assert _daily(calc) == 0.0


@pytest.mark.unit
class TestDaylightIsUnchanged:
    """#556 must survive intact — that is the whole point of the sun gate."""

    def test_556_deye_cloud_stall_still_recovers(self):
        # Power sensor stuck at 0 DURING THE DAY: integration stalled at 6.2,
        # the inverter counter saw 18.6. The counter still wins.
        states = {COUNTER: _state(5000.0)}
        _day(states)
        calc = _calc(states)
        calc._daily_accumulators[f"solar_{TODAY}"] = 6.2
        _reconcile(calc)  # anchor = 6.2
        states[COUNTER] = _state(5012.4)
        _reconcile(calc)

        assert _daily(calc) == pytest.approx(18.6)

    def test_upward_only_still_holds_in_daylight(self):
        states = {COUNTER: _state(5000.0)}
        _day(states)
        calc = _calc(states)
        _reconcile(calc)
        calc._daily_accumulators[f"solar_{TODAY}"] = 20.0  # integrator ran ahead
        states[COUNTER] = _state(5003.0)
        _reconcile(calc)

        assert _daily(calc) == pytest.approx(20.0)


@pytest.mark.unit
class TestTheGateFailsOpen:
    """No sun entity → pre-#681 behaviour, not a silently disabled feature."""

    def test_missing_sun_entity_does_not_gate(self):
        states = {COUNTER: _state(5000.0)}  # no sun.sun at all
        calc = _calc(states)
        _reconcile(calc)
        states[COUNTER] = _state(5012.4)
        _reconcile(calc)

        assert _daily(calc) == pytest.approx(12.4)

    @pytest.mark.parametrize("sun_state", ["unknown", "unavailable", "", "None"])
    def test_unusable_sun_state_does_not_gate(self, sun_state):
        states = {COUNTER: _state(5000.0),
                  "sun.sun": SimpleNamespace(state=sun_state, attributes={})}
        calc = _calc(states)
        _reconcile(calc)
        states[COUNTER] = _state(5012.4)
        _reconcile(calc)

        assert _daily(calc) == pytest.approx(12.4)

    def test_only_below_horizon_gates(self):
        calc = _calc({"sun.sun": SimpleNamespace(state="below_horizon", attributes={})})
        assert calc._sun_is_down() is True
        calc = _calc({"sun.sun": SimpleNamespace(state="above_horizon", attributes={})})
        assert calc._sun_is_down() is False
        calc = _calc({})
        assert calc._sun_is_down() is False
