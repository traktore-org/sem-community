"""(#1083) The Simulation tab's job: replay picked days in the background.

One job per coordinator (``coordinator._simulation_job``), one run at a
time, at most ``MAX_DAYS`` days. A run is ONE Home Assistant task that
walks the days oldest first: one hourly-statistics read per day (SEM's own
sensors, found in the entity registry), one ``HourlyDay``, one
``simulate_day``, one small row kept — then the day is dropped and the
loop yields to the event loop. Only one day's hours are ever held.

The days chain: the simulated pack carries from one day to the next
(``PeriodChain``); a gap in the dates starts the pack again from the
recorded SOC. What the simulated pack holds more or less than the real
one at the end is valued once, on its own line (``stored_energy``).

The calibration check (#1083 accuracy). Before a what-if is believed, the
same days run with the install's OWN settings, in the same walk (one day
resident still). If that misses the real cost by more than
``CALIBRATION_MAX_PCT`` of the money moved, the result carries
``calibrated: false`` and the measured error, and the card shows that this
period cannot be simulated reliably instead of what-if numbers.

A day the recorder cannot answer for is skipped with a reason; it never
stops the run. The finished run (or what a stop left of it, flagged) goes
to the daily store under ``simulation_runs`` — never an entity attribute.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date as _date, timedelta
from typing import Any, Callable, Dict, List, Optional

from ..analytics.simulation.battery_sim import (
    DEFAULT_EXPORT_RATE,
    DEFAULT_IMPORT_RATE,
    DEFAULTS_TAKEN,
    MODEL_DECISIONS,
    PeriodChain,
    SimParams,
)
from ..analytics.simulation.hourly_day import CORE_ROLES, HourlyDay
from ..analytics.simulation.summary import summarise
from .day_tag_store import BACKFILL_DAYS, BACKFILL_ROLES, simulation_tab_on

_LOGGER = logging.getLogger(__name__)

#: at most this many days in one run (a year, one day resident)
MAX_DAYS = 365
#: the days the tab offers
OFFERED_DAYS = BACKFILL_DAYS
#: the own settings must give back the real cost within this share of the
#: money moved (import cost + export revenue), or no what-if is shown
CALIBRATION_MAX_PCT = 5.0


class SimulationError(Exception):
    """A refused start. ``code`` is ``busy`` or ``invalid``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _is_gap(record: Dict[str, Any]) -> bool:
    return bool(record.get("gap")) or "gap" in (record.get("tags") or [])


def _blank_progress() -> Dict[str, Any]:
    return {"running": False, "run_id": None, "status": "idle", "done": 0,
            "total": 0, "skipped": 0, "started_at": None, "error": None}


def params_dict(params: SimParams) -> Dict[str, Any]:
    return {
        "capacity_kwh": params.capacity_kwh,
        "reserve_pct": params.reserve_pct,
        "peak_limit_kw": params.peak_limit_kw,
        "import_rate": params.import_rate,
        "export_rate": params.export_rate,
        "max_charge_w": params.max_charge_w,
        "max_discharge_w": params.max_discharge_w,
        "roundtrip": params.roundtrip,
        "battery_mode": params.battery_mode,
        "ev_mode": params.ev_mode,
    }


class Calibration:
    """The own settings against the real cost, day by day."""

    def __init__(self) -> None:
        self.days = 0
        self.actual = 0.0
        self.simulated = 0.0
        self.moved = 0.0

    def add(self, own) -> None:
        a = own.actual
        self.days += 1
        self.actual += float(own.actual_cost)
        self.simulated += float(own.simulated_cost)
        self.moved += abs(float(a.get("import_cost", 0.0))) + abs(
            float(a.get("export_revenue", 0.0)))

    @property
    def error_pct(self) -> Optional[float]:
        if self.days == 0 or self.moved <= 0:
            return None
        return 100.0 * abs(self.simulated - self.actual) / self.moved

    def as_dict(self) -> Dict[str, Any]:
        err = self.error_pct
        return {
            "calibrated": err is not None and err <= CALIBRATION_MAX_PCT,
            "error_pct": None if err is None else round(err, 1),
            "max_pct": CALIBRATION_MAX_PCT,
            "days": self.days,
            "actual": round(self.actual, 2),
            "own_simulated": round(self.simulated, 2),
        }


class SimulationJob:
    """Runs one Simulation at a time for one coordinator."""

    def __init__(self, hass, coordinator, storage=None,
                 read_stats: Optional[Callable] = None) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._fixed_storage = storage
        if read_stats is None:
            from .recorder_history import read_hourly_statistics as _rh
            read_stats = _rh
        self._read_stats = read_stats
        self._task: Optional[asyncio.Task] = None
        self._run: Optional[Dict[str, Any]] = None
        self.progress: Dict[str, Any] = _blank_progress()
        #: a run record is in the store's memory but not on disk yet
        self._unsaved = False

    # ── what the form shows ───────────────────────────────────────────

    @property
    def storage(self):
        return self._fixed_storage or getattr(self.coordinator, "_storage", None)

    @property
    def install_config(self) -> Dict[str, Any]:
        cfg = getattr(self.coordinator, "config", None)
        return dict(cfg) if isinstance(cfg, dict) else {}

    def _currency(self) -> str:
        cur = getattr(getattr(self.hass, "config", None), "currency", None)
        return cur if isinstance(cur, str) else ""

    def defaults(self) -> Dict[str, Any]:
        """The form's current values: the install as configured."""
        cfg = self.install_config
        p = SimParams.from_config(cfg)
        export = cfg.get("electricity_export_rate")
        return {
            "capacity_kwh": p.capacity_kwh,
            "reserve_pct": p.reserve_pct,
            "peak_limit_kw": p.peak_limit_kw,
            "import_rate": float(cfg.get("electricity_import_rate",
                                         DEFAULT_IMPORT_RATE)),
            "export_rate": float(export if export is not None
                                 else DEFAULT_EXPORT_RATE),
            "battery_mode": str(cfg.get("battery_mode") or "auto"),
            "ev_mode": "recorded",
            "currency": self._currency(),
        }

    def _tag_records(self) -> List[Dict[str, Any]]:
        storage = self.storage
        if storage is None:
            return []
        recs = [r for r in storage.get_day_tags()
                if isinstance(r, dict) and r.get("date")]
        recs.sort(key=lambda r: str(r["date"]))
        return recs[-OFFERED_DAYS:]

    def days(self) -> Dict[str, Any]:
        """The tagged days on offer, oldest first; gap days not selectable."""
        out = []
        for rec in self._tag_records():
            gap = _is_gap(rec)
            out.append({
                "date": str(rec["date"]),
                "tags": [str(t) for t in (rec.get("tags") or [])],
                "backfilled": rec.get("source") == "backfill",
                "selectable": not gap,
            })
        return {"days": out, "stored": len(out),
                "gaps": sum(1 for d in out if not d["selectable"])}

    # ── a run ─────────────────────────────────────────────────────────

    @property
    def running(self) -> bool:
        return self._run is not None and self._run.get("status") == "running"

    def start(self, dates: List[str], params: SimParams,
              include_gaps: bool = False) -> str:
        """Start a run; returns its id. Raises ``SimulationError``."""
        if self.running:
            raise SimulationError("busy", "a simulation is already running")
        # (review) the switch is the one gate: a websocket call must not
        # start a recorder read and a decision replay while the tab is off
        if not simulation_tab_on(self.coordinator):
            raise SimulationError("off", "switch the Simulation tab on first")
        if self.storage is None:
            raise SimulationError("invalid", "SEM's store is not ready yet")
        if not isinstance(params, SimParams):
            raise SimulationError("invalid", "no simulation settings")
        wanted = sorted({str(d) for d in (dates or [])})
        if not wanted:
            raise SimulationError("invalid", "pick at least one day")
        if len(wanted) > MAX_DAYS:
            raise SimulationError("invalid", f"at most {MAX_DAYS} days")
        tagged = {str(r["date"]): r for r in self._tag_records()}
        for d in wanted:
            try:
                _date.fromisoformat(d)
            except ValueError:
                raise SimulationError("invalid", f"not a date: {d}") from None
            rec = tagged.get(d)
            if rec is None:
                raise SimulationError("invalid", f"{d} is not a recorded day")
            if _is_gap(rec) and not include_gaps:
                raise SimulationError("invalid", f"{d} has a gap in its data")
        from homeassistant.util import dt as dt_util
        started = dt_util.now().isoformat()
        run_id = uuid.uuid4().hex[:12]
        self._run = {
            "run_id": run_id, "started_at": started, "finished_at": None,
            "status": "running", "params": params_dict(params),
            "days": [], "results": [], "skipped": [],
            "stored_energy": {"kwh": 0.0, "value": 0.0},
            "calibration": None,
        }
        self.progress = {**_blank_progress(), "running": True,
                         "run_id": run_id, "status": "running",
                         "total": len(wanted), "started_at": started}
        tags = {d: [str(t) for t in (tagged[d].get("tags") or [])]
                for d in wanted}
        coro = self._walk(run_id, wanted, tags, params)
        create = getattr(self.hass, "async_create_background_task", None)
        if create is not None:
            self._task = create(coro, f"sem simulation {run_id}")
        else:
            self._task = self.hass.async_create_task(coro)
        return run_id

    async def _walk(self, run_id: str, dates: List[str],
                    tags: Dict[str, List[str]], params: SimParams) -> None:
        from homeassistant.util import dt as dt_util
        run = self._run
        progress = self.progress
        cfg = self.install_config
        tz = dt_util.get_default_time_zone()
        ids = self._entity_ids()
        chain = PeriodChain(params, cfg, MODEL_DECISIONS)
        own_params = SimParams.from_config(cfg)
        # the own settings, walked beside the what-if — the same chain
        # when the what-if IS the own settings
        own = None if params == own_params else PeriodChain(
            own_params, cfg, MODEL_DECISIONS)
        calib = Calibration()
        run["_chains"] = (chain, own, calib)
        try:
            for d in dates:
                reason = None
                try:
                    reason = await self._one_day(run, d, tags.get(d, []),
                                                 params, cfg, ids, tz)
                except asyncio.CancelledError:
                    raise
                except Exception as err:  # noqa: BLE001 — one day, not the run
                    _LOGGER.debug("simulation day %s failed", d, exc_info=True)
                    # CAUSE: `err` is the exception _one_day raised for this
                    # day, caught right here; its own text says what failed.
                    reason = f"could not simulate: {err}"
                if reason:
                    run["skipped"].append({"date": d, "reason": reason})
                    progress["skipped"] = len(run["skipped"])
                progress["done"] += 1
                await asyncio.sleep(0)
        except asyncio.CancelledError:
            self._finish(run, progress, "cancelled")
            raise
        except Exception as err:  # noqa: BLE001 — say so, keep what ran
            _LOGGER.warning("simulation run stopped: %s", err)
            progress["error"] = str(err)
            self._finish(run, progress, "failed")
            await self._save()
            return
        self._finish(run, progress, "done")
        await self._save()

    def _entity_ids(self) -> Dict[str, str]:
        out = {}
        for role, (key, _stat) in BACKFILL_ROLES.items():
            eid = self._entity_id(key)
            if eid:
                out[role] = eid
        return out

    def _entity_id(self, key: str) -> Optional[str]:
        try:
            from homeassistant.helpers import entity_registry as er
            from ..const import DOMAIN
            return er.async_get(self.hass).async_get_entity_id(
                "sensor", DOMAIN, f"sem_{key}")
        except Exception:  # noqa: BLE001 — no registry, no read
            return None

    async def _one_day(self, run, d: str, tags: List[str], params: SimParams,
                       cfg, ids: Dict[str, str], tz) -> Optional[str]:
        """Simulate one day into ``run``; a reason when it was skipped."""
        from homeassistant.util import dt as dt_util
        absent = [r for r in CORE_ROLES if r not in ids]
        if absent:
            return ("not in the entity registry: " + ", ".join(absent))
        day = _date.fromisoformat(d)
        start = dt_util.start_of_local_day(day)
        end = dt_util.start_of_local_day(day + timedelta(days=1))
        stats = await self._read_stats(self.hass, start, end,
                                       set(ids.values()), {"change", "mean"})
        if stats is None:
            return "the recorder could not answer"
        rows = {role: stats.get(eid) or [] for role, eid in ids.items()}
        empty = [r for r in CORE_ROLES if not rows.get(r)]
        if empty:
            return "no hourly statistics for this day: " + ", ".join(empty)
        hourly = HourlyDay.from_statistics(rows, date=d, tags=tags, tz=tz)
        del rows, stats
        chain, own, calib = run["_chains"]
        result = chain.add(hourly)
        own_res = own.add(hourly) if own is not None else result
        if not hourly.counters_disagree:
            calib.add(own_res)
        del hourly, own_res
        result.hours = []           # the hour rows are not kept
        run["results"].append(result)
        return None

    def _finish(self, run, progress, status: str) -> None:
        """Turn what ran into the stored record. Sync: a stop calls it.
        A second call for the same run does nothing."""
        if run is None or run.get("status") != "running":
            return
        run["status"] = status
        chains = run.pop("_chains", None)
        if chains is not None:
            chain, own, calib = chains
            chain.finish()
            if own is not None:
                own.finish()
            run["stored_energy"] = {
                "kwh": round(chain.stored_energy_kwh, 2),
                "value": round(chain.stored_energy_value, 2)}
            run["calibration"] = calib.as_dict()
        try:
            self._store(run, status)
        finally:
            run["results"] = []
            progress.update({"running": False, "status": status})

    def _store(self, run, status: str) -> None:
        from homeassistant.util import dt as dt_util
        run["finished_at"] = dt_util.now().isoformat()
        record = {
            "run_id": run["run_id"], "started_at": run["started_at"],
            "finished_at": run["finished_at"], "status": status,
            "cancelled": status == "cancelled",
            "params": run["params"],
            "result": self._result(run),
        }
        storage = self.storage
        if storage is not None:
            storage.put_simulation_run(record)
            self._unsaved = True

    def _result(self, run) -> Dict[str, Any]:
        results = run["results"]
        summary = summarise(results)
        extra = {r.date: r for r in results}
        days = []
        for row in summary["days"]:
            res = extra.get(row["date"])
            days.append({
                "date": row["date"], "tags": row["tags"],
                "actual_cost": row["actual_cost"],
                "simulated_cost": row["simulated_cost"],
                "delta": row["delta"],
                "kwh_over_limit": row["kwh_over_limit"],
                "ev_moved_kwh": round(
                    float(getattr(res, "ev_moved_kwh", 0.0)), 2),
                "ev_not_delivered_kwh": round(
                    float(getattr(res, "ev_not_delivered_kwh", 0.0)), 2),
                "indicative": row["indicative"],
                # the defaults every day takes are said once, below
                "reasons": [r for r in row["indicative_reasons"]
                            if r not in DEFAULTS_TAKEN],
            })

        def _short(t):
            return {"days": t["days"], "actual": t["actual_cost"],
                    "simulated": t["simulated_cost"], "delta": t["delta"]}

        o = summary["overall"]
        calib = run.get("calibration") or Calibration().as_dict()
        ev_moved = sum(float(getattr(r, "ev_moved_kwh", 0.0)) for r in results)
        ev_short = sum(float(getattr(r, "ev_not_delivered_kwh", 0.0))
                       for r in results)
        ev_short_value = sum(float(getattr(r, "ev_not_delivered_value", 0.0))
                             for r in results)
        return {
            "modelled": True,
            "currency": self._currency(),
            "calibrated": bool(calib.get("calibrated")),
            "calibration": calib,
            "stored_energy": dict(run.get("stored_energy")
                                  or {"kwh": 0.0, "value": 0.0}),
            "ev": {"moved_kwh": round(ev_moved, 2),
                   "not_delivered_kwh": round(ev_short, 2),
                   "not_delivered_value": round(ev_short_value, 2)},
            "days": days,
            "per_tag": {tag: _short(t) for tag, t in summary["by_tag"].items()},
            "total": {**_short(o), "kwh_over_limit": o["kwh_over_limit"],
                      "indicative_days": o["indicative_days"]},
            "skipped": list(run["skipped"]),
            "defaults_taken": list(DEFAULTS_TAKEN),
        }

    async def _save(self) -> None:
        storage = self.storage
        if storage is None:
            return
        self._unsaved = False
        try:
            await storage.async_save_daily()
        except Exception:  # noqa: BLE001 — the next save carries it
            self._unsaved = True
            _LOGGER.debug("simulation run saved later")

    async def async_flush(self) -> None:
        """Write a stored run that is not on disk yet (unload awaits this:
        the daily store is otherwise saved only when HA stops)."""
        if self._unsaved:
            await self._save()

    def cancel(self, persist: bool = True) -> bool:
        """Stop a running run now. What ran is kept, flagged ``cancelled``.
        ``persist`` also schedules a store save (not on unload)."""
        task = self._task
        if not self.running:
            return False
        if task is not None and not task.done():
            task.cancel()
        self._finish(self._run, self.progress, "cancelled")
        if persist and self.storage is not None:
            try:
                self.hass.async_create_task(self._save())
            except Exception:  # noqa: BLE001 — the next save carries it
                _LOGGER.debug("simulation stop saved later")
        return True

    def runs(self) -> List[Dict[str, Any]]:
        storage = self.storage
        return storage.get_simulation_runs() if storage is not None else []

    def run(self, run_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """A stored run by id, or the latest."""
        runs = self.runs()
        if not runs:
            return None
        if not run_id:
            return runs[-1]
        return next((r for r in runs if r.get("run_id") == run_id), None)
