"""(#1083) The Simulation tab's websocket commands.

The card asks over these; nothing rides on an entity attribute (#979).
Every result is modelled and says so (``"modelled": True``).
"""
from __future__ import annotations

import base64
import datetime as dt
from typing import Any, Optional

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback

from .analytics.simulation.battery_sim import SimParams
from .analytics.simulation.ev_retime import EV_MODE_CHOICES, RECORDED
from .consts.battery_modes import BATTERY_MODES
from .analytics.simulation.summary import SUMMARY_TAGS
from .const import DOMAIN
from .consts.bounds import BOUNDS
from .coordinator.simulation_job import SimulationError
from .utils.xlsx import write_workbook

WS_PREFIX = f"{DOMAIN}/simulation"
WS_DAYS = f"{WS_PREFIX}/days"
WS_DEFAULTS = f"{WS_PREFIX}/defaults"
WS_START = f"{WS_PREFIX}/start"
WS_STATUS = f"{WS_PREFIX}/status"
WS_CANCEL = f"{WS_PREFIX}/cancel"
WS_RESULT = f"{WS_PREFIX}/result"
WS_XLSX = f"{WS_PREFIX}/xlsx"

ERR_BUSY = "busy"
ERR_INVALID = "invalid"

def _number(value):
    """A JSON number; a boolean is not one (True would be 1 kWh)."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise vol.Invalid("expected a number")
    return value


_NUMBER = _number
_RATE = vol.Any("recorded", _number)
_CAP = BOUNDS["battery_capacity_kwh"]
EST = " (est.)"


def _job(hass: HomeAssistant, entry_id: Optional[str]):
    entries = hass.config_entries.async_entries(DOMAIN)
    if entry_id:
        entries = [e for e in entries if e.entry_id == entry_id]
    entry = entries[0] if entries else None
    coordinator = getattr(entry, "runtime_data", None) if entry else None
    return getattr(coordinator, "_simulation_job", None)


def _no_job(connection, msg) -> None:
    connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no SEM entry")


def _params(job, raw: dict) -> SimParams:
    """The form's values on top of the install's config."""
    cap = float(raw["capacity_kwh"])
    reserve = float(raw["reserve_pct"])
    peak = raw.get("peak_limit_kw")
    peak = float(peak) if peak is not None else None
    if not _CAP.min <= cap <= _CAP.max:
        raise SimulationError(
            ERR_INVALID, f"capacity must be {_CAP.min:g}–{_CAP.max:g} kWh")
    if not 0 <= reserve <= 100:
        raise SimulationError(ERR_INVALID, "reserve must be 0–100 %")
    if peak is not None and peak < 0:
        raise SimulationError(ERR_INVALID, "peak limit must be 0 kW or more")
    rates = {}
    for key in ("import_rate", "export_rate"):
        val = raw.get(key, "recorded")
        rates[key] = val if val == "recorded" else float(val)
    cfg = job.install_config
    mode = raw.get("battery_mode")
    # the configured mode is no change: None keeps the own settings equal
    if not mode or mode == str(cfg.get("battery_mode") or "auto"):
        mode = None
    return SimParams.from_config(cfg, capacity_kwh=cap,
                                 reserve_pct=reserve,
                                 peak_limit_kw=peak or None,
                                 battery_mode=mode,
                                 ev_mode=str(raw.get("ev_mode") or RECORDED),
                                 **rates)


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_DAYS,
    vol.Optional("entry_id"): str,
})
@callback
def ws_days(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The tagged days on offer."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    connection.send_result(msg["id"], job.days())


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_DEFAULTS,
    vol.Optional("entry_id"): str,
})
@callback
def ws_defaults(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The form's current values."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    connection.send_result(msg["id"], job.defaults())


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_START,
    vol.Optional("entry_id"): str,
    vol.Required("days"): [str],
    vol.Required("params"): {
        vol.Required("capacity_kwh"): _NUMBER,
        vol.Required("reserve_pct"): _NUMBER,
        vol.Optional("peak_limit_kw"): vol.Any(None, _NUMBER),
        vol.Optional("import_rate", default="recorded"): _RATE,
        vol.Optional("export_rate", default="recorded"): _RATE,
        vol.Optional("battery_mode"): vol.Any(None, vol.In(list(BATTERY_MODES))),
        vol.Optional("ev_mode", default=RECORDED): vol.In(list(EV_MODE_CHOICES)),
    },
    vol.Optional("include_gaps", default=False): bool,
})
@callback
def ws_start(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Start a run: ``{"run_id"}``, or the error ``busy`` / ``invalid``."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    try:
        params = _params(job, msg["params"])
        run_id = job.start(msg["days"], params,
                           include_gaps=bool(msg.get("include_gaps")))
    except SimulationError as err:
        connection.send_error(msg["id"], err.code, str(err))
        return
    connection.send_result(msg["id"], {"run_id": run_id})


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_STATUS,
    vol.Optional("entry_id"): str,
})
@callback
def ws_status(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The progress of the current (or last) run."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    connection.send_result(msg["id"], dict(job.progress))


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_CANCEL,
    vol.Optional("entry_id"): str,
})
@callback
def ws_cancel(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """Stop the running run; what ran is kept, flagged."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    connection.send_result(msg["id"], {"cancelled": job.cancel()})


def result_payload(run: dict) -> dict:
    """A stored run, flat, marked modelled."""
    out = {k: v for k, v in run.items() if k != "result"}
    out.update(run.get("result") or {})
    out["modelled"] = True
    return out


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_RESULT,
    vol.Optional("entry_id"): str,
    vol.Optional("run_id"): str,
})
@callback
def ws_result(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """A stored run (the latest when no ``run_id``)."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    run = job.run(msg.get("run_id"))
    if run is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no such run")
        return
    connection.send_result(msg["id"], result_payload(run))


def _day(value: str):
    try:
        return dt.date.fromisoformat(value)
    except (TypeError, ValueError):
        return value


def run_xlsx(run: dict) -> bytes:
    """Two sheets: one row per day, and the totals per day type."""
    res = run.get("result") or {}
    cur = res.get("currency") or ""
    money = f" ({cur})" if cur else ""
    days = [["Date", "Tags", f"Actual cost{money}",
             f"Simulated cost{money}{EST}", f"Delta{money}{EST}",
             f"Car kWh moved{EST}", f"Car kWh not delivered{EST}",
             "Indicative"]]
    for row in res.get("days") or []:
        days.append([_day(row.get("date")), ", ".join(row.get("tags") or []),
                     row.get("actual_cost"), row.get("simulated_cost"),
                     row.get("delta"), row.get("ev_moved_kwh", 0.0),
                     row.get("ev_not_delivered_kwh", 0.0),
                     bool(row.get("indicative"))])
    totals = [["Day type", "Days", f"Actual cost{money}",
               f"Simulated cost{money}{EST}", f"Delta{money}{EST}"]]
    per_tag = res.get("per_tag") or {}
    for tag in SUMMARY_TAGS:
        t = per_tag.get(tag)
        if t and t.get("days"):
            totals.append([tag, t["days"], t["actual"], t["simulated"], t["delta"]])
    t = res.get("total") or {}
    totals.append(["total", t.get("days", 0), t.get("actual", 0.0),
                   t.get("simulated", 0.0), t.get("delta", 0.0)])
    stored = res.get("stored_energy") or {}
    calib = res.get("calibration") or {}
    ev = res.get("ev") or {}
    notes = [["What", "Value"],
             [f"Energy in the battery at the end, kWh{EST}", stored.get("kwh")],
             [f"Energy in the battery at the end{money}{EST}", stored.get("value")],
             ["Own settings against the real cost, % off", calib.get("error_pct")],
             ["Own settings reproduce the real cost", calib.get("calibrated")],
             [f"Car kWh moved{EST}", ev.get("moved_kwh")],
             [f"Car kWh not delivered{EST}", ev.get("not_delivered_kwh")]]
    return write_workbook([("Days", days), ("Totals", totals), ("Notes", notes)])


@websocket_api.require_admin
@websocket_api.websocket_command({
    vol.Required("type"): WS_XLSX,
    vol.Optional("entry_id"): str,
    vol.Optional("run_id"): str,
})
@callback
def ws_xlsx(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """A stored run as an .xlsx, base64."""
    job = _job(hass, msg.get("entry_id"))
    if job is None:
        _no_job(connection, msg)
        return
    run = job.run(msg.get("run_id"))
    if run is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND, "no such run")
        return
    stamp = str(run.get("started_at") or "")[:10] or "run"
    connection.send_result(msg["id"], {
        "filename": f"sem-simulation-{stamp}.xlsx",
        "base64": base64.b64encode(run_xlsx(run)).decode("ascii"),
    })


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands. Idempotent: a reload overwrites the same slot."""
    for handler in (ws_days, ws_defaults, ws_start, ws_status, ws_cancel,
                    ws_result, ws_xlsx):
        websocket_api.async_register_command(hass, handler)


