"""(#1086) Draft a bug report for the SEM GitHub, for a person to post.

Nothing here sends anything or holds a token. It builds text and a
prefilled new-issue link; the owner opens the link and presses Submit.
Everything that goes in is scrubbed: tokens, emails, IP addresses,
coordinates, entity ids, and the owner's own configured entity ids.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any
from urllib.parse import quote, urlencode

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import __version__ as HA_VERSION
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from .const import DOMAIN
from .diagnostics import REDACT_CONFIG_KEYS

REPO = "traktore-org/sem-community"
NEW_ISSUE_URL = "https://github.com/traktore-org/sem-community/issues/new"
MAX_URL = 7500
MAX_TITLE = 60
MAX_TEXT = 2000
MAX_LOG_LINES = 10
MAX_LOG_CHARS = 300
NO_LOGS = "no recent SEM log entries available"
LOGGER_PREFIX = f"custom_components.{DOMAIN}"
_SECRET = "<removed>"

_ENTITY_DOMAINS = (
    "sensor|binary_sensor|switch|number|select|button|climate|weather|sun|"
    "input_number|input_boolean|input_select|input_text|device_tracker|"
    "light|lock|cover|fan|person|zone|calendar|time|datetime|update|notify"
)
_SCRUBS = (
    (re.compile(r"\beyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]*"), _SECRET),
    (re.compile(r"(?i)\b(bearer|token|api[_-]?key|password|secret)\b\s*[:=]?\s*\S+"),
     _SECRET),
    (re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+"), _SECRET),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), _SECRET),
    (re.compile(r"(?i)\b(?:[0-9a-f]{1,4}:){3,7}[0-9a-f]{1,4}\b"), _SECRET),
    (re.compile(r"-?\d{1,3}\.\d{3,}\s*[,;/]\s*-?\d{1,3}\.\d{3,}"), _SECRET),
    (re.compile(r"(?i)\b(lat(?:itude)?|lon(?:gitude)?|lng)\b\s*[:=]\s*-?\d+(?:\.\d+)?"),
     _SECRET),
    (re.compile(rf"\b(?:{_ENTITY_DOMAINS})\.[a-z0-9_]+\b"), "<entity>"),
    (re.compile(r"\b[A-Za-z0-9_-]{32,}\b"), _SECRET),
)


def configured_ids(config: dict) -> set[str]:
    """The owner's own entity ids and service names, from the config keys
    diagnostics.py redacts. Used to blank them wherever they appear."""
    found: set[str] = set()
    for key in REDACT_CONFIG_KEYS:
        values = [config.get(key)]
        for charger in config.get("ev_chargers") or []:
            if isinstance(charger, dict):
                values.append(charger.get(key))
        for value in values:
            found.update(v for v in (value if isinstance(value, (list, tuple))
                                     else [value]) if isinstance(v, str) and v)
    return found


def scrub(text: Any, own_ids: set[str] = frozenset()) -> str:
    out = str(text or "")
    for ident in sorted(own_ids, key=len, reverse=True):
        out = out.replace(ident, "<entity>")
    for pattern, repl in _SCRUBS:
        out = pattern.sub(repl, out)
    return out


def recent_sem_log_lines(hass: HomeAssistant, own_ids: set[str]) -> list[str]:
    """Newest WARNING/ERROR lines of SEM's own logger from system_log."""
    handler = hass.data.get("system_log")
    try:
        records = handler.records.to_list() if handler is not None else []
    except Exception:  # noqa: BLE001 — no log is not an error
        return []
    lines: list[str] = []
    for rec in records:
        if not str(rec.get("name", "")).startswith(LOGGER_PREFIX):
            continue
        if rec.get("level") not in ("WARNING", "ERROR", "CRITICAL"):
            continue
        messages = rec.get("message") or [""]
        stamp = datetime.fromtimestamp(
            float(rec.get("timestamp") or 0), timezone.utc).strftime("%H:%M:%S")
        text = scrub(messages[-1], own_ids).replace("\n", " ")[:MAX_LOG_CHARS]
        lines.append(f"{stamp} {rec['level']} {text}")
        if len(lines) >= MAX_LOG_LINES:
            break
    return lines


def _domain_of(hass: HomeAssistant, entity_id: Any) -> str | None:
    if not isinstance(entity_id, str) or not entity_id:
        return None
    entry = er.async_get(hass).async_get(entity_id)
    return str(entry.platform) if entry else None


def detected_hardware(hass: HomeAssistant, config: dict) -> dict[str, list[str]]:
    """Integration domains only, never ids."""
    inverter = {_domain_of(hass, config.get(k))
                for k in ("solar_power_sensor", "battery_power_sensor")}
    chargers = list(config.get("ev_chargers") or [])
    chargers = [c for c in chargers if isinstance(c, dict)] or [config]
    charger = set()
    for card in chargers:
        service = card.get("ev_charger_service")
        if isinstance(service, str) and "." in service:
            charger.add(service.split(".", 1)[0])
        charger.add(_domain_of(hass, card.get("ev_charging_power_sensor")))
    return {"inverter": sorted(d for d in inverter if d),
            "charger": sorted(d for d in charger if d)}


def _status_text(status: dict) -> str:
    safe = async_redact_data(dict(status), REDACT_CONFIG_KEYS)
    chargers = (safe.get("chargers") or {}).get("count", 0)
    rec = (safe.get("forecast_source") or {}).get("recommended")
    return "\n".join((
        f"- Watch-only: {'yes' if safe.get('watch_only') else 'no'}",
        f"- Chargers: {chargers}",
        f"- Battery seen: {'yes' if safe.get('battery_seen') else 'no'}",
        f"- Forecast source: {(safe.get('forecast_source') or {}).get('in_use')}"
        + (f" (recommended: {rec})" if rec else ""),
        f"- Tariff configured: {'yes' if safe.get('tariff_configured') else 'no'}",
        "- Open repairs: " + (", ".join(safe.get("open_repairs") or []) or "none"),
    ))


def _fields(status: dict, hw: dict, what: str, expected: str,
            status_text: str, logs: list[str], own: set[str]) -> dict[str, str]:
    """Fields in the order of .github/ISSUE_TEMPLATE/bug_report.yml. The two
    dropdowns (inverter, charger) cannot be prefilled by a label SEM does not
    own, so they ride in the diagnostics text and the owner picks them."""
    said = scrub(what, own)[:MAX_TEXT]
    if expected:
        said += f"\n\nExpected: {scrub(expected, own)[:MAX_TEXT]}"
    detected = (f"Detected inverter/battery: {', '.join(hw['inverter']) or 'unknown'}\n"
                f"Detected charger: {', '.join(hw['charger']) or 'unknown'}\n")
    return {
        "ha-version": HA_VERSION,
        "sem-version": str(status.get("version", "")),
        "inverter": ", ".join(hw["inverter"]) or "unknown",
        "charger": ", ".join(hw["charger"]) or "unknown",
        "description": said,
        "diagnostics": detected + status_text,
        "logs": "\n".join(logs) if logs else NO_LOGS,
    }


_HEADINGS = {
    "ha-version": "Home Assistant Version", "sem-version": "SEM Version",
    "inverter": "Inverter / Battery System", "charger": "EV Charger",
    "description": "What happened?", "diagnostics": "System Diagnostics",
    "logs": "Relevant log entries",
}


# Dropdowns cannot be prefilled by a label SEM does not own: body only.
_BODY_ONLY = ("inverter", "charger")
MAX_EXTRACT = 2000
CLOSING = "Prepared with SEM's report tool and checked by the reporter before posting."


def _section(key: str, text: str) -> str:
    if key == "logs":
        return f"```text\n{text}\n```"
    if key == "diagnostics":
        return ("<details><summary>Diagnostics extract</summary>\n\n```text\n"
                f"{text[:MAX_EXTRACT]}\n```\n\n</details>")
    return text


def _body(fields: dict[str, str]) -> str:
    parts = [f"### {heading}\n\n{_section(key, fields[key])}"
             for key, heading in _HEADINGS.items()]
    return "\n\n".join(parts + [CLOSING])


def _title(what: str, own: set[str]) -> str:
    line = (scrub(what, own).strip().splitlines() or [""])[0].strip()
    if len(line) > MAX_TITLE:
        line = line[:MAX_TITLE - 1].rsplit(" ", 1)[0].rstrip(" ,;:.-") + "…"
    return line or "SEM problem"


def _url(title: str, fields: dict[str, str]) -> str:
    shown = {k: v for k, v in fields.items() if k not in _BODY_ONLY}
    query = {"template": "bug_report.yml", "title": title, **shown}
    return f"{NEW_ISSUE_URL}?{urlencode(query, quote_via=quote)}"


def _fit_url(title: str, fields: dict[str, str], logs: list[str]) -> str:
    """Under MAX_URL: cut the log part first, then the diagnostics, then the text."""
    work = dict(fields)
    shown = list(logs)
    while len(_url(title, work)) > MAX_URL and shown:
        shown.pop()  # oldest line goes first
        work["logs"] = "\n".join(shown) if shown else NO_LOGS
    for key in ("diagnostics", "description"):
        while len(_url(title, work)) > MAX_URL and len(work[key]) > 40:
            work[key] = work[key][: len(work[key]) // 2] + "…"
    return _url(title, work)


NEXT_STEPS = [
    "Show the draft to the user. Post it only after they agree.",
    "On the web page (the link): pick the inverter and the charger.",
    "On the web page, attach the full diagnostics file (Settings → Devices & "
    "services → Solar Energy Management → ⋮ → Download diagnostics).",
    "Press Submit.",
]


def build_draft(hass: HomeAssistant, config: dict, status: dict,
                what_happened: str, expected: str = "") -> dict[str, Any]:
    own = configured_ids(config)
    logs = recent_sem_log_lines(hass, own)
    status = {k: v for k, v in status.items() if k != "chargers"} | {
        "chargers": {"count": (status.get("chargers") or {}).get("count", 0)}}
    fields = _fields(status, detected_hardware(hass, config), what_happened,
                     expected, _status_text(status), logs, own)
    title = _title(what_happened, own)
    return {"repo": REPO, "labels": ["bug"], "title": title,
            "body": _body(fields), "url": _fit_url(title, fields, logs), "next_steps": NEXT_STEPS}
