"""Hot water diverter controller for Solar Energy Management.

Simple relay-based control for hot water heating:
- Surplus available -> turn on relay (heat water)
- Surplus drops -> turn off relay (stop heating)
- Temperature safety cutoff (max temperature protection)
- Temperature monitoring via HA sensor

Supports: myPV, Shelly relay, ESPHome relay, or any switch entity.
"""
import logging
from datetime import datetime
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant

from .base import SwitchDevice, DeviceState

_LOGGER = logging.getLogger(__name__)

DEFAULT_MAX_TEMPERATURE = 60.0  # Safety cutoff
DEFAULT_MIN_TEMPERATURE = 40.0  # Minimum useful temperature
DEFAULT_HOT_WATER_POWER = 2000  # Typical immersion heater power


class HotWaterController(SwitchDevice):
    """Hot water diverter with temperature monitoring and safety cutoff.

    Implements SwitchDevice interface — turns on when surplus is available,
    turns off when surplus drops. Adds temperature-based safety logic.

    Typical priority: heat pump(4) > hot water(5-6) > EV(7)
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

    def get_current_temperature(self) -> Optional[float]:
        """Read water temperature from sensor."""
        if not self.temperature_entity_id:
            return None
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
        return temp < self.max_temperature

    def needs_heating(self) -> bool:
        """Check if water temperature is below minimum."""
        temp = self.get_current_temperature()
        if temp is None:
            return True  # No sensor — assume needs heating
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
                self.max_temperature,
            )
            return 0.0

        return await super().activate(available_watts)

    async def deactivate(self) -> None:
        """Deactivate hot water heating."""
        await super().deactivate()

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "current_temperature": self.get_current_temperature(),
            "max_temperature": self.max_temperature,
            "min_temperature": self.min_temperature,
            "temperature_safe": self.is_temperature_safe(),
            "needs_heating": self.needs_heating(),
        })
        return d
