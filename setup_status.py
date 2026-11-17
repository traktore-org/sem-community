"""(#1379) How SEM is set up: ONE reading for the AI tool and the dashboard.

``setup_facts`` is the shared, synchronous reading (``llm.build_setup_status``
adds the version and translated repair titles on top). ``build_setup_checklist``
turns the same facts into the first-run checklist the Home card draws; the
coordinator publishes it on the charger-control diag sensor, so no new entity
exists. Nothing here writes or derives a decision.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er, issue_registry as ir
from homeassistant.helpers.translation import async_get_translations

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

# Integrations that only compute or relabel; they name no hardware.
_NOT_HARDWARE = frozenset({DOMAIN, "template", "utility_meter", "derivative",
                           "integration", "group", "min_max"})


def open_issues(hass: HomeAssistant) -> list[ir.IssueEntry]:
    reg = ir.async_get(hass)
    return [i for i in reg.issues.values()
            if i.domain == DOMAIN and not i.dismissed_version]


async def issue_titles(hass: HomeAssistant, issues: list[ir.IssueEntry]) -> list[str]:
    if not issues:
        return []
    texts = await async_get_translations(
        hass, hass.config.language, "issues", [DOMAIN])
    prefix = f"component.{DOMAIN}.issues."
    return [texts.get(f"{prefix}{i.translation_key}.title") or i.issue_id
            for i in issues]


def forecast_part(coordinator: Any) -> dict[str, Any]:
    reader = getattr(coordinator, "_forecast_reader", None)
    out: dict[str, Any] = {"in_use": getattr(reader, "source", None)}
    try:
        rec = coordinator.source_recommendation()
    except Exception:  # noqa: BLE001 — advice is optional
        rec = None
    if rec:
        out["recommended"] = rec.get("source")
    return out


def tariff_configured(config: dict) -> bool:
    """A dynamic or calendar tariff, or a price the owner typed in."""
    if config.get("tariff_mode", "static") != "static":
        return True
    return config.get("electricity_import_rate") is not None


def setup_facts(hass: HomeAssistant, coordinator: Any) -> dict[str, Any]:
    """The reading both surfaces share. Reads only."""
    chargers = coordinator.config.get("ev_chargers") or []
    return {
        "watch_only": bool(getattr(coordinator, "_observer_mode", False)),
        "chargers": chargers,
        "forecast_source": forecast_part(coordinator),
        "tariff_configured": tariff_configured(coordinator.config),
        "issues": open_issues(hass),
    }


def _hardware_domains(hass: HomeAssistant, coordinator: Any) -> list[str]:
    """Integrations behind the entities SEM reads (what the crawler found)."""
    # (#1379) only what SEM reads as solar, grid and battery power: the
    # whole configured list also holds helpers, price and weather sources
    ed = getattr(getattr(coordinator, "_sensor_reader", None), "_energy_dashboard_config", None)
    eids = []
    for attr in ("solar_power", "grid_import_power", "grid_export_power", "grid_power",
                 "battery_power", "battery_power_from", "battery_power_to",
                 "grid_power_from", "grid_power_to"):
        v = getattr(ed, attr, None)
        if isinstance(v, str) and v:
            eids.append(v)
    # one entity per battery, combined sensors and pairs alike (#1171)
    from .ha_energy_reader import battery_units
    eids.extend(v for v in battery_units(ed) if isinstance(v, str) and v)
    if not eids:
        return []
    reg = er.async_get(hass)
    found = {getattr(reg.async_get(e), "platform", None) for e in eids}
    return sorted(p for p in found if isinstance(p, str) and p not in _NOT_HARDWARE)


def _detected_charger(coordinator: Any) -> str | None:
    """A charger the crawler found that SEM does not drive yet (same report
    the Configuration card's Detected hardware section draws)."""
    report = getattr(coordinator, "_detection_report", None)
    if not isinstance(report, dict):
        return None
    for row in report.get("chargers") or []:
        if isinstance(row, dict) and not row.get("configured"):
            return str(row.get("unit") or row.get("platform") or "")
    return None


def _item(key: str, done: bool, **extra: Any) -> dict[str, Any]:
    return {"key": key, "done": bool(done), **extra}


async def build_setup_checklist(hass: HomeAssistant, coordinator: Any) -> dict[str, Any]:
    """The first-run checklist. ``must_open`` is the only thing that keeps it
    on screen after SEM took control: a detected charger not yet set up."""
    facts = setup_facts(hass, coordinator)
    hardware = _hardware_domains(hass, coordinator)
    detected = _detected_charger(coordinator)
    configured = len(facts["chargers"])
    titles = await issue_titles(hass, facts["issues"])
    items = [
        _item("hardware", bool(hardware), brands=hardware),
        _item("dashboard", True),
        _item("charger", configured > 0, count=configured,
              detected=None if configured else detected),
        _item("forecast", bool(facts["forecast_source"].get("in_use")),
              recommended=facts["forecast_source"].get("recommended")),
        _item("price", facts["tariff_configured"]),
    ]
    return {
        "watch_only": facts["watch_only"],
        "items": items,
        "done": sum(1 for i in items if i["done"]),
        "total": len(items),
        "must_open": bool(detected) and configured == 0,
        "repairs": {"count": len(titles), "first": titles[0] if titles else None},
    }
