"""Load management coordinator for SEM Solar Energy Management."""
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Any, Tuple

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from ..const import (
    DOMAIN,
    DEFAULT_TARGET_PEAK_LIMIT,
    DEFAULT_WARNING_PEAK_LEVEL,
    DEFAULT_EMERGENCY_PEAK_LEVEL,
    DEFAULT_PEAK_HYSTERESIS,
    DEFAULT_LOAD_MANAGEMENT_ENABLED,
    DEFAULT_CRITICAL_DEVICE_PROTECTION,
    DEFAULT_LOAD_SHEDDING_DELAY,
    DEFAULT_LOAD_RESTORE_DELAY,
    DEFAULT_MIN_ON_DURATION,
    DEFAULT_MIN_OFF_DURATION,
    DEFAULT_MIN_CHARGING_CURRENT,
    DEFAULT_MAX_CHARGING_CURRENT,
    DEFAULT_VOLTAGE_PER_PHASE,
    DEFAULT_POWER_FACTOR,
    LoadManagementState,
)
from .load_device_discovery import LoadDeviceDiscovery

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "load_management_devices"


class LoadManagementCoordinator:
    """Coordinate load management based on target peak limits."""

    def __init__(self, hass: HomeAssistant, config_entry):
        """Initialize load management coordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{STORAGE_KEY}")

        # Load management settings
        self._enabled = config_entry.options.get(
            "load_management_enabled", DEFAULT_LOAD_MANAGEMENT_ENABLED
        )
        self._target_peak_limit = config_entry.options.get(
            "target_peak_limit", DEFAULT_TARGET_PEAK_LIMIT
        )
        self._warning_level = config_entry.options.get(
            "warning_peak_level", DEFAULT_WARNING_PEAK_LEVEL
        )
        self._emergency_level = config_entry.options.get(
            "emergency_peak_level", DEFAULT_EMERGENCY_PEAK_LEVEL
        )
        self._hysteresis = config_entry.options.get(
            "peak_hysteresis", DEFAULT_PEAK_HYSTERESIS
        )

        # Device management
        self._device_discovery = LoadDeviceDiscovery(hass)
        self._devices: Dict[str, Dict] = {}
        self._devices_shed: List[str] = []

        # State tracking
        self._state = LoadManagementState.NORMAL
        self._last_shedding_time: Optional[datetime] = None
        self._last_restore_time: Optional[datetime] = None
        # EV current control removed — now handled by coordinator._execute_ev_control()

        # 15-minute rolling peak tracking
        self._peak_samples: List[Tuple[datetime, float]] = []  # (timestamp, grid_import_kw)
        self._consecutive_peak_15min: float = 0.0  # Current 15-min rolling average (kW)
        self._monthly_consecutive_peak: float = 0.0  # Highest 15-min peak this month (kW)
        self._monthly_peak_month: Optional[int] = None  # Track which month the peak belongs to

        # Callbacks for main coordinator
        self._update_callbacks = []

        # When True, skip _discover_devices() — UnifiedDeviceRegistry owns device list
        self._unified_registry_active = False

        # Observer mode: skip all hardware control
        self._observer_mode = config_entry.options.get("observer_mode", False)

    async def async_initialize(self):
        """Initialize the load management system."""
        try:
            # Load device configuration from storage
            await self._load_device_configuration()

            # Schedule discovery with retry if result is incomplete
            async def _discovery_with_retry():
                initial_delay = 30
                retry_delay = 15
                max_retries = 3
                previous_count = len(self._devices)

                await asyncio.sleep(initial_delay)
                _LOGGER.info("Running initial device discovery...")
                await self._discover_devices()

                # Retry if discovery found fewer devices than we had in storage
                for attempt in range(1, max_retries + 1):
                    current_count = len(self._devices)
                    if current_count >= previous_count:
                        break
                    _LOGGER.info(
                        "Discovery incomplete: found %d devices but expected at least %d, "
                        "retry %d/%d in %ds",
                        current_count, previous_count, attempt, max_retries, retry_delay,
                    )
                    await asyncio.sleep(retry_delay)
                    await self._discover_devices()

            # Start discovery in background
            asyncio.create_task(_discovery_with_retry())

            _LOGGER.info(
                f"Load management initialized: {len(self._devices)} devices loaded from storage, "
                f"target peak: {self._target_peak_limit}kW (device discovery will run in 30s)"
            )
        except Exception as e:
            _LOGGER.error(f"Failed to initialize load management: {e}")

    def is_enabled(self) -> bool:
        """Check if load management is enabled."""
        return self._enabled

    async def _load_device_configuration(self):
        """Load device configuration and peak data from storage."""
        try:
            data = await self._store.async_load()
            if data:
                if "devices" in data:
                    self._devices = data["devices"]
                    _LOGGER.debug(f"Loaded {len(self._devices)} devices from storage")

                # Restore monthly peak (only if same month)
                stored_month = data.get("monthly_peak_month")
                current_month = dt_util.now().month
                if stored_month == current_month:
                    self._monthly_consecutive_peak = data.get("monthly_consecutive_peak", 0.0)
                    self._monthly_peak_month = current_month
                    _LOGGER.info(
                        "Restored monthly peak: %.3f kW (month %d)",
                        self._monthly_consecutive_peak, current_month,
                    )
                else:
                    _LOGGER.info(
                        "Monthly peak reset: stored month %s != current %d",
                        stored_month, current_month,
                    )
        except Exception as e:
            _LOGGER.warning(f"Could not load device configuration: {e}")
            self._devices = {}

    async def _save_device_configuration(self):
        """Save device configuration and peak data to storage."""
        try:
            data = {
                "devices": self._devices,
                "last_updated": dt_util.now().isoformat(),
                "monthly_consecutive_peak": self._monthly_consecutive_peak,
                "monthly_peak_month": self._monthly_peak_month,
            }
            await self._store.async_save(data)
            _LOGGER.debug("Saved device configuration to storage")
        except Exception as e:
            _LOGGER.error(f"Failed to save device configuration: {e}")

    async def _discover_devices(self):
        """Discover new controllable devices.

        Discovery priority:
        1. Energy Dashboard individual devices (primary source)
        2. Pattern-based discovery (fallback for devices not in Energy Dashboard)
        """
        if self._unified_registry_active:
            _LOGGER.debug("Skipping device discovery — UnifiedDeviceRegistry is active")
            return

        try:
            _LOGGER.info("Starting device discovery process...")

            # First, discover from Energy Dashboard individual devices
            energy_dashboard_devices = await self._device_discovery.discover_from_energy_dashboard()
            _LOGGER.info(f"Energy Dashboard discovery: found {len(energy_dashboard_devices)} devices")

            # Then, pattern-based discovery for additional devices
            pattern_discovered = self._device_discovery.discover_controllable_devices()
            _LOGGER.info(f"Pattern-based discovery: found {len(pattern_discovered)} devices")

            # Merge discoveries - Energy Dashboard takes priority
            all_discovered = {}
            all_discovered.update(pattern_discovered)
            all_discovered.update(energy_dashboard_devices)  # Override with Energy Dashboard

            _LOGGER.info(f"Total discovered: {len(all_discovered)} unique devices")

            # Add new devices while preserving existing configuration
            for device_id, device_info in all_discovered.items():
                if device_id not in self._devices:
                    self._devices[device_id] = device_info
                    switch_info = device_info.get('switch_entity', 'no switch')
                    power_info = device_info.get('power_entity', 'no power sensor')
                    source = device_info.get('source', 'pattern')
                    _LOGGER.info(f"Added new device: {device_id} ({switch_info} + {power_info}) [source: {source}]")
                else:
                    # Update availability and power rating, preserve user settings
                    # NOTE: is_controllable, is_critical, and priority are user-editable —
                    # never overwrite them from discovery when the user has set them.
                    existing = self._devices[device_id]
                    update = {
                        "is_available": device_info.get("is_available", True),
                        "power_rating": device_info.get("power_rating", 0.0),
                        "power_entity": device_info.get("power_entity"),
                        "energy_entity": device_info.get("energy_entity"),
                        "switch_entity": device_info.get("switch_entity") or existing.get("switch_entity"),
                        "source": device_info.get("source", "pattern"),
                    }
                    # Only set priority from discovery if the user hasn't customized it
                    if not existing.get("user_set_priority", False):
                        discovered_priority = device_info.get("priority")
                        if discovered_priority is not None:
                            update["priority"] = discovered_priority
                    existing.update(update)
                    _LOGGER.debug(f"Updated existing device: {device_id}")

            # Save updated configuration
            await self._save_device_configuration()
            _LOGGER.info(f"Device discovery complete: {len(self._devices)} total devices in system")

            # Trigger callbacks to update coordinator and sensors
            self._trigger_callbacks()
            _LOGGER.info("Triggered coordinator update after device discovery")

        except Exception as e:
            _LOGGER.error(f"Device discovery failed: {e}", exc_info=True)

    async def register_ev_charger(
        self,
        current_control_entity: str = None,
        power_entity: str = None,
        priority: int = 3,
        is_critical: bool = False,
        charger_service: str = None
    ):
        """Register EV charger as a load management device.

        EV charger is special because it uses current control (number entity or service)
        instead of on/off (switch entity). When load shedding is needed,
        it sets current to 0A instead of turning off a switch.

        Args:
            current_control_entity: Number entity for charging current (e.g., number.keba_charging_current)
            power_entity: Sensor for charging power (e.g., sensor.keba_charging_power)
            priority: Priority level (1-10, higher = shed first). Default 3 = low priority
            is_critical: If True, never shed this device
            charger_service: Service for current control (e.g., "keba.set_current") - alternative to number entity
        """
        try:
            device_id = "load_device_ev_charger"

            # Need at least one control method
            if not current_control_entity and not charger_service:
                _LOGGER.error("EV charger registration requires either current_control_entity or charger_service")
                return False

            # Check if number entity exists (if specified)
            if current_control_entity and not self.hass.states.get(current_control_entity):
                _LOGGER.warning(f"EV charger current control entity not found: {current_control_entity}")
                current_control_entity = None  # Fall back to service

            # Check power entity
            if power_entity and not self.hass.states.get(power_entity):
                _LOGGER.warning(f"EV charger power entity not found: {power_entity}")

            # Get friendly name
            friendly_name = "EV Charger"
            if current_control_entity:
                current_state = self.hass.states.get(current_control_entity)
                if current_state:
                    friendly_name = current_state.attributes.get("friendly_name", "EV Charger")

            # EV charger can draw up to 22kW (32A × 3 phases × 230V)
            max_power = 22.0  # kW

            # Register as load management device
            self._devices[device_id] = {
                "switch_entity": current_control_entity,  # Number entity (may be None)
                "charger_service": charger_service,  # Service-based control (e.g., "keba.set_current")
                "power_entity": power_entity,
                "device_type": "ev_charger",
                "description": "EV Charger (Current Control)",
                "friendly_name": friendly_name,
                "power_rating": max_power,
                "is_available": True,
                "priority": priority,
                "is_critical": is_critical,
                "is_controllable": True,
                "control_type": "current",  # Special flag: use current control instead of switch
            }

            # Save configuration
            await self._save_device_configuration()

            control_method = current_control_entity if current_control_entity else charger_service
            _LOGGER.info(
                f"Registered EV charger for load management: {device_id} "
                f"(control: {control_method}, power: {power_entity}, "
                f"priority: {priority}, max: {max_power}kW)"
            )

            # Trigger callbacks to update sensors
            self._trigger_callbacks()

            return True

        except Exception as e:
            _LOGGER.error(f"Failed to register EV charger: {e}", exc_info=True)
            return False

    def add_update_callback(self, callback):
        """Add callback for updates."""
        self._update_callbacks.append(callback)

    def remove_update_callback(self, callback):
        """Remove update callback."""
        if callback in self._update_callbacks:
            self._update_callbacks.remove(callback)

    @callback
    def _trigger_callbacks(self):
        """Trigger all update callbacks."""
        for callback in self._update_callbacks:
            try:
                callback()
            except Exception as e:
                _LOGGER.error(f"Error in load management callback: {e}")

    async def update_target_peak_limit(self, new_limit: float):
        """Update the target peak limit."""
        self._target_peak_limit = new_limit
        _LOGGER.info(f"Updated target peak limit to {new_limit}kW")
        self._trigger_callbacks()

    async def update_device_priority(self, device_id: str, priority: int):
        """Update device priority."""
        if device_id in self._devices:
            self._devices[device_id]["priority"] = priority
            self._devices[device_id]["user_set_priority"] = True
            await self._save_device_configuration()
            _LOGGER.debug(f"Updated {device_id} priority to {priority} (user-set)")

    async def update_device_critical_status(self, device_id: str, is_critical: bool):
        """Update device critical status."""
        if device_id in self._devices:
            self._devices[device_id]["is_critical"] = is_critical
            await self._save_device_configuration()
            _LOGGER.debug(f"Updated {device_id} critical status to {is_critical}")

    async def update_device_controllable_status(self, device_id: str, is_controllable: bool):
        """Update device controllable status."""
        if device_id in self._devices:
            self._devices[device_id]["is_controllable"] = is_controllable
            await self._save_device_configuration()
            _LOGGER.debug(f"Updated {device_id} controllable status to {is_controllable}")

    def _update_peak_tracking(self, grid_import_w: float) -> bool:
        """Update 15-minute rolling average peak and monthly maximum.

        Called every coordinator cycle (~10s). Maintains a sliding window
        of grid import samples over the last 15 minutes, computes the
        rolling average, and updates the monthly peak if exceeded.

        Args:
            grid_import_w: Current grid import in Watts.

        Returns:
            True if monthly peak was updated (caller should persist).
        """
        now = dt_util.now()
        grid_import_kw = grid_import_w / 1000.0

        # Add current sample
        self._peak_samples.append((now, grid_import_kw))

        # Remove samples older than 15 minutes
        cutoff = now - timedelta(minutes=15)
        self._peak_samples = [(t, v) for t, v in self._peak_samples if t >= cutoff]

        # Calculate 15-min rolling average
        if self._peak_samples:
            self._consecutive_peak_15min = round(
                sum(v for _, v in self._peak_samples) / len(self._peak_samples), 3
            )
        else:
            self._consecutive_peak_15min = 0.0

        # Monthly peak reset on month change
        current_month = now.month
        if self._monthly_peak_month is not None and current_month != self._monthly_peak_month:
            _LOGGER.info(
                "Monthly peak reset: previous month peak was %.3f kW",
                self._monthly_consecutive_peak,
            )
            self._monthly_consecutive_peak = 0.0
        self._monthly_peak_month = current_month

        # Update monthly peak if current 15-min average exceeds it
        peak_changed = False
        if self._consecutive_peak_15min > self._monthly_consecutive_peak:
            self._monthly_consecutive_peak = self._consecutive_peak_15min
            peak_changed = True

        return peak_changed

    async def process_peak_update(
        self,
        current_peak: float,
        consecutive_peak: float,
        ev_is_charging: bool = False,
        grid_import_w: float = 0,
        ev_power_w: float = 0
    ):
        """Process peak power update and manage loads accordingly.

        Args:
            current_peak: Current 15-minute rolling average peak (kW)
            consecutive_peak: Monthly peak for tracking/billing (kW)
            ev_is_charging: Whether EV should be actively charging (night charging active)
            grid_import_w: Current grid import in Watts (positive = importing)
            ev_power_w: Current EV charging power in Watts
        """
        if not self._enabled:
            return

        # Update rolling peak tracking from actual grid import
        peak_changed = self._update_peak_tracking(grid_import_w)
        if peak_changed:
            await self._save_device_configuration()

        try:
            # Clean up shed list: remove devices that powered off naturally
            self._cleanup_shed_list()

            # Determine current state based on peak levels
            new_state = self._determine_load_management_state(current_peak, consecutive_peak)

            # Handle state changes
            if new_state != self._state:
                await self._handle_state_change(self._state, new_state, current_peak)
                self._state = new_state

            # Execute load management based on current state
            await self._execute_load_management(current_peak, consecutive_peak)

            # EV charging current is now managed by coordinator._execute_ev_control()
            # via CurrentControlDevice — no duplicate control here.

            self._trigger_callbacks()

        except Exception as e:
            _LOGGER.error(f"Error in load management processing: {e}")
            self._state = LoadManagementState.ERROR

    # NOTE: update_ev_charging_current() has been removed.
    # EV charging current is now managed by the coordinator's _execute_ev_control()
    # method via CurrentControlDevice, providing a single-writer architecture.
    # The reactive headroom algorithm is embedded in _execute_ev_control().

    def get_state(self) -> str:
        """Get current load management state."""
        return self._state

    def _cleanup_shed_list(self):
        """Remove devices from the shed list if they are already off naturally.

        Devices may power off on their own (e.g., a cycle completes, user turns
        them off manually). Keeping them in _devices_shed blocks state
        transitions and prevents correct accounting.
        """
        if not self._devices_shed:
            return

        stale = []
        for device_id in self._devices_shed:
            device_info = self._devices.get(device_id)
            if device_info is None:
                # Device was removed from the device list entirely
                stale.append(device_id)
                continue

            device_state = self._device_discovery.get_device_current_state(device_info)
            if not device_state["is_on"] and device_state["current_power"] <= 0:
                stale.append(device_id)

        for device_id in stale:
            self._devices_shed.remove(device_id)
            _LOGGER.debug(
                "Cleaned %s from shed list (device is off / removed)", device_id
            )

    def _determine_load_management_state(self, current_peak: float, consecutive_peak: float) -> str:
        """Determine the appropriate load management state.

        Args:
            current_peak: Current 15-minute rolling average peak (kW)
            consecutive_peak: Monthly peak for tracking/billing (kW) - not used for decisions

        Note: We only react to current_peak to PREVENT it from becoming a new monthly peak.
        The consecutive_peak (monthly) is tracked separately for billing purposes only.

        State transitions:
        - NORMAL → WARNING: peak >= warning_level (4.5kW)
        - WARNING → SHEDDING: peak >= target_limit (5.0kW)
        - SHEDDING → EMERGENCY: peak >= emergency_level (6.0kW)
        - EMERGENCY → SHEDDING: peak < emergency_level
        - SHEDDING → NORMAL: peak <= (target_limit - hysteresis) OR peak < warning_level
        - WARNING → NORMAL: peak < warning_level

        Hysteresis applies at SHEDDING→NORMAL transition to prevent rapid cycling.
        If peak drops well below warning level, immediately restore to NORMAL.
        """
        peak_to_check = current_peak
        restore_threshold = self._target_peak_limit - self._hysteresis

        # Emergency state - immediate action required
        if peak_to_check >= self._emergency_level:
            return LoadManagementState.EMERGENCY

        # At or above target - must shed loads
        elif peak_to_check >= self._target_peak_limit:
            return LoadManagementState.SHEDDING

        # In warning zone (between warning and target)
        elif peak_to_check >= self._warning_level:
            # If we have devices shed and peak is still in warning zone,
            # stay in SHEDDING to allow controlled restoration
            if self._devices_shed:
                return LoadManagementState.SHEDDING
            return LoadManagementState.WARNING

        # Below warning level
        else:
            # If peak is below warning level, always return to NORMAL
            # even if devices are still shed (they will be restored gradually)
            # This prevents the deadlock where devices stay shed indefinitely
            if peak_to_check <= restore_threshold:
                # Well below threshold - definitely NORMAL
                return LoadManagementState.NORMAL
            elif self._devices_shed:
                # Between restore_threshold and warning_level with devices shed
                # Allow restoration to proceed (return NORMAL to enable restore logic)
                return LoadManagementState.NORMAL
            else:
                return LoadManagementState.NORMAL

    async def _handle_state_change(self, old_state: str, new_state: str, current_peak: float):
        """Handle load management state changes."""
        _LOGGER.info(
            f"Load management state change: {old_state} → {new_state} "
            f"(peak: {current_peak:.2f}kW, target: {self._target_peak_limit}kW)"
        )

        if new_state == LoadManagementState.EMERGENCY:
            _LOGGER.warning(
                f"EMERGENCY load shedding triggered! Peak {current_peak:.2f}kW "
                f"exceeds emergency level {self._emergency_level}kW"
            )

    async def _execute_load_management(self, current_peak: float, consecutive_peak: float):
        """Execute load management actions based on current state.

        Priority: battery discharge first (instant, no disruption),
        then device shedding only if battery insufficient.
        """
        if self._state in (LoadManagementState.SHEDDING, LoadManagementState.EMERGENCY):
            # Try battery discharge first before shedding devices
            await self._battery_peak_shaving(current_peak)

        if self._state == LoadManagementState.EMERGENCY:
            await self._emergency_load_shedding()
        elif self._state == LoadManagementState.SHEDDING:
            await self._progressive_load_shedding(current_peak, consecutive_peak)
        elif self._state == LoadManagementState.NORMAL:
            await self._restore_loads()
            await self._restore_battery_peak_shaving()

    async def _battery_peak_shaving(self, current_peak: float):
        """Discharge battery to reduce grid peak before shedding devices.

        Sets battery discharge power = overshoot above target peak.
        Battery responds instantly (no disruption to user).
        """
        config_entry = getattr(self, '_config_entry', None)
        if not config_entry:
            return
        battery_discharge_entity = config_entry.options.get(
            "battery_discharge_control_entity", ""
        )
        if not battery_discharge_entity:
            return

        overshoot_w = (current_peak - self._target_peak_limit) * 1000
        if overshoot_w <= 0:
            return

        max_discharge = config_entry.options.get("battery_max_discharge_power", 5000)
        discharge_power = min(overshoot_w, max_discharge)

        try:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": battery_discharge_entity, "value": discharge_power},
                blocking=True,
            )
            _LOGGER.info("Battery peak shaving: %.0fW discharge (overshoot %.0fW)",
                         discharge_power, overshoot_w)
        except Exception as e:
            _LOGGER.debug("Battery peak shaving failed: %s", e)

    async def _restore_battery_peak_shaving(self):
        """Restore battery to normal operation when peak is normal."""
        config_entry = getattr(self, '_config_entry', None)
        if not config_entry:
            return
        battery_discharge_entity = config_entry.options.get(
            "battery_discharge_control_entity", ""
        )
        if not battery_discharge_entity:
            return

        max_discharge = config_entry.options.get("battery_max_discharge_power", 5000)
        try:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": battery_discharge_entity, "value": max_discharge},
                blocking=True,
            )
        except Exception:
            pass

    async def _emergency_load_shedding(self):
        """Emergency load shedding - turn off all non-critical loads immediately."""
        devices_to_shed = [
            device_id for device_id, device_info in self._devices.items()
            if (device_info.get("is_controllable", True) and
                not device_info.get("is_critical", False) and
                device_id not in self._devices_shed and
                self._is_device_currently_on(device_info))
        ]

        for device_id in devices_to_shed:
            await self._shed_device(device_id, "EMERGENCY")

    async def _progressive_load_shedding(self, current_peak: float, consecutive_peak: float):
        """Progressive load shedding based on priority and power reduction needed."""
        # Calculate how much power we need to reduce based on current peak only
        power_reduction_needed = current_peak - self._target_peak_limit + self._hysteresis

        if power_reduction_needed <= 0:
            return

        # Get available devices for shedding (sorted by priority, highest first)
        available_devices = self._get_devices_for_shedding()

        power_reduced = 0.0
        for device_id, device_info in available_devices:
            if power_reduced >= power_reduction_needed:
                break

            device_state = self._device_discovery.get_device_current_state(device_info)
            if device_state["is_on"] and device_state["current_power"] > 0:
                await self._shed_device(device_id, "PROGRESSIVE")
                power_reduced += device_state["current_power"] / 1000  # Convert to kW

        _LOGGER.debug(
            f"Progressive shedding: needed {power_reduction_needed:.2f}kW, "
            f"achieved {power_reduced:.2f}kW"
        )

    async def _restore_loads(self):
        """Restore loads that were shed."""
        if not self._devices_shed:
            return

        # Check if enough time has passed since last restore
        if (self._last_restore_time and
            dt_util.now() - self._last_restore_time < timedelta(seconds=DEFAULT_LOAD_RESTORE_DELAY)):
            return

        # Restore devices in reverse priority order (low priority restored first)
        devices_to_restore = sorted(
            self._devices_shed,
            key=lambda device_id: self._devices[device_id].get("priority", 5),
            reverse=True
        )

        for device_id in devices_to_restore:
            await self._restore_device(device_id)
            # Restore one device at a time to avoid sudden peak
            break

    def _can_shed_device(self, device_id: str, device_info: Dict) -> bool:
        """Check if device can be turned off (anti-flicker check)."""
        if not self._is_device_currently_on(device_info):
            return False

        # Check minimum on duration
        last_turned_on = device_info.get("last_turned_on")
        if last_turned_on:
            time_on = (dt_util.now() - last_turned_on).total_seconds()
            min_duration = device_info.get("min_on_duration", DEFAULT_MIN_ON_DURATION)
            if time_on < min_duration:
                _LOGGER.debug(
                    f"Device {device_id} cannot be shed yet "
                    f"(on for {time_on:.0f}s, min: {min_duration}s)"
                )
                return False

        return True

    def _can_restore_device(self, device_id: str, device_info: Dict) -> bool:
        """Check if device can be turned on (anti-flicker check)."""
        if self._is_device_currently_on(device_info):
            return False

        # Check minimum off duration
        last_turned_off = device_info.get("last_turned_off")
        if last_turned_off:
            time_off = (dt_util.now() - last_turned_off).total_seconds()
            min_duration = device_info.get("min_off_duration", DEFAULT_MIN_OFF_DURATION)
            if time_off < min_duration:
                _LOGGER.debug(
                    f"Device {device_id} cannot be restored yet "
                    f"(off for {time_off:.0f}s, min: {min_duration}s)"
                )
                return False

        return True

    def _get_devices_for_shedding(self) -> List[Tuple[str, Dict]]:
        """Get available devices for shedding, sorted by priority."""
        available_devices = []

        for device_id, device_info in self._devices.items():
            if (device_info.get("is_controllable", True) and
                not device_info.get("is_critical", False) and
                device_id not in self._devices_shed and
                device_info.get("is_available", False) and
                self._can_shed_device(device_id, device_info)):
                available_devices.append((device_id, device_info))

        # Sort by priority (highest priority number = first to shed)
        available_devices.sort(
            key=lambda x: x[1].get("priority", 5),
            reverse=True
        )

        return available_devices

    def _is_device_currently_on(self, device_info: Dict) -> bool:
        """Check if device is currently turned on."""
        device_state = self._device_discovery.get_device_current_state(device_info)
        return device_state["is_on"]

    async def _shed_device(self, device_id: str, reason: str):
        """Turn off a device for load shedding.

        Uses the 'control' config from device discovery to determine how to shed:
        - switch: Turn off the switch entity
        - current: Set number entity to 0A (EV chargers)
        - service: Call service with shed_value (e.g., keba.set_current)
        - input_boolean: Turn off the input_boolean
        """
        if self._observer_mode:
            _LOGGER.debug("Observer mode: skipping shed of %s", device_id)
            return

        if device_id not in self._devices:
            return

        device_info = self._devices[device_id]

        # Check anti-flicker constraint
        if not self._can_shed_device(device_id, device_info):
            _LOGGER.debug(f"Cannot shed {device_id}: anti-flicker protection active")
            return

        # Check if enough time has passed since last shedding
        if (self._last_shedding_time and
            dt_util.now() - self._last_shedding_time < timedelta(seconds=DEFAULT_LOAD_SHEDDING_DELAY)):
            _LOGGER.debug(f"Cannot shed {device_id}: shedding delay active")
            return

        # RACE CONDITION FIX: Update shedding time BEFORE executing action
        # This prevents multiple concurrent calls from passing the time check
        self._last_shedding_time = dt_util.now()

        # Get control config (new style) or fall back to legacy style
        control = device_info.get("control")
        success = False

        try:
            if control:
                # New unified control config from discover_control_for_energy_device()
                control_type = control.get("type")

                if control_type == "switch":
                    entity = control.get("entity")
                    if entity:
                        # Record pre-shed state so restore only turns on if it was on
                        switch_state = self.hass.states.get(entity)
                        was_on = switch_state is not None and switch_state.state.lower() in ("on", "true", "1")
                        self._devices[device_id]["_pre_shed_was_on"] = was_on

                        await self.hass.services.async_call(
                            "switch", "turn_off",
                            {"entity_id": entity},
                            blocking=True
                        )
                        success = True
                        _LOGGER.debug(f"Shed device via switch {entity} (was_on={was_on})")

                elif control_type == "current":
                    entity = control.get("entity")
                    if entity:
                        # Store current value for restore
                        current_state = self.hass.states.get(entity)
                        if current_state:
                            try:
                                self._devices[device_id]["_pre_shed_current"] = float(current_state.state)
                            except (ValueError, TypeError):
                                self._devices[device_id]["_pre_shed_current"] = control.get("original_value", 16)

                        await self.hass.services.async_call(
                            "number", "set_value",
                            {"entity_id": entity, "value": 0},
                            blocking=True
                        )
                        success = True
                        _LOGGER.debug(f"Shed device via current control {entity} (set to 0A)")

                elif control_type == "service":
                    service = control.get("service")
                    param = control.get("param", "current")
                    shed_value = control.get("shed_value", 0)

                    if service:
                        parts = service.split(".", 1)
                        if len(parts) == 2:
                            domain, svc = parts
                            await self.hass.services.async_call(
                                domain, svc,
                                {param: shed_value},
                                blocking=True
                            )
                            success = True
                            _LOGGER.debug(f"Shed device via service {service}")

                elif control_type == "input_boolean":
                    entity = control.get("entity")
                    if entity:
                        # Record pre-shed state so restore only turns on if it was on
                        bool_state = self.hass.states.get(entity)
                        was_on = bool_state is not None and bool_state.state.lower() in ("on", "true", "1")
                        self._devices[device_id]["_pre_shed_was_on"] = was_on

                        await self.hass.services.async_call(
                            "input_boolean", "turn_off",
                            {"entity_id": entity},
                            blocking=True
                        )
                        success = True
                        _LOGGER.debug(f"Shed device via input_boolean {entity} (was_on={was_on})")

            else:
                # Legacy fallback: use switch_entity directly or control_type
                if device_info.get("control_type") == "current":
                    current_entity = device_info.get("switch_entity")
                    charger_service = device_info.get("charger_service")

                    if current_entity and self.hass.states.get(current_entity):
                        await self.hass.services.async_call(
                            "number", "set_value",
                            {"entity_id": current_entity, "value": 0},
                            blocking=True
                        )
                        success = True
                    elif charger_service:
                        parts = charger_service.split(".", 1)
                        if len(parts) == 2:
                            domain, service = parts
                            await self.hass.services.async_call(
                                domain, service,
                                {"current": 0},
                                blocking=True
                            )
                            success = True
                else:
                    # Record pre-shed state for legacy switch devices
                    switch_entity = device_info.get("switch_entity")
                    if switch_entity:
                        switch_state = self.hass.states.get(switch_entity)
                        was_on = switch_state is not None and switch_state.state.lower() in ("on", "true", "1")
                        self._devices[device_id]["_pre_shed_was_on"] = was_on

                    success = await self._device_discovery.turn_off_device(device_info)

            if success:
                self._devices_shed.append(device_id)
                self._devices[device_id]["last_turned_off"] = dt_util.now()
                _LOGGER.info(
                    f"Shed device {device_info.get('friendly_name', device_id)} "
                    f"({reason} load shedding)"
                )

        except Exception as e:
            _LOGGER.error(f"Failed to shed device {device_id}: {e}")

    async def _restore_device(self, device_id: str):
        """Restore a device that was shed.

        Uses the 'control' config from device discovery to determine how to restore:
        - switch: Turn on the switch entity
        - current: Restore to pre-shed value or let automation handle
        - service: Call service with restore_value
        - input_boolean: Turn on the input_boolean
        """
        if self._observer_mode:
            _LOGGER.debug("Observer mode: skipping restore of %s", device_id)
            return

        if device_id not in self._devices or device_id not in self._devices_shed:
            return

        device_info = self._devices[device_id]

        # Check anti-flicker constraint
        if not self._can_restore_device(device_id, device_info):
            return

        # Get control config (new style) or fall back to legacy style
        control = device_info.get("control")
        success = False

        try:
            if control:
                # New unified control config
                control_type = control.get("type")

                if control_type == "switch":
                    entity = control.get("entity")
                    if entity:
                        # Check if device was on before shedding
                        # If unknown (e.g. after restart), check current state
                        was_on = device_info.get("_pre_shed_was_on")
                        if was_on is None:
                            current = self.hass.states.get(entity)
                            was_on = current is not None and current.state.lower() in ("on", "true", "1")
                        if not was_on:
                            # Device was OFF before shedding — don't turn it back on
                            success = True
                            _LOGGER.info("Skipping restore of %s — was off before shedding", entity)
                        else:
                            await self.hass.services.async_call(
                                "switch", "turn_on",
                                {"entity_id": entity},
                                blocking=True
                            )
                            success = True
                            _LOGGER.debug(f"Restored device via switch {entity}")

                elif control_type == "current":
                    # For current-control devices (EV chargers), we have options:
                    # 1. Restore to pre-shed value (if stored)
                    # 2. Let automation handle it (for EV chargers with peak-aware charging)
                    # For now, just mark as restored and let automation handle
                    success = True
                    _LOGGER.debug(
                        f"Restored current-control device {device_id} "
                        f"(automation will resume with appropriate current)"
                    )

                elif control_type == "service":
                    service = control.get("service")
                    param = control.get("param", "current")
                    restore_value = control.get("restore_value", 16)

                    if service:
                        parts = service.split(".", 1)
                        if len(parts) == 2:
                            domain, svc = parts
                            await self.hass.services.async_call(
                                domain, svc,
                                {param: restore_value},
                                blocking=True
                            )
                            success = True
                            _LOGGER.debug(f"Restored device via service {service}")

                elif control_type == "input_boolean":
                    entity = control.get("entity")
                    if entity:
                        was_on = device_info.get("_pre_shed_was_on")
                        if was_on is None:
                            current = self.hass.states.get(entity)
                            was_on = current is not None and current.state.lower() in ("on", "true", "1")
                        if not was_on:
                            success = True
                            _LOGGER.info("Skipping restore of %s — was off before shedding", entity)
                        else:
                            await self.hass.services.async_call(
                                "input_boolean", "turn_on",
                                {"entity_id": entity},
                                blocking=True
                            )
                            success = True
                            _LOGGER.debug(f"Restored device via input_boolean {entity}")

            else:
                # Legacy fallback
                if device_info.get("control_type") == "current":
                    # For EV charger, just mark as restored
                    success = True
                else:
                    was_on = device_info.get("_pre_shed_was_on")
                    if was_on is None:
                        # Unknown pre-shed state — check current device state
                        switch_entity = device_info.get("control", {}).get("entity") or device_info.get("entity_id")
                        if switch_entity:
                            current = self.hass.states.get(switch_entity)
                            was_on = current is not None and current.state.lower() in ("on", "true", "1")
                        else:
                            was_on = False
                    if not was_on:
                        success = True
                        _LOGGER.info(
                            "Skipping restore of %s — was off before shedding",
                            device_info.get("friendly_name", device_id)
                        )
                    else:
                        success = await self._device_discovery.turn_on_device(device_info)

            if success:
                self._devices_shed.remove(device_id)
                self._last_restore_time = dt_util.now()
                self._devices[device_id]["last_turned_on"] = dt_util.now()
                _LOGGER.info(f"Restored device {device_info.get('friendly_name', device_id)}")

        except Exception as e:
            _LOGGER.error(f"Failed to restore device {device_id}: {e}")

    def get_load_management_data(self) -> Dict[str, Any]:
        """Get current load management data for sensors."""
        total_devices = len(self._devices)
        controllable_devices = sum(
            1 for d in self._devices.values()
            if d.get("is_controllable", True) and d.get("is_available", False)
        )

        available_reduction = sum(
            self._device_discovery.get_device_current_state(device_info)["current_power"] / 1000
            for device_id, device_info in self._devices.items()
            if (device_info.get("is_controllable", True) and
                not device_info.get("is_critical", False) and
                device_id not in self._devices_shed and
                self._is_device_currently_on(device_info))
        )

        return {
            "state": self._state,
            "target_peak_limit": self._target_peak_limit,
            "warning_level": self._warning_level,
            "emergency_level": self._emergency_level,
            "total_devices": total_devices,
            "controllable_devices": controllable_devices,
            "devices_shed": len(self._devices_shed),
            "devices_shed_list": self._devices_shed.copy(),
            "available_load_reduction": round(available_reduction, 2),
            "enabled": self._enabled,
            "devices": self._devices.copy(),
            "consecutive_peak_15min": self._consecutive_peak_15min,
            "monthly_consecutive_peak": self._monthly_consecutive_peak,
        }

    def get_peak_margin(self, current_peak: float) -> float:
        """Get remaining margin before target peak is reached."""
        return max(0, self._target_peak_limit - current_peak)