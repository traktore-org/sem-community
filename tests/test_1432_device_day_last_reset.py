"""#1432 — the heat pump's day, month and year say when they reset.

``sensor.sem_heat_pump_energy_today`` counts by the heat pump's own day: it
falls to 0 a few minutes after sunrise (#620/#704), not at midnight. It is a
TOTAL sensor, and its ``last_reset`` was None — no key pattern matched it.
Home Assistant then adds every change to the long-term sum, the drop too:
each sunrise booked about −55 kWh on the reporter's heat pump. The month
and year rows (``heat_pump_energy_month`` / ``_year``) had the same hole.

Pinned here:

* ``last_reset`` is the sunrise that opened the row's day, month or year,
  read from the same day key as the kWh — it moves in the cycle the row
  falls to 0, never in another cycle; a restart, a restart with no
  ``sun.sun`` yet, or a changed home location does not move it;
* a period already running when this code first published says None, as
  before — a new ``last_reset`` mid-period makes Home Assistant count the
  period so far again;
* Home Assistant's own sum over a run of days equals the kWh booked;
* every TOTAL sensor has a reset rule, or is listed as one without.
"""
from __future__ import annotations

import ast
import re
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from freezegun import freeze_time
from homeassistant.components.sensor import (
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import SUN_EVENT_SUNRISE
from homeassistant.helpers.sun import (
    get_astral_location,
    get_location_astral_event_next,
)
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.storage import (
    CALCULATOR_STATE_KEYS,
)
from custom_components.solar_energy_management.coordinator.types import (
    HeatPumpSensorData,
)
from custom_components.solar_energy_management.sensor import (
    CAR_DAY_SENSOR_KEYS,
    DEVICE_DAY_SENSOR_STARTS,
    NO_RESET_TOTAL_KEYS,
    RESET_UNTOLD_TOTAL_KEYS,
    SEMSolarSensor,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager

SENSOR_PY = Path(__file__).resolve().parents[1] / "sensor.py"
HP = "heat_pump"
STEP = timedelta(minutes=5)


# ── a home with a real sun ──────────────────────────────────────────


class _SunHass:
    """A hass with a location and a ``sun.sun`` whose ``next_rising`` is
    the next sunrise after now — as the sun integration publishes it, so
    the meter day rolls a few minutes after sunrise, as on the reporter's
    home."""

    def __init__(self):
        self.data = {}
        self.config = SimpleNamespace(
            latitude=52.37, longitude=4.90, elevation=0,
            time_zone=str(dt_util.get_default_time_zone()))
        self.states = SimpleNamespace(get=self._get)

    def _get(self, entity_id):
        if entity_id != "sun.sun":
            return None
        location, elevation = get_astral_location(self)
        rising = get_location_astral_event_next(
            location, elevation, SUN_EVENT_SUNRISE, dt_util.utcnow())
        return SimpleNamespace(attributes={"next_rising": rising.isoformat()})


def _local(y, mo, d, h=0, mi=0):
    return datetime(y, mo, d, h, mi, tzinfo=dt_util.get_default_time_zone())


def _calc(hass=None):
    hass = hass or _SunHass()
    return EnergyCalculator({"update_interval": 10}, TimeManager(hass))


def _cycle(calc: EnergyCalculator, kw: float = 2.0):
    """One cycle of the pump: book, then read back as the coordinator does
    — the kWh and its start from ONE day key."""
    day = calc._time_manager.get_current_meter_day_sunrise_based()
    calc.accumulate_device_energy(HP, kw * STEP.total_seconds() / 3600, day)
    row = calc.get_device_energy(HP, day)
    return day, row, calc.device_period_starts(day)


def _ha_sum(rows):
    """Home Assistant's long-term sum of a TOTAL sensor (the sensor
    recorder's ``_compile_statistics``), for one state per 5-minute window:
    a ``last_reset`` other than the one the last window kept starts a new
    period from 0; with none, every change is added, up or down. A window
    keeps its LAST state's ``last_reset``, None too."""
    total, old, old_reset = 0.0, None, None
    for value, reset in rows:
        if old is None:
            old, old_reset = value, reset
            continue
        if reset is not None and reset != old_reset:
            total += value
        else:
            total += value - old
        old, old_reset = value, reset
    return total


# ── the sunrise of a date ───────────────────────────────────────────


def test_the_sunrise_of_a_date_does_not_depend_on_the_clock():
    """``sun.sun``'s next rising moves to tomorrow once the sun is up; a
    start read from it would move mid-day and count the day twice."""
    day = date(2026, 11, 26)
    seen = set()
    for hour in (3, 8, 9, 12, 23):
        with freeze_time(_local(2026, 11, 26, hour)):
            seen.add(TimeManager(_SunHass()).sunrise_on(day))
    assert len(seen) == 1
    (sunrise,) = seen
    assert sunrise.date() == day and 6 <= sunrise.hour <= 9


def test_no_sunrise_that_date_starts_at_midnight():
    far_north = _SunHass()
    far_north.config.latitude = 78.2   # Svalbard: no sunrise in December
    day = date(2026, 12, 20)
    assert TimeManager(far_north).sunrise_on(day) == dt_util.start_of_local_day(day)
    # no location at all reads as no sunrise, never an error
    assert TimeManager(Mock()).sunrise_on(day) == dt_util.start_of_local_day(day)


# ── the starts ──────────────────────────────────────────────────────


def test_a_period_running_on_the_first_day_says_none_then_its_sunrise():
    calc = _calc()
    def sunrise(day):
        return calc._time_manager.sunrise_on(day).isoformat()
    first = date(2026, 11, 26)
    assert calc.device_period_starts(first) == {
        "day": None, "month": None, "year": None}
    # the next day: the day says its sunrise; month and year still run
    nxt = date(2026, 11, 27)
    assert calc.device_period_starts(nxt) == {
        "day": sunrise(nxt), "month": None, "year": None}
    # the next month: the month starts at the sunrise of the 1st
    dec = date(2026, 12, 3)
    assert calc.device_period_starts(dec) == {
        "day": sunrise(dec), "month": sunrise(date(2026, 12, 1)),
        "year": None}
    # the next year: 1 January's sunrise
    jan = date(2027, 1, 5)
    assert calc.device_period_starts(jan)["year"] == sunrise(date(2027, 1, 1))


def test_the_first_day_mark_survives_a_restart():
    before = _calc()
    before.device_period_starts(date(2026, 11, 26))
    state = before.get_state()
    assert state["device_period_since"] == "2026-11-26"
    assert "device_period_since" in CALCULATOR_STATE_KEYS

    after = _calc()
    after.restore_state(state)
    nxt = date(2026, 11, 27)
    assert after.device_period_starts(nxt)["day"] == (
        after._time_manager.sunrise_on(nxt).isoformat())
    # a store without the mark is the upgrade: today is the first day
    legacy = _calc()
    legacy.restore_state({k: v for k, v in state.items()
                          if k != "device_period_since"})
    assert legacy.device_period_starts(nxt)["day"] is None


def test_the_day_start_moves_only_in_the_cycle_the_row_falls_to_zero():
    with freeze_time(_local(2026, 11, 25, 12)) as clock:
        calc = _calc()
        rows = []
        while dt_util.now() < _local(2026, 11, 29, 12):
            _day, row, starts = _cycle(calc)
            rows.append((row["daily_kwh"], starts["day"]))
            clock.tick(STEP)
    drops = [i for i in range(1, len(rows)) if rows[i][0] < rows[i - 1][0]]
    moves = [i for i in range(1, len(rows)) if rows[i][1] != rows[i - 1][1]]
    assert len(drops) == 4          # four sunrises
    assert moves == drops
    # the upgrade day said None; every later day says its own sunrise
    assert rows[0][1] is None
    assert all(r is not None for _, r in rows[drops[0]:])


def test_home_assistant_sums_what_the_pump_used():
    """The reporter's numbers: about 55 kWh by morning, then the sunrise
    drop. Home Assistant's sum must be the kWh booked, not the booked kWh
    minus each morning's drop."""
    with freeze_time(_local(2026, 11, 24, 12)) as clock:
        calc = _calc()
        day_rows, month_rows, booked = [], [], 0.0
        while dt_util.now() < _local(2026, 12, 3, 12):
            _day, row, starts = _cycle(calc, kw=2.3)
            booked += 2.3 * STEP.total_seconds() / 3600
            day_rows.append((row["daily_kwh"], starts["day"]))
            month_rows.append((row["monthly_kwh"], starts["month"]))
            clock.tick(STEP)
    first = 2.3 * STEP.total_seconds() / 3600   # the sum starts at the first state
    assert _ha_sum(day_rows) == pytest.approx(booked - first, abs=0.01)
    assert _ha_sum(month_rows) == pytest.approx(booked - first, abs=0.01)
    # the old None booked each drop as negative use
    old = [(v, None) for v, _ in day_rows]
    assert _ha_sum(old) < booked - 300


def test_a_restart_across_sunrise_keeps_the_pairing():
    """Down from 07:00 to 10:00: the first cycle back is a new day, and its
    start moves in that cycle, with the drop."""
    with freeze_time(_local(2026, 11, 26, 0)) as clock:
        calc = _calc()
        calc.device_period_starts(date(2026, 11, 24))   # an older first day
        while dt_util.now() < _local(2026, 11, 26, 7):
            _d, before, s_before = _cycle(calc)
            clock.tick(STEP)
        state = calc.get_state()
        clock.move_to(_local(2026, 11, 26, 10))
        after = _calc()
        after.restore_state(state)
        _d, row, s_after = _cycle(after)
    assert row["daily_kwh"] < before["daily_kwh"]
    assert s_after["day"] != s_before["day"] and s_after["day"] is not None


def test_a_restart_before_sun_sun_is_up_does_not_step_the_day_back():
    """Review finding: Home Assistant restarts at 07:00 in November and
    ``sun.sun`` is not set up at SEM's first cycle. A fixed 06:00 fallback
    put that cycle in the new day; the next cycle, with ``sun.sun``, went
    back to yesterday — and its start with it, which Home Assistant read as
    a new period: yesterday's kWh counted twice."""
    hass = _SunHass()
    with freeze_time(_local(2026, 11, 25, 12)) as clock:
        calc = _calc(hass)
        rows, booked = [], 0.0
        while dt_util.now() < _local(2026, 11, 28, 7):
            _d, row, starts = _cycle(calc)
            booked += 2.0 * STEP.total_seconds() / 3600
            rows.append((row["daily_kwh"], starts["day"]))
            clock.tick(STEP)
        state = calc.get_state()
        # the restart: no sun.sun for the first cycle
        real_get = hass.states.get
        hass.states.get = lambda _eid: None
        after = _calc(hass)
        after.restore_state(state)
        days = []
        while dt_util.now() < _local(2026, 11, 28, 12):
            day, row, starts = _cycle(after)
            booked += 2.0 * STEP.total_seconds() / 3600
            rows.append((row["daily_kwh"], starts["day"]))
            days.append(day)
            hass.states.get = real_get
            clock.tick(STEP)
    assert days == sorted(days)            # the day never steps back
    assert days[0] == date(2026, 11, 27)   # 07:00 is before the sunrise
    first = 2.0 * STEP.total_seconds() / 3600
    assert _ha_sum(rows) == pytest.approx(booked - first, abs=0.01)


def test_the_day_rolls_at_the_sunrise_not_minutes_later():
    """The reporter saw the row fall 3-4 minutes after sunrise: tomorrow's
    sunrise minus 24 h, which is later in autumn. Today's own sunrise now."""
    hass = _SunHass()
    tm = TimeManager(hass)
    sunrise = tm.sunrise_on(date(2026, 11, 26))
    with freeze_time(sunrise - timedelta(seconds=30)) as clock:
        assert tm.get_current_meter_day_sunrise_based() == date(2026, 11, 25)
        clock.tick(timedelta(seconds=60))
        assert tm.get_current_meter_day_sunrise_based() == date(2026, 11, 26)
    # no sun.sun at all: the same sunrise, not a fixed 06:00
    hass.states.get = lambda _eid: None
    with freeze_time(sunrise - timedelta(minutes=30)):
        assert tm.get_current_meter_day_sunrise_based() == date(2026, 11, 25)
        assert tm.get_diagnostics()["sunrise_correction"] == "fallback_location"


def test_a_changed_location_does_not_move_a_running_start():
    """Review finding: the start is a sunrise, so a new home location (or a
    new astral) gives another one. Moved mid-period, Home Assistant counts
    the period so far again — a whole year on the year row."""
    hass = _SunHass()
    calc = _calc(hass)
    calc.device_period_starts(date(2025, 6, 1))
    before = calc.device_period_starts(date(2026, 11, 26))
    hass.config.latitude, hass.config.elevation = 47.0, 900
    assert calc.device_period_starts(date(2026, 11, 26)) == before
    # and after a restart
    after = _calc(hass)
    after.restore_state(calc.get_state())
    assert after.device_period_starts(date(2026, 11, 26)) == before
    assert "device_period_kept" in CALCULATOR_STATE_KEYS
    # the next day takes the new location's sunrise; month and year stay
    nxt = after.device_period_starts(date(2026, 11, 27))
    assert nxt["day"] == after._time_manager.sunrise_on(
        date(2026, 11, 27)).isoformat()
    assert (nxt["month"], nxt["year"]) == (before["month"], before["year"])


def test_a_bad_kept_row_is_dropped_not_raised():
    calc = _calc()
    calc.restore_state({"device_period_since": "2026-01-01",
                        "device_period_kept": {"day": ["2026-11-26"],
                                               "month": 5, "year": [1, 2]}})
    out = calc.device_period_starts(date(2026, 11, 26))
    assert out["day"] == calc._time_manager.sunrise_on(
        date(2026, 11, 26)).isoformat()


# ── the coordinator and the sensor ──────────────────────────────────


def test_the_coordinator_hands_the_starts_to_the_sensor_data():
    """The three starts reach ``HeatPumpSensorData`` from the view."""
    src = (SENSOR_PY.parent / "coordinator" / "coordinator.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "HeatPumpSensorData"):
            kw = {k.arg: ast.unparse(k.value) for k in node.keywords}
            break
    else:
        pytest.fail("no HeatPumpSensorData(...) in coordinator.py")
    for period in ("day", "month", "year"):
        assert kw[f"heat_pump_{period}_start"] == f"hp_starts.get('{period}')"


def test_the_coordinator_reads_kwh_and_starts_from_one_day():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    calc = _calc()
    calc.device_period_starts(date(2026, 11, 20))
    calc.accumulate_device_energy(HP, 4.0, date(2026, 11, 26))
    host = SimpleNamespace(_energy_calculator=calc,
                           time_manager=calc._time_manager)
    pump = SimpleNamespace(_daily_runtime_meter_day=date(2026, 11, 26))
    ledger, _today, _total, starts = SEMCoordinator._heat_pump_ledger_view(
        host, pump)
    assert ledger["daily_kwh"] == pytest.approx(4.0)
    assert starts["day"] == calc._time_manager.sunrise_on(
        date(2026, 11, 26)).isoformat()
    assert isinstance(starts["day"], str)   # ISO, as coordinator data carries
    assert starts["month"] is None and starts["year"] is None
    # no heat pump: no starts, nothing raised
    assert SEMCoordinator._heat_pump_ledger_view(host, None)[3] == {}


def test_the_starts_are_published():
    data = HeatPumpSensorData(heat_pump_day_start="2026-11-26T08:13:15+01:00")
    from custom_components.solar_energy_management.coordinator.types import SEMData
    published = SEMData(heat_pump=data).to_dict()
    assert published["heat_pump_day_start"] == "2026-11-26T08:13:15+01:00"
    assert published["heat_pump_month_start"] is None
    assert published["heat_pump_year_start"] is None


def _sensor(key: str, data: dict | None = None, calc=None):
    sensor = SEMSolarSensor.__new__(SEMSolarSensor)
    sensor.entity_description = SensorEntityDescription(
        key=key, state_class=SensorStateClass.TOTAL)
    sensor.coordinator = SimpleNamespace(data=data or {},
                                         _energy_calculator=calc)
    return sensor


@pytest.mark.parametrize("key", sorted(DEVICE_DAY_SENSOR_STARTS))
def test_each_heat_pump_row_says_its_own_start(key):
    data = {
        "heat_pump_day_start": "2026-11-26T08:13:15+01:00",
        "heat_pump_month_start": "2026-11-01T07:45:00+01:00",
        "heat_pump_year_start": "2026-01-01T08:48:00+01:00",
    }
    want = dt_util.parse_datetime(data[DEVICE_DAY_SENSOR_STARTS[key]])
    assert _sensor(key, data).last_reset == want
    # a period running at the upgrade says None, as before
    assert _sensor(key, {}).last_reset is None


# ── every TOTAL sensor has a reset rule (the guard) ─────────────────


def _total_keys() -> set[str]:
    """Every ``SensorEntityDescription`` key in sensor.py with state_class
    TOTAL; an f-string key keeps its ``{name}`` fields."""
    keys = set()
    for node in ast.walk(ast.parse(SENSOR_PY.read_text())):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "SensorEntityDescription"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        sc = kw.get("state_class")
        if not (isinstance(sc, ast.Attribute) and sc.attr == "TOTAL"):
            continue
        key = kw["key"]
        if isinstance(key, ast.Constant):
            keys.add(key.value)
        else:
            keys.add("".join(
                p.value if isinstance(p, ast.Constant)
                else "{" + ast.unparse(p.value) + "}" for p in key.values))
    return keys


def test_the_guard_reads_the_sensors_it_should():
    keys = _total_keys()
    assert {"heat_pump_energy_today", "daily_home_energy",
            "charger_{cid}_session_energy", "daily_tariff_cost_{did}"} <= keys
    assert len(keys) > 80


def test_every_total_sensor_says_when_it_resets():
    """A TOTAL sensor that falls back to 0 needs a ``last_reset`` that moves
    with the fall. One matched by no rule read None, unseen, until #1432.
    Each key is either told by a rule here, or listed as never resetting,
    or listed as open."""
    calc = SimpleNamespace(ev_last_reset=lambda: _local(2026, 11, 26, 7))
    data = {start: "2026-11-26T08:13:15+01:00"
            for start in DEVICE_DAY_SENSOR_STARTS.values()}
    listed = NO_RESET_TOTAL_KEYS | RESET_UNTOLD_TOTAL_KEYS
    untold = []
    for key in sorted(_total_keys()):
        if key in listed:
            continue
        real = re.sub(r"\{\w+\}", "x1", key)
        if _sensor(real, data, calc).last_reset is None:
            untold.append(key)
    assert untold == [], (
        "TOTAL sensors with no reset rule — give them one in "
        f"SEMSolarSensor.last_reset, or list them: {untold}")


def test_the_lists_hold_only_real_total_sensors():
    keys = _total_keys()
    for name, listed in (("NO_RESET_TOTAL_KEYS", NO_RESET_TOTAL_KEYS),
                         ("RESET_UNTOLD_TOTAL_KEYS", RESET_UNTOLD_TOTAL_KEYS),
                         ("DEVICE_DAY_SENSOR_STARTS", set(DEVICE_DAY_SENSOR_STARTS)),
                         ("CAR_DAY_SENSOR_KEYS", CAR_DAY_SENSOR_KEYS)):
        assert set(listed) <= keys, f"{name}: {set(listed) - keys}"
    assert not NO_RESET_TOTAL_KEYS & RESET_UNTOLD_TOTAL_KEYS
    assert not set(DEVICE_DAY_SENSOR_STARTS) & (
        NO_RESET_TOTAL_KEYS | RESET_UNTOLD_TOTAL_KEYS)
