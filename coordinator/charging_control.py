"""Charging control module for SEM coordinator.

This module manages the dual state machine for EV charging mode selection:
- Solar charging (day mode): surplus-only, battery-assist, or Min+PV
- Night charging (night mode): NT-window-aware, latest-start planning,
  forecast-aware target reduction, dynamic peak-aware current

The state machine only decides IF and WHICH mode to charge in.
Actual KEBA commands are sent through CurrentControlDevice (devices/base.py).

ChargingContext carries all decision inputs including night-specific fields
(nt_period_active, night_end_time, ev_max_power_w, night_target_kwh).
"""
import logging
from typing import Dict, Any, Optional
from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..const import (
    ChargingState,
    DEFAULT_BATTERY_PRIORITY_SOC,
    DEFAULT_DAILY_EV_TARGET,
)
from ..utils.time_manager import TimeManager

_LOGGER = logging.getLogger(__name__)


@dataclass
class ChargingContext:
    """Context data for charging decisions.

    Built by SEMCoordinator._build_charging_context() each cycle and passed
    to ChargingStateMachine.update_state() for mode selection.

    Attributes:
        ev_connected: EV plug detected.
        ev_charging: EV currently drawing power.
        battery_soc: Home battery state of charge (%).
        battery_too_low: SOC below minimum threshold (EV blocked).
        battery_needs_priority: SOC below priority threshold (surplus → battery first).
        calculated_current: EV budget expressed as current (A), from FlowCalculator.
        excess_solar: Solar minus home minus battery charge (W), can be negative.
        available_power: EV power budget (W), from FlowCalculator.calculate_ev_budget().
        daily_target_reached: Daily EV energy >= configured target.
        daily_ev_energy: Today's accumulated EV energy (kWh).
        daily_ev_energy_offset: EV energy from offset utility meter (kWh), 0 if unused.
        remaining_ev_energy: Raw remaining EV need: daily_target - daily_ev (kWh).
        charging_strategy: Strategy from SOC zone logic — one of:
            "solar_only", "battery_assist", "night_grid", "min_pv", "idle".
        charging_strategy_reason: Human-readable explanation of strategy choice.
        night_target_kwh: Night charging target (kWh), may be forecast-adjusted if enabled.
    """
    # EV status
    ev_connected: bool = False
    ev_charging: bool = False

    # Battery status
    battery_soc: float = 0.0
    battery_too_low: bool = False
    battery_needs_priority: bool = False

    # Power calculations
    calculated_current: float = 0.0
    excess_solar: float = 0.0
    available_power: float = 0.0

    # Targets
    daily_target_reached: bool = False
    daily_ev_energy: float = 0.0
    daily_ev_energy_offset: float = 0.0
    remaining_ev_energy: float = 0.0

    # Mode flags
    charging_strategy: str = "idle"
    charging_strategy_reason: str = ""

    # Night charging context
    night_target_kwh: float = 0


class ChargingStateMachine:
    """Dual state machine for solar and night charging modes."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any], time_manager: TimeManager):
        """Initialize charging state machine."""
        self.hass = hass
        self.config = config
        self.time_manager = time_manager

        # State tracking
        self._current_state = ChargingState.IDLE
        self._last_charging_current: float = 0.0

        # Session tracking for solar mode
        self._battery_initial_check_done = False
        self._ev_session_allowed = False

        # Delta for current changes (avoid flapping)
        self.current_delta = config.get("current_delta", 1)

    @property
    def current_state(self) -> str:
        """Get current charging state."""
        return self._current_state

    @property
    def last_charging_current(self) -> float:
        """Get last applied charging current."""
        return self._last_charging_current

    def update_state(self, context: ChargingContext) -> str:
        """Update charging state based on context.

        Routes to the appropriate state machine based on time of day.
        """
        if self.time_manager.is_night_mode():
            new_state = self._night_state_machine(context)
        else:
            new_state = self._solar_state_machine(context)

        old_state = self._current_state
        self._current_state = new_state

        if old_state != new_state:
            _LOGGER.info(f"Charging state changed: {old_state} -> {new_state}")

        return new_state

    def _solar_state_machine(self, ctx: ChargingContext) -> str:
        """Solar EV charging state machine — active from sunrise to sunset.

        Decision priority:
        1. EV not connected → SOLAR_IDLE
        2. Battery too low → SOLAR_PAUSE_LOW_BATTERY
        3. Min+PV strategy → SOLAR_MIN_PV
        4. Target reached (low surplus) → SOLAR_TARGET_REACHED
        5. Battery-assist strategy → SOLAR_SUPER_CHARGING (battery-assisted solar)
        6. Battery priority gate → SOLAR_WAITING_BATTERY_PRIORITY
        7. Surplus available → SOLAR_CHARGING_ACTIVE
        8. Waiting → SOLAR_CHARGING_ALLOWED or SOLAR_WAITING_BATTERY_PRIORITY

        Args:
            ctx: Charging context with strategy, battery, and power data.

        Returns:
            ChargingState string for the current cycle.
        """
        # Check EV connection first
        if not ctx.ev_connected:
            self._battery_initial_check_done = False
            self._ev_session_allowed = False
            return ChargingState.SOLAR_IDLE

        # Battery too low - critical safety check
        if ctx.battery_too_low:
            _LOGGER.info(f"Solar: Paused - battery too low ({ctx.battery_soc:.0f}%)")
            return ChargingState.SOLAR_PAUSE_LOW_BATTERY

        # Now mode: charge at max immediately
        if ctx.charging_strategy == "now":
            return ChargingState.SOLAR_MIN_PV  # Reuse Min+PV path (grid + surplus)

        # Min+PV mode: guarantee minimum from grid, add solar surplus on top
        if ctx.charging_strategy == "min_pv":
            return ChargingState.SOLAR_MIN_PV

        # Daily target only limits night (grid) charging, not solar.
        # Solar surplus is free — always charge if available.

        # Battery-assisted mode: forecast says solar won't cover EV need,
        # but battery can bridge the deficit.
        if ctx.charging_strategy == "battery_assist":
            self._battery_initial_check_done = True
            self._ev_session_allowed = True
            return ChargingState.SOLAR_SUPER_CHARGING

        # Initial battery check for normal solar charging (surplus-only)
        battery_priority_soc = self.config.get("battery_priority_soc", DEFAULT_BATTERY_PRIORITY_SOC)
        if not self._battery_initial_check_done:
            if ctx.battery_soc >= battery_priority_soc:
                self._battery_initial_check_done = True
                self._ev_session_allowed = True
                _LOGGER.info(
                    f"Solar: Battery priority met ({ctx.battery_soc:.0f}% >= {battery_priority_soc}%), "
                    f"EV session allowed"
                )
            else:
                _LOGGER.debug(
                    f"Solar: Waiting for battery priority ({ctx.battery_soc:.0f}% < {battery_priority_soc}%)"
                )
                return ChargingState.SOLAR_WAITING_BATTERY_PRIORITY

        # Normal solar charging — pure surplus from SurplusController
        if ctx.calculated_current > 0:
            if (self._ev_session_allowed or
                (self._current_state == ChargingState.SOLAR_CHARGING_ACTIVE and
                 not ctx.battery_needs_priority)):
                return ChargingState.SOLAR_CHARGING_ACTIVE

        # Waiting for better solar conditions
        _LOGGER.debug(
            f"Solar: Waiting — calculated_current={ctx.calculated_current:.1f}A, "
            f"excess_solar={ctx.excess_solar:.0f}W, "
            f"battery_soc={ctx.battery_soc:.0f}%, "
            f"session_allowed={self._ev_session_allowed}, "
            f"daily_ev={ctx.daily_ev_energy:.1f}kWh, "
            f"target_reached={ctx.daily_target_reached}"
        )
        if self._ev_session_allowed:
            return ChargingState.SOLAR_CHARGING_ALLOWED
        return ChargingState.SOLAR_WAITING_BATTERY_PRIORITY

    def _night_state_machine(self, ctx: ChargingContext) -> str:
        """Night charging state machine.

        Starts charging immediately when night mode is active (no solar production).
        Night mode is gated by is_night_mode() in _determine_charging_strategy().
        """
        if not ctx.ev_connected:
            return ChargingState.NIGHT_IDLE

        # Check if night charging is enabled
        night_charging_entity = "switch.sem_night_charging"
        if not self.hass.states.is_state(night_charging_entity, "on"):
            return ChargingState.NIGHT_DISABLED

        remaining_needed = ctx.night_target_kwh

        _LOGGER.debug(
            "Night charging: remaining=%.1fkWh",
            remaining_needed,
        )

        if remaining_needed <= 0.1:
            return ChargingState.NIGHT_TARGET_REACHED

        return ChargingState.NIGHT_CHARGING_ACTIVE

    def reset_session(self) -> None:
        """Reset session tracking for new charging session."""
        self._battery_initial_check_done = False
        self._ev_session_allowed = False
        self._current_state = ChargingState.IDLE


