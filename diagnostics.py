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
    # Preferred source: the in-memory ring buffer attached at setup
    # (utils/log_buffer.py). Works on EVERY install type — Supervisor
    # routes HA's log to journald, so there is no flat file to tail and
    # the whole #461/#462 triage ran blind on recent_logs. Type-guarded:
    # tests run with MagicMock hass objects whose ``data.get`` returns a
    # truthy mock.
    from .utils.log_buffer import SEMLogBuffer
    buffer = hass.data.get(f"{DOMAIN}_log_buffer")
    if isinstance(buffer, SEMLogBuffer):
        try:
            lines = buffer.get_lines(_LOG_MAX_LINES)
            if lines:
                return lines
            return ["<no SEM log records captured since startup>"]
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("Log buffer read failed: %s", e)

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


def _build_deye_diagnostics(adapters: dict[str, Any]) -> dict[str, Any] | None:
    """Return a read-only Deye diagnostics block for the first Deye adapter.

    Exposes the fail-closed capability gate (``available`` + ``reason``),
    the effective max charge current, the persisted unsafe latch, and the
    last recovery/actuation error. Pure read — it never writes to the
    adapter or store, and it never serialises the runtime snapshot store
    object. Returns ``None`` when no Deye adapter is present so installs
    that don't use Deye keep the dump compact.
    """
    deye_adapters = [
        ad for ad in adapters.values()
        if type(ad).__name__ == "DeyeBatteryAdapter"
    ]
    if not deye_adapters:
        return None

    ad = deye_adapters[0]
    try:
        capability = ad.capability()
    except Exception:  # noqa: BLE001 — diagnostics must never raise
        capability = None

    available = bool(
        getattr(capability, "available", False) if capability is not None else False
    )
    reason = str(
        getattr(capability, "reason", "") if capability is not None else ""
    )
    return {
        "available": available,
        "reason": reason,
        "max_charge_current_a": float(
            getattr(capability, "max_charge_current_a", 0.0)
            if capability is not None else 0.0
        ),
        "unsafe_latched": bool(getattr(ad, "unsafe_latched", False)),
        "recovery_error": getattr(ad, "_last_error", None) or None,
        "observer_mode": bool(getattr(ad, "_observer_mode", False)),
        "actuation_enabled": bool(getattr(ad, "_actuation_enabled", False)),
    }


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


def _safe(fn):
    """Evaluate a diagnostics accessor; a broken internal must never take
    the whole download down (the download IS the debugging tool)."""
    try:
        return fn()
    except Exception as e:  # noqa: BLE001
        return f"unavailable ({e})"


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: SEMConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator: SEMCoordinator = entry.runtime_data
    data = coordinator.data if coordinator.data else {}

    # (#708) EV stop-decision internals — the taper latch, session peak,
    # SOC anchor (+ age via last_full_at) and the stability give-up
    # streak/backoff. Promised to @Azlinon: no more guessing from source.
    ev_stability: dict[str, Any] = {}
    try:
        dets = getattr(coordinator, "_ev_taper_detectors", None) or {}
        single = getattr(coordinator, "_ev_taper_detector", None)
        if not dets and single is not None:
            dets = {"primary": single}
        ev_stability["taper"] = {
            cid: det.diagnostics_view()
            for cid, det in dets.items()
            if hasattr(det, "diagnostics_view")
        }
        stab = getattr(coordinator, "_charge_stability", None)
        if stab is not None and hasattr(stab, "snapshot_timers"):
            import time as _time
            ev_stability["stability_timers"] = stab.snapshot_timers(
                _time.monotonic())
    except Exception:  # noqa: BLE001 — diagnostics must never fail the download
        ev_stability["error"] = "collection failed"

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

    # #588 — battery sign detection state (mirrors grid sign block above).
    battery_sign_info: dict[str, Any] = {}
    reader_pre = getattr(coordinator, "_sensor_reader", None)
    if reader_pre is not None:
        try:
            battery_sign_info = reader_pre.battery_sign_diagnostics()
        except Exception:  # noqa: BLE001 — diagnostics must never raise
            battery_sign_info = {"error": "diagnostics_failed"}

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

    # PV string discovery result (#379 triage support).
    # The discover_pv_strings_from_registry result lives on
    # ``coordinator._sensor_reader._pv_strings`` (direct-power form)
    # AND ``coordinator._sensor_reader._pv_vi_pairs`` (V+I synthesis
    # form). When a user reports "PV2 is empty in the dashboard", the
    # gap is almost always either:
    #   * Discovery returned empty → ``_pv_strings = {}``
    #   * Discovery returned 1 entry → fallback to multi-inverter
    #     didn't fire (would have produced N entries)
    #   * Both populated correctly → bug is in the dashboard card
    #     rendering (not in this layer)
    pv_strings_info = {}
    if reader:
        pv_strings_info = {
            "discovered_direct": dict(getattr(reader, "_pv_strings", {}) or {}),
            "discovered_vi_pairs": {
                k: list(v) for k, v in
                (getattr(reader, "_pv_vi_pairs", None) or {}).items()
            },
        }

    # Per-charger adapter state (#357 triage support).
    # Surface the brand the adapter resolved to + the brand-specific
    # discovery state. For Wallbox: the ``pause_resume`` switch entity
    # the adapter found (or didn't). When @RienduPre's "charge_mode=off
    # but charger keeps charging" report drops in, this tells us at a
    # glance whether the adapter failed to discover the pause switch
    # (then ``command_disable`` silently no-ops on the pause action,
    # leaving the contactor closed).
    charger_adapter_info = {}
    ev_devices = getattr(coordinator, "_ev_devices", None) or {}
    if ev_devices:
        from .coordinator.ev_control import EVControlMixin  # noqa: F401
        adapters = getattr(coordinator, "_ev_adapters", {}) or {}
        for cid, dev in ev_devices.items():
            ad = adapters.get(cid)
            entry_info = {
                "device_name": getattr(dev, "name", None),
                "device_max_current": getattr(dev, "max_current", None),
                "device_min_current": getattr(dev, "min_current", None),
                "charger_service": getattr(dev, "charger_service", None),
                "adapter_class": type(ad).__name__ if ad else None,
            }
            # Brand-specific state — currently Wallbox is the only
            # one with non-trivial discovery state. KEBA / generic
            # don't have discovery, so this block stays small.
            if ad is not None and type(ad).__name__ == "WallboxAdapter":
                entry_info["wallbox"] = {
                    "pause_switch_searched": getattr(ad, "_pause_switch_searched", False),
                    "pause_switch_entity": getattr(ad, "_pause_switch_entity", None),
                    "pause_switch_discovered": getattr(ad, "_pause_switch_entity", None) is not None,
                }
            charger_adapter_info[cid] = entry_info

    # Battery control observability (#523) — the battery-side mirror of
    # ``charger_adapters``. Answers, in one payload: is the battery
    # controllable at ALL (the Sessy / AC-coupled question), what mode +
    # reserve it's in, and the last per-battery decision + reason — so
    # "is the EV draining the battery?" is a single readable line
    # (``LIMIT_DISCHARGE — ev_charging → 1200W``).
    battery_info: dict[str, Any] = {}
    try:
        full_cfg = {**(entry.data or {}), **(entry.options or {})}
        sched = getattr(coordinator, "_battery_charge_scheduler", None)
        _adapters = getattr(coordinator, "_battery_adapters", None)
        _adapters = _adapters if isinstance(_adapters, dict) else {}
        _decisions = getattr(coordinator, "_last_battery_decisions", None)
        _decisions = _decisions if isinstance(_decisions, dict) else {}
        battery_info = {
            "adapters": {
                bid: {
                    "class": type(ad).__name__,
                    "supports_forced_charge": getattr(ad, "supports_forced_charge", None),
                    "supports_forced_discharge": getattr(ad, "supports_forced_discharge", None),
                    "force_discharge_entity": getattr(ad, "_force_discharge_entity", None) or None,
                    "discharge_control_entity": getattr(ad, "_discharge_control_entity", None) or None,
                    "inverter_device_id_set": bool(getattr(ad, "_inverter_device_id", "")),
                }
                for bid, ad in _adapters.items()
            },
            "last_decisions": _decisions,
            "config": {
                "battery_mode": full_cfg.get("battery_mode"),
                "battery_reserve_soc": full_cfg.get("battery_reserve_soc"),
                "battery_modes": full_cfg.get("battery_modes"),
                "battery_reserve_socs": full_cfg.get("battery_reserve_socs"),
                "battery_discharge_protection_enabled": full_cfg.get(
                    "battery_discharge_protection_enabled", True),
                "battery_grid_arbitrage_enabled": full_cfg.get(
                    "battery_grid_arbitrage_enabled", False),
                "inverter_device_id_set": bool(full_cfg.get("inverter_device_id")),
                "battery_charge_platform": full_cfg.get("battery_charge_platform"),
                "battery_force_discharge_control_entity": full_cfg.get(
                    "battery_force_discharge_control_entity") or None,
                "battery_force_discharge_entities": full_cfg.get(
                    "battery_force_discharge_entities"),
            },
            "scheduler": {
                "enabled": getattr(sched, "enabled", None),
                "state": str(getattr(getattr(sched, "state", None), "value", "")) or None,
            },
        }
        # #709 — Deye forced-grid-charge observability. Read-only. Keep the
        # generic payload unchanged when no Deye adapter exists.
        deye_info = _build_deye_diagnostics(_adapters)
        if deye_info is not None:
            battery_info["deye"] = deye_info
    except Exception as exc:  # noqa: BLE001 — diagnostics must never raise
        battery_info = {"error": str(exc)}

    # Surplus allocation snapshot — answers "why didn't the heat pump /
    # hot water turn on?" (distributable surplus + who won it). Combined
    # with heat_pump.registered + sg_ready_state below, it's the gate
    # reason: not enough surplus, lost priority to the EV, or not wired.
    surplus_info = {
        k: data.get(k) for k in (
            "surplus_total_w", "surplus_distributable_w", "surplus_allocated_w",
            "surplus_unallocated_w", "surplus_active_devices",
            "surplus_total_devices", "surplus_allocations",
        )
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
            # (#628 visibility) per-category counter-backing today: how many
            # cycles reconciled against the hardware counters vs skipped on a
            # partial read. A category absent here has no counters configured
            # (integration IS the design); one with skipped >> backed names
            # the unreadable counter as the divergence mechanism in one look.
            "counter_backing": _safe(
                lambda: coordinator._energy_calculator.counter_backing_today()),
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
        "battery_control": battery_info,
        "surplus": surplus_info,
        # (#653) Appliance schedules — the run state machine and the #426
        # transition telemetry. ``None`` on the vast majority of installs,
        # which never call ``schedule_appliance``. This is the READER for
        # ``diag_appliance_schedules``: publishing the summary into
        # ``coordinator.data`` with nothing consuming it would repeat the
        # exact defect this issue fixes.
        "appliance_schedules": data.get("diag_appliance_schedules"),
        "load_management": load_info,
        "ev_stability": ev_stability,
        "energy_dashboard": ed_info,
        "battery_sign": battery_sign_info,
        "split_grid_discovery": split_grid_info,
        "pv_strings_discovery": pv_strings_info,
        "charger_adapters": charger_adapter_info,
        # #432 — full heat-pump observability block. One-click dump for
        # users with non-standard SG-Ready wiring (ESP relays, Shellies,
        # Modbus-bridged template switches). Tells the maintainer in a
        # single payload whether the gate logic is wrong, the entity
        # wiring is broken, or the config is half-set.
        "heat_pump": {
            "registered": data.get("heat_pump_registered"),
            "registration_status": data.get("heat_pump_registration_status"),
            "mode": data.get("heat_pump_mode"),
            "sg_ready_state": data.get("heat_pump_sg_ready_state"),
            "solar_boost": data.get("heat_pump_solar_boost"),
            "config": {
                "relay1_entity": data.get("heat_pump_relay1_entity"),
                "relay2_entity": data.get("heat_pump_relay2_entity"),
                "climate_entity": data.get("heat_pump_climate_entity"),
            },
            "live": {
                "relay1_state": data.get("heat_pump_relay1_state"),
                "relay2_state": data.get("heat_pump_relay2_state"),
                "climate_state": data.get("heat_pump_climate_state"),
            },
        },
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
