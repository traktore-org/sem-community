"""Utility ripple control signal support — OBSERVE ONLY.

Grid operators use ripple control signals (*Rundsteuerung*) to curtail
electric water heaters, heat pumps and other large loads during peak demand.
This module watches such a signal and reports it:

- reads the configured binary sensor
- detects rising/falling edges and counts activations per day
- publishes ``utility_signal_active`` / ``_source`` / ``_count_today``

**It does not shed anything.** SEM takes no action on the signal: the heat
pump keeps running and every surplus load keeps running. Wiring the shedding
is tracked in #664, which also has to settle whether a load running on your
own PV is covered by the block — that is contract- and operator-dependent,
not something this module can infer.

This docstring used to describe the shedding as though it happened, and
``update`` logged a WARNING claiming loads were being shed, while the
selection function that would have chosen them had no caller at all (#654).
A user with a ripple-control contract could have read that log and believed
SEM was complying. Nothing here may claim an action it does not take.
"""
import logging
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional

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
    solar_loads_exempt: bool = True

    # #427 — telemetry surface mirroring classifier_path / dampening_path
    # pattern. Tracks edge-detection branches that fire silently today.
    # ``block_path`` was removed with the dead blocking code (#654): a
    # diagnostic field that can only ever hold "uninitialized" is worse than
    # no field, because it reads as "nothing was blocked" rather than
    # "blocking does not exist".
    update_path: str = "uninitialized"
    signal_read_path: str = "uninitialized"

    def to_dict(self) -> Dict[str, Any]:
        return {
            "utility_signal_active": self.signal_active,
            "utility_signal_source": self.signal_source,
            "utility_signal_count_today": self.signal_count_today,
            # (#654) ``utility_loads_blocked`` was removed with the blocking
            # code. It could only ever have read "none", which a reader would
            # take as "the block ran and matched nothing" rather than "there
            # is no block".
            "utility_solar_exempt": self.solar_loads_exempt,
            # #427 — telemetry surface
            "utility_update_path": self.update_path,
            "utility_signal_read_path": self.signal_read_path,
        }


class UtilitySignalMonitor:
    """Monitors utility ripple control signals. Reports; does not act.

    There is no SurplusController integration — the previous version of this
    docstring claimed one and grep proved it absent (#654). Blocking devices
    on the signal is #664.
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

    @property
    def signal_data(self) -> UtilitySignalData:
        return self._data

    @property
    def is_signal_active(self) -> bool:
        """Check if utility signal is currently active.

        Sets ``self._data.signal_read_path`` to one of (#427):
        ``no_entity_configured`` / ``entity_missing`` / ``active`` /
        ``inactive``. Important: ``no_entity_configured`` is the
        silent-failure surface — SEM treats utility-signal as
        permanently inactive when no entity is configured, so users
        with a configuration mistake never see any blocking behavior.
        """
        if not self.signal_entity_id:
            self._data.signal_read_path = "no_entity_configured"
            return False

        state = self.hass.states.get(self.signal_entity_id)
        if state is None:
            self._data.signal_read_path = "entity_missing"
            return False
        if state.state in ("on", "true", "1", "active"):
            self._data.signal_read_path = "active"
            return True
        self._data.signal_read_path = "inactive"
        return False

    def update(self, solar_power_w: float = 0.0) -> UtilitySignalData:
        """Update signal status (called during coordinator update).

        Records the edge-detection branch on
        ``self._data.update_path`` (#427): ``signal_started`` /
        ``signal_ended`` / ``signal_continues_active`` /
        ``signal_continues_inactive``.
        """
        active = self.is_signal_active

        # Detect signal start
        if active and not self._was_active:
            self._data.last_signal_start = datetime.now()
            self._data.signal_count_today += 1
            self._data.signal_source = "ripple_control"
            self._data.update_path = "signal_started"
            # (#654) Says what SEM does, which is nothing. The old text —
            # "shedding non-critical loads" — described a feature that was
            # never wired (see the module docstring). WARNING is still the
            # right level: the user is inside a utility block window and
            # SEM is not acting on it, which is exactly what they need to
            # know to comply by other means.
            _LOGGER.warning(
                "Utility ripple control signal ACTIVE — SEM is reporting it "
                "only; no loads are being shed (see #664)"
            )
        # Detect signal end
        elif not active and self._was_active:
            self._data.last_signal_end = datetime.now()
            self._data.update_path = "signal_ended"
            _LOGGER.info("Utility ripple control signal ended")
        elif active:
            self._data.update_path = "signal_continues_active"
        else:
            self._data.update_path = "signal_continues_inactive"

        self._was_active = active
        self._data.signal_active = active

        return self._data

    # (#654) ``get_devices_to_block`` lived here. It chose which devices to
    # shed during a signal — and nothing ever called it, so its result was
    # never acted on and its ``block_path`` telemetry could only ever read
    # "uninitialized". Deleted rather than kept: dead code that looks
    # finished is what made this feature read as shipped for eight releases.
    # #664 re-adds a selection pass together with the wiring that uses it,
    # and with the solar-exemption question actually decided.

    def reset_daily_counters(self) -> None:
        """Reset daily counters (called at day rollover)."""
        self._data.signal_count_today = 0
