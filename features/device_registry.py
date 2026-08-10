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
from typing import Any, Callable, Dict, List, Optional

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


def _goal_bool(value: Any) -> bool:
    """(#620) Parse a stored goal bool. The service persists these as STRINGS
    ("True"/"False"), and ``bool("False")`` is True in Python — so an explicit
    truthiness test is required, never bool(). Accepts native bools too."""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in ("true", "1", "on", "yes")


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
    # (#650) "hands off this device" — the user's explicit opt-out, applied from
    # the registry's ``_controllable_overrides`` at build. Only ever RESTRICTS:
    # ``True`` can't invent controllability on a device with no control config
    # (LoadManagement would count it as sheddable and then have nothing to
    # switch), so re-enabling clears the override back to the derived value.
    controllable_override: Optional[bool] = None

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
        """Device is controllable if it has a control config.

        (#650) A stored ``controllable_override`` of ``False`` wins — that's the
        user saying "never touch this load". See the field's docstring for why
        ``True`` is not the symmetric case.
        """
        if self.controllable_override is False:
            return False
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
        # (#650) device_id → user's "critical" / "controllable" toggles from the
        # priority card. Persisted HERE, exactly like the dependency and
        # priority overrides above, because ``_sync_to_load_manager``
        # WHOLESALE-REPLACES the LoadManagement entry on every rebuild (drag,
        # the 35 s re-discovery, a config change, restart). Pre-fix these two
        # flags lived only in that dict, so "hands off the pond pump" or "the
        # freezer is critical" silently reverted to the defaults within 35 s and
        # the next peak event shed the device anyway.
        # ``_critical_overrides`` stores BOTH values (False is a meaningful
        # "un-mark it"); ``_controllable_overrides`` stores only False — a True
        # override can't invent controllability, so re-enabling deletes the key.
        self._critical_overrides: Dict[str, bool] = {}
        self._controllable_overrides: Dict[str, bool] = {}
        # (#650) the legacy adoption must run EXACTLY ONCE. On any later refresh
        # the LoadManagement dict is the registry's OWN last sync, so re-reading
        # it resurrects a flag the user just cleared: re-enabling "controllable"
        # DELETES the key, and a second adoption pass would immediately put it
        # back from the not-yet-resynced LM entry. That is this very bug, rebuilt.
        self._legacy_flags_adopted: bool = False
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
        # id — so the card row, the drag store, the per-charger loop and
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
        # Serialize goal writes: async_update_device_goal is a read-modify-write
        # that snapshots the dict inside _save_storage across await points, so
        # two concurrent updates (the card writes stop_entity + stop_at as two
        # separate calls) could interleave and one stale snapshot would clobber
        # the other — the value would silently drop back to 0 (caught live on
        # the Heizband PROD test). One lock makes each update atomic.
        self._goal_write_lock = asyncio.Lock()
        # (#622) Callback that re-applies persisted per-device accrued daily
        # runtime from the coordinator's storage onto any device that came back
        # EMPTY after a rebuild. Set by the coordinator after construction.
        # Runtime uniquely lives in the coordinator's daily store (not this
        # registry's override store), so unlike rated_power / dependencies /
        # goals it isn't re-applied from _store during _sync_to_surplus_controller;
        # this hook closes that gap for a device that appears only via the 35 s
        # delayed re-discovery, after the one-shot setup restore already ran.
        self._runtime_restore_hook: Optional[Callable[[], None]] = None

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
                # (#650) tolerate legacy/hand-edited stores: coerce to bool
                self._critical_overrides = {
                    k: bool(v) for k, v in data.get("critical_overrides", {}).items()
                }
                self._controllable_overrides = {
                    k: bool(v) for k, v in data.get("controllable_overrides", {}).items()
                }
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

        # (#662) Both dependency stores are loaded now — break any cycle a
        # pre-guard or hand-edited store carried in, before a device can
        # deadlock on it. Persist the repair so the warning doesn't fire again
        # on every future restart. Deliberately outside the load try/except:
        # a failure here is a SAVE failure and must not be reported as
        # "could not load device mappings". The repair itself already holds
        # in memory either way, so a failed save only costs us a repeat on the
        # next restart.
        try:
            if self._sanitize_dependency_cycles():
                await self._save_storage()
        except Exception as e:  # pragma: no cover - defensive
            _LOGGER.warning("Could not persist dependency-cycle repair: %s", e)

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
        # (#620) max cap + the two battery tiers.
        "daily_max_runtime_min", "battery_assist_enabled",
        "battery_eligible_overnight",
        # (#688) per-load anti-cycling (minutes) — overrides the SwitchDevice
        # default window. Absent keeps the constructor default (never 0).
        "min_on_time_min", "min_off_time_min",
        # (#705) thermal comfort band — Phase 1 consumes them on climate
        # devices; stored against any device (Phase 2 opens switch loads).
        "comfort_entity", "comfort_target", "comfort_offset", "comfort_limit",
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
        # (#620) daily max cap (persisted → restored, the #559 HIGH-1 fix) +
        # the two battery tiers. All default off so an upgraded device with no
        # stored values behaves exactly as before. NOTE: the service stores
        # these as STRINGS ("True"/"False") — ``bool("False")`` is True in
        # Python, so parse with an explicit truthiness test, never bool().
        device.daily_max_runtime_sec = int(
            float(goals.get("daily_max_runtime_min", 0) or 0) * 60
        )
        device.battery_assist_enabled = _goal_bool(goals.get("battery_assist_enabled"))
        device.battery_eligible_overnight = _goal_bool(
            goals.get("battery_eligible_overnight")
        )
        # (#688) per-load anti-cycling. Applied ONLY when the key is present, so a
        # device that carries other goals but no anti-cycle override keeps its
        # constructor default window (unconditional set with a 0 default would
        # DISABLE anti-cycling — the very bug being fixed). Minutes → seconds.
        if "min_on_time_min" in goals:
            device.min_on_seconds = int(float(goals.get("min_on_time_min") or 0) * 60)
        if "min_off_time_min" in goals:
            device.min_off_seconds = int(float(goals.get("min_off_time_min") or 0) * 60)
        # (#705) comfort band. Key-present-only (the #688 pattern) so devices
        # without comfort goals keep their constructor values; plain setattr
        # so a comfort goal stored against a non-climate device lands as an
        # unused attribute instead of crashing the rebuild (Phase 2 reads it).
        if "comfort_entity" in goals:
            device.comfort_entity = str(goals.get("comfort_entity", "") or "")
        for _ck in ("comfort_target", "comfort_offset", "comfort_limit"):
            if _ck in goals:
                try:
                    setattr(device, _ck, float(goals.get(_ck) or 0.0))
                except (TypeError, ValueError):
                    setattr(device, _ck, 0.0)

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
        async with self._goal_write_lock:
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
        # (#662) This is the ONLY multi-dependency write path SEM has (the UI
        # select is single-value), and it was the one with no cycle guard.
        # Validate against the current graph BEFORE storing, so the edges
        # being checked aren't already in it.
        # Self-dependency is caught by the same call — ``_dependency_would_cycle``
        # returns True for device_id == parent (this path has no separate
        # self-filter the way ``async_set_dependency`` does).
        requested_deps = [str(d) for d in (spec.get("depends_on") or [])]
        safe_deps = []
        for dep in requested_deps:
            if self._dependency_would_cycle(device_id, dep):
                _LOGGER.warning(
                    "register_surplus_device %s: dropped circular dependency "
                    "on %s (would deadlock both devices); registering without "
                    "it", device_id, dep,
                )
                continue
            safe_deps.append(dep)
        spec = {**spec, "depends_on": safe_deps}
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
        # (#748) Reconcile persisted charger-duplicate rows FIRST, before the
        # early-returns below. A persisted ``load_device_<slug>`` smart-switch
        # dup is immortal regardless of ED shape (the sync's prune spares every
        # ``load_device_*`` key), so an install with a charger but NO Energy
        # Dashboard individual devices — where the two returns below skip the
        # sync entirely — would otherwise keep its duplicate forever. This pass
        # depends only on the charger rows + LoadManagement._devices, not on the
        # ED, so it runs on every refresh (incl. the 35 s rediscovery, by which
        # time the charger rows are populated).
        await self._reconcile_charger_dups_and_persist()

        energy_config = await read_energy_dashboard_config(self.hass)
        if not energy_config:
            _LOGGER.info("Energy Dashboard not configured, no devices to register")
            return

        individual_devices = get_all_individual_devices(energy_config, self.hass)
        if not individual_devices:
            _LOGGER.info("No individual devices in Energy Dashboard")
            return

        # (#650) One-time adoption: users who toggled critical/controllable
        # BEFORE the override stores existed have their choice only in the
        # LoadManagement store. Read it once into the registry so the upgrade
        # doesn't hand them the very reset this issue is about.
        await self._adopt_legacy_device_flags()

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
                # (#650) re-apply the user's flags — the rebuild is exactly
                # where they used to be lost.
                is_critical=bool(self._critical_overrides.get(device_id, False)),
                controllable_override=self._controllable_overrides.get(device_id),
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
        # (#748) _sync_to_load_manager now also drops charger-duplicate rows
        # from LoadManagement._devices (the data-layer fold #700 never did) —
        # including any ED row it just re-added that names a charger entity. If
        # it removed any, de-persist immediately — the row lives in
        # LoadManagement's OWN store and is otherwise reloaded on every restart
        # (its prune spares all load_device_* keys). Without this, the fix only
        # helps installs that never had the duplicate.
        if self._sync_to_load_manager():
            try:
                await self._load_manager._save_device_configuration()
            except Exception as e:  # never let a persist hiccup break discovery
                _LOGGER.debug(
                    "#748 de-persist after charger-dup prune failed: %s", e)

        # (#586) Re-apply the runtime snapshot onto the rebuilt devices.
        self._restore_accrued_runtimes(runtime_snapshot)

        # (#622) The in-memory snapshot above only carries runtime that was
        # already live in this process. A device that appears for the FIRST
        # time after a restart — e.g. an auto-discovered load whose switch
        # entity wasn't ready at setup, so it's created only by the 35 s
        # delayed re-discovery — has no snapshot entry and comes back at 0.0.
        # Re-apply the persisted runtime from the coordinator's storage so its
        # daily-target progress survives instead of resetting to 0 and re-running
        # the whole target every restart (alexmc1510's pool pump).
        if self._runtime_restore_hook is not None:
            try:
                self._runtime_restore_hook()
            except Exception as e:  # never let restore break discovery
                _LOGGER.debug("Runtime restore hook failed: %s", e)

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

    def _sync_to_load_manager(self) -> bool:
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
            return False

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
                # (#649) Is this device driven by the surplus controller? Only
                # then may load_management stand down from shedding it — a
                # surplus-mode device with no live controller object (e.g. a
                # service-control type, which _sync_to_surplus_controller
                # skips) would otherwise be shed by nobody. This sync runs
                # right after _sync_to_surplus_controller, so the lookup sees
                # this cycle's registrations.
                "surplus_managed": self._surplus_controller is not None
                and self._surplus_controller.get_device(device.device_id) is not None,
            }

            # Backwards-compatible switch_entity
            if control and control.get("type") == "switch":
                device_info["switch_entity"] = control.get("entity")

            self._load_manager._devices[device_id] = device_info

        # (#748) DATA-LAYER charger-duplicate reconcile — the twin of the #700
        # display fold. #700 suppressed the duplicate only in
        # get_devices_for_sensor (the card payload); it never removed the row
        # from LoadManagement._devices, and _sync_to_load_manager's prune above
        # deliberately SPARES every ``load_device_*`` key (#436) — so a
        # persisted smart-switch row (``load_device_<slug>``) that shares the
        # charger's stop switch, and any ED row re-added just above that names a
        # charger entity, survived here: controllable, sheddable, acting on the
        # charger behind the EV controller's back. Drop them now, at the
        # registry (identity) level — the authoritative per-charger rows
        # (``load_device_<charger_id>``) are kept.
        pruned = self._prune_charger_duplicate_lm_rows()

        _LOGGER.info(
            "Synced %d devices to LoadManagement", len(self._devices)
        )
        return pruned

    async def _reconcile_charger_dups_and_persist(self) -> None:
        """(#748) Drop charger-duplicate LoadManagement rows and de-persist if
        anything changed. Idempotent — safe to call more than once per refresh.
        Never raises: a persist hiccup must not break device discovery."""
        try:
            if self._prune_charger_duplicate_lm_rows() and self._load_manager:
                await self._load_manager._save_device_configuration()
        except Exception as e:  # never let a persist hiccup break discovery
            _LOGGER.debug("#748 charger-dup reconcile/persist failed: %s", e)

    def _prune_charger_duplicate_lm_rows(self) -> bool:
        """(#748) Remove LoadManagement rows whose power / control / energy
        entity belongs to a configured charger — the data-layer version of the
        #700 identity fold. Everything that shares a charger's declared entity
        is a duplicate of that charger and is deleted; the authoritative
        per-charger rows (``load_device_<charger_id>``) ARE the chargers and are
        kept. Returns True if it removed anything, so the caller can de-persist.
        Never raises: a bad row must not break the device sync."""
        lm = self._load_manager
        if not lm or not self._ev_charger_rows:
            return False
        # Fail SAFE, not open: if any charger row lacks an id we cannot build
        # the protected authoritative set for it, and pruning could then delete
        # that charger's own load row (it names charger entities by design). A
        # populated row always carries an id (``_charger_priority_rows`` sets
        # it); a missing one is a bug upstream — prune nothing rather than risk
        # shedding the authoritative charger.
        if any(not c.get("id") for c in self._ev_charger_rows):
            _LOGGER.debug(
                "#748 skipping charger-dup prune: a charger row has no id")
            return False
        charger_entities = self._configured_charger_entities()
        # The authoritative rows: one per configured charger, keyed by its id
        # (register_ev_charger → ``load_device_<charger_id>``). These name a
        # charger entity BY DESIGN (their own current/power entity) and must
        # never be pruned as duplicates of themselves.
        authoritative = {
            f"load_device_{c.get('id')}" for c in self._ev_charger_rows
        }
        removed: List[str] = []
        for did, info in list(getattr(lm, "_devices", {}).items()):
            if did in authoritative:
                continue
            control = info.get("control") or {}
            # Direct entity-string identity: any entity the row names that the
            # charger declares (power sensor, stop switch, current number,
            # status sensor, control/service).
            string_candidates = [
                info.get("power_entity"),
                info.get("switch_entity"),
                info.get("energy_entity"),
                control.get("entity"),
                control.get("service"),
            ]
            # Registry-device identity (same HA device as the charger): kept
            # NARROW — only the power / energy sensors, exactly like the #700
            # display fold. A shared-device match on an arbitrary control/switch
            # entity would be broader than the card path and could catch a
            # co-located but separate load; the string match above already
            # covers a switch/number that IS a charger entity.
            device_candidates = [
                info.get("power_entity"),
                info.get("energy_entity"),
            ]
            hit = any(e and e in charger_entities for e in string_candidates) or any(
                self._same_registry_device_as_charger(e)
                for e in device_candidates if e
            )
            if hit:
                removed.append(did)
        for did in removed:
            try:
                del lm._devices[did]
            except KeyError:  # pragma: no cover - defensive
                continue
            _LOGGER.info(
                "#748 dropped charger-duplicate load row %s "
                "(shares a configured charger's entity)", did,
            )
        return bool(removed)

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
        # (#615) Entities claimed by a directly-registered heat pump / hot
        # water / climate device. An ED individual-device row for the SAME
        # physical appliance is suppressed so it never appears twice.
        direct_entities = self._direct_registration_entities()
        for device in self._devices:
            did = device.device_id
            if device.control_entity and device.control_entity in service_entities:
                continue
            # (#700) Identity-based charger dedup. The old gate required the
            # ED row's ``is_ev`` flag — an English-only name-pattern guess
            # ("ev", "charger", "wallbox", …), so a Swedish "Billaddare" row
            # for the SAME Garo the user configured as a charger survived
            # and Load Management showed the charger twice. Names can't
            # cover languages; identity can: the ED row is suppressed when
            # its power/energy sensor IS a configured charger's entity or
            # lives on the same HA registry device as one (any entity on
            # the charger's own device is charger telemetry).
            same_charger = (
                (device.power_sensor and device.power_sensor in charger_entities)
                # (#748) an ED / manually-mapped row whose CONTROL entity is
                # the charger's own stop switch / current number is the same
                # physical charger — the exact "Billaddare" miss #700 left.
                or (device.control_entity and device.control_entity in charger_entities)
                or (device.energy_sensor and device.energy_sensor in charger_entities)
                or self._same_registry_device_as_charger(device.power_sensor)
                or self._same_registry_device_as_charger(device.energy_sensor)
            )
            if same_charger or (device.is_ev and chargers_configured):
                continue
            # (#615) SAME physical appliance already owned by a direct heat
            # pump / hot water registration (deduped on the shared entity, not
            # the id — the ED id ``energy_dashboard_<slug>`` differs from the
            # control id ``heat_pump``/``hot_water``). Drop the ED row; the
            # authoritative control-id row is emitted below.
            if direct_entities and (
                (device.energy_sensor and device.energy_sensor in direct_entities)
                or (device.power_sensor and device.power_sensor in direct_entities)
                or (device.control_entity and device.control_entity in direct_entities)
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
                # the service accepts energy_entity_id (#600) — emit it
                # instead of a hardcoded None, else registering a device that
                # HAD an auto-discovered energy counter silently drops it from
                # the row (caught live on PROD: an ED device re-registered by
                # service lost sensor.<shelly>_energy).
                "energy_sensor": spec.get("energy_entity_id"),
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

        # (#602/#576) heat-pump / hot-water controllers are ALREADY surfaced as
        # first-class draggable rows by the direct-registration loop above
        # (``_surplus_device_row``), keyed by their control id with a
        # ``priority_for`` drag position — so their surplus priority is the list
        # slot, not a standalone ``heat_pump_priority`` / ``hot_water_priority``
        # knob. No separate emit path needed (a parallel one was dead code).

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
        # (#602/#576) the heat-pump / hot-water controllers register as a
        # generic ``setpoint`` device_type — override to their control id so the
        # priority card renders the right glyph (mdi:heat-pump / mdi:water-boiler)
        # instead of the generic plug. They're the same ONE-list draggable row.
        if did in ("heat_pump", "hot_water"):
            dtype = did
        mode = getattr(getattr(dev, "control_mode", None), "value", None) or "surplus"
        return {
            "name": getattr(dev, "name", did),
            "priority": self.priority_for(
                did, seed=int(getattr(dev, "priority", 5) or 5)),
            "is_controllable": True,
            "is_critical": False,
            "power_rating": round(float(getattr(dev, "rated_power", 0) or 0)),
            "power_entity": getattr(dev, "power_entity_id", None),
            # (#600) surface the companion energy counter if the controller has
            # one, so the card can show derived power for a power-sensor-less HP.
            "energy_sensor": getattr(dev, "energy_entity_id", None),
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
            # (#620) goals + progress so directly-registered surplus devices
            # (heat pump / hot water / climate) expose the min/max/battery
            # controls on the card, same as the load rows.
            **self._goal_payload(did),
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

    # (#748) Every row key a configured charger may carry that names a HA
    # entity BELONGING to the physical charger — not just its power sensor.
    # A charger is identified by ANY of these; an ED row or a discovered
    # switch that names one of them is the same physical charger and must
    # fold. #700's fold looked only at ``power_entity`` and so missed
    # "Billaddare", whose control entity is the charger's start/stop switch.
    _CHARGER_ENTITY_KEYS = (
        "power_entity",
        "control_entity",
        "current_entity",
        "current_sensor_entity",
        "status_entity",
        "start_stop_entity",
        "charge_mode_entity",
        "service_entity",
    )

    def _configured_charger_entities(self) -> set:
        """(#576/#700/#748) EVERY HA entity a configured charger declares —
        power sensor, start/stop switch, current-limit number, status sensor,
        charge-mode select and control/service entities. A charger is
        identified by ANY of these, not only its power sensor: an ED row or a
        discovered switch naming the charger's *stop* control is the same
        physical charger and must fold, exactly as one naming its power sensor
        does. Used both to suppress the ED duplicate row (card) and, at the
        data layer, to keep the charger's own entities out of load discovery.

        Only populated for the keys the coordinator plumbs into the charger
        rows (``_charger_priority_rows``, #748) — a legacy row that carries
        only ``power_entity`` degrades to the old power-only behaviour, never
        an error."""
        entities: set = set()
        for c in self._ev_charger_rows:
            for key in self._CHARGER_ENTITY_KEYS:
                ent = c.get(key)
                if ent:
                    entities.add(ent)
        return entities

    def _same_registry_device_as_charger(self, entity_id) -> bool:
        """(#700) Does ``entity_id`` live on the same HA registry device as a
        configured charger's power entity? The identity test behind the ED
        duplicate-row suppression — an ED row pointing at the charger's own
        energy counter shares its device even when no entity string matches
        and the English name-pattern ``is_ev`` guess fails ("Billaddare").
        Defensive throughout: an unanswerable registry reads as "no match",
        never as a crash in the discovery path.
        """
        if not entity_id or not self._ev_charger_rows:
            return False
        try:
            from homeassistant.helpers import entity_registry as er
            reg = er.async_get(self.hass)
            ent = reg.async_get(entity_id)
            did = getattr(ent, "device_id", None)
            if not isinstance(did, str):
                return False
            for c in self._ev_charger_rows:
                pe = c.get("power_entity")
                if not pe:
                    continue
                pent = reg.async_get(pe)
                if getattr(pent, "device_id", None) == did:
                    return True
        except Exception:
            return False
        return False

    def _direct_registration_entities(self) -> set:
        """(#615) Entities OWNED by a directly-registered surplus device
        (heat pump / hot water / climate — registered straight into the
        controller, not via the ED list). These are authoritative rows,
        emitted below by their control id. An ED ``individual device`` that
        the user *also* added to HA's Energy Dashboard for the SAME physical
        appliance (its power/energy counter) would otherwise appear a SECOND
        time — because the ED row's id (``energy_dashboard_<slug>``) differs
        from the control id (``heat_pump``/``hot_water``), so the id-keyed
        dedup can't see it (issue #615: heat pump "twice in overview").

        Same class as the #559 service-registration and #576 charger
        suppressions: dedup on the SHARED ENTITY, not the id. Returns the set
        of power/energy/switch entities the direct registrations claim; an ED
        row referencing any of them is suppressed in favour of the
        authoritative control-id row.
        """
        reserved: set = set()
        for did, dev in getattr(
            self._surplus_controller, "_devices", {}
        ).items():
            # ED-synced rows live here too (id ``energy_dashboard_*``) — they
            # ARE the ED devices, so skip them. EV chargers have their own
            # suppression path. Only the direct (heat_pump/hot_water/climate)
            # registrations reserve entities here.
            if did.startswith("energy_dashboard_") or getattr(dev, "is_ev", False):
                continue
            if did in self._service_registrations:
                continue
            for attr in ("power_entity_id", "energy_entity_id", "entity_id"):
                ent = getattr(dev, attr, None)
                if ent:
                    reserved.add(ent)
        return reserved

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
            runtime_min = getattr(live, "_daily_runtime_accumulated_sec", 0) / 60
            targets_met = bool(getattr(live, "daily_targets_met", False))
        return {
            "goals": {
                "daily_min_runtime_min": goals.get("daily_min_runtime_min", 0),
                "top_up_policy": goals.get("top_up_policy", "solar_only"),
                "stop_entity": goals.get("stop_entity", ""),
                "stop_at": goals.get("stop_at", 0),
                # (#620) the card reads these to pick the mode (solar_only vs
                # solar_battery), draw the Max handle and the overnight toggle.
                "daily_max_runtime_min": goals.get("daily_max_runtime_min", 0),
                "battery_assist_enabled": _goal_bool(goals.get("battery_assist_enabled")),
                "battery_eligible_overnight": _goal_bool(
                    goals.get("battery_eligible_overnight")
                ),
                # (#688) so the card shows the saved anti-cycle values after a
                # reload (None ⇒ the card shows the default placeholder).
                "min_on_time_min": goals.get("min_on_time_min"),
                "min_off_time_min": goals.get("min_off_time_min"),
                # (#705) the comfort band — pre-fill for the editor.
                "comfort_entity": goals.get("comfort_entity", ""),
                "comfort_target": goals.get("comfort_target", 0),
                "comfort_offset": goals.get("comfort_offset", 0),
                "comfort_limit": goals.get("comfort_limit", 0),
            },
            "progress": {
                "runtime_today_min": round(runtime_min, 1),
                "targets_met": targets_met,
            },
        } | self._comfort_payload(live)

    @staticmethod
    def _comfort_payload(live) -> Dict[str, Any]:
        """(#705) The live band verdict, published beside the goals.

        The card must never re-derive the band from the goals — a frontend
        copy of the band logic is how the published state and the action
        drift apart. Only devices that HAVE a band (ClimateDevice today,
        switch loads in Phase 2) carry the block; ``disengaged`` is
        reported rather than omitted, so a climate device with goals set
        and a dead thermometer does not look identical to one that was
        never configured.
        """
        if live is None or not hasattr(live, "comfort_state"):
            return {}
        try:
            return {"comfort": {
                "state": str(live.comfort_state),
                "reading_c": live._comfort_reading(),
                # so the chip says cooling vs heating without guessing —
                # from the band's own direction hook, not hvac_mode (a
                # switch heater has no hvac_mode).
                "hvac": live._comfort_direction(),
            }}
        except Exception:  # noqa: BLE001 — a payload must never break the sensor
            return {}

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

    async def _adopt_legacy_device_flags(self) -> None:
        """Seed the #650 override stores from LoadManagement — ONCE per session.

        Only non-default values are adopted (critical=True, controllable=False):
        those are the ones a user had to click for, and only the OLD code path
        could have put them in the LM dict without a matching override.

        One-shot by design. After the first sync the LM dict holds the
        REGISTRY's values, so a second pass would read our own output back — and
        would re-apply an opt-out the user had just cleared (re-enabling
        "controllable" removes the key, which this would helpfully restore).
        Deferred, not skipped, while the load manager is still empty.
        """
        if self._legacy_flags_adopted:
            return
        lm = self._load_manager
        if not lm or not getattr(lm, "_devices", None):
            return  # LM not up yet — try again on the next refresh
        self._legacy_flags_adopted = True
        crit = ctrl = 0
        for did, info in lm._devices.items():
            if not did.startswith("energy_dashboard_") or not isinstance(info, dict):
                continue
            if info.get("is_critical") is True and did not in self._critical_overrides:
                self._critical_overrides[did] = True
                crit += 1
            if info.get("is_controllable") is False and did not in self._controllable_overrides:
                self._controllable_overrides[did] = False
                ctrl += 1
        if crit or ctrl:
            await self._save_storage()
            _LOGGER.info(
                "Adopted %d critical / %d controllable flag(s) from LoadManagement (#650)",
                crit, ctrl,
            )

    async def async_set_device_flag(
        self, device_id: str, flag: str, value: bool
    ) -> None:
        """Persist a "critical" / "controllable" toggle from the priority card (#650).

        Pre-fix these two went straight into ``LoadManagement._devices`` and
        nowhere else, so ``_sync_to_load_manager`` — which REPLACES that entry
        wholesale — dropped them on the next rebuild (drag, the 35 s
        re-discovery, a config change, restart). Stored here alongside the
        priority / control-mode / dependency overrides so the rebuild re-applies
        them instead of wiping them.

        Args:
            device_id: e.g. ``energy_dashboard_pond_pump``
            flag: ``"critical"`` or ``"controllable"``
            value: the toggle's new state.
        """
        if flag == "critical":
            self._critical_overrides[device_id] = bool(value)
        elif flag == "controllable":
            if value:
                # Re-enabling means "go back to what the control config says" —
                # an override of True can't create controllability that isn't
                # there (see UnifiedDevice.controllable_override).
                self._controllable_overrides.pop(device_id, None)
            else:
                self._controllable_overrides[device_id] = False
        else:
            _LOGGER.warning("Unknown device flag %r for %s (#650)", flag, device_id)
            return

        await self._save_storage()
        await self.async_refresh_devices()
        _LOGGER.info("Updated %s %s = %s (persisted)", device_id, flag, bool(value))

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
            # (class-17 sibling, live PROD 2026-07-23) One-shot release on the
            # transition INTO Off: turn the load off once — regardless of who
            # started it or whether ownership survived a restart — then SEM
            # keeps its hands off. Without this, a running load was stranded
            # on forever ("mode off and SEM does not touch the device any
            # more"). The user's explicit mode change overrides the min_on
            # anti-flicker (a deliberate command beats flicker protection).
            if control_mode is DeviceControlMode.OFF:
                try:
                    obs = surplus_device.observed_on()
                except Exception:  # noqa: BLE001
                    obs = None
                if obs is True or (obs is None and surplus_device.is_active):
                    if getattr(surplus_device, "_status", None) is not None:
                        surplus_device._status.last_activated = None
                    await surplus_device.deactivate()
                    surplus_device._offpeak_forced = False
                    surplus_device._offpeak_forced_date = None
                    surplus_device._batt_overnight_forced = False
                    surplus_device._batt_overnight_forced_date = None
                    surplus_device._sem_owned = False
                    _LOGGER.info(
                        "Mode off: released %s (turned off once — SEM will "
                        "not touch it again while mode stays off)", device_id,
                    )

        # (#649) Keep the load manager's copy in step NOW. It is only rebuilt by
        # the 35 s rediscovery, so until then a device the user has just handed
        # to the surplus controller would still be a peak-shed candidate there —
        # two writers on the same switch, which is the bug this flag exists for.
        lm_info = (
            self._load_manager._devices.get(device_id)
            if self._load_manager is not None else None
        )
        if lm_info is not None:
            lm_info["control_mode"] = mode
            lm_info["surplus_managed"] = surplus_device is not None

        await self._save_storage()

    def sync_cycle_priorities(self, has_battery_reading, charger_rows):
        """(#625, extracted from the coordinator cycle) Per-cycle priority-list
        upkeep: latch the battery row once a real reading was seen (#576 — a
        transient SOC dropout must not flicker the row out), hand the
        configured chargers to the registry as first-class rows (#576 P2.1),
        and make the drag store authoritative for directly-registered devices
        (#602/#576). Returns the battery's list priority (or None).
        Never raises — a registry hiccup must not break the cycle."""
        try:
            if has_battery_reading:
                self._has_battery = True
            battery_priority = self.battery_surplus_priority()
            self.set_ev_chargers(charger_rows)
            self.refresh_direct_device_priorities()
            return battery_priority
        except Exception:  # pragma: no cover - never break the cycle
            return None

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

    def _effective_parents(self, node: str) -> list:
        """Every device ``node`` currently requires, across BOTH stores (#662).

        A "requires" edge can be written from two places that persist
        separately: the UI / ``set_device_property`` path lands in
        ``_dependency_overrides``, the ``register_surplus_device`` service
        lands in ``_service_registrations[id]["depends_on"]``. Walking only
        the first made the cycle guard blind to any loop whose other half
        came from a service registration — service sets a→b, UI sets b→a,
        the walk from ``a`` found no parents and the cycle was created.

        Both branches gate on ``isinstance`` before iterating: a hand-edited
        store can hold a bare string, and ``list("pump")`` would push the
        characters ``p, u, m, p`` onto the walk as if they were device ids.
        The result is de-duplicated — ``async_set_dependency`` deliberately
        mirrors an edge into both stores for service-registered devices, so
        the same parent legitimately appears twice.
        """
        parents: list = []
        for store in (
            self._dependency_overrides.get(node),
            (self._service_registrations.get(node) or {}).get("depends_on"),
        ):
            if isinstance(store, (list, tuple)):
                parents.extend(str(d) for d in store)
        seen: set = set()
        return [p for p in parents if not (p in seen or seen.add(p))]

    def _dependency_would_cycle(self, device_id: str, new_parent: str) -> bool:
        """Would making ``device_id`` require ``new_parent`` close a cycle?

        True iff ``device_id`` is already reachable UP the existing "requires"
        graph from ``new_parent`` (so the new edge would loop back). Walks ALL
        parents (a device can require several — the ``[0]``-only walk of the
        retired ``validate_dependencies`` missed every cycle that ran through
        a second dependency, #662) with a visited-set, so it's bounded even if
        the stored graph already contains a stray cycle."""
        if device_id == new_parent:
            return True
        stack = [new_parent]
        seen = set()
        while stack:
            node = stack.pop()
            if node == device_id:
                return True
            if node in seen:
                continue
            seen.add(node)
            stack.extend(self._effective_parents(node))
        return False

    def _sanitize_dependency_cycles(self) -> bool:
        """Break any cycle already present in restored storage (#662).

        The write-path guard rejects new cyclic edges, but it can only
        protect writes it sees: a store written before the guard existed
        (≤ v1.7.5-beta.2), or hand-edited, can hold a loop. Both devices in
        a cycle then wait on each other forever under the default
        ``dependency_mode='must_active'`` and never start.

        Cleans **both** stores in one pass. Doing only
        ``_dependency_overrides`` would leave two failure modes (ruflo
        review): a cycle written entirely through ``register_surplus_device``
        survives untouched and still deadlocks, and — worse — it then
        poisons the guard, because re-registering the *innocent* direction
        of that stale pair walks up through the surviving reverse edge and
        gets falsely rejected.

        Rebuilds edge by edge in deterministic order against a graph that
        starts empty, keeping only edges that don't close a loop, so an
        already-cyclic store can't make the walk itself wrong. Returns True
        if anything was dropped, so the caller can persist the repair —
        otherwise the warning would fire on every restart forever.

        **Tiebreak, when a cycle spans the two stores:** every edge is a
        candidate for dropping, and which one survives is decided purely by
        replay order — ``_dependency_overrides`` edges are replayed first, so
        the UI-set link wins and the service-registered one is dropped. That
        is the deliberate choice: the override store is what the user set by
        hand in the config card, while ``depends_on`` comes from an
        integration's ``register_surplus_device`` call, which will be replayed
        (and re-validated by the write-path guard) on its next registration.
        Within a single store the tiebreak is ``sorted()`` by device id.
        """
        orig_ovr = self._dependency_overrides
        orig_svc_deps = {
            did: reg.get("depends_on")
            for did, reg in (self._service_registrations or {}).items()
            if isinstance(reg, dict) and reg.get("depends_on")
        }
        cleaned_ovr: Dict[str, list] = {}
        cleaned_svc: Dict[str, list] = {}
        dropped: list = []

        def _edges(store, tag):
            for node in sorted(store):
                raw = store.get(node)
                if not isinstance(raw, (list, tuple)):
                    continue
                for parent in raw:
                    yield node, str(parent), tag

        try:
            # Swap in the empty graph so each candidate edge is validated
            # against only the edges already admitted. Safe without a lock:
            # this is sync, on HA's single-threaded event loop, with no
            # await between the swap and the restore below.
            self._dependency_overrides = cleaned_ovr
            for did in orig_svc_deps:
                self._service_registrations[did]["depends_on"] = []
            for node, parent, tag in [
                *_edges(orig_ovr, "ovr"),
                *_edges(orig_svc_deps, "svc"),
            ]:
                if self._dependency_would_cycle(node, parent):
                    dropped.append(f"{node}→{parent}")
                    continue
                target = cleaned_ovr if tag == "ovr" else cleaned_svc
                target.setdefault(node, []).append(parent)
                if tag == "svc":
                    self._service_registrations[node]["depends_on"] = list(
                        target[node]
                    )
        except Exception:  # pragma: no cover — never block startup
            self._dependency_overrides = orig_ovr
            for did, deps in orig_svc_deps.items():
                self._service_registrations[did]["depends_on"] = deps
            return False
        if dropped:
            _LOGGER.warning(
                "Dropped %d circular dependency link(s) found in stored "
                "device config: %s. Those devices would each have waited on "
                "the other and never started; re-add the link in the "
                "direction you meant.",
                len(dropped), ", ".join(dropped),
            )
        return bool(dropped)

    async def _save_storage(self) -> None:
        """Persist manual mappings, priority overrides, and control modes."""
        data = {
            "mappings": self._manual_mappings,
            "priority_overrides": self._priority_overrides,
            "control_modes": self._control_mode_overrides,
            "dependencies": self._dependency_overrides,
            "critical_overrides": self._critical_overrides,          # (#650)
            "controllable_overrides": self._controllable_overrides,  # (#650)
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
