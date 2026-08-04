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

    def test_an_overnight_charge_books_zero_solar(self):
        """The gate is magnitude-blind: an 11 kW night charge is still not PV.

        The catch was a 510 W house load. An overnight EV charge (or a
        cheap-hours battery top-up) pushes the SAME AC-output counter up two
        orders of magnitude harder — ~40 kWh across a night — because the
        inverter is passing grid power through to the car. Pre-#681 every one
        of those kWh was booked as production.
        """
        states = {COUNTER: _state(20675.17)}
        _night(states)
        calc = _calc(states)
        _reconcile(calc)

        # 22:00Z → 06:00Z at ~5 kW: +40 kWh of pass-through.
        for hour in range(1, 9):
            states[COUNTER] = _state(20675.17 + hour * 5.0)
            _reconcile(calc)

        assert _daily(calc) == 0.0
        assert calc._lifetime_accumulators.get("lifetime_solar", 0.0) == 0.0

    def test_an_overnight_charge_across_midnight_books_zero_solar(self):
        """Day rollover mid-charge: the new day starts anchored, not inflated.

        Every overnight charge crosses midnight, so the rollover branch runs
        while the gate is closed. The new day must re-baseline on the counter
        as it stands at that moment — otherwise the post-midnight half of the
        charge lands on the new day as production.
        """
        states = {COUNTER: _state(20675.17)}
        _night(states)
        calc = _calc(states)
        _reconcile(calc)
        states[COUNTER] = _state(20685.17)  # 22:00Z → 00:00Z, +10 kWh
        _reconcile(calc)

        # Midnight: the coordinator now passes tomorrow's keys.
        tomorrow = date(2026, 7, 27)
        for value in (20690.17, 20695.17, 20705.17):  # +20 kWh more, still dark
            states[COUNTER] = _state(value)
            calc._reconcile_solar_energy(tomorrow, MONTH, YEAR)

        assert calc._daily_accumulators.get(f"solar_{tomorrow}", 0.0) == 0.0
        assert _daily(calc) == 0.0
        assert calc._lifetime_accumulators.get("lifetime_solar", 0.0) == 0.0

        # ...and sunrise on the new day still anchors on the integrator.
        _day(states)
        calc._reconcile_solar_energy(tomorrow, MONTH, YEAR)
        states[COUNTER] = _state(20713.17)  # +8 kWh of real production
        calc._reconcile_solar_energy(tomorrow, MONTH, YEAR)

        assert calc._daily_accumulators.get(f"solar_{tomorrow}") == pytest.approx(8.0)

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
class TestTheNightWindowLiesInsideTheGate:
    """The overnight charge can never outlive the gate that covers it.

    Both subsystems read the same ``sun.sun``. ``get_night_window`` clamps::

        night_start = max(sunset + 10min, earliest_start)   # after sunset
        night_end   = min(sunrise, latest_end)              # at/before sunrise

    so the whole night-charging window sits strictly inside the period where
    ``_sun_is_down()`` is True. That is what makes #681 cover an overnight
    charge in full: the inverter's AC-output counter passes grid power through
    to the car at kW scale, and the gate is closed for every minute of it.

    If someone ever relaxes a clamp — lets night charging run past sunrise to
    "finish the session" — the counter starts booking that pass-through as
    production again. This test is the tripwire.
    """

    @staticmethod
    def _window(sunrise_utc, sunset_utc, **config):
        from unittest.mock import MagicMock as MM

        from custom_components.solar_energy_management.utils.time_manager import (
            TimeManager,
        )

        sun = MM()
        sun.attributes = {"next_rising": sunrise_utc, "next_setting": sunset_utc}
        hass = MM()
        hass.states.get = MM(return_value=sun)
        return TimeManager(hass=hass, config=config).get_night_window()

    @pytest.mark.parametrize(
        "label,sunrise,sunset",
        [
            # Midsummer: sunrise 03:51 is what PROD reported on 26.07.2026.
            ("midsummer", "2026-07-26T03:51:00+00:00", "2026-07-26T19:08:00+00:00"),
            # Midwinter: sunrise is LATER than latest_end, so the ceiling wins.
            ("midwinter", "2026-01-15T07:15:00+00:00", "2026-01-15T15:35:00+00:00"),
        ],
    )
    def test_the_window_never_escapes_darkness(self, label, sunrise, sunset):
        night_start, night_end = self._window(sunrise, sunset)
        sunrise_hhmm, sunset_hhmm = sunrise[11:16], sunset[11:16]

        # Charging stops at or before the gate opens...
        assert night_end <= sunrise_hhmm, f"{label}: charge outlives the gate"
        # ...and never starts before the gate closes.
        assert night_start > sunset_hhmm, f"{label}: charge starts before the gate"

    def test_an_absurd_earliest_start_cannot_open_a_daylight_window(self):
        """``max()`` is load-bearing: a midday floor still yields a dark start."""
        night_start, night_end = self._window(
            "2026-07-26T03:51:00+00:00",
            "2026-07-26T19:08:00+00:00",
            night_earliest_start=12.0,  # user asks for noon
        )
        assert night_start == "19:18"  # sunset + 10, not 12:00
        assert night_end <= "03:51"


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
