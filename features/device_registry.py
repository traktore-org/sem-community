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
                _LOGGER.debug(
                    "Loaded %d manual mappings, %d priority overrides, %d control modes",
                    len(self._manual_mappings),
                    len(self._priority_overrides),
                    len(self._control_mode_overrides),
                )
        except Exception as e:
            _LOGGER.warning("Could not load device mappings: %s", e)

        await self.async_refresh_devices()

        # Schedule delayed re-discovery after entities are fully loaded
        async def _delayed_rediscovery():
            await asyncio.sleep(35)
            _LOGGER.info("Running delayed device re-discovery...")
            await self.async_refresh_devices()

        asyncio.create_task(_delayed_rediscovery())

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
        - Devices managed by this registry (energy_dashboard_*)
        - EV charger registered separately by __init__.py (load_device_ev_charger)
        """
        if not self._load_manager:
            return

        # Remove old non-registry, non-EV devices
        old_ids = [
            did for did in list(self._load_manager._devices.keys())
            if not did.startswith("energy_dashboard_") and did != "load_device_ev_charger"
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
            }
        return result

    async def async_set_manual_mapping(
        self,
        energy_sensor: str,
        control_entity: str,
        control_type: str = "switch",
    ) -> None:
        """User maps a control entity for a device. Persists and re-syncs."""
        control: Dict[str, Any] = {
            "type": control_type,
            "entity": control_entity,
            "discovered_via": "manual_mapping",
        }

        self._manual_mappings[energy_sensor] = control
        await self._save_storage()
        await self.async_refresh_devices()

        _LOGGER.info(
            "Manual mapping set: %s → %s (%s)", energy_sensor, control_entity, control_type
        )

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
