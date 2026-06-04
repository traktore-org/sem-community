"""Heat pump SG-Ready controller for Solar Energy Management.

Implements SG-Ready (Smart Grid Ready) standard for heat pump control:
- State 1 (00): BLOCKED - utility request to reduce consumption
- State 2 (01): NORMAL - standard operation
- State 3 (10): BOOST - recommended increased consumption (solar surplus)
- State 4 (11): FORCE_ON - forced maximum consumption (high surplus/cheap price)

Control is via two relay entities (Shelly/ESPHome) mapped to SG-Ready pins.
Temperature boost via climate entity for additional thermal storage.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from enum import IntEnum
from typing import Any, Dict, Optional

from homeassistant.core import HomeAssistant

from .base import SetpointDevice, DeviceState

_LOGGER = logging.getLogger(__name__)


class SGReadyState(IntEnum):
    """SG-Ready states per standard."""
    BLOCKED = 1      # 00 - Utility block
    NORMAL = 2       # 01 - Normal operation
    BOOST = 3        # 10 - Recommended increased consumption
    FORCE_ON = 4     # 11 - Forced maximum consumption


# Relay mapping: (relay1, relay2) for each SG-Ready state
SG_READY_RELAY_MAP = {
    SGReadyState.BLOCKED:  (False, False),  # 00
    SGReadyState.NORMAL:   (False, True),   # 01
    SGReadyState.BOOST:    (True, False),    # 10
    SGReadyState.FORCE_ON: (True, True),     # 11
}


@dataclass
class HeatPumpStatus:
    """Heat pump operational status."""
    sg_ready_state: SGReadyState = SGReadyState.NORMAL
    current_temperature: Optional[float] = None
    target_temperature: Optional[float] = None
    cop: Optional[float] = None  # Coefficient of Performance
    is_solar_boosted: bool = False
    boost_start_time: Optional[datetime] = None


class HeatPumpController(SetpointDevice):
    """SG-Ready heat pump controller.

    Registers as a SetpointDevice in the SurplusController.
    When surplus is available, switches to BOOST or FORCE_ON mode
    and optionally increases the temperature setpoint.

    Typical priority: battery(2) > heat pump(3-4) > EV(5)
    """

    def __init__(
        self,
        hass: HomeAssistant,
        device_id: str = "heat_pump",
        name: str = "Heat Pump",
        rated_power: float = 2000.0,
        priority: int = 4,
        min_power_threshold: float = 2000.0,
        relay1_entity_id: Optional[str] = None,
        relay2_entity_id: Optional[str] = None,
        climate_entity_id: Optional[str] = None,
        power_entity_id: Optional[str] = None,
        temperature_entity_id: Optional[str] = None,
        normal_setpoint: float = 21.0,
        boost_offset: float = 2.0,
        max_setpoint: float = 55.0,
        force_on_threshold: float = 5000.0,
        min_power_change_interval: float = 300.0,
        daily_min_runtime_sec: int = 0,
    ):
        super().__init__(
            hass=hass,
            device_id=device_id,
            name=name,
            rated_power=rated_power,
            priority=priority,
            min_power_threshold=min_power_threshold,
            climate_entity_id=climate_entity_id,
            power_entity_id=power_entity_id,
            normal_setpoint=normal_setpoint,
            boost_offset=boost_offset,
            max_setpoint=max_setpoint,
            min_power_change_interval=min_power_change_interval,
        )
        self.daily_min_runtime_sec = daily_min_runtime_sec
        self.relay1_entity_id = relay1_entity_id
        self.relay2_entity_id = relay2_entity_id
        self.temperature_entity_id = temperature_entity_id
        self.force_on_threshold = force_on_threshold
        self._hp_status = HeatPumpStatus()

        # #421 — telemetry surface mirroring #359/#416/#420
        # classifier_path / dampening_path / legionella_path patterns.
        # Each decision branch sets the corresponding ``*_path`` string
        # so the ``load_management_status`` sensor's ``devices`` dict
        # can publish them for self-diagnosis. No behavior change.
        self._last_activation_path: str = "uninitialized"
        self._last_deactivation_path: str = "uninitialized"
        self._last_relay_path: str = "uninitialized"
        self._last_temperature_reading_path: str = "uninitialized"
        self._last_offpeak_path: str = "uninitialized"

    @property
    def sg_ready_state(self) -> SGReadyState:
        return self._hp_status.sg_ready_state

    @property
    def hp_status(self) -> HeatPumpStatus:
        return self._hp_status

    @property
    def needs_offpeak_activation(self) -> bool:
        """Temperature-aware override: don't force-boost if already warm.

        Records the decision branch on ``self._last_offpeak_path`` (#421):
        ``parent_declines`` / ``already_warm_skip`` / ``activate``.
        """
        if not super().needs_offpeak_activation:
            self._last_offpeak_path = "parent_declines"
            return False
        temp = self.get_current_temperature()
        if temp is not None and temp >= self.max_setpoint - self.boost_offset:
            self._last_offpeak_path = "already_warm_skip"
            return False
        self._last_offpeak_path = "activate"
        return True

    async def activate(self, available_watts: float) -> float:
        """Activate heat pump in boost or force-on mode based on surplus.

        Records the SG-Ready branch on ``self._last_activation_path`` (#421):
        ``boost`` (surplus < force_on_threshold) or
        ``force_on`` (surplus >= threshold). Climate boost is composed via
        a ``+climate`` suffix when ``climate_entity_id`` is configured.
        """
        if available_watts >= self.force_on_threshold:
            target_state = SGReadyState.FORCE_ON
            self._last_activation_path = "force_on"
        else:
            target_state = SGReadyState.BOOST
            self._last_activation_path = "boost"

        await self._set_sg_ready_state(target_state)
        if self.climate_entity_id:
            self._last_activation_path += "+climate"

        # Also boost temperature setpoint if climate entity configured
        if self.climate_entity_id:
            await super().activate(available_watts)

        self._status.state = DeviceState.ACTIVE
        self._status.current_consumption_w = self.rated_power
        self._status.allocated_power_w = self.rated_power
        self._status.last_activated = datetime.now()
        self._status.activation_count += 1
        self._hp_status.is_solar_boosted = True
        self._hp_status.boost_start_time = datetime.now()

        _LOGGER.info(
            "Heat pump activated: SG-Ready=%s, surplus=%.0fW",
            target_state.name, available_watts,
        )
        return self.rated_power

    async def deactivate(self) -> None:
        """Return heat pump to normal operation.

        Sets ``self._last_deactivation_path = "normal"`` (#421).
        ``+climate`` suffix when climate boost is also reverted.
        """
        await self._set_sg_ready_state(SGReadyState.NORMAL)
        self._last_deactivation_path = "normal"

        # Restore normal temperature
        if self.climate_entity_id:
            await super().deactivate()
            self._last_deactivation_path += "+climate"

        self._status.state = DeviceState.IDLE
        self._status.current_consumption_w = 0.0
        self._status.allocated_power_w = 0.0
        self._status.last_deactivated = datetime.now()
        self._hp_status.is_solar_boosted = False

        _LOGGER.info("Heat pump returned to normal operation")

    async def block(self) -> None:
        """Block heat pump (utility signal / load shedding).

        Sets ``self._last_deactivation_path = "blocked"`` (#421).
        """
        await self._set_sg_ready_state(SGReadyState.BLOCKED)
        self._status.state = DeviceState.BLOCKED
        self._last_deactivation_path = "blocked"
        _LOGGER.info("Heat pump blocked by utility signal")

    async def unblock(self) -> None:
        """Unblock heat pump (return to normal).

        Sets ``self._last_deactivation_path = "unblocked"`` (#421).
        """
        await self._set_sg_ready_state(SGReadyState.NORMAL)
        self._status.state = DeviceState.IDLE
        self._last_deactivation_path = "unblocked"
        _LOGGER.info("Heat pump unblocked")

    async def _set_sg_ready_state(self, state: SGReadyState) -> None:
        """Set SG-Ready state via relay entities.

        Records the relay branch on ``self._last_relay_path`` (#421):
        ``both_relays`` / ``relay1_only`` / ``relay2_only`` /
        ``no_relays_configured`` / ``relay1_failed`` / ``relay2_failed``.
        The ``no_relays_configured`` path is the silent-failure surface
        — SG-Ready state mutates internally but no physical relay
        actuates. The audit's biggest finding.
        """
        relay1_on, relay2_on = SG_READY_RELAY_MAP[state]
        relay1_called = False

        if self.relay1_entity_id:
            service = "turn_on" if relay1_on else "turn_off"
            try:
                await self.hass.services.async_call(
                    "homeassistant", service,
                    {"entity_id": self.relay1_entity_id},
                    blocking=True,
                )
                relay1_called = True
            except Exception as e:
                _LOGGER.error("Failed to set SG-Ready relay 1: %s", e)
                self._last_relay_path = "relay1_failed"
                return

        if self.relay2_entity_id:
            service = "turn_on" if relay2_on else "turn_off"
            try:
                await self.hass.services.async_call(
                    "homeassistant", service,
                    {"entity_id": self.relay2_entity_id},
                    blocking=True,
                )
                if relay1_called:
                    self._last_relay_path = "both_relays"
                else:
                    self._last_relay_path = "relay2_only"
            except Exception as e:
                _LOGGER.error("Failed to set SG-Ready relay 2: %s", e)
                self._last_relay_path = "relay2_failed"
                return
        elif relay1_called:
            self._last_relay_path = "relay1_only"
        else:
            self._last_relay_path = "no_relays_configured"

        self._hp_status.sg_ready_state = state
        _LOGGER.debug("SG-Ready state set to %s", state.name)

    def get_current_temperature(self) -> Optional[float]:
        """Read current temperature from sensor.

        Records the source path on
        ``self._last_temperature_reading_path`` (#421).
        """
        if self.temperature_entity_id:
            state = self.hass.states.get(self.temperature_entity_id)
            if state and state.state not in ("unknown", "unavailable"):
                try:
                    val = float(state.state)
                    self._last_temperature_reading_path = "sensor"
                    return val
                except (ValueError, TypeError):
                    self._last_temperature_reading_path = "sensor_invalid"
            elif state:
                self._last_temperature_reading_path = "sensor_unavailable"
            else:
                self._last_temperature_reading_path = "sensor_missing"
        else:
            self._last_temperature_reading_path = "no_sensor_configured"
        return None

    def to_dict(self) -> Dict[str, Any]:
        d = super().to_dict()
        d.update({
            "sg_ready_state": self._hp_status.sg_ready_state.name,
            "sg_ready_value": self._hp_status.sg_ready_state.value,
            "is_solar_boosted": self._hp_status.is_solar_boosted,
            "current_temperature": self.get_current_temperature(),
            "force_on_threshold": self.force_on_threshold,
            # #421 — telemetry surface (mirrors #359/#416/#420 pattern).
            "activation_path": self._last_activation_path,
            "deactivation_path": self._last_deactivation_path,
            "relay_path": self._last_relay_path,
            "temperature_reading_path": self._last_temperature_reading_path,
            "offpeak_path": self._last_offpeak_path,
        })
        return d
