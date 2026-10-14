"""#1083 — the Simulation job and its websocket commands.

The job replays picked days in one background task: one hourly-statistics
read per day, one day held at a time, a failing day skipped with a reason,
a stop keeps what ran (flagged), the last 3 runs stored. The card talks to
it over seven websocket commands; every result says it is modelled.
"""
import asyncio
import base64
import copy
import gc
import io
import weakref
import zipfile
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from xml.etree import ElementTree as ET

import pytest

from custom_components.solar_energy_management import simulation_ws as ws
from custom_components.solar_energy_management.analytics.simulation import (
    hourly_day as hourly_mod,
)
from custom_components.solar_energy_management.analytics.simulation.battery_sim import (
    DEFAULTS_TAKEN,
    SimParams,
)
from custom_components.solar_energy_management.coordinator import (
    recorder_history,
    simulation_job as job_mod,
)
from custom_components.solar_energy_management.coordinator.simulation_job import (
    MAX_DAYS,
    SimulationError,
    SimulationJob,
)
from custom_components.solar_energy_management.coordinator.storage import SEMStorage

DATES = ["2026-10-10", "2026-10-11", "2026-10-12"]
CFG = {"simulation_tab": True,     # the one gate (review): off = no run
       "battery_capacity_kwh": 10.0, "battery_reserve_soc": 10.0,
       "electricity_import_rate": 0.30, "electricity_export_rate": 0.08,
       "target_peak_limit": 6.0}
SOLAR = {8: 0.3, 9: 1.0, 10: 2.0, 11: 3.0, 12: 3.5, 13: 3.5, 14: 3.0,
         15: 2.0, 16: 1.0, 17: 0.3}
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


# ── doubles ───────────────────────────────────────────────────────────

def _storage():
    st = SEMStorage.__new__(SEMStorage)
    st._daily_data = {}
    st._energy_data = {}
    st.saves = 0

    st.disk = None

    async def _save():
        st.saves += 1
        st.disk = copy.deepcopy(st._daily_data)
    st.async_save_daily = _save
    return st


def _tag(date, tags=("mixed",), gap=False, source=None):
    rec = {"date": date, "tags": list(tags) + (["gap"] if gap else []),
           "gap": gap}
    if source:
        rec["source"] = source
    return rec


def _hass():
    loop = asyncio.get_running_loop()
    hass = SimpleNamespace(config=SimpleNamespace(currency="CHF"))
    hass.async_create_background_task = lambda coro, name: loop.create_task(coro)
    hass.async_create_task = lambda coro: loop.create_task(coro)
    return hass


def _rows(date):
    """One day of hourly statistics for every role."""
    day = datetime.fromisoformat(date).replace(tzinfo=timezone.utc)
    out = {}
    for role, value in (("solar", None), ("grid_import", 0.1),
                        ("grid_export", 0.0), ("battery_charge", 0.0),
                        ("battery_discharge", 0.0), ("ev", 0.0),
                        ("home", 0.4)):
        out[f"sensor.sem_{role}"] = [
            {"start": day + timedelta(hours=h),
             "change": SOLAR.get(h, 0.0) if value is None else value}
            for h in range(24)]
    for role, value in (("soc", 50.0), ("import_rate", 0.30),
                        ("export_rate", 0.08)):
        out[f"sensor.sem_{role}"] = [
            {"start": day + timedelta(hours=h), "mean": value} for h in range(24)]
    return out


class FakeStats:
    """Stands in for ``read_hourly_statistics``: one call per day."""

    def __init__(self, fail=(), none=(), gate=None, hold=None):
        self.calls = []
        self.fail = set(fail)
        self.none = set(none)
        self.gate = gate
        self.hold = dict(hold or {})

    async def __call__(self, _hass, start, end, entity_ids, types):
        date = start.date().isoformat()
        self.calls.append((date, end - start, set(entity_ids), set(types)))
        if self.gate is not None:
            await self.gate.wait()
        if date in self.hold:
            await self.hold[date].wait()
        if date in self.fail:
            raise RuntimeError("database is locked")
        if date in self.none:
            return None
        return {eid: rows for eid, rows in _rows(date).items()
                if eid in entity_ids}


def _entity_id(key):
    role = {"daily_solar_energy": "solar",
            "daily_grid_import_energy": "grid_import",
            "daily_grid_export_energy": "grid_export",
            "daily_battery_charge_energy": "battery_charge",
            "daily_battery_discharge_energy": "battery_discharge",
            "daily_ev_energy": "ev", "daily_home_energy": "home",
            "battery_soc": "soc",
            "tariff_current_import_rate": "import_rate",
            "tariff_current_export_rate": "export_rate"}[key]
    return f"sensor.sem_{role}"


def _job(tags=None, stats=None, cfg=None):
    storage = _storage()
    for rec in tags if tags is not None else [_tag(d) for d in DATES]:
        storage.put_day_tag(rec)
    coordinator = SimpleNamespace(config=dict(CFG if cfg is None else cfg),
                                  _storage=storage)
    job = SimulationJob(_hass(), coordinator, read_stats=stats or FakeStats())
    job._entity_id = _entity_id          # the instance only: no registry here
    coordinator._simulation_job = job
    return job, storage, coordinator


def _params(**over):
    base = dict(capacity_kwh=10.0, reserve_pct=10.0)
    base.update(over)
    return SimParams(**base)


async def _finish(job):
    await job._task


# ── the job ───────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_three_days_three_rows_progress_done_and_stored():
    stats = FakeStats()
    job, storage, _ = _job(stats=stats)
    run_id = job.start(list(reversed(DATES)), _params())
    assert job.progress["running"] is True and job.progress["total"] == 3
    await _finish(job)
    p = job.progress
    assert (p["running"], p["status"], p["done"], p["total"], p["run_id"]) == (
        False, "done", 3, 3, run_id)
    # oldest first, one read per day, the whole local day, both statistics
    assert [c[0] for c in stats.calls] == DATES
    assert all(c[1] == timedelta(days=1) for c in stats.calls)
    assert all(c[3] == {"change", "mean"} for c in stats.calls)
    assert "sensor.sem_solar" in stats.calls[0][2]
    runs = storage.get_simulation_runs()
    assert len(runs) == 1 and storage.saves == 1
    run = runs[0]
    assert run["run_id"] == run_id and run["status"] == "done"
    assert run["finished_at"] and run["started_at"]
    assert run["params"]["capacity_kwh"] == 10.0
    res = run["result"]
    assert res["modelled"] is True and res["currency"] == "CHF"
    assert [d["date"] for d in res["days"]] == DATES
    row = res["days"][0]
    assert set(row) >= {"date", "tags", "actual_cost", "simulated_cost",
                        "delta", "stored_energy_value", "indicative", "reasons"}
    # the defaults every day takes are said once, not per day
    assert not set(row["reasons"]) & set(DEFAULTS_TAKEN)
    assert res["defaults_taken"] == list(DEFAULTS_TAKEN)
    assert res["per_tag"]["mixed"]["days"] == 3
    assert res["total"]["days"] == 3
    assert res["total"]["actual"] == pytest.approx(
        sum(d["actual_cost"] for d in res["days"]), abs=0.02)


@pytest.mark.asyncio
async def test_last_three_runs_kept():
    job, storage, _ = _job()
    ids = []
    for _ in range(4):
        ids.append(job.start(DATES[:1], _params()))
        await _finish(job)
    assert [r["run_id"] for r in storage.get_simulation_runs()] == ids[1:]
    assert job.run()["run_id"] == ids[-1]
    assert job.run(ids[1])["run_id"] == ids[1]
    assert job.run(ids[0]) is None


def test_storage_caps_day_rows_at_90():
    st = _storage()
    st.put_simulation_run({"run_id": "a", "result": {
        "days": [{"date": str(i)} for i in range(120)]}})
    assert len(st.get_simulation_runs()[0]["result"]["days"]) == 90


@pytest.mark.asyncio
async def test_a_second_start_is_refused_busy():
    gate = asyncio.Event()
    job, _, _ = _job(stats=FakeStats(gate=gate))
    job.start(DATES, _params())
    with pytest.raises(SimulationError) as err:
        job.start(DATES, _params())
    assert err.value.code == "busy"
    gate.set()
    await _finish(job)


@pytest.mark.asyncio
async def test_start_refuses_bad_picks():
    tags = [_tag(DATES[0]), _tag(DATES[1], gap=True)]
    job, _, _ = _job(tags=tags)
    for dates in ([], ["2026-01-01"], ["not-a-date"], [DATES[1]]):
        with pytest.raises(SimulationError) as err:
            job.start(dates, _params())
        assert err.value.code == "invalid"
    many = [(datetime(2026, 1, 1) + timedelta(days=i)).date().isoformat()
            for i in range(MAX_DAYS + 1)]
    with pytest.raises(SimulationError):
        job.start(many, _params())
    assert job.progress["running"] is False


@pytest.mark.asyncio
async def test_a_gap_day_runs_only_with_include_gaps():
    job, storage, _ = _job(tags=[_tag(DATES[0], gap=True)])
    with pytest.raises(SimulationError):
        job.start([DATES[0]], _params())
    job.start([DATES[0]], _params(), include_gaps=True)
    await _finish(job)
    row = storage.get_simulation_runs()[0]["result"]["days"][0]
    assert row["indicative"] is True
    assert "the day carries the gap tag" in row["reasons"]


@pytest.mark.asyncio
async def test_a_failing_day_is_skipped_with_a_reason():
    stats = FakeStats(fail={DATES[1]}, none={DATES[2]})
    job, storage, _ = _job(stats=stats)
    job.start(DATES, _params())
    await _finish(job)
    assert job.progress["status"] == "done" and job.progress["done"] == 3
    assert job.progress["skipped"] == 2
    res = storage.get_simulation_runs()[0]["result"]
    assert [d["date"] for d in res["days"]] == [DATES[0]]
    skipped = {s["date"]: s["reason"] for s in res["skipped"]}
    assert "database is locked" in skipped[DATES[1]]
    assert skipped[DATES[2]] == "the recorder could not answer"


@pytest.mark.asyncio
async def test_cancel_mid_run_keeps_what_ran_flagged():
    hold = asyncio.Event()
    stats = FakeStats(hold={DATES[1]: hold})
    job, storage, _ = _job(stats=stats)
    job.start(DATES, _params())
    while len(stats.calls) < 2:          # day 1 done, day 2 waiting
        await asyncio.sleep(0)
    assert job.progress["done"] == 1
    task = job._task
    assert job.cancel() is True
    assert job.progress["status"] == "cancelled"
    assert job.progress["running"] is False
    with pytest.raises(asyncio.CancelledError):
        await task
    assert task.done()
    await asyncio.sleep(0)               # the scheduled save
    run = storage.get_simulation_runs()[0]
    assert run["status"] == "cancelled" and run["cancelled"] is True
    assert [d["date"] for d in run["result"]["days"]] == [DATES[0]]
    assert storage.saves == 1
    assert job.cancel() is False         # nothing left to stop
    # a new run may start at once
    hold.set()
    job.start(DATES, _params())
    await _finish(job)
    assert len(storage.get_simulation_runs()) == 2


@pytest.mark.asyncio
async def test_unload_stops_the_run_and_saves_what_ran():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    hold = asyncio.Event()
    stats = FakeStats(hold={DATES[1]: hold})
    job, storage, coordinator = _job(stats=stats)
    coordinator._wpa_replay_unsub = None
    coordinator._day_tag_backfill_cancel = None
    job.start(DATES, _params())
    while len(stats.calls) < 2:
        await asyncio.sleep(0)
    task = job._task
    SEMCoordinator.cancel_pending_recorder_work(coordinator)
    await job.async_flush()              # what async_unload_entry awaits
    with pytest.raises(asyncio.CancelledError):
        await task
    assert storage.saves == 1
    # a reload reads the store from disk: the partial run is there
    reloaded = _storage()
    reloaded._daily_data = copy.deepcopy(storage.disk)
    run = reloaded.get_simulation_runs()[0]
    assert run["status"] == "cancelled"
    assert [d["date"] for d in run["result"]["days"]] == [DATES[0]]
    await job.async_flush()              # nothing new: no second save
    assert storage.saves == 1


def test_setup_registers_the_unload_stop_and_the_coordinator_owns_a_job():
    src = (job_mod.__file__.rsplit("/coordinator/", 1)[0])
    init = open(f"{src}/__init__.py", encoding="utf-8").read()
    assert "simulation_ws import async_register_websocket" in init
    assert "entry.async_on_unload(lambda: sim_job.cancel(persist=False))" in init
    unload = init[init.index("async def async_unload_entry"):]
    assert "await sim_job.async_flush()" in unload[:unload.index("\nasync def ")
                                                     if "\nasync def " in unload
                                                     else len(unload)]
    coord = open(f"{src}/coordinator/coordinator.py", encoding="utf-8").read()
    assert "self._simulation_job = SimulationJob(hass, self)" in coord


@pytest.mark.asyncio
async def test_one_day_resident():
    alive = weakref.WeakSet()
    peak = []
    real = hourly_mod.HourlyDay.from_statistics

    def counting(rows, **kw):
        gc.collect()
        peak.append(len(alive))
        day = real(rows, **kw)
        alive.add(day)
        return day

    job, _, _ = _job()
    with patch.object(job_mod.HourlyDay, "from_statistics", side_effect=counting):
        job.start(DATES, _params())
        await _finish(job)
    assert len(peak) == 3
    assert max(peak) == 0               # the day before was gone each time


@pytest.mark.asyncio
async def test_default_reader_is_read_hourly_statistics():
    stats = FakeStats()
    storage = _storage()
    storage.put_day_tag(_tag(DATES[0]))
    with patch.object(recorder_history, "read_hourly_statistics", stats):
        job = SimulationJob(_hass(), SimpleNamespace(config=dict(CFG),
                                                    _storage=storage))
    job._entity_id = _entity_id
    job.start([DATES[0]], _params())
    await _finish(job)
    assert [c[0] for c in stats.calls] == [DATES[0]]


@pytest.mark.asyncio
async def test_a_day_without_a_core_flow_is_skipped():
    class NoHome(FakeStats):
        async def __call__(self, *a):
            out = await super().__call__(*a)
            out.pop("sensor.sem_home", None)
            return out
    job, storage, _ = _job(stats=NoHome())
    job.start(DATES[:1], _params())
    await _finish(job)
    res = storage.get_simulation_runs()[0]["result"]
    assert res["days"] == [] and res["total"]["days"] == 0
    assert "home" in res["skipped"][0]["reason"]
    # and a core sensor missing from the registry
    job, storage, _ = _job()
    job._entity_id = lambda key: (None if key == "daily_grid_export_energy"
                                  else _entity_id(key))
    job.start(DATES[:1], _params())
    await _finish(job)
    res = storage.get_simulation_runs()[0]["result"]
    assert res["days"] == []
    assert "grid_export" in res["skipped"][0]["reason"]


@pytest.mark.asyncio
async def test_a_zero_import_rate_shows_zero():
    job, _, _ = _job(cfg={**CFG, "electricity_import_rate": 0.0})
    assert job.defaults()["import_rate"] == 0.0


@pytest.mark.asyncio
async def test_finish_clears_running_even_when_the_store_fails():
    job, storage, _ = _job()
    def _boom(_run):
        raise RuntimeError("store broken")
    storage.put_simulation_run = _boom
    job.start(DATES[:1], _params())
    with pytest.raises(RuntimeError):
        await _finish(job)
    assert job.progress["running"] is False
    assert job.running is False


@pytest.mark.asyncio
async def test_defaults_and_days():
    tags = [_tag(DATES[0], ("sunny",)), _tag(DATES[1], gap=True, source="backfill")]
    job, _, _ = _job(tags=tags)
    d = job.defaults()
    assert d == {"capacity_kwh": 10.0, "reserve_pct": 10.0, "peak_limit_kw": 6.0,
                 "import_rate": 0.30, "export_rate": 0.08, "currency": "CHF"}
    job2, _, _ = _job(cfg={"battery_capacity_kwh": 5.0})
    assert job2.defaults()["peak_limit_kw"] is None
    days = job.days()
    assert days["stored"] == 2 and days["gaps"] == 1
    assert days["days"][0] == {"date": DATES[0], "tags": ["sunny"],
                               "backfilled": False, "selectable": True}
    assert days["days"][1]["selectable"] is False
    assert days["days"][1]["backfilled"] is True


@pytest.mark.asyncio
async def test_days_offers_the_last_90():
    tags = [_tag((datetime(2026, 5, 1) + timedelta(days=i)).date().isoformat())
            for i in range(120)]
    job, _, _ = _job(tags=tags)
    days = job.days()["days"]
    assert len(days) == 90 and days[-1]["date"] == tags[-1]["date"]


# ── websocket ─────────────────────────────────────────────────────────

def _ws_hass(job):
    hass = MagicMock()
    entry = SimpleNamespace(entry_id="e1",
                            runtime_data=SimpleNamespace(_simulation_job=job))
    hass.config_entries.async_entries.return_value = [entry]
    return hass


def _call(handler, hass, **msg):
    conn = MagicMock()
    handler(hass, conn, {"id": 7, **msg})
    return conn


def _result(conn):
    conn.send_error.assert_not_called()
    msg_id, payload = conn.send_result.call_args.args
    assert msg_id == 7
    return payload


def _error(conn):
    conn.send_result.assert_not_called()
    return conn.send_error.call_args.args[1]


START = {"days": DATES, "params": {"capacity_kwh": 15, "reserve_pct": 20,
                                   "peak_limit_kw": None, "import_rate": 0.25,
                                   "export_rate": "recorded"}}


def test_command_names():
    assert ws.WS_DAYS == "solar_energy_management/simulation/days"
    assert {ws.WS_DEFAULTS, ws.WS_START, ws.WS_STATUS, ws.WS_CANCEL,
            ws.WS_RESULT, ws.WS_XLSX} == {
        f"solar_energy_management/simulation/{n}"
        for n in ("defaults", "start", "status", "cancel", "result", "xlsx")}


def test_registered():
    hass = MagicMock()
    hass.data = {}
    ws.async_register_websocket(hass)
    for name in (ws.WS_DAYS, ws.WS_DEFAULTS, ws.WS_START, ws.WS_STATUS,
                 ws.WS_CANCEL, ws.WS_RESULT, ws.WS_XLSX):
        assert name in hass.data["websocket_api"]


def test_no_sem_entry_is_not_found_for_every_command():
    hass = MagicMock()
    hass.config_entries.async_entries.return_value = []
    for handler, extra in ((ws.ws_days, {}), (ws.ws_defaults, {}),
                           (ws.ws_start, START), (ws.ws_status, {}),
                           (ws.ws_cancel, {}), (ws.ws_result, {}),
                           (ws.ws_xlsx, {})):
        assert _error(_call(handler, hass, **extra)) == "not_found"


@pytest.mark.asyncio
async def test_days_defaults_status_over_websocket():
    job, _, _ = _job(tags=[_tag(DATES[0]), _tag(DATES[1], gap=True)])
    hass = _ws_hass(job)
    days = _result(_call(ws.ws_days, hass))
    assert days["stored"] == 2 and days["gaps"] == 1
    assert _result(_call(ws.ws_defaults, hass))["capacity_kwh"] == 10.0
    status = _result(_call(ws.ws_status, hass))
    assert status == {"running": False, "run_id": None, "status": "idle",
                      "done": 0, "total": 0, "skipped": 0, "started_at": None,
                      "error": None}


@pytest.mark.asyncio
async def test_start_result_and_xlsx_over_websocket():
    job, _, _ = _job()
    hass = _ws_hass(job)
    run_id = _result(_call(ws.ws_start, hass, **START))["run_id"]
    assert _error(_call(ws.ws_start, hass, **START)) == "busy"
    await _finish(job)
    status = _result(_call(ws.ws_status, hass))
    assert status["done"] == status["total"] == 3 and status["run_id"] == run_id
    res = _result(_call(ws.ws_result, hass))
    assert res["modelled"] is True and res["run_id"] == run_id
    assert res["params"]["capacity_kwh"] == 15.0
    assert res["params"]["reserve_pct"] == 20.0
    assert res["params"]["peak_limit_kw"] is None
    assert res["params"]["import_rate"] == 0.25
    assert res["params"]["export_rate"] == "recorded"
    assert res["currency"] == "CHF" and len(res["days"]) == 3
    assert set(res) >= {"days", "per_tag", "total", "status", "started_at"}
    assert "result" not in res
    assert _result(_call(ws.ws_result, hass, run_id=run_id))["run_id"] == run_id
    assert _error(_call(ws.ws_result, hass, run_id="nope")) == "not_found"

    out = _result(_call(ws.ws_xlsx, hass))
    assert out["filename"] == f"sem-simulation-{res['started_at'][:10]}.xlsx"
    sheets = _read_xlsx(base64.b64decode(out["base64"]))
    assert list(sheets) == ["Days", "Totals"]
    head = sheets["Days"][0]
    assert head[0] == "Date" and head[-1] == "Indicative"
    assert all("(est.)" in h for h in head[3:6])
    assert "(est.)" not in head[2]
    assert len(sheets["Days"]) == 4
    first = sheets["Days"][1]
    assert first[0][0] == "n"                        # a date serial
    assert first[2] == ("n", res["days"][0]["actual_cost"])
    totals = sheets["Totals"]
    assert all("(est.)" in h for h in totals[0][3:5])
    assert totals[-1][0] == ("s", "total")
    assert totals[-1][1] == ("n", 3)
    assert [r[0][1] for r in totals[1:-1]] == ["mixed"]


@pytest.mark.asyncio
async def test_bad_params_are_invalid_and_cancel_answers():
    job, _, _ = _job()
    hass = _ws_hass(job)
    bad = {**START, "params": {**START["params"], "capacity_kwh": 0}}
    assert _error(_call(ws.ws_start, hass, **bad)) == "invalid"
    bad = {**START, "params": {**START["params"], "reserve_pct": 101}}
    assert _error(_call(ws.ws_start, hass, **bad)) == "invalid"
    assert _error(_call(ws.ws_start, hass, **{**START, "days": ["1999-01-01"]})) == "invalid"
    assert _result(_call(ws.ws_cancel, hass)) == {"cancelled": False}
    _result(_call(ws.ws_start, hass, **START))
    assert _result(_call(ws.ws_cancel, hass)) == {"cancelled": True}
    with pytest.raises(asyncio.CancelledError):
        await job._task


@pytest.mark.asyncio
async def test_bounds_and_booleans():
    job, _, _ = _job()
    hass = _ws_hass(job)
    for key, val in (("capacity_kwh", 0.5), ("capacity_kwh", 101),
                     ("reserve_pct", -1), ("reserve_pct", 101),
                     ("peak_limit_kw", -1)):
        bad = {**START, "params": {**START["params"], key: val}}
        assert _error(_call(ws.ws_start, hass, **bad)) == "invalid", (key, val)
    schema = ws.ws_start._ws_schema
    import voluptuous as vol
    with pytest.raises(vol.Invalid):
        schema({"type": ws.WS_START, "id": 1, "days": DATES,
                "params": {"capacity_kwh": True, "reserve_pct": 5}})
    with pytest.raises(vol.Invalid):
        schema({"type": ws.WS_START, "id": 1, "days": DATES,
                "params": {"capacity_kwh": 5, "reserve_pct": 5,
                           "import_rate": False}})
    # the edges are allowed
    edge = {**START, "params": {**START["params"], "capacity_kwh": 100,
                                "reserve_pct": 100, "peak_limit_kw": 0}}
    _result(_call(ws.ws_start, hass, **edge))
    await _finish(job)
    assert job.run()["params"]["peak_limit_kw"] is None


@pytest.mark.asyncio
async def test_unknown_run_id_while_runs_exist_and_an_all_skipped_xlsx():
    job, _, _ = _job(stats=FakeStats(none=set(DATES)))
    hass = _ws_hass(job)
    _result(_call(ws.ws_start, hass, **START))
    await _finish(job)
    assert _error(_call(ws.ws_result, hass, run_id="nope")) == "not_found"
    assert _error(_call(ws.ws_xlsx, hass, run_id="nope")) == "not_found"
    res = _result(_call(ws.ws_result, hass))
    assert res["days"] == [] and len(res["skipped"]) == 3
    sheets = _read_xlsx(base64.b64decode(_result(_call(ws.ws_xlsx, hass))["base64"]))
    assert len(sheets["Days"]) == 1                  # the header only
    assert sheets["Totals"][-1][:2] == [("s", "total"), ("n", 0)]


def test_start_schema_takes_the_documented_shape():
    schema = ws.ws_start._ws_schema
    out = schema({"type": ws.WS_START, "id": 1, **START})
    assert out["include_gaps"] is False
    out = schema({"type": ws.WS_START, "id": 1, "days": DATES,
                  "params": {"capacity_kwh": 5, "reserve_pct": 5}})
    assert out["params"]["import_rate"] == "recorded"


def _read_xlsx(data):
    """{sheet: rows of (type, value)}; header rows as plain text."""
    z = zipfile.ZipFile(io.BytesIO(data))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    names = [s.get("name") for s in wb.find("m:sheets", NS)]
    out = {}
    for i, name in enumerate(names, start=1):
        root = ET.fromstring(z.read(f"xl/worksheets/sheet{i}.xml"))
        rows = []
        for r in root.find("m:sheetData", NS):
            cells = []
            for c in r:
                t = c.get("t", "n")
                if t == "inlineStr":
                    cells.append(("s", "".join(c.find("m:is", NS).itertext())))
                elif t == "b":
                    cells.append(("b", c.find("m:v", NS).text == "1"))
                else:
                    v = float(c.find("m:v", NS).text)
                    cells.append(("n", int(v) if v.is_integer() else v))
            rows.append(cells)
        rows[0] = [c[1] for c in rows[0]]
        out[name] = rows
    return out


async def test_start_is_refused_while_the_tab_switch_is_off():
    """(review) The day-tag test flag alone makes tagged days exist; a
    direct websocket start must still be refused while the switch is off."""
    job, _storage, _coord = _job(cfg={**CFG, "simulation_tab": False})
    with pytest.raises(SimulationError) as err:
        job.start(DATES[:1], SimParams.from_config(CFG))
    assert err.value.code == "off"
    assert job.progress["status"] == "idle"
