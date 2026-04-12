"""Diagnostics support for Solar Energy Management."""
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN

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
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = hass.data[DOMAIN][entry.entry_id]
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
        ed_info = {
            "has_solar": ed_config.has_solar,
            "has_grid": ed_config.has_grid,
            "has_battery": ed_config.has_battery,
            "has_ev": ed_config.has_ev,
            "device_count": len(ed_config.device_consumption),
        }

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
    }
