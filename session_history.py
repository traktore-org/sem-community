"""(#1024) The session list: one reader for the EV card and the CSV export.

SEM stores a finished charging session per charger (``ev_control.
_finished_session_record``). This module is the only way out of that
store: a websocket command the card calls, a CSV the export service
returns. Nothing here rides on an entity attribute — the recorder cap
(#979) stays untouched however long the list gets.
"""
from __future__ import annotations

import base64
import csv
import datetime as dt
import io
import logging
from typing import Any, Iterable, Optional

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util

from .const import DOMAIN
from .utils.xlsx import write_workbook

_LOGGER = logging.getLogger(__name__)

WS_SESSION_HISTORY = f"{DOMAIN}/session_history"
WS_SESSION_HISTORY_XLSX = f"{DOMAIN}/session_history/xlsx"

# The CSV columns, in this order. ``timestamp`` is the stored key for the
# start; the column says what it is.
CSV_COLUMNS = (
    ("start", "timestamp"),
    ("end", "end"),
    ("charger", "charger_id"),
    ("energy_kwh", "energy_kwh"),
    ("solar_share_pct", "solar_share_pct"),
    ("cost", "cost"),
    ("currency", "currency"),
    ("duration_min", "duration_min"),
    ("energy_source", "energy_source"),
)


def select_sessions(
    history: Iterable[dict],
    charger_id: Optional[str] = None,
    month: Optional[str] = None,
    since: Optional[str] = None,
) -> list:
    """Rows newest first, narrowed by charger, ``YYYY-MM`` month or a
    ``YYYY-MM-DD`` floor. A record without a start sorts last; an old
    record without a charger matches every charger filter — it was written
    before SEM knew which charger it was."""
    rows = []
    seen = set()
    for r in history:
        if not isinstance(r, dict):
            continue
        # Records written before 2.2 hold many sessions twice: the old
        # writer re-recorded a finished session on a later plug + unplug
        # with no charge. Show an exact double once; storage stays as is.
        ident = (r.get("timestamp"), r.get("charger_id"), r.get("energy_kwh"))
        if r.get("timestamp") is not None and ident in seen:
            continue
        seen.add(ident)
        rows.append(dict(r))
    if charger_id:
        rows = [r for r in rows if r.get("charger_id") in (charger_id, None)]
    if month:
        rows = [r for r in rows if str(r.get("timestamp") or "").startswith(month)]
    if since:
        rows = [r for r in rows if str(r.get("timestamp") or "")[:10] >= since]
    rows.sort(key=lambda r: str(r.get("timestamp") or ""), reverse=True)
    return rows


def _cell(value):
    """A text cell that a spreadsheet would run as a formula gets a leading
    quote; numbers pass as they are."""
    if value is None:
        return ""
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@"):
        return "'" + value
    return value


def sessions_csv(rows: Iterable[dict]) -> str:
    """The rows as CSV text, header first, comma-safe, formula-safe."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([name for name, _ in CSV_COLUMNS])
    for row in rows:
        writer.writerow([_cell(row.get(key)) for _, key in CSV_COLUMNS])
    return out.getvalue()


_DATE_KEYS = ("timestamp", "end")


def _xlsx_value(key: str, value):
    """A start or end becomes a datetime (wall clock as stored); the rest
    keeps its type, so numbers stay numbers."""
    if key in _DATE_KEYS and isinstance(value, str) and value:
        try:
            return dt.datetime.fromisoformat(value).replace(tzinfo=None)
        except ValueError:
            return value
    return value


def sessions_xlsx(rows: Iterable[dict]) -> bytes:
    """The rows as an .xlsx workbook: the CSV's columns, cells typed."""
    table = [[name for name, _ in CSV_COLUMNS]]
    for row in rows:
        table.append([_xlsx_value(key, row.get(key)) for _, key in CSV_COLUMNS])
    return write_workbook([("Sessions", table)])


def _entry_for(hass: HomeAssistant, entry_id: Optional[str]):
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    if entry_id:
        return next((e for e in entries if e.entry_id == entry_id), None)
    return entries[0]


def history_for(hass: HomeAssistant, entry_id: Optional[str] = None) -> Optional[list]:
    """The stored session list of one SEM entry, or None when there is no
    entry (or it has no coordinator yet)."""
    entry = _entry_for(hass, entry_id)
    coordinator = getattr(entry, "runtime_data", None) if entry else None
    storage = getattr(coordinator, "_storage", None)
    if storage is None:
        return None
    try:
        return list(storage.get_session_history() or [])
    except Exception:  # noqa: BLE001 — a half-built store answers "nothing"
        _LOGGER.debug("session history unreadable", exc_info=True)
        return []


@websocket_api.websocket_command({
    vol.Required("type"): WS_SESSION_HISTORY,
    vol.Optional("entry_id"): str,
    vol.Optional("charger_id"): str,
    vol.Optional("month"): str,
    vol.Optional("since"): str,
})
@callback
def ws_session_history(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """The card's read: rows newest first."""
    history = history_for(hass, msg.get("entry_id"))
    if history is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND,
                              "no SEM entry")
        return
    rows = select_sessions(history, charger_id=msg.get("charger_id"),
                           month=msg.get("month"), since=msg.get("since"))
    connection.send_result(msg["id"], {"rows": rows})


@websocket_api.websocket_command({
    vol.Required("type"): WS_SESSION_HISTORY_XLSX,
    vol.Optional("entry_id"): str,
    vol.Optional("charger_id"): str,
    vol.Optional("month"): str,
    vol.Optional("since"): str,
})
@callback
def ws_session_history_xlsx(hass: HomeAssistant, connection, msg: dict[str, Any]) -> None:
    """(#1083) The card's download: the same rows as an .xlsx, base64."""
    history = history_for(hass, msg.get("entry_id"))
    if history is None:
        connection.send_error(msg["id"], websocket_api.ERR_NOT_FOUND,
                              "no SEM entry")
        return
    rows = select_sessions(history, charger_id=msg.get("charger_id"),
                           month=msg.get("month"), since=msg.get("since"))
    data = sessions_xlsx(rows)
    connection.send_result(msg["id"], {
        # (review) two chargers must not download the same file name
        "filename": "sem-sessions-"
                    + (f"{msg.get('charger_id')}-" if msg.get("charger_id") else "")
                    + f"{dt_util.now().date().isoformat()}.xlsx",
        "base64": base64.b64encode(data).decode("ascii"),
    })


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands. Idempotent: a reload overwrites the same slot."""
    websocket_api.async_register_command(hass, ws_session_history)
    websocket_api.async_register_command(hass, ws_session_history_xlsx)
