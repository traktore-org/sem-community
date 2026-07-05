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
from ..devices.base import SwitchDevice, CurrentControlDevice
from ..hardware_detection import discover_ev_charger_from_registry

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

    # (#559) goal properties settable via update_device_config / register
    GOAL_PROPERTIES = (
        "daily_min_runtime_min", "daily_max_runtime_min",
        "daily_target_energy_kwh", "daily_max_energy_kwh",
        "target_deadline", "top_up_policy",
        "stop_entity", "stop_at",
    )

    def _apply_goals(self, device) -> None:
        """Apply the persisted goal config onto a live device object."""
        goals = self._device_goals.get(device.device_id)
        if not goals:
            return
        device.daily_min_runtime_sec = int(
            float(goals.get("daily_min_runtime_min", 0)) * 60
        )
        device.daily_max_runtime_sec = int(
            float(goals.get("daily_max_runtime_min", 0)) * 60
        )
        device.daily_target_energy_kwh = float(
            goals.get("daily_target_energy_kwh", 0.0)
        )
        device.daily_max_energy_kwh = float(
            goals.get("daily_max_energy_kwh", 0.0)
        )
        device.target_deadline = str(goals.get("target_deadline", "") or "")
        device.top_up_policy = str(
            goals.get("top_up_policy", "solar_only") or "solar_only"
        )
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
            device = SwitchDevice(
                hass=self.hass,
                device_id=device_id,
                name=spec.get("name", device_id),
                rated_power=spec.get("rated_power", 1000),
                priority=spec.get("priority", 5),
                entity_id=spec.get("entity_id", ""),
                power_entity_id=spec.get("power_entity_id"),
            )
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
            "control_mode": spec.get("control_mode", "surplus"),
            "depends_on": list(spec.get("depends_on") or []),
        }
        self._service_registrations[device_id] = stored
        # keep the mode-overrides map consistent (same value, two readers)
        self._control_mode_overrides[device_id] = stored["control_mode"]
        # (Re-)create the live device — replaces any previous instance
        # under the same id.
        from ..devices.base import DeviceControlMode
        device = SwitchDevice(
            hass=self.hass,
            device_id=device_id,
            name=stored["name"],
            rated_power=stored["rated_power"],
            priority=stored["priority"],
            entity_id=stored["entity_id"],
            power_entity_id=stored["power_entity_id"],
        )
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
        return {
            "device_id": device_id,
            "name": stored["name"],
            "entity_id": stored["entity_id"],
            "priority": stored["priority"],
            "rated_power": stored["rated_power"],
            "control_mode": stored["control_mode"],
            "total_devices": len(self._surplus_controller._devices),
        }

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
        """Unregister ED-discovered devices that drive the same switch."""
        if not entity_id:
            return
        for did, dev in list(self._surplus_controller._devices.items()):
            if did == service_device_id or not did.startswith("energy_dashboard_"):
                continue
            if getattr(dev, "entity_id", None) == entity_id:
                _LOGGER.info(
                    "Dropping auto-discovered %s — switch %s is now "
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

            # Priority override from drag-and-drop
            priority = self._priority_overrides.get(device_id, position)

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

        # Sync to both systems
        self._sync_to_surplus_controller()
        self._sync_to_load_manager()

    def _sync_to_surplus_controller(self) -> None:
        """Create ControllableDevice objects and register with SurplusController.

        Skips EV charger — it's registered separately in __init__.py with
        special CurrentControlDevice config (phases, min/max current, service).
        """
        # Unregister old registry-managed devices (prefix: energy_dashboard_)
        existing_ids = list(self._surplus_controller._devices.keys())
        for did in existing_ids:
            if did.startswith("energy_dashboard_"):
                self._surplus_controller.unregister_device(did)

        for device in self._devices:
            if device.is_ev:
                continue  # EV charger handled by __init__.py
            if not device.is_controllable:
                continue

            control = device.control
            control_type = control.get("type", "switch") if control else "switch"

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
                    rated_power=self._get_power_rating(device.power_sensor),
                    priority=device.priority,
                    entity_id=entity,
                    power_entity_id=device.power_sensor,
                )
                # Apply persisted control mode (#49)
                from ..devices.base import DeviceControlMode
                mode_str = self._control_mode_overrides.get(device.device_id, "peak_only")
                try:
                    surplus_device.control_mode = DeviceControlMode(mode_str)
                except ValueError:
                    surplus_device.control_mode = DeviceControlMode.PEAK_ONLY
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
        for device in self._devices:
            did = device.device_id
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
                "power_rating": self._get_power_rating(device.power_sensor),
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
                **self._goal_payload(did),
            }

        # (#559) service-registered devices — pre-fix they never appeared
        # on the Control tab at all.
        for did, spec in self._service_registrations.items():
            if did in result:
                continue
            live = self._surplus_controller.get_device(did)
            is_on = bool(live and live.is_active)
            current_power = live.get_current_consumption() / 1000 if is_on and live else 0.0
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
                **self._goal_payload(did),
            }
        return result

    def _goal_payload(self, device_id: str) -> Dict[str, Any]:
        """Goal config + live progress for the card payload (#559)."""
        goals = self._device_goals.get(device_id, {})
        live = self._surplus_controller.get_device(device_id)
        runtime_min = 0.0
        energy_kwh = 0.0
        targets_met = False
        if live is not None:
            runtime_min = live._daily_runtime_accumulated_sec / 60
            energy_kwh = live._daily_energy_accumulated_kwh
            targets_met = bool(live.daily_targets_met)
        return {
            "goals": {
                "daily_min_runtime_min": goals.get("daily_min_runtime_min", 0),
                "daily_max_runtime_min": goals.get("daily_max_runtime_min", 0),
                "daily_target_energy_kwh": goals.get("daily_target_energy_kwh", 0),
                "daily_max_energy_kwh": goals.get("daily_max_energy_kwh", 0),
                "target_deadline": goals.get("target_deadline", ""),
                "top_up_policy": goals.get("top_up_policy", "solar_only"),
                "stop_entity": goals.get("stop_entity", ""),
                "stop_at": goals.get("stop_at", 0),
            },
            "progress": {
                "runtime_today_min": round(runtime_min, 1),
                "energy_today_kwh": round(energy_kwh, 2),
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

    async def _save_storage(self) -> None:
        """Persist manual mappings, priority overrides, and control modes."""
        data = {
            "mappings": self._manual_mappings,
            "priority_overrides": self._priority_overrides,
            "control_modes": self._control_mode_overrides,
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
