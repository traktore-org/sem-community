"""(#1437) A counter that adds up over a period never steps back inside it.

#1382 held the meter-backed daily rows. PROD 26.11 showed two counters it did
not cover still stepping back: the day's base load (house minus the controlled
loads) 9.29 → 9.28 kWh eight times, and the CO₂ saved 0.02 → 0.01 kg twice.
The rule now sits where every counter is published: the sensor.
"""
import ast
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.sensor import (
    SENSOR_TYPES, SEMSolarSensor,
)
from custom_components.solar_energy_management.utils.never_back import (
    MAY_FALL, NEVER_BACK_KEYS, NEVER_BACK_MAX, never_back,
)

ZONE = dt_util.get_time_zone("Europe/Zurich")
SENSOR_PY = Path(__file__).resolve().parents[1] / "sensor.py"


def _totals_in_sensor_py():
    """Every SensorEntityDescription key with a TOTAL or TOTAL_INCREASING
    state class, read from the source so a new one cannot hide."""
    tree = ast.parse(SENSOR_PY.read_text())
    keys = set()
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call)
                and getattr(node.func, "id", "") == "SensorEntityDescription"):
            continue
        kw = {k.arg: k.value for k in node.keywords}
        key, sc = kw.get("key"), kw.get("state_class")
        if isinstance(key, ast.Constant) and sc is not None and \
                ast.unparse(sc).rsplit(".", 1)[-1] in ("TOTAL", "TOTAL_INCREASING"):
            keys.add(key.value)
    return keys


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
