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
from collections.abc import Mapping
from typing import Any, Iterable, Optional

import voluptuous as vol
from homeassistant.components import websocket_api
from homeassistant.core import HomeAssistant, callback
from homeassistant.util import dt as dt_util
from homeassistant.util import slugify

from .charger_refs import REFS_KEY
from .const import DOMAIN
from .utils.device_names import charger_display_name
from .utils.xlsx import write_workbook

_LOGGER = logging.getLogger(__name__)

WS_SESSION_HISTORY = f"{DOMAIN}/session_history"
WS_SESSION_HISTORY_XLSX = f"{DOMAIN}/session_history/xlsx"

# The CSV columns, in this order. ``timestamp`` is the stored key for the
# start; the column says what it is. (#1410) ``charger`` is the name the
# user gave the charger, read when the file is made, so a rename shows; the
# stored id is in ``charger_id``, last, for a script that keys on it.
_NAME = "charger_name"   # filled from the config, never stored in a record

CSV_COLUMNS = (
    ("start", "timestamp"),
    ("end", "end"),
    ("charger", _NAME),
    ("energy_kwh", "energy_kwh"),
    ("solar_share_pct", "solar_share_pct"),
    ("cost", "cost"),
    ("currency", "currency"),
    ("duration_min", "duration_min"),
    ("energy_source", "energy_source"),
    # (#1088) the session's grid CO2, kg — last, so existing columns keep
    # their place; empty for sessions stored before
    ("co2_kg", "co2_kg"),
    ("charger_id", "charger_id"),
)


def _value(row: dict, key: str, names: Optional[Mapping]):
    """One cell's value. The charger column is the charger's name now; a
    charger no longer set up keeps its id, a record with no id stays
    empty."""
    if key != _NAME:
        return row.get(key)
    cid = row.get("charger_id")
    if cid is None:
        return None
    return (names or {}).get(cid) or cid


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
    if isinstance(value, str) and value[:1] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def sessions_csv(rows: Iterable[dict], names: Optional[Mapping] = None) -> str:
    """The rows as CSV text, header first, comma-safe, formula-safe.
    ``names`` maps a charger id to its name (``charger_names``)."""
    out = io.StringIO()
    writer = csv.writer(out, lineterminator="\n")
    writer.writerow([name for name, _ in CSV_COLUMNS])
    for row in rows:
        writer.writerow([_cell(_value(row, key, names)) for _, key in CSV_COLUMNS])
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


def sessions_xlsx(rows: Iterable[dict], names: Optional[Mapping] = None) -> bytes:
    """The rows as an .xlsx workbook: the CSV's columns, cells typed."""
    table = [[name for name, _ in CSV_COLUMNS]]
    for row in rows:
        table.append([_xlsx_value(key, _value(row, key, names))
                      for _, key in CSV_COLUMNS])
    return write_workbook([("Sessions", table)])


def _entry_for(hass: HomeAssistant, entry_id: Optional[str]):
    entries = hass.config_entries.async_entries(DOMAIN)
    if not entries:
        return None
    if entry_id:
        return next((e for e in entries if e.entry_id == entry_id), None)
    return entries[0]


def charger_names(hass: HomeAssistant, entry_id: Optional[str] = None) -> dict:
    """(#1410) Each set-up charger's id -> the name the user sees now.

    Read from the entry's saved charger list (options first: they are the
    live copy), with the id and name rules charger setup uses, so a rename
    shows in the next file. An install with no list has the one legacy
    charger setup builds from flat keys, id ``ev_charger``."""
    entry = _entry_for(hass, entry_id)
    if entry is None:
        return {}
    data = entry.data if isinstance(entry.data, Mapping) else {}
    options = entry.options if isinstance(entry.options, Mapping) else {}
    config = {**data, **options}
    chargers = config.get("ev_chargers")
    if not isinstance(chargers, list) or not chargers:
        # (review) setup builds the legacy charger only on an install that
        # never had a charger list, and only from its flat keys; once refs
        # exist an empty list means the last charger was removed
        if (REFS_KEY not in options
                and config.get("ev_charging_power_sensor")
                and (config.get("ev_charger_service")
                     or config.get("ev_current_control_entity"))):
            return {"ev_charger": charger_display_name(hass, None)}
        return {}
    names: dict = {}
    for idx, cfg in enumerate(chargers):
        if not isinstance(cfg, dict):
            continue
        cid = cfg.get("id") or f"ev_charger_{idx}"
        # setup uses the first charger with a doubled id; so does this
        names.setdefault(cid, charger_display_name(hass, cfg, idx))
    return names


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
    names = charger_names(hass, msg.get("entry_id"))
    data = sessions_xlsx(rows, names)
    connection.send_result(msg["id"], {
        "filename": _xlsx_filename(msg.get("charger_id"), names),
        "base64": base64.b64encode(data).decode("ascii"),
    })


def _name_slug(name) -> str:
    """A name as a file-name part, at most 60 characters; "" when slugify
    finds nothing it can write (it then gives "unknown")."""
    text = str(name or "").strip()
    if not text:
        return ""
    slug = slugify(text)
    if slug == "unknown" and text.casefold() != "unknown":
        return ""
    return slug[:60].strip("_")


def _xlsx_filename(charger_id: Optional[str], names: Mapping) -> str:
    """``sem-sessions-<charger>-<date>.xlsx``. (review) Two chargers must
    not download the same file name, so the charger part is there when
    one charger is asked for: (#1410) its name as a slug. Its id when it
    has no name left, or when another charger has the same name."""
    part = ""
    if charger_id:
        slug = _name_slug(names.get(charger_id))
        if slug and any(_name_slug(n) == slug
                        for cid, n in names.items() if cid != charger_id):
            slug = ""
        part = (slug or charger_id) + "-"
    return f"sem-sessions-{part}{dt_util.now().date().isoformat()}.xlsx"


@callback
def async_register_websocket(hass: HomeAssistant) -> None:
    """Register the commands. Idempotent: a reload overwrites the same slot."""
    websocket_api.async_register_command(hass, ws_session_history)
    websocket_api.async_register_command(hass, ws_session_history_xlsx)
