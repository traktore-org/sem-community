"""Utility ripple control signal support.

Monitors utility grid operator signals for load reduction:
- Binary sensor for ripple control signal (utility signal)
- When utility signals load reduction: shed non-critical loads
- Allow continued EV charging from solar even during utility shedding
  (don't shed solar-powered loads)

Grid operators use ripple control signals to control
electric water heaters, heat pumps, and other large loads during
peak demand periods.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


@dataclass
class UtilitySignalData:
    """Utility signal status."""
    signal_active: bool = False
    signal_entity: Optional[str] = None
    signal_source: str = "none"
    last_signal_start: Optional[datetime] = None
    last_signal_end: Optional[datetime] = None
    signal_count_today: int = 0
    loads_blocked: List[str] = None
    solar_loads_exempt: bool = True

    def __post_init__(self):
        if self.loads_blocked is None:
            self.loads_blocked = []

    def to_dict(self) -> Dict[str, Any]:
        return {
            "utility_signal_active": self.signal_active,
            "utility_signal_source": self.signal_source,
            "utility_signal_count_today": self.signal_count_today,
            "utility_loads_blocked": ", ".join(self.loads_blocked) if self.loads_blocked else "none",
            "utility_solar_exempt": self.solar_loads_exempt,
        }


class UtilitySignalMonitor:
    """Monitors utility ripple control signals and manages load blocking.

    Integrates with SurplusController to block/unblock devices when
    the utility sends a load reduction signal.
    """

    def __init__(
        self,
        hass: HomeAssistant,
        signal_entity_id: Optional[str] = None,
        solar_loads_exempt: bool = True,
    ):
        self.hass = hass
        self.signal_entity_id = signal_entity_id
        self.solar_loads_exempt = solar_loads_exempt
        self._data = UtilitySignalData(
            signal_entity=signal_entity_id,
            solar_loads_exempt=solar_loads_exempt,
        )
        self._was_active = False
        self._blocked_devices: List[str] = []

    @property
    def signal_data(self) -> UtilitySignalData:
        return self._data

    @property
    def is_signal_active(self) -> bool:
        """Check if utility signal is currently active."""
        if not self.signal_entity_id:
            return False

        state = self.hass.states.get(self.signal_entity_id)
        if state and state.state in ("on", "true", "1", "active"):
            return True
        return False

    def update(self, solar_power_w: float = 0.0) -> UtilitySignalData:
        """Update signal status (called during coordinator update)."""
        active = self.is_signal_active

        # Detect signal start
        if active and not self._was_active:
            self._data.last_signal_start = datetime.now()
            self._data.signal_count_today += 1
            self._data.signal_source = "ripple_control"
            _LOGGER.warning(
                "Utility ripple control signal ACTIVE — shedding non-critical loads"
            )

        # Detect signal end
        if not active and self._was_active:
            self._data.last_signal_end = datetime.now()
            _LOGGER.info("Utility ripple control signal ended")

        self._was_active = active
        self._data.signal_active = active

        return self._data

    def get_devices_to_block(
        self,
        all_device_ids: List[str],
        solar_powered_device_ids: List[str],
    ) -> List[str]:
        """Get list of devices that should be blocked during signal.

        If solar_loads_exempt is True, devices currently powered by solar
        are allowed to continue operating.
        """
        if not self.is_signal_active:
            return []

        blocked = []
        for device_id in all_device_ids:
            if self.solar_loads_exempt and device_id in solar_powered_device_ids:
                continue
            blocked.append(device_id)

        self._data.loads_blocked = blocked
        return blocked

    def reset_daily_counters(self) -> None:
        """Reset daily counters (called at day rollover)."""
        self._data.signal_count_today = 0
