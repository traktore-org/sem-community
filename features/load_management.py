"""Load management coordinator for SEM Solar Energy Management."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Mapping
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
    DEFAULT_PEAK_LIMIT_UNLIMITED,
    WARNING_PEAK_RATIO,
    EMERGENCY_PEAK_RATIO,
    DEFAULT_LOAD_MANAGEMENT_ENABLED,
    DEFAULT_LOAD_SHEDDING_DELAY,
    DEFAULT_LOAD_RESTORE_DELAY,
    DEFAULT_MIN_ON_DURATION,
    DEFAULT_MIN_OFF_DURATION,
    LoadManagementState,
)
from .device_axes import may_actuate
from .load_device_discovery import LoadDeviceDiscovery

_LOGGER = logging.getLogger(__name__)

STORAGE_VERSION = 1
STORAGE_KEY = "load_management_devices"


def repair_ladder(
    target: float, warning: float, emergency: float
) -> tuple[float, float]:
    """The ONE rule for putting an out-of-order peak ladder back in order.

    (#872) #813 established that *a writer must leave a state its own form
    accepts*, and fixed the target writer. The warning and emergency writers
    kept storing what the options page then refused to save, so the store and
    the decision path held two different ladders — which is how RienduPre met
    a warning about numbers he had never typed together.

    Same repair, one definition, called by ``_effective_levels`` and by every
    writer, so "what is stored" and "what is used" cannot drift again.

    The dangerous end is a LOW emergency: ``emergency <= target`` makes the
    EMERGENCY branch win before SHEDDING is ever considered, so SEM dumps
    loads the moment the target is touched. A HIGH warning is merely a lost
    stage, repaired for symmetry.

    Repair lands on the install-flow ratios (#717) rather than on the target
    itself — clamping *to* the target would leave ``emergency == target`` and
    the ``>=`` branch would still win, making SHEDDING unreachable.
    """
    if warning >= target:
        warning = round(target * WARNING_PEAK_RATIO, 1)
    if emergency <= target:
        emergency = round(target * EMERGENCY_PEAK_RATIO, 1)
    return warning, emergency


class LoadManagementCoordinator:
    """Coordinate load management based on target peak limits."""

    def __init__(self, hass: HomeAssistant, config_entry):
        """Initialize load management coordinator."""
        self.hass = hass
        self.config_entry = config_entry
        self._store = Store(hass, STORAGE_VERSION, f"{DOMAIN}_{STORAGE_KEY}")

        # Load management settings — read the MERGED entry view (#692), the
        # same one the coordinator gets (__init__.py builds
        # ``{**entry.data, **entry.options}``). The install flow writes
        # ``target_peak_limit`` to entry.data; only an options-flow re-save
        # copies it to options. Reading options alone therefore enforced the
        # 5.0 kW default on every install that never re-saved — the user's
        # configured limit was silently ignored (live on TEST: data 6.0,
        # options absent, shedding armed at 5.0). The Mapping guard: HA's
        # real surfaces are MappingProxy (not dict); a stub entry's may be
        # anything — a surface that isn't a mapping contributes nothing.
        _data = getattr(config_entry, "data", None)
        _opts = getattr(config_entry, "options", None)
        _cfg = {
            **(_data if isinstance(_data, Mapping) else {}),
            **(_opts if isinstance(_opts, Mapping) else {}),
        }
        self._enabled = _cfg.get(
            "load_management_enabled", DEFAULT_LOAD_MANAGEMENT_ENABLED
        )
        self._target_peak_limit = _cfg.get(
            "target_peak_limit", DEFAULT_TARGET_PEAK_LIMIT
        )
        self._warning_level = _cfg.get(
            "warning_peak_level", DEFAULT_WARNING_PEAK_LEVEL
        )
        self._emergency_level = _cfg.get(
            "emergency_peak_level", DEFAULT_EMERGENCY_PEAK_LEVEL
        )
        self._hysteresis = _cfg.get(
            "peak_hysteresis", DEFAULT_PEAK_HYSTERESIS
        )
        # (#716) Explicit "this install has no grid ceiling". Peak shedding
        # never escalates above NORMAL while this is set. Deliberately NOT
        # inferred from ``load_management_enabled`` or from a 0 limit: an
        # unlimited that can be reached by accident is how a 5 kW house got
        # handed a 10 kW EV slot (#638 finding #5). One boolean, one meaning.
        self._peak_unlimited = bool(
            _cfg.get("peak_limit_unlimited", DEFAULT_PEAK_LIMIT_UNLIMITED)
        )
        self._logged_ladder_repair = False

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

        # Observer mode: skip all hardware control (same merged view — the
        # switch writes options, so options still wins when present)
        self._observer_mode = _cfg.get("observer_mode", False)

        # #433 — telemetry surface mirroring classifier_path /
        # dampening_path / legionella_path. Focus on the high-leverage
        # decision points: state transitions, action dispatch, and the
        # try/except catch that masks all errors. Not every if/elif
        # — the module has 118 branches and exhaustive attribution
        # would dwarf the actual logic.
        self._last_state_decision_path: str = "uninitialized"
        self._last_process_path: str = "uninitialized"
        self._last_action_path: str = "uninitialized"
        self._last_error_message: Optional[str] = None

        # (#896) The shed plan reads the LIVE meter, never the 15-minute
        # average the state machine reads: a shed cannot move a rolling
        # average for minutes, and judging the next shed against it is how
        # one circuit after another went dark (forum #30). ``process_peak_
        # update`` stores the reading every cycle; the plan's verdict and
        # numbers are telemetry beside ``action_path``.
        self._last_grid_import_w: float = 0.0
        self._shed_path: str = "uninitialized"
        self._shed_need_w: float = 0.0
        self._shed_sheddable_w: float = 0.0
        self._shed_futile: bool = False
        self._uncontrolled_w: float = 0.0
        self._futile_repair_open: bool = False
        self._shed_notified: bool = False

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
            self.hass.async_create_task(_discovery_with_retry())

            _LOGGER.info(
                "Load management initialized: %s devices loaded from storage, "
                "target peak: %skW (device discovery will run in 30s)",
                len(self._devices), self._target_peak_limit,
            )
        except Exception as e:
            _LOGGER.error("Failed to initialize load management: %s", e)

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
                    _LOGGER.debug("Loaded %s devices from storage", len(self._devices))

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
            _LOGGER.warning("Could not load device configuration: %s", e)
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
            _LOGGER.error("Failed to save device configuration: %s", e)

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
            _LOGGER.info("Energy Dashboard discovery: found %s devices", len(energy_dashboard_devices))

            # Then, pattern-based discovery for additional devices.
            # (#748) Exclude every entity a configured charger already owns (its
            # stop switch, current number, power / status sensors) so the
            # ``switch.*`` smart-switch glob doesn't rediscover the charger's
            # own start/stop switch as a smart plug — the third duplicate row.
            excluded_entities = self._charger_claimed_entities()
            pattern_discovered = self._device_discovery.discover_controllable_devices(
                excluded_entities=excluded_entities
            )
            _LOGGER.info("Pattern-based discovery: found %s devices", len(pattern_discovered))

            # Merge discoveries - Energy Dashboard takes priority
            all_discovered = {}
            all_discovered.update(pattern_discovered)
            all_discovered.update(energy_dashboard_devices)  # Override with Energy Dashboard

            _LOGGER.info("Total discovered: %s unique devices", len(all_discovered))

            # Add new devices while preserving existing configuration
            for device_id, device_info in all_discovered.items():
                if device_id not in self._devices:
                    self._devices[device_id] = device_info
                    switch_info = device_info.get('switch_entity', 'no switch')
                    power_info = device_info.get('power_entity', 'no power sensor')
                    source = device_info.get('source', 'pattern')
                    _LOGGER.info("Added new device: %s (%s + %s) [source: %s]", device_id, switch_info, power_info, source)
                else:
                    # Update availability and power rating, preserve user settings
                    # NOTE: the user-editable axes (hands-off, critical,
                    # priority) are never overwritten from discovery. Capability
                    # (has_control_handle) IS discovery's to state — but it only
                    # arrives with a fresh row, so nothing to re-derive here.
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
                    _LOGGER.debug("Updated existing device: %s", device_id)

            # Save updated configuration
            await self._save_device_configuration()
            _LOGGER.info("Device discovery complete: %s total devices in system", len(self._devices))

            # Trigger callbacks to update coordinator and sensors
            self._trigger_callbacks()
            _LOGGER.info("Triggered coordinator update after device discovery")

        except Exception as e:
            _LOGGER.error("Device discovery failed: %s", e, exc_info=True)

    def _charger_claimed_entities(self) -> set:
        """(#748) Every entity owned by a registered EV charger — its current
        control / power sensor, its start/stop switch and its status sensor.
        Pattern discovery excludes these so a charger's own stop switch is not
        rediscovered as a smart plug. Reads the charger rows registered by
        ``register_ev_charger`` (device_type ``ev_charger``); an install with
        no charger yields an empty set (no exclusion). Never raises."""
        claimed: set = set()
        try:
            for info in self._devices.values():
                if not isinstance(info, dict) or info.get("device_type") != "ev_charger":
                    continue
                for key in (
                    "switch_entity", "power_entity", "charger_service",
                    "start_stop_entity", "status_entity",
                ):
                    ent = info.get(key)
                    # charger_service is a "domain.service" string, not an
                    # entity — but it can never match a switch/power entity_id,
                    # so including it is harmless and keeps the set simple.
                    if ent:
                        claimed.add(ent)
        except Exception:  # pragma: no cover - defensive
            return claimed
        return claimed

    async def register_ev_charger(
        self,
        current_control_entity: str = None,
        power_entity: str = None,
        priority: int = 3,
        is_critical: bool = False,
        charger_service: str = None,
        charger_id: str = "ev_charger",
        charger_name: str = "EV Charger",
        start_stop_entity: str = None,
        status_entity: str = None,
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
            charger_id: Per-charger id from ``ev_chargers[i].id`` (#436).
                Defaults to ``"ev_charger"`` for backward compatibility with
                pre-#436 single-charger installs (their storage key was
                ``load_device_ev_charger``; preserved here so saved
                priority / critical / controllable flags carry across).
            charger_name: Per-charger friendly name from
                ``ev_chargers[i].name`` (#436). Falls back to the
                control entity's friendly_name if unset.
        """
        try:
            # #436: key on per-charger id. Pre-fix used a hardcoded
            # ``"load_device_ev_charger"`` so a multi-charger loop
            # caller overwrote the same entry N times — only the last
            # charger survived in the Load Priority card and peak
            # shedding throttled the wrong charger.
            device_id = f"load_device_{charger_id}"

            # Need at least one control method
            if not current_control_entity and not charger_service:
                _LOGGER.error("EV charger registration requires either current_control_entity or charger_service")
                return False

            # Check if number entity exists (if specified)
            if current_control_entity and not self.hass.states.get(current_control_entity):
                _LOGGER.warning("EV charger current control entity not found: %s", current_control_entity)
                current_control_entity = None  # Fall back to service

            # Check power entity
            if power_entity and not self.hass.states.get(power_entity):
                _LOGGER.warning("EV charger power entity not found: %s", power_entity)

            # Get friendly name. Caller-supplied ``charger_name`` wins
            # (it's the user-chosen label from ``ev_chargers[i].name``);
            # fall back to the control entity's friendly_name if the
            # caller passed the default ``"EV Charger"`` placeholder.
            friendly_name = charger_name
            if friendly_name in (None, "EV Charger") and current_control_entity:
                current_state = self.hass.states.get(current_control_entity)
                if current_state:
                    friendly_name = current_state.attributes.get(
                        "friendly_name", charger_name or "EV Charger",
                    )

            # EV charger can draw up to 22 kW (32 A × 3 phases × 230 V).
            # WATTS — the LM row's one unit (#896), as the registry rows.
            max_power = 22000.0

            # Register as load management device
            self._devices[device_id] = {
                "switch_entity": current_control_entity,  # Number entity (may be None)
                "charger_service": charger_service,  # Service-based control (e.g., "keba.set_current")
                "power_entity": power_entity,
                "device_type": "ev_charger",
                "description": f"EV Charger (Current Control) — {charger_id}",
                "friendly_name": friendly_name,
                "power_rating": max_power,
                "is_available": True,
                "priority": priority,
                "is_critical": is_critical,
                # (#780) a registered charger always has a control handle;
                # whether SEM may use it is control_mode's question.
                "has_control_handle": True,
                "user_hands_off": False,
                "is_controllable": True,  # LEGACY-WRITE (#780) — derived
                "control_type": "current",  # Special flag: use current control instead of switch
                "charger_id": charger_id,  # #436: lets callers / card map back to ev_chargers[i].id
                # (#748) the charger's stop switch / status sensor. Stored so
                # pattern discovery can EXCLUDE them: a switch already claimed
                # as this charger's start/stop is not a smart plug, and without
                # this it was rediscovered as ``load_device_<slug>`` — the third
                # duplicate row. Kept even when None so the key always exists.
                "start_stop_entity": start_stop_entity,
                "status_entity": status_entity,
            }

            # Save configuration
            await self._save_device_configuration()

            control_method = current_control_entity if current_control_entity else charger_service
            _LOGGER.info(
                "Registered EV charger for load management: %s "
                "(control: %s, power: %s, priority: %s, max: %skW)",
                device_id, control_method, power_entity, priority, max_power,
            )

            # Trigger callbacks to update sensors
            self._trigger_callbacks()

            return True

        except Exception as e:
            _LOGGER.error("Failed to register EV charger: %s", e, exc_info=True)
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
        # ``cb``, not ``callback`` — the loop name shadowed HA's ``@callback``
        # decorator imported at module level for the rest of this function.
        for cb in self._update_callbacks:
            try:
                cb()
            except Exception as e:
                _LOGGER.error("Error in load management callback: %s", e)

    def _effective_levels(self) -> Tuple[float, float]:
        """Warning/emergency levels, repaired into order at READ time (#717).

        The ladder must be ``warning < target < emergency``. The options flow
        rejects anything else, but that is not the only writer: the
        ``set_option`` service writes arbitrary keys with no validation, and
        entries created before the flow validated could already hold an
        inverted ladder. Repairing here covers every writer plus stored
        history, and leaves the user's numbers untouched so they can put them
        back in order themselves.

        The dangerous end is a LOW emergency: ``emergency <= target`` makes the
        EMERGENCY branch win before SHEDDING is ever considered, so SEM dumps
        loads the moment the target is touched. A HIGH warning is merely a lost
        stage (the target check fires first), repaired for symmetry.

        Repair falls back on the same ratios the install flow derives from
        (#717), not on the target itself: clamping *to* the target would leave
        ``emergency == target``, and the EMERGENCY branch — which tests ``>=`` —
        would still win at the target, making SHEDDING unreachable. The ratios
        put each level back on its own side with a stage's worth of room.
        """
        warning, emergency = repair_ladder(
            self._target_peak_limit, self._warning_level, self._emergency_level
        )
        if not self._logged_ladder_repair and (
            warning != self._warning_level or emergency != self._emergency_level
        ):
            self._logged_ladder_repair = True
            _LOGGER.warning(
                "Peak levels out of order (warning %.1f / target %.1f / emergency "
                "%.1f kW) — using %.1f / %.1f / %.1f for shedding decisions. "
                "Warning must be below the target and emergency above it; fix "
                "them under Configure → Load Management.",
                self._warning_level, self._target_peak_limit,
                self._emergency_level,
                warning, self._target_peak_limit, emergency,
            )
        return warning, emergency

    async def update_target_peak_limit(
        self, new_limit: float, unlimited: bool | None = None
    ):
        """Update the target peak limit and persist to config entry.

        (#717 redesign) ``unlimited`` is optional so the two existing
        Configure-flow writers (which set the flag separately via the
        options flow's own submit path) keep working unchanged. The
        Control-tab slider is the one caller that passes both in the same
        atomic write — dragging to the MAX notch and letting go must not
        leave a half-applied state between two separate service calls.
        """
        self._target_peak_limit = new_limit
        new_options = {**self.config_entry.options, "target_peak_limit": new_limit}
        # (#813) Carry the ladder with the target. Raising the target past the
        # emergency level left the STORED config inverted: the decision path
        # repairs it in memory (``_effective_levels``) so shedding still
        # behaves, but the options page — rightly — then refuses to save what
        # SEM itself wrote, and the user meets "emergency must be above the
        # target" on a page they never touched (live on PROD at 6.0/6.0).
        # A writer must leave a state its own form accepts. Same ratios the
        # in-memory repair uses, so both agree on where the levels land.
        _warn = float(new_options.get("warning_peak_level",
                                      DEFAULT_WARNING_PEAK_LEVEL) or 0)
        _emerg = float(new_options.get("emergency_peak_level",
                                       DEFAULT_EMERGENCY_PEAK_LEVEL) or 0)
        # (#872) The same one rule the other two writers and the decision
        # path use — three writers open-coding it was how they drifted.
        _warn_fixed, _emerg_fixed = repair_ladder(new_limit, _warn, _emerg)
        if _emerg_fixed != _emerg:
            new_options["emergency_peak_level"] = _emerg_fixed
            self._emergency_level = _emerg_fixed
        if _warn_fixed != _warn:
            new_options["warning_peak_level"] = _warn_fixed
            self._warning_level = _warn_fixed
        if unlimited is not None:
            self._peak_unlimited = unlimited
            new_options["peak_limit_unlimited"] = unlimited
        # Persist to config_entry.options so value survives restart (#199)
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator:
            # (#636b) the listener honors a SNAPSHOT (dict == new options,
            # recently armed) — the legacy bool True never matched and a
            # redundant reload followed every live-apply (seen 05:49:39).
            from homeassistant.util import dt as dt_util
            coordinator._skip_options_reload = dict(new_options)
            coordinator._skip_options_reload_armed_at = dt_util.utcnow().timestamp()
        self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)
        _LOGGER.info(
            "Updated target peak limit to %skW%s", new_limit,
            "" if unlimited is None else f" (unlimited={unlimited})",
        )
        self._trigger_callbacks()

    async def update_warning_peak_level(self, new_level: float):
        """(#636) Live-apply + persist the warning peak level.

        (#872) Through the same repair the decision path uses, so a warning
        set above the target is never STORED above it — #813's rule, which
        until now only the target writer honoured.
        """
        if not getattr(self, "_peak_unlimited", False):
            repaired, _ = repair_ladder(
                self._target_peak_limit, new_level, self._emergency_level)
            if repaired != new_level:
                _LOGGER.warning(
                    "Warning peak level %.1f kW is not below the target "
                    "%.1f kW — storing %.1f kW instead, which is what "
                    "shedding would have used anyway.",
                    new_level, self._target_peak_limit, repaired,
                )
                new_level = repaired
        self._warning_level = new_level
        new_options = {**self.config_entry.options, "warning_peak_level": new_level}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator:
            # (#636b) the listener honors a SNAPSHOT (dict == new options,
            # recently armed) — the legacy bool True never matched and a
            # redundant reload followed every live-apply (seen 05:49:39).
            from homeassistant.util import dt as dt_util
            coordinator._skip_options_reload = dict(new_options)
            coordinator._skip_options_reload_armed_at = dt_util.utcnow().timestamp()
        self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)
        _LOGGER.info("Updated warning peak level to %skW", new_level)
        self._trigger_callbacks()

    async def update_emergency_peak_level(self, new_level: float):
        """(#636) Live-apply + persist the emergency peak level.

        (#872) An emergency at or below the target makes the EMERGENCY branch
        win before SHEDDING is considered — SEM would dump loads the moment
        the target is touched. Repaired at the writer, not only in memory.
        """
        if not getattr(self, "_peak_unlimited", False):
            _, repaired = repair_ladder(
                self._target_peak_limit, self._warning_level, new_level)
            if repaired != new_level:
                _LOGGER.warning(
                    "Emergency peak level %.1f kW is not above the target "
                    "%.1f kW — storing %.1f kW instead; at or below the "
                    "target it would shed loads the moment the target is "
                    "reached.",
                    new_level, self._target_peak_limit, repaired,
                )
                new_level = repaired
        self._emergency_level = new_level
        new_options = {**self.config_entry.options, "emergency_peak_level": new_level}
        coordinator = getattr(self.config_entry, "runtime_data", None)
        if coordinator:
            # (#636b) the listener honors a SNAPSHOT (dict == new options,
            # recently armed) — the legacy bool True never matched and a
            # redundant reload followed every live-apply (seen 05:49:39).
            from homeassistant.util import dt as dt_util
            coordinator._skip_options_reload = dict(new_options)
            coordinator._skip_options_reload_armed_at = dt_util.utcnow().timestamp()
        self.hass.config_entries.async_update_entry(self.config_entry, options=new_options)
        _LOGGER.info("Updated emergency peak level to %skW", new_level)
        self._trigger_callbacks()

    async def update_device_priority(self, device_id: str, priority: int):
        """Update device priority."""
        if device_id in self._devices:
            self._devices[device_id]["priority"] = priority
            self._devices[device_id]["user_set_priority"] = True
            await self._save_device_configuration()
            _LOGGER.debug("Updated %s priority to %s (user-set)", device_id, priority)

    async def update_device_critical_status(self, device_id: str, is_critical: bool):
        """Update device critical status."""
        if device_id in self._devices:
            self._devices[device_id]["is_critical"] = is_critical
            await self._save_device_configuration()
            _LOGGER.debug("Updated %s critical status to %s", device_id, is_critical)

    async def async_set_hands_off(self, device_id: str, hands_off: bool):
        """The user's "never touch this load" toggle (#650) — PERMISSION (#780).

        It writes the permission axis and leaves the discovered capability
        alone. Pre-#780 it overwrote ``is_controllable``, so the row forgot a
        switch had ever been found for the appliance and anything asking "can
        this even be controlled?" got the user's preference back instead. The
        mixed key is still kept in step, derived, for readers on the old name.
        """
        if device_id in self._devices:
            row = self._devices[device_id]
            row["user_hands_off"] = bool(hands_off)
            row["is_controllable"] = (  # LEGACY-WRITE (#780) — derived
                may_actuate({**row, "control_mode": None}))
            await self._save_device_configuration()
            _LOGGER.debug("Updated %s hands-off to %s", device_id, hands_off)

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
            self._last_process_path = "disabled_skip"
            return

        # (#896) The live meter is what the shed plan is judged against.
        self._last_grid_import_w = float(grid_import_w or 0.0)

        # Update rolling peak tracking from actual grid import
        peak_changed = self._update_peak_tracking(grid_import_w)
        if peak_changed:
            await self._save_device_configuration()

        try:
            # Clean up shed list: remove devices that powered off naturally
            self._cleanup_shed_list()

            # Determine current state based on peak levels
            old_state = self._state
            new_state = self._determine_load_management_state(current_peak, consecutive_peak)

            # Handle state changes
            if new_state != self._state:
                await self._handle_state_change(self._state, new_state, current_peak)
                self._state = new_state
                self._last_process_path = f"state_changed:{old_state}_to_{new_state}"
            else:
                self._last_process_path = f"state_stable:{new_state}"

            # Execute load management based on current state
            await self._execute_load_management(current_peak, consecutive_peak)

            # EV charging current is now managed by coordinator._execute_ev_control()
            # via CurrentControlDevice — no duplicate control here.

            self._trigger_callbacks()

        except Exception as e:
            _LOGGER.error("Error in load management processing: %s", e)
            self._state = LoadManagementState.ERROR
            # Pre-#433 this catch-all set state=ERROR with no surface
            # signal beyond a log line. The path + last_error_message
            # now make WHICH error masked the load-shedding action
            # visible on the sensor.
            self._last_process_path = "error_caught"
            self._last_error_message = str(e)[:200]  # truncate runaway tracebacks

    # NOTE: update_ev_charging_current() has been removed.
    # EV charging current is now managed by the coordinator's _execute_ev_control()
    # method via CurrentControlDevice, providing a single-writer architecture.
    # The reactive headroom algorithm is embedded in _execute_ev_control().

    def get_state(self) -> str:
        """Get current load management state."""
        return self._state

    def _cleanup_shed_list(self):
        """Drop shed-list entries that are no longer ours to restore.

        A device may be removed from the list, or power off on its own (a
        cycle completes, the user turns it off). Keeping those in
        _devices_shed blocks state transitions and prevents correct
        accounting.

        (#896) "Off" alone is NOT "powered off on its own": a load SEM shed
        reads off — that is the shed working. #40's version evicted every
        shed load on the next cycle, so ``_restore_loads`` never had anything
        to restore and what SEM switched off stayed off (forum #30). A load
        is ours until it has RUN again since the shed (somebody switched it
        back on — ``_ran_since_shed``); a load that ran and then stopped on
        its own has nothing left for us to restore.
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

            # (#649) Not ours to hold — evict regardless of on/off. A stale
            # entry (upgrade, or a mode flip made while the device was shed)
            # otherwise pins the state machine: a non-empty _devices_shed reads
            # as SHEDDING, so _restore_loads never runs, so the guard that drops
            # the entry is never reached, and genuinely LM-shed peak_only loads
            # stay off indefinitely. Only reachable when the owning engine has
            # the device back ON (an off device is cleaned below anyway).
            if self._peak_managed_elsewhere(device_info):
                stale.append(device_id)
                continue

            device_state = self._device_discovery.get_device_current_state(device_info)
            if device_state["is_on"]:
                device_info["_ran_since_shed"] = True
            elif device_state["current_power"] <= 0 and device_info.get("_ran_since_shed"):
                stale.append(device_id)

        for device_id in stale:
            self._devices_shed.remove(device_id)
            if device_id in self._devices:
                self._devices[device_id].pop("_ran_since_shed", None)
            _LOGGER.debug(
                "Cleaned %s from shed list (ran and stopped on its own / removed)",
                device_id,
            )
        if stale and not self._devices_shed:
            self._end_shed_episode()

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
        # (#716) No grid ceiling declared → nothing to defend. Return NORMAL
        # before any threshold is consulted, so a stale level left in config
        # can't shed on an install that opted out.
        if self._peak_unlimited:
            self._last_state_decision_path = "peak_limit_unlimited_normal"
            return LoadManagementState.NORMAL

        warning_level, emergency_level = self._effective_levels()
        peak_to_check = current_peak
        restore_threshold = self._target_peak_limit - self._hysteresis

        # Emergency state - immediate action required
        if peak_to_check >= emergency_level:
            self._last_state_decision_path = "emergency"
            return LoadManagementState.EMERGENCY

        # At or above target - must shed loads
        elif peak_to_check >= self._target_peak_limit:
            self._last_state_decision_path = "above_target_shedding"
            return LoadManagementState.SHEDDING

        # In warning zone (between warning and target)
        elif peak_to_check >= warning_level:
            # If we have devices shed and peak is still in warning zone,
            # stay in SHEDDING to allow controlled restoration
            if self._devices_shed:
                self._last_state_decision_path = "warning_zone_keep_shedding"
                return LoadManagementState.SHEDDING
            self._last_state_decision_path = "warning_zone_clean"
            return LoadManagementState.WARNING

        # Below warning level
        else:
            # If peak is below warning level, always return to NORMAL
            # even if devices are still shed (they will be restored gradually)
            # This prevents the deadlock where devices stay shed indefinitely
            if peak_to_check <= restore_threshold:
                # Well below threshold - definitely NORMAL
                self._last_state_decision_path = "below_restore_threshold_normal"
                return LoadManagementState.NORMAL
            elif self._devices_shed:
                # Between restore_threshold and warning_level with devices shed
                # Allow restoration to proceed (return NORMAL to enable restore logic)
                #
                # NOTE (#433 audit, reviewer-flagged): with default
                # config (target=5.0, hysteresis=0.3, warning=4.5),
                # restore_threshold = 4.7 > warning_level = 4.5, so
                # this branch is **unreachable** — peaks satisfying
                # ``peak < warning_level`` (< 4.5) cannot
                # simultaneously satisfy ``peak > restore_threshold``
                # (> 4.7). It only fires when the user has configured
                # ``hysteresis > target - warning`` (an unusual but
                # valid setup). Telemetry exposes this so a future
                # audit can either fix the inverted-band config or
                # remove the branch.
                self._last_state_decision_path = "in_hysteresis_band_with_shed_devices_restore"
                return LoadManagementState.NORMAL
            else:
                self._last_state_decision_path = "in_hysteresis_band_clean_normal"
                return LoadManagementState.NORMAL

    async def _handle_state_change(self, old_state: str, new_state: str, current_peak: float):
        """Handle load management state changes."""
        _LOGGER.info(
            "Load management state change: %s → %s (peak: %skW, target: %skW)",
            old_state, new_state, round(current_peak, 2), self._target_peak_limit,
        )

        if new_state == LoadManagementState.EMERGENCY:
            _LOGGER.warning(
                "EMERGENCY load shedding triggered! Peak %skW exceeds emergency level %skW",
                round(current_peak, 2), self._emergency_level,
            )

    async def _execute_load_management(self, current_peak: float, consecutive_peak: float):
        """Execute load management actions based on current state.

        Sets ``self._last_action_path`` (#433) to one of:
        ``emergency_shedding`` / ``progressive_shedding`` /
        ``restore`` / ``no_action:<state>`` (WARNING / ERROR).
        """
        if self._state == LoadManagementState.EMERGENCY:
            self._last_action_path = "emergency_shedding"
            await self._emergency_load_shedding()
        elif self._state == LoadManagementState.SHEDDING:
            self._last_action_path = "progressive_shedding"
            await self._progressive_load_shedding(current_peak, consecutive_peak)
        elif self._state == LoadManagementState.NORMAL:
            self._last_action_path = "restore"
            await self._restore_loads()
        else:
            # WARNING / ERROR states intentionally take no action
            self._last_action_path = f"no_action:{self._state}"

    @staticmethod
    def _peak_managed_elsewhere(device_info: Dict) -> bool:
        """Does another engine already own this device's peak shed + restart?

        Two kinds, one rule — the load manager must not actuate a device whose
        run/stop decision belongs to a different writer, because the two engines
        keep SEPARATE shed state, anti-flicker and restore criteria and will
        fight each other:

        * **EV chargers** (#461-peak) — peak-managed by ``decide()`` / the night
          planner, actuated through the reconciler. Daytime charging is
          solar-driven (no grid peak) and the night grid top-up is already
          peak-aware (``ev_control._night_peak_managed_amps``).
        * **SURPLUS-mode loads** (#649) — the surplus controller receives
          ``peak_state`` every cycle and sheds its own actives (SHEDDING: one
          per cycle, EMERGENCY: all of them). Shedding them here too was
          survivable; RESTORING them was not. ``_restore_device`` turns the
          switch back on the moment the peak recedes — with zero surplus, and
          with surplus intent OFF — after which ``device_reconciler``
          classifies the load ``external_on`` ("don't fight the user") and it
          runs on grid all night. The comment at ``surplus_controller.py:155``
          has always claimed the load manager owns only ``peak_only``; this is
          the code finally saying the same thing.

        ``surplus_managed`` is set by the registry sync for devices actually
        registered with the surplus controller — a surplus-mode device that
        nothing else drives (no live controller object) stays ours to shed,
        so the exclusion can't silently orphan a load.
        """
        if device_info.get("device_type") == "ev_charger":
            return True
        return (
            device_info.get("control_mode") == "surplus"
            and bool(device_info.get("surplus_managed"))
        )

    async def _emergency_load_shedding(self):
        """EMERGENCY: shed toward the aim in one pass — several switches if
        the need says so, none if it does not. Bounded by the need, never by
        a timer (#896)."""
        await self._shed_toward("EMERGENCY")

    async def _progressive_load_shedding(self, current_peak: float, consecutive_peak: float):
        """SHEDDING: one switch per pass, then let the meter answer (#896).

        ``current_peak`` is the 15-minute average the state machine reads;
        the plan itself reads the live meter — see ``_shed_plan``."""
        await self._shed_toward("PROGRESSIVE")

    def _shed_plan(self) -> Dict[str, Any]:
        """What the meter asks for, and what SEM can answer with (#896).

        Three numbers, one verdict:

        * ``need_w`` — live grid import above the aim (target − hysteresis).
          Read from the METER, not from the 15-minute average: the average
          is the past, and no switch can undo the past. Under the aim → no
          need, whatever the average still says.
        * ``sheddable_w`` — the draw of everything SEM MAY shed: permitted,
          available, not critical, not already shed, and on. Anti-flicker-
          blocked loads count — they are still ours, just not yet. So do
          **surplus-managed** loads: the surplus controller sheds its own
          actives on the same SHEDDING/EMERGENCY state (#649 — one per
          cycle, then all of them). They are SEM's authority through the
          other engine; leaving them out filed a Repair naming kilowatts SEM
          was switching off on the very same cycle. ``surplus_engine_w`` is
          that share, so the path can say who is answering.
        * ``futile`` — even with all of that off the meter would sit above
          the TARGET. Then the peak belongs to a load SEM does not control
          (forum #30: an unmanaged EV) and shedding the house cannot fix
          it. Shed nothing; say so.

        ``candidates`` is the subset that can be thrown right now, highest
        priority number first — the order the drag list gives.
        """
        target_w = float(self._target_peak_limit) * 1000.0
        aim_w = (float(self._target_peak_limit) - float(self._hysteresis)) * 1000.0
        grid_import_w = float(self._last_grid_import_w)
        need_w = max(0.0, grid_import_w - aim_w)

        sheddable_w = 0.0
        surplus_engine_w = 0.0
        candidates: List[Tuple[str, Dict, float]] = []
        can_shed_now = {did for did, _ in self._get_devices_for_shedding()}
        for device_id, device_info in self._devices.items():
            if not may_actuate(device_info):
                continue
            # A charger's peak is decide()'s (#461-peak) and never drawn
            # from here; a surplus-managed load IS shed on this state, by the
            # surplus controller — its draw is authority, not a candidate.
            if device_info.get("device_type") == "ev_charger":
                continue
            if device_info.get("is_critical", False):
                continue
            if device_id in self._devices_shed:
                continue
            if not device_info.get("is_available", False):
                continue
            state = self._device_discovery.get_device_current_state(device_info)
            if not state.get("is_on"):
                continue
            draw_w = float(state.get("current_power") or 0.0)
            if not state.get("power_known", True):
                # Energy-only load, or a power entity that is dark right now:
                # ON is ON, and the rating is the best estimate of what the
                # switch would free. A MEASURED 0 (thermostat idle) stays 0
                # — the rating is no substitute for a reading that exists.
                draw_w = float(device_info.get("power_rating") or 0.0)
            if draw_w <= 0:
                continue
            sheddable_w += draw_w
            if self._peak_managed_elsewhere(device_info):
                surplus_engine_w += draw_w
            elif device_id in can_shed_now:
                candidates.append((device_id, device_info, draw_w))
        candidates.sort(key=lambda c: c[1].get("priority", 5), reverse=True)

        uncontrolled_w = grid_import_w - sheddable_w
        return {
            "grid_import_w": grid_import_w,
            "target_w": target_w,
            "need_w": need_w,
            "sheddable_w": sheddable_w,
            "surplus_engine_w": surplus_engine_w,
            "uncontrolled_w": uncontrolled_w,
            "futile": need_w > 0 and uncontrolled_w > target_w,
            "candidates": candidates,
        }

    async def _shed_toward(self, reason: str) -> None:
        """Shed until the meter's need is covered — and not one switch more.

        EMERGENCY throws as many switches as the need takes in one pass;
        PROGRESSIVE throws one and waits for the meter (the inter-shed delay
        inside ``_shed_device``). Both stop the moment the shed draw covers
        the need. A futile plan sheds nothing and files the Repair; the
        Repair is withdrawn the first pass the plan is not futile.
        """
        plan = self._shed_plan()
        self._shed_need_w = plan["need_w"]
        self._shed_sheddable_w = plan["sheddable_w"]
        self._uncontrolled_w = plan["uncontrolled_w"]
        self._shed_futile = plan["futile"]

        if plan["futile"]:
            self._shed_path = "futile"
            if not self._futile_repair_open:
                self._futile_repair_open = True
                from ..coordinator.repair_issues import raise_load_shed_futile
                raise_load_shed_futile(
                    self.hass,
                    grid_import_kw=plan["grid_import_w"] / 1000.0,
                    target_kw=plan["target_w"] / 1000.0,
                    uncontrolled_kw=plan["uncontrolled_w"] / 1000.0,
                )
                _LOGGER.warning(
                    "Load shedding is futile: %.1f kW at the meter, %.1f kW is "
                    "everything SEM may shed — %.1f kW belongs to a load SEM does "
                    "not control (target %.1f kW). Shedding nothing.",
                    plan["grid_import_w"] / 1000.0, plan["sheddable_w"] / 1000.0,
                    plan["uncontrolled_w"] / 1000.0, plan["target_w"] / 1000.0,
                )
            return

        if self._futile_repair_open:
            self._futile_repair_open = False
            from ..coordinator.repair_issues import clear_load_shed_futile
            clear_load_shed_futile(self.hass)

        if plan["need_w"] <= 0:
            self._shed_path = "held:under_aim"
            return

        if self._observer_mode and plan["candidates"]:
            # The plan is made; the switch is not thrown. Name what was
            # withheld — a rig in observer mode must read as "withheld",
            # never as a shed delay that was not the reason.
            would, would_w = [], 0.0
            for device_id, _info, draw_w in plan["candidates"]:
                would.append(device_id)
                would_w += draw_w
                if would_w >= plan["need_w"] or reason != "EMERGENCY":
                    break
            self._shed_path = f"observer:withheld:{len(would)}"
            _LOGGER.info(
                "Observer mode: %s shedding would turn off %s (need %.0f W)",
                reason, ", ".join(would), plan["need_w"],
            )
            return

        shed_w = 0.0
        shed_n = 0
        for device_id, _info, draw_w in plan["candidates"]:
            if shed_w >= plan["need_w"]:
                break
            if await self._shed_device(device_id, reason):
                shed_w += draw_w
                shed_n += 1
                if reason != "EMERGENCY":
                    break  # one per pass — the meter answers before the next
        if shed_n:
            self._shed_path = f"shed:{shed_n}"
            self._announce_shed_episode(plan)
        elif not plan["candidates"]:
            if plan["sheddable_w"] > plan["surplus_engine_w"]:
                self._shed_path = "waiting:anti_flicker"
            elif plan["surplus_engine_w"] > 0:
                self._shed_path = "waiting:surplus_controller"
            else:
                self._shed_path = "nothing_sheddable"
        else:
            self._shed_path = "waiting:shed_delay"
        _LOGGER.debug(
            "%s shedding: need %.0f W, sheddable %.0f W, shed %.0f W (%d) → %s",
            reason, plan["need_w"], plan["sheddable_w"], shed_w, shed_n, self._shed_path,
        )

    # -- a shed is never silent (#896) ------------------------------------

    def _announce_shed_episode(self, plan: Dict[str, Any]) -> None:
        """One persistent notification per episode, updated in place with
        every further shed, dismissed when the last load is restored; plus
        the bus event the mobile/notification layer listens on."""
        names = [
            self._devices.get(did, {}).get("friendly_name", did)
            for did in self._devices_shed
        ]
        grid_kw = plan["grid_import_w"] / 1000.0
        target_kw = plan["target_w"] / 1000.0
        message = (
            f"SEM switched off {', '.join(names)} to hold the grid peak: "
            f"{grid_kw:.1f} kW at the meter against a {target_kw:.1f} kW target. "
            f"Loads come back one at a time once the peak has passed."
        )
        try:
            from homeassistant.components import persistent_notification
            persistent_notification.async_create(
                self.hass, message,
                title="Peak load shedding",
                notification_id="sem_load_shed",
            )
            self._shed_notified = True
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("shed notification failed: %s", e)
        try:
            self.hass.bus.async_fire(f"{DOMAIN}_notification", {
                "category": "alerts",
                "event": "load_shed",
                "devices": list(self._devices_shed),
                "grid_import_kw": round(grid_kw, 2),
                "target_kw": round(target_kw, 2),
            })
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("shed event failed: %s", e)

    def _end_shed_episode(self) -> None:
        """The last shed load is back (or gone): take the notification down."""
        if not self._shed_notified:
            return
        self._shed_notified = False
        try:
            from homeassistant.components import persistent_notification
            persistent_notification.async_dismiss(self.hass, "sem_load_shed")
        except Exception as e:  # noqa: BLE001
            _LOGGER.debug("shed notification dismiss failed: %s", e)

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
                    "Device %s cannot be shed yet (on for %ss, min: %ss)",
                    device_id, round(time_on), min_duration,
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
                    "Device %s cannot be restored yet (off for %ss, min: %ss)",
                    device_id, round(time_off), min_duration,
                )
                return False

        return True

    def _get_devices_for_shedding(self) -> List[Tuple[str, Dict]]:
        """Get available devices for shedding, sorted by priority."""
        available_devices = []

        for device_id, device_info in self._devices.items():
            # (#780) Capability AND permission — "off" mode (#49) and the
            # user's hands-off opt-out (#650) both live in may_actuate now.
            if not may_actuate(device_info):
                continue
            # Devices another engine peak-manages (#461-peak EV, #649
            # surplus-mode loads) are never shed from here — see
            # _peak_managed_elsewhere for the full rationale.
            if self._peak_managed_elsewhere(device_info):
                continue
            if (not device_info.get("is_critical", False) and
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

    async def _shed_device(self, device_id: str, reason: str) -> bool:
        """Turn off a device for load shedding. True when the switch was thrown.

        Uses the 'control' config from device discovery to determine how to shed:
        - switch: Turn off the switch entity
        - current: Set number entity to 0A (EV chargers)
        - service: Call service with shed_value (e.g., keba.set_current)
        - input_boolean: Turn off the input_boolean

        (#896) The inter-shed delay is PROGRESSIVE's: one switch, then let
        the meter answer. EMERGENCY is bounded by the plan's need instead —
        several switches in one pass when the need says so.
        """
        if self._observer_mode:
            _LOGGER.debug("Observer mode: skipping shed of %s", device_id)
            return False

        if device_id not in self._devices:
            return False

        # Single-writer guard (#461-peak EV, #649 surplus): the side-channel
        # write would fight the owning engine's heartbeat. Belt-and-braces with
        # the two selection-path skips, for any future caller that reaches here.
        if self._peak_managed_elsewhere(self._devices[device_id]):
            _LOGGER.debug(
                "Skipping load-manager shed of %s — peak-managed by another "
                "writer (#461-peak / #649)", device_id,
            )
            return False

        device_info = self._devices[device_id]

        # Check anti-flicker constraint
        if not self._can_shed_device(device_id, device_info):
            _LOGGER.debug("Cannot shed %s: anti-flicker protection active", device_id)
            return False

        # Check if enough time has passed since last shedding
        if (reason != "EMERGENCY" and self._last_shedding_time and
            dt_util.now() - self._last_shedding_time < timedelta(seconds=DEFAULT_LOAD_SHEDDING_DELAY)):
            _LOGGER.debug("Cannot shed %s: shedding delay active", device_id)
            return False

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
                        _LOGGER.debug("Shed device via switch %s (was_on=%s)", entity, was_on)

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
                        _LOGGER.debug("Shed device via current control %s (set to 0A)", entity)

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
                            _LOGGER.debug("Shed device via service %s", service)

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
                        _LOGGER.debug("Shed device via input_boolean %s (was_on=%s)", entity, was_on)

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
                self._devices[device_id]["shed_reason"] = reason
                self._devices[device_id].pop("_ran_since_shed", None)
                _LOGGER.info(
                    "Shed device %s (%s load shedding)",
                    device_info.get('friendly_name', device_id), reason,
                )

        except Exception as e:
            _LOGGER.error("Failed to shed device %s: %s", device_id, e)
        return success

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

        # Single-writer guard (#461-peak EV, #649 surplus): never restore a
        # device another engine owns — we don't shed them, so they shouldn't be
        # in _devices_shed, but an entry can survive an upgrade or a mode change
        # made while the device was already shed. Drop it WITHOUT turning the
        # load on: the owning engine restarts it on its own criteria (for a
        # surplus load, when there is actually surplus). Turning it on here is
        # exactly the #649 all-night-on-grid failure.
        if self._peak_managed_elsewhere(device_info):
            self._devices_shed = [d for d in self._devices_shed if d != device_id]
            return

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
                            _LOGGER.debug("Restored device via switch %s", entity)

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
                            _LOGGER.debug("Restored device via service %s", service)

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
                            _LOGGER.debug("Restored device via input_boolean %s", entity)

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
                self._devices[device_id].pop("shed_reason", None)
                self._devices[device_id].pop("_ran_since_shed", None)
                _LOGGER.info("Restored device %s", device_info.get('friendly_name', device_id))
                if not self._devices_shed:
                    self._end_shed_episode()

        except Exception as e:
            _LOGGER.error("Failed to restore device %s: %s", device_id, e)

    def get_load_management_data(self) -> Dict[str, Any]:
        """Get current load management data for sensors."""
        total_devices = len(self._devices)
        # "Switchable" = controllable AND currently on (i.e. could be shed now).
        # Previously counted all available+controllable devices, which kept the
        # number at "10" even when the user had turned them all off (#193).
        # Devices another engine peak-manages are excluded everywhere
        # (#461-peak EV, #649 surplus loads): load_management neither sheds them
        # nor counts them as sheddable, so the sensor doesn't over-report — "how
        # much can we shed?" must match what shedding will actually target (a
        # 22 kW EV draw, or a surplus pump the surplus controller owns, is NOT
        # reducible from here).
        # (#780) ...and the mode: a load the user set to Off is not sheddable,
        # so counting it here over-reported "how much can we shed?" in exactly
        # the way the paragraph above says it must not. may_actuate asks both
        # axes, which is what _get_devices_for_shedding walks.
        controllable_devices = sum(
            1 for d in self._devices.values()
            if not self._peak_managed_elsewhere(d)
            and may_actuate(d)
            and d.get("is_available", False)
            and self._is_device_currently_on(d)
        )

        available_reduction = sum(
            self._device_discovery.get_device_current_state(device_info)["current_power"] / 1000
            for device_id, device_info in self._devices.items()
            if (not self._peak_managed_elsewhere(device_info) and
                may_actuate(device_info) and
                not device_info.get("is_critical", False) and
                device_id not in self._devices_shed and
                self._is_device_currently_on(device_info))
        )

        warning_level, emergency_level = self._effective_levels()

        return {
            "state": self._state,
            "target_peak_limit": self._target_peak_limit,
            # (#717, found in review) repaired at read time, not the raw
            # stored values — a consumer of this dict must see the same
            # ladder _monitor_and_shed() actually shed against, not a stored
            # ladder that could still be inverted (set_option writes with no
            # validation; pre-#717 entries could predate the options-flow
            # ordering check).
            "warning_level": warning_level,
            "emergency_level": emergency_level,
            # (#716) The label, not the number. The stored kW values stay as
            # they are and keep flowing to the sensors — no consumer of this
            # dict ever sees an infinity, so nothing downstream can render
            # NaN. Cards read this flag to show "Unlimited" instead.
            "peak_limit_unlimited": self._peak_unlimited,
            "total_devices": total_devices,
            "controllable_devices": controllable_devices,
            "devices_shed": len(self._devices_shed),
            "devices_shed_list": self._devices_shed.copy(),
            "available_load_reduction": round(available_reduction, 2),
            "enabled": self._enabled,
            "devices": {
                did: {**dinfo, "is_shed": did in self._devices_shed}
                for did, dinfo in self._devices.items()
            },
            "consecutive_peak_15min": self._consecutive_peak_15min,
            "monthly_consecutive_peak": self._monthly_consecutive_peak,
            # #433 — telemetry surface (mirrors classifier_path /
            # dampening_path pattern). Last-call decision paths so
            # users hitting an unexpected state can self-diagnose.
            "state_decision_path": self._last_state_decision_path,
            "process_path": self._last_process_path,
            "action_path": self._last_action_path,
            "last_error": self._last_error_message,
            # (#896) The plan's verdict and its numbers: what the meter asked
            # for, what SEM could answer with, and whether the peak was ours
            # to fix at all.
            "shed_path": self._shed_path,
            "shed_need_w": round(self._shed_need_w),
            "shed_sheddable_w": round(self._shed_sheddable_w),
            "shed_futile": self._shed_futile,
            "uncontrolled_w": round(self._uncontrolled_w),
        }

    def get_peak_margin(self, current_peak: float) -> float:
        """Get remaining margin before target peak is reached."""
        return max(0, self._target_peak_limit - current_peak)