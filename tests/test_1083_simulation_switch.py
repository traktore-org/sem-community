"""#1083 — the Simulation tab switch.

One switch a person can find: it shows the Simulation tab, turns day tagging
on, and backfills up to 90 days of tags from hourly statistics. Hourly data
cannot show midday steadiness, so a backfilled day is never "sunny".
"""
import asyncio
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management import switch as sw_mod
from custom_components.solar_energy_management.analytics.day_tags import (
    tag_day,
    tag_sky,
)
from custom_components.solar_energy_management.coordinator import day_tag_store
from custom_components.solar_energy_management.coordinator.day_tag_store import (
    DayTagger,
    day_tags_on,
    simulation_tab_on,
)
from custom_components.solar_energy_management.coordinator.storage import SEMStorage
from custom_components.solar_energy_management.persisted_flags import (
    PERSISTED_FLAG_DEFAULTS,
)

KEY = "simulation_tab"
TODAY = date(2026, 10, 14)


# ── the switch ────────────────────────────────────────────────────────────

def _switch(options=None):
    desc = next(s for s in sw_mod.SWITCH_TYPES if s.key == KEY)
    coordinator = MagicMock()
    coordinator.config = {}
    entry = MagicMock()
    entry.options = dict(options or {})
    entry.data = {}
    coordinator.config_entry = entry
    sw = sw_mod.SEMSolarSwitch(coordinator, desc, "entry")
    sw.hass = MagicMock()
    sw.async_write_ha_state = MagicMock()
    return sw, coordinator, entry


def test_switch_is_config_and_defaults_off():
    desc = next(s for s in sw_mod.SWITCH_TYPES if s.key == KEY)
    assert str(desc.entity_category) == "config"
    assert desc.icon == "mdi:flask-outline"
    assert PERSISTED_FLAG_DEFAULTS[KEY] is False
    sw, _, _ = _switch()
    assert sw.is_on is False


@pytest.mark.asyncio
async def test_turn_on_persists_regenerates_once_and_notifies():
    sw, coordinator, entry = _switch()
    with patch.object(sw_mod, "regenerate_dashboard") as regen, \
            patch.object(sw_mod, "notify_simulation_tab") as note, \
            patch.object(day_tag_store, "start_backfill") as backfill:
        await sw.async_turn_on()
    opts = sw.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert opts[KEY] is True
    assert coordinator.config[KEY] is True
    regen.assert_called_once_with(sw.hass)
    note.assert_called_once_with(sw.hass, True)
    backfill.assert_called_once_with(sw.hass, coordinator)


@pytest.mark.asyncio
async def test_turn_off_persists_regenerates_and_stops_the_backfill():
    sw, coordinator, _ = _switch({KEY: True})
    with patch.object(sw_mod, "regenerate_dashboard") as regen, \
            patch.object(sw_mod, "notify_simulation_tab") as note, \
            patch.object(day_tag_store, "cancel_backfill") as cancel:
        await sw.async_turn_off()
    opts = sw.hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert opts[KEY] is False
    regen.assert_called_once_with(sw.hass)
    note.assert_called_once_with(sw.hass, False)
    cancel.assert_called_once_with(coordinator)


@pytest.mark.asyncio
async def test_other_switches_do_not_regenerate():
    desc = next(s for s in sw_mod.SWITCH_TYPES if s.key == "vacation_mode")
    coordinator = MagicMock()
    coordinator.config = {}
    coordinator.config_entry = MagicMock(options={}, data={})
    sw = sw_mod.SEMSolarSwitch(coordinator, desc, "entry")
    sw.hass = MagicMock()
    sw.async_write_ha_state = MagicMock()
    with patch.object(sw_mod, "regenerate_dashboard") as regen:
        await sw.async_turn_on()
    regen.assert_not_called()


def test_regenerate_skips_when_no_live_sem_dashboard():
    hass = MagicMock()
    hass.data = {}
    sw_mod.regenerate_dashboard(hass)
    hass.async_create_task.assert_not_called()


def test_regenerate_uses_the_generate_dashboard_service():
    hass = MagicMock()
    hass.data = {"lovelace": SimpleNamespace(dashboards={"sem-dashboard": object()})}
    sw_mod.regenerate_dashboard(hass)
    assert hass.async_create_task.call_count == 1
    hass.async_create_task.call_args.args[0].close()


# ── simulation_tab_on / day_tags_on ───────────────────────────────────────

def test_simulation_tab_on_reads_options_then_data_then_config():
    entry = SimpleNamespace(options={KEY: True}, data={KEY: False})
    assert simulation_tab_on(entry) is True
    entry = SimpleNamespace(options={}, data={KEY: True})
    assert simulation_tab_on(entry) is True
    coord = SimpleNamespace(config_entry=SimpleNamespace(options={}, data={}),
                            config={KEY: True})
    assert simulation_tab_on(coord) is True
    assert simulation_tab_on({KEY: True}) is True
    assert simulation_tab_on({}) is False
    assert simulation_tab_on(None) is False


@pytest.mark.parametrize("day_tags,sim,expected", [
    (False, False, False),
    (True, False, True),
    (False, True, True),
    (True, True, True),
])
def test_day_tags_on_truth_table(day_tags, sim, expected):
    coord = SimpleNamespace(config={"day_tags": day_tags, KEY: sim})
    assert day_tags_on(coord) is expected


# ── the hourly rule ───────────────────────────────────────────────────────

def _steady_5min():
    return [(h / 12.0, 5000.0) for h in range(24 * 12)]


def test_hourly_data_can_never_be_sunny():
    assert tag_sky(30.0, 30.0, 30.0, 0.01) == "sunny"
    assert tag_sky(30.0, 30.0, 30.0, 0.01, hourly=True) == "mixed"
    assert tag_day(date="d", solar=_steady_5min(), actual_kwh=30.0,
                   forecast_kwh=30.0, clear_sky_kwh=30.0).sky == "sunny"
    assert tag_day(date="d", solar=_steady_5min(), actual_kwh=30.0,
                   forecast_kwh=30.0, clear_sky_kwh=30.0,
                   hourly=True).sky == "mixed"


# ── the backfill ──────────────────────────────────────────────────────────

def _storage():
    st = SEMStorage.__new__(SEMStorage)
    st._daily_data = {}
    st._energy_data = {}
    st.saves = 0

    async def _save():
        st.saves += 1
    st.async_save_daily = _save
    st.get_session_history = lambda: []
    return st


def _rows(day, values, stat="change"):
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return [{"start": (start + timedelta(hours=h)).timestamp(), stat: v}
            for h, v in values.items()]


def _sunny_day(day, with_car=False):
    solar = {h: (0.0 if h < 7 or h > 18 else 3.0) for h in range(24)}
    out = {
        "sensor.sem_daily_solar_energy": _rows(day, solar),
        "sensor.sem_daily_grid_import_energy": _rows(day, {h: 0.2 for h in range(24)}),
        "sensor.sem_tariff_current_import_rate": _rows(
            day, {h: (0.05 if h == 3 else 0.30) for h in range(24)}, "mean"),
    }
    if with_car:
        out["sensor.sem_daily_ev_energy"] = _rows(day, {12: 4.0, 13: 4.0})
    return out


def _backfill_tagger(stats_by_day, storage=None, flag=True, gate=None):
    coord = SimpleNamespace(
        config={KEY: flag, "cheap_price_threshold": 0.10},
        _forecast_tracker=SimpleNamespace(_history=[]),
        _tracker_date=TODAY,
    )
    st = storage or _storage()
    calls = []

    async def _read(_hass, start, _end, entity_ids, types=None):
        calls.append(start)
        if gate is not None:
            await gate.wait()
        day = start.date()
        got = stats_by_day.get(day, {})
        if got is None:
            return None
        return {k: v for k, v in got.items() if k in set(entity_ids)}

    tg = DayTagger(SimpleNamespace(), coord, storage=st, read_stats=_read)
    tg._entity_id = lambda key: f"sensor.sem_{key}"
    return tg, st, calls


def test_backfill_tags_three_days_never_sunny_and_marks_the_source():
    days = [TODAY - timedelta(days=i) for i in (1, 2, 3)]
    stats = {d: _sunny_day(d, with_car=(d == days[0])) for d in days}
    tg, st, calls = _backfill_tagger(stats)
    stored = asyncio.run(tg.async_backfill(days=3))
    assert stored == 3
    tags = st.get_day_tags()
    assert [t["date"] for t in tags] == sorted(d.isoformat() for d in days)
    assert all(t["source"] == "backfill" for t in tags)
    assert all(t["sky"] != "sunny" for t in tags)
    assert all(t["prices"] == "cheap" for t in tags)
    assert tags[-1]["car"] is True and tags[0]["car"] is False
    # oldest first
    assert [c.date() for c in calls] == sorted(c.date() for c in calls)
    assert st.saves == 1


def test_backfill_skips_a_day_already_tagged():
    days = [TODAY - timedelta(days=i) for i in (1, 2)]
    st = _storage()
    st.put_day_tag({"date": days[0].isoformat(), "tags": ["grey"]})
    tg, st, calls = _backfill_tagger({d: _sunny_day(d) for d in days}, storage=st)
    assert asyncio.run(tg.async_backfill(days=2)) == 1
    assert [c.date() for c in calls] == [days[1]]
    kept = next(t for t in st.get_day_tags() if t["date"] == days[0].isoformat())
    assert kept == {"date": days[0].isoformat(), "tags": ["grey"]}


def test_backfill_is_capped_at_90_days():
    tg, st, calls = _backfill_tagger({})
    asyncio.run(tg.async_backfill(days=500))
    assert len(calls) == 90


def test_a_failed_read_stores_nothing():
    day = TODAY - timedelta(days=1)
    tg, st, _ = _backfill_tagger({day: None})
    assert asyncio.run(tg.async_backfill(days=1)) == 0
    assert st.get_day_tags() == []


def test_a_day_without_statistics_stores_nothing():
    tg, st, _ = _backfill_tagger({})
    assert asyncio.run(tg.async_backfill(days=2)) == 0
    assert st.get_day_tags() == []


def test_backfill_does_nothing_with_both_flags_off():
    day = TODAY - timedelta(days=1)
    tg, st, calls = _backfill_tagger({day: _sunny_day(day)}, flag=False)
    assert asyncio.run(tg.async_backfill(days=1)) == 0
    assert calls == []


def test_cancel_mid_run_leaves_no_task():
    days = [TODAY - timedelta(days=i) for i in (1, 2)]

    async def _run():
        gate = asyncio.Event()
        tg, st, _ = _backfill_tagger({d: _sunny_day(d) for d in days}, gate=gate)
        task = asyncio.ensure_future(tg.async_backfill(days=2))
        await asyncio.sleep(0)
        tg.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        return task, st

    task, st = asyncio.run(_run())
    assert task.done()
    assert st.get_day_tags() == []


def test_start_and_cancel_backfill_keep_the_unsub_on_the_coordinator():
    coord = SimpleNamespace(config={KEY: True})
    unsub = MagicMock()
    with patch("custom_components.solar_energy_management.coordinator."
               "recorder_history.run_after_start", return_value=unsub) as ras:
        day_tag_store.start_backfill(SimpleNamespace(), coord)
    assert ras.call_count == 1
    assert callable(coord._day_tag_backfill_cancel)
    day_tag_store.cancel_backfill(coord)
    unsub.assert_called_once()
    assert coord._day_tag_backfill_cancel is None
    day_tag_store.cancel_backfill(coord)  # twice is harmless
