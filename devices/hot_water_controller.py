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

    def get_current_temperature(self) -> Optional[float]:
        """Read water temperature from sensor or entity attributes."""
        # For water_heater and climate: read from entity attributes
        if self._entity_domain in ("water_heater", "climate") and self.entity_id:
            state = self.hass.states.get(self.entity_id)
            if state:
                temp = state.attributes.get("current_temperature")
                if temp is not None:
                    try:
                        return float(temp)
                    except (ValueError, TypeError):
                        pass

        # For switch or fallback: use separate temperature sensor
        if self.temperature_entity_id:
            state = self.hass.states.get(self.temperature_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    return float(state.state)
                except (ValueError, TypeError):
                    pass
        return None

    def is_temperature_safe(self) -> bool:
        """Check if temperature is below safety cutoff."""
        temp = self.get_current_temperature()
        if temp is None:
            return True  # No sensor — allow operation (rely on thermostat)
        # During Legionella cycle, allow up to legionella target
        if self._legionella_cycle_active:
            return temp < self.legionella_target_temp
        return temp < self.max_temperature

    def needs_heating(self) -> bool:
        """Check if water temperature is below minimum."""
        temp = self.get_current_temperature()
        if temp is None:
            return True
        return temp < self.min_temperature

    @property
    def needs_offpeak_activation(self) -> bool:
        """Temperature-aware override: don't force-heat if already at max temp."""
        if not super().needs_offpeak_activation:
            return False
        if not self.is_temperature_safe():
            return False
        return True

    async def activate(self, available_watts: float) -> float:
        """Activate hot water heating with temperature safety check."""
        if not self.is_temperature_safe():
            _LOGGER.info(
                "Hot water at %.1f°C — above max %.1f°C, skipping",
                self.get_current_temperature() or 0,
                self.legionella_target_temp if self._legionella_cycle_active else self.max_temperature,
            )
            return 0.0

        # Use appropriate control method based on entity type
        if self._entity_domain == "water_heater":
            return await self._activate_water_heater()
        elif self._entity_domain == "climate":
            return await self._activate_climate()
        else:
            return await super().activate(available_watts)

    async def deactivate(self) -> None:
        """Deactivate hot water heating."""
        if self._entity_domain == "water_heater":
            await self._deactivate_water_heater()
        elif self._entity_domain == "climate":
            await self._deactivate_climate()
        else:
            await super().deactivate()

    async def _activate_water_heater(self) -> float:
        """Activate via water_heater domain."""
        try:
            target = self.legionella_target_temp if self._legionella_cycle_active else self.solar_target_temp
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
            target = self.legionella_target_temp if self._legionella_cycle_active else self.solar_target_temp
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
        """
        temp = self.get_current_temperature()

        # 1. Natural achievement: solar heated to ≥60°C
        if temp is not None and temp >= DEFAULT_LEGIONELLA_MIN_TEMP and not self._legionella_cycle_active:
            self._last_legionella_time = dt_util.now()
            return None

        # 2. Cycle in progress — check hold
        if self._legionella_cycle_active:
            if temp is not None and temp >= self.legionella_target_temp:
                if self._legionella_hold_start is None:
                    self._legionella_hold_start = dt_util.now()
                    _LOGGER.info(
                        "Legionella cycle: target %.0f°C reached, holding for %d min",
                        self.legionella_target_temp, self.legionella_hold_minutes,
                    )
                    return f"legionella_holding:{self.legionella_hold_minutes}"

                elapsed = (dt_util.now() - self._legionella_hold_start).total_seconds() / 60
                if elapsed >= self.legionella_hold_minutes:
                    # Cycle complete
                    self._legionella_cycle_active = False
                    self._legionella_hold_start = None
                    self._last_legionella_time = dt_util.now()
                    await self.deactivate()
                    _LOGGER.info("Legionella prevention cycle completed at %.0f°C", temp)
                    return "legionella_complete"
            else:
                # Still heating towards target
                return "legionella_heating"

        # 3. Check if overdue — start forced cycle
        if self.legionella_overdue:
            if temp is None:
                _LOGGER.warning("Legionella cycle overdue but no temperature sensor — skipping")
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
            return "legionella_started"

        return None

    def record_legionella_cycle(self, timestamp: Optional[datetime] = None) -> None:
        """Manually record a Legionella cycle (e.g. from storage restore)."""
        self._last_legionella_time = timestamp or dt_util.now()

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
            "hours_since_legionella": round(self.hours_since_legionella, 1),
            "last_legionella_time": self._last_legionella_time.isoformat() if self._last_legionella_time else None,
        })
        return d
