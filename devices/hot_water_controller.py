"""Hot water controller for Solar Energy Management.

Supports three HA entity types for broad hardware compatibility (#92):
- water_heater.* (Viessmann, Nibe, Daikin Altherma, MQTT)
- climate.* (KNX, Stiebel Eltron, ESPHome thermostat)
- switch.* (Shelly relay, smart plugs, ESPHome GPIO) + separate temp sensor

Includes mandatory Legionella prevention cycle:
- Tracks hours since tank last reached disinfection temperature
- Forces heating to target (60-80°C) if interval exceeded
- Cannot be disabled — only interval and target are configurable
- Auto-adjusts hold duration based on target temperature
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .base import SwitchDevice, DeviceState

_LOGGER = logging.getLogger(__name__)

DEFAULT_SOLAR_TARGET_TEMP = 50.0  # Normal solar heating target
DEFAULT_MAX_TEMPERATURE = 55.0    # Solar heating cutoff (below Legionella target)
DEFAULT_MIN_TEMPERATURE = 40.0    # Minimum useful temperature
DEFAULT_HOT_WATER_POWER = 2000    # Typical immersion heater power

# Legionella prevention defaults
DEFAULT_LEGIONELLA_TARGET = 65.0  # Disinfection temperature
DEFAULT_LEGIONELLA_INTERVAL_HOURS = 72  # Max hours between cycles
DEFAULT_LEGIONELLA_MIN_TEMP = 60.0  # Absolute minimum allowed

# Hold duration by target temperature (higher = shorter hold)
LEGIONELLA_HOLD_MINUTES = {
    60: 30,
    65: 20,
    70: 5,
    75: 3,
    80: 3,
}


class HotWaterController(SwitchDevice):
    """Hot water controller with multi-entity support and Legionella prevention.

    Supports water_heater, climate, and switch entities.
    The Legionella cycle is mandatory and cannot be disabled.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str = "hot_water",
        name: str = "Hot Water",
        rated_power: float = DEFAULT_HOT_WATER_POWER,
        priority: int = 6,
        entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        temperature_entity_id: Optional[str] = None,
        max_temperature: float = DEFAULT_MAX_TEMPERATURE,
        min_temperature: float = DEFAULT_MIN_TEMPERATURE,
        solar_target_temp: float = DEFAULT_SOLAR_TARGET_TEMP,
        legionella_target_temp: float = DEFAULT_LEGIONELLA_TARGET,
        legionella_interval_hours: float = DEFAULT_LEGIONELLA_INTERVAL_HOURS,
        min_on_time: int = 300,
        min_off_time: int = 60,
        daily_min_runtime_sec: int = 0,
        energy_entity_id: Optional[str] = None,
    ):
        super().__init__(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            entity_id=entity_id,
            power_entity_id=power_entity_id,
            min_on_time=min_on_time,
            min_off_time=min_off_time,
            daily_min_runtime_sec=daily_min_runtime_sec,
            energy_entity_id=energy_entity_id,  # #600 — DHW kWh counter → derived power
        )
        self.temperature_entity_id = temperature_entity_id
        self.max_temperature = max_temperature
        self.min_temperature = min_temperature
        self.solar_target_temp = solar_target_temp
        self.legionella_target_temp = max(legionella_target_temp, DEFAULT_LEGIONELLA_MIN_TEMP)
        self.legionella_interval_hours = legionella_interval_hours

        # Detect entity type from domain
        self._entity_domain: Optional[str] = None
        if entity_id:
            self._entity_domain = entity_id.split(".")[0]

        # Legionella tracking
        self._last_legionella_time: Optional[datetime] = None
        self._legionella_cycle_active: bool = False
        self._legionella_hold_start: Optional[datetime] = None

        # #594 — vacation mode. Both set each cycle by the coordinator.
        # While ``vacation`` is True there is no comfort heating (no solar-
        # target boost, no cheap-tariff force) and legionella cycles are
        # PAUSED — ``_last_legionella_time`` keeps aging, so a cycle that
        # falls due while away runs promptly on return. When
        # ``vacation_dhw_surplus`` is also True the tank may still soak up
        # solar surplus, but only to ``min_temperature`` (free energy
        # without comfort heating).
        self.vacation: bool = False
        self.vacation_dhw_surplus: bool = False

        # #420 — telemetry surface mirroring #359/#416 classifier_path
        # pattern. Each decision branch sets the corresponding ``*_path``
        # string so the ``load_management_status`` sensor's ``devices``
        # dict can publish them for self-diagnosis. No behavior change.
        self._last_legionella_path: str = "uninitialized"
        self._last_temperature_safety_path: str = "uninitialized"
        self._last_temperature_reading_path: str = "uninitialized"
        self._last_activation_path: str = "uninitialized"
        self._last_deactivation_path: str = "uninitialized"
        self._last_temperature_reading: Optional[float] = None

        # #508 — hot water exists to soak up solar surplus, so it must be
        # a SURPLUS-mode device. The base default is PEAK_ONLY, and
        # SurplusController.update() never proactively activates a
        # non-SURPLUS device — so without this the controller registered
        # but never turned on. Overridable via set_device_control_mapping.
        from .base import DeviceControlMode
        self.control_mode = DeviceControlMode.SURPLUS

    @property
    def entity_domain(self) -> Optional[str]:
        """Return the entity domain (water_heater, climate, or switch)."""
        return self._entity_domain

    @property
    def hours_since_legionella(self) -> float:
        """Hours since last Legionella prevention cycle."""
        if self._last_legionella_time is None:
            return 999.0  # Never run — trigger immediately
        delta = dt_util.now() - self._last_legionella_time
        return delta.total_seconds() / 3600

    @property
    def legionella_overdue(self) -> bool:
        """True if Legionella prevention cycle is overdue."""
        return self.hours_since_legionella > self.legionella_interval_hours

    @property
    def legionella_hold_minutes(self) -> int:
        """Hold duration based on target temperature."""
        target = int(self.legionella_target_temp)
        # Find the closest threshold
        for temp in sorted(LEGIONELLA_HOLD_MINUTES.keys()):
            if target <= temp:
                return LEGIONELLA_HOLD_MINUTES[temp]
        return 3  # 80°C+ = 3 minutes

    def _active_target_temp(self) -> float:
        """The temperature target for the CURRENT operating context (#594).

        Legionella cycle → ``legionella_target_temp`` (disinfection is never
        run during vacation — the coordinator pauses cycles, see
        ``check_legionella_cycle``). Vacation surplus dump →
        ``min_temperature`` (free solar energy without comfort heating).
        Normal solar boost → ``solar_target_temp``.
        """
        if self._legionella_cycle_active:
            return self.legionella_target_temp
        if self.vacation and self.vacation_dhw_surplus:
            return self.min_temperature
        return self.solar_target_temp

    def get_current_temperature(self) -> Optional[float]:
        """Read water temperature from sensor or entity attributes.

        Records which source produced the reading on
        ``self._last_temperature_reading_path`` (#420 telemetry).
        """
        attribute_invalid = False

        # For water_heater and climate: read from entity attributes
        if self._entity_domain in ("water_heater", "climate") and self.entity_id:
            state = self.hass.states.get(self.entity_id)
            if state:
                temp = state.attributes.get("current_temperature")
                if temp is not None:
                    try:
                        val = float(temp)
                        self._last_temperature_reading_path = "entity_attribute"
                        self._last_temperature_reading = val
                        return val
                    except (ValueError, TypeError):
                        # Attribute present but non-numeric — fall
                        # through to the separate sensor path so we
                        # can still produce a reading. Remember that
                        # we saw a bad attribute so the diagnostic
                        # path captures it if the fallback also fails.
                        attribute_invalid = True

        # For switch or fallback: use separate temperature sensor
        if self.temperature_entity_id:
            state = self.hass.states.get(self.temperature_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    val = float(state.state)
                    self._last_temperature_reading_path = "separate_sensor"
                    self._last_temperature_reading = val
                    return val
                except (ValueError, TypeError):
                    self._last_temperature_reading_path = "separate_sensor_invalid"
            elif state:
                self._last_temperature_reading_path = "separate_sensor_unavailable"
            else:
                self._last_temperature_reading_path = "separate_sensor_missing"
        elif attribute_invalid:
            # Entity attribute was unparseable and no separate sensor
            # is configured to fall back to.
            self._last_temperature_reading_path = "entity_attribute_invalid"
        else:
            # Neither entity attribute usable nor a separate sensor
            # configured — we operate "blind" and rely on the device's
            # own thermostat. Important to surface this state on every
            # call, not just the first (the prior ``uninitialized``
            # guard was too narrow — flagged by reviewer).
            self._last_temperature_reading_path = "no_source_configured"

        self._last_temperature_reading = None
        return None

    def is_temperature_safe(self) -> bool:
        """Check if temperature is below the active target.

        During normal solar boost: cutoff is solar_target_temp.
        During Legionella cycle: cutoff is legionella_target_temp.

        Records which branch fired on
        ``self._last_temperature_safety_path`` (#420).

        Sensor-unavailable distinction (v1.7.2, 2026-06-07):
        * ``no_sensor_configured`` — user never configured a sensor.
          Returns ``True`` so SEM can drive the device and rely on the
          device's own internal thermostat (by design).
        * ``configured_sensor_broken`` — user DID configure a sensor
          but it is currently ``unavailable`` / ``unknown`` / invalid.
          Returns ``False`` (fail-safe). Without this, a broken
          temperature sensor would let SEM activate the heater
          indefinitely, relying only on the device's thermostat —
          fine when the device's thermostat is healthy, dangerous if
          the sensor failure is correlated with broader hardware issues.
        """
        temp = self.get_current_temperature()
        if temp is None:
            # ``get_current_temperature`` already recorded WHY the read
            # returned None on ``_last_temperature_reading_path``. We
            # use that to split the silent-failure case from the
            # genuinely-unconfigured case.
            reading_path = self._last_temperature_reading_path or "uninitialized"
            if reading_path == "no_source_configured":
                self._last_temperature_safety_path = "no_sensor_configured"
                return True  # No sensor — allow operation (rely on thermostat)
            # Sensor configured but broken — fail-safe.
            self._last_temperature_safety_path = "configured_sensor_broken"
            return False
        if self._legionella_cycle_active:
            if temp < self.legionella_target_temp:
                self._last_temperature_safety_path = "in_legionella_cycle_below_target"
                return True
            self._last_temperature_safety_path = "in_legionella_cycle_at_target"
            return False
        if self.vacation and self.vacation_dhw_surplus:
            # #594 — surplus dump caps at the MINIMUM temperature target,
            # not the solar comfort target.
            if temp < self.min_temperature:
                self._last_temperature_safety_path = "vacation_below_min_target"
                return True
            self._last_temperature_safety_path = "vacation_at_min_target"
            return False
        if temp < self.solar_target_temp:
            self._last_temperature_safety_path = "normal_below_solar_target"
            return True
        self._last_temperature_safety_path = "normal_at_solar_target"
        return False

    def needs_heating(self) -> bool:
        """Check if water temperature is below minimum."""
        temp = self.get_current_temperature()
        if temp is None:
            return True
        return temp < self.min_temperature

    @property
    def needs_offpeak_activation(self) -> bool:
        """Temperature-aware override: don't force-heat if already at max temp."""
        if self.vacation:
            # #594 — no cheap-tariff comfort forcing while away (the optional
            # surplus dump is solar-surplus-only by design).
            return False
        if not super().needs_offpeak_activation:
            return False
        if not self.is_temperature_safe():
            return False
        return True

    async def activate(self, available_watts: float) -> float:
        """Activate hot water heating with temperature safety check.

        Records the activation branch on ``self._last_activation_path`` (#420):
        ``blocked_unsafe`` / ``water_heater`` / ``climate`` / ``switch_fallback``
        / ``vacation_blocked`` (#594).

        #594: while vacation mode is active there is no comfort heating.
        With the opt-in ``vacation_dhw_surplus`` the tank may still take
        surplus, capped at ``min_temperature`` (see ``_active_target_temp``
        and the vacation branch in ``is_temperature_safe``).
        """
        if self.vacation and not self.vacation_dhw_surplus:
            self._last_activation_path = "vacation_blocked"
            return 0.0
        if not self.is_temperature_safe():
            _LOGGER.info(
                "Hot water at %.1f°C — above max %.1f°C, skipping",
                self.get_current_temperature() or 0,
                self.legionella_target_temp if self._legionella_cycle_active else self.max_temperature,
            )
            self._last_activation_path = "blocked_unsafe"
            return 0.0

        # Use appropriate control method based on entity type
        if self._entity_domain == "water_heater":
            self._last_activation_path = "water_heater"
            return await self._activate_water_heater()
        elif self._entity_domain == "climate":
            self._last_activation_path = "climate"
            return await self._activate_climate()
        else:
            self._last_activation_path = "switch_fallback"
            return await super().activate(available_watts)

    async def deactivate(self) -> None:
        """Deactivate hot water heating.

        Records the deactivation branch on
        ``self._last_deactivation_path`` (#420).
        """
        if self._entity_domain == "water_heater":
            self._last_deactivation_path = "water_heater"
            await self._deactivate_water_heater()
        elif self._entity_domain == "climate":
            self._last_deactivation_path = "climate"
            await self._deactivate_climate()
        else:
            self._last_deactivation_path = "switch_fallback"
            await super().deactivate()

    async def _activate_water_heater(self) -> float:
        """Activate via water_heater domain."""
        try:
            target = self._active_target_temp()
            await self.hass.services.async_call(
                "water_heater", "set_temperature",
                {"entity_id": self.entity_id, "temperature": target},
                blocking=True,
            )
            # Try turn_on if supported
            try:
                await self.hass.services.async_call(
                    "water_heater", "turn_on",
                    {"entity_id": self.entity_id},
                    blocking=True,
                )
            except Exception:
                pass  # Not all water_heater entities support turn_on
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to activate water_heater: %s", e)
            return 0.0

    async def _deactivate_water_heater(self) -> None:
        """Deactivate via water_heater domain."""
        try:
            await self.hass.services.async_call(
                "water_heater", "turn_off",
                {"entity_id": self.entity_id},
                blocking=True,
            )
        except Exception:
            # Not all support turn_off — set low temp instead
            try:
                await self.hass.services.async_call(
                    "water_heater", "set_temperature",
                    {"entity_id": self.entity_id, "temperature": self.min_temperature},
                    blocking=True,
                )
            except Exception as e:
                _LOGGER.error("Failed to deactivate water_heater: %s", e)
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0

    async def _activate_climate(self) -> float:
        """Activate via climate domain."""
        try:
            target = self._active_target_temp()
            await self.hass.services.async_call(
                "climate", "set_temperature",
                {"entity_id": self.entity_id, "temperature": target},
                blocking=True,
            )
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": self.entity_id, "hvac_mode": "heat"},
                blocking=True,
            )
            self._status.state = DeviceState.ACTIVE
            self._status.current_consumption_w = self.rated_power
            self._status.allocated_power_w = self.rated_power
            return self.rated_power
        except Exception as e:
            _LOGGER.error("Failed to activate climate for hot water: %s", e)
            return 0.0

    async def _deactivate_climate(self) -> None:
        """Deactivate via climate domain."""
        try:
            await self.hass.services.async_call(
                "climate", "set_hvac_mode",
                {"entity_id": self.entity_id, "hvac_mode": "off"},
                blocking=True,
            )
        except Exception as e:
            _LOGGER.error("Failed to deactivate climate for hot water: %s", e)
        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0

    # ─── Legionella Prevention ───────────────────────────────

    async def check_legionella_cycle(self) -> Optional[str]:
        """Check and execute Legionella prevention cycle.

        Called every coordinator cycle. Returns a status message or None.

        Logic:
        1. If tank naturally reached ≥60°C → record timestamp, no forced cycle
        2. If overdue (>interval hours) → force heat to target, hold, record
        3. If cycle active → check hold duration, complete when done

        Records which branch fired on ``self._last_legionella_path`` (#420):
        ``natural_achievement`` / ``hold_reached_target`` /
        ``hold_in_progress`` / ``heating_to_target`` / ``overdue_start`` /
        ``overdue_no_sensor`` / ``idle`` / ``vacation_paused`` /
        ``vacation_aborted`` (#594).

        #594 vacation: cycles are PAUSED — no disinfection activation while
        away. ``_last_legionella_time`` is deliberately NOT touched, so
        ``hours_since_legionella`` keeps accumulating; when the interval
        elapses during the vacation, the normal overdue branch fires on the
        first post-vacation cycle (run-on-return). An in-flight cycle is
        aborted cleanly once (deactivate, clear hold) and re-runs on return
        via the same overdue path.
        """
        temp = self.get_current_temperature()

        # 1. Natural achievement: solar heated to ≥60°C
        if temp is not None and temp >= DEFAULT_LEGIONELLA_MIN_TEMP and not self._legionella_cycle_active:
            self._last_legionella_time = dt_util.now()
            self._last_legionella_path = "natural_achievement"
            return None

        # 1b. Vacation pause (#594) — after the natural-achievement record
        # (a tank that reached 60°C anyway IS disinfected), before any
        # forced heating.
        if self.vacation:
            if self._legionella_cycle_active:
                self._legionella_cycle_active = False
                self._legionella_hold_start = None
                await self.deactivate()
                _LOGGER.info(
                    "Legionella cycle aborted: vacation mode active — "
                    "will re-run when vacation ends"
                )
                self._last_legionella_path = "vacation_aborted"
                return "legionella_vacation_paused"
            self._last_legionella_path = "vacation_paused"
            return "legionella_vacation_paused" if self.legionella_overdue else None

        # 2. Cycle in progress — check hold
        if self._legionella_cycle_active:
            if temp is not None and temp >= self.legionella_target_temp:
                if self._legionella_hold_start is None:
                    self._legionella_hold_start = dt_util.now()
                    _LOGGER.info(
                        "Legionella cycle: target %.0f°C reached, holding for %d min",
                        self.legionella_target_temp, self.legionella_hold_minutes,
                    )
                    self._last_legionella_path = "hold_reached_target"
                    return f"legionella_holding:{self.legionella_hold_minutes}"

                elapsed = (dt_util.now() - self._legionella_hold_start).total_seconds() / 60
                if elapsed >= self.legionella_hold_minutes:
                    # Cycle complete
                    self._legionella_cycle_active = False
                    self._legionella_hold_start = None
                    self._last_legionella_time = dt_util.now()
                    await self.deactivate()
                    _LOGGER.info("Legionella prevention cycle completed at %.0f°C", temp)
                    self._last_legionella_path = "hold_complete"
                    return "legionella_complete"
                self._last_legionella_path = "hold_in_progress"
                return "legionella_holding"
            else:
                # Still heating towards target
                self._last_legionella_path = "heating_to_target"
                return "legionella_heating"

        # 3. Check if overdue — start forced cycle
        if self.legionella_overdue:
            if temp is None:
                _LOGGER.warning("Legionella cycle overdue but no temperature sensor — skipping")
                self._last_legionella_path = "overdue_no_sensor"
                return "legionella_no_sensor"

            _LOGGER.info(
                "Legionella prevention: %.0f hours since last cycle (max %d), "
                "forcing heat to %.0f°C",
                self.hours_since_legionella,
                self.legionella_interval_hours,
                self.legionella_target_temp,
            )
            self._legionella_cycle_active = True
            self._legionella_hold_start = None
            # Force activate regardless of solar surplus
            await self.activate(self.rated_power)
            self._last_legionella_path = "overdue_start"
            return "legionella_started"

        self._last_legionella_path = "idle"
        return None

    def record_legionella_cycle(self, timestamp: Optional[datetime] = None) -> None:
        """Manually record a Legionella cycle (e.g. from storage restore)."""
        self._last_legionella_time = timestamp or dt_util.now()

    @property
    def legionella_hold_elapsed_minutes(self) -> Optional[float]:
        """Minutes elapsed in the current legionella hold, or None.

        Returns ``None`` when no hold is in progress. While a hold is
        running this surfaces ``elapsed_minutes`` so users can see
        progress against ``legionella_hold_minutes`` rather than just
        a binary ``legionella_cycle_active`` flag (#420).
        """
        if self._legionella_hold_start is None:
            return None
        delta = dt_util.now() - self._legionella_hold_start
        return round(delta.total_seconds() / 60, 1)

    @property
    def hours_since_legionella_or_none(self) -> Optional[float]:
        """Hours since last legionella cycle, ``None`` when never run.

        Companion to ``hours_since_legionella`` which returns a 999.0
        sentinel when ``_last_legionella_time`` is None. The sentinel
        is convenient for the overdue check (``999 > interval`` always
        fires) but leaks into sensors and ``to_dict``, making it
        indistinguishable from a genuinely very-stale reading. This
        property exposes the unambiguous ``None`` for diagnostics (#420).
        """
        if self._last_legionella_time is None:
            return None
        return round(self.hours_since_legionella, 1)

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "entity_domain": self._entity_domain,
            "current_temperature": self.get_current_temperature(),
            "solar_target_temp": self.solar_target_temp,
            "max_temperature": self.max_temperature,
            "min_temperature": self.min_temperature,
            "temperature_safe": self.is_temperature_safe(),
            "needs_heating": self.needs_heating(),
            "legionella_target_temp": self.legionella_target_temp,
            "legionella_interval_hours": self.legionella_interval_hours,
            "legionella_overdue": self.legionella_overdue,
            "legionella_cycle_active": self._legionella_cycle_active,
            "vacation": self.vacation,  # #594
            "vacation_dhw_surplus": self.vacation_dhw_surplus,  # #594
            "hours_since_legionella": round(self.hours_since_legionella, 1),
            "hours_since_legionella_or_none": self.hours_since_legionella_or_none,
            "legionella_hold_elapsed_minutes": self.legionella_hold_elapsed_minutes,
            "last_legionella_time": self._last_legionella_time.isoformat() if self._last_legionella_time else None,
            # #420 — telemetry surface (mirrors #359/#416 classifier_path
            # pattern). Each ``*_path`` string is set by the corresponding
            # method on every call; reading them tells users which branch
            # fired without needing a debug log.
            "legionella_path": self._last_legionella_path,
            "temperature_safety_path": self._last_temperature_safety_path,
            "temperature_reading_path": self._last_temperature_reading_path,
            "activation_path": self._last_activation_path,
            "deactivation_path": self._last_deactivation_path,
        })
        return d
