"""(#1083) The Simulation tab's job: replay picked days in the background.

One job per coordinator (``coordinator._simulation_job``), one run at a
time, at most ``MAX_DAYS`` days. A run is ONE Home Assistant task that
walks the days oldest first: one hourly-statistics read per day (SEM's own
sensors, found in the entity registry), one ``HourlyDay``, one
``simulate_day``, one small row kept — then the day is dropped and the
loop yields to the event loop. Only one day's hours are ever held.

A run is one continuous period (``start_period``): a battery carries
energy from one day to the next, so picking single days would cut that
carry on every day. The days chain (``PeriodChain``); a gap of up to two
missing days is bridged, a longer one starts the pack again from the
recorded SOC. What the simulated pack gained more or less than the real
one is valued once per stretch, on its own line (``stored_energy``), and
the headline total says the difference with that value counted
(``net_delta``). Day types (sunny, grey, car …) filter the result; they
never change what is simulated.

The calibration check (#1083 accuracy). Before a what-if is believed, the
same days run with the install's OWN settings, in the same walk (one day
resident still). If that misses the real cost by more than
``CALIBRATION_REFUSE_PCT`` of the money moved, the result carries
``calibrated: false`` and the measured error, and the card shows that this
period cannot be simulated reliably instead of what-if numbers. Between
``CALIBRATION_MAX_PCT`` and that, the numbers show with the error beside them.

A day the recorder cannot answer for is skipped with a reason; it never
stops the run. The finished run (or what a stop left of it, flagged) goes
to the daily store under ``simulation_runs`` — never an entity attribute.
"""
from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import date as _date, timedelta
from typing import Any, Callable, Dict, Iterable, List, Optional

from ..analytics.simulation.battery_sim import (
    DEFAULT_EXPORT_RATE,
    DEFAULT_IMPORT_RATE,
    DEFAULTS_TAKEN,
    MODEL_DECISIONS,
    PeriodChain,
    SimParams,
    real_capacity_kwh,
)
from ..consts.battery_permissions import may_assist_ev
from ..analytics.simulation.hourly_day import (
    CORE_ROLES,
    GRID_EXPORT_BATTERY,
    HourlyDay,
)
from ..analytics.day_tags import without_restart_gap
from ..analytics.simulation.summary import summarise
from ..utils.helpers import BATTERY_SALE_SENSOR_KEY, solar_export
from .day_tag_store import (
    BACKFILL_DAYS,
    BACKFILL_ROLES,
    car_daily_entities,
    car_day_notes,
    car_rows,
    car_spans,
    simulation_tab_on,
)

_LOGGER = logging.getLogger(__name__)

#: at most this many days in one run (a year, one day resident)
MAX_DAYS = 365
#: the days the tab offers
OFFERED_DAYS = BACKFILL_DAYS
#: the own settings give back the real cost within this share of the money
#: moved (import cost + export revenue): the what-if stands without a note
CALIBRATION_MAX_PCT = 5.0
#: past this share no what-if is shown; between the two it is shown with the
#: measured error beside it (#1278: PROD sat at 5.3 % with the hourly
#: battery model 16 % short on discharge)
CALIBRATION_REFUSE_PCT = 10.0
#: (#1216) roles the run reads beside the day-tag roles: the pack's sale
SALE_ROLES = {GRID_EXPORT_BATTERY: BATTERY_SALE_SENSOR_KEY}


class SimulationError(Exception):
    """A refused start. ``code`` is ``busy`` or ``invalid``."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _kwp(cfg: Dict[str, Any]) -> Optional[float]:
    """The install's PV size (kWp) when the config knows it."""
    try:
        val = float(cfg.get("system_size_kwp") or 0.0)
    except (TypeError, ValueError):
        return None
    return val if val > 0 else None


def _day_detail(res) -> Dict[str, Any]:
    """What a person needs to see why a day differs: grid in and out,
    battery in and out, the pack's level at the day's end — actual and
    simulated — and the day's own short story."""
    if res is None:
        return {}
    a, s = res.actual, res.simulated
    rec_end = getattr(res, "recorded_end_kwh", None)
    out = {}
    for key in ("grid_import", "grid_export", "battery_charge",
                "battery_discharge"):
        out[f"actual_{key}_kwh"] = _r(a.get(key, 0.0), 1)
        out[f"simulated_{key}_kwh"] = _r(s.get(key, 0.0), 1)
    out.update({
        "actual_end_kwh": None if rec_end is None else _r(rec_end, 1),
        "simulated_end_kwh": _r(getattr(res, "end_kwh", 0.0), 1),
        "pack_change_kwh": _r(getattr(res, "pack_change_kwh", 0.0), 1),
        "pack_change_value": _r(getattr(res, "pack_change_value", 0.0)),
        "net_delta": _r(float(res.delta)
                        - float(getattr(res, "pack_change_value", 0.0))),
        "story": list(getattr(res, "story", []) or []),
    })
    return out


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
        "pv_factor": params.pv_factor,
        "battery_to_ev": params.battery_to_ev,
    }


def _r(value: float, nd: int = 2) -> float:
    return round(float(value or 0.0), nd)


def energy_totals(results: Iterable, sim_cap: float,
                  real_cap: float) -> Dict[str, Dict[str, float]]:
    """Actual against simulated over the days: grid in and out (kWh), money,
    self-consumption (% of the solar used on site) and battery cycles
    (throughput ÷ 2 ÷ capacity — a full charge and discharge is one).

    (#1216) Self-consumption takes only solar's export away from solar: a
    pack's sale is not solar sent out. A day with no recorded split of who
    exported counts all its export as solar's, as before."""
    out = {}
    for side, cap in (("actual", real_cap), ("simulated", sim_cap)):
        imp = exp = sale = solar = charge = dis = cost = 0.0
        for r in results:
            f = getattr(r, side)
            imp += float(f.get("grid_import", 0.0))
            exp += float(f.get("grid_export", 0.0))
            sale += float(f.get(GRID_EXPORT_BATTERY, 0.0) or 0.0)
            solar += float(f.get("solar", 0.0))
            charge += float(f.get("battery_charge", 0.0))
            dis += float(f.get("battery_discharge", 0.0))
            cost += float(getattr(r, f"{side}_cost"))
        own = (100.0 * max(0.0, solar - solar_export(exp, sale)) / solar
               if solar > 0 else None)
        out[side] = {
            "grid_import_kwh": _r(imp, 1), "grid_export_kwh": _r(exp, 1),
            "cost": _r(cost), "solar_kwh": _r(solar, 1),
            "self_consumption_pct": None if own is None else _r(own, 1),
            "battery_charge_kwh": _r(charge, 1),
            "battery_discharge_kwh": _r(dis, 1),
            "cycles": _r((charge + dis) / 2.0 / cap, 1) if cap > 0 else None,
        }
    return out


def month_rows(results: Iterable) -> List[Dict[str, Any]]:
    """The difference per month, oldest first. ``net_delta`` counts what
    the pack gained over each day (``pack_change_value``), so a month that
    filled a bigger pack is not shown dearer for energy the next month
    spends."""
    months: Dict[str, Dict[str, Any]] = {}
    for r in results:
        m = str(r.date)[:7]
        row = months.setdefault(m, {"month": m, "days": 0, "actual": 0.0,
                                    "simulated": 0.0, "delta": 0.0,
                                    "net_delta": 0.0})
        row["days"] += 1
        row["actual"] += float(r.actual_cost)
        row["simulated"] += float(r.simulated_cost)
        row["delta"] += float(r.delta)
        row["net_delta"] += float(r.delta) - float(
            getattr(r, "pack_change_value", 0.0))
    return [{k: (_r(v) if isinstance(v, float) else v) for k, v in row.items()}
            for _m, row in sorted(months.items())]


CAR_DAY_KWH = 0.5


class _Tally:
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


class Calibration(_Tally):
    """The own settings against the real cost, day by day. Days where a
    counter jumped are left out; the days with a car are also tallied alone."""

    def __init__(self) -> None:
        super().__init__()
        self.left_out = 0
        self.car = _Tally()

    def add(self, own) -> None:
        super().add(own)
        if float(own.actual.get("ev", 0.0)) >= CAR_DAY_KWH:
            self.car.add(own)

    def skip(self) -> None:
        self.left_out += 1

    def as_dict(self) -> Dict[str, Any]:
        err = self.error_pct
        car = self.car.error_pct
        return {
            "calibrated": err is not None and err <= CALIBRATION_REFUSE_PCT,
            "error_pct": None if err is None else round(err, 1),
            "max_pct": CALIBRATION_MAX_PCT,
            "refuse_pct": CALIBRATION_REFUSE_PCT,
            "days": self.days,
            "left_out": self.left_out,
            "car_days": self.car.days,
            "car_error_pct": None if car is None else round(car, 1),
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
            "max_charge_w": p.max_charge_w,
            "max_discharge_w": p.max_discharge_w,
            "system_size_kwp": _kwp(cfg),
            "pv_factor": 1.0,
            "battery_to_ev": may_assist_ev(cfg.get("battery_mode"),
                                           cfg.get("battery_permissions")),
            "currency": self._currency(),
        }

    def _tag_records(self) -> List[Dict[str, Any]]:
        storage = self.storage
        if storage is None:
            return []
        recs = [without_restart_gap(r) for r in storage.get_day_tags()
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

    def period_days(self, date_from: str, date_to: str) -> List[str]:
        """The stored days from ``date_from`` to ``date_to`` (both in),
        gap days left out. Raises ``SimulationError``."""
        try:
            lo = _date.fromisoformat(str(date_from))
            hi = _date.fromisoformat(str(date_to))
        except ValueError:
            raise SimulationError("invalid", "not a date") from None
        if hi < lo:
            raise SimulationError("invalid", "the period ends before it starts")
        if (hi - lo).days + 1 > MAX_DAYS:
            raise SimulationError("invalid", f"at most {MAX_DAYS} days")
        out = []
        for rec in self._tag_records():
            d = str(rec["date"])
            if lo.isoformat() <= d <= hi.isoformat() and not _is_gap(rec):
                out.append(d)
        if not out:
            raise SimulationError("invalid", "no recorded day in this period")
        return out

    def start_period(self, date_from: str, date_to: str,
                     params: SimParams) -> str:
        """Start a run over one continuous period; returns its id. Every
        stored day in it is simulated as one chain; a gap day is left out
        and the chain bridges it (up to two days) or starts again."""
        if self.running:
            raise SimulationError("busy", "a simulation is already running")
        if not simulation_tab_on(self.coordinator):
            raise SimulationError("off", "switch the Simulation tab on first")
        if self.storage is None:
            raise SimulationError("invalid", "SEM's store is not ready yet")
        dates = self.period_days(date_from, date_to)
        run_id = self.start(dates, params)
        self._run["period"] = {"from": str(date_from), "to": str(date_to)}
        return run_id

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
            "stored_energy": {"kwh": 0.0, "value": 0.0, "stretches": 0},
            "calibration": None,
            "period": {"from": wanted[0], "to": wanted[-1]},
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

    async def _car_spans(self, run, live: Dict[str, bool]):
        """(#1176) Each charger's first and last hour with a row over the
        run's period — read once per run. None when it cannot be read: the
        day's own rows decide then."""
        if not live or not isinstance(run, dict):
            return None
        if "_car_spans" in run:
            return run["_car_spans"]
        spans = None
        period = run.get("period") or {}
        try:
            from homeassistant.util import dt as dt_util
            first, last = sorted((_date.fromisoformat(str(period["from"])),
                                  _date.fromisoformat(str(period["to"]))))
            got = await self._read_stats(
                self.hass, dt_util.start_of_local_day(first),
                dt_util.start_of_local_day(last + timedelta(days=1)),
                set(live), {"change"})
            if got is not None:
                spans = car_spans(got, list(live))
            del got
        except (KeyError, ValueError, TypeError):
            spans = None
        run["_car_spans"] = spans
        return spans

    def _entity_ids(self) -> Dict[str, str]:
        out = {}
        keys = {role: key for role, (key, _stat) in BACKFILL_ROLES.items()}
        keys.update(SALE_ROLES)
        for role, key in keys.items():
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
        live = car_daily_entities(self.hass)
        car_ids = list(live)
        spans = await self._car_spans(run, live)
        stats = await self._read_stats(self.hass, start, end,
                                       set(ids.values()) | set(car_ids),
                                       {"change", "mean"})
        if stats is None:
            return "the recorder could not answer"
        rows = {role: stats.get(eid) or [] for role, eid in ids.items()}
        # (#1176) the car from its chargers' daily rows, which hold no reset
        rows["ev"] = car_rows(stats, car_ids, ids.get("ev"))
        doubt = car_day_notes(stats, live, start, end, spans)
        empty = [r for r in CORE_ROLES if not rows.get(r)]
        if empty:
            return "no hourly statistics for this day: " + ", ".join(empty)
        hourly = HourlyDay.from_statistics(rows, date=d, tags=tags, tz=tz,
                                           notes=doubt)
        del rows, stats
        chain, own, calib = run["_chains"]
        result = chain.add(hourly)
        own_res = own.add(hourly) if own is not None else result
        if hourly.counter_jumped:
            calib.skip()
        else:
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
        run.pop("_car_spans", None)     # (#1176) working data, not stored
        if chains is not None:
            chain, own, calib = chains
            chain.finish()
            if own is not None:
                own.finish()
            run["stored_energy"] = {
                "kwh": round(chain.stored_energy_kwh, 2),
                "value": round(chain.stored_energy_value, 2),
                "stretches": chain.stretches}
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
                **_day_detail(res),
            })

        def _short(t):
            return {"days": t["days"], "actual": t["actual_cost"],
                    "simulated": t["simulated_cost"], "delta": t["delta"],
                    "net_delta": t.get("net_delta", t["delta"])}

        o = summary["overall"]
        calib = run.get("calibration") or Calibration().as_dict()
        stored = dict(run.get("stored_energy")
                      or {"kwh": 0.0, "value": 0.0, "stretches": 0})
        params = run.get("params") or {}
        sim_cap = float(params.get("capacity_kwh") or 0.0)
        cfg = self.install_config
        real_cap = real_capacity_kwh(cfg, SimParams(
            capacity_kwh=sim_cap or 10.0, reserve_pct=0.0))
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
            "repriced": any(str(params.get(k)) != "recorded"
                            for k in ("import_rate", "export_rate")),
            "stored_energy": stored,
            "ev": {"moved_kwh": round(ev_moved, 2),
                   "not_delivered_kwh": round(ev_short, 2),
                   "not_delivered_value": round(ev_short_value, 2)},
            "days": days,
            "per_tag": {tag: _short(t) for tag, t in summary["by_tag"].items()},
            "total": {**_short(o), "kwh_over_limit": o["kwh_over_limit"],
                      "indicative_days": o["indicative_days"],
                      # the plain difference with the stored energy counted:
                      # what the what-if saves once the energy the pack still
                      # holds is valued (the headline)
                      "net_delta": round(float(o["delta"])
                                         - float(stored.get("value") or 0.0), 2)},
            "energy": energy_totals(results, sim_cap, real_cap),
            "months": month_rows(results),
            "period": dict(run.get("period") or {}),
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
