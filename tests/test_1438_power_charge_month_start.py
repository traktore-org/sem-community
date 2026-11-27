"""#1438 — the power charge cost says its month starts when its value does.

``sensor.sem_power_charge_cost`` is the month's demand charge: the highest
booked 15-minute slot times the rate. Load management starts a new month
when it books that month's first slot, so on the 1st the value falls near
00:15, after the first slot closes. The slot 23:45–00:00 of the last day is
booked at 00:00 and still belongs to the old month. The sensor's
``last_reset`` said the calendar month, 00:00, so for those minutes Home
Assistant counted last month's charge again under the new month, and then
booked the fall as a minus.

Pinned here:

* load management holds the month its peak belongs to (with its year),
  saves it, and publishes it with the peak;
* the sensor's ``last_reset`` is that month: it moves in the cycle the
  value falls, never at midnight;
* Home Assistant's own sum over the month change, an upgrade and a restart
  equals the charge booked, with no minus — and the old calendar rule does
  not;
* every other day, month or year counter reads the record whose day the
  sensor's ``last_reset`` follows (the class guard).
"""
from __future__ import annotations

import ast
import json
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from freezegun import freeze_time
from homeassistant.core import State
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    SEMData,
)
from custom_components.solar_energy_management.features.load_management import (
    month_start,
)
from custom_components.solar_energy_management.sensor import (
    CAR_DAY_SENSOR_KEYS,
    MODULE_PERIOD_SENSOR_STARTS,
    NO_RESET_TOTAL_KEYS,
    RESET_UNTOLD_TOTAL_KEYS,
    SEMSolarSensor,
    calendar_kind,
    calendar_start,
    period_start_key,
)
from custom_components.solar_energy_management.tests.test_1432_device_day_last_reset import (
    _ha_sum,
    _total_keys,
)
from custom_components.solar_energy_management.tests.test_1436_session_last_reset import (
    _sensor,
)

ROOT = Path(__file__).resolve().parents[1]
RATE = 10.0          # demand charge per kW
KEY = "power_charge_cost"
START_KEY = "power_charge_month_start"


def _local(y, mo, d, h=0, mi=0, s=0):
    return datetime(y, mo, d, h, mi, s, tzinfo=dt_util.get_default_time_zone())


NOV = _local(2026, 11, 1)
DEC = _local(2026, 12, 1)


@pytest.fixture
def make_lm(mock_hass):
    """A real load manager; its store is a mock that keeps what it saved."""
    from custom_components.solar_energy_management.load_management import (
        LoadManagementCoordinator,
    )
    base = "custom_components.solar_energy_management.features.load_management"

    def _make(saved=None):
        entry = MagicMock()
        entry.options = {"load_management_enabled": True,
                         "target_peak_limit": 5.0, "warning_peak_level": 4.5,
                         "emergency_peak_level": 6.0, "peak_hysteresis": 0.3}
        entry.entry_id = "test_entry"
        with patch(f"{base}.LoadDeviceDiscovery") as disc, \
                patch(f"{base}.Store") as store:
            disc.return_value = MagicMock()
            st = MagicMock()
            st.async_load = AsyncMock(return_value=saved)
            st.async_save = AsyncMock()
            store.return_value = st
            lm = LoadManagementCoordinator(mock_hass, entry)
            lm._store = st
        return lm
    return _make


def _coord(lm):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {"demand_charge_rate": RATE}
    coord.hass = MagicMock()
    coord._load_manager = lm
    return coord


def _publish(coord) -> dict:
    """One cycle's published data, as the sensors read it."""
    return SEMData(load_management=coord._build_load_management_data(
        PowerReadings())).to_dict()


async def _added(last_state: State | None) -> SEMSolarSensor:
    sensor = _sensor(KEY)

    async def _last():
        return last_state
    sensor.async_get_last_state = _last
    await sensor._restore_reset()
    return sensor


def _state(value: float, last_reset: datetime | None, seen: datetime) -> State:
    attrs = {"last_reset": last_reset.isoformat()} if last_reset else {}
    return State("sensor.sem_power_charge_cost", str(value), attrs,
                 last_updated=seen, last_changed=seen)


def _read(sensor: SEMSolarSensor, data: dict):
    sensor.coordinator.data = data
    return data[KEY], sensor.last_reset


def _steps(rows):
    """Each window's change in Home Assistant's sum (``_ha_sum`` rule)."""
    return [_ha_sum(rows[: i + 2]) - _ha_sum(rows[: i + 1])
            for i in range(len(rows) - 1)]


# ── the load manager holds the month of its peak ────────────────────


def test_the_late_slot_stays_in_its_month(make_lm):
    with freeze_time(_local(2026, 11, 30, 23, 0)):
        lm = make_lm()
        assert lm.record_closed_slot(_local(2026, 11, 30, 22, 45), 3.0)
    with freeze_time(_local(2026, 12, 1, 0, 0, 10)):
        # the last slot of November closes after midnight: November's
        assert lm.record_closed_slot(_local(2026, 11, 30, 23, 45), 4.0)
        info = lm.get_load_management_data()
        assert info["monthly_consecutive_peak"] == pytest.approx(4.0)
        assert dt_util.parse_datetime(info["monthly_peak_start"]) == NOV
    with freeze_time(_local(2026, 12, 1, 0, 15, 10)):
        assert lm.record_closed_slot(_local(2026, 12, 1, 0, 0), 1.5)
        info = lm.get_load_management_data()
        assert info["monthly_consecutive_peak"] == pytest.approx(1.5)
        assert dt_util.parse_datetime(info["monthly_peak_start"]) == DEC


def test_the_same_month_a_year_later_is_a_new_month(make_lm):
    """The month number alone read November 2025 as this November."""
    with freeze_time(_local(2025, 11, 30, 12)):
        lm = make_lm()
        assert lm.record_closed_slot(_local(2025, 11, 30, 11, 45), 9.0)
    with freeze_time(_local(2026, 11, 20, 12)):
        assert lm.record_closed_slot(_local(2026, 11, 20, 11, 45), 2.0)
        assert lm._monthly_consecutive_peak == pytest.approx(2.0)
        assert lm._monthly_peak_start == NOV


def test_a_slot_of_a_month_already_over_is_not_booked(make_lm):
    """A manager that started again just after midnight holds December; the
    last slot of November closes after that. Booking it moved the month
    back, then forward again at 00:15: the sensor kept December and booked
    the fall as a minus."""
    with freeze_time(_local(2026, 12, 1, 0, 0, 5)):
        lm = make_lm()
        assert lm._monthly_peak_start == DEC
        assert lm.record_closed_slot(_local(2026, 11, 30, 23, 45), 6.0) is False
        assert lm._monthly_consecutive_peak == 0.0
        assert lm._monthly_peak_start == DEC
    with freeze_time(_local(2026, 12, 1, 0, 15, 5)):
        assert lm.record_closed_slot(_local(2026, 12, 1, 0, 0), 1.5)
        assert lm._monthly_consecutive_peak == pytest.approx(1.5)
        assert lm._monthly_peak_start == DEC


def test_a_fresh_manager_holds_this_month_at_zero(make_lm):
    with freeze_time(_local(2026, 11, 30, 23, 50)):
        lm = make_lm()
        info = lm.get_load_management_data()
        assert info["monthly_consecutive_peak"] == 0.0
        assert dt_util.parse_datetime(info["monthly_peak_start"]) == NOV
    # midnight alone moves nothing: the month starts with its first slot
    with freeze_time(_local(2026, 12, 1, 0, 5)):
        assert dt_util.parse_datetime(
            lm.get_load_management_data()["monthly_peak_start"]) == NOV


# ── saved and restored ──────────────────────────────────────────────


async def _loaded(make_lm, saved, now):
    with freeze_time(now):
        lm = make_lm(saved)
        await lm._load_device_configuration()
    return lm


@pytest.mark.asyncio
async def test_the_month_start_survives_a_restart(make_lm):
    with freeze_time(_local(2026, 11, 20, 12)):
        lm = make_lm()
        lm.record_closed_slot(_local(2026, 11, 20, 11, 45), 2.629)
        await lm._save_device_configuration()
    saved = json.loads(json.dumps(lm._store.async_save.call_args.args[0]))
    assert dt_util.parse_datetime(saved["monthly_peak_start"]) == NOV
    assert saved["monthly_peak_month"] == 11    # an older build reads this

    back = await _loaded(make_lm, saved, _local(2026, 11, 21, 8))
    assert back._monthly_consecutive_peak == pytest.approx(2.629)
    assert back._monthly_peak_start == NOV


@pytest.mark.asyncio
async def test_a_saved_start_keeps_the_month_it_names(make_lm):
    """A start saved under another offset (the time zone moved) still names
    its own month, and is kept as saved: the sensor told that moment."""
    zone_off = NOV.utcoffset() + timedelta(hours=1)
    sign = "+" if zone_off >= timedelta(0) else "-"
    hours = abs(int(zone_off.total_seconds())) // 3600
    raw = f"2026-11-01T00:00:00{sign}{hours:02d}:00"
    saved = {"devices": {}, "monthly_consecutive_peak": 3.1,
             "monthly_peak_month": 11, "monthly_peak_start": raw}
    lm = await _loaded(make_lm, saved, _local(2026, 11, 20, 12))
    assert lm._monthly_consecutive_peak == pytest.approx(3.1)
    assert lm._monthly_peak_start == dt_util.parse_datetime(raw)
    assert lm._monthly_peak_start.isoformat() == raw
    # a slot of this month keeps that start
    with freeze_time(_local(2026, 11, 20, 12, 15, 5)):
        assert lm.record_closed_slot(_local(2026, 11, 20, 12, 0), 3.5)
        assert lm._monthly_peak_start.isoformat() == raw


@pytest.mark.asyncio
async def test_a_restart_in_a_new_month_starts_it_at_zero(make_lm):
    saved = {"devices": {}, "monthly_consecutive_peak": 4.0,
             "monthly_peak_month": 11,
             "monthly_peak_start": NOV.isoformat()}
    lm = await _loaded(make_lm, saved, _local(2026, 12, 1, 0, 5))
    assert lm._monthly_consecutive_peak == 0.0
    assert lm._monthly_peak_start == DEC


@pytest.mark.asyncio
async def test_a_saved_month_a_year_old_is_not_restored(make_lm):
    saved = {"devices": {}, "monthly_consecutive_peak": 9.0,
             "monthly_peak_month": 11,
             "monthly_peak_start": _local(2025, 11, 1).isoformat()}
    lm = await _loaded(make_lm, saved, _local(2026, 11, 20, 12))
    assert lm._monthly_consecutive_peak == 0.0
    assert lm._monthly_peak_start == NOV


@pytest.mark.asyncio
@pytest.mark.parametrize("start", [None, "not a date", 7, "2026-11-01T00:00:00"])
async def test_a_store_without_a_good_start_reads_the_month_number(make_lm, start):
    """An older build saved the month number only; a broken or naive start
    reads as none."""
    saved = {"devices": {}, "monthly_consecutive_peak": 2.5,
             "monthly_peak_month": 11}
    if start is not None:
        saved["monthly_peak_start"] = start
    lm = await _loaded(make_lm, saved, _local(2026, 11, 20, 12))
    assert lm._monthly_consecutive_peak == pytest.approx(2.5)
    assert lm._monthly_peak_start == NOV
    other = await _loaded(make_lm, {**saved, "monthly_peak_month": 10},
                          _local(2026, 11, 20, 12))
    assert other._monthly_consecutive_peak == 0.0
    assert other._monthly_peak_start == NOV


# ── the sensor follows the published month ──────────────────────────


def test_the_sensor_reads_the_published_month():
    assert period_start_key(KEY) == START_KEY
    assert calendar_kind(KEY) is None
    sensor = _sensor(KEY, {START_KEY: NOV.isoformat()})
    assert sensor.last_reset == NOV


def test_the_start_is_published_from_the_same_snapshot():
    """The builder asks the load manager more than once a cycle; the peak
    and its month come from one answer, so they cannot split."""
    pairs = {float(m): _local(2026, m, 1).isoformat() for m in range(1, 13)}
    answers = iter(pairs.items())

    def _answer():
        peak, start = next(answers)
        return {"state": "normal", "monthly_consecutive_peak": peak,
                "monthly_peak_start": start}
    lm = MagicMock()
    lm.get_load_management_data = MagicMock(side_effect=_answer)
    data = _publish(_coord(lm))
    assert data[START_KEY] == pairs[data[KEY] / RATE]


def test_no_load_manager_publishes_no_start():
    data = _publish(_coord(None))
    assert data[KEY] == 0.0
    assert data[START_KEY] is None


# ── Home Assistant's sum over the month change ──────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize("restart_at", [None, _local(2026, 12, 1, 0, 5, 10)])
async def test_home_assistant_books_each_charge_once(make_lm, restart_at):
    """Every 5 minutes from 23:00 on 30.11 to 00:40 on 1.12, slots booked as
    the coordinator books them: the first sample after a slot ends. The old
    build had told November (the upgrade). The sum equals the charge the
    two months booked, and no window books a minus."""
    with freeze_time(_local(2026, 11, 30, 22, 0)):
        lm = make_lm()
        lm.record_closed_slot(_local(2026, 11, 30, 21, 0), 3.0)
    coord = _coord(lm)
    sensor = await _added(_state(3.0 * RATE, NOV, _local(2026, 11, 30, 22, 55)))
    slots = {(23, 30): ((2026, 11, 30, 23, 15), 2.0),
             (23, 45): ((2026, 11, 30, 23, 30), 3.5),
             (0, 0): ((2026, 11, 30, 23, 45), 4.0),
             (0, 15): ((2026, 12, 1, 0, 0), 1.5),
             (0, 30): ((2026, 12, 1, 0, 15), 2.5)}
    rows = []
    t = _local(2026, 11, 30, 23, 0, 10)
    while t <= _local(2026, 12, 1, 0, 40, 10):
        with freeze_time(t):
            if restart_at is not None and t == restart_at:
                saved = lm._store.async_save.call_args.args[0]
                lm = await _loaded(make_lm, json.loads(json.dumps(saved)), t)
                coord = _coord(lm)
                value, start = rows[-1]
                sensor = await _added(_state(value, start, t - timedelta(minutes=5)))
            slot = slots.get((t.hour, t.minute))
            if slot is not None and lm.record_closed_slot(_local(*slot[0]), slot[1]):
                await lm._save_device_configuration()
            rows.append(_read(sensor, _publish(coord)))
        t += timedelta(minutes=5)

    # November rose 3.0 → 3.5 → 4.0; December's first slots 1.5 then 2.5
    booked = (4.0 - 3.0 + 2.5) * RATE
    assert _ha_sum(rows) == pytest.approx(booked)
    assert min(_steps(rows)) >= 0
    # the month starts with the fall, not at midnight
    by_time = dict(zip(
        [(_local(2026, 11, 30, 23, 0, 10) + timedelta(minutes=5 * i)).strftime("%H:%M")
         for i in range(len(rows))], rows, strict=True))
    if restart_at is None:
        assert by_time["00:10"] == (4.0 * RATE, NOV)
    else:
        # the restart dropped November's peak: December from 0, told now
        assert by_time["00:05"] == (0.0, DEC)
    assert by_time["00:15"] == (1.5 * RATE, DEC)


def test_the_calendar_rule_booked_the_minus():
    """The same values with the old midnight start: Home Assistant counted
    November's charge again under December and booked the fall as a minus.
    This is what the fix changes."""
    values = [3.0, 3.0, 3.0, 3.5, 3.5, 3.5, 4.0, 4.0, 4.0, 1.5]
    times = [_local(2026, 11, 30, 23, 30, 10) + timedelta(minutes=5 * i)
             for i in range(len(values))]
    assert times[6].day == 1 and times[-1].minute == 15
    rows = [(v * RATE, calendar_start("month", t)) for v, t in zip(values, times, strict=True)]
    assert min(_steps(rows)) < 0
    assert _ha_sum(rows) != pytest.approx((4.0 - 3.0 + 1.5) * RATE)


# ── the class: a period counter reads the record its start follows ──


def _to_dict_roots() -> dict[str, set]:
    """Each key ``SEMData.to_dict`` publishes (an f-string key as its
    pattern) → the ``self.<record>`` its value is read from."""
    tree = ast.parse((ROOT / "coordinator" / "types.py").read_text())

    def roots(node):
        return {n.value.attr for n in ast.walk(node)
                if isinstance(n, ast.Attribute)
                and isinstance(n.value, ast.Attribute)
                and isinstance(n.value.value, ast.Name)
                and n.value.value.id == "self"}

    def name(k):
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            return k.value
        if isinstance(k, ast.JoinedStr):
            return "".join(v.value if isinstance(v, ast.Constant) else "{}"
                           for v in k.values)
        return None

    out: dict[str, set] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for k, v in zip(node.keys, node.values, strict=True):
                if name(k):
                    out.setdefault(name(k), set()).update(roots(v))
        elif isinstance(node, ast.DictComp) and name(node.key):
            got = roots(node.value) or set().union(
                *(roots(g.iter) for g in node.generators))
            out.setdefault(name(node.key), set()).update(got)
    return out


#: Calendar counters published outside ``SEMData.to_dict``, and the code
#: that reads them on the calculator's booking day.
_BOOKED_ELSEWHERE = {
    "daily_tariff_cost_{}": SEMCoordinator._device_tariff_books,
}


def test_every_period_counter_reads_the_record_its_start_follows():
    """(#1438) A day, month or year counter says the calendar period of the
    calculator that booked it (``SEMSolarSensor._data_day``: the flow
    calculator for flow and PV string rows, the energy calculator for the
    rest). A counter that another module rolls at its own moment — the
    power charge — must publish its own start (``period_start_key``)."""
    import inspect
    import textwrap
    roots = _to_dict_roots()
    want_flow, want_energy = {"energy_flows"}, {"energy", "costs"}
    wrong, unseen = {}, []
    for key in sorted(_total_keys()):
        real = key.replace("{cid}", "x1").replace("{slot}", "x1").replace(
            "{did}", "x1")
        if (calendar_kind(real) is None or key in NO_RESET_TOTAL_KEYS
                or key in RESET_UNTOLD_TOTAL_KEYS or key in CAR_DAY_SENSOR_KEYS
                or period_start_key(real) is not None):
            continue
        pattern = "".join("{}" if part.endswith("}") else part
                          for part in _split(key))
        if pattern in _BOOKED_ELSEWHERE:
            fn = ast.parse(textwrap.dedent(inspect.getsource(_BOOKED_ELSEWHERE[pattern])))
            # ``calc.booking_day`` or ``getattr(calc, "booking_day", …)``
            assert any(
                (isinstance(n, ast.Attribute) and n.attr == "booking_day")
                or (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "getattr"
                    and len(n.args) > 1 and isinstance(n.args[1], ast.Constant)
                    and n.args[1].value == "booking_day")
                for n in ast.walk(fn)), pattern
            continue
        got = roots.get(pattern)
        if not got:
            unseen.append(key)
            continue
        flow = "flow_" in real or real.startswith("pv_string_")
        if not got <= (want_flow if flow else want_energy):
            wrong[key] = got
    assert unseen == [], f"period counters not published by SEMData.to_dict: {unseen}"
    assert wrong == {}, (
        "period counters read from a record whose day the sensor does not "
        f"follow — publish their own start (MODULE_PERIOD_SENSOR_STARTS): {wrong}")


def _split(key: str):
    """``charger_{cid}_daily_energy`` → ``charger_``, ``{cid}``, ``_daily_energy``."""
    out, buf, depth = [], "", 0
    for ch in key:
        if ch == "{":
            if buf:
                out.append(buf)
            buf, depth = "{", 1
        elif ch == "}" and depth:
            out.append(buf + "}")
            buf, depth = "", 0
        else:
            buf += ch
    if buf:
        out.append(buf)
    return out


def test_a_module_start_is_published_beside_its_value():
    roots = _to_dict_roots()
    for key, start in MODULE_PERIOD_SENSOR_STARTS.items():
        assert roots[start] == roots[key] == {"load_management"}


def test_month_start_keeps_the_zone():
    assert month_start(_local(2026, 3, 29, 12)) == _local(2026, 3, 1)
    assert month_start(_local(2026, 10, 31, 23, 59)) == _local(2026, 10, 1)
