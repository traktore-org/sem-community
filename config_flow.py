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
    DEFAULT_PHASE_GUARD_TOPOLOGY,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_BATTERY_PRIORITY_SOC,
    DEFAULT_BATTERY_BUFFER_SOC,
    DEFAULT_BATTERY_AUTO_START_SOC,
    DEFAULT_MIN_SOLAR_POWER,
    DEFAULT_DAILY_EV_TARGET,
    DEFAULT_BATTERY_ASSIST_MAX_POWER,
    DEFAULT_BATTERY_ASSIST_MIN_SURPLUS,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_BATTERY_DISCHARGE_PROTECTION_ENABLED,
    DEFAULT_BATTERY_MAX_DISCHARGE_POWER,
    DEFAULT_PREFER_HARDWARE_ENERGY,
    DEFAULT_ENERGY_SOURCE_AUTO,
    DEFAULT_TARGET_PEAK_LIMIT,
    DEFAULT_WARNING_PEAK_LEVEL,
    DEFAULT_EMERGENCY_PEAK_LEVEL,
    DEFAULT_LOAD_MANAGEMENT_ENABLED,
    DEFAULT_OBSERVER_MODE,
    MIN_PEAK_LIMIT_KW,
    MAX_PEAK_LIMIT_KW,
    PEAK_LIMIT_STEP_KW,
    DEFAULT_PEAK_LIMIT_UNLIMITED,
)
from .coordinator.ev_taper_detector import resolve_charge_efficiency
from .coordinator.units import energy_state_to_kwh, normalize_unit
from .ha_energy_reader import read_energy_dashboard_config, EnergyDashboardConfig
from .hardware_detection import (
    HardwareDetector,
    discover_ev_charger_from_registry,
    discover_inverter_from_registry,
)

_LOGGER = logging.getLogger(__name__)

# #735 — ``ev_charger_efficiency`` is stored as the fraction the taper
# detector books with (0.5–1.0), but a percentage is what a charger's
# datasheet quotes and what the user is thinking in. The dialog is the only
# place the two units meet, so the conversion lives here and nowhere else.


def _efficiency_as_percent(stored: Any) -> int:
    """Stored fraction → the whole percent the dialog shows.

    Runs the value through the detector's resolver first, so a figure the
    booking is already ignoring (a hand-edited ``92``, a stray ``3.0``) is
    displayed as the default rather than as a number outside the box's own
    range — which HA refuses to submit, wedging the whole dialog.

    Round-trips exactly for anything the form itself wrote (whole percent →
    multiples of 0.01). A hand-edited 0.785 shows as 78 % and saves back as
    0.78: the field's resolution is one point, so sub-point precision cannot
    survive a visit to the dialog. Bounded and one-way.
    """
    return round(resolve_charge_efficiency(stored) * 100)


def _efficiency_from_percent(percent: Any) -> float:
    """The dialog's whole percent → the fraction the detector reads.

    Re-validating after the divide is not belt-and-braces: the step is also
    reachable from a raw ``config_entries/options/flow`` POST, which is not
    bound by the selector's 50–100 range.
    """
    try:
        fraction = float(percent) / 100.0
    except (TypeError, ValueError):
        return resolve_charge_efficiency(None)
    return resolve_charge_efficiency(fraction)


def _clearable_keys(schema: Any) -> set[str]:
    """The fields a form lets the user leave EMPTY.

    ``vol.Optional(key, description={"suggested_value": …})`` with no
    ``default`` is exactly HA's "may be absent": the marker only *suggests*
    a value, so an emptied field comes back as a MISSING key rather than an
    empty string. An Optional that carries a ``default`` is always filled in
    by validation, so it is never ambiguous and never clearable.
    """
    inner = getattr(schema, "schema", None)
    if not isinstance(inner, dict):
        return set()
    return {
        str(marker.schema)
        for marker in inner
        if isinstance(marker, vol.Optional)
        and getattr(marker, "default", vol.UNDEFINED) is vol.UNDEFINED
    }


def _merge_form_input(flow: Any, target: dict, user_input: dict) -> None:
    """Merge a submitted form into ``target``, honouring CLEARED fields.

    ``target.update(user_input)`` — what every step used to do — cannot tell
    "the user left this alone" from "the user emptied it", because HA drops
    an emptied optional field out of ``user_input`` altogether. The result
    is a config key that can be re-pointed but never taken back: a wrong
    auto-detected ``ev_start_stop_entity`` (#627's symptom), a mis-picked
    ``phase_guard_*`` sensor, a heat-pump relay on the wrong switch. The
    only recorded cure was deleting the integration.

    The missing input is *which fields this page offered* — and HA keeps it:
    ``flow.cur_step`` is the form it just showed, schema included. So the
    page itself decides what may be cleared, and no hand-written key list
    can drift away from the fields on screen.

    A cleared field is written as ``None``, not deleted. The runtime config
    is ``{**entry.data, **entry.options}`` and the options flow replaces
    options wholesale (#690), so deleting the key merely un-covers whatever
    initial setup wrote into ``entry.data`` and the cleared value returns.
    ``None`` is also the house spelling of "not set" — the v8→v9 migration
    seeds ``vehicle_min_current: None`` — and every consumer of these keys
    reads them for truth or with a falsy fallback.

    With no shown form to consult (a direct handler call), this degrades to
    a plain update: nothing to clear against.
    """
    cur_step = getattr(flow, "cur_step", None) or {}
    for key in _clearable_keys(cur_step.get("data_schema")):
        if key not in user_input:
            target[key] = None
    target.update(user_input)


# Every per-charger key that names an ENTITY, i.e. that says something about
# the physical box rather than about the car or about how to talk to it.
# Service names are deliberately absent: two KEBAs both answer to
# ``keba.set_current``, so a service is not an identity. Pinned against
# ``hardware_detection`` by tests/test_ev_charger_post_install_surface.py, so
# a brand that starts reporting a new entity key cannot quietly slip out of
# the comparison below.
_CHARGER_ENTITY_KEYS = frozenset({
    "ev_charge_mode_entity",
    "ev_charger_service_entity_id",
    "ev_charging_power_sensor",
    "ev_charging_sensor",
    "ev_connected_sensor",
    "ev_current_control_entity",
    "ev_current_sensor",
    "ev_session_energy_sensor",
    "ev_start_stop_entity",
    "ev_total_energy_sensor",
})


def _charger_entities(charger: Any) -> set[str]:
    """The entities a charger config points at — its fingerprint."""
    if not isinstance(charger, dict):
        return set()
    return {str(v) for k, v in charger.items() if k in _CHARGER_ENTITY_KEYS and v}


def _charger_already_installed(discovery: dict, installed: Any) -> bool:
    """Is this discovery a box the user already has?

    Compared by ENTITY OVERLAP. The dedup this replaces compared
    ``_device_id`` — a key ``hardware_detection`` puts on a *discovery* and
    that nothing ever writes onto the *stored* charger. So the set of
    already-known ids was always empty, every discovery always looked new,
    and the values offered for charger #2 were charger #1's own config: its
    sensors and its ``ev_charger_service``. Accept the suggestions and SEM
    drives the first box twice while the second one never moves.

    Entities are the right key because they are what actually gets stored,
    for every charger — including charger #0, which the initial setup flow
    creates and which can never carry a ``_device_id``, and including one
    that was configured by hand.
    """
    mine = _charger_entities(discovery)
    if not mine:
        return False
    return any(mine & _charger_entities(c) for c in (installed or []))


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
                    if val > 0:
                        # #641 — the unit half goes through units.py (so MWh
                        # converts too). The ``> 500`` magnitude heuristic
                        # applies ONLY to an UNLABELLED counter, which is the
                        # case it was written for: applying it after a unit
                        # conversion would divide a labelled 600 kWh bank twice.
                        labelled = bool(normalize_unit(state))
                        val = energy_state_to_kwh(state, default=val)
                        if not labelled and val > 500:
                            val = val / 1000  # unlabelled Wh → kWh
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
    # v17 (#758): write ``energy_plan_actuation`` down explicitly on upgrade
    #     and announce it once. The v1.8 plan drives hardware; the default
    #     is on, and a default nobody was told about is not consent.
    VERSION = 18

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
            # (#777) Record ALL persisted-switch defaults explicitly at
            # install: a key present in entry data means "this install
            # chose", so a dead install's restore-store ghost can never
            # speak for a fresh one. Only true legacy upgrades (no key
            # anywhere) keep the restore-state fallback.
            self._data["vacation_mode"] = False
            self._data["energy_plan_actuation"] = True
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
                _merge_form_input(self, self._data, user_input)
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
            # Load management — the grid ceiling used to be asked at install
            # (#717 removed that field: it duplicated the live Control-tab
            # slider and the Configure fallback, see docs/UI_PATTERNS.md).
            # Every value here is a safe default the user can tune later.
            "load_management_enabled": DEFAULT_LOAD_MANAGEMENT_ENABLED,
            "target_peak_limit": DEFAULT_TARGET_PEAK_LIMIT,
            "peak_limit_unlimited": DEFAULT_PEAK_LIMIT_UNLIMITED,
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
        """Final install step: dashboard style + auto-detected hardware.

        The grid peak limit used to be asked here too, but it duplicated the
        live Control-tab slider and the Configure options-flow fallback —
        three places to set one number (#717). It now seeds from
        ``DEFAULT_TARGET_PEAK_LIMIT`` like every other tunable and is tuned
        post-install. Auto-detects the inverter's battery discharge control
        entity from the entity registry. All other tunables are filled from
        ``_install_defaults()`` so the coordinator boots with a complete
        config dict.
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
                _merge_form_input(self, merged, user_input)

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


# #690 — every config key the options dialog itself OWNS (a form field on
# one of its pages, or a key its steps write into ``self._data`` directly).
# The final save replaces ``entry.options`` wholesale, so any option that is
# NOT in this set — values written by services (``grid_sign_user_flip``),
# dashboard entities (``battery_mode``, ``battery_reserve_soc``,
# ``vacation_mode``, price thresholds, …) or setup helpers — must be carried
# forward, or a config-dialog save silently erases it ("Grid Sign Always
# Changes Back"). Owned keys keep today's semantics: present in the submitted
# form = new value, omitted = cleared. tests/test_690_options_carry_forward.py
# recomputes this set from the flow source, so a new form field that isn't
# added here fails CI.
OPTIONS_FLOW_OWNED_KEYS = frozenset({
    # (#819) which solar-forecast integration SEM reads
    "solar_forecast_source",
    "action",
    "battery_assist_max_power",
    "battery_assist_min_surplus",
    "battery_auto_start_soc",
    "battery_buffer_soc",
    "battery_capacity_kwh",
    "battery_charge_platform",
    "battery_charge_scheduler_enabled",
    "battery_cycle_cost",
    "battery_discharge_control_entity",
    "battery_discharge_protection_enabled",
    "battery_force_charge_negative_price",
    "battery_max_charge_power_w",
    "battery_max_discharge_power",
    "battery_max_target_soc",
    "battery_min_deficit_kwh",
    "battery_pessimism_weight",
    "battery_precharge_trigger_hour",
    "battery_prefer_consecutive_window",
    "battery_priority_soc",
    "battery_replan_interval_min",
    "battery_roundtrip_efficiency",
    "charger_name",
    "charger_to_remove",
    "curtailment_probe_enabled",
    "daily_ev_target",
    "daily_ev_target_max",
    "demand_charge_rate",
    "deye_actuation_enabled",
    "deye_battery_voltage_entity",
    "deye_battery_voltage_max_age_s",
    "deye_bms_max_charge_current_a",
    "deye_charge_current_entity",
    "deye_force_charge_work_mode",
    "deye_grid_charge_switch",
    "deye_max_charge_current_a",
    "deye_max_discharge_power",
    "deye_observer_mode",
    "deye_program_control",
    "deye_program_groups",
    "deye_work_mode_battery_first_option",
    "deye_work_mode_control",
    "deye_work_mode_entity",
    "deye_work_mode_load_first_option",
    "diagram_style",
    "dynamic_feedin_entity",
    "dynamic_forecast_entity",
    "dynamic_tariff_entity",
    "electricity_export_rate",
    "electricity_import_rate",
    "electricity_off_peak_rate",
    "emergency_peak_level",
    "enable_charger_notifications",
    "enable_mobile_notifications",
    "ev_battery_capacity_kwh",
    "ev_charge_mode_entity",
    "ev_charge_mode_start",
    "ev_charge_mode_stop",
    "ev_charger_efficiency",
    "ev_charger_service",
    "ev_charger_service_entity_id",
    "ev_chargers",
    "ev_charging_power_sensor",
    "ev_charging_sensor",
    "ev_connected_sensor",
    "ev_current_control_entity",
    "ev_current_sensor",
    "ev_kwh_per_100km",
    "ev_min_current",
    "ev_phase_switch_entity",
    "ev_phase_switch_value_1p",
    "ev_phase_switch_value_3p",
    "ev_start_stop_entity",
    "ev_surplus_priority",
    "ev_target_soc",
    "ev_target_soc_max",
    "ev_total_energy_sensor",
    "export_limit_entity",
    "grid_export_power_entity",
    "grid_import_power_entity",
    "grid_import_surcharge",
    "grid_sign_invert",
    "heat_pump_boost_offset",
    "heat_pump_climate_entity",
    "heat_pump_invert_sg_ready",
    "heat_pump_max_setpoint",
    "heat_pump_power_sensor",
    "heat_pump_priority",
    "heat_pump_relay1_entity",
    "heat_pump_relay2_entity",
    "initial_current",
    "load_management_enabled",
    "minimum_solar_power",
    "mobile_notification_service",
    "observer_mode",
    "peak_limit_unlimited",
    "phase_guard_enabled",
    "phase_guard_enforcement_enabled",
    "phase_guard_notifications_enabled",
    "phase_guard_recovery_margin_a",
    "phase_guard_recovery_cycles",
    "phase_guard_topology",
    "phase_guard_grid_limit_a",
    "phase_guard_inverter_limit_a",
    "phase_guard_max_age_s",
    "phase_guard_phase_count",
    "phase_guard_grid_l1_current_entity",
    "phase_guard_grid_l2_current_entity",
    "phase_guard_grid_l3_current_entity",
    "phase_guard_grid_l1_power_entity",
    "phase_guard_grid_l2_power_entity",
    "phase_guard_grid_l3_power_entity",
    "phase_guard_grid_l1_voltage_entity",
    "phase_guard_grid_l2_voltage_entity",
    "phase_guard_grid_l3_voltage_entity",
    "phase_guard_inverter_l1_current_entity",
    "phase_guard_inverter_l2_current_entity",
    "phase_guard_inverter_l3_current_entity",
    "pv_string_names",
    "target_peak_limit",
    "tariff_classification_mode",
    "tariff_mode",
    "update_interval",
    "vehicle_min_current",
    "vehicle_range_entity",
    "vehicle_soc_entity",
    "warning_peak_level",
})


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

    def _discovered_pv_strings(self) -> dict:
        """(#566) Live coordinator's discovered PV-string slot->source map.

        Same source the ``pv_naming`` step reads; used by the charger menu to
        decide whether to offer the "Rename PV strings" shortcut. Empty when
        the coordinator/reader isn't up or fewer than 2 strings were found.
        """
        coordinator = self.hass.data.get(DOMAIN, {}).get(self.config_entry.entry_id)
        reader = getattr(coordinator, "_sensor_reader", None)
        return dict(getattr(reader, "_pv_strings", {}) or {})

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
            # #735 — the only place the percent the user sees becomes the
            # fraction everything downstream books with. Converted before the
            # two writes below so both copies carry the same number. The
            # membership test is for raw options-flow POSTs that omit the
            # field; a form submit always carries it (vol.Optional default).
            if "ev_charger_efficiency" in user_input:
                user_input = {
                    **user_input,
                    "ev_charger_efficiency": _efficiency_from_percent(
                        user_input["ev_charger_efficiency"]
                    ),
                }
            # Update both flat keys and ev_chargers[0] (#112)
            _merge_form_input(self, self._data, user_input)
            ev_chargers = list(self._data.get("ev_chargers") or self.config_entry.options.get("ev_chargers") or [])
            if ev_chargers:
                _merge_form_input(self, ev_chargers[0], user_input)
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
                # #735 — AC metered → DC in the pack. Sits next to capacity
                # because the two are read together: the estimate is
                # ``delivered kWh × efficiency ÷ capacity``. The band matches
                # what the detector will accept, in percent (see
                # ``_efficiency_as_percent``); offering a value the booking
                # then discards would be a setting that silently does nothing.
                vol.Optional(
                    "ev_charger_efficiency",
                    default=_efficiency_as_percent(
                        current_config.get("ev_charger_efficiency")
                    ),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=50, max=100, step=1, unit_of_measurement="%", mode="box"
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
                        min=0, max=100, step=5, unit_of_measurement="%", mode="slider"
                    )
                ),
                # Optional solar ceiling (Max): surplus charges up to this, then
                # stops. Defaults to full (100) = charge freely from sun (#245).
                vol.Optional(
                    "daily_ev_target_max",
                    default=_c("daily_ev_target_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=200, step=0.5, unit_of_measurement="kWh", mode="slider"
                    )
                ),
                vol.Optional(
                    "ev_target_soc_max",
                    default=_c("ev_target_soc_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=5, unit_of_measurement="%", mode="slider"
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
            if action == "rename_pv":
                # (#566) direct shortcut to PV-string naming — otherwise it's
                # only reachable 7 forms deep via "Continue".
                self._pv_naming_return = "menu"
                return await self.async_step_pv_naming()
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
        # (#566) Direct entry point to PV-string naming when ≥2 strings exist —
        # so it's discoverable, not buried at the end of the settings chain.
        if len(self._discovered_pv_strings()) >= 2:
            options.append(
                {"value": "rename_pv", "label": "Rename PV strings"},
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
        # Offer only a box the user does NOT already have — see
        # ``_charger_already_installed`` for why the fingerprint is the
        # entities and not ``_device_id``.
        installed = self._data.get("ev_chargers", [])
        new_discoveries = [
            c for c in all_discovered if not _charger_already_installed(c, installed)
        ]
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
                # #627 (bug class 30): ``__init__.py`` reads all four keys
                # below off the per-charger dict and ``hardware_detection``
                # auto-fills them for several brands — but none had an
                # editable surface, so a wrong or missing auto-detect could
                # not be corrected, and a charger ADDED after install never
                # got them at all. The reported symptom: a box that keeps
                # its contactor closed at 0 A had no way to be told to open.
                vol.Optional(
                    "ev_start_stop_entity",
                    description={"suggested_value": suggestions.get("ev_start_stop_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "button"])
                ),
                vol.Optional(
                    "ev_current_sensor",
                    description={"suggested_value": suggestions.get("ev_current_sensor")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="current")
                ),
                vol.Optional(
                    "ev_charge_mode_entity",
                    description={"suggested_value": suggestions.get("ev_charge_mode_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
                vol.Optional(
                    "ev_charge_mode_start",
                    description={"suggested_value": suggestions.get("ev_charge_mode_start")},
                ): selector.TextSelector(),
                vol.Optional(
                    "ev_charge_mode_stop",
                    description={"suggested_value": suggestions.get("ev_charge_mode_stop")},
                ): selector.TextSelector(),
                # (#804 Phase A) The entity that PERFORMS a 1/3-phase switch
                # when the hardware has one (go-e's psm select, KEBA
                # X-series number, openWB switch). Named, never inferred
                # (evcc #30143). Observe-only until Phase B.
                vol.Optional(
                    "ev_phase_switch_entity",
                    description={"suggested_value": suggestions.get("ev_phase_switch_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=[
                        "select", "number", "switch",
                        "input_select", "input_number", "input_boolean",
                    ])
                ),
                # The 1p/3p positions in the entity's own vocabulary.
                # Required for a select (its option strings are the
                # device's language — never guessed); number defaults to
                # 1/3 and switch to off/on when left empty.
                vol.Optional(
                    "ev_phase_switch_value_1p",
                    description={"suggested_value": suggestions.get("ev_phase_switch_value_1p")},
                ): selector.TextSelector(),
                vol.Optional(
                    "ev_phase_switch_value_3p",
                    description={"suggested_value": suggestions.get("ev_phase_switch_value_3p")},
                ): selector.TextSelector(),
                # #604: ONE priority axis — the unified device-priority list
                # (#576). Shed order under peak is the reverse list walk
                # (#470: higher list number sheds first), so there is no
                # separate shed slider.
                vol.Optional(
                    "ev_surplus_priority",
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
                        min=0, max=200, step=0.5,
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
                        min=0, max=200, step=0.5,
                        unit_of_measurement="kWh", mode="slider",
                    )
                ),
                vol.Optional(
                    "initial_current",
                    default=self._data.get("initial_current", 10),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=32, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_min_current",
                    default=self._data.get("ev_min_current", 6),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=16, step=1,
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
                        min=0, max=100, step=5,
                        unit_of_measurement="%", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_target_soc_max",
                    default=self._data.get("ev_target_soc_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=5,
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
            _merge_form_input(self, charger, user_input)
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
                # #627 — see async_step_ev_charger_add for the why.
                vol.Optional(
                    "ev_start_stop_entity",
                    description={"suggested_value": charger.get("ev_start_stop_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "button"])
                ),
                vol.Optional(
                    "ev_current_sensor",
                    description={"suggested_value": charger.get("ev_current_sensor")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="sensor", device_class="current")
                ),
                vol.Optional(
                    "ev_charge_mode_entity",
                    description={"suggested_value": charger.get("ev_charge_mode_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="select")
                ),
                vol.Optional(
                    "ev_charge_mode_start",
                    description={"suggested_value": charger.get("ev_charge_mode_start")},
                ): selector.TextSelector(),
                vol.Optional(
                    "ev_charge_mode_stop",
                    description={"suggested_value": charger.get("ev_charge_mode_stop")},
                ): selector.TextSelector(),
                # (#804 Phase A) See async_step_ev_charger_add for the why.
                vol.Optional(
                    "ev_phase_switch_entity",
                    description={"suggested_value": charger.get("ev_phase_switch_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=[
                        "select", "number", "switch",
                        "input_select", "input_number", "input_boolean",
                    ])
                ),
                vol.Optional(
                    "ev_phase_switch_value_1p",
                    description={"suggested_value": charger.get("ev_phase_switch_value_1p")},
                ): selector.TextSelector(),
                vol.Optional(
                    "ev_phase_switch_value_3p",
                    description={"suggested_value": charger.get("ev_phase_switch_value_3p")},
                ): selector.TextSelector(),
                # #604: ONE priority axis — the unified device-priority list
                # (#576). Lower number = charges first on surplus; shed
                # order under peak is the reverse list walk (#470: higher
                # list number sheds first). The legacy per-charger
                # ``ev_shed_priority`` slider is retired.
                vol.Optional(
                    "ev_surplus_priority",
                    default=charger.get("ev_surplus_priority", 5),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=1, max=10, step=1, mode="slider")
                ),
                # Per-charger night charging settings (#193)
                vol.Optional(
                    "daily_ev_target",
                    default=charger.get("daily_ev_target", self._data.get("daily_ev_target", 10)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=200, step=0.5,
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
                        min=0, max=200, step=0.5,
                        unit_of_measurement="kWh", mode="slider",
                    )
                ),
                vol.Optional(
                    "initial_current",
                    default=charger.get("initial_current", self._data.get("initial_current", 10)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=32, step=1,
                        unit_of_measurement="A", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_min_current",
                    default=charger.get("ev_min_current", self._data.get("ev_min_current", 6)),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=1, max=16, step=1,
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
                        min=1, max=32, step=1,
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
                        min=0, max=100, step=5,
                        unit_of_measurement="%", mode="slider",
                    )
                ),
                vol.Optional(
                    "ev_target_soc_max",
                    default=charger.get("ev_target_soc_max", 100),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=0, max=100, step=5,
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
            _merge_form_input(self, self._data, user_input)
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
                    "battery_capacity_kwh",
                    default=_c("battery_capacity_kwh", DEFAULT_BATTERY_CAPACITY_KWH),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=5, max=100, step=1, unit_of_measurement="kWh", mode="slider")
                ),
                vol.Optional(
                    "battery_assist_max_power",
                    default=_c("battery_assist_max_power", _c("super_charger_power", DEFAULT_BATTERY_ASSIST_MAX_POWER)),
                ): selector.NumberSelector(
                    # #689: 25 kW ceiling (was 10 kW) — matches the charge-power
                    # slider; a Flexboss 21 discharges 12 kW, parallel stacks more.
                    selector.NumberSelectorConfig(min=1000, max=25000, step=500, unit_of_measurement="W", mode="slider")
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
                    # #689: 25 kW ceiling (was 10 kW) — see battery_assist_max_power.
                    selector.NumberSelectorConfig(min=500, max=25000, step=250, unit_of_measurement="W", mode="slider")
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
        """EV charging, solar and observer-mode settings."""
        if user_input is not None:
            _merge_form_input(self, self._data, user_input)
            return await self.async_step_settings_phase_guard_topology()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        return self.async_show_form(
            step_id="settings_ev",
            data_schema=vol.Schema({
                vol.Optional(
                    "daily_ev_target",
                    default=_c("daily_ev_target", DEFAULT_DAILY_EV_TARGET),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0, max=200, step=0.5, unit_of_measurement="kWh", mode="slider")
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
                # #743 — the curtailment probe (opt-in, default off): when
                # an export-limited inverter clamps production to
                # consumption, probe with the EV at minimum amps and
                # harvest the solar the forecast says is hidden.
                vol.Optional(
                    "curtailment_probe_enabled",
                    default=bool(_c("curtailment_probe_enabled", False)),
                ): selector.BooleanSelector(),
                vol.Optional(
                    "export_limit_entity",
                    description={"suggested_value": current_config.get("export_limit_entity") or None},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["number", "sensor", "select"])
                ),
            }),
        )

    async def async_step_settings_phase_guard_topology(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Choose which electrical lanes need independent phase protection."""
        if user_input is not None:
            topology = user_input["phase_guard_topology"]
            user_input["phase_guard_phase_count"] = int(
                user_input.get("phase_guard_phase_count", 3)
            )
            _merge_form_input(self, self._data, user_input)
            self._data["phase_guard_enabled"] = topology != "disabled"
            if topology == "disabled":
                return await self.async_step_settings_tariff()
            return await self.async_step_settings_phase_guard()

        current_config = {
            **self.config_entry.data,
            **self.config_entry.options,
            **self._data,
        }
        topology = current_config.get("phase_guard_topology")
        if topology not in {"disabled", "grid_only", "hybrid_load_port"}:
            topology = "disabled"

        return self.async_show_form(
            step_id="settings_phase_guard_topology",
            data_schema=vol.Schema({
                vol.Required(
                    "phase_guard_topology",
                    default=topology,
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            "disabled",
                            "grid_only",
                            "hybrid_load_port",
                        ],
                        translation_key="phase_guard_topology",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    "phase_guard_phase_count",
                    default=str(self._cfg(current_config, "phase_guard_phase_count", 3)),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["1", "3"],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
            }),
        )

    async def async_step_settings_phase_guard(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Map per-phase sensors for the selected electrical topology."""
        if user_input is not None:
            _merge_form_input(self, self._data, user_input)
            return await self.async_step_settings_tariff()

        current_config = {
            **self.config_entry.data,
            **self.config_entry.options,
            **self._data,
        }
        topology = current_config.get(
            "phase_guard_topology", DEFAULT_PHASE_GUARD_TOPOLOGY
        )
        try:
            phase_count = int(current_config.get("phase_guard_phase_count", 3))
        except (TypeError, ValueError):
            phase_count = 3
        if phase_count not in {1, 3}:
            phase_count = 3
        from .coordinator.phase_current_discovery import (
            discover_grid_phase_current_entities,
        )

        discovered_currents = {}
        if not any(
            current_config.get(f"phase_guard_grid_l{phase}_current_entity")
            for phase in range(1, phase_count + 1)
        ):
            discovered_currents = discover_grid_phase_current_entities(
                self.hass.states.async_all("sensor"), phase_count=phase_count
            )

        fields: dict[Any, Any] = {
            vol.Optional(
                "phase_guard_enforcement_enabled",
                default=self._cfg(
                    current_config, "phase_guard_enforcement_enabled", False
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                "phase_guard_notifications_enabled",
                default=self._cfg(
                    current_config, "phase_guard_notifications_enabled", True
                ),
            ): selector.BooleanSelector(),
            vol.Optional(
                "phase_guard_recovery_margin_a",
                default=self._cfg(
                    current_config, "phase_guard_recovery_margin_a", 2.0
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=0.5,
                    max=10.0,
                    step=0.5,
                    unit_of_measurement="A",
                    mode="box",
                )
            ),
            vol.Optional(
                "phase_guard_recovery_cycles",
                default=self._cfg(
                    current_config, "phase_guard_recovery_cycles", 3
                ),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1,
                    max=12,
                    step=1,
                    mode="box",
                )
            ),
            vol.Optional(
                "phase_guard_grid_limit_a",
                default=self._cfg(current_config, "phase_guard_grid_limit_a", 16.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1.0,
                    max=63.0,
                    step=0.5,
                    unit_of_measurement="A",
                    mode="box",
                )
            ),
            vol.Optional(
                "phase_guard_max_age_s",
                default=self._cfg(current_config, "phase_guard_max_age_s", 30.0),
            ): selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=5.0,
                    max=300.0,
                    step=5.0,
                    unit_of_measurement="s",
                    mode="box",
                )
            ),
        }
        sensor_selector = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="sensor")
        )
        fields.update({
            vol.Optional(
                "phase_guard_grid_l1_current_entity",
                description={
                    "suggested_value": current_config.get(
                        "phase_guard_grid_l1_current_entity"
                    )
                    or discovered_currents.get(
                        "phase_guard_grid_l1_current_entity"
                    )
                    or None
                },
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l2_current_entity",
                description={
                    "suggested_value": current_config.get(
                        "phase_guard_grid_l2_current_entity"
                    )
                    or discovered_currents.get(
                        "phase_guard_grid_l2_current_entity"
                    )
                    or None
                },
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l3_current_entity",
                description={
                    "suggested_value": current_config.get(
                        "phase_guard_grid_l3_current_entity"
                    )
                    or discovered_currents.get(
                        "phase_guard_grid_l3_current_entity"
                    )
                    or None
                },
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l1_power_entity",
                description={"suggested_value": current_config.get("phase_guard_grid_l1_power_entity") or None},
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l2_power_entity",
                description={"suggested_value": current_config.get("phase_guard_grid_l2_power_entity") or None},
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l3_power_entity",
                description={"suggested_value": current_config.get("phase_guard_grid_l3_power_entity") or None},
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l1_voltage_entity",
                description={"suggested_value": current_config.get("phase_guard_grid_l1_voltage_entity") or None},
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l2_voltage_entity",
                description={"suggested_value": current_config.get("phase_guard_grid_l2_voltage_entity") or None},
            ): sensor_selector,
            vol.Optional(
                "phase_guard_grid_l3_voltage_entity",
                description={"suggested_value": current_config.get("phase_guard_grid_l3_voltage_entity") or None},
            ): sensor_selector,
        })
        if phase_count == 1:
            fields = {
                marker: value
                for marker, value in fields.items()
                if "_l2_" not in marker.schema and "_l3_" not in marker.schema
            }

        if topology == "hybrid_load_port":
            fields[
                vol.Optional(
                    "phase_guard_inverter_limit_a",
                    default=self._cfg(
                        current_config, "phase_guard_inverter_limit_a", 16.0
                    ),
                )
            ] = selector.NumberSelector(
                selector.NumberSelectorConfig(
                    min=1.0,
                    max=63.0,
                    step=0.5,
                    unit_of_measurement="A",
                    mode="box",
                )
            )
            fields.update({
                vol.Optional(
                    "phase_guard_inverter_l1_current_entity",
                    description={"suggested_value": current_config.get("phase_guard_inverter_l1_current_entity") or None},
                ): sensor_selector,
                vol.Optional(
                    "phase_guard_inverter_l2_current_entity",
                    description={"suggested_value": current_config.get("phase_guard_inverter_l2_current_entity") or None},
                ): sensor_selector,
                vol.Optional(
                    "phase_guard_inverter_l3_current_entity",
                    description={"suggested_value": current_config.get("phase_guard_inverter_l3_current_entity") or None},
                ): sensor_selector,
            })
            if phase_count == 1:
                fields = {
                    marker: value
                    for marker, value in fields.items()
                    if "_l2_" not in marker.schema and "_l3_" not in marker.schema
                }

        topology_summary = (
            "grid and inverter Load/EPS output"
            if topology == "hybrid_load_port"
            else "grid supply"
        )
        return self.async_show_form(
            step_id="settings_phase_guard",
            data_schema=vol.Schema(fields),
            description_placeholders={"topology": topology_summary},
        )

    async def async_step_settings_tariff(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """Tariff & Advanced settings."""
        if user_input is not None:
            # The surcharge field is hidden outside dynamic mode, but it is
            # still an options-flow-owned key. Preserve an existing value
            # while static/calendar is selected so a temporary mode switch
            # cannot silently erase the user's dynamic-tariff configuration.
            current_config = {
                **self.config_entry.data,
                **self.config_entry.options,
            }
            if (
                user_input.get("tariff_mode") != "dynamic"
                and "grid_import_surcharge" not in user_input
                and "grid_import_surcharge" in current_config
            ):
                user_input["grid_import_surcharge"] = current_config[
                    "grid_import_surcharge"
                ]
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
            _merge_form_input(self, self._data, user_input)
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
                            {"value": "dynamic", "label": "Dynamic / price sensor (Tibber / Nordpool / aWATTar / Amber / Octopus — or any entity with the current price as state, e.g. a template sensor)"},
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
                # (#819) WHICH solar forecast integration SEM reads.
                # Deliberately next to the price-forecast entity above,
                # because the setup guide confused the two and promised
                # this override on that field. "Auto" keeps the historic
                # ladder (Solcast, then Forecast.Solar, then Open-Meteo);
                # naming one wins only while it is actually installed.
                vol.Optional(
                    "solar_forecast_source",
                    default=current_config.get("solar_forecast_source", "auto"),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "auto", "label": "Auto-detect (Solcast, then Forecast.Solar, then Open-Meteo)"},
                            {"value": "solcast", "label": "Solcast PV Solar"},
                            {"value": "forecast_solar", "label": "Forecast.Solar"},
                            {"value": "open_meteo", "label": "Open-Meteo Solar Forecast"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
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
                    selector.NumberSelectorConfig(min=0.0, max=10000.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")  # #549 currency-agnostic
                ),
                vol.Optional(
                    "electricity_off_peak_rate",
                    default=_c("electricity_off_peak_rate", None) or _c("electricity_nt_rate", 0.3387),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=10000.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")  # #549 currency-agnostic
                ),
                vol.Optional(
                    "electricity_export_rate",
                    default=_c("electricity_export_rate", 0.075),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=10000.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")  # #549 currency-agnostic
                ),
                vol.Optional(
                    "demand_charge_rate",
                    default=_c("demand_charge_rate", 4.32),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(min=0.0, max=100000.0, step=0.01, unit_of_measurement=f"{currency}/kW/Mt", mode="box")  # #549 currency-agnostic
                ),
                # Grid import surcharge is meaningful only for dynamic
                # tariffs. Static/calendar providers never consume it, so
                # hiding it there avoids a silent no-op configuration.
                **({
                    vol.Optional(
                        "grid_import_surcharge",
                        default=_c("grid_import_surcharge", 0.0),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(min=0.0, max=10000.0, step=0.001, unit_of_measurement=f"{currency}/kWh", mode="box")  # #549 currency-agnostic / SEK/NOK/HUF-safe
                    ),
                } if _c("tariff_mode", "static") == "dynamic" else {}),
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
            # (#717) The three levels are an ordered ladder, and getting the
            # order wrong is silently destructive rather than merely odd: an
            # emergency level at or below the target means ``LoadManager``
            # escalates to EMERGENCY shedding before the target it is meant
            # to defend is even reached. Raising the target and leaving the
            # other two at their old values is the easy way to land here, so
            # say so instead of saving it.
            #
            # (#716) An install with no grid ceiling has no ladder to order,
            # so skip the check rather than force three meaningless numbers
            # into line before the user can save the opt-out.
            _target = float(user_input.get("target_peak_limit", 0) or 0)
            _warn = float(user_input.get("warning_peak_level", 0) or 0)
            _emerg = float(user_input.get("emergency_peak_level", 0) or 0)
            if not user_input.get("peak_limit_unlimited", False):
                if _warn >= _target:
                    errors["warning_peak_level"] = "peak_warning_not_below_target"
                if _emerg <= _target:
                    errors["emergency_peak_level"] = "peak_emergency_not_above_target"

            if not errors:
                _merge_form_input(self, self._data, user_input)
                return await self.async_step_heat_pump()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        data_defaults = {
            "load_management_enabled": _c("load_management_enabled", DEFAULT_LOAD_MANAGEMENT_ENABLED),
            "target_peak_limit": _c("target_peak_limit", DEFAULT_TARGET_PEAK_LIMIT),
            "warning_peak_level": _c("warning_peak_level", DEFAULT_WARNING_PEAK_LEVEL),
            "emergency_peak_level": _c("emergency_peak_level", DEFAULT_EMERGENCY_PEAK_LEVEL),
            "peak_limit_unlimited": _c("peak_limit_unlimited", DEFAULT_PEAK_LIMIT_UNLIMITED),
        }

        return self.async_show_form(
            step_id="load_management",
            data_schema=vol.Schema({
                vol.Required(
                    "load_management_enabled",
                    default=data_defaults["load_management_enabled"],
                ): selector.BooleanSelector(),
                # (#716) The opt-out for installs whose grid connection is
                # large enough that no household load can threaten it. Its own
                # boolean, NOT ``load_management_enabled = False``: that switch
                # only stops SEM *shedding*, while the ceiling still constrains
                # everything SEM *sizes* (the EV night rate above all). Turning
                # off shedding and silently going unlimited would hand an EV
                # the whole house.
                vol.Required(
                    "peak_limit_unlimited",
                    default=data_defaults["peak_limit_unlimited"],
                ): selector.BooleanSelector(),
                # (#717) All three share one range and a box input — see the
                # install step for why a slider is wrong here. They used to
                # cap at 15/15/20 kW, which no North-American service fits.
                vol.Required(
                    "target_peak_limit",
                    default=data_defaults["target_peak_limit"],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_PEAK_LIMIT_KW, max=MAX_PEAK_LIMIT_KW,
                        step=PEAK_LIMIT_STEP_KW,
                        unit_of_measurement="kW", mode="box"
                    )
                ),
                vol.Required(
                    "warning_peak_level",
                    default=data_defaults["warning_peak_level"],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_PEAK_LIMIT_KW, max=MAX_PEAK_LIMIT_KW,
                        step=PEAK_LIMIT_STEP_KW,
                        unit_of_measurement="kW", mode="box"
                    )
                ),
                vol.Required(
                    "emergency_peak_level",
                    default=data_defaults["emergency_peak_level"],
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=MIN_PEAK_LIMIT_KW, max=MAX_PEAK_LIMIT_KW,
                        step=PEAK_LIMIT_STEP_KW,
                        unit_of_measurement="kW", mode="box"
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
          pump via the standard SG-Ready relay table: NORMAL / BOOST /
          FORCE_ON. State 1 (BLOCKED) is the grid operator's own
          ripple-control lock — SEM does not drive it and has no
          Sperrzeiten surface (#664). For Viessmann / Stiebel Eltron /
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
                _merge_form_input(self, self._data, user_input)
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
                    selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
                ),
                vol.Optional(
                    "heat_pump_relay2_entity",
                    description={"suggested_value": _opt("heat_pump_relay2_entity")},
                ): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=["switch", "input_boolean"])
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
            _merge_form_input(self, self._data, user_input)
            if self._data.get("battery_charge_platform") == "deye":
                return await self.async_step_deye()
            return await self.async_step_pv_naming()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)

        return self.async_show_form(
            step_id="battery_scheduler",
            data_schema=vol.Schema({
                vol.Optional(
                    "battery_charge_platform",
                    default=_c("battery_charge_platform", "generic"),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=[
                            {"value": "generic", "label": "Generic / other"},
                            {"value": "deye", "label": "Deye hybrid inverter"},
                        ],
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                ),
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

    async def async_step_deye(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """(#709) Deye forced-grid-charge configuration section.

        Lets an operator wire a Deye hybrid inverter without editing YAML:
        the grid-charge switch, the charge-current number (unit A), the
        battery-voltage sensor, exactly six program groups (time/soc/charge
        entities), a safe max current, an optional BMS max current, an
        optional Work Mode select with two distinct mapping values, and the
        two safety gates (observer mode default **on**, actuation default
        **off** — so a bare config never writes until explicitly enabled).

        The submitted form is normalised into the documented Deye contract
        keys read by ``DeyeBatteryAdapter`` (``deye_program_groups`` as a
        list of six {time, soc, charge} dicts). Booleans stay real bools.
        The runtime snapshot store is never part of entry options — it is
        attached to the adapter at runtime, not serialised here.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            # Keep only the Deye-owned keys so a generic/other platform
            # doesn't accumulate stale deye_* keys.
            clean = {k: v for k, v in user_input.items() if k.startswith("deye_")}
            self._data["battery_charge_platform"] = user_input.get(
                "battery_charge_platform",
                self._data.get("battery_charge_platform", "generic"),
            )
            if self._data["battery_charge_platform"] == "deye":
                # Normalise the six numbered program groups into the list shape.
                groups = []
                for n in range(1, 7):
                    group = {
                        "time": clean.get(f"deye_program_{n}_time", "").strip(),
                        "soc": clean.get(f"deye_program_{n}_soc", "").strip(),
                        "charge": clean.get(f"deye_program_{n}_charge", "").strip(),
                    }
                    groups.append(group)
                self._data["deye_program_groups"] = groups

                # Validation: exactly six complete groups.
                if len(groups) != 6 or not all(
                    g["time"] and g["soc"] and g["charge"] for g in groups
                ):
                    errors["base"] = "deye_program_groups_incomplete"

                # Work Mode mappings must be explicit and distinct when enabled.
                load_first = clean.get("deye_work_mode_load_first_option", "").strip()
                battery_first = clean.get(
                    "deye_work_mode_battery_first_option", ""
                ).strip()
                if clean.get("deye_work_mode_control") is True:
                    if not load_first or not battery_first or load_first == battery_first:
                        errors["deye_work_mode_battery_first_option"] = (
                            "deye_work_mode_mapping_not_distinct"
                        )
                    force_mode = clean.get("deye_force_charge_work_mode", "")
                    if force_mode not in ("load_first", "battery_first"):
                        errors["deye_force_charge_work_mode"] = (
                            "deye_force_charge_work_mode_invalid"
                        )

                # Safety booleans must stay real bools (never strings).
                self._data["deye_observer_mode"] = clean.get(
                    "deye_observer_mode", True,
                ) is True
                self._data["deye_actuation_enabled"] = clean.get(
                    "deye_actuation_enabled", False,
                ) is True
                self._data["deye_program_control"] = clean.get(
                    "deye_program_control", True,
                ) is True
                self._data["deye_work_mode_control"] = clean.get(
                    "deye_work_mode_control", False,
                ) is True
                # Copy the scalar Deye config terms through.
                for key in (
                    "deye_grid_charge_switch",
                    "deye_charge_current_entity",
                    "deye_battery_voltage_entity",
                    "deye_battery_voltage_max_age_s",
                    "deye_max_charge_current_a",
                    "deye_bms_max_charge_current_a",
                    "deye_max_discharge_power",
                    "deye_work_mode_entity",
                    "deye_work_mode_load_first_option",
                    "deye_work_mode_battery_first_option",
                    "deye_force_charge_work_mode",
                ):
                    if clean.get(key) is not None:
                        self._data[key] = clean[key]
            else:
                # Non-Deye platform: drop stale Deye keys from the payload.
                for key in list(self._data.keys()):
                    if key.startswith("deye_") or key == "deye_program_groups":
                        self._data.pop(key, None)

            if not errors:
                return await self.async_step_pv_naming()

        current_config = {**self.config_entry.data, **self.config_entry.options}
        _c = lambda key, fb: self._cfg(current_config, key, fb)
        _platform = _c("battery_charge_platform", "generic")

        # Re-populate the six program slots from what was actually persisted.
        # Save normalises the numbered form fields into the ``deye_program_groups``
        # list (above), and the flat ``deye_program_<n>_<kind>`` keys are never
        # stored — so on reopen the fields must read the list shape (with the
        # numbered keys as fallback), mirroring the adapter's own slot
        # resolution order. Reading only the flat keys left every slot blank.
        _groups = current_config.get("deye_program_groups")

        def _prog(n: int, kind: str):
            if isinstance(_groups, list) and len(_groups) >= n:
                group = _groups[n - 1]
                if isinstance(group, dict):
                    value = group.get(kind)
                    if value:
                        return value
            return _c(f"deye_program_{n}_{kind}", None)

        return self.async_show_form(
            step_id="deye",
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        "deye_grid_charge_switch",
                        description={"suggested_value": _c("deye_grid_charge_switch", None)},
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="switch")
                    ),
                    vol.Optional(
                        "deye_charge_current_entity",
                        description={"suggested_value": _c("deye_charge_current_entity", None)},
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain=["number", "input_number"])
                    ),
                    vol.Optional(
                        "deye_battery_voltage_entity",
                        description={"suggested_value": _c("deye_battery_voltage_entity", None)},
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="sensor")
                    ),
                    vol.Optional(
                        "deye_battery_voltage_max_age_s",
                        default=_c("deye_battery_voltage_max_age_s", 30),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=600, step=1,
                            unit_of_measurement="s",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "deye_max_charge_current_a",
                        default=_c("deye_max_charge_current_a", 25),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=1, max=100, step=1,
                            unit_of_measurement="A",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "deye_bms_max_charge_current_a",
                        default=_c("deye_bms_max_charge_current_a", 0),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=200, step=1,
                            unit_of_measurement="A",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "deye_max_discharge_power",
                        default=_c("deye_max_discharge_power", 0),
                    ): selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            min=0, max=50000, step=100,
                            unit_of_measurement="W",
                            mode=selector.NumberSelectorMode.BOX,
                        )
                    ),
                    vol.Optional(
                        "deye_program_control",
                        default=_c("deye_program_control", True),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        "deye_observer_mode",
                        default=_c("deye_observer_mode", True),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        "deye_actuation_enabled",
                        default=_c("deye_actuation_enabled", False),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        "deye_work_mode_control",
                        default=_c("deye_work_mode_control", False),
                    ): selector.BooleanSelector(),
                    vol.Optional(
                        "deye_work_mode_entity",
                        description={"suggested_value": _c("deye_work_mode_entity", None)},
                    ): selector.EntitySelector(
                        selector.EntitySelectorConfig(domain="select")
                    ),
                    vol.Optional(
                        "deye_work_mode_load_first_option",
                        description={"suggested_value": _c("deye_work_mode_load_first_option", "Load First")},
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Optional(
                        "deye_work_mode_battery_first_option",
                        description={"suggested_value": _c("deye_work_mode_battery_first_option", "Battery First")},
                    ): selector.TextSelector(
                        selector.TextSelectorConfig(type=selector.TextSelectorType.TEXT)
                    ),
                    vol.Optional(
                        "deye_force_charge_work_mode",
                        default=_c("deye_force_charge_work_mode", "battery_first"),
                    ): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {"value": "load_first", "label": "Load First"},
                                {"value": "battery_first", "label": "Battery First"},
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    ),
                }
                | {
                    vol.Optional(
                        f"deye_program_{n}_{kind}",
                        description={"suggested_value": _prog(n, kind)},
                    ): (
                        selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="time")
                        )
                        if kind == "time"
                        else selector.EntitySelector(
                            selector.EntitySelectorConfig(domain=["number", "input_number"])
                        )
                        if kind == "soc"
                        else selector.EntitySelector(
                            selector.EntitySelectorConfig(domain="select")
                        )
                    )
                    for n in range(1, 7)
                    for kind in ("time", "soc", "charge")
                }
            ),
            errors=errors,
            description_placeholders={
                "platform": _platform,
            },
        )

    async def async_step_pv_naming(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """(#566) Name the per-PV-string sensors (East/South/West …).

        Only shown when ≥ 2 strings were discovered. Each field is labelled
        with its source sensor + live power so the user can tell which slot is
        which physical panel (the slots are ordered by the Energy-Dashboard
        solar-sensor list, not by compass direction).
        """
        # Reach the live coordinator's discovered slot -> source map.
        coordinator = self.hass.data.get(DOMAIN, {}).get(
            self.config_entry.entry_id
        )
        reader = getattr(coordinator, "_sensor_reader", None)
        pv_strings = dict(getattr(reader, "_pv_strings", {}) or {})

        # < 2 strings → nothing to name, skip straight on. Carry any
        # previously-saved names forward so this save (which replaces the whole
        # options dict via async_create_entry) does not erase them when the
        # step is skipped (e.g. discovery hasn't run yet). Mirrors the
        # ev_chargers carry-forward pattern above.
        if len(pv_strings) < 2:
            existing = self.config_entry.options.get("pv_string_names")
            if existing:
                self._data.setdefault("pv_string_names", existing)
            return await self.async_step_notifications()

        slots = sorted(pv_strings.keys())

        if user_input is not None:
            names = {
                slot: str(user_input.get(f"pv_name_{slot}", "") or "").strip()
                for slot in slots
            }
            # store only the non-empty ones; keep the key present so clearing
            # a name reverts to default
            self._data["pv_string_names"] = {
                s: v for s, v in names.items() if v
            }
            # (#566) Reached via the charger-menu shortcut → finalize NOW,
            # preserving every other saved option. The normal chain finishes
            # at notifications() with the fully-accumulated self._data; the
            # shortcut skipped those forms, so replacing options with self._data
            # would wipe them. Merge onto the existing options instead.
            if getattr(self, "_pv_naming_return", None) == "menu":
                merged = {
                    **self.config_entry.options,
                    "pv_string_names": self._data["pv_string_names"],
                }
                return self.async_create_entry(data=merged)
            return await self.async_step_notifications()

        current = {**self.config_entry.data, **self.config_entry.options}
        saved_names = current.get("pv_string_names", {}) or {}

        # Build the "which slot is which" mapping shown in the description,
        # and the per-slot text fields.
        mapping_lines = []
        schema_dict = {}
        for slot in slots:
            src = pv_strings[slot]
            if isinstance(src, (tuple, list)):
                src_label = " × ".join(str(x) for x in src) + " (V×I)"
                watts = None
            else:
                src_label = str(src)
                st = self.hass.states.get(src_label)
                try:
                    watts = float(st.state) if st else None
                except (ValueError, TypeError):
                    watts = None
            w_txt = f" · {watts:.0f} W" if isinstance(watts, float) else ""
            n = slot.replace("pv", "")
            mapping_lines.append(f"• PV{n}  ←  {src_label}{w_txt}")
            schema_dict[vol.Optional(
                f"pv_name_{slot}",
                default=saved_names.get(slot, ""),
            )] = selector.TextSelector()

        return self.async_show_form(
            step_id="pv_naming",
            data_schema=vol.Schema(schema_dict),
            description_placeholders={"mapping": "\n".join(mapping_lines)},
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
                _merge_form_input(self, self._data, user_input)
                # #690 — async_create_entry REPLACES entry.options wholesale.
                # Carry forward every stored option this dialog does not own,
                # so a config-dialog save can't erase values written by
                # services / dashboard entities (grid_sign_user_flip,
                # battery_mode, vacation_mode, …). Flow-owned keys keep the
                # replace semantics (omitted from the form = cleared).
                carried = {
                    k: v
                    for k, v in (self.config_entry.options or {}).items()
                    if k not in OPTIONS_FLOW_OWNED_KEYS
                }
                return self.async_create_entry(data={**carried, **self._data})

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
