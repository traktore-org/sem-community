"""Unified Device Registry for SEM Solar Energy Management.

Single source of truth for all controllable devices. Reads devices from the
HA Energy Dashboard's "Individual devices" list, auto-discovers control
entities, and syncs to both SurplusController and LoadManagementCoordinator.

Flow:
    HA Energy Dashboard (.storage/energy)
        → device_consumption[] (flat list)
            ↓
    UnifiedDeviceRegistry
        → auto-discover control entity per device (3-strategy logic)
        → load manual mappings from .storage/sem_device_mappings
        → position in list = priority (overridable via drag-and-drop)
            ↓
        ├── SurplusController.register_device(ControllableDevice)
        ├── LoadManagement._devices[id] = dict
        └── sensor.sem_controllable_devices_count attributes (card reads this)
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers import entity_registry as er

from ..ha_energy_reader import read_energy_dashboard_config, get_all_individual_devices
from .load_device_discovery import LoadDeviceDiscovery
from ..devices.base import (
    SwitchDevice,
    CurrentControlDevice,
    surplus_device_from_spec,
)
from ..hardware_detection import discover_ev_charger_from_registry
from ..const import LOAD_PRIORITY_BASE as _LOAD_PRIORITY_BASE
from ..const import DEFAULT_DEVICE_RATED_POWER as _DEFAULT_RATED_POWER

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "sem_device_mappings"


@dataclass
class UnifiedDevice:
    """A device from the Energy Dashboard with discovered/mapped control."""

    energy_sensor: str
    power_sensor: Optional[str]
    name: str
    priority: int
    is_ev: bool = False
    control: Optional[Dict[str, Any]] = None
    is_critical: bool = False
    has_manual_mapping: bool = False

    @property
    def device_id(self) -> str:
        """Derive stable ID from energy sensor."""
        if "." in self.energy_sensor:
            name = self.energy_sensor.split(".", 1)[1]
        else:
            name = self.energy_sensor
        for suffix in ["_energy", "_total_energy", "_consumption", "_power"]:
            if name.endswith(suffix):
                name = name[: -len(suffix)]
                break
        return f"energy_dashboard_{name}"

    @property
    def is_controllable(self) -> bool:
        """Device is controllable if it has a control config."""
        return self.control is not None

    @property
    def control_entity(self) -> Optional[str]:
        """Extract entity from control dict."""
        if not self.control:
            return None
        return self.control.get("entity") or self.control.get("service")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize for sensor attributes / card consumption."""
        return {
            "name": self.name,
            "priority": self.priority,
            "is_controllable": self.is_controllable,
            "is_critical": self.is_critical,
            "power_entity": self.power_sensor,
            "energy_sensor": self.energy_sensor,
            "control": self.control,
            "control_entity": self.control_entity,
            "is_ev": self.is_ev,
            "has_manual_mapping": self.has_manual_mapping,
            "device_id": self.device_id,
        }


def _migrate_control_modes(overrides: Dict[str, str]) -> List[str]:
    """Map the removed 'surplus_target' control mode to 'surplus' in place (#235).

    Returns the list of device_ids that were migrated.
    """
    migrated = [did for did, mode in overrides.items() if mode == "surplus_target"]
    for did in migrated:
        overrides[did] = "surplus"
    return migrated


class UnifiedDeviceRegistry:
    """Reads Energy Dashboard devices, discovers controls, syncs to both systems."""

    def __init__(
        self,
        hass: HomeAssistant,
        surplus_controller,
        load_manager,
        discovery: LoadDeviceDiscovery,
    ):
        self.hass = hass
        self._surplus_controller = surplus_controller
        self._load_manager = load_manager
        self._discovery = discovery
        self._store = Store(hass, STORAGE_VERSION, STORAGE_KEY)
        self._devices: List[UnifiedDevice] = []
        self._manual_mappings: Dict[str, Dict[str, Any]] = {}
        self._priority_overrides: Dict[str, int] = {}
        self._control_mode_overrides: Dict[str, str] = {}  # device_id → "off"/"peak_only"/"surplus"
        # (#122/#576) device_id → [parent_id] "Requires" link. Persisted HERE so
        # a device rebuild (drag → async_refresh_devices, the 35s re-discovery,
        # config change, restart) re-applies it — pre-fix it lived only on the
        # transient live device and got wiped on every re-sync ("separated all
        # the time").
        self._dependency_overrides: Dict[str, list] = {}
        # (#576) device_id → learned rated_power (W). A sensor-equipped load
        # self-calibrates its real draw at runtime (calibrate_rated_power); we
        # PERSIST that here so it survives a restart instead of resetting to the
        # 1 kW default floor, and re-apply it when the device is rebuilt. Seeded
        # once from the power sensor's recorder history so a fresh device shows
        # its real rating immediately rather than the placeholder.
        self._rated_power_overrides: Dict[str, float] = {}
        # device_ids we've already tried to seed from history this session — so
        # a device with no history yet isn't re-queried on every 35 s refresh.
        self._rating_seed_attempted: set = set()
        # (#576) Only surface the home-battery priority row when the install
        # actually has a battery. Set by the coordinator each cycle from
        # ``power.battery_soc is not None``; batteryless systems never see it.
        self._has_battery: bool = False
        # (#576 P2.1) Configured EV chargers, handed over each cycle by the
        # coordinator (mirrors ``_has_battery``). Each is the authoritative
        # source for that charger's priority-list row, keyed by its CONTROL
        # id — so the card row, the drag store, ``distribute_ev_budget`` and
        # the reclaim gate all share ONE identity. The ED ``is_ev`` naming
        # guess is suppressed when chargers are configured (no double-add).
        self._ev_charger_rows: List[Dict[str, Any]] = []
        # (#559 Phase 0) Devices registered via the register_surplus_device
        # service. Pre-fix these lived only in the surplus controller's
        # memory and silently vanished on every restart.
        # device_id → {entity_id, name, priority, rated_power,
        #              power_entity_id, control_mode}
        self._service_registrations: Dict[str, Dict[str, Any]] = {}
        # (#559 Phases 1-3) per-device goal config (targets, deadline,
        # top-up policy, stop condition) — device_id → dict. Applies to
        # BOTH auto-discovered and service-registered devices.
        self._device_goals: Dict[str, Dict[str, Any]] = {}

    @property
    def devices(self) -> List[UnifiedDevice]:
        """Return current device list."""
        return self._devices

    async def async_initialize(self) -> None:
        """Load manual mappings from storage, then refresh devices.

        Also schedules a delayed re-discovery after 35s because at startup
        many entities aren't available yet (HA loads integrations in stages).
        """
        try:
            data = await self._store.async_load()
            if data:
                self._manual_mappings = data.get("mappings", {})
                self._priority_overrides = data.get("priority_overrides", {})
                self._control_mode_overrides: Dict[str, str] = data.get("control_modes", {})
                self._dependency_overrides = data.get("dependencies", {})
                self._rated_power_overrides = {
                    k: float(v) for k, v in
                    data.get("rated_power_overrides", {}).items()
                    if v is not None
                }
                self._service_registrations = data.get("service_registrations", {})
                self._device_goals = data.get("device_goals", {})
                # Migrate the removed "surplus_target" mode (#235): a device set to
                # surplus_target in v1.5.9 keeps surplus charging (rather than silently
                # falling back to peak_only). The "stop at target" intent is now the
                # separate "Limit surplus to target" switch, which the user can re-enable.
                migrated = _migrate_control_modes(self._control_mode_overrides)
                if migrated:
                    _LOGGER.info(
                        "Migrated %d device(s) from removed 'surplus_target' mode to 'surplus' (#235): %s",
                        len(migrated), ", ".join(migrated),
                    )
                _LOGGER.debug(
                    "Loaded %d manual mappings, %d priority overrides, %d control modes",
                    len(self._manual_mappings),
                    len(self._priority_overrides),
                    len(self._control_mode_overrides),
                )
        except Exception as e:
            _LOGGER.warning("Could not load device mappings: %s", e)

        await self.async_refresh_devices()

        # (#559 Phase 0) Re-register persisted service devices — pre-fix a
        # restart silently dropped everything the user registered.
        self._register_service_devices()

        # Schedule delayed re-discovery after entities are fully loaded
        async def _delayed_rediscovery():
            await asyncio.sleep(35)
            _LOGGER.info("Running delayed device re-discovery...")
            await self.async_refresh_devices()

        self.hass.async_create_task(_delayed_rediscovery())

    # (#559) goal properties settable via update_device_config / register.
    # Grounded core after the beta.19 freeze: runtime target + top-up policy
    # (solar_only|cheap_hours) + external stop condition. Deleted keys from
    # beta.18 (daily_max_runtime_min, daily_target_energy_kwh, daily_max_energy_kwh,
    # target_deadline) are ignored on load — see _apply_goals.
    GOAL_PROPERTIES = (
        "daily_min_runtime_min", "top_up_policy",
        "stop_entity", "stop_at",
    )

    def _apply_goals(self, device) -> None:
        """Apply the persisted goal config onto a live device object.

        Only the surviving grounded-core keys are read; any extra keys from
        beta.18-persisted devices (daily_max_*, daily_target_energy_kwh,
        target_deadline) are silently ignored so upgrades load cleanly."""
        goals = self._device_goals.get(device.device_id)
        if not goals:
            return
        device.daily_min_runtime_sec = int(
            float(goals.get("daily_min_runtime_min", 0)) * 60
        )
        policy = str(goals.get("top_up_policy", "solar_only") or "solar_only")
        if policy not in ("solar_only", "cheap_hours"):
            # migrate a legacy 'always' off the removed value AND clean the
            # stored dict so the next _save_storage doesn't roundtrip it back
            policy = "solar_only"
            goals["top_up_policy"] = "solar_only"
        device.top_up_policy = policy
        device.stop_entity = str(goals.get("stop_entity", "") or "")
        device.stop_at = float(goals.get("stop_at", 0.0) or 0.0)

    def seed_goals(self, device_id: str, goals: "Dict[str, Any]") -> None:
        """Stage goal fields before registration (register_surplus_device
        one-call path). Unknown properties are dropped."""
        clean = {k: v for k, v in goals.items() if k in self.GOAL_PROPERTIES}
        if clean:
            self._device_goals.setdefault(device_id, {}).update(clean)

    async def async_update_device_goal(
        self, device_id: str, prop: str, value: Any
    ) -> None:
        """Set one goal property, persist it, and apply it live (#559)."""
        if prop not in self.GOAL_PROPERTIES:
            raise ValueError(f"Unknown goal property: {prop}")
        goals = self._device_goals.setdefault(device_id, {})
        goals[prop] = value
        device = self._surplus_controller.get_device(device_id)
        if device:
            self._apply_goals(device)
        await self._save_storage()
        _LOGGER.info("Device goal updated: %s.%s = %s", device_id, prop, value)

    def _register_service_devices(self) -> None:
        """(Re-)register all persisted service registrations with the
        surplus controller."""
        from ..devices.base import DeviceControlMode
        for device_id, spec in self._service_registrations.items():
            device = surplus_device_from_spec(self.hass, device_id, spec)
            try:
                device.control_mode = DeviceControlMode(
                    spec.get("control_mode", "surplus")
                )
            except ValueError:
                device.control_mode = DeviceControlMode.SURPLUS
            if spec.get("depends_on"):
                device.depends_on = list(spec["depends_on"])
            self._apply_goals(device)
            if device.control_mode == DeviceControlMode.SURPLUS:
                device.adopt_if_running()  # (#559) re-own after restart
            self._surplus_controller.register_device(device)
        if self._service_registrations:
            _LOGGER.info(
                "Re-registered %d persisted service device(s): %s",
                len(self._service_registrations),
                ", ".join(self._service_registrations),
            )

    async def async_register_service_device(
        self, spec: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Register a surplus device from the register_surplus_device
        service — persisted, so it survives restarts (#559 Phase 0).

        Returns a summary dict for the service response.
        """
        device_id = spec["device_id"]
        stored = {
            "entity_id": spec.get("entity_id", ""),
            "name": spec.get("name") or device_id,
            "priority": spec.get("priority", 5),
            "rated_power": spec.get("rated_power", 1000),
            "power_entity_id": spec.get("power_entity_id"),
            "energy_entity_id": spec.get("energy_entity_id"),  # #600
            "control_mode": spec.get("control_mode", "surplus"),
            "depends_on": list(spec.get("depends_on") or []),
            # (#569) device kind + climate params — persisted so a climate
            # AC rehydrates as a ClimateDevice (not a SwitchDevice) on restart.
            "device_type": (spec.get("device_type") or "switch").lower(),
            "hvac_mode": spec.get("hvac_mode", "cool"),
            "target_temperature": spec.get("target_temperature"),
        }
        self._service_registrations[device_id] = stored
        # keep the mode-overrides map consistent (same value, two readers)
        self._control_mode_overrides[device_id] = stored["control_mode"]
        # (Re-)create the live device — replaces any previous instance
        # under the same id.
        from ..devices.base import DeviceControlMode
        device = surplus_device_from_spec(self.hass, device_id, stored)
        try:
            device.control_mode = DeviceControlMode(stored["control_mode"])
        except ValueError:
            device.control_mode = DeviceControlMode.SURPLUS
            stored["control_mode"] = "surplus"
        if stored["depends_on"]:
            device.depends_on = list(stored["depends_on"])
        self._apply_goals(device)
        self._surplus_controller.register_device(device)
        # Dedupe: if auto-discovery already registered this switch under an
        # energy_dashboard_* id, drop that instance — two device objects
        # driving one switch WILL fight. The explicit registration wins.
        self._drop_discovered_duplicates(device_id, stored["entity_id"])
        await self._save_storage()
        summary = {
            "device_id": device_id,
            "name": stored["name"],
            "entity_id": stored["entity_id"],
            "priority": stored["priority"],
            "rated_power": stored["rated_power"],
            "control_mode": stored["control_mode"],
            "device_type": stored["device_type"],
            "total_devices": len(self._surplus_controller._devices),
        }
        if stored["device_type"] == "climate":
            summary["hvac_mode"] = stored["hvac_mode"]
            summary["target_temperature"] = stored["target_temperature"]
        return summary

    async def async_unregister_service_device(self, device_id: str) -> bool:
        """Remove a service registration (and its live device).

        Returns True when something was removed."""
        if device_id not in self._service_registrations:
            # Auto-discovered devices are owned by ED discovery — removing
            # them here would be silently undone by the next refresh.
            return False
        self._service_registrations.pop(device_id, None)
        self._control_mode_overrides.pop(device_id, None)
        self._device_goals.pop(device_id, None)
        if self._surplus_controller.get_device(device_id):
            self._surplus_controller.unregister_device(device_id)
        await self._save_storage()
        return True

    def _drop_discovered_duplicates(
        self, service_device_id: str, entity_id: str
    ) -> None:
        """Unregister ED-discovered devices that drive the same entity."""
        if not entity_id:
            return
        for did, dev in list(self._surplus_controller._devices.items()):
            if did == service_device_id or not did.startswith("energy_dashboard_"):
                continue
            if getattr(dev, "entity_id", None) == entity_id:
                _LOGGER.info(
                    "Dropping auto-discovered %s — entity %s is now "
                    "explicitly registered as %s",
                    did, entity_id, service_device_id,
                )
                self._surplus_controller.unregister_device(did)

    async def async_refresh_devices(self) -> None:
        """Read Energy Dashboard, discover controls, build device list, sync."""
        energy_config = await read_energy_dashboard_config(self.hass)
        if not energy_config:
            _LOGGER.info("Energy Dashboard not configured, no devices to register")
            return

        individual_devices = get_all_individual_devices(energy_config, self.hass)
        if not individual_devices:
            _LOGGER.info("No individual devices in Energy Dashboard")
            return

        devices: List[UnifiedDevice] = []

        for position, dev_info in enumerate(individual_devices, start=1):
            energy_sensor = dev_info.get("energy_sensor", "")
            power_sensor = dev_info.get("power_sensor")
            name = dev_info.get("name", "")
            is_ev = dev_info.get("is_ev", False)

            # Build a temporary device to get device_id
            temp = UnifiedDevice(
                energy_sensor=energy_sensor,
                power_sensor=power_sensor,
                name=name,
                priority=position,
                is_ev=is_ev,
            )
            device_id = temp.device_id

            # Manual mapping takes precedence over auto-discovery
            has_manual = energy_sensor in self._manual_mappings
            if has_manual:
                control = self._manual_mappings[energy_sensor]
            else:
                control = self._discovery.discover_control_for_energy_device(
                    energy_sensor, power_sensor
                )

            # Priority override from drag-and-drop wins; else the default seed.
            # (#576) non-EV loads seed BELOW the battery band so the default
            # order is EV → battery → loads (loads yield to battery charging
            # until dragged above it). EV rows are suppressed here (sourced from
            # the charger config), so their seed is immaterial — leave as-is.
            seed = position if is_ev else position + _LOAD_PRIORITY_BASE
            priority = self._priority_overrides.get(device_id, seed)

            device = UnifiedDevice(
                energy_sensor=energy_sensor,
                power_sensor=power_sensor,
                name=name,
                priority=priority,
                is_ev=is_ev,
                control=control,
                has_manual_mapping=has_manual,
            )
            devices.append(device)

        # Sort by priority
        devices.sort(key=lambda d: d.priority)
        self._devices = devices

        _LOGGER.info(
            "UnifiedDeviceRegistry: %d devices from Energy Dashboard "
            "(%d controllable, %d manual mappings)",
            len(devices),
            sum(1 for d in devices if d.is_controllable),
            sum(1 for d in devices if d.has_manual_mapping),
        )

        # (#576) Preserve any rating the live loads self-calibrated to BEFORE
        # the rebuild replaces them (else the learned value resets to the 1 kW
        # floor and the card drops back to a 1 kW placeholder after every drag /
        # 35 s re-discovery / restart).
        dirty = self._capture_calibrated_ratings()

        # (#586) Snapshot each live device's accrued daily runtime BEFORE the
        # rebuild resets it. _sync_to_surplus_controller recreates every
        # auto-discovered (energy_dashboard_*) device as a fresh object with
        # _daily_runtime_accumulated_sec = 0.0, so without this the DAGDOEL
        # progress bar ("X/Y u op zon vandaag") reset to 0 on every 35 s
        # re-discovery / drag — not just the startup restore fixed in __init__.
        runtime_snapshot = self._capture_accrued_runtimes()

        # Sync to both systems
        self._sync_to_surplus_controller()
        self._sync_to_load_manager()

        # (#586) Re-apply the runtime snapshot onto the rebuilt devices.
        self._restore_accrued_runtimes(runtime_snapshot)

        # (#576) Re-apply the learned rating to the rebuilt devices, and seed a
        # rating from the power sensor's history for any load we haven't learned
        # yet. Persist once if anything changed.
        if (await self._seed_and_apply_ratings()) or dirty:
            await self._save_storage()

    def _sync_to_surplus_controller(self) -> None:
        """Create ControllableDevice objects and register with SurplusController.

        Skips EV charger — it's registered separately in __init__.py with
        special CurrentControlDevice config (phases, min/max current, service).
        """
        # Unregister old registry-managed devices (prefix: energy_dashboard_).
        # (#559) NEVER wipe a SERVICE-registered device, even when the user
        # picked an energy_dashboard_* id: the wipe removed it and the rebuild
        # below then SKIPPED recreating it (the entity-dedup correctly treats
        # the switch as service-owned) — so the device vanished entirely on
        # every re-discovery (the 35s delayed one after each restart included)
        # and the load never ran again (alexmc1510's pool pump). Ownership by
        # construction: service registrations survive discovery syncs with
        # their live object (and accrued daily runtime) intact.
        existing_ids = list(self._surplus_controller._devices.keys())
        for did in existing_ids:
            if did.startswith("energy_dashboard_") and did not in self._service_registrations:
                self._surplus_controller.unregister_device(did)

        for device in self._devices:
            if device.is_ev:
                continue  # EV charger handled by __init__.py
            if not device.is_controllable:
                continue

            control = device.control
            control_type = control.get("type", "switch") if control else "switch"

            # (#559) id collision: the discovery row's id is service-registered
            # (user picked the energy_dashboard_* namespace) — the service
            # device owns it; re-registering here would overwrite the explicit
            # object (rated_power, goals, runtime) with a discovery snapshot.
            if device.device_id in self._service_registrations:
                _LOGGER.debug(
                    "Skipping auto-discovered %s — id is service-registered",
                    device.device_id,
                )
                continue

            if control_type in ("switch", "input_boolean"):
                entity = control.get("entity", "")
                # (#559 Phase 0) dedupe: an explicitly service-registered
                # device owns its switch — don't spawn a second controller
                # for the same entity from auto-discovery.
                if entity and any(
                    spec.get("entity_id") == entity
                    for spec in self._service_registrations.values()
                ):
                    _LOGGER.debug(
                        "Skipping auto-discovered %s — %s is service-registered",
                        device.device_id, entity,
                    )
                    continue
                surplus_device = SwitchDevice(
                    hass=self.hass,
                    device_id=device.device_id,
                    name=device.name,
                    # (#576) persisted self-calibrated rating wins over the raw
                    # sensor (0 W when off → the 1 kW default), so the learned
                    # value survives the rebuild.
                    rated_power=self._initial_rated_power(
                        device.device_id, device.power_sensor),
                    priority=device.priority,
                    entity_id=entity,
                    power_entity_id=device.power_sensor,
                    # #600 — discovered devices carry an energy_sensor too; pass
                    # it so an energy-only individual device (power_sensor None)
                    # derives live power. The power_sensor, when present, still
                    # wins in observed_power_w (it IS the autodetected companion).
                    energy_entity_id=device.energy_sensor,
                )
                # Apply persisted control mode (#49)
                from ..devices.base import DeviceControlMode
                mode_str = self._control_mode_overrides.get(device.device_id, "peak_only")
                try:
                    surplus_device.control_mode = DeviceControlMode(mode_str)
                except ValueError:
                    surplus_device.control_mode = DeviceControlMode.PEAK_ONLY
                # (#122/#576) re-apply the persisted "Requires" link so a
                # rebuild doesn't wipe it — the root cause of "separated all
                # the time" (every drag/discovery/restart rebuilds the device).
                deps = self._dependency_overrides.get(device.device_id)
                if deps:
                    surplus_device.depends_on = list(deps)
                self._apply_goals(surplus_device)
                if surplus_device.control_mode == DeviceControlMode.SURPLUS:
                    surplus_device.adopt_if_running()  # (#559) re-own after restart
                self._surplus_controller.register_device(surplus_device)

            elif control_type == "current":
                entity = control.get("entity", "")
                surplus_device = CurrentControlDevice(
                    hass=self.hass,
                    device_id=device.device_id,
                    name=device.name,
                    priority=device.priority,
                    min_current=float(control.get("min_value", 6)),
                    max_current=float(control.get("max_value", 32)),
                    phases=1,
                    voltage=230.0,
                    current_entity_id=entity,
                    power_entity_id=device.power_sensor,
                )
                self._surplus_controller.register_device(surplus_device)

            elif control_type == "service":
                # Service-based control (e.g., keba.set_current) — create SwitchDevice
                # with the control entity (won't actually use switch turn_on/off but
                # surplus controller will manage it)
                _LOGGER.debug(
                    "Skipping service-based device %s for surplus (EV handled separately)",
                    device.device_id,
                )

    def _sync_to_load_manager(self) -> None:
        """Populate LoadManagement._devices dict from registry devices.

        Removes old pattern-discovered / manually-added devices that aren't
        from this registry, keeping only:
        - Devices managed by this registry (``energy_dashboard_*``)
        - Per-charger EV entries registered separately by ``__init__.py``
          (``load_device_<charger_id>`` for every ``ev_chargers[i].id``)

        #436: pre-fix this only spared the legacy hardcoded
        ``load_device_ev_charger`` key. After #436 makes the key
        per-charger, the second / third / Nth charger's entry uses
        ``load_device_ev_charger_1`` etc. — these were silently pruned
        on every device_registry sync. Widened to spare any
        ``load_device_*`` key so the multi-charger fix actually sticks.
        """
        if not self._load_manager:
            return

        # Remove old non-registry, non-EV devices
        old_ids = [
            did for did in list(self._load_manager._devices.keys())
            if not did.startswith("energy_dashboard_")
            and not did.startswith("load_device_")
            # (#559 Phase 0) never prune service-registered devices
            and did not in self._service_registrations
        ]
        for did in old_ids:
            del self._load_manager._devices[did]
            _LOGGER.debug("Removed old device from load manager: %s", did)

        for device in self._devices:
            device_id = device.device_id
            control = device.control

            # Build device info dict compatible with LoadManagementCoordinator
            device_info = {
                "power_entity": device.power_sensor,
                "energy_entity": device.energy_sensor,
                "switch_entity": None,
                "control": control,
                "friendly_name": device.name,
                "device_type": "ev_charger" if device.is_ev else "individual_device",
                "description": f"Energy Dashboard: {device.name}",
                "source": "unified_registry",
                "power_rating": self._get_power_rating(device.power_sensor),
                "is_available": True,
                "priority": device.priority,
                "is_critical": device.is_critical,
                "is_controllable": device.is_controllable,
                "is_ev": device.is_ev,
                "control_mode": self._control_mode_overrides.get(device.device_id, "peak_only"),
            }

            # Backwards-compatible switch_entity
            if control and control.get("type") == "switch":
                device_info["switch_entity"] = control.get("entity")

            self._load_manager._devices[device_id] = device_info

        _LOGGER.info(
            "Synced %d devices to LoadManagement", len(self._devices)
        )

    def get_devices_for_sensor(self) -> Dict[str, Dict[str, Any]]:
        """Return dict formatted for the controllable_devices_count sensor attributes."""
        result = {}
        # (#559) Entities that an explicit register_surplus_device call owns.
        # An auto-discovered ED device for the SAME switch must not shadow that
        # registration — otherwise the card showed the live sensor (0 W while
        # the load is off) instead of the user's rated_power, and the explicit
        # entry was skipped as a duplicate id. Suppress the auto-discovered row;
        # the authoritative service registration is added below with its
        # rated_power / priority / mode.
        service_entities = {
            spec.get("entity_id")
            for spec in self._service_registrations.values()
            if spec.get("entity_id")
        }
        # (#576 P2.1) When chargers are configured, they are the authoritative
        # source of EV rows (emitted below by control id). Suppress the ED
        # ``is_ev`` naming-guess rows so a charger never appears twice — root
        # cause of the drag-writes-a-dead-key split (card row id != control id).
        chargers_configured = bool(self._ev_charger_rows)
        charger_entities = self._configured_charger_entities()
        for device in self._devices:
            did = device.device_id
            if device.control_entity and device.control_entity in service_entities:
                continue
            if device.is_ev and (
                chargers_configured
                or (device.power_sensor and device.power_sensor in charger_entities)
            ):
                continue
            # Get live power reading
            current_power = 0.0
            is_on = False
            if device.power_sensor:
                state = self.hass.states.get(device.power_sensor)
                if state and state.state not in ("unknown", "unavailable"):
                    try:
                        current_power = float(state.state)
                        is_on = current_power > 0
                    except (ValueError, TypeError):
                        pass

            result[did] = {
                "name": device.name,
                "priority": device.priority,
                "is_controllable": device.is_controllable,
                "is_critical": device.is_critical,
                # (#559) rated_power, not the raw live sensor: the live
                # ControllableDevice carries a self-calibrating rated_power
                # (snapped to the real draw when the load runs), so an OFF
                # device shows its rated power instead of a bare 0 W. Falls
                # back to the live sensor when no device is registered yet.
                "power_rating": self._rated_power_for(did, device.power_sensor),
                "power_entity": device.power_sensor,
                "energy_sensor": device.energy_sensor,
                "switch_entity": device.control_entity,
                "is_available": True,
                "is_on": is_on,
                "current_power": current_power,
                "device_type": "ev_charger" if device.is_ev else "individual_device",
                "has_manual_mapping": device.has_manual_mapping,
                "control": device.control,
                "control_mode": self._control_mode_overrides.get(did, "peak_only"),
                # (#122/#576) the "Requires" link — read from the persistent
                # store so it both survives rebuilds AND shows on the card
                # (pre-fix it was never emitted, so the card couldn't display it).
                "depends_on": self._dependency_overrides.get(did, []),
                # (arc Phase 3) is it on because SEM turned it on, or externally?
                "sem_owned": bool(getattr(
                    self._surplus_controller.get_device(did), "_sem_owned", False)),
                **self._goal_payload(did),
            }

        # (#559) service-registered devices — pre-fix they never appeared
        # on the Control tab at all.
        for did, spec in self._service_registrations.items():
            if did in result:
                continue
            live = self._surplus_controller.get_device(did)
            is_on = bool(live and live.is_active)
            # WATTS — the card divides by 1000 then formats (ruflo HIGH: was
            # kW here, so a 2 kW draw rendered as "2 W"). Matches the ED rows.
            current_power = round(live.get_current_consumption()) if is_on and live else 0.0
            result[did] = {
                "name": spec.get("name", did),
                "priority": spec.get("priority", 5),
                "is_controllable": True,
                "is_critical": False,
                "power_rating": spec.get("rated_power", 1000),
                "power_entity": spec.get("power_entity_id"),
                "energy_sensor": None,
                "switch_entity": spec.get("entity_id"),
                "is_available": True,
                "is_on": is_on,
                "current_power": current_power,
                "device_type": "service_device",
                "has_manual_mapping": False,
                "control": {"type": "switch", "entity": spec.get("entity_id")},
                "control_mode": spec.get("control_mode", "surplus"),
                # (arc Phase 3) is it on because SEM turned it on, or externally?
                "sem_owned": bool(getattr(live, "_sem_owned", False)),
                **self._goal_payload(did),
            }

        # (#576) surplus-controller devices registered DIRECTLY (heat pump,
        # hot water, climate — not via the ED list or a service call) — emit
        # them so they're draggable too. Dedup by id: skip anything already
        # surfaced above (ED / service rows), so a device never appears twice.
        for did, dev in getattr(self._surplus_controller, "_devices", {}).items():
            if did in result or getattr(dev, "is_ev", False):
                continue
            result[did] = self._surplus_device_row(did, dev)

        # (#576 P2.1) configured EV chargers — first-class rows keyed by their
        # CONTROL id, sourced from the coordinator (not the ED is_ev guess).
        for charger in self._ev_charger_rows:
            cid = charger.get("id")
            if cid:
                result[cid] = self._ev_charger_row(charger)

        # (#576) the home battery — a draggable sink in the same priority list.
        # Loads ABOVE it reclaim the power that would charge the battery; loads
        # BELOW it yield. It's a passive device (no on/off, no mode): its only
        # control is its position, so the card renders just the drag handle,
        # name and priority. Live SOC / charge power come from the SEM sensors.
        # Only shown when the install actually has a battery.
        if self._has_battery:
            result[self._battery_device_id()] = self._battery_device_row()
        return result

    def _battery_device_id(self) -> str:
        from ..const import BATTERY_SURPLUS_DEVICE_ID
        return BATTERY_SURPLUS_DEVICE_ID

    def priority_for(self, device_id: str, seed: Optional[int] = None) -> int:
        """Authoritative priority for ANY device in the one list (#576 P2.1).

        A drag override always wins; else the caller's per-device ``seed``
        (e.g. config ``ev_surplus_priority`` for a charger, the ED position
        for a load, ``DEFAULT_BATTERY_SURPLUS_PRIORITY`` for the battery);
        else a large default that sinks unknown devices to the bottom.

        This is the SINGLE priority axis — loads, the battery, AND every EV
        charger read their slot from here, so the drag list is the one control.
        ``ev_surplus_priority`` is now just the boot seed for a charger's slot;
        the separate ``ev_shed_priority`` knob was removed (shed = reverse walk).
        """
        if device_id in self._priority_overrides:
            return int(self._priority_overrides[device_id])
        if seed is not None:
            return int(seed)
        return 999

    def battery_surplus_priority(self) -> int:
        """The battery's position in the surplus priority walk (drag-set)."""
        from ..const import (
            BATTERY_SURPLUS_DEVICE_ID, DEFAULT_BATTERY_SURPLUS_PRIORITY,
        )
        return self.priority_for(
            BATTERY_SURPLUS_DEVICE_ID, seed=DEFAULT_BATTERY_SURPLUS_PRIORITY)

    def _battery_device_row(self) -> Dict[str, Any]:
        def _num(entity: str):
            st = self.hass.states.get(entity)
            if st and st.state not in ("unknown", "unavailable"):
                try:
                    return float(st.state)
                except (ValueError, TypeError):
                    return None
            return None
        charge_w = _num("sensor.sem_battery_charge_power") or 0.0
        soc = _num("sensor.sem_battery_soc")   # None when momentarily unavailable
        # (#587) the synthetic battery row name is localized to the server
        # language — RienduPre saw a hardcoded English "Home battery" tile.
        from ..utils.translate import get_text
        return {
            "name": get_text(self.hass, "home_battery", "Home battery"),
            "priority": self.battery_surplus_priority(),
            "is_controllable": False,
            "is_critical": False,
            "power_rating": round(charge_w),
            "power_entity": "sensor.sem_battery_charge_power",
            "energy_sensor": None,
            "switch_entity": None,
            "is_available": True,
            "is_on": charge_w > 0,          # "on" = currently charging
            # WATTS — the card divides by 1000 then formats. Emitting kW here
            # showed a 2 kW charge as "2 W" (ruflo HIGH; matches the ED rows).
            "current_power": round(charge_w),
            "device_type": "battery",
            "has_manual_mapping": False,
            "control": {"type": "none"},
            "control_mode": "surplus",      # participates by position, no toggle
            "sem_owned": False,
            "soc": round(soc, 1) if soc is not None else None,
        }

    def _surplus_device_row(self, did: str, dev: Any) -> Dict[str, Any]:
        """(#576) Priority-list payload for a directly-registered surplus
        device (heat pump / hot water / climate), keyed by its id, with its
        drag-set (or config-seeded) priority so it's positionable like the
        loads, EV and battery."""
        is_on = bool(getattr(dev, "is_active", False))
        current_w = 0.0
        if is_on and hasattr(dev, "get_current_consumption"):
            try:
                current_w = float(dev.get_current_consumption() or 0.0)
            except (TypeError, ValueError):
                current_w = 0.0
        dtype = getattr(getattr(dev, "device_type", None), "value", None) or "individual_device"
        mode = getattr(getattr(dev, "control_mode", None), "value", None) or "surplus"
        return {
            "name": getattr(dev, "name", did),
            "priority": self.priority_for(
                did, seed=int(getattr(dev, "priority", 5) or 5)),
            "is_controllable": True,
            "is_critical": False,
            "power_rating": round(float(getattr(dev, "rated_power", 0) or 0)),
            "power_entity": getattr(dev, "power_entity_id", None),
            "energy_sensor": None,
            "switch_entity": getattr(dev, "entity_id", None),
            "is_available": True,
            "is_on": is_on,
            # WATTS (ruflo HIGH — the card divides by 1000; kW here showed
            # milliwatts). Matches the battery / ED rows.
            "current_power": round(current_w),
            "device_type": dtype,
            "has_manual_mapping": False,
            "control": {"type": "surplus"},
            "control_mode": mode,
            "sem_owned": bool(getattr(dev, "_sem_owned", False)),
        }

    def refresh_direct_device_priorities(self) -> None:
        """(#576) Make the drag store authoritative for directly-registered
        surplus devices (heat pump / hot water / climate) too — mirrors the EV
        charger refresh. ED / service devices already resolve via the registry
        sync; this covers the ones registered straight into the controller so
        their list position governs the walk (not just the card row)."""
        for did, dev in getattr(self._surplus_controller, "_devices", {}).items():
            if did.startswith("energy_dashboard_") or getattr(dev, "is_ev", False):
                continue
            if did in self._service_registrations:
                continue
            dev.priority = self.priority_for(
                did, seed=int(getattr(dev, "priority", 5) or 5))

    def set_ev_chargers(self, chargers: List[Dict[str, Any]]) -> None:
        """(#576 P2.1) The coordinator hands its configured chargers here each
        cycle, so each appears in the ONE priority list keyed by its CONTROL id.

        Each dict: ``{id, name, priority_seed, power_entity, current_power_w,
        is_on, max_power_w, connected}``. This is the single authoritative
        source for the EV rows — the ED ``is_ev`` naming guess is suppressed
        in :meth:`get_devices_for_sensor` while any charger is configured.
        """
        self._ev_charger_rows = list(chargers or [])

    def _configured_charger_entities(self) -> set:
        """Power entities of configured chargers — used to suppress the ED
        ``is_ev`` duplicate row for the same physical charger."""
        return {
            c.get("power_entity") for c in self._ev_charger_rows
            if c.get("power_entity")
        }

    def _ev_charger_row(self, charger: Dict[str, Any]) -> Dict[str, Any]:
        """Build the priority-list payload for one configured charger, keyed
        by its control id, with its drag-set (or seeded) priority."""
        cid = charger["id"]
        power_w = float(charger.get("current_power_w", 0.0) or 0.0)
        return {
            "name": charger.get("name", cid),
            "priority": self.priority_for(
                cid, seed=int(charger.get("priority_seed", 3))),
            "is_controllable": True,
            "is_critical": False,
            # Rating = the charger's MIN power (min_A × phases × voltage) — the
            # surplus THRESHOLD to start charging, the real analog of a heater's
            # rating (and far more meaningful than the 32A×3φ ~22 kW max, which
            # read as "the EV draws 22 kW"). The card shows the live draw while
            # charging and this threshold when idle. Falls back to the live draw
            # if min isn't available.
            "power_rating": round(float(charger.get("min_power_w", power_w) or power_w)),
            "power_entity": charger.get("power_entity"),
            "energy_sensor": None,
            "switch_entity": None,
            "is_available": True,
            "is_on": bool(charger.get("is_on", False)),
            # WATTS (ruflo HIGH — the card divides by 1000; kW here showed
            # milliwatts). Matches the battery / ED rows.
            "current_power": round(power_w),
            "device_type": "ev_charger",
            "has_manual_mapping": False,
            "control": {"type": "current"},
            "control_mode": "surplus",
            "sem_owned": False,
            "connected": bool(charger.get("connected", False)),
            "is_ev": True,
        }

    def _goal_payload(self, device_id: str) -> Dict[str, Any]:
        """Goal config + live progress for the card payload (#559)."""
        goals = self._device_goals.get(device_id, {})
        live = self._surplus_controller.get_device(device_id)
        runtime_min = 0.0
        targets_met = False
        if live is not None:
            runtime_min = live._daily_runtime_accumulated_sec / 60
            targets_met = bool(live.daily_targets_met)
        return {
            "goals": {
                "daily_min_runtime_min": goals.get("daily_min_runtime_min", 0),
                "top_up_policy": goals.get("top_up_policy", "solar_only"),
                "stop_entity": goals.get("stop_entity", ""),
                "stop_at": goals.get("stop_at", 0),
            },
            "progress": {
                "runtime_today_min": round(runtime_min, 1),
                "targets_met": targets_met,
            },
        }

    async def async_set_manual_mapping(
        self,
        energy_sensor: str,
        control_entity: str,
        control_type: str = "switch",
        *,
        service: Optional[str] = None,
        param: Optional[str] = None,
        shed_value: Optional[float] = None,
        restore_value: Optional[float] = None,
    ) -> None:
        """User maps a control for a device. Persists and re-syncs.

        Entity-based types (``switch``/``current``/``input_boolean``) store the
        chosen ``entity``. ``service`` stores the call definition
        (``service``/``param``/``shed_value``/``restore_value``) that
        ``load_management`` invokes to shed/restore — it has no entity (#219).
        """
        if control_type == "service":
            control: Dict[str, Any] = {
                "type": "service",
                "service": service,
                "param": param or "current",
                "shed_value": shed_value if shed_value is not None else 0,
                "restore_value": restore_value if restore_value is not None else 16,
                "discovered_via": "manual_mapping",
            }
            detail = service
        else:
            control = {
                "type": control_type,
                "entity": control_entity,
                "discovered_via": "manual_mapping",
            }
            detail = control_entity

        self._manual_mappings[energy_sensor] = control
        await self._save_storage()
        await self.async_refresh_devices()

        _LOGGER.info(
            "Manual mapping set: %s → %s (%s)", energy_sensor, detail, control_type
        )

    async def async_remove_manual_mapping(self, energy_sensor: str) -> bool:
        """Remove a manual mapping so the device reverts to auto-discovery (#219).

        Returns True if a mapping was removed. After removal, a re-sync re-runs
        discovery — the device gets its auto-detected control again, or none
        (e.g. a meter-only device), which is the "clear it and leave it" intent.
        """
        if energy_sensor not in self._manual_mappings:
            return False
        del self._manual_mappings[energy_sensor]
        await self._save_storage()
        await self.async_refresh_devices()
        _LOGGER.info("Manual mapping removed: %s", energy_sensor)
        return True

    async def async_update_priority_overrides(
        self, priorities: List[Dict[str, Any]]
    ) -> None:
        """Update priority overrides from drag-and-drop. Re-syncs."""
        for item in priorities:
            device_id = item.get("device_id")
            priority = item.get("priority")
            if device_id and priority is not None:
                self._priority_overrides[device_id] = int(priority)

        await self._save_storage()
        await self.async_refresh_devices()

    async def update_device_control_mode(self, device_id: str, mode: str) -> None:
        """Update a device's control mode and persist (#49).

        Args:
            device_id: Device identifier (e.g., "energy_dashboard_heizband")
            mode: "off", "peak_only", or "surplus"
        """
        from ..devices.base import DeviceControlMode
        try:
            control_mode = DeviceControlMode(mode)
        except ValueError:
            _LOGGER.warning("Invalid control mode '%s' for %s", mode, device_id)
            return

        self._control_mode_overrides[device_id] = mode
        # (#559 Phase 0) mode changes on service-registered devices persist
        # in their registration spec so the re-register at boot applies them.
        if device_id in self._service_registrations:
            self._service_registrations[device_id]["control_mode"] = mode

        # Apply to running surplus device if registered
        surplus_device = self._surplus_controller.get_device(device_id)
        if surplus_device:
            surplus_device.control_mode = control_mode
            _LOGGER.info(
                "Updated %s control mode to %s", device_id, mode,
            )

        await self._save_storage()

    async def async_set_dependency(self, device_id: str, depends_on) -> None:
        """Set (or clear) a device's "Requires" link and persist it (#122/#576).

        Stored in the registry (``_dependency_overrides``) so it survives every
        device rebuild — a drag, the 35s re-discovery, a config change, or a
        restart — instead of only living on the transient live device (which
        got wiped on each re-sync). Applied live immediately too.
        """
        # Guard against self-dependency (device requires itself) — it would
        # deadlock activation forever and persist across restarts (ruflo HIGH).
        deps = [str(d) for d in (
            depends_on if isinstance(depends_on, (list, tuple)) else [depends_on]
        ) if d and str(d) != device_id]
        # Guard against a TRANSITIVE cycle (A requires B, B requires A) — a
        # multi-hop self-dependency that the single-hop guard above misses. It
        # would deadlock BOTH devices (each waits on the other) and persist
        # across restarts (ruflo MEDIUM). Reject the write, keep the old link.
        cyclic = [d for d in deps
                  if self._dependency_would_cycle(device_id, d)]
        if cyclic:
            _LOGGER.warning(
                "Rejected circular dependency: %s requires %s (would form a "
                "cycle); keeping the existing link", device_id, cyclic,
            )
            deps = [d for d in deps if d not in cyclic]
        if deps:
            self._dependency_overrides[device_id] = deps
        else:
            self._dependency_overrides.pop(device_id, None)
        # Service-registered devices carry depends_on in their spec too.
        if device_id in self._service_registrations:
            self._service_registrations[device_id]["depends_on"] = deps
        live = self._surplus_controller.get_device(device_id)
        if live is not None:
            live.depends_on = list(deps)
        await self._save_storage()
        _LOGGER.info("Device dependency set: %s requires %s", device_id, deps or "nothing")

    def _dependency_would_cycle(self, device_id: str, new_parent: str) -> bool:
        """Would making ``device_id`` require ``new_parent`` close a cycle?

        True iff ``device_id`` is already reachable UP the existing "requires"
        graph from ``new_parent`` (so the new edge would loop back). Walks ALL
        parents (a device can require several) with a visited-set, so it's
        bounded even if the stored graph already contains a stray cycle."""
        stack = [new_parent]
        seen = set()
        while stack:
            node = stack.pop()
            if node == device_id:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self._dependency_overrides.get(node, []))
        return False

    async def _save_storage(self) -> None:
        """Persist manual mappings, priority overrides, and control modes."""
        data = {
            "mappings": self._manual_mappings,
            "priority_overrides": self._priority_overrides,
            "control_modes": self._control_mode_overrides,
            "dependencies": self._dependency_overrides,
            "rated_power_overrides": self._rated_power_overrides,
            "service_registrations": self._service_registrations,
            "device_goals": self._device_goals,
        }
        await self._store.async_save(data)
        _LOGGER.debug("Saved device mappings to storage")

    def discover_ev_charger(self) -> Dict[str, Any]:
        """Auto-discover EV charger config from known integrations.

        Delegates to hardware_detection.discover_ev_charger_from_registry()
        which queries the entity registry for supported EV charger integrations.

        Returns:
            Dict with config keys (ev_connected_sensor, ev_charging_sensor, etc.)
            Only includes keys where entities were found.
        """
        return discover_ev_charger_from_registry(self.hass)

    def _get_power_rating(self, power_sensor: Optional[str]) -> float:
        """Get current power reading from sensor."""
        if not power_sensor:
            return 0.0
        state = self.hass.states.get(power_sensor)
        if state and state.state not in ("unknown", "unavailable"):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return 0.0

    def _rated_power_for(self, device_id: str, power_sensor: Optional[str]) -> float:
        """(#559) The device's rated power for the Control card.

        Prefers the live ControllableDevice's ``rated_power`` — a stable value
        that self-calibrates to the real draw when the load runs — over the raw
        power sensor, which reads 0 W whenever the load is off. Falls back to the
        live sensor reading when no device is registered (or its rating is 0).
        """
        live = self._surplus_controller.get_device(device_id)
        rated = float(getattr(live, "rated_power", 0) or 0) if live else 0.0
        if rated > 0:
            return rated
        return self._get_power_rating(power_sensor)

    def _initial_rated_power(self, device_id: str, power_sensor: Optional[str]) -> float:
        """(#576) The rated power to hand a freshly-built device.

        A persisted, self-calibrated value wins — so a sensor-equipped load
        keeps its learned rating across a restart / rebuild instead of dropping
        back to the 1 kW floor. Else the live sensor reading (0 when the load is
        off), which ``SwitchDevice.__init__`` turns into the 1 kW default."""
        override = float(self._rated_power_overrides.get(device_id, 0) or 0)
        if override > 0:
            return override
        return self._get_power_rating(power_sensor)

    def _capture_calibrated_ratings(self) -> bool:
        """(#576) Snapshot any rating a live device self-calibrated UP to, into
        the persistent overrides — BEFORE ``_sync_to_surplus_controller`` rebuilds
        the devices and resets ``rated_power`` to the default. Only records real,
        above-floor values; returns True if anything changed."""
        dirty = False
        for did, dev in getattr(self._surplus_controller, "_devices", {}).items():
            if getattr(dev, "is_ev", False) or not getattr(dev, "power_entity_id", None):
                continue
            rated = getattr(dev, "rated_power", None)
            if rated is None:
                continue
            rated = float(rated)
            prev = float(self._rated_power_overrides.get(did, 0) or 0)
            if rated > _DEFAULT_RATED_POWER and rated > prev:
                self._rated_power_overrides[did] = rated
                dirty = True
        return dirty

    def _capture_accrued_runtimes(self) -> "Dict[str, tuple]":
        """(#586) Snapshot each live device's accrued daily runtime + meter day
        BEFORE ``_sync_to_surplus_controller`` rebuilds the auto-discovered
        devices (which resets ``_daily_runtime_accumulated_sec`` to 0.0).

        Only records devices that have actually accrued something for a known
        meter day — a fresh device (0.0) has nothing worth preserving. Paired
        with :meth:`_restore_accrued_runtimes`."""
        snapshot: Dict[str, tuple] = {}
        for did, dev in getattr(self._surplus_controller, "_devices", {}).items():
            meter_day = getattr(dev, "_daily_runtime_meter_day", None)
            accrued = float(getattr(dev, "_daily_runtime_accumulated_sec", 0.0) or 0.0)
            if meter_day is not None and accrued > 0.0:
                snapshot[did] = (accrued, meter_day)
        return snapshot

    def _restore_accrued_runtimes(self, snapshot: "Dict[str, tuple]") -> None:
        """(#586) Re-apply a pre-rebuild runtime snapshot onto the rebuilt
        devices. A freshly rebuilt auto-discovered device starts at 0.0; this
        refills it so its DAGDOEL progress survives the rebuild.

        Only fills a device that came back EMPTY — never clobbers runtime that
        already accrued (a service-registered device keeps its live object
        across the sync, so its value is intact and must be left alone)."""
        for did, (accrued, meter_day) in snapshot.items():
            dev = self._surplus_controller.get_device(did)
            if dev is None:
                continue
            if float(getattr(dev, "_daily_runtime_accumulated_sec", 0.0) or 0.0) <= 0.0:
                dev._daily_runtime_accumulated_sec = accrued
                dev._daily_runtime_meter_day = meter_day

    async def _seed_and_apply_ratings(self) -> bool:
        """(#576) After the rebuild: (a) apply a persisted override to any live
        device that came back at a lower rating, and (b) for a sensor-equipped
        device we haven't learned yet, seed its rating from the power sensor's
        recorder-history running max. Returns True if anything changed."""
        dirty = False
        for did, dev in getattr(self._surplus_controller, "_devices", {}).items():
            sensor = getattr(dev, "power_entity_id", None)
            if getattr(dev, "is_ev", False) or not sensor:
                continue
            if getattr(dev, "rated_power", None) is None:
                continue
            override = float(self._rated_power_overrides.get(did, 0) or 0)
            # (b) one-shot history seed for a device we've never learned.
            if override <= 0 and did not in self._rating_seed_attempted:
                self._rating_seed_attempted.add(did)
                hist_max = await self._history_max_power(sensor)
                if hist_max > _DEFAULT_RATED_POWER:
                    override = hist_max
                    self._rated_power_overrides[did] = hist_max
                    dirty = True
            # (a) apply the learned rating if the rebuilt device is below it.
            if override > 0 and override > float(getattr(dev, "rated_power", 0) or 0):
                dev.rated_power = override
                if hasattr(dev, "min_power_threshold"):
                    dev.min_power_threshold = override
        return dirty

    async def _history_max_power(self, power_sensor: str, days: int = 7) -> float:
        """(#576) Largest numeric value the power sensor reported in the last
        ``days`` — the load's real running draw. 0.0 if the recorder is
        unavailable or has no usable history (best-effort, never raises)."""
        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import (
                state_changes_during_period,
            )
            from homeassistant.util import dt as dt_util
            from datetime import timedelta as _timedelta

            end = dt_util.utcnow()
            start = end - _timedelta(days=days)
            history = await get_instance(self.hass).async_add_executor_job(
                state_changes_during_period, self.hass, start, end, str(power_sensor),
            )
            mx = 0.0
            for st in history.get(power_sensor, []):
                try:
                    v = float(st.state)
                except (ValueError, TypeError):
                    continue
                if v > mx:
                    mx = v
            return mx
        except Exception as e:  # noqa: BLE001 — best-effort seed, never blocks setup
            _LOGGER.debug(
                "rated-power history seed for %s unavailable: %s", power_sensor, e,
            )
            return 0.0
