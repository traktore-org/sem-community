"""#1436 — session sensors say when they reset, and no start is told twice.

The EV, per-charger and battery session sensors are TOTAL sensors that fall
to 0 when the next session starts. Their ``last_reset`` was None, so Home
Assistant booked each fall as negative use. The charger's own session
counter (``_session_energy_external``) falls when the charger likes, which
SEM cannot see.

Pinned here:

* each session sensor's ``last_reset`` is its session's start, published
  with the value from the same session record;
* a start Home Assistant does not have is told only for a period that began
  after it last saw the sensor (the restored state). A session or device
  day running at the upgrade says None, and so does one running when a beta
  was rolled back and installed again (#1432's comment): Home Assistant
  forgot the start while the old build ran, and a start that comes back
  counts the period again;
* Home Assistant's own sum over sessions, an upgrade, a restart and a
  rollback equals the kWh the sessions drew;
* the battery session survives a restart: cut to 0, the fall was booked as
  use;
* the charger's own counter counts up (TOTAL_INCREASING) and reads unknown,
  not 0, while it cannot be read.
"""
from __future__ import annotations

import ast
import json
import math
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from freezegun import freeze_time
from homeassistant.components.sensor import (
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
    charger_own_session_kwh,
)
from custom_components.solar_energy_management.coordinator.storage import SEMStorage
from custom_components.solar_energy_management.coordinator.types import (
    BatterySessionData,
    SEMData,
    SessionData,
)
from custom_components.solar_energy_management.sensor import (
    NO_RESET_TOTAL_KEYS,
    RESET_UNTOLD_TOTAL_KEYS,
    SESSION_SENSOR_STARTS,
    SEMSolarSensor,
    period_start_key,
)
from custom_components.solar_energy_management.tests.test_1432_device_day_last_reset import (
    SENSOR_PY,
    _ha_sum,
    _total_keys,
)

UTC = timezone.utc
T0 = datetime(2026, 11, 26, 12, 0, tzinfo=UTC)
STEP = timedelta(minutes=5)


def _sensor(key: str, data: dict | None = None) -> SEMSolarSensor:
    sensor = SEMSolarSensor.__new__(SEMSolarSensor)
    sensor.entity_description = SensorEntityDescription(
        key=key, state_class=SensorStateClass.TOTAL)
    sensor.coordinator = SimpleNamespace(data=dict(data or {}),
                                         _energy_calculator=None)
    return sensor


async def _added(key: str, last_state: State | None) -> SEMSolarSensor:
    """A sensor as Home Assistant adds it: the restored state first."""
    sensor = _sensor(key)

    async def _last():
        return last_state
    sensor.async_get_last_state = _last
    await sensor._restore_reset()
    return sensor


def _state(value: float, last_reset: datetime | None, seen: datetime) -> State:
    attrs = {"last_reset": last_reset.isoformat()} if last_reset else {}
    return State("sensor.sem_session_energy", str(value), attrs,
                 last_updated=seen, last_changed=seen)


def _read(sensor: SEMSolarSensor, start_key: str, start: datetime | None):
    sensor.coordinator.data[start_key] = start.isoformat() if start else None
    return sensor.last_reset


# ── each session row says its own start ─────────────────────────────


@pytest.mark.parametrize("key", sorted(SESSION_SENSOR_STARTS) + [
    "charger_wb_1_session_energy", "charger_keba_p30_2_session_energy"])
def test_each_session_row_reads_its_own_start(key):
    start_key = period_start_key(key)
    assert start_key is not None
    data = {start_key: "2026-11-26T17:42:10.123456+01:00"}
    assert _sensor(key, data).last_reset == dt_util.parse_datetime(
        data[start_key])
    # no session yet: None, as before
    assert _sensor(key, {}).last_reset is None


def test_each_charger_reads_its_own_session():
    assert period_start_key("charger_wb_1_session_energy") == \
        "charger_wb_1_session_start"
    assert period_start_key("charger_keba_p30_2_session_energy") == \
        "charger_keba_p30_2_session_start"
    # the charger's own counter has no start SEM can see
    assert period_start_key("charger_wb_1_session_energy_external") is None
    assert period_start_key("daily_ev_energy") is None


def test_the_record_publishes_its_start_with_its_value():
    ev = SessionData(active=True, start_time="2026-11-26T17:42:10+01:00",
                     energy_kwh=3.2, cost_chf=0.8)
    other = SessionData(active=True, start_time="2026-11-26T18:01:00+01:00",
                        energy_kwh=1.234)
    battery = BatterySessionData(active=True, session_type="discharge",
                                 start_time="2026-11-26T16:00:00+01:00",
                                 energy_kwh=2.5, savings=0.625)
    data = SEMData(session=ev, sessions={"wb_1": ev, "wb_2": other},
                   battery_session=battery,
                   ev_charger_ids=["wb_1", "wb_2"]).to_dict()
    assert (data["session_energy"], data["session_start"]) == (
        3.2, ev.start_time)
    assert data["session_cost"] == 0.8
    assert (data["charger_wb_2_session_energy"],
            data["charger_wb_2_session_start"]) == (1.23, other.start_time)
    assert data["charger_wb_1_session_start"] == ev.start_time
    assert (data["battery_session_energy"], data["battery_session_start"]) \
        == (2.5, battery.start_time)
    assert data["battery_session_savings"] == pytest.approx(0.62, abs=0.011)


def _coordinator_tree() -> ast.AST:
    return ast.parse(SENSOR_PY.parent.joinpath(
        "coordinator", "coordinator.py").read_text())


def _row_writes(body: list) -> dict:
    """``result[f"..."] = value`` statements of one block, by their key."""
    out = {}
    for stmt in body:
        if (isinstance(stmt, ast.Assign) and len(stmt.targets) == 1
                and isinstance(stmt.targets[0], ast.Subscript)
                and getattr(stmt.targets[0].value, "id", None) == "result"):
            out[ast.unparse(stmt.targets[0].slice)] = stmt.value
    return out


def test_the_coordinator_row_publishes_the_start_beside_the_energy():
    """The per-charger row is written twice (``to_dict`` and the cycle's
    per-charger block); each block that writes the energy writes the start
    from the same record."""
    energy, start = "f'charger_{cid}_session_energy'", "f'charger_{cid}_session_start'"
    blocks = 0
    for node in ast.walk(_coordinator_tree()):
        for body in (getattr(node, "body", None), getattr(node, "orelse", None)):
            if not isinstance(body, list):
                continue
            rows = _row_writes(body)
            if energy in rows:
                blocks += 1
                assert start in rows, ast.unparse(rows[energy])
                if isinstance(rows[energy], ast.Call):
                    assert ast.unparse(rows[start]) == "session.start_time"
                else:
                    assert ast.unparse(rows[start]) == "None"
    assert blocks == 2


def test_the_lists_know_the_session_rows():
    keys = _total_keys()
    assert set(SESSION_SENSOR_STARTS) <= keys
    assert "charger_{cid}_session_energy" in keys
    assert not set(SESSION_SENSOR_STARTS) & (
        NO_RESET_TOTAL_KEYS | RESET_UNTOLD_TOTAL_KEYS)
    assert RESET_UNTOLD_TOTAL_KEYS == {
        "forecast_today_kwh", "forecast_tomorrow_kwh",
        "forecast_remaining_today_kwh"}


# ── a start Home Assistant does not have ────────────────────────────


async def test_a_session_running_at_the_upgrade_says_none_until_the_next():
    """The old build published no start; Home Assistant counted the
    session so far without one. Its start now would count it again."""
    running = T0 - timedelta(hours=1)
    sensor = await _added("session_energy", _state(4.2, None, T0))
    assert _read(sensor, "session_start", running) is None
    nxt = T0 + timedelta(hours=3)
    assert _read(sensor, "session_start", nxt) == nxt
    assert _read(sensor, "session_start", nxt) == nxt


async def test_a_rollback_inside_the_day_keeps_none():
    """(#1432's comment) A beta is rolled back and installed again inside
    the day. SEM's store still holds the day's start; Home Assistant forgot
    it while the old build ran (its last state says none). Told again, it
    counts the day so far twice."""
    sunrise = datetime(2026, 11, 26, 7, 13, tzinfo=UTC)
    sensor = await _added("heat_pump_energy_today",
                          _state(6.0, None, sunrise + timedelta(hours=5)))
    assert _read(sensor, "heat_pump_day_start", sunrise) is None
    tomorrow = sunrise + timedelta(days=1, minutes=1)
    assert _read(sensor, "heat_pump_day_start", tomorrow) == tomorrow


async def test_a_restart_keeps_the_start_home_assistant_has():
    start = T0 - timedelta(hours=2)
    sensor = await _added("battery_session_energy", _state(1.5, start, T0))
    assert _read(sensor, "battery_session_start", start) == start


async def test_a_period_that_began_while_sem_was_down_is_told():
    """HA was down over sunrise: the new day began after the last state
    Home Assistant saw, so it counts from 0 and nothing twice."""
    yesterday = datetime(2026, 11, 25, 7, 11, tzinfo=UTC)
    stopped = datetime(2026, 11, 26, 5, 0, tzinfo=UTC)
    today = datetime(2026, 11, 26, 7, 13, tzinfo=UTC)
    sensor = await _added("heat_pump_energy_today",
                          _state(9.0, yesterday, stopped))
    assert _read(sensor, "heat_pump_day_start", today) == today


async def test_none_and_older_starts_are_never_told():
    """None starts no period; a start that moved back is no new period.
    After a None the start Home Assistant has stays, so a start that comes
    back cannot count its period again."""
    start = T0 - timedelta(hours=2)
    sensor = await _added("session_cost", _state(0.4, start, T0))
    assert _read(sensor, "session_start", None) == start
    assert _read(sensor, "session_start", start) == start
    assert _read(sensor, "session_start", start - timedelta(minutes=5)) == start


async def test_no_saved_state_tells_only_a_period_begun_in_this_run():
    with freeze_time(T0):
        sensor = await _added("charger_wb_1_session_energy", None)
    assert _read(sensor, "charger_wb_1_session_start",
                 T0 - timedelta(minutes=30)) is None
    later = T0 + timedelta(minutes=10)
    assert _read(sensor, "charger_wb_1_session_start", later) == later


async def test_a_start_with_no_offset_is_local_time():
    local = datetime(2026, 11, 26, 18, 0)        # no offset, as some stores
    sensor = await _added("session_energy",
                          _state(1.0, None, T0 - timedelta(days=1)))
    told = _read(sensor, "session_start", local)
    assert told == local.replace(tzinfo=dt_util.get_default_time_zone())


async def test_a_restored_state_with_a_bad_last_reset_reads_none():
    state = State("sensor.sem_session_energy", "3.0",
                  {"last_reset": "not a time"}, last_updated=T0)
    sensor = await _added("session_energy", state)
    assert sensor._reset_told is None
    assert _read(sensor, "session_start", T0 - timedelta(hours=1)) is None


def test_the_restore_runs_before_the_first_state():
    """The first state written must already know the start Home Assistant
    has: the restore comes before ``super().async_added_to_hass``."""
    tree = ast.parse(SENSOR_PY.read_text())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "SEMSolarSensor")
    fn = next(n for n in cls.body if getattr(n, "name", "") == "async_added_to_hass")
    src = ast.unparse(fn)
    assert src.index("_restore_reset") < src.index("super().async_added_to_hass")


# ── Home Assistant's sum ────────────────────────────────────────────


async def test_home_assistant_sums_each_session_once():
    """Sessions A (running at the upgrade, 3 kWh counted by the old build),
    B and C, with a restart inside B and a beta rolled back inside C.
    Home Assistant must book what the car drew after the upgrade: A 3→5,
    B 0→7, C 0→4 — 13 kWh — and never a fall."""
    t = T0
    rows = [(3.0, None)]                      # the old build's last window
    sensor = await _added("session_energy", _state(3.0, None, t))

    def run(start, values):
        nonlocal t
        for value in values:
            t += STEP
            rows.append((value, _read(sensor, "session_start", start)))

    run(T0 - timedelta(hours=1), [3.5, 4.0, 5.0, 5.0])
    b = t + timedelta(minutes=2)              # starts inside a window
    run(b, [0.4, 2.0, 3.5])
    # restart inside B: the new run reads the state Home Assistant had
    sensor = await _added("session_energy", _state(3.5, rows[-1][1], t))
    run(b, [5.0, 7.0])
    c = t + timedelta(minutes=2)
    run(c, [1.0, 2.0])
    # rolled back inside C: the old build says no start
    for value in (2.5, 3.0):
        t += STEP
        rows.append((value, None))
    sensor = await _added("session_energy", _state(3.0, None, t))
    run(c, [3.5, 4.0])                        # SEM's store still says C
    assert all(r is None for _, r in rows[-2:])
    assert _ha_sum(rows) == pytest.approx(13.0)


# ── the battery session survives a restart ──────────────────────────


def _storage() -> SEMStorage:
    storage = SEMStorage.__new__(SEMStorage)
    storage._daily_data = {}
    return storage


def _coord(storage) -> SEMCoordinator:
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord._storage = storage
    coord._battery_session = BatterySessionData()
    coord._battery_session_idle_count = 7
    coord._battery_session_opposite_count = 2
    return coord


def test_the_battery_session_survives_a_restart():
    storage = _storage()
    before = _coord(storage)
    before._battery_session = BatterySessionData(
        active=True, session_type="discharge",
        start_time="2026-11-26T16:00:00+01:00", duration_minutes=30.0,
        energy_kwh=2.5, savings=0.625, avg_power_w=5000.0)
    before._save_battery_session_state()
    # the store is written as JSON
    storage._daily_data = json.loads(json.dumps(storage._daily_data))
    after = _coord(storage)
    after._restore_battery_session_state()
    assert after._battery_session == before._battery_session
    assert (after._battery_session_idle_count,
            after._battery_session_opposite_count) == (0, 0)


@pytest.mark.parametrize("broken", [
    {"session_type": "sideways"},
    {"start_time": 12},
    {"energy_kwh": "2.5"},
    {"energy_kwh": math.nan},
    {"savings": True},
])
def test_a_broken_battery_record_is_not_restored(broken):
    storage = _storage()
    saved = {"active": True, "session_type": "charge",
             "start_time": "2026-11-26T10:00:00+01:00", "energy_kwh": 1.0}
    storage._daily_data["battery_session"] = {**saved, **broken}
    coord = _coord(storage)
    coord._restore_battery_session_state()
    assert coord._battery_session == BatterySessionData()


def test_no_saved_battery_session_keeps_a_new_one():
    coord = _coord(_storage())
    coord._restore_battery_session_state()
    assert coord._battery_session == BatterySessionData()


def test_the_cycle_saves_and_the_first_update_restores_the_battery_session():
    tree = ast.parse(SENSOR_PY.parent.joinpath(
        "coordinator", "coordinator.py").read_text())
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_async_update_data")
    calls = [n.func.attr for n in ast.walk(fn)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    order = [c for c in calls if c in (
        "_restore_ev_session_state", "_restore_battery_session_state",
        "_update_battery_session_tracking", "_save_battery_session_state")]
    assert "_restore_battery_session_state" in order
    lines = {}
    for n in ast.walk(fn):
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute):
            lines.setdefault(n.func.attr, n.lineno)
    assert lines["_restore_ev_session_state"] < lines["_restore_battery_session_state"]
    assert lines["_update_battery_session_tracking"] < lines["_save_battery_session_state"]
    assert lines["_save_battery_session_state"] - lines["_update_battery_session_tracking"] <= 2


# ── the charger's own counter ───────────────────────────────────────


def _description(key: str) -> dict:
    for node in ast.walk(ast.parse(SENSOR_PY.read_text())):
        if (isinstance(node, ast.Call)
                and getattr(node.func, "id", None) == "SensorEntityDescription"):
            kw = {k.arg: k.value for k in node.keywords}
            if ast.unparse(kw["key"]) == key:
                return kw
    raise AssertionError(key)


def test_the_charger_counter_counts_up():
    kw = _description("f'charger_{cid}_session_energy_external'")
    assert ast.unparse(kw["state_class"]) == "SensorStateClass.TOTAL_INCREASING"
    # SEM's own session row keeps TOTAL with its start
    kw = _description("f'charger_{cid}_session_energy'")
    assert ast.unparse(kw["state_class"]) == "SensorStateClass.TOTAL"


def _hass(states: dict):
    return SimpleNamespace(states=SimpleNamespace(get=states.get))


def test_the_charger_counter_reads_unknown_not_zero():
    meter = "sensor.keba_p30_session_energy"

    def read(state, unit="kWh"):
        found = {meter: State(meter, state, {"unit_of_measurement": unit})}
        return charger_own_session_kwh(_hass(found), meter)

    assert charger_own_session_kwh(_hass({}), "") == 0.0      # none set up
    assert charger_own_session_kwh(_hass({}), None) == 0.0
    assert charger_own_session_kwh(_hass({}), meter) is None  # gone
    assert read("unavailable") is None
    assert read("unknown") is None
    assert read("5.678") == 5.68
    assert read("1234", unit="Wh") == 1.23


def test_the_cycle_uses_the_counter_helper():
    key = "f'charger_{cid}_session_energy_external'"
    values = [rows[key] for node in ast.walk(_coordinator_tree())
              if isinstance(getattr(node, "body", None), list)
              for rows in [_row_writes(node.body)]
              if key in rows]
    assert len(values) == 1
    assert isinstance(values[0], ast.Call)
    assert getattr(values[0].func, "id", None) == "charger_own_session_kwh"
    assert coord_mod.charger_own_session_kwh is charger_own_session_kwh
