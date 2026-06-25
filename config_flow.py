"""Config flow for Solar Energy Management integration."""

from __future__ import annotations

import logging
from typing import Any, Dict

import voluptuous as vol
from homeassistant.helpers import selector
from homeassistant.core import callback

from homeassistant import config_entries
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResult

from .const import (
    DOMAIN,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_BATTERY_PRIORITY_SOC,
    DEFAULT_BATTERY_MINIMUM_SOC,
    DEFAULT_BATTERY_BUFFER_SOC,
    DEFAULT_BATTERY_AUTO_START_SOC,
    DEFAULT_BATTERY_ASSIST_FLOOR_SOC,
    DEFAULT_MIN_SOLAR_POWER,
    DEFAULT_DAILY_EV_TARGET,
    DEFAULT_BATTERY_ASSIST_MAX_POWER,
    DEFAULT_BATTERY_ASSIST_MIN_SURPLUS,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_BATTERY_DISCHARGE_PROTECTION_ENABLED,
    DEFAULT_BATTERY_MAX_DISCHARGE_POWER,
    DEFAULT_BATTERY_DISCHARGE_CONTROL_ENTITY,
    DEFAULT_EV_CHARGER_SERVICE,
    DEFAULT_EV_CHARGER_SERVICE_ENTITY_ID,
    DEFAULT_PREFER_HARDWARE_ENERGY,
    DEFAULT_ENERGY_SOURCE_AUTO,
    DEFAULT_TARGET_PEAK_LIMIT,
    DEFAULT_WARNING_PEAK_LEVEL,
    DEFAULT_EMERGENCY_PEAK_LEVEL,
    DEFAULT_LOAD_MANAGEMENT_ENABLED,
    DEFAULT_OBSERVER_MODE,
)
from .ha_energy_reader import read_energy_dashboard_config, EnergyDashboardConfig
from .hardware_detection import (
    HardwareDetector,
    discover_ev_charger_from_registry,
    discover_inverter_from_registry,
)

_LOGGER = logging.getLogger(__name__)


def _detect_hardware_specs(hass: HomeAssistant) -> Dict[str, float]:
    """Auto-detect battery capacity, system size, and max discharge from hardware.

    Searches the entity registry for known sensor patterns across inverter brands.
    Returns a dict of detected values (only includes keys that were found).
    """
    detected: Dict[str, float] = {}

    # Battery capacity (Wh or kWh)
    capacity_patterns = [
        "sensor.*akkukapazitat*",      # Huawei (Wh)
        "sensor.*battery_capacity*",    # Generic (kWh or Wh)
        "sensor.*usable_capacity*",     # SolarEdge, generic
        "sensor.*rated_capacity*",      # BYD, generic
    ]
    for pattern in capacity_patterns:
        import fnmatch
        for state in hass.states.async_all("sensor"):
            if fnmatch.fnmatch(state.entity_id, pattern):
                try:
                    val = float(state.state)
                    unit = state.attributes.get("unit_of_measurement", "")
                    if val > 0:
                        # Convert Wh to kWh if needed
                        if unit.lower() == "wh" or val > 500:
                            val = val / 1000
                        detected["battery_capacity_kwh"] = round(val, 1)
                        break
                except (ValueError, TypeError):
                    continue
        if "battery_capacity_kwh" in detected:
            break

    # Inverter rated power (W → kWp)
    power_patterns = [
        "sensor.*nennleistung*",         # Huawei (W)
        "sensor.*rated_power*",          # Generic (W)
        "sensor.*nominal_power*",        # SolarEdge (W)
        "sensor.*max_power*",            # Generic
    ]
    for pattern in power_patterns:
        import fnmatch
        for state in hass.states.async_all("sensor"):
            if fnmatch.fnmatch(state.entity_id, pattern) and "inverter" in state.entity_id.lower():
                try:
                    val = float(state.state)
                    if val > 100:  # Must be in W
                        detected["system_size_kwp"] = round(val / 1000, 1)
                        break
                except (ValueError, TypeError):
                    continue
        if "system_size_kwp" in detected:
            break

    # Battery max discharge power (W)
    discharge_patterns = [
        "number.*maximale_entladeleistung*",  # Huawei
        "number.*max_discharge*",              # Generic
        "sensor.*max_discharge_power*",        # SolarEdge, generic
    ]
    for pattern in discharge_patterns:
        import fnmatch
        for state in hass.states.async_all(["number", "sensor"]):
            if fnmatch.fnmatch(state.entity_id, pattern):
                try:
                    val = float(state.state)
                    if val > 0:
                        detected["battery_max_discharge_power"] = round(val, 0)
                        detected["battery_assist_max_power"] = round(val, 0)
                        break
                except (ValueError, TypeError):
                    continue
        if "battery_max_discharge_power" in detected:
            break

    if detected:
        _LOGGER.info("Hardware auto-detected: %s", detected)

    return detected


class SolarEnergyManagementConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Solar Energy Management."""

    # v4 (#255): per-charger settings seeded from globals (async_migrate_entry).
    # v5 (#277 Phase A): per-charger charge_mode derived from legacy toggles.
    # v6 (#277 Phase B): re-derive charge_mode for the pv+tariff combinations
    #     Phase A's derivation silently dropped.
    # v7 (#277 Phase C): drop the dead ev_charging_mode key (charge_mode is
    #     authoritative now; the legacy select + 3 legacy switches are gone).
    # v8 (#359): flip tariff_classification_mode static→percentile when
    #     tariff_mode == "dynamic".
    # v9 (#440 ADR 0010 #3): add ``vehicle_min_current`` to each
    #     ``ev_chargers`` entry (default None = use the loadpoint
    #     ``ev_min_current``). Optional per-car handshake-floor override.
    # v10 (#441): rename per-charger ``ev_night_initial_current`` to
    #     ``initial_current`` (decouples from the misleading "night"
    #     prefix — the value is the session-start ramp current, applied
    #     whenever a session begins). Display: "Vehicle Start Amps".
    VERSION = 14

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry) -> config_entries.OptionsFlow:
        """Get the options flow for this handler."""
        return OptionsFlowHandler(config_entry)

    def __init__(self):
        """Initialize the config flow."""
        self._data = {}
        self._errors = {}
        self._energy_dashboard_config: EnergyDashboardConfig | None = None
        self._detector = None

    async def async_step_integration_discovery(
        self, discovery_info: dict[str, Any]
    ) -> FlowResult:
        """Handle integration discovery (#44).

        Triggered when a supported inverter integration (huawei_solar,
        solaredge, fronius, goodwe, enphase_envoy, sma, growatt_server,
        solis, powerwall, kostal_plenticore, solax, victron) is loaded.
        Suggests SEM setup if Energy Dashboard is configured.
        """
        await self.async_set_unique_id(DOMAIN)
        # Reload on rediscovery to pick up updated version/device info
        # (quality scale: discovery-update-info)
        self._abort_if_unique_id_configured(reload_on_update=True)

        # Only proceed if Energy Dashboard is actually configured
        dashboard = await read_energy_dashboard_config(self.hass)
        if not dashboard or not dashboard.is_minimally_configured():
            return self.async_abort(reason="energy_dashboard_not_configured")

        return await self.async_step_user()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the initial step - check Energy Dashboard configuration."""
        errors: dict[str, str] = {}

        # Read Energy Dashboard configuration
        self._energy_dashboard_config = await read_energy_dashboard_config(self.hass)

        if self._energy_dashboard_config is None:
            # Energy Dashboard not configured at all
            return self.async_abort(
                reason="energy_dashboard_not_configured",
                description_placeholders={
                    "url": "/config/energy"
                }
            )

        if not self._energy_dashboard_config.is_minimally_configured():
            # Energy Dashboard missing required components
            missing = self._energy_dashboard_config.get_missing_components()
            return self.async_abort(
                reason="energy_dashboard_incomplete",
                description_placeholders={
                    "missing": ", ".join(missing),
                    "url": "/config/energy"
                }
            )

        # Energy Dashboard is configured - show summary and continue.
        # Slim install (v1.7.1-beta.11+, #442): route directly to
        # ``async_step_hardware`` and skip the EV charger step entirely.
        # The EV step's fields stay available in the OptionsFlow for
        # power users and via the new dashboard Configuration tab for
        # everyone else — fresh installs no longer need to lie about
        # their EV setup just to get past the install.
        if user_input is not None:
            # Store Energy Dashboard sensor config + the observer_mode toggle
            self._data.update(self._energy_dashboard_config.to_dict())
            self._data["observer_mode"] = user_input.get("observer_mode", False)
            return await self.async_step_hardware()

        # Show Energy Dashboard summary — list every sensor SEM picked up so the
        # user can verify the auto-detection at a glance.
        cfg = self._energy_dashboard_config
        summary_lines: list[str] = []

        def _add(category: str, fields: list[tuple[str, str | None]]) -> None:
            present = [(label, eid) for label, eid in fields if eid]
            if not present:
                return
            summary_lines.append(f"**{category}**")
            for label, eid in present:
                summary_lines.append(f"  • {label}: `{eid}`")
            summary_lines.append("")

        if cfg.has_solar:
            if len(cfg.solar_power_list) > 1:
                fields = [(f"Power ({i+1})", p) for i, p in enumerate(cfg.solar_power_list)]
                fields += [(f"Energy ({i+1})", e) for i, e in enumerate(cfg.solar_energy_list)]
                _add(f"Solar ({len(cfg.solar_power_list)} inverters)", fields)
            else:
                _add("Solar", [
                    ("Power", cfg.solar_power),
                    ("Energy", cfg.solar_energy),
                ])
        if cfg.has_grid:
            if len(cfg.grid_import_energy_list) > 1:
                fields = [(f"Import energy ({i+1})", e) for i, e in enumerate(cfg.grid_import_energy_list)]
                fields += [(f"Export energy ({i+1})", e) for i, e in enumerate(cfg.grid_export_energy_list)]
                fields.insert(0, ("Power", cfg.grid_import_power))
                _add(f"Grid ({len(cfg.grid_import_energy_list)} tariffs)", fields)
            else:
                _add("Grid", [
                    ("Power", cfg.grid_import_power),
                    ("Import energy", cfg.grid_import_energy),
                    ("Export energy", cfg.grid_export_energy),
                ])
        if cfg.has_battery:
            if len(cfg.battery_power_list) > 1:
                fields = [(f"Power ({i+1})", p) for i, p in enumerate(cfg.battery_power_list)]
                fields += [(f"Charge energy ({i+1})", e) for i, e in enumerate(cfg.battery_charge_energy_list)]
                fields += [(f"Discharge energy ({i+1})", e) for i, e in enumerate(cfg.battery_discharge_energy_list)]
                _add(f"Battery ({len(cfg.battery_power_list)} units)", fields)
            else:
                _add("Battery", [
                    ("Power", cfg.battery_power),
                    ("Charge energy", cfg.battery_charge_energy),
                    ("Discharge energy", cfg.battery_discharge_energy),
                ])
        if cfg.has_ev:
            _add("EV", [
                ("Power", cfg.ev_power),
                ("Energy", cfg.ev_energy),
            ])

        # Trim trailing blank line for tidy rendering
        if summary_lines and summary_lines[-1] == "":
            summary_lines.pop()

        return self.async_show_form(
            step_id="user",
            data_schema=vol.Schema({
                # Single safety toggle. Defaulted OFF so a real install
                # actually controls hardware. Set to ON for test/staging
                # instances that mirror a production HA — observer mode
                # blocks every outbound service call from SEM.
                vol.Optional(
                    "observer_mode",
                    default=False,
                ): selector.BooleanSelector(),
            }),
            description_placeholders={
                "summary": "\n".join(summary_lines)
            },
            errors=errors
        )

    async def async_step_ev_charger(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle the EV charger control configuration step."""
        errors: dict[str, str] = {}

        # Initialize hardware detector for EV control entity detection
        if self._detector is None:
            self._detector = HardwareDetector(self.hass)

        if user_input is not None:
            # Validate EV charger entities
            validation_errors = self._detector.validate_ev_configuration(user_input)
            if validation_errors:
                errors.update(validation_errors)
                _LOGGER.error(f"EV validation failed: {validation_errors}")

            # Validate optional entity IDs exist in HA and have usable state (#32)
            for entity_key in (
                "ev_charger_service_entity_id",
                "ev_current_sensor",
                "ev_total_energy_sensor",
            ):
                entity_id = user_input.get(entity_key, "")
                if entity_id:
                    state = self.hass.states.get(entity_id)
                    if not state:
                        errors[entity_key] = "entity_not_found"
                    elif state.state in ("unknown", "unavailable"):
                        _LOGGER.warning(
                            "Entity %s exists but has state '%s' — may cause issues",
                            entity_id, state.state,
                        )

            if not errors:
                # Store EV charger entities and continue to the hardware step
                self._data.update(user_input)
                return await self.async_step_hardware()

        # Primary: integration-aware registry discovery (KEBA, Easee, go-eCharger, Wallbox).
        # This filters by entity registry platform and device_class, so it never matches
        # unrelated devices like generic smart plugs.
        suggestions = discover_ev_charger_from_registry(self.hass)

        # Fallback: pattern-based detection only fills keys the registry didn't already set,
        # so a stray generic match can never override a confident registry match.
        pattern_suggestions = self._detector.get_suggested_ev_defaults() if self._detector else {}
        for key, value in pattern_suggestions.items():
            if value and not suggestions.get(key):
                suggestions[key] = value

        # Pre-fill from Energy Dashboard if available
        if self._energy_dashboard_config and self._energy_dashboard_config.has_ev:
            if self._energy_dashboard_config.ev_power and not suggestions.get("ev_charging_power_sensor"):
                suggestions["ev_charging_power_sensor"] = self._energy_dashboard_config.ev_power
            if self._energy_dashboard_config.ev_energy and not suggestions.get("ev_total_energy_sensor"):
                suggestions["ev_total_energy_sensor"] = self._energy_dashboard_config.ev_energy

        # Helper for optional EntitySelector fields: HA rejects default="" because
        # an empty string is neither a valid entity_id nor None. Use suggested_value
        # via the field description so the prefill is shown without becoming a
        # hard default.
        def _opt_entity_default(key: str):
            v = suggestions.get(key)
            return v if v is not None else None

        return self.async_show_form(
            step_id="ev_charger",
            data_schema=vol.Schema({
                # EV Charger Control Entities (Required for solar optimization)
                # Accept both binary_sensor and sensor for Easee/GoodWe (#68)
                vol.Required(
                    "ev_connected_sensor",
                    default=suggestions.get("ev_connected_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_sensor",
                    default=suggestions.get("ev_charging_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_power_sensor",
                    default=suggestions.get("ev_charging_power_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="power"
                    )
                ),

                # EV Charger Control — pick ONE of the two paths below:
                #   • Number entity (Wallbox, go-eCharger, Heidelberg, OpenWB, Ohme, V2C, …)
                #   • Service call    (KEBA, Easee, Zaptec, OCPP, …)
                vol.Optional(
                    "ev_current_control_entity",
                    description={"suggested_value": _opt_entity_default("ev_current_control_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(
                    "ev_charger_service",
                    default=suggestions.get("ev_charger_service", ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(
                        type=selector.TextSelectorType.TEXT
                    )
                ),
                vol.Optional(
                    "ev_charger_service_entity_id",
                    description={"suggested_value": _opt_entity_default("ev_charger_service_entity_id")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor", "switch"])
                ),

                # Optional readback sensors
                vol.Optional(
                    "ev_current_sensor",
                    description={"suggested_value": _opt_entity_default("ev_current_sensor")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="current"
                    )
                ),
                vol.Optional(
                    "ev_total_energy_sensor",
                    description={"suggested_value": _opt_entity_default("ev_total_energy_sensor")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain="sensor",
                        device_class="energy"
                    )
                ),
                # #397: per-charger tunables — `ev_surplus_priority`,
                # `daily_ev_target` + `_max`, `initial_current`,
                # `ev_min_current`, `ev_target_soc` + `_max`,
                # `ev_battery_capacity_kwh`, `vehicle_soc_entity` — all live
                # in OptionsFlow only. PR #390 surfaced them at install time
                # and the resulting 16-field step became the biggest install
                # drop-off; the original slim-3-step design at line ~440 is
                # the right shape per the SaaS-onboarding research. The
                # Wallbox install-time blocker (`ev_current_control_entity`)
                # is the only #390 field that stays — it's not a tunable, it's
                # a control-path requirement no default can substitute for.
            }),
            errors=errors
        )

    @staticmethod
    def _install_defaults() -> dict[str, Any]:
        """Return the default values for fields the install flow no longer asks.

        These keys are read by the coordinator (and various sub-modules) at
        startup. Asking the user for every one of them is overwhelming, so the
        slim install flow stores sensible defaults silently and lets advanced
        users tune them later via the OptionsFlow or the runtime number
        entities. Keep this in sync with the OptionsFlowHandler so the same
        keys are editable post-install.
        """
        return {
            # Coordinator loop
            "update_interval": DEFAULT_UPDATE_INTERVAL,
            # 4-zone SOC strategy thresholds (see docs/ARCHITECTURE.md)
            "battery_priority_soc": DEFAULT_BATTERY_PRIORITY_SOC,
            "battery_buffer_soc": DEFAULT_BATTERY_BUFFER_SOC,
            "battery_auto_start_soc": DEFAULT_BATTERY_AUTO_START_SOC,
            "battery_assist_floor_soc": DEFAULT_BATTERY_ASSIST_FLOOR_SOC,
            # Legacy 3-zone hard-stop / resume — kept for the safety gates
            # in coordinator.py that haven't been migrated to the 4-zone
            # strategy yet (battery_too_low check, hysteresis resume).
            "battery_minimum_soc": DEFAULT_BATTERY_MINIMUM_SOC,
            # Solar / power gates
            "minimum_solar_power": DEFAULT_MIN_SOLAR_POWER,
            # Daily target & battery assist
            "daily_ev_target": DEFAULT_DAILY_EV_TARGET,
            "battery_assist_max_power": DEFAULT_BATTERY_ASSIST_MAX_POWER,
            "battery_assist_min_surplus": DEFAULT_BATTERY_ASSIST_MIN_SURPLUS,
            # Battery discharge protection (entity is auto-detected separately)
            "battery_discharge_protection_enabled": DEFAULT_BATTERY_DISCHARGE_PROTECTION_ENABLED,
            "battery_max_discharge_power": DEFAULT_BATTERY_MAX_DISCHARGE_POWER,
            # Energy source selection
            "prefer_hardware_energy": DEFAULT_PREFER_HARDWARE_ENERGY,
            "energy_source_auto": DEFAULT_ENERGY_SOURCE_AUTO,
            # ``smart_night_charging`` removed in #277 Phase C — the
            # named ``charge_mode`` carries that intent now.
            # Notifications — sensible defaults; tune in OptionsFlow
            "enable_charger_notifications": True,
            "enable_mobile_notifications": False,
            "mobile_notification_service": "",
            # Load management — only target_peak_limit is asked at install,
            # everything else uses safe defaults that the user can tune later.
            "load_management_enabled": DEFAULT_LOAD_MANAGEMENT_ENABLED,
            "warning_peak_level": DEFAULT_WARNING_PEAK_LEVEL,
            "emergency_peak_level": DEFAULT_EMERGENCY_PEAK_LEVEL,
            # #442 slim install: explicit empty EV chargers list so
            # downstream code reading ``config["ev_chargers"]`` always
            # finds a list (even though ``.get("ev_chargers") or []``
            # would also work). Users add their first charger from the
            # dashboard Configuration tab → OptionsFlow ``ev_charger_add``.
            "ev_chargers": [],
        }

    async def async_step_hardware(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Final install step: ask only the genuinely hardware-dependent values.

        Asks the user for the home battery capacity and the grid peak limit
        (both vary by install and have no universal default). Auto-detects
        the inverter's battery discharge control entity from the entity
        registry. All other tunables are filled from ``_install_defaults()``
        so the coordinator boots with a complete config dict.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                await self.async_set_unique_id(DOMAIN)
                self._abort_if_unique_id_configured()

                # Apply silent defaults first, then layer hardware auto-detection,
                # user's hardware answers, and discharge entity on top.
                merged: dict[str, Any] = {}
                merged.update(self._install_defaults())
                merged.update(_detect_hardware_specs(self.hass))
                merged.update(self._data)
                merged.update(user_input)

                discharge_entity = discover_inverter_from_registry(
                    self.hass, self._energy_dashboard_config
                )
                if discharge_entity:
                    merged["battery_discharge_control_entity"] = discharge_entity
                else:
                    # Coordinator fallback expects the key to be present even
                    # if empty so config.get() returns "".
                    merged.setdefault("battery_discharge_control_entity", "")

                # Wrap flat EV keys into ev_chargers list (#112 multi-charger).
                # #442: ``_install_defaults()`` now sets ``ev_chargers: []`` so
                # downstream code always finds a list. Treat both "missing" and
                # "empty list" as the wrap-eligible state.
                if merged.get("ev_charging_power_sensor") and not merged.get("ev_chargers"):
                    _EV_KEYS = [
                        "ev_connected_sensor", "ev_charging_sensor",
                        "ev_charging_power_sensor", "ev_charger_service",
                        "ev_charger_service_entity_id", "ev_current_sensor",
                        "ev_total_energy_sensor", "ev_session_energy_sensor",
                        "ev_service_param_name", "ev_service_device_id",
                        "ev_start_stop_entity", "ev_charge_mode_entity",
                        "ev_charge_mode_start", "ev_charge_mode_stop",
                        "ev_start_service", "ev_start_service_data",
                        "ev_stop_service", "ev_stop_service_data",
                        "ev_charger_needs_cycle", "ev_surplus_priority",
                        "ev_shed_priority",
                        # Wallbox-style control path (#384 Part 2 kept). The
                        # other 8 per-charger fields from #390 reverted to
                        # OptionsFlow-only in #397 — they were tunables with
                        # sensible defaults, not install-time blockers.
                        "ev_current_control_entity",
                    ]
                    charger_0 = {"id": "ev_charger", "name": "EV Charger"}
                    for k in _EV_KEYS:
                        if merged.get(k) is not None:
                            charger_0[k] = merged[k]
                    merged["ev_chargers"] = [charger_0]

                self._data = merged
                return self.async_create_entry(
                    title="Solar Energy Management",
                    data=self._data,
                )
            except Exception:
                _LOGGER.exception("Unexpected exception creating entry")
                errors["base"] = "unknown"

        # Best-effort preview of the auto-detected discharge entity for the
        # description placeholder so the user can see what was found.
        detected_discharge = discover_inverter_from_registry(
            self.hass, self._energy_dashboard_config
        )
        discharge_summary = (
            f"`{detected_discharge}`" if detected_discharge else "(not auto-detected)"
        )

        return self.async_show_form(
            step_id="hardware",
            data_schema=vol.Schema({
                vol.Required(
                    "target_peak_limit",
                    default=DEFAULT_TARGET_PEAK_LIMIT,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=2.0, max=20.0, step=0.5, unit_of_measurement="kW", mode="slider"
                    )
                ),
                # Opt-in: generate the SEM Lovelace dashboard right after the
                # config entry is created. The post-setup hook in __init__.py
                # consumes this flag exactly once and clears it from
                # entry.data so the dashboard isn't regenerated on every
                # restart.
                vol.Optional(
                    "generate_dashboard_on_install",
                    default=True,
                ): selector.BooleanSelector(),
                vol.Optional(
                    "diagram_style",
                    default="sem",
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "sem", "label": "SEM (built-in)"},
                            {"value": "kflow", "label": "K-Flow (HACS)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
            description_placeholders={
                "discharge_entity": discharge_summary,
            },
            errors=errors,
        )



    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle reconfiguration of the integration."""
        errors: dict[str, str] = {}

        reconfigure_entry = self._get_reconfigure_entry()
        current_config = {**reconfigure_entry.data, **reconfigure_entry.options}

        if user_input is not None:
            # Validate EV charger entities if provided
            if self._detector is None:
                self._detector = HardwareDetector(self.hass)

            validation_errors = self._detector.validate_ev_configuration(user_input)
            if validation_errors:
                errors.update(validation_errors)

            # Validate optional entity IDs exist in HA
            for entity_key in (
                "ev_charger_service_entity_id",
                "ev_total_energy_sensor",
            ):
                entity_id = user_input.get(entity_key, "")
                if entity_id and not self.hass.states.get(entity_id):
                    errors[entity_key] = "entity_not_found"

            # Validate notification service if provided
            mobile_service = user_input.get("mobile_notification_service", "").strip()
            if user_input.get("enable_mobile_notifications", False) and mobile_service:
                svc_name = mobile_service.replace("notify.", "").split(".")[-1]
                if not (self.hass.services.has_service("notify", svc_name)
                        or self.hass.services.has_service("rest_command", svc_name)):
                    errors["mobile_notification_service"] = "service_not_found"

            if not errors:
                return self.async_update_reload_and_abort(
                    reconfigure_entry,
                    data_updates=user_input,
                )

        # Get available notification services (notify.* and rest_command.*)
        notify_services = [{"value": "", "label": "None"}]
        try:
            services_dict = self.hass.services.async_services()
            if "notify" in services_dict:
                for service in services_dict["notify"].keys():
                    notify_services.append({
                        "value": service,
                        "label": f"notify.{service}"
                    })
            if "rest_command" in services_dict:
                for service in services_dict["rest_command"].keys():
                    notify_services.append({
                        "value": service,
                        "label": f"rest_command.{service}"
                    })
            notify_services[1:] = sorted(notify_services[1:], key=lambda x: x["label"])
        except Exception:
            pass

        return self.async_show_form(
            step_id="reconfigure",
            data_schema=vol.Schema({
                vol.Required(
                    "ev_connected_sensor",
                    default=current_config.get("ev_connected_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_sensor",
                    default=current_config.get("ev_charging_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_power_sensor",
                    default=current_config.get("ev_charging_power_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(
                    "ev_charger_service",
                    default=current_config.get("ev_charger_service", ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    "ev_charger_service_entity_id",
                    default=current_config.get("ev_charger_service_entity_id", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor", "switch"])
                ),
                vol.Optional(
                    "ev_total_energy_sensor",
                    default=current_config.get("ev_total_energy_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="energy")
                ),
                vol.Optional(
                    "enable_charger_notifications",
                    default=current_config.get("enable_charger_notifications", True),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "enable_mobile_notifications",
                    default=current_config.get("enable_mobile_notifications", False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "mobile_notification_service",
                    default=current_config.get("mobile_notification_service", ""),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notify_services,
                        mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
            }),
            errors=errors,
        )


class OptionsFlowHandler(config_entries.OptionsFlow):
    """Handle options flow for Solar Energy Management."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Initialize options flow.

        On HA 2024.12+ the framework auto-injects `self.config_entry` via
        a property on the OptionsFlow base — explicitly assigning it raises
        a deprecation warning. We just initialise our own state.
        """
        self._data: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Manage the options."""
        return await self.async_step_ev_charger()

    @staticmethod
    def _cfg(config: dict, key: str, fallback: Any) -> Any:
        """Null-safe config lookup.

        ``dict.get(key, fallback)`` returns ``None`` when the key exists
        with value ``None``.  Voluptuous rejects ``None`` as a default
        for NumberSelector / BooleanSelector, causing the form to crash
        with HTTP 400 (#73).  This helper treats ``None`` the same as
        missing.
        """
        v = config.get(key)
        return fallback if v is None else v

    async def async_step_ev_charger(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle EV charger options (primary charger)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            # Update both flat keys and ev_chargers[0] (#112)
            self._data.update(user_input)
            ev_chargers = list(self._data.get("ev_chargers") or self.config_entry.options.get("ev_chargers") or [])
            if ev_chargers:
                ev_chargers[0].update(user_input)
            else:
                ev_chargers = [{"id": "ev_charger", "name": "EV Charger", **user_input}]
            self._data["ev_chargers"] = ev_chargers
            return await self.async_step_ev_charger_menu()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        # Read from ev_chargers[0] if available (#112 multi-charger)
        ev_chargers = current_config.get("ev_chargers", [])
        if ev_chargers:
            for k, v in ev_chargers[0].items():
                if k not in ("id", "name") and v is not None:
                    current_config.setdefault(k, v)
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        def _opt(key: str):
            v = current_config.get(key)
            return v if v is not None else None

        return self.async_show_form(
            step_id="ev_charger",
            data_schema=vol.Schema({
                vol.Required(
                    "ev_connected_sensor",
                    default=current_config.get("ev_connected_sensor", "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_sensor",
                    default=current_config.get("ev_charging_sensor", "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_power_sensor",
                    default=current_config.get("ev_charging_power_sensor", "")
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    "ev_charger_service",
                    default=current_config.get("ev_charger_service", ""),
                ): selector.TextSelector(
                    selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                ),
                vol.Optional(
                    "ev_charger_service_entity_id",
                    description={"suggested_value": _opt("ev_charger_service_entity_id")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor", "switch"])
                ),
                vol.Optional(
                    "ev_total_energy_sensor",
                    description={"suggested_value": _opt("ev_total_energy_sensor")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                # Vehicle SOC fields — moved here from the install flow.
                # Only meaningful when a vehicle SOC sensor is exposed in HA;
                # see issues #97 and #98.
                vol.Optional(
                    "vehicle_soc_entity",
                    description={"suggested_value": _opt("vehicle_soc_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="battery")
                ),
                vol.Optional(
                    "ev_battery_capacity_kwh",
                    default=_c("ev_battery_capacity_kwh", 40),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=120, step=5, unit_of_measurement="kWh", mode="box"
                    )
                ),
                # Optional real range sensor; else range is derived from
                # SOC × capacity ÷ consumption (kWh/100km) (#245).
                vol.Optional(
                    "vehicle_range_entity",
                    description={"suggested_value": _opt("vehicle_range_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="distance")
                ),
                vol.Optional(
                    "ev_kwh_per_100km",
                    default=_c("ev_kwh_per_100km", 18),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=8, max=50, step=0.5, unit_of_measurement="kWh/100km", mode="box"
                    )
                ),
                vol.Optional(
                    "ev_target_soc",
                    default=_c("ev_target_soc", 80),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5, unit_of_measurement="%", mode="slider"
                    )
                ),
                # Optional solar ceiling (Max): surplus charges up to this, then
                # stops. Defaults to full (100) = charge freely from sun (#245).
                vol.Optional(
                    "daily_ev_target_max",
                    default=_c("daily_ev_target_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=0.5, unit_of_measurement="kWh", mode="slider"
                    )
                ),
                vol.Optional(
                    "ev_target_soc_max",
                    default=_c("ev_target_soc_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5, unit_of_measurement="%", mode="slider"
                    )
                ),
            }),
            errors=errors
        )

    async def async_step_ev_charger_menu(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Multi-charger menu: add another charger or continue (#112)."""
        if user_input is not None:
            action = user_input.get("action", "continue")
            if action == "add_charger":
                return await self.async_step_ev_charger_add()
            if action == "remove_charger":
                return await self.async_step_ev_charger_remove()
            if action.startswith("edit_charger:"):
                self._edit_charger_id = action.split(":", 1)[1]
                return await self.async_step_ev_charger_edit()
            return await self.async_step_settings()

        ev_chargers = self._data.get("ev_chargers", [])
        charger_count = len(ev_chargers)

        # Show charger list + options
        options = [
            {"value": "continue", "label": f"Continue ({charger_count} charger{'s' if charger_count != 1 else ''} configured)"},
        ]
        # Edit option per charger
        for c in ev_chargers:
            options.append(
                {"value": f"edit_charger:{c['id']}", "label": f"Edit: {c.get('name', c['id'])}"},
            )
        options.append({"value": "add_charger", "label": "Add another EV charger"})
        if charger_count > 1:
            options.append(
                {"value": "remove_charger", "label": "Remove a charger"},
            )

        return self.async_show_form(
            step_id="ev_charger_menu",
            data_schema=vol.Schema({
                vol.Required("action", default="continue"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }),
        )

    async def async_step_ev_charger_add(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Add an additional EV charger (#112)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            ev_chargers = list(self._data.get("ev_chargers", []))
            idx = len(ev_chargers)
            charger_name = user_input.pop("charger_name", f"EV Charger {idx + 1}")
            new_charger = {
                "id": f"ev_charger_{idx}",
                "name": charger_name,
                **user_input,
            }
            ev_chargers.append(new_charger)
            self._data["ev_chargers"] = ev_chargers
            _LOGGER.info("Added EV charger '%s' (total: %d)", charger_name, len(ev_chargers))
            return await self.async_step_ev_charger_menu()

        # Auto-discover additional chargers
        from .hardware_detection import discover_all_ev_chargers_from_registry
        all_discovered = discover_all_ev_chargers_from_registry(self.hass)
        existing_ids = {c.get("_device_id") for c in self._data.get("ev_chargers", []) if c.get("_device_id")}
        # Filter to undiscovered chargers
        new_discoveries = [c for c in all_discovered if c.get("_device_id") not in existing_ids]
        suggestions = new_discoveries[0] if new_discoveries else {}

        return self.async_show_form(
            step_id="ev_charger_add",
            data_schema=vol.Schema({
                vol.Required(
                    "charger_name",
                    default=suggestions.get("name", f"EV Charger {len(self._data.get('ev_chargers', [])) + 1}"),
                ): selector.TextSelector(),
                vol.Required(
                    "ev_connected_sensor",
                    default=suggestions.get("ev_connected_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_sensor",
                    default=suggestions.get("ev_charging_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_power_sensor",
                    default=suggestions.get("ev_charging_power_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(
                    "ev_current_control_entity",
                    description={"suggested_value": suggestions.get("ev_current_control_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(
                    "ev_charger_service",
                    default=suggestions.get("ev_charger_service", ""),
                ): selector.TextSelector(),
                vol.Optional(
                    "ev_charger_service_entity_id",
                    description={"suggested_value": suggestions.get("ev_charger_service_entity_id")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor", "switch"])
                ),
                vol.Optional(
                    "ev_surplus_priority",
                    default=5,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1, mode="slider")
                ),
                # #470: independent shed order under peak; defaults to the
                # surplus priority above.
                vol.Optional(
                    "ev_shed_priority",
                    default=5,
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1, mode="slider")
                ),
                # Per-charger night charging settings (#193)
                vol.Optional(
                    "daily_ev_target",
                    default=self._data.get("daily_ev_target", 10),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=0.5,
                        unit_of_measurement="kWh", mode="slider",
                    )
                ),
                # Solar ceiling (Max): surplus charges up to this, then stops.
                # Default full (100) = charge freely from sun (#245).
                vol.Optional(
                    "daily_ev_target_max",
                    default=self._data.get("daily_ev_target_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=0.5,
                        unit_of_measurement="kWh", mode="slider",
                    )
                ),
                vol.Optional(
                    "initial_current",
                    default=self._data.get("initial_current", 10),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=6, max=32, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_min_current",
                    default=self._data.get("ev_min_current", 6),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=6, max=16, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                # Per-charger vehicle SOC entity (#193)
                vol.Optional(
                    "vehicle_soc_entity",
                    description={"suggested_value": suggestions.get("vehicle_soc_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                # Optional real range sensor; else range is derived from
                # SOC × capacity ÷ consumption (kWh/100km) (#245, #384).
                vol.Optional(
                    "vehicle_range_entity",
                    description={"suggested_value": suggestions.get("vehicle_range_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="distance")
                ),
                vol.Optional(
                    "ev_kwh_per_100km",
                    default=self._data.get("ev_kwh_per_100km", 18),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=8, max=50, step=0.5,
                        unit_of_measurement="kWh/100km", mode="box",
                    )
                ),
                # Per-charger SOC target (#215): Min floor + Max solar ceiling (#245)
                vol.Optional(
                    "ev_target_soc",
                    default=self._data.get("ev_target_soc", 80),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5,
                        unit_of_measurement="%", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_target_soc_max",
                    default=self._data.get("ev_target_soc_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5,
                        unit_of_measurement="%", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_battery_capacity_kwh",
                    default=self._data.get("ev_battery_capacity_kwh", 40),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=120, step=5,
                        unit_of_measurement="kWh", mode="box",
                    )
                ),
            }),
            errors=errors,
        )

    async def async_step_ev_charger_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Edit an existing EV charger's configuration (#130)."""
        errors: dict[str, str] = {}
        charger_id = getattr(self, '_edit_charger_id', None)
        ev_chargers = list(self._data.get("ev_chargers", []))
        charger = next((c for c in ev_chargers if c.get("id") == charger_id), None)

        if not charger:
            return await self.async_step_ev_charger_menu()

        if user_input is not None:
            # Update charger with new values
            charger_name = user_input.pop("charger_name", charger.get("name", "EV Charger"))
            charger.update(user_input)
            charger["name"] = charger_name
            self._data["ev_chargers"] = ev_chargers
            _LOGGER.info("Updated EV charger '%s'", charger_name)
            return await self.async_step_ev_charger_menu()

        return self.async_show_form(
            step_id="ev_charger_edit",
            data_schema=vol.Schema({
                vol.Required(
                    "charger_name",
                    default=charger.get("name", "EV Charger"),
                ): selector.TextSelector(),
                vol.Required(
                    "ev_connected_sensor",
                    default=charger.get("ev_connected_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_sensor",
                    default=charger.get("ev_charging_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor"])
                ),
                vol.Required(
                    "ev_charging_power_sensor",
                    default=charger.get("ev_charging_power_sensor", ""),
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    "ev_current_control_entity",
                    description={"suggested_value": charger.get("ev_current_control_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="number")
                ),
                vol.Optional(
                    "ev_charger_service",
                    default=charger.get("ev_charger_service", ""),
                ): selector.TextSelector(),
                vol.Optional(
                    "ev_charger_service_entity_id",
                    description={"suggested_value": charger.get("ev_charger_service_entity_id")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["binary_sensor", "sensor", "switch"])
                ),
                vol.Optional(
                    "ev_surplus_priority",
                    default=charger.get("ev_surplus_priority", 5),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1, mode="slider")
                ),
                # #470: shed order under peak — independent of the surplus
                # order above. Lower number = charges first on surplus;
                # higher number = shed first under peak. Defaults to the
                # surplus priority so they coincide until deliberately split.
                vol.Optional(
                    "ev_shed_priority",
                    default=charger.get(
                        "ev_shed_priority", charger.get("ev_surplus_priority", 5),
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1, mode="slider")
                ),
                # Per-charger night charging settings (#193)
                vol.Optional(
                    "daily_ev_target",
                    default=charger.get("daily_ev_target", self._data.get("daily_ev_target", 10)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=0.5,
                        unit_of_measurement="kWh", mode="slider",
                    )
                ),
                # Optional solar ceiling (Max): surplus charges up to this, then
                # stops. Defaults to full (100) = charge freely from sun (#245).
                vol.Optional(
                    "daily_ev_target_max",
                    default=charger.get("daily_ev_target_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=0.5,
                        unit_of_measurement="kWh", mode="slider",
                    )
                ),
                vol.Optional(
                    "initial_current",
                    default=charger.get("initial_current", self._data.get("initial_current", 10)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=6, max=32, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_min_current",
                    default=charger.get("ev_min_current", self._data.get("ev_min_current", 6)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=6, max=16, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                # Per-vehicle handshake-floor minimum (ADR 0010 #3, #440).
                # Optional; defaults to whatever ``ev_min_current`` is set to.
                # Lets users record per-car constraints (e.g. Renault Zoe ~9 A
                # handshake floor) without raising the SEM-side floor that
                # other chargers in a multi-charger fleet might want at 6 A.
                # Effective floor at the decision layer is
                # ``max(ev_min_current, vehicle_min_current or 0)``.
                vol.Optional(
                    "vehicle_min_current",
                    description={"suggested_value": charger.get("vehicle_min_current")},
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=6, max=32, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                # Per-charger vehicle SOC entity (#193)
                vol.Optional(
                    "vehicle_soc_entity",
                    description={"suggested_value": charger.get("vehicle_soc_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                # Optional real range sensor; else range is derived from
                # SOC × capacity ÷ consumption (kWh/100km) (#245, #384).
                vol.Optional(
                    "vehicle_range_entity",
                    description={"suggested_value": charger.get("vehicle_range_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="distance")
                ),
                vol.Optional(
                    "ev_kwh_per_100km",
                    default=charger.get("ev_kwh_per_100km", self._data.get("ev_kwh_per_100km", 18)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=8, max=50, step=0.5,
                        unit_of_measurement="kWh/100km", mode="box",
                    )
                ),
                # Per-charger SOC target (#215)
                vol.Optional(
                    "ev_target_soc",
                    default=charger.get("ev_target_soc", self._data.get("ev_target_soc", 80)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5,
                        unit_of_measurement="%", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_target_soc_max",
                    default=charger.get("ev_target_soc_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5,
                        unit_of_measurement="%", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_battery_capacity_kwh",
                    default=charger.get("ev_battery_capacity_kwh", self._data.get("ev_battery_capacity_kwh", 40)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=120, step=5,
                        unit_of_measurement="kWh", mode="box",
                    )
                ),
            }),
            errors=errors,
        )

    async def async_step_ev_charger_remove(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Remove an EV charger (#112)."""
        if user_input is not None:
            remove_id = user_input.get("charger_to_remove")
            ev_chargers = [c for c in self._data.get("ev_chargers", []) if c.get("id") != remove_id]
            self._data["ev_chargers"] = ev_chargers
            _LOGGER.info("Removed EV charger '%s' (remaining: %d)", remove_id, len(ev_chargers))
            return await self.async_step_ev_charger_menu()

        ev_chargers = self._data.get("ev_chargers", [])
        # Don't allow removing the last charger
        removable = [c for c in ev_chargers[1:]]  # Skip primary
        if not removable:
            return await self.async_step_ev_charger_menu()

        options = [{"value": c["id"], "label": c.get("name", c["id"])} for c in removable]

        return self.async_show_form(
            step_id="ev_charger_remove",
            data_schema=vol.Schema({
                vol.Required("charger_to_remove"): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=options,
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_settings(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """SOC Zone Strategy — battery thresholds for the 4-zone model."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_settings_ev()

        current_config = {**self.config_entry.data, **self.config_entry.options}

        _c = lambda key, fb: self._cfg(current_config, key, fb)
        return self.async_show_form(
            step_id="settings",
            data_schema=vol.Schema({
                vol.Optional(
                    "battery_priority_soc",
                    default=_c("battery_priority_soc", DEFAULT_BATTERY_PRIORITY_SOC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=60, step=5, unit_of_measurement="%", mode="slider")
                ),
                vol.Optional(
                    "battery_buffer_soc",
                    default=_c("battery_buffer_soc", DEFAULT_BATTERY_BUFFER_SOC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=50, max=95, step=5, unit_of_measurement="%", mode="slider")
                ),
                vol.Optional(
                    "battery_auto_start_soc",
                    default=_c("battery_auto_start_soc", DEFAULT_BATTERY_AUTO_START_SOC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=70, max=100, step=5, unit_of_measurement="%", mode="slider")
                ),
                vol.Optional(
                    "battery_assist_floor_soc",
                    default=_c("battery_assist_floor_soc", DEFAULT_BATTERY_ASSIST_FLOOR_SOC),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=30, max=80, step=5, unit_of_measurement="%", mode="slider")
                ),
                vol.Optional(
                    "battery_capacity_kwh",
                    default=_c("battery_capacity_kwh", DEFAULT_BATTERY_CAPACITY_KWH),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=100, step=1, unit_of_measurement="kWh", mode="slider")
                ),
                vol.Optional(
                    "battery_assist_max_power",
                    default=_c("battery_assist_max_power", _c("super_charger_power", DEFAULT_BATTERY_ASSIST_MAX_POWER)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1000, max=10000, step=500, unit_of_measurement="W", mode="slider")
                ),
                vol.Optional(
                    "battery_assist_min_surplus",
                    default=_c("battery_assist_min_surplus", DEFAULT_BATTERY_ASSIST_MIN_SURPLUS),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=5000, step=100, unit_of_measurement="W", mode="slider")
                ),
                vol.Optional(
                    "battery_discharge_protection_enabled",
                    default=_c("battery_discharge_protection_enabled", DEFAULT_BATTERY_DISCHARGE_PROTECTION_ENABLED),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "battery_max_discharge_power",
                    default=_c("battery_max_discharge_power", DEFAULT_BATTERY_MAX_DISCHARGE_POWER),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=500, max=10000, step=250, unit_of_measurement="W", mode="slider")
                ),
                vol.Optional(
                    "battery_discharge_control_entity",
                    description={"suggested_value": current_config.get("battery_discharge_control_entity") or None},
                ): selector.EntitySelector(selector.EntitySelectorConfig(domain="number")),
                vol.Optional(
                    "diagram_style",
                    default=_c("diagram_style", "sem"),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "sem", "label": "SEM (built-in)"},
                            {"value": "kflow", "label": "K-Flow (HACS)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                # #352 — Enphase + a handful of other installs report
                # grid power with +import / -export polarity (opposite
                # of SEM's convention). The Energy-Dashboard-counter
                # auto-detect can't always stabilise on these (counters
                # tick at coarse intervals). This toggle is the manual
                # escape hatch: when ON, the raw read is negated and
                # auto-detect is bypassed.
                vol.Optional(
                    "grid_sign_invert",
                    default=_c("grid_sign_invert", False),
                ): selector.BooleanSelector(),
            }),
            errors=errors,
        )

    async def async_step_settings_ev(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """EV Charging & Solar settings."""
        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_settings_tariff()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        return self.async_show_form(
            step_id="settings_ev",
            data_schema=vol.Schema({
                vol.Optional(
                    "daily_ev_target",
                    default=_c("daily_ev_target", DEFAULT_DAILY_EV_TARGET),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=100, step=0.5, unit_of_measurement="kWh", mode="slider")
                ),
                vol.Optional(
                    "minimum_solar_power",
                    default=_c("minimum_solar_power", DEFAULT_MIN_SOLAR_POWER),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=5000, step=100, unit_of_measurement="W", mode="slider")
                ),
                vol.Optional(
                    "observer_mode",
                    default=_c("observer_mode", DEFAULT_OBSERVER_MODE),
                ): selector.BooleanSelector(),
                # ``smart_night_charging`` removed in #277 Phase C — the
                # named ``charge_mode`` carries that intent (implicit ON
                # for ``min_plus_solar`` / ``solar_plus_cheap``). Phase B
                # already routed ``_smart_night_charging_enabled()``
                # through the mode resolver, so this options-flow field
                # has been inert for a release; Phase C removes it from
                # the UI to match.
            }),
        )

    async def async_step_settings_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Tariff & Advanced settings."""
        if user_input is not None:
            # Auto-detect dynamic tariff provider entity if mode=dynamic
            if user_input.get("tariff_mode") == "dynamic" and not user_input.get("dynamic_tariff_entity"):
                # Shared candidate matcher (#485 K5): the flow used to
                # keep its own pattern subset, which drifted from the
                # runtime provider's detection (it missed Octopus and
                # Amber despite the dropdown label promising them).
                from .tariff.tariff_provider import DynamicTariffProvider
                for state in self.hass.states.async_all("sensor"):
                    eid = state.entity_id
                    if DynamicTariffProvider.is_price_entity_candidate(eid):
                        user_input["dynamic_tariff_entity"] = eid
                        _LOGGER.info("Auto-detected dynamic tariff entity: %s", eid)
                        break
            self._data.update(user_input)
            return await self.async_step_load_management()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)
        currency = self.hass.config.currency or "EUR"

        return self.async_show_form(
            step_id="settings_tariff",
            data_schema=vol.Schema({
                vol.Optional(
                    "tariff_mode",
                    default=_c("tariff_mode", "static"),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "static", "label": "Static (fixed HT/NT rates)"},
                            {"value": "dynamic", "label": "Dynamic (Tibber / Nordpool / aWATTar / Amber / Octopus)"},
                            {"value": "calendar", "label": "Calendar (time-based HT/NT schedule)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Optional(
                    "dynamic_tariff_entity",
                    description={"suggested_value": current_config.get("dynamic_tariff_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                vol.Optional(
                    "dynamic_forecast_entity",
                    description={"suggested_value": current_config.get("dynamic_forecast_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["sensor", "event"])
                ),
                vol.Optional(
                    "dynamic_feedin_entity",
                    description={"suggested_value": current_config.get("dynamic_feedin_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor")
                ),
                # #359 — dynamic-tariff price classification mode. The
                # legacy fixed thresholds (0.15 / 0.35 CHF) mis-bucketed
                # everything as "normal" on UK/AU/NL providers whose
                # daily range is 0.05–0.80 €/kWh. Percentile (default)
                # bucket relative to today's 24-hour price distribution.
                vol.Optional(
                    "tariff_classification_mode",
                    default=_c("tariff_classification_mode", "percentile"),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "percentile", "label": "Percentile (relative to today's prices)"},
                            {"value": "static", "label": "Static (fixed cheap/expensive thresholds)"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                # #417: max raised 1.0 -> 5.0 (and export 0.5 -> 5.0) for
                # high-unit currencies (SEK/NOK/CZK/PLN ~1-5 per kWh) --
                # same fix the cheap/expensive threshold number entities
                # got in v1.7.0-beta.21. The import rate doubles as the
                # dynamic-tariff fallback price, so capping it at 1.0
                # forced a wrong fallback on those markets.
                vol.Optional(
                    "electricity_import_rate",
                    default=_c("electricity_import_rate", 0.3387),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=5.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")
                ),
                vol.Optional(
                    "electricity_off_peak_rate",
                    default=_c("electricity_off_peak_rate", None) or _c("electricity_nt_rate", 0.3387),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=5.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")
                ),
                vol.Optional(
                    "electricity_export_rate",
                    default=_c("electricity_export_rate", 0.075),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=5.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")
                ),
                vol.Optional(
                    "demand_charge_rate",
                    default=_c("demand_charge_rate", 4.32),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=20.0, step=0.01, unit_of_measurement=f"{currency}/kW/Mt", mode="box")
                ),
                vol.Optional(
                    "update_interval",
                    default=_c("update_interval", DEFAULT_UPDATE_INTERVAL),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=10, max=60, step=5, unit_of_measurement="s", mode="slider")
                ),
                vol.Optional(
                    "grid_import_power_entity",
                    description={"suggested_value": current_config.get("grid_import_power_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(
                    "grid_export_power_entity",
                    description={"suggested_value": current_config.get("grid_export_power_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
            }),
        )

    async def async_step_load_management(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle load management options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_heat_pump()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        data_defaults = {
            "load_management_enabled": _c("load_management_enabled", DEFAULT_LOAD_MANAGEMENT_ENABLED),
            "target_peak_limit": _c("target_peak_limit", DEFAULT_TARGET_PEAK_LIMIT),
            "warning_peak_level": _c("warning_peak_level", DEFAULT_WARNING_PEAK_LEVEL),
            "emergency_peak_level": _c("emergency_peak_level", DEFAULT_EMERGENCY_PEAK_LEVEL),
        }

        return self.async_show_form(
            step_id="load_management",
            data_schema=vol.Schema({
                vol.Required(
                    "load_management_enabled",
                    default=data_defaults["load_management_enabled"],
                ): selector.BooleanSelector(),
                vol.Required(
                    "target_peak_limit",
                    default=data_defaults["target_peak_limit"],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1.0, max=15.0, step=0.5, unit_of_measurement="kW", mode="slider"
                    )
                ),
                vol.Required(
                    "warning_peak_level",
                    default=data_defaults["warning_peak_level"],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1.0, max=15.0, step=0.5, unit_of_measurement="kW", mode="slider"
                    )
                ),
                vol.Required(
                    "emergency_peak_level",
                    default=data_defaults["emergency_peak_level"],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1.0, max=20.0, step=0.5, unit_of_measurement="kW", mode="slider"
                    )
                ),
            }),
            errors=errors
        )

    async def async_step_heat_pump(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle heat pump SG-Ready configuration.

        Two control paths are supported (#437):

        - **SG-Ready** — configure both relay entities. Drives the heat
          pump via the standard SG-Ready 4-state protocol (BLOCKED /
          NORMAL / BOOST / FORCE_ON). For Viessmann / Stiebel Eltron /
          Vaillant and similar hardware-relay setups.
        - **Climate-only** — configure only ``heat_pump_climate_entity``.
          Drives ``climate.set_temperature`` with ``boost_offset``
          increments when surplus is available. For Nibe, Mitsubishi,
          Daikin and any integration that exposes a climate entity but
          no SG-Ready binary inputs.

        Both paths can also coexist (SG-Ready relays + climate boost
        for additional thermal storage).

        Configuring no relays AND no climate entity = the heat pump
        step is intentionally skipped (existing behaviour, leaves the
        controller unregistered).
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # #437: validate the two-path rule — if the user fills ONE
            # of the relay entities but not BOTH, AND has no climate
            # entity, the controller can't be driven. Reject so the
            # user doesn't ship a half-configured heat pump that
            # silently does nothing.
            relay1 = user_input.get("heat_pump_relay1_entity")
            relay2 = user_input.get("heat_pump_relay2_entity")
            climate = user_input.get("heat_pump_climate_entity")
            has_one_relay = bool(relay1) ^ bool(relay2)
            has_climate = bool(climate)
            if has_one_relay and not has_climate:
                errors["base"] = "heat_pump_partial_relays"
            else:
                self._data.update(user_input)
                return await self.async_step_battery_scheduler()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        def _opt(key):
            v = current_config.get(key)
            return v if v is not None else None

        return self.async_show_form(
            step_id="heat_pump",
            data_schema=vol.Schema({
                vol.Optional(
                    "heat_pump_relay1_entity",
                    description={"suggested_value": _opt("heat_pump_relay1_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    "heat_pump_relay2_entity",
                    description={"suggested_value": _opt("heat_pump_relay2_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch")
                ),
                vol.Optional(
                    "heat_pump_invert_sg_ready",
                    default=_c("heat_pump_invert_sg_ready", False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "heat_pump_climate_entity",
                    description={"suggested_value": _opt("heat_pump_climate_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="climate")
                ),
                vol.Optional(
                    "heat_pump_power_sensor",
                    description={"suggested_value": _opt("heat_pump_power_sensor")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="power")
                ),
                vol.Optional(
                    "heat_pump_boost_offset",
                    default=_c("heat_pump_boost_offset", 2.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=10.0, step=0.5, unit_of_measurement="°C", mode="slider"
                    )
                ),
                vol.Optional(
                    "heat_pump_max_setpoint",
                    default=_c("heat_pump_max_setpoint", 55.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=30.0, max=80.0, step=1.0, unit_of_measurement="°C", mode="slider"
                    )
                ),
                vol.Optional(
                    "heat_pump_priority",
                    default=_c("heat_pump_priority", 4),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=10, step=1, mode="slider"
                    )
                ),
            }),
            errors=errors,
        )

    async def async_step_battery_scheduler(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle battery charge scheduler options (#6)."""
        errors: dict[str, str] = {}

        if user_input is not None:
            self._data.update(user_input)
            return await self.async_step_notifications()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        return self.async_show_form(
            step_id="battery_scheduler",
            data_schema=vol.Schema({
                vol.Optional(
                    "battery_charge_scheduler_enabled",
                    default=_c("battery_charge_scheduler_enabled", False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "battery_capacity_kwh",
                    default=_c("battery_capacity_kwh", 10.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=100, step=0.5,
                        unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    "battery_max_charge_power_w",
                    default=_c("battery_max_charge_power_w", 5000),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=500, max=25000, step=100,
                        unit_of_measurement="W",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    "battery_roundtrip_efficiency",
                    default=_c("battery_roundtrip_efficiency", 0.92),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.70, max=0.99, step=0.01,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    "battery_cycle_cost",
                    default=_c("battery_cycle_cost", 0.02),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=0.50, step=0.001,
                        unit_of_measurement="EUR/kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    "battery_precharge_trigger_hour",
                    default=_c("battery_precharge_trigger_hour", 21),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=18, max=23, step=1,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    "battery_replan_interval_min",
                    default=_c("battery_replan_interval_min", 30),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=5, max=120, step=5,
                        unit_of_measurement="min",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    "battery_prefer_consecutive_window",
                    default=_c("battery_prefer_consecutive_window", True),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "battery_max_target_soc",
                    default=_c("battery_max_target_soc", 95.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=5,
                        unit_of_measurement="%",
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    "battery_min_deficit_kwh",
                    default=_c("battery_min_deficit_kwh", 2.0),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.5, max=10, step=0.5,
                        unit_of_measurement="kWh",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Optional(
                    "battery_pessimism_weight",
                    default=_c("battery_pessimism_weight", 0.3),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0.0, max=1.0, step=0.1,
                        mode=selector.NumberSelectorMode.SLIDER,
                    )
                ),
                vol.Optional(
                    "battery_force_charge_negative_price",
                    default=_c("battery_force_charge_negative_price", True),
                ): selector.BooleanSelector(),
            }),
            errors=errors,
        )

    async def async_step_notifications(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Handle notification options."""
        errors: dict[str, str] = {}

        if user_input is not None:
            mobile_service = user_input.get("mobile_notification_service", "").strip()
            if user_input.get("enable_mobile_notifications", False) and mobile_service:
                svc_name = mobile_service.replace("notify.", "").split(".")[-1]
                if not (self.hass.services.has_service("notify", svc_name)
                        or self.hass.services.has_service("rest_command", svc_name)):
                    errors["mobile_notification_service"] = "service_not_found"

            if not errors:
                self._data.update(user_input)
                return self.async_create_entry(data=self._data)

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        suggestions = {
            "enable_charger_notifications": _c("enable_charger_notifications", True),
            "enable_mobile_notifications": _c("enable_mobile_notifications", False),
            "mobile_notification_service": _c("mobile_notification_service", ""),
        }

        notify_services = [{"value": "", "label": "None"}]
        try:
            services_dict = self.hass.services.async_services()
            if "notify" in services_dict:
                for service in services_dict["notify"].keys():
                    notify_services.append({
                        "value": service,
                        "label": f"notify.{service}"
                    })
            if "rest_command" in services_dict:
                for service in services_dict["rest_command"].keys():
                    notify_services.append({
                        "value": service,
                        "label": f"rest_command.{service}"
                    })
            notify_services[1:] = sorted(notify_services[1:], key=lambda x: x["label"])
        except Exception as e:
            _LOGGER.warning(f"Failed to get notification services: {e}")

        return self.async_show_form(
            step_id="notifications",
            data_schema=vol.Schema({
                vol.Optional(
                    "enable_charger_notifications",
                    default=suggestions.get("enable_charger_notifications", True),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "enable_mobile_notifications",
                    default=suggestions.get("enable_mobile_notifications", False),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "mobile_notification_service",
                    default=suggestions.get("mobile_notification_service", ""),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=notify_services,
                        mode=selector.SelectSelectorMode.DROPDOWN
                    )
                ),
            }),
            errors=errors
        )
