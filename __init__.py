"""Solar Energy Management Integration.

This integration provides comprehensive solar energy management with:
- Real-time energy flow monitoring and optimization
- EV charging control with solar priority
- Battery management and discharge protection
- Peak load management and demand control
- Energy dashboard integration
- Sankey flow visualization

Best Practices Implementation:
- Async-first with proper error handling
- Graceful degradation for optional features
- Non-blocking initialization for better startup performance
- Service registry checks to prevent conflicts
- Comprehensive logging and diagnostics
"""
import logging
import os
from typing import Any, Dict

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform, EVENT_HOMEASSISTANT_STARTED
from homeassistant.core import HomeAssistant, callback
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.exceptions import ConfigEntryNotReady, HomeAssistantError, ServiceValidationError
from homeassistant.helpers import issue_registry as ir
import voluptuous as vol
from homeassistant.helpers import config_validation as cv

from .const import DOMAIN
from .coordinator import SEMCoordinator

_LOGGER = logging.getLogger(__name__)

type SEMConfigEntry = ConfigEntry[SEMCoordinator]

PLATFORMS: list[Platform] = [
    Platform.SENSOR,
    Platform.SWITCH,
    Platform.NUMBER,
    Platform.BINARY_SENSOR,
    Platform.SELECT,
]


async def async_migrate_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> bool:
    """Migrate old config entry data to current schema.

    Migrations:
    - v1 → v2 (#98): `battery_priority_soc` semantics changed from
      legacy 3-zone "battery target before EV" (default 80) to 4-zone
      "Zone 1 floor: below this all solar → battery, EV blocked"
      (default 30). Existing entries that still carry the legacy 80%
      get remapped down to 30% so the 4-zone strategy actually leaves
      Zone 1 on a normally-charged battery.
    """
    _LOGGER.info(
        "Migrating SEM config entry from version %s.%s",
        entry.version, entry.minor_version
    )

    if entry.version < 2:
        try:
            from .consts.core import (
                DEFAULT_BATTERY_BUFFER_SOC,
                DEFAULT_BATTERY_AUTO_START_SOC,
                DEFAULT_BATTERY_ASSIST_FLOOR_SOC,
            )

            new_data = {**entry.data}
            new_options = {**entry.options}
            legacy_priority = max(
                new_options.get("battery_priority_soc") or 0,
                new_data.get("battery_priority_soc") or 0,
            )
            # Anything ≥ 50 is the legacy 3-zone meaning — remap.
            if legacy_priority >= 50:
                _LOGGER.warning(
                    "Migrating battery_priority_soc %s → 30 (4-zone semantics, see #98)",
                    legacy_priority,
                )
                new_data["battery_priority_soc"] = 30
                new_options.pop("battery_priority_soc", None)

            # Seed any 4-zone keys missing or null on legacy entries so the
            # number entities boot with sensible state.
            for key, default in (
                ("battery_buffer_soc", DEFAULT_BATTERY_BUFFER_SOC),
                ("battery_auto_start_soc", DEFAULT_BATTERY_AUTO_START_SOC),
                ("battery_assist_floor_soc", DEFAULT_BATTERY_ASSIST_FLOOR_SOC),
            ):
                if new_data.get(key) in (None, 0):
                    new_data[key] = default

            hass.config_entries.async_update_entry(
                entry,
                data=new_data,
                options=new_options,
                version=2,
                minor_version=1,
            )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    if entry.version < 3:
        try:
            # v2 → v3: Wrap flat ev_* keys into ev_chargers list for multi-charger support
            new_data = {**entry.data}
            new_options = {**entry.options}
            full = {**new_data, **new_options}

            # Only migrate if flat EV keys exist and ev_chargers doesn't
            if full.get("ev_charging_power_sensor") and "ev_chargers" not in full:
                _EV_FLAT_KEYS = [
                    "ev_connected_sensor", "ev_charging_sensor",
                    "ev_charging_power_sensor", "ev_charger_service",
                    "ev_charger_service_entity_id", "ev_current_control_entity",
                    "ev_current_sensor", "ev_total_energy_sensor",
                    "ev_session_energy_sensor", "ev_service_param_name",
                    "ev_service_device_id", "ev_start_stop_entity",
                    "ev_charge_mode_entity", "ev_charge_mode_start",
                    "ev_charge_mode_stop", "ev_start_service",
                    "ev_start_service_data", "ev_stop_service",
                    "ev_stop_service_data", "ev_charger_needs_cycle",
                    "ev_surplus_priority", "ev_load_priority",
                ]
                charger_0 = {"id": "ev_charger", "name": "EV Charger"}
                for k in _EV_FLAT_KEYS:
                    val = new_options.get(k) or new_data.get(k)
                    if val is not None:
                        charger_0[k] = val
                new_options["ev_chargers"] = [charger_0]
                _LOGGER.info(
                    "Migrated flat EV config to ev_chargers list (1 charger)"
                )

            hass.config_entries.async_update_entry(
                entry,
                data=new_data,
                options=new_options,
                version=3,
                minor_version=1,
            )
        except Exception as e:
            _LOGGER.error(
                "Migration from v%s to v3 failed — keeping original config: %s",
                entry.version, e,
            )
            return False

    _LOGGER.info("Migration to version %s.%s done", entry.version, entry.minor_version)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> bool:
    """Set up Solar Energy Management from a config entry.

    This follows Home Assistant best practices:
    1. Fast initialization - non-blocking operations deferred
    2. Proper error handling with ConfigEntryNotReady
    3. Graceful degradation for optional features
    4. Service registry checks to prevent conflicts
    """
    _LOGGER.info(
        "Starting Solar Energy Management setup (entry_id: %s, version: %s)",
        entry.entry_id,
        entry.version
    )

    # Initialize domain data storage (kept for backward compatibility with services)
    hass.data.setdefault(DOMAIN, {})

    # Merge entry.data and entry.options for complete configuration
    full_config = {**entry.data, **entry.options}
    _LOGGER.debug("Configuration keys: %s", list(full_config.keys()))

    # Create coordinator with error handling
    try:
        coordinator = SEMCoordinator(hass, full_config)
        coordinator.config_entry = entry
        _LOGGER.debug("SEMCoordinator created successfully")
    except Exception as err:
        _LOGGER.error("Failed to create coordinator: %s", err, exc_info=True)
        raise ConfigEntryNotReady(f"Coordinator creation failed: {err}") from err

    # Try to initialize from HA Energy Dashboard (HA 2025.12+)
    # This reads sensor configuration from the Energy Dashboard instead of manual config
    _LOGGER.info("Attempting to read sensors from HA Energy Dashboard...")
    try:
        result = await coordinator.async_initialize_energy_dashboard()
        if result:
            _LOGGER.info("Successfully using sensors from HA Energy Dashboard")
        else:
            _LOGGER.info("Energy Dashboard not available or incomplete, using legacy sensor config")
    except Exception as err:
        _LOGGER.warning("Failed to read Energy Dashboard, using legacy config: %s", err, exc_info=True)

    # Fetch initial data - this is critical for setup
    _LOGGER.debug("Fetching initial data from coordinator")
    try:
        await coordinator.async_config_entry_first_refresh()
        _LOGGER.info("Initial data fetch successful")
    except Exception as err:
        _LOGGER.error(
            "Failed to fetch initial data. This may indicate missing sensors or "
            "connectivity issues: %s",
            err,
            exc_info=True
        )
        raise ConfigEntryNotReady(
            f"Could not fetch initial data. Check that all required sensors exist: {err}"
        ) from err

    # Store coordinator in runtime_data (quality scale: runtime-data)
    entry.runtime_data = coordinator
    # Also store in hass.data for backward compatibility with platform setup
    hass.data[DOMAIN][entry.entry_id] = coordinator

    # Create repair issue if EV charger is not configured (quality scale: repair-issues)
    if not full_config.get("ev_connected_sensor") and not full_config.get("ev_charging_power_sensor"):
        ir.async_create_issue(
            hass,
            DOMAIN,
            "ev_charger_not_configured",
            is_fixable=False,
            is_persistent=False,
            severity=ir.IssueSeverity.WARNING,
            translation_key="ev_charger_not_configured",
        )
    else:
        ir.async_delete_issue(hass, DOMAIN, "ev_charger_not_configured")

    # Initialize load management (optional feature - don't fail setup if it fails)
    try:
        await coordinator.async_initialize_load_management(entry)
        _LOGGER.info("Load management initialized successfully")

        # Initialize unified device registry (reads Energy Dashboard, syncs to both systems)
        try:
            from .device_registry import UnifiedDeviceRegistry
            from .load_device_discovery import LoadDeviceDiscovery
            discovery = LoadDeviceDiscovery(hass)
            registry = UnifiedDeviceRegistry(
                hass, coordinator._surplus_controller, coordinator._load_manager, discovery
            )
            await registry.async_initialize()
            coordinator._device_registry = registry
            # Tell load manager to skip its own discovery — registry owns the device list
            if coordinator._load_manager:
                coordinator._load_manager._unified_registry_active = True
            _LOGGER.info("Unified device registry initialized with %d devices", len(registry.devices))
        except Exception as err:
            _LOGGER.warning("Unified device registry init failed (non-critical): %s", err)
            coordinator._device_registry = None

        # Register EV charger(s) as CurrentControlDevice for unified control
        # Solar mode: SurplusController manages by priority
        # Night mode: coordinator manages directly with grid headroom budget
        #
        # Multi-charger support (#112): ev_chargers list in config
        # Backward compat: flat ev_* keys wrapped into list by v2→v3 migration

        # Build charger config list from config + auto-discovery
        ev_chargers_config = list(full_config.get("ev_chargers") or [])

        # Auto-discover if no chargers configured
        if not ev_chargers_config:
            ev_auto = {}
            if coordinator._device_registry:
                ev_auto = coordinator._device_registry.discover_ev_charger()
                if ev_auto:
                    _LOGGER.info("Auto-discovered EV charger config: %s", list(ev_auto.keys()))
                    ev_auto["id"] = "ev_charger"
                    ev_auto["name"] = "EV Charger"
                    ev_chargers_config = [ev_auto]
                    # Persist discovered config
                    new_options = dict(entry.options)
                    new_options["ev_chargers"] = ev_chargers_config
                    hass.config_entries.async_update_entry(entry, options=new_options)
                    full_config["ev_chargers"] = ev_chargers_config
            # Fallback: check flat keys (pre-migration installs)
            if not ev_chargers_config:
                ev_power = full_config.get("ev_charging_power_sensor")
                ev_svc = full_config.get("ev_charger_service")
                ev_ctl = full_config.get("ev_current_control_entity")
                if ev_power and (ev_svc or ev_ctl):
                    ev_chargers_config = [{
                        "id": "ev_charger", "name": "EV Charger",
                        **{k: full_config[k] for k in full_config
                           if k.startswith("ev_") and full_config[k] is not None},
                    }]

        # Register each charger
        from .devices.base import CurrentControlDevice
        coordinator._ev_devices = {}

        for idx, charger_cfg in enumerate(ev_chargers_config):
            charger_id = charger_cfg.get("id", f"ev_charger_{idx}")
            charger_name = charger_cfg.get("name", f"EV Charger {idx + 1}")

            # Resolve config: charger-specific keys, fall back to global config
            def _cfg(key, default=None):
                return charger_cfg.get(key) or full_config.get(key) or default

            ev_power_entity = _cfg("ev_charging_power_sensor")
            ev_charger_service = _cfg("ev_charger_service")
            ev_service_entity = _cfg("ev_charger_service_entity_id")
            ev_current_entity = _cfg("ev_current_control_entity")
            ev_priority = int(_cfg("ev_surplus_priority", _cfg("ev_load_priority", 3 + idx)))

            # Also auto-fill sensor reader config from first charger
            if idx == 0:
                for key in ("ev_connected_sensor", "ev_charging_sensor", "ev_total_energy_sensor"):
                    if not full_config.get(key) and charger_cfg.get(key):
                        full_config[key] = charger_cfg[key]

            if not ev_power_entity or not (ev_charger_service or ev_current_entity):
                _LOGGER.debug("Charger %s missing power sensor or control method, skipping", charger_id)
                continue

            ev_device = CurrentControlDevice(
                hass=hass,
                device_id=charger_id,
                name=charger_name,
                priority=ev_priority,
                min_current=float(_cfg("ev_min_current", 6)),
                max_current=float(_cfg("max_charging_current", 32)),
                phases=int(_cfg("ev_phases", 3)),
                voltage=230.0,
                power_entity_id=ev_power_entity,
                charger_service=ev_charger_service,
                charger_service_entity_id=ev_service_entity,
                current_entity_id=ev_current_entity,
            )
            ev_device.needs_pilot_cycle = _cfg("ev_charger_needs_cycle", False)
            # Per-integration charger profile (#82)
            if _cfg("ev_service_param_name"):
                ev_device.service_param_name = _cfg("ev_service_param_name")
            if _cfg("ev_service_device_id"):
                ev_device.service_device_id = _cfg("ev_service_device_id")
            if _cfg("ev_start_stop_entity"):
                ev_device.start_stop_entity = _cfg("ev_start_stop_entity")
            if _cfg("ev_charge_mode_entity"):
                ev_device.charge_mode_entity = _cfg("ev_charge_mode_entity")
                ev_device.charge_mode_start = _cfg("ev_charge_mode_start")
                ev_device.charge_mode_stop = _cfg("ev_charge_mode_stop")
            if _cfg("ev_start_service"):
                ev_device.start_service = _cfg("ev_start_service")
                import json as _json
                ev_device.start_service_data = _json.loads(_cfg("ev_start_service_data", "{}"))
            if _cfg("ev_stop_service"):
                ev_device.stop_service = _cfg("ev_stop_service")
                import json as _json
                ev_device.stop_service_data = _json.loads(_cfg("ev_stop_service_data", "{}"))

            coordinator._surplus_controller.register_device(ev_device)
            coordinator._ev_devices[charger_id] = ev_device
            ev_device.managed_externally = True
            _LOGGER.info(
                "EV charger '%s' registered as CurrentControlDevice "
                "(priority %d, max %dA, service: %s)",
                charger_name, ev_priority,
                int(ev_device.max_current),
                ev_charger_service or ev_current_entity,
            )

            # Also register in load management for peak shedding
            if coordinator._load_manager:
                await coordinator._load_manager.register_ev_charger(
                    current_control_entity=ev_current_entity,
                    power_entity=ev_power_entity,
                    priority=ev_priority,
                    is_critical=False,
                    charger_service=ev_charger_service,
                )

        # Backward compat: _ev_device points to primary (first) charger
        if coordinator._ev_devices:
            coordinator._ev_device = next(iter(coordinator._ev_devices.values()))
            _LOGGER.info(
                "Registered %d EV charger(s). Primary: %s",
                len(coordinator._ev_devices),
                coordinator._ev_device.name,
            )
        else:
            _LOGGER.debug("EV charger not configured (no power sensor or control method)")

    except Exception as err:
        _LOGGER.warning(
            "Load management initialization failed (non-critical): %s. "
            "Load management features will be unavailable.",
            err
        )

    # Setup platforms (critical - must succeed)
    try:
        await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
        _LOGGER.info("Platforms setup completed: %s", PLATFORMS)
    except Exception as err:
        _LOGGER.error("Failed to setup platforms: %s", err, exc_info=True)
        # Cleanup coordinator data
        hass.data[DOMAIN].pop(entry.entry_id, None)
        raise ConfigEntryNotReady(f"Platform setup failed: {err}") from err

    # Register services (with duplicate check)
    try:
        await _async_register_services(hass, coordinator)
        await _async_register_phase_services(hass, coordinator)
        _LOGGER.debug("Services registered successfully")
    except Exception as err:
        _LOGGER.warning(
            "Service registration failed (non-critical): %s. "
            "Services may not be available.",
            err
        )

    # Register frontend resources (optional - don't fail setup)
    try:
        await _async_register_frontend_resources(hass)
        _LOGGER.debug("Frontend resources registered successfully")
    except Exception as err:
        _LOGGER.warning(
            "Frontend resource registration failed (non-critical): %s. "
            "Custom cards may not be available.",
            err
        )

    # Auto-install card JS files to /config/www/ on startup (#55)
    # Only runs if dashboard was previously generated. On HACS updates,
    # this ensures new cards are available after restart without manual action.
    try:
        await _async_install_card_assets(hass, entry)
    except Exception as err:
        _LOGGER.debug("Card asset installation skipped: %s", err)

    # Register options update listener
    entry.async_on_unload(entry.add_update_listener(async_update_options))

    # Schedule post-startup tasks (non-blocking)
    _schedule_post_startup_tasks(hass, entry, full_config, coordinator)

    # One-shot: if the user opted in during the install flow, generate the
    # SEM dashboard right after first setup. The dashboard service schedules
    # an HA restart 5s after success, so we set a marker in entry.options
    # *before* calling the service. The reload triggered by setting the
    # marker will see it on the second setup_entry pass and skip; the same
    # marker survives the HA restart and prevents a third regeneration.
    install_flag = entry.data.get("generate_dashboard_on_install")
    already_generated = entry.options.get("_install_dashboard_generated", False)
    if install_flag and not already_generated:
        _LOGGER.info(
            "Install flow opted in to dashboard generation — scheduling one-shot"
        )

        async def _run_once_install_dashboard(_now=None) -> None:
            try:
                hass.config_entries.async_update_entry(
                    entry,
                    options={
                        **entry.options,
                        "_install_dashboard_generated": True,
                    },
                )
                await hass.services.async_call(
                    DOMAIN, "generate_dashboard", {}, blocking=False
                )
            except Exception as gen_err:
                _LOGGER.error(
                    "Post-install dashboard generation failed: %s", gen_err
                )

        from homeassistant.helpers.event import async_call_later as _acl
        _acl(hass, 2, _run_once_install_dashboard)

    _LOGGER.info("Solar Energy Management integration setup completed successfully")
    return True


def _schedule_post_startup_tasks(
    hass: HomeAssistant,
    entry: ConfigEntry,
    full_config: Dict[str, Any],
    coordinator: SEMCoordinator
) -> None:
    """Schedule non-critical tasks to run after Home Assistant has started.

    This prevents blocking the startup process while still ensuring
    these tasks run when the system is ready.
    """

    @callback
    def _async_post_startup_init(event) -> None:
        """Execute post-startup initialization tasks."""
        _LOGGER.debug("Running post-startup initialization tasks")
        # Additional post-startup tasks can be added here if needed

    # Schedule tasks to run when Home Assistant is fully started
    hass.bus.async_listen_once(EVENT_HOMEASSISTANT_STARTED, _async_post_startup_init)


async def async_update_options(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Handle options update."""
    _LOGGER.info("Config options updated, reloading integration")
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: SEMConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id, None)

    return unload_ok


async def _async_register_services(
    hass: HomeAssistant,
    coordinator: SEMCoordinator,
) -> None:
    """Register services for the integration.

    Implements best practices:
    - Checks for existing services to prevent conflicts
    - Proper error handling for each service
    - Schema validation for all services
    - Clear logging for debugging
    """

    # Check if services are already registered (prevents conflicts on reload)
    services_already_registered = hass.services.has_service(DOMAIN, "sync_priorities_from_dashboard")
    if services_already_registered:
        _LOGGER.debug(
            "Services already registered for domain '%s', skipping re-registration",
            DOMAIN
        )
        return

    # Dashboard generation service
    async def async_generate_dashboard_service(call) -> None:
        """Generate and install the SEM dashboard with all assets."""
        dashboard_title = call.data.get("dashboard_title", "Solar Energy Management")
        dashboard_path = call.data.get("dashboard_path", "sem-dashboard")

        try:
            from .dashboard_generator import DashboardGenerator
            from homeassistant.helpers.storage import Store
            import shutil

            # Step 1: Install SVG system diagram + card JS files to /config/www/
            # All filesystem ops run in an executor to avoid blocking the event loop.
            component_dir = os.path.dirname(__file__)
            svg_source = os.path.join(component_dir, "dashboard", "www", "sem-system-diagram.svg")
            www_target_dir = os.path.join(hass.config.config_dir, "www", "sem")
            svg_target = os.path.join(www_target_dir, "sem-system-diagram.svg")
            card_src_dir = os.path.join(component_dir, "dashboard", "card")
            card_www_dir = os.path.join(
                hass.config.config_dir, "www",
                "custom_components", DOMAIN, "dashboard", "card",
            )

            def _install_assets() -> tuple[bool, list[str]]:
                """Sync all dashboard assets to /config/www/. Runs in executor."""
                os.makedirs(www_target_dir, exist_ok=True)
                svg_installed = False
                if os.path.exists(svg_source):
                    shutil.copy2(svg_source, svg_target)
                    svg_installed = True

                os.makedirs(card_www_dir, exist_ok=True)
                cards: list[str] = []
                if os.path.isdir(card_src_dir):
                    for fname in os.listdir(card_src_dir):
                        if fname.endswith(".js"):
                            shutil.copy2(
                                os.path.join(card_src_dir, fname),
                                os.path.join(card_www_dir, fname),
                            )
                            cards.append(fname)
                return svg_installed, cards

            svg_installed, installed_cards = await hass.async_add_executor_job(_install_assets)
            if svg_installed:
                _LOGGER.info("Installed SVG diagram to %s", svg_target)
            else:
                _LOGGER.warning("SVG diagram not found at %s", svg_source)
            if installed_cards:
                _LOGGER.info("Installed %d card(s) to %s: %s", len(installed_cards), card_www_dir, installed_cards)

            # Step 1b: Clean up stale card copies in /config/www/ root
            # Old standalone installs may leave files that conflict with
            # the component-managed copies (double customElements.define).
            def _cleanup_stale_www():
                www_dir = os.path.join(hass.config.config_dir, "www")
                removed = []
                for fname in os.listdir(www_dir) if os.path.isdir(www_dir) else []:
                    if fname.startswith("sem-") and fname.endswith(".js"):
                        stale = os.path.join(www_dir, fname)
                        os.remove(stale)
                        removed.append(fname)
                return removed

            stale_removed = await hass.async_add_executor_job(_cleanup_stale_www)
            if stale_removed:
                _LOGGER.info("Removed %d stale card(s) from /config/www/: %s", len(stale_removed), stale_removed)

            # Step 1c: Register cards as Lovelace resources (idempotent)
            # Compare by base URL (without ?v= query) to avoid duplicates
            # when _async_register_frontend_resources already added versioned URLs.
            # Also remove stale /local/sem-*.js entries (old standalone installs).
            resources_store = Store(hass, 1, "lovelace_resources")
            resources_data = await resources_store.async_load() or {"items": []}
            if "items" not in resources_data:
                resources_data["items"] = []

            # Remove stale standalone resource entries (/local/sem-*.js)
            component_prefix = f"/local/custom_components/{DOMAIN}/"
            before_count = len(resources_data["items"])
            resources_data["items"] = [
                item for item in resources_data["items"]
                if not (
                    item.get("url", "").startswith("/local/sem-")
                    and component_prefix not in item.get("url", "")
                )
            ]
            stale_count = before_count - len(resources_data["items"])
            if stale_count:
                _LOGGER.info("Removed %d stale Lovelace resource(s)", stale_count)

            # Cache-busting: use timestamp so every generate_dashboard
            # call forces browsers to reload card JS files.
            import time as _time
            cache_bust = str(int(_time.time()))

            existing_bases = {item.get("url", "").split("?")[0] for item in resources_data["items"]}
            added_resources = []
            updated_resources = 0
            for fname in installed_cards:
                base_url = f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
                if base_url not in existing_bases:
                    import uuid as _uuid
                    resources_data["items"].append({
                        "id": _uuid.uuid4().hex,
                        "url": f"{base_url}?v={cache_bust}",
                        "type": "module",
                    })
                    added_resources.append(base_url)

            # Update ?v= on existing SEM resources and remove orphaned ones
            installed_bases = {
                f"/local/custom_components/{DOMAIN}/dashboard/card/{fname}"
                for fname in installed_cards
            }
            cleaned = []
            kept_items = []
            for item in resources_data["items"]:
                url = item.get("url", "")
                base = url.split("?")[0]
                if f"/custom_components/{DOMAIN}/" in base and base.endswith(".js"):
                    if base not in installed_bases:
                        # Card file no longer exists — remove orphaned resource
                        cleaned.append(base)
                        continue
                    new_url = f"{base}?v={cache_bust}"
                    if item["url"] != new_url:
                        item["url"] = new_url
                        updated_resources += 1
                kept_items.append(item)
            resources_data["items"] = kept_items
            if cleaned:
                _LOGGER.info("Removed %d orphaned card resource(s): %s", len(cleaned), cleaned)

            if added_resources or stale_count or updated_resources:
                await resources_store.async_save(resources_data)
                if added_resources:
                    _LOGGER.info("Registered %d new Lovelace resource(s): %s", len(added_resources), added_resources)
                if updated_resources:
                    _LOGGER.info("Updated cache-bust on %d Lovelace resource(s) to v=%s", updated_resources, cache_bust)

            # Step 2: Generate dashboard config
            generator = DashboardGenerator(hass)
            dashboard_config = await generator.generate_dashboard(
                dashboard_title=dashboard_title,
                dashboard_path=dashboard_path,
            )

            if not dashboard_config:
                raise ValueError("Dashboard generator returned empty configuration")

            # Save dashboard to storage
            storage_key = f"lovelace.{dashboard_path}"
            dashboard_store = Store(hass, 1, storage_key)

            views = dashboard_config.get("views", [])
            if not views:
                raise ValueError("Dashboard config has no views")

            storage_data = {"config": {"views": views}}
            await dashboard_store.async_save(storage_data)
            _LOGGER.info("Dashboard config saved to .storage/%s with %d views", storage_key, len(views))

            # Register dashboard in lovelace_dashboards storage
            dashboards_store = Store(hass, 1, "lovelace_dashboards")
            dashboards_data = await dashboards_store.async_load()
            if dashboards_data is None:
                dashboards_data = {"items": []}

            dashboard_exists = False
            for item in dashboards_data.get("items", []):
                if item.get("id") == dashboard_path:
                    item["mode"] = "storage"
                    item["title"] = dashboard_title
                    item["icon"] = "mdi:solar-power"
                    item["show_in_sidebar"] = True
                    item["require_admin"] = False
                    dashboard_exists = True
                    break

            if not dashboard_exists:
                dashboards_data["items"].append({
                    "id": dashboard_path,
                    "mode": "storage",
                    "title": dashboard_title,
                    "icon": "mdi:solar-power",
                    "show_in_sidebar": True,
                    "require_admin": False,
                    "url_path": dashboard_path,
                })

            await dashboards_store.async_save(dashboards_data)

            await hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "SEM Dashboard Created",
                    "message": (
                        f"Dashboard **{dashboard_title}** created with {len(views)} views.\n\n"
                        f"Access at: /lovelace/{dashboard_path}\n\n"
                        f"Home Assistant will restart in 5 seconds to apply changes."
                    ),
                    "notification_id": "sem_dashboard_success",
                },
            )
            _LOGGER.info("Dashboard created: %s at /%s — scheduling restart", dashboard_title, dashboard_path)

            # Schedule HA restart so the new dashboard is visible in the browser
            async def _delayed_restart(_now):
                _LOGGER.info("Restarting Home Assistant to apply dashboard changes")
                await hass.services.async_call("homeassistant", "restart")

            from homeassistant.helpers.event import async_call_later
            async_call_later(hass, 5, _delayed_restart)

        except Exception as e:
            _LOGGER.error("Dashboard generation failed: %s", e, exc_info=True)
            await hass.services.async_call(
                "persistent_notification", "create",
                {
                    "title": "SEM Dashboard Generation Failed",
                    "message": f"Error: {e}\n\nSee logs for details.",
                    "notification_id": "sem_dashboard_error",
                },
            )

    try:
        hass.services.async_register(
            DOMAIN,
            "generate_dashboard",
            async_generate_dashboard_service,
            schema=vol.Schema({
                vol.Optional("dashboard_title", default="Solar Energy Management"): cv.string,
                vol.Optional("dashboard_path", default="sem-dashboard"): cv.string,
            }),
        )
        _LOGGER.debug("Registered service: %s.generate_dashboard", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register generate_dashboard service: %s", err)

    # Energy dashboard configuration service
    async def async_configure_energy_dashboard_service(call) -> None:
        """Automatically configure HA Energy Dashboard with SEM sensors."""
        try:
            from .energy_dashboard import configure_energy_dashboard
            full_config = {**coordinator.config}
            result = await configure_energy_dashboard(hass, full_config)
            if result:
                _LOGGER.info("Energy Dashboard configured successfully")
                await hass.services.async_call(
                    "persistent_notification", "create",
                    {
                        "title": "Energy Dashboard Configured",
                        "message": "HA Energy Dashboard has been configured with SEM sensors.",
                        "notification_id": "sem_energy_dashboard_success",
                    },
                )
            else:
                _LOGGER.warning("Energy Dashboard configuration returned False")
        except Exception as e:
            _LOGGER.error("Energy Dashboard configuration failed: %s", e, exc_info=True)

    try:
        hass.services.async_register(
            DOMAIN,
            "configure_energy_dashboard",
            async_configure_energy_dashboard_service,
            schema=vol.Schema({}),
        )
        _LOGGER.debug("Registered service: %s.configure_energy_dashboard", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register configure_energy_dashboard service: %s", err)

    # Load management priority sync service
    async def async_sync_priorities_from_dashboard_service(call) -> None:
        """Sync device priorities from dashboard card order."""
        import json
        import re

        dashboard_storage_key = call.data.get("dashboard_storage_key", "lovelace.dashboard_test")
        view_path = call.data.get("view_path", "peak-load-management")

        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        try:
            # Load dashboard configuration
            dashboard_file = os.path.join(hass.config.config_dir, ".storage", dashboard_storage_key)
            if not os.path.exists(dashboard_file):
                _LOGGER.error("Dashboard file not found: %s", dashboard_file)
                return

            with open(dashboard_file, "r", encoding="utf-8") as f:
                dashboard_data = json.load(f)

            # Find the specified view
            views = dashboard_data.get("data", {}).get("config", {}).get("views", [])
            target_view = next((v for v in views if v.get("path") == view_path), None)

            if not target_view:
                _LOGGER.error("View with path '%s' not found in dashboard", view_path)
                return

            # Find the Device Priority Management section
            sections = target_view.get("sections", [])
            device_section = None
            for section in sections:
                cards = section.get("cards", [])
                for card in cards:
                    if isinstance(card, dict):
                        title = card.get("title", "")
                        if "Device Priority Management" in title:
                            device_section = section
                            break
                if device_section:
                    break

            if not device_section:
                _LOGGER.error("Device Priority Management section not found")
                return

            # Extract device IDs from card order
            cards = device_section.get("cards", [])
            device_updates = []

            for index, card in enumerate(cards):
                if not isinstance(card, dict):
                    continue

                # Skip title cards
                card_type = card.get("type", "")
                if "title" in card_type:
                    continue

                # Extract device_id from Jinja template
                secondary_template = card.get("secondary", "")
                match = re.search(r"'load_device_[^']+", secondary_template)

                if match:
                    device_id = match.group(0).strip("'")
                    # Position starts at 1 (skip title card at index 0)
                    priority = index  # Since we skip title cards, first device card becomes priority 1
                    device_updates.append((device_id, priority))
                    _LOGGER.debug("Found device %s at position %d", device_id, priority)

            # Update priorities
            updated_count = 0
            for device_id, priority in device_updates:
                if device_id in coordinator._load_manager._devices:
                    await coordinator._load_manager.update_device_priority(device_id, priority)
                    updated_count += 1
                    _LOGGER.info("Updated %s priority to %d (from card position)", device_id, priority)
                else:
                    _LOGGER.warning("Device %s found in dashboard but not in load manager", device_id)

            _LOGGER.info("Synced priorities for %d devices from dashboard card order", updated_count)

        except Exception as e:
            _LOGGER.error("Failed to sync priorities from dashboard: %s", e, exc_info=True)

    # Register priority sync service
    try:
        hass.services.async_register(
            DOMAIN,
            "sync_priorities_from_dashboard",
            async_sync_priorities_from_dashboard_service,
            schema=vol.Schema({
                vol.Optional("dashboard_storage_key", default="lovelace.dashboard_test"): cv.string,
                vol.Optional("view_path", default="peak-load-management"): cv.string,
            })
        )
        _LOGGER.debug("Registered service: %s.sync_priorities_from_dashboard", DOMAIN)
    except Exception as err:
        _LOGGER.error(
            "Failed to register sync_priorities_from_dashboard service: %s",
            err
        )

    # ── set_device_control_mapping service ──

    async def async_set_device_control_mapping(call) -> None:
        """Manually map a control entity for an Energy Dashboard device."""
        registry = getattr(coordinator, '_device_registry', None)
        if not registry:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="device_registry_not_initialized",
            )

        energy_sensor = call.data.get("energy_sensor")
        control_entity = call.data.get("control_entity")
        control_type = call.data.get("control_type", "switch")

        await registry.async_set_manual_mapping(energy_sensor, control_entity, control_type)
        _LOGGER.info("Manual mapping set: %s → %s (%s)", energy_sensor, control_entity, control_type)

    try:
        hass.services.async_register(
            DOMAIN,
            "set_device_control_mapping",
            async_set_device_control_mapping,
            schema=vol.Schema({
                vol.Required("energy_sensor"): cv.string,
                vol.Required("control_entity"): cv.string,
                vol.Optional("control_type", default="switch"): vol.In(["switch", "current", "service"]),
            }),
        )
        _LOGGER.debug("Registered service: %s.set_device_control_mapping", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register set_device_control_mapping service: %s", err)

    # ── Drag-and-drop priority card services ──

    async def async_update_device_priorities(call) -> None:
        """Batch update device priorities from drag-and-drop reorder."""
        priorities = call.data.get("priorities", [])

        # Update via unified registry if available
        registry = getattr(coordinator, '_device_registry', None)
        if registry:
            await registry.async_update_priority_overrides(priorities)
            _LOGGER.info("Updated priorities for %d devices via registry", len(priorities))
            return

        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        updated = 0
        for item in priorities:
            device_id = item.get("device_id")
            priority = item.get("priority")
            if device_id and priority is not None:
                await coordinator._load_manager.update_device_priority(device_id, int(priority))
                updated += 1
        _LOGGER.info("Updated priorities for %d devices via drag-and-drop", updated)

    try:
        hass.services.async_register(
            DOMAIN,
            "update_device_priorities",
            async_update_device_priorities,
            schema=vol.Schema({
                vol.Required("priorities"): list,
            }),
        )
        _LOGGER.debug("Registered service: %s.update_device_priorities", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register update_device_priorities service: %s", err)

    async def async_update_device_config(call) -> None:
        """Update a single device property (controllable or critical)."""
        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        device_id = call.data.get("device_id")
        prop = call.data.get("property")
        value = call.data.get("value")

        if prop == "critical":
            await coordinator._load_manager.update_device_critical_status(device_id, bool(value))
        elif prop == "controllable":
            await coordinator._load_manager.update_device_controllable_status(device_id, bool(value))
        elif prop == "control_mode":
            # Update device control mode: off / peak_only / surplus (#49)
            registry = getattr(coordinator, '_device_registry', None)
            if registry:
                await registry.update_device_control_mode(device_id, str(value))
            else:
                raise HomeAssistantError("Device registry not initialized")
        else:
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_device_property",
                translation_placeholders={"property": prop},
            )
        _LOGGER.info("Updated %s.%s = %s", device_id, prop, value)
        await coordinator.async_request_refresh()

    try:
        hass.services.async_register(
            DOMAIN,
            "update_device_config",
            async_update_device_config,
            schema=vol.Schema({
                vol.Required("device_id"): cv.string,
                vol.Required("property"): vol.In(["controllable", "critical", "control_mode"]),
                vol.Required("value"): cv.string,
            }),
        )
        _LOGGER.debug("Registered service: %s.update_device_config", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register update_device_config service: %s", err)

    async def async_update_target_peak(call) -> None:
        """Update target peak limit."""
        if not coordinator._load_manager:
            raise HomeAssistantError(
                translation_domain=DOMAIN,
                translation_key="load_management_not_initialized",
            )

        target = call.data.get("target_peak_limit")
        await coordinator._load_manager.update_target_peak_limit(float(target))
        _LOGGER.info("Updated target peak limit to %.1f kW", target)

    try:
        hass.services.async_register(
            DOMAIN,
            "update_target_peak",
            async_update_target_peak,
            schema=vol.Schema({
                vol.Required("target_peak_limit"): vol.All(
                    vol.Coerce(float), vol.Range(min=1.0, max=20.0)
                ),
            }),
        )
        _LOGGER.debug("Registered service: %s.update_target_peak", DOMAIN)
    except Exception as err:
        _LOGGER.error("Failed to register update_target_peak service: %s", err)


async def _async_register_frontend_resources(hass: HomeAssistant) -> None:
    """Register frontend resources for the SEM dashboard cards."""
    try:
        import os

        component_path = os.path.dirname(__file__)
        dashboard_path = os.path.join(component_path, "dashboard")
        card_file_path = os.path.join(dashboard_path, "card", "sem-load-priority-card.js")

        if not os.path.exists(card_file_path):
            return

        static_path = f"/local/custom_components/{DOMAIN}/dashboard"

        # Register static path (may fail on reload if already registered)
        try:
            hass.http.register_static_path(
                static_path, dashboard_path, cache_headers=False
            )
        except Exception:
            pass  # Already registered from previous load

        # Register the JS as Lovelace resources (not add_extra_js_url) so they
        # load into HA's scoped custom-element registry. add_extra_js_url loads
        # as a plain <script> in the global scope, which conflicts with the
        # Lovelace resource load and leaves the element in the wrong registry —
        # symptom: "Custom element doesn't exist: sem-system-diagram-card".
        # Read version from manifest for cache-busting query param.
        # Without this, browsers cache the old JS indefinitely even with
        # cache_headers=False, because Lovelace resources are fetched once
        # and kept in the service worker cache.
        import json as _json
        manifest_path = os.path.join(component_path, "manifest.json")
        try:
            with open(manifest_path) as f:
                version = _json.load(f).get("version", "0")
        except Exception:
            version = "0"

        localize_base = f"{static_path}/card/sem-localize.js"
        shared_base = f"{static_path}/card/sem-shared.js"
        card_base = f"{static_path}/card/sem-load-priority-card.js"
        diagram_base = f"{static_path}/card/sem-system-diagram-card.js"
        period_base = f"{static_path}/card/sem-period-selector-card.js"
        chart_base = f"{static_path}/card/sem-chart-card.js"
        solar_summary_base = f"{static_path}/card/sem-solar-summary-card.js"
        weather_base = f"{static_path}/card/sem-weather-card.js"
        flow_base = f"{static_path}/card/sem-flow-card.js"
        tab_header_base = f"{static_path}/card/sem-tab-header.js"
        battery_card_base = f"{static_path}/card/sem-battery-card.js"
        ev_status_base = f"{static_path}/card/sem-ev-status-card.js"
        schedule_base = f"{static_path}/card/sem-schedule-card.js"
        localize_url = f"{localize_base}?v={version}"
        shared_url = f"{shared_base}?v={version}"
        card_url = f"{card_base}?v={version}"
        diagram_url = f"{diagram_base}?v={version}"
        period_url = f"{period_base}?v={version}"
        chart_url = f"{chart_base}?v={version}"
        solar_summary_url = f"{solar_summary_base}?v={version}"
        weather_url = f"{weather_base}?v={version}"
        flow_url = f"{flow_base}?v={version}"
        tab_header_url = f"{tab_header_base}?v={version}"
        battery_card_url = f"{battery_card_base}?v={version}"
        ev_status_url = f"{ev_status_base}?v={version}"
        schedule_url = f"{schedule_base}?v={version}"
        try:
            from homeassistant.components.lovelace.resources import ResourceStorageCollection
            resources: ResourceStorageCollection = hass.data["lovelace"].resources
            if not resources.loaded:
                await resources.async_load()

            # Build lookup: base URL (without query) → resource item
            existing_by_base = {}
            for item in resources.async_items():
                base = item["url"].split("?")[0]
                existing_by_base[base] = item

            for base, versioned_url in (
                (localize_base, localize_url),
                (shared_base, shared_url),
                (card_base, card_url),
                (diagram_base, diagram_url),
                (period_base, period_url),
                (chart_base, chart_url),
                (solar_summary_base, solar_summary_url),
                (weather_base, weather_url),
                (flow_base, flow_url),
                (tab_header_base, tab_header_url),
                (battery_card_base, battery_card_url),
                (ev_status_base, ev_status_url),
                (schedule_base, schedule_url),
            ):
                item = existing_by_base.get(base)
                if item is None:
                    # Not registered yet — create
                    await resources.async_create_item({"res_type": "module", "url": versioned_url})
                    _LOGGER.info("Registered SEM Lovelace resource: %s", versioned_url)
                elif item["url"] != versioned_url:
                    # Registered but with old version — update to bust cache
                    await resources.async_update_item(
                        item["id"], {"res_type": "module", "url": versioned_url}
                    )
                    _LOGGER.info("Updated SEM Lovelace resource: %s → %s", item["url"], versioned_url)
        except Exception as e:
            _LOGGER.warning("Could not register SEM Lovelace resources: %s", e)

    except Exception as e:
        _LOGGER.debug("Frontend resource registration skipped: %s", e)


async def _async_install_card_assets(
    hass: HomeAssistant, entry: ConfigEntry
) -> None:
    """Auto-install card JS files to /config/www/ on startup (#55).

    Only runs if the SEM dashboard was previously generated, detected by:
    1. Config entry flag `_install_dashboard_generated` (set by install flow)
    2. Dashboard storage file `.storage/lovelace.sem-dashboard` (set by service)

    On first install (no dashboard yet): skip — generate_dashboard handles it.
    On HACS update: auto-copy new/changed cards so restart is sufficient.
    Self-healing: recreates www dir if deleted but dashboard still exists.
    """
    import shutil

    component_dir = os.path.dirname(__file__)
    card_src_dir = os.path.join(component_dir, "dashboard", "card")
    card_www_dir = os.path.join(
        hass.config.config_dir, "www",
        "custom_components", DOMAIN, "dashboard", "card",
    )

    # Check if dashboard was ever generated
    dashboard_generated = False

    # Method 1: Config entry flag (set during install flow)
    if entry.options.get("_install_dashboard_generated"):
        dashboard_generated = True

    # Method 2: Dashboard storage file (set by generate_dashboard service)
    dashboard_storage = os.path.join(
        hass.config.config_dir, ".storage", "lovelace.sem-dashboard"
    )
    if os.path.exists(dashboard_storage):
        dashboard_generated = True

    if not dashboard_generated:
        _LOGGER.debug(
            "SEM dashboard not yet generated — skipping card auto-install. "
            "Run the generate_dashboard service after setup."
        )
        return

    def _copy_cards() -> list:
        os.makedirs(card_www_dir, exist_ok=True)
        cards = []
        if os.path.isdir(card_src_dir):
            for fname in os.listdir(card_src_dir):
                if fname.endswith(".js"):
                    src = os.path.join(card_src_dir, fname)
                    dst = os.path.join(card_www_dir, fname)
                    if not os.path.exists(dst) or os.path.getmtime(src) > os.path.getmtime(dst):
                        shutil.copy2(src, dst)
                        cards.append(fname)
        # Also copy translations.json for sem-localize.js (#60)
        dashboard_dir = os.path.dirname(card_src_dir)
        translations_src = os.path.join(dashboard_dir, "translations.json")
        translations_dst = os.path.join(os.path.dirname(card_www_dir), "translations.json")
        if os.path.exists(translations_src):
            if not os.path.exists(translations_dst) or os.path.getmtime(translations_src) > os.path.getmtime(translations_dst):
                os.makedirs(os.path.dirname(translations_dst), exist_ok=True)
                shutil.copy2(translations_src, translations_dst)
                cards.append("translations.json")
        return cards

    updated = await hass.async_add_executor_job(_copy_cards)
    if updated:
        _LOGGER.info("Auto-installed %d updated card(s): %s", len(updated), updated)
    else:
        _LOGGER.debug("All card assets up to date")


async def _async_register_phase_services(
    hass: HomeAssistant,
    coordinator: SEMCoordinator,
) -> None:
    """Register services for new phases (surplus control, scheduling, etc.)."""
    from datetime import datetime

    # Skip if already registered
    if hass.services.has_service(DOMAIN, "schedule_appliance"):
        return

    # Phase 0: Register/unregister surplus devices
    async def async_register_surplus_device(call) -> None:
        """Register a device for surplus control."""
        from .devices.base import SwitchDevice
        device_id = call.data.get("device_id")
        entity_id = call.data.get("entity_id")
        name = call.data.get("name", device_id)
        priority = call.data.get("priority", 5)
        rated_power = call.data.get("rated_power", 1000)
        power_entity = call.data.get("power_entity_id")

        device = SwitchDevice(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            entity_id=entity_id,
            power_entity_id=power_entity,
        )
        coordinator._surplus_controller.register_device(device)
        _LOGGER.info("Registered surplus device: %s (priority %d)", name, priority)

    hass.services.async_register(
        DOMAIN,
        "register_surplus_device",
        async_register_surplus_device,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("entity_id"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("priority", default=5): vol.All(int, vol.Range(min=1, max=10)),
            vol.Optional("rated_power", default=1000): vol.Coerce(float),
            vol.Optional("power_entity_id"): cv.string,
        }),
    )

    # Phase 4: Schedule appliance
    async def async_schedule_appliance(call) -> None:
        """Schedule an appliance to run before a deadline."""
        device_id = call.data.get("device_id")
        entity_id = call.data.get("entity_id")
        name = call.data.get("name", device_id)
        deadline_str = call.data.get("deadline")
        runtime_minutes = call.data.get("estimated_runtime_minutes", 120)
        energy_kwh = call.data.get("estimated_energy_kwh", 1.0)
        rated_power = call.data.get("rated_power", 1000)
        priority = call.data.get("priority", 7)

        try:
            deadline = datetime.fromisoformat(deadline_str)
        except (ValueError, TypeError):
            raise ServiceValidationError(
                translation_domain=DOMAIN,
                translation_key="invalid_deadline_format",
                translation_placeholders={"deadline": str(deadline_str)},
            )

        # Lazy-init appliance scheduler
        if not hasattr(coordinator, '_appliance_scheduler'):
            from .devices.appliance_scheduler import ApplianceScheduler
            coordinator._appliance_scheduler = ApplianceScheduler(hass)

        scheduler = coordinator._appliance_scheduler

        # Register if not already known
        if device_id not in scheduler._devices:
            device = scheduler.register_appliance(
                device_id=device_id,
                name=name,
                rated_power=rated_power,
                entity_id=entity_id,
                priority=priority,
            )
            # Also register with surplus controller
            coordinator._surplus_controller.register_device(device)

        scheduler.schedule_appliance(
            device_id=device_id,
            deadline=deadline,
            estimated_runtime_minutes=runtime_minutes,
            estimated_energy_kwh=energy_kwh,
        )

    hass.services.async_register(
        DOMAIN,
        "schedule_appliance",
        async_schedule_appliance,
        schema=vol.Schema({
            vol.Required("device_id"): cv.string,
            vol.Required("entity_id"): cv.string,
            vol.Required("deadline"): cv.string,
            vol.Optional("name"): cv.string,
            vol.Optional("estimated_runtime_minutes", default=120): vol.Coerce(int),
            vol.Optional("estimated_energy_kwh", default=1.0): vol.Coerce(float),
            vol.Optional("rated_power", default=1000): vol.Coerce(float),
            vol.Optional("priority", default=7): vol.All(int, vol.Range(min=1, max=10)),
        }),
    )

    _LOGGER.debug("Phase services registered: register_surplus_device, schedule_appliance")
