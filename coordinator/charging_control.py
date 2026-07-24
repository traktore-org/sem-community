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
from __future__ import annotations

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
        available_power: EV power budget (W), from
            FlowCalculator.calculate_canonical_ev_budget().net_w (the
            unified per-cycle canonical budget — Phase D.2 / v1.6.2).
        daily_target_reached: Remaining EV need <= 0.1 kWh (SOC-based or kWh-based).
        daily_ev_energy: Today's accumulated EV energy (kWh).
        daily_ev_energy_offset: EV energy from offset utility meter (kWh), 0 if unused.
        remaining_ev_energy: Remaining EV need (kWh), from vehicle SOC or daily target.
        charging_strategy: Strategy from SOC zone logic — one of:
            "solar_only", "battery_assist", "night_grid", "idle",
            "disabled". ``"disabled"`` is the explicit-off intent
            (charge_mode=off) and routes the state machine to
            SOLAR_IDLE → actuator stop_session(); ``"idle"`` is the
            transient pause (Zone 1, solar<200W, target met) which
            stays in CHARGING_ALLOWED (warm, waiting for surplus).
            The legacy ``"min_pv"`` + ``"now"`` values were retired
            in #305 (producer) and #308 (consumer).
        charging_strategy_reason: Human-readable explanation of strategy choice.
        night_target_kwh: Night charging target (kWh), may be forecast-adjusted if enabled.
            For night mode, remaining is derived from this field directly.
        soc_limit_active: When True, stop surplus (solar) charging (#245).
            Set when the Max ceiling is reached (remaining-to-Max <= 0.1). Max
            defaults to full, so by default this only fires at car-full.
            Only gates the solar state machine — night mode uses night_target_kwh directly.
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

    # Canonical strategy (EVBudgetStrategy.value string) — the input the
    # canonical EV budget calc consumed in this cycle. Distinct from
    # ``charging_strategy`` (which is now the ChargerIntent enum value
    # post arch-rewrite — "idle" / "charge_at_amps" / "charge_max" /
    # "disable" — the actuator command). The canonical strategy is the
    # *intent* in EV-budget terms ("solar_only" / "battery_assist" /
    # "self_consumption" / "now" / "min_pv" / "idle"). Exposed so the
    # scenario harness and any future consumer can pin the budget-input
    # decision without re-deriving the mapping (the v1.6.2 vacuous-pass
    # class). Default "idle" mirrors ``charging_strategy``.
    canonical_strategy: str = "idle"

    # Night charging context
    night_target_kwh: float = 0

    # Surplus limit: when True, stop ALL charging (including surplus) at target
    soc_limit_active: bool = False

    # Target-time deadline (#246) + tariff-optimized timing (#247).
    # night_deadline_amps: current floor (A) to reach Min by the deadline (0 = none).
    # night_deadline_active: deadline is forcing current above the gentle ramp.
    # night_tariff_wait: tariff mode wants to idle now and charge in a cheaper window.
    # night_deadline_reachable: Min can still be met by the deadline at max current.
    night_deadline_amps: int = 0
    # (#630) peak-managed plain top-up rate (0 = fall back to Min floor).
    night_top_up_amps: int = 0
    night_deadline_active: bool = False
    night_tariff_wait: bool = False
    night_deadline_reachable: bool = True


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

        # Night-charging-enabled debounce state (#290). The raw vote (sum-of-
        # per-charger-switches) can transiently flip during HA-internal races
        # right after a config entry update — observed live on PROD 2026-05-29
        # 21:47 UTC as a one-cycle ``NIGHT_CHARGING_ACTIVE → NIGHT_DISABLED →
        # NIGHT_CHARGING_ACTIVE`` blip immediately after a slider write. Require
        # 2 consecutive cycles of the new value before flipping the cached
        # state we actually return. Trades 10 s of responsiveness for race
        # immunity — well worth it; this gate is checked once per 10 s cycle
        # anyway, so 10 s of extra latency is one cycle.
        self._night_enabled_cached: Optional[bool] = None  # last committed value
        self._night_enabled_pending: Optional[bool] = None  # value awaiting confirm
        self._night_enabled_pending_cycles: int = 0

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

        # Explicit-off intent (charge_mode=off → strategy="disabled")
        # terminates the session rather than holding in CHARGING_ALLOWED
        # with budget=0. Distinct from generic "idle" (which can be
        # transient — Zone 1 battery priority, solar<200W, target met).
        # Observed during the v1.6.3 PROD soak: KEBA's contactor stayed
        # closed when only the setpoint was zeroed, because the actuator's
        # CHARGING_ALLOWED path never calls stop_session(). SOLAR_IDLE
        # routes through ev_control.py's TERMINAL STATES branch which
        # invokes stop_session() → keba.disable. Matches the not-connected
        # reset above so a later mode flip back to a charging mode replays
        # the normal enable-delay warmup.
        if ctx.charging_strategy == "disabled":
            self._battery_initial_check_done = False
            self._ev_session_allowed = False
            return ChargingState.SOLAR_IDLE

        # Battery too low - critical safety check
        if ctx.battery_too_low:
            _LOGGER.info(f"Solar: Paused - battery too low ({ctx.battery_soc:.0f}%)")
            return ChargingState.SOLAR_PAUSE_LOW_BATTERY

        # Surplus ceiling — stop solar charging once the Max ceiling is reached (#245).
        # Night mode does NOT need this gate — it stops via night_target_kwh <= 0.1
        # (the Min floor), already SOC-aware through _calculate_remaining_need().
        if ctx.soc_limit_active:
            return ChargingState.SOLAR_TARGET_REACHED

        # The ``"now"`` and ``"min_pv"`` consumer branches were dropped in
        # v1.6.10 (#308). Post-#305 the strategy producer
        # ``_determine_charging_strategy`` only emits ``solar_only`` /
        # ``battery_assist`` / ``night_grid`` / ``idle`` / ``disabled`` —
        # neither ``"now"`` nor ``"min_pv"`` is reachable in production.
        # ``ChargingState.SOLAR_MIN_PV`` is still alive via the
        # ``night_grid`` → ``EVBudgetStrategy.MIN_PV`` mapping in the
        # canonical-budget producer.

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

    def _any_night_charging_enabled(self) -> bool:
        """True if night charging is enabled for at least one charger (#255).

        Per-charger switches are canonical. With no chargers configured
        (legacy), fall back to the removed-elsewhere global
        ``switch.sem_night_charging``.

        Debounced (#290): the raw vote can transiently flip during
        HA-internal races right after a config entry update — observed
        live on PROD 2026-05-29 21:47 UTC as a one-cycle
        ``NIGHT_CHARGING_ACTIVE → NIGHT_DISABLED → NIGHT_CHARGING_ACTIVE``
        blip immediately after a slider write. Require 2 consecutive
        cycles of the new value before flipping the cached state.
        """
        raw = self._read_night_enabled_raw()

        # First call after init — commit immediately, no debounce needed.
        if self._night_enabled_cached is None:
            self._night_enabled_cached = raw
            self._night_enabled_pending = None
            self._night_enabled_pending_cycles = 0
            return raw

        # Vote agrees with cached — reset any pending counter and return.
        if raw == self._night_enabled_cached:
            self._night_enabled_pending = None
            self._night_enabled_pending_cycles = 0
            return self._night_enabled_cached

        # Vote disagrees with cached. Start (or continue) the confirm window.
        if raw == self._night_enabled_pending:
            self._night_enabled_pending_cycles += 1
        else:
            self._night_enabled_pending = raw
            self._night_enabled_pending_cycles = 1

        # 2 consecutive cycles of disagreement → flip.
        if self._night_enabled_pending_cycles >= 2:
            _LOGGER.info(
                "Night charging enabled state flipped: %s → %s (after 2-cycle debounce)",
                self._night_enabled_cached, raw,
            )
            self._night_enabled_cached = raw
            self._night_enabled_pending = None
            self._night_enabled_pending_cycles = 0

        # Until confirmed, keep returning the cached value.
        return self._night_enabled_cached

    def _read_night_enabled_raw(self) -> bool:
        """The raw per-cycle vote: True if any per-charger ``charge_mode``
        permits night/grid charging (``solar_plus_cheap`` / ``min_plus_solar``
        / ``always_max``). Pre-#277 Phase B this read the per-charger
        ``switch.sem_charger_<id>_night_charging`` directly; post-B, mode
        authority — the switch is a deprecated read-only mirror.

        Pre-EV / no-chargers installs (no ``ev_chargers`` in config) still
        consult the legacy global ``switch.sem_night_charging`` — those
        installs never went through the v4→v5 migration so they have no
        ``charge_mode`` to read. Removed in Phase C when the migration
        becomes mandatory.

        Separated from ``_any_night_charging_enabled`` so the debounce
        logic in the latter can call this without recursion, and so unit
        tests can drive each path independently.
        """
        from ..consts.ev_charge_modes import (
            MODE_NIGHT_ALLOWED,
            effective_charge_mode_for,
        )

        chargers = self.config.get("ev_chargers") or []
        if not chargers:
            # Pre-EV / no-chargers install: nothing to enable. The
            # legacy global ``switch.sem_night_charging`` was removed
            # in #277 Phase C, so there is no fallback to consult.
            return False
        def _night_capable(c):
            mode = effective_charge_mode_for(self.hass, self.config, c)
            if mode in MODE_NIGHT_ALLOWED:
                return True
            # (#634) solar_only joins the night lane ONLY when its "At least"
            # floor is set — the floor is the mode-independent guarantee
            # (overnight source auto-derives to GRID; floor 0 = classic
            # never-grids-at-night). Mirrors the #620 axis, no GUI surface.
            if mode == "solar_only":
                target = c.get("daily_ev_target")
                if target is None:
                    target = self.config.get("daily_ev_target", 0)
                try:
                    return float(target or 0) > 0.1
                except (TypeError, ValueError):
                    return False
            return False

        return any(_night_capable(c) for c in chargers if isinstance(c, dict))

    def _night_state_machine(self, ctx: ChargingContext) -> str:
        """Night charging state machine.

        Starts charging immediately when night mode is active (no solar production).
        Night mode is gated by is_night_mode() in _determine_charging_strategy().
        """
        if not ctx.ev_connected:
            return ChargingState.NIGHT_IDLE

        # Check if night charging is enabled (#255: per-charger is canonical — night
        # charging is on when ANY charger's per-charger switch is on; the per-charger
        # control loop then skips the chargers that are off. Falls back to the global
        # master switch only for legacy / no-charger installs.)
        if not self._any_night_charging_enabled():
            return ChargingState.NIGHT_DISABLED

        remaining_needed = ctx.night_target_kwh

        _LOGGER.debug(
            "Night charging: remaining=%.1fkWh",
            remaining_needed,
        )

        if remaining_needed <= 0.1:
            return ChargingState.NIGHT_TARGET_REACHED

        # Tariff-optimized (#247): idle until a cheap window. The Min floor is
        # still guaranteed before the deadline — the planner only sets this flag
        # when waiting can still meet Min in time (else it charges regardless).
        if ctx.night_tariff_wait:
            return ChargingState.TARIFF_WAITING_FOR_CHEAP

        return ChargingState.NIGHT_CHARGING_ACTIVE

    def reset_session(self) -> None:
        """Reset session tracking for new charging session."""
        self._battery_initial_check_done = False
        self._ev_session_allowed = False
        self._current_state = ChargingState.IDLE


