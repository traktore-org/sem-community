"""Battery discharge protection methods extracted from SEMCoordinator.

Mixin class providing battery discharge protection during night charging:
- Limits battery discharge to home consumption (prevents battery → EV)
- Restores full discharge when night charging ends
- Startup recovery for stale discharge limits after restart
"""
import logging
from typing import Optional

from ..const import ChargingState
from .types import PowerReadings

_LOGGER = logging.getLogger(__name__)


class BatteryProtectionMixin:
    """Battery discharge protection methods for SEMCoordinator.

    Expects the coordinator to have these attributes:
    - _battery_protection_active, _last_discharge_limit
    - config, hass
    """

    async def _restore_battery_discharge_limit_on_startup(self) -> None:
        """Restore battery discharge limit to max on startup if protection is not needed.

        After a restart, _battery_protection_active is False, so the normal
        deactivation path in _apply_battery_discharge_protection won't fire.
        This checks if the control entity is below max and restores it.
        """
        control_entity = self.config.get("battery_discharge_control_entity", "")
        max_discharge = self.config.get("battery_max_discharge_power", 5000)

        if not control_entity:
            return

        current_state = self.hass.states.get(control_entity)
        if current_state is None:
            return

        try:
            current_limit = float(current_state.state)
        except (ValueError, TypeError):
            return

        if current_limit < max_discharge:
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": control_entity, "value": max_discharge},
                blocking=True,
            )
            _LOGGER.info(
                "Startup: restored battery discharge limit from %dW to %dW",
                int(current_limit), max_discharge,
            )

    async def _apply_battery_discharge_protection(
        self, charging_state: str, power: PowerReadings
    ) -> Optional[float]:
        """Limit battery discharge to home consumption during night charging.

        Returns the discharge_limit if active, None otherwise.
        """
        protection_enabled = self.config.get("battery_discharge_protection_enabled", True)
        control_entity = self.config.get("battery_discharge_control_entity", "")
        max_discharge = self.config.get("battery_max_discharge_power", 5000)

        if not protection_enabled:
            return None

        is_night_charging = charging_state == ChargingState.NIGHT_CHARGING_ACTIVE
        ev_is_charging = power.ev_charging
        battery_hold_solar = self.config.get("battery_hold_solar_ev", False)

        # Check if protection should be active
        protection_active = False
        if is_night_charging and ev_is_charging:
            protection_active = True  # Always protect during night charging
        elif battery_hold_solar and ev_is_charging and charging_state in (
            ChargingState.SOLAR_CHARGING_ACTIVE,
            ChargingState.SOLAR_MIN_PV,
        ):
            protection_active = True  # Optionally protect during solar EV charging

        # DEACTIVATION: restore full discharge when protection not needed
        if not protection_active:
            if self._battery_protection_active:
                self._battery_protection_active = False
                self._last_discharge_limit = None
                if control_entity and self.hass.states.get(control_entity):
                    await self.hass.services.async_call(
                        "number", "set_value",
                        {"entity_id": control_entity, "value": max_discharge},
                        blocking=True,
                    )
                    _LOGGER.info("Battery protection OFF — restored to %dW", max_discharge)
            return None

        # ACTIVATION: limit discharge to home consumption (1:1)
        home_power = power.home_consumption_power
        discharge_limit = min(max(0, round(home_power)), max_discharge)

        significant_change = (
            self._last_discharge_limit is None
            or abs(discharge_limit - self._last_discharge_limit) >= 100
        )

        if control_entity and self.hass.states.get(control_entity):
            await self.hass.services.async_call(
                "number", "set_value",
                {"entity_id": control_entity, "value": discharge_limit},
                blocking=True,
            )
            self._battery_protection_active = True
            if significant_change:
                _LOGGER.info(
                    "Battery protection ON — discharge=%dW (home=%dW, max=%dW)",
                    discharge_limit, home_power, max_discharge,
                )

        self._last_discharge_limit = discharge_limit
        return discharge_limit
