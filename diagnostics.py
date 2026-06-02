"""Diagnostics support for Solar Energy Management."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import SEMCoordinator

_LOGGER = logging.getLogger(__name__)

# Recent-log surface (v1.6.11). When users report a bug via "Copy
# diagnostics", the dump now also includes the last few SEM-related
# log lines so we can see what was actually happening at the time
# without asking the reporter for a separate ``ha core logs`` dump.
#
# Defensive caps — the diagnostics dump is shown in the user's
# clipboard / a GitHub issue, so we don't want it to balloon and we
# don't want to crash on log files that have grown unbounded.
_LOG_TAIL_KB = 2048           # only read the last 2 MB of the log
_LOG_MAX_LINES = 80           # return up to 80 matching lines
_LOG_NEEDLE = "solar_energy_management"


async def _get_recent_sem_logs(hass: HomeAssistant) -> list[str]:
    """Return the most recent SEM-related lines from ``home-assistant.log``.

    Tails the file (up to ``_LOG_TAIL_KB``), filters for
    ``solar_energy_management`` mentions, and returns the last
    ``_LOG_MAX_LINES`` matches in order.

    Returns a one-line placeholder explaining why if the file isn't
    accessible — most commonly that's a Home Assistant Supervisor
    install where logs go to journald rather than a flat file (the
    user can still attach ``ha core logs`` output separately). Never
    raises: a failure here must not break the rest of the diagnostics
    dump.
    """
    try:
        log_path = Path(hass.config.config_dir) / "home-assistant.log"
        if not log_path.exists():
            return [
                "<no flat log file at .storage parent — Supervisor "
                "installs use journald; please paste output of "
                "`ha core logs | grep solar_energy_management | tail -80`>"
            ]

        def _read_tail() -> list[str]:
            with open(log_path, "rb") as f:
                f.seek(0, 2)
                size = f.tell()
                start = max(0, size - _LOG_TAIL_KB * 1024)
                f.seek(start)
                if start > 0:
                    f.readline()  # discard the partial first line
                payload = f.read().decode("utf-8", errors="replace")
            sem_lines = [
                line for line in payload.splitlines()
                if _LOG_NEEDLE in line
            ]
            return sem_lines[-_LOG_MAX_LINES:]

        return await hass.async_add_executor_job(_read_tail)
    except Exception as e:  # pragma: no cover - defensive only
        _LOGGER.debug("Failed to read recent SEM logs for diagnostics: %s", e)
        return [f"<failed to read logs: {e!r}>"]

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

# Config keys that could contain user-specific entity IDs (not secrets, but privacy)
REDACT_CONFIG_KEYS = {
    "ev_connected_sensor",
    "ev_charging_sensor",
    "ev_charging_power_sensor",
    "ev_charger_service",
    "ev_charger_service_entity_id",
    "ev_daily_energy_sensor",
    "vehicle_soc_entity",
    "battery_discharge_control_entity",
}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SEMConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SEMCoordinator = entry.runtime_data
    data = coordinator.data if coordinator.data else {}

    # Load manager info
    load_mgr = getattr(coordinator, "_load_manager", None)
    load_info = {}
    if load_mgr:
        lm_data = load_mgr.get_load_management_data()
        devices = lm_data.get("devices", {})
        load_info = {
            "enabled": load_mgr.is_enabled(),
            "device_count": len(devices),
            "devices": {
                did: {
                    "type": info.get("device_type"),
                    "is_controllable": info.get("is_controllable"),
                    "is_critical": info.get("is_critical"),
                    "priority": info.get("priority"),
                    "is_on": info.get("is_on"),
                    "current_power": info.get("current_power", 0),
                }
                for did, info in devices.items()
            },
        }

    # Energy dashboard config
    ed_config = getattr(coordinator, "_energy_dashboard_config", None)
    ed_info = {}
    if ed_config:
        # Resolved power sensors + where each came from. "derived" means it was
        # recovered from the energy sensor's device because the Energy Dashboard
        # had no stat_rate power link (#250); "stat_rate" means HA had it; None
        # means no power sensor — that source reads 0. Makes "all values are 0"
        # reports diagnosable at a glance.
        derived = getattr(ed_config, "derived_power", {}) or {}

        def _power_source(kind: str, entity_id) -> str | None:
            if kind in derived:
                return "derived"
            return "stat_rate" if entity_id else None

        # Per-source sensor lists (#378 diagnostic gap). The cached single
        # ``solar_power`` / ``battery_power`` / ``grid_import_power`` field
        # is the PRIMARY entity SEM reads, but for multi-inverter /
        # multi-battery / multi-grid setups the ACTUAL aggregated value
        # comes from the ``*_list`` fields — each entity in the list is
        # read and summed. If a user reports "fleet sensor underreports",
        # the gap is almost always either:
        #   (a) the list is missing an entity (autodiscovery missed it,
        #       or HA Energy Dashboard config doesn't include it), or
        #   (b) one of the entities is unavailable / returns non-numeric.
        # Capturing the lists + each entity's current state makes the
        # triage one-shot from the diagnostics dump alone.
        def _read_state(eid):
            if not eid:
                return None
            s = hass.states.get(eid)
            if s is None:
                return {"state": "missing"}
            return {"state": s.state, "unit": s.attributes.get("unit_of_measurement")}

        per_source_lists = {
            "solar_power_list": list(getattr(ed_config, "solar_power_list", []) or []),
            "battery_power_list": list(getattr(ed_config, "battery_power_list", []) or []),
            "grid_power_list": list(getattr(ed_config, "grid_power_list", []) or []),
        }
        per_source_readings = {
            "solar": {eid: _read_state(eid) for eid in per_source_lists["solar_power_list"]},
            "battery": {eid: _read_state(eid) for eid in per_source_lists["battery_power_list"]},
            "grid": {eid: _read_state(eid) for eid in per_source_lists["grid_power_list"]},
        }

        ed_info = {
            "has_solar": ed_config.has_solar,
            "has_grid": ed_config.has_grid,
            "has_battery": ed_config.has_battery,
            "has_ev": ed_config.has_ev,
            "device_count": len(ed_config.device_consumption),
            "power_sensors": {
                "solar": ed_config.solar_power,
                "grid": ed_config.grid_import_power,
                "battery": ed_config.battery_power,
            },
            "power_source": {
                "solar": _power_source("solar", ed_config.solar_power),
                "grid": _power_source("grid", ed_config.grid_import_power),
                "battery": _power_source("battery", ed_config.battery_power),
            },
            "per_source_lists": per_source_lists,
            "per_source_readings": per_source_readings,
            "energy_sensors": {
                "solar": ed_config.solar_energy,
                "grid_import": ed_config.grid_import_energy,
                "grid_export": ed_config.grid_export_energy,
                "battery_charge": ed_config.battery_charge_energy,
                "battery_discharge": ed_config.battery_discharge_energy,
            },
        }

    # Split-grid discovery state (issue #166): surface which import/export
    # sensors auto-discovery picked and how confident it is. A "split-lowconf"
    # value means same-device filtering failed and re-discovery is still active.
    reader = getattr(coordinator, "_sensor_reader", None)
    disc = getattr(reader, "_split_grid_discovery", None) if reader else None
    split_grid_info = {}
    if disc:
        grid_device_resolved = None
        if reader and ed_config and getattr(ed_config, "grid_import_energy", None):
            try:
                grid_device_resolved = bool(
                    reader._get_device_for_entity(ed_config.grid_import_energy)
                )
            except Exception:
                grid_device_resolved = None
        split_grid_info = {
            "import_sensor": disc.get("import"),
            "export_sensor": disc.get("export"),
            "confidence": disc.get("confidence"),
            "grid_energy_device_resolved": grid_device_resolved,
        }

    # v1.6.11: bundle the last ~80 SEM-related log lines into the
    # diagnostics dump so bug reports come pre-loaded with the
    # surrounding log context. See ``_get_recent_sem_logs`` for the
    # defensive caps and the Supervisor-install fallback.
    recent_logs = await _get_recent_sem_logs(hass)

    return {
        "config_entry": {
            "entry_id": entry.entry_id,
            "version": entry.version,
            "title": entry.title,
            "data": async_redact_data(dict(entry.data), REDACT_CONFIG_KEYS),
            "options": async_redact_data(dict(entry.options), REDACT_CONFIG_KEYS),
        },
        "coordinator": {
            "last_update_success": coordinator.last_update_success,
            "update_interval_s": coordinator.update_interval.total_seconds() if coordinator.update_interval else None,
            "observer_mode": getattr(coordinator, "_observer_mode", False),
        },
        "power": {
            "solar_w": data.get("solar_power"),
            "grid_w": data.get("grid_power"),
            "grid_import_w": data.get("grid_import_power"),
            "grid_export_w": data.get("grid_export_power"),
            "battery_w": data.get("battery_power"),
            "battery_soc": data.get("battery_soc"),
            "home_w": data.get("home_consumption_power"),
            "ev_w": data.get("ev_power"),
        },
        "charging": {
            "state": str(data.get("charging_state")),
            "strategy": str(data.get("charging_strategy")),
            "reason": str(data.get("charging_strategy_reason")),
            "ev_connected": data.get("ev_connected"),
            "ev_charging": data.get("ev_charging"),
            "available_power_w": data.get("available_power"),
            "calculated_current_a": data.get("calculated_current"),
        },
        "energy_daily": {
            "solar_kwh": data.get("daily_solar_energy"),
            "home_kwh": data.get("daily_home_energy"),
            "ev_kwh": data.get("daily_ev_energy"),
            "grid_import_kwh": data.get("daily_grid_import_energy"),
            "grid_export_kwh": data.get("daily_grid_export_energy"),
            "battery_charge_kwh": data.get("daily_battery_charge_energy"),
            "battery_discharge_kwh": data.get("daily_battery_discharge_energy"),
        },
        "energy_yearly": {
            "solar_kwh": data.get("yearly_solar_yield_energy"),
            "grid_import_kwh": data.get("yearly_grid_import_energy"),
            "grid_export_kwh": data.get("yearly_grid_export_energy"),
            "co2_avoided_kg": data.get("yearly_co2_avoided"),
            "trees_equivalent": data.get("yearly_trees_equivalent"),
        },
        "costs_daily": {
            "costs": data.get("daily_costs"),
            "savings": data.get("daily_savings"),
            "export_revenue": data.get("daily_export_revenue"),
            "net_cost": data.get("daily_net_cost"),
        },
        "performance": {
            "self_consumption_pct": data.get("self_consumption_rate"),
            "autarky_pct": data.get("autarky_rate"),
        },
        "peak_management": {
            "consecutive_peak_kw": data.get("consecutive_peak_15min"),
            "monthly_peak_kw": data.get("monthly_consecutive_peak"),
            "target_limit_kw": data.get("target_peak_limit"),
            "percentage": data.get("current_vs_peak_percentage"),
            "status": data.get("load_management_status"),
        },
        "load_management": load_info,
        "energy_dashboard": ed_info,
        "split_grid_discovery": split_grid_info,
        "forecast": {
            "today_kwh": data.get("forecast_today_kwh"),
            "tomorrow_kwh": data.get("forecast_tomorrow_kwh"),
            "source": data.get("forecast_source"),
            "available": data.get("forecast_available"),
        },
        "tariff": {
            "import_rate": data.get("tariff_current_import_rate"),
            "export_rate": data.get("tariff_current_export_rate"),
            "price_level": data.get("tariff_price_level"),
            "provider": data.get("tariff_provider"),
        },
        "recent_logs": recent_logs,
    }
