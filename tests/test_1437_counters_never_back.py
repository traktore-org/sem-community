"""(#1437) A counter that adds up over a period never steps back inside it.

#1382 held the meter-backed daily rows. PROD 26.11 showed two counters it did
not cover still stepping back: the day's base load (house minus the controlled
loads) 9.29 → 9.28 kWh eight times, and the CO₂ saved 0.02 → 0.01 kg twice.
The rule now sits where every counter is published: the sensor.
"""
import ast
import math
from datetime import date, datetime
from itertools import pairwise
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from homeassistant.components.sensor import (
    SensorDeviceClass, SensorEntityDescription, SensorStateClass,
)

from custom_components.solar_energy_management.sensor import (
    SENSOR_TYPES, SEMSolarSensor,
)
from custom_components.solar_energy_management.utils.never_back import (
    MAY_FALL, MAY_FALL_FAMILIES, NEVER_BACK_FAMILIES, NEVER_BACK_KEYS,
    NEVER_BACK_MAX, family_of, is_never_back, never_back,
)

ZONE = dt_util.get_time_zone("Europe/Zurich")
SENSOR_PY = Path(__file__).resolve().parents[1] / "sensor.py"


def _scan_totals():
    """Every SensorEntityDescription key with a TOTAL or TOTAL_INCREASING
    state class, read from the source so a new one cannot hide: the fixed
    keys, and the families whose key is built with an id (``{}`` for it)."""
    tree = ast.parse(SENSOR_PY.read_text())
    keys, families, other = set(), set(), []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "SensorEntityDescription"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        key, sc = kw.get("key"), kw.get("state_class")
        if sc is None or ast.unparse(sc).rsplit(".", 1)[-1] not in (
                "TOTAL", "TOTAL_INCREASING"):
            continue
        if isinstance(key, ast.Constant):
            keys.add(key.value)
        elif isinstance(key, ast.JoinedStr):
            families.add("".join(
                part.value if isinstance(part, ast.Constant) else "{}"
                for part in key.values))
        else:
            other.append(ast.unparse(key))
    return keys, families, other


def _totals_in_sensor_py():
    return _scan_totals()[0]


# ── the rule covers every counter ───────────────────────────────────────────

def test_every_total_is_named_never_back_or_says_why_it_may_fall():
    totals = _totals_in_sensor_py()
    assert totals, "the source scan found the counters"
    missing = totals - NEVER_BACK_KEYS - set(MAY_FALL)
    assert not missing, (
        f"new counters with no rule: {sorted(missing)} — add each to "
        "NEVER_BACK_KEYS, or to MAY_FALL with the reason it may fall "
        "(utils/never_back.py)")


def test_the_lists_name_real_counters_and_do_not_overlap():
    totals = _totals_in_sensor_py()
    assert not NEVER_BACK_KEYS & set(MAY_FALL)
    assert not (NEVER_BACK_KEYS | set(MAY_FALL)) - totals, "a stale name"
    assert all(reason.strip() for reason in MAY_FALL.values())


def test_every_counter_family_is_named_never_back_or_says_why():
    """A counter built per charger, string or device has its id in the
    key: the scan reads its family, so a new one cannot miss the rule."""
    _, families, other = _scan_totals()
    assert not other, f"a counter key the scan cannot read: {other}"
    assert families, "the source scan found the per-unit counters"
    missing = families - NEVER_BACK_FAMILIES - set(MAY_FALL_FAMILIES)
    assert not missing, (
        f"new counter families with no rule: {sorted(missing)} — add each "
        "to NEVER_BACK_FAMILIES, or to MAY_FALL_FAMILIES with the reason")
    assert not NEVER_BACK_FAMILIES & set(MAY_FALL_FAMILIES)
    assert not (NEVER_BACK_FAMILIES | set(MAY_FALL_FAMILIES)) - families, \
        "a stale family"
    assert all(reason.strip() for reason in MAY_FALL_FAMILIES.values())


@pytest.mark.parametrize("key, family", [
    ("charger_ev_charger_0_session_energy", "charger_{}_session_energy"),
    ("charger_ev_charger_0_session_energy_external",
     "charger_{}_session_energy_external"),
    ("charger_c2_daily_energy", "charger_{}_daily_energy"),
    ("charger_c2_flow_grid_to_ev_energy", "charger_{}_flow_grid_to_ev_energy"),
    ("pv_string_pv1_daily_energy", "pv_string_{}_daily_energy"),
    ("daily_tariff_cost_boiler", "daily_tariff_cost_{}"),
    ("daily_true_baseload_energy", None),
])
def test_a_built_key_finds_its_family(key, family):
    assert family_of(key) == family


def test_never_back_covers_keys_and_families():
    assert is_never_back("daily_co2_avoided")
    assert is_never_back("charger_c2_flow_solar_to_ev_energy")
    assert not is_never_back("charger_c2_session_energy_external")
    assert not is_never_back("daily_tariff_cost_boiler")
    assert not is_never_back("daily_net_cost")


def test_the_two_prod_counters_are_held():
    assert {"daily_true_baseload_energy", "daily_co2_avoided"} <= NEVER_BACK_KEYS


# ── the hold itself ─────────────────────────────────────────────────────────

@pytest.mark.parametrize("value, floor, out", [
    (9.28, 9.29, 9.29),          # PROD 26.11 09:03 base load
    (0.01, 0.02, 0.02),          # PROD 26.11 11:45 CO₂
    (9.31, 9.29, 9.31),          # a rise goes through
    (2.0, 5.0, 2.0 + NEVER_BACK_MAX),   # a real drop is held only so far
    (0.17, None, 0.17),          # a new period: no floor
])
def test_never_back(value, floor, out):
    assert never_back(value, floor) == pytest.approx(out)


# ── the sensor publishes it ─────────────────────────────────────────────────

def _desc(key):
    return next(d for d in SENSOR_TYPES if d.key == key)


def _sensor(mock_coordinator, key):
    mock_coordinator.last_update_success = True
    mock_coordinator.data = {"last_update": "x"}
    return SEMSolarSensor(coordinator=mock_coordinator, description=_desc(key),
                          entry_id="e")


def _publish(sensor, key, value, when):
    sensor.coordinator.data = {"last_update": "x", key: value}
    with patch.object(dt_util, "now", return_value=when):
        sensor._update_from_coordinator()
    return sensor._attr_native_value


@pytest.mark.parametrize("key, samples, want", [
    # PROD 26.11, local time: the base load and the CO₂ as SEM computed them
    ("daily_true_baseload_energy",
     [(9.29, "09:03:01"), (9.28, "09:03:11"), (9.30, "09:03:51"),
      (9.29, "09:04:11")],
     [9.29, 9.29, 9.30, 9.30]),
    ("daily_co2_avoided",
     [(0.02, "11:38:41"), (0.01, "11:45:01"), (0.03, "12:50:31"),
      (0.02, "12:54:51")],
     [0.02, 0.02, 0.03, 0.03]),
])
def test_prod_step_backs_are_held(mock_coordinator, key, samples, want):
    s = _sensor(mock_coordinator, key)
    got = [_publish(s, key, v, datetime.fromisoformat(f"2026-11-26T{t}").replace(tzinfo=ZONE))
           for v, t in samples]
    assert got == pytest.approx(want)


def test_midnight_starts_from_the_new_value(mock_coordinator):
    key = "daily_true_baseload_energy"
    s = _sensor(mock_coordinator, key)
    _publish(s, key, 26.29, datetime(2026, 11, 26, 23, 59, tzinfo=ZONE))
    assert _publish(s, key, 0.17, datetime(2026, 11, 27, 0, 0, 10, tzinfo=ZONE)) == 0.17


def test_a_counter_that_may_fall_is_left_alone(mock_coordinator):
    key = "daily_net_cost"
    s = _sensor(mock_coordinator, key)
    when = datetime(2026, 11, 26, 12, 0, tzinfo=ZONE)
    _publish(s, key, 3.20, when)
    assert _publish(s, key, 3.10, when) == 3.10


def test_a_restored_value_is_the_floor_only_in_its_own_period(mock_coordinator):
    key = "daily_true_baseload_energy"
    s = _sensor(mock_coordinator, key)
    s._reset_told = datetime(2026, 11, 26, 0, 0, tzinfo=ZONE)
    s._restore_not_back(9.29)
    # same day: held
    assert _publish(s, key, 9.28, datetime(2026, 11, 26, 9, 5, tzinfo=ZONE)) == 9.29
    s2 = _sensor(mock_coordinator, key)
    s2._reset_told = datetime(2026, 11, 26, 0, 0, tzinfo=ZONE)
    s2._restore_not_back(26.29)
    # HA was down over midnight: yesterday's value is no floor today
    assert _publish(s2, key, 0.17, datetime(2026, 11, 27, 0, 5, tzinfo=ZONE)) == 0.17


# ── per-unit counters and TOTAL_INCREASING ─────────────────────────────────

def _built(mock_coordinator, key, state_class=SensorStateClass.TOTAL):
    mock_coordinator.last_update_success = True
    mock_coordinator.data = {"last_update": "x"}
    desc = SensorEntityDescription(
        key=key, name=key, device_class=SensorDeviceClass.ENERGY,
        state_class=state_class, native_unit_of_measurement="kWh")
    return SEMSolarSensor(coordinator=mock_coordinator, description=desc,
                          entry_id="e")


def _at(h, m, day=26):
    return datetime(2026, 11, day, h, m, tzinfo=ZONE)


@pytest.mark.parametrize("key", [
    "charger_c2_flow_solar_to_ev_energy", "pv_string_pv1_daily_energy"])
def test_a_per_unit_day_counter_is_held_and_starts_again_at_midnight(
        mock_coordinator, key):
    s = _built(mock_coordinator, key)
    assert _publish(s, key, 4.21, _at(14, 0)) == 4.21
    assert _publish(s, key, 4.20, _at(14, 1)) == 4.21
    assert _publish(s, key, 4.25, _at(14, 2)) == 4.25
    # midnight: the hold ends where last_reset starts the new day
    assert _publish(s, key, 0.0, _at(0, 0, day=27)) == 0.0
    with patch.object(dt_util, "now", return_value=_at(0, 0, day=27)):
        assert s.last_reset == _at(0, 0, day=27)


def test_a_charger_day_row_falls_to_zero_at_its_own_day_start(mock_coordinator):
    """One charger reports the car day's row, which falls to 0 at the
    Charge-by time, not at midnight. TOTAL_INCREASING has no last_reset:
    Home Assistant reads that fall as a new cycle, and so does the hold."""
    key = "charger_c1_daily_energy"
    s = _built(mock_coordinator, key, SensorStateClass.TOTAL_INCREASING)
    assert _publish(s, key, 12.40, _at(6, 59)) == 12.40
    assert _publish(s, key, 12.39, _at(6, 59)) == 12.40      # a step back: held
    assert _publish(s, key, 0.0, _at(7, 0)) == 0.0           # a new cycle
    assert _publish(s, key, 0.02, _at(7, 5)) == 0.02


def test_a_lifetime_count_that_restarts_is_not_held_above_zero(mock_coordinator):
    key = "lifetime_ev_sessions"
    s = _sensor(mock_coordinator, key)
    assert s.entity_description.state_class == SensorStateClass.TOTAL_INCREASING
    first = _publish(s, key, 50, _at(12, 0))
    assert first == 50 and type(first) is int      # "50", not "50.0"
    one_less = _publish(s, key, 49, _at(12, 1))
    assert one_less == 49 and type(one_less) is int  # never 49.1 sessions
    assert _publish(s, key, 0, _at(12, 2)) == 0


def test_a_session_family_ends_its_hold_with_a_new_session(mock_coordinator):
    key = "charger_c1_session_energy"
    s = _built(mock_coordinator, key)

    def pub(value, start, when):
        s.coordinator.data = {"last_update": "x", key: value,
                              "charger_c1_session_start": start}
        with patch.object(dt_util, "now", return_value=when):
            s._update_from_coordinator()
        return s._attr_native_value

    first = _at(18, 0).isoformat()
    assert pub(7.31, first, _at(20, 0)) == 7.31
    assert pub(7.30, first, _at(20, 1)) == 7.31
    assert pub(0.0, _at(21, 0).isoformat(), _at(21, 0)) == 0.0


def test_the_hold_and_last_reset_change_period_together(mock_coordinator):
    """For every calendar counter that never steps back, the guard's period
    changes exactly where last_reset does."""
    times = [_at(23, 59, day=30).replace(month=11),
             datetime(2026, 12, 1, 0, 0, 5, tzinfo=ZONE),
             datetime(2026, 12, 31, 23, 59, tzinfo=ZONE),
             datetime(2027, 1, 1, 0, 0, 5, tzinfo=ZONE)]
    checked = set()
    for desc in SENSOR_TYPES:
        if (desc.key not in NEVER_BACK_KEYS
                or desc.state_class != SensorStateClass.TOTAL):
            continue
        s = _sensor(mock_coordinator, desc.key)
        seen = []
        for when in times:
            with patch.object(dt_util, "now", return_value=when):
                seen.append((s._period_of(s._current_start()), s.last_reset))
        if all(lr is None for _, lr in seen):
            continue          # lifetime, or a counter with its own start
        for (p0, r0), (p1, r1) in pairwise(seen):
            assert (p0 != p1) == (r0 != r1), desc.key
        checked.add(desc.key.split("_", 1)[0])
    assert {"daily", "flow", "monthly", "yearly"} <= checked


# ── the counter's own day, not the sensor's clock ──────────────────────────

def _books(mock_coordinator, day, ev_start=None):
    mock_coordinator._energy_calculator = SimpleNamespace(
        booking_day=day, ev_last_reset=lambda: ev_start)
    mock_coordinator._flow_calculator = SimpleNamespace(flow_day=day)


@pytest.mark.parametrize("key", [
    "daily_grid_export_negative_kwh", "flow_battery_to_grid_energy"])
def test_yesterday_published_after_midnight_is_no_floor_for_today(
        mock_coordinator, key):
    """A cycle reads its data at 23:59:59.6 and publishes at 00:00:00.4.
    That value is yesterday's: it must not hold today's 0 at 0.1 all day,
    and today's period starts with today's data, not with it."""
    s = _sensor(mock_coordinator, key)
    _books(mock_coordinator, date(2026, 11, 26))
    assert _publish(s, key, 2.0, _at(23, 59)) == 2.0
    late = datetime(2026, 11, 27, 0, 0, 0, 400000, tzinfo=ZONE)
    assert _publish(s, key, 2.0, late) == 2.0
    with patch.object(dt_util, "now", return_value=late):
        assert s.last_reset == _at(0, 0, day=26)      # still yesterday's day
    _books(mock_coordinator, date(2026, 11, 27))
    assert _publish(s, key, 0.0, _at(0, 0, day=27)) == 0.0
    assert _publish(s, key, 0.0, _at(18, 0, day=27)) == 0.0
    with patch.object(dt_util, "now", return_value=_at(18, 0, day=27)):
        assert s.last_reset == _at(0, 0, day=27)


def test_the_car_day_row_holds_by_the_car_day(mock_coordinator):
    key = "daily_ev_energy"
    s = _sensor(mock_coordinator, key)
    day_start = _at(7, 0, day=26)
    _books(mock_coordinator, date(2026, 11, 27), ev_start=day_start)
    assert _publish(s, key, 9.50, _at(6, 0, day=27)) == 9.50
    assert _publish(s, key, 9.49, _at(6, 1, day=27)) == 9.50   # held
    _books(mock_coordinator, date(2026, 11, 27), ev_start=_at(7, 0, day=27))
    assert _publish(s, key, 0.0, _at(7, 0, day=27)) == 0.0     # new car day


def test_a_value_that_is_not_a_number_is_no_floor(mock_coordinator):
    key = "daily_true_baseload_energy"
    s = _sensor(mock_coordinator, key)
    assert _publish(s, key, 5.0, _at(12, 0)) == 5.0
    assert math.isnan(_publish(s, key, float("nan"), _at(12, 1)))
    assert _publish(s, key, 4.99, _at(12, 2)) == 5.0
    assert _publish(s, key, 5.2, _at(12, 3)) == 5.2


def test_a_small_charger_day_dip_is_held_not_read_as_a_reset(mock_coordinator):
    """Home Assistant reads a TOTAL_INCREASING fall below 90 % as a reset
    and counts the value again: 0.09 → 0.08 kWh is held."""
    key = "charger_c2_daily_energy"
    s = _built(mock_coordinator, key, SensorStateClass.TOTAL_INCREASING)
    assert _publish(s, key, 0.09, _at(10, 0)) == 0.09
    assert _publish(s, key, 0.08, _at(10, 1)) == 0.09
