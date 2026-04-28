"""Battery charge scheduler — decides when and how much to charge from grid.

The scheduler runs a daily decision (default 21:00) that:
1. Calculates energy deficit: expected consumption - corrected solar forecast
2. Converts deficit to target SOC
3. Performs break-even check: only charge if NT/efficiency < HT rate
4. Selects cheapest hours (dynamic tariff) or uses full NT window (static)
5. Issues forced charge commands via BatteryChargeAdapter
6. Monitors SOC and stops when target reached

Coordinates with EV night charging via shared peak limit.
"""
import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from .battery_charge_adapter import (
    BatteryChargeAdapter,
    ChargeCommand,
    ChargeCommandStatus,
    ChargeStatus,
)

_LOGGER = logging.getLogger(__name__)


class SchedulerState(Enum):
    """State of the battery charge scheduler."""

    IDLE = "idle"
    EVALUATING = "evaluating"
    SCHEDULED = "scheduled"
    WAITING_FOR_SLOT = "waiting_for_slot"
    CHARGING = "charging"
    TARGET_REACHED = "target_reached"
    NOT_NEEDED = "not_needed"
    NOT_PROFITABLE = "not_profitable"
    FAILED = "failed"


@dataclass
class SchedulerDecision:
    """Result of the daily charge evaluation."""

    state: SchedulerState
    target_soc: float = 0.0
    deficit_kwh: float = 0.0
    hours_needed: int = 0
    charge_windows: List[datetime] = field(default_factory=list)
    reason: str = ""
    evaluated_at: Optional[datetime] = None

    @property
    def should_charge(self) -> bool:
        """Whether the scheduler decided to charge."""
        return self.state in (SchedulerState.SCHEDULED, SchedulerState.WAITING_FOR_SLOT, SchedulerState.CHARGING)


@dataclass
class SchedulerConfig:
    """Configuration for the battery charge scheduler."""

    # Battery parameters
    battery_capacity_kwh: float = 10.0
    battery_usable_capacity_kwh: float = 9.5  # Accounting for min SOC
    battery_min_soc: float = 5.0  # Don't plan below this
    battery_max_charge_power_w: float = 5000.0
    roundtrip_efficiency: float = 0.92  # Round-trip (charge + discharge losses)

    # Scheduling parameters
    trigger_hour: int = 21  # Hour to run daily evaluation (0-23)
    trigger_minute: int = 0
    min_deficit_kwh: float = 2.0  # Don't bother charging less than this
    forecast_confidence: float = 0.8  # Safety margin on forecast (use 80%)
    max_target_soc: float = 95.0  # Never plan above this

    # Peak management
    peak_limit_w: float = 0.0  # 0 = no limit
    ev_priority: bool = True  # EV gets priority over battery in peak conflicts

    @classmethod
    def from_config(cls, config: dict) -> "SchedulerConfig":
        """Create from HA config entry options."""
        return cls(
            battery_capacity_kwh=config.get("battery_capacity_kwh", 10.0),
            battery_usable_capacity_kwh=config.get("battery_usable_capacity_kwh", 9.5),
            battery_min_soc=config.get("battery_min_soc", 5.0),
            battery_max_charge_power_w=config.get("battery_max_charge_power_w", 5000.0),
            roundtrip_efficiency=config.get("battery_roundtrip_efficiency", 0.92),
            trigger_hour=config.get("battery_precharge_trigger_hour", 21),
            trigger_minute=config.get("battery_precharge_trigger_minute", 0),
            min_deficit_kwh=config.get("battery_min_deficit_kwh", 2.0),
            forecast_confidence=config.get("battery_forecast_confidence", 0.8),
            max_target_soc=config.get("battery_max_target_soc", 95.0),
            peak_limit_w=config.get("peak_limit_w", 0.0),
            ev_priority=config.get("ev_priority_over_battery", True),
        )


class BatteryChargeScheduler:
    """Daily battery charge scheduler using forecast + tariff optimization.

    Lifecycle:
    - Created once when coordinator initializes
    - `evaluate()` called at trigger time (21:00) to make daily decision
    - `update()` called every coordinator cycle (~10s) to execute decision
    - `reset()` called when night ends or manually
    """

    def __init__(
        self,
        hass: HomeAssistant,
        adapter: BatteryChargeAdapter,
        scheduler_config: SchedulerConfig,
    ) -> None:
        self.hass = hass
        self._adapter = adapter
        self._config = scheduler_config
        self._decision: SchedulerDecision = SchedulerDecision(state=SchedulerState.IDLE)
        self._last_evaluation_date: Optional[datetime] = None
        self._charge_started_at: Optional[datetime] = None

    @property
    def decision(self) -> SchedulerDecision:
        """Current scheduler decision."""
        return self._decision

    @property
    def state(self) -> SchedulerState:
        """Current scheduler state."""
        return self._decision.state

    def evaluate(
        self,
        current_soc: float,
        forecast_tomorrow_kwh: float,
        expected_consumption_kwh: float,
        nt_rate: float,
        ht_rate: float,
        tariff_provider=None,
        correction_factor: float = 1.0,
    ) -> SchedulerDecision:
        """Run the daily charge evaluation.

        Args:
            current_soc: Current battery SOC (0-100%)
            forecast_tomorrow_kwh: Raw solar forecast for tomorrow
            expected_consumption_kwh: Expected daily consumption
            nt_rate: Night tariff rate (cost per kWh)
            ht_rate: Day tariff rate (cost per kWh)
            tariff_provider: Optional DynamicTariffProvider for cheapest-hour scheduling
            correction_factor: Forecast correction factor from ForecastTracker

        Returns:
            SchedulerDecision with the charge plan
        """
        now = dt_util.now()
        self._last_evaluation_date = now

        # Apply forecast correction and confidence margin
        corrected_forecast = forecast_tomorrow_kwh * correction_factor * self._config.forecast_confidence

        # Calculate energy deficit
        deficit_kwh = expected_consumption_kwh - corrected_forecast
        _LOGGER.debug(
            "Battery scheduler evaluation: consumption=%.1f kWh, forecast=%.1f kWh "
            "(raw=%.1f, correction=%.2f, confidence=%.0f%%), deficit=%.1f kWh",
            expected_consumption_kwh,
            corrected_forecast,
            forecast_tomorrow_kwh,
            correction_factor,
            self._config.forecast_confidence * 100,
            deficit_kwh,
        )

        # No deficit — solar covers consumption
        if deficit_kwh <= 0:
            self._decision = SchedulerDecision(
                state=SchedulerState.NOT_NEEDED,
                deficit_kwh=0.0,
                reason="Solar forecast covers expected consumption",
                evaluated_at=now,
            )
            return self._decision

        # Below minimum threshold
        if deficit_kwh < self._config.min_deficit_kwh:
            self._decision = SchedulerDecision(
                state=SchedulerState.NOT_NEEDED,
                deficit_kwh=deficit_kwh,
                reason=f"Deficit {deficit_kwh:.1f} kWh below threshold {self._config.min_deficit_kwh:.1f} kWh",
                evaluated_at=now,
            )
            return self._decision

        # Break-even check: is grid charging profitable?
        effective_nt_cost = nt_rate / self._config.roundtrip_efficiency
        if effective_nt_cost >= ht_rate:
            self._decision = SchedulerDecision(
                state=SchedulerState.NOT_PROFITABLE,
                deficit_kwh=deficit_kwh,
                reason=(
                    f"Not profitable: NT effective cost {effective_nt_cost:.3f}/kWh "
                    f">= HT rate {ht_rate:.3f}/kWh"
                ),
                evaluated_at=now,
            )
            return self._decision

        # Calculate target SOC
        soc_increase_needed = (deficit_kwh / self._config.battery_usable_capacity_kwh) * 100
        target_soc = min(
            self._config.max_target_soc,
            current_soc + soc_increase_needed,
        )

        # Already at or above target
        if current_soc >= target_soc - 1.0:  # 1% tolerance
            self._decision = SchedulerDecision(
                state=SchedulerState.NOT_NEEDED,
                target_soc=target_soc,
                deficit_kwh=deficit_kwh,
                reason=f"Already at target SOC ({current_soc:.0f}% >= {target_soc:.0f}%)",
                evaluated_at=now,
            )
            return self._decision

        # Calculate hours needed for charging
        actual_charge_kwh = (target_soc - current_soc) / 100 * self._config.battery_usable_capacity_kwh
        charge_power_kw = self._config.battery_max_charge_power_w / 1000
        hours_needed = max(1, int(actual_charge_kwh / charge_power_kw + 0.5))

        # Find cheapest hours if dynamic tariff available
        charge_windows: List[datetime] = []
        if tariff_provider and hasattr(tariff_provider, "find_cheapest_hours"):
            cheapest = tariff_provider.find_cheapest_hours(hours_needed, within_hours=12)
            charge_windows = [p.timestamp for p in cheapest]

        self._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=target_soc,
            deficit_kwh=deficit_kwh,
            hours_needed=hours_needed,
            charge_windows=charge_windows,
            reason=(
                f"Charge {actual_charge_kwh:.1f} kWh "
                f"({current_soc:.0f}% → {target_soc:.0f}%) "
                f"in {hours_needed}h"
            ),
            evaluated_at=now,
        )
        _LOGGER.info(
            "Battery charge scheduled: %s (windows: %s)",
            self._decision.reason,
            [w.strftime("%H:%M") for w in charge_windows] if charge_windows else "full NT",
        )
        return self._decision

    async def update(
        self,
        current_soc: float,
        ev_charging_power_w: float = 0.0,
    ) -> SchedulerState:
        """Called every coordinator cycle to execute the scheduled decision.

        Handles:
        - Waiting for the right time slot
        - Starting forced charge
        - Monitoring SOC and stopping when target reached
        - Peak limit coordination with EV

        Args:
            current_soc: Current battery SOC
            ev_charging_power_w: Current EV charging power (for peak coordination)

        Returns:
            Current scheduler state
        """
        if self._decision.state == SchedulerState.IDLE:
            return SchedulerState.IDLE

        if self._decision.state in (
            SchedulerState.NOT_NEEDED,
            SchedulerState.NOT_PROFITABLE,
            SchedulerState.FAILED,
        ):
            return self._decision.state

        # Check if target reached
        if current_soc >= self._decision.target_soc - 0.5:
            if self._adapter.is_active:
                await self._adapter.stop_forced_charge()
            self._decision.state = SchedulerState.TARGET_REACHED
            _LOGGER.info(
                "Battery charge target reached: SOC %.1f%% >= target %.1f%%",
                current_soc,
                self._decision.target_soc,
            )
            return SchedulerState.TARGET_REACHED

        # Determine if we should be charging right now
        now = dt_util.now()
        should_charge_now = self._is_in_charge_window(now)

        if should_charge_now and not self._adapter.is_active:
            # Calculate available power (respect peak limit)
            charge_power = self._calculate_available_charge_power(ev_charging_power_w)
            if charge_power <= 0:
                self._decision.state = SchedulerState.WAITING_FOR_SLOT
                return SchedulerState.WAITING_FOR_SLOT

            command = ChargeCommand(
                target_soc=self._decision.target_soc,
                max_power_w=charge_power,
                duration_minutes=self._decision.hours_needed * 60 + 30,  # +30min safety
            )
            status = await self._adapter.start_forced_charge(command)

            if status.status == ChargeCommandStatus.CHARGING:
                self._decision.state = SchedulerState.CHARGING
                self._charge_started_at = now
            else:
                self._decision.state = SchedulerState.FAILED
                self._decision.reason = status.message
                _LOGGER.error("Battery charge start failed: %s", status.message)

        elif not should_charge_now and self._adapter.is_active:
            # Outside charge window but still charging — stop
            await self._adapter.stop_forced_charge()
            self._decision.state = SchedulerState.WAITING_FOR_SLOT

        elif should_charge_now and self._adapter.is_active:
            self._decision.state = SchedulerState.CHARGING

        else:
            self._decision.state = SchedulerState.WAITING_FOR_SLOT

        return self._decision.state

    def _is_in_charge_window(self, now: datetime) -> bool:
        """Check if current time is within a scheduled charge window."""
        if not self._decision.charge_windows:
            # No specific windows = charge during entire NT period (assume we're in NT)
            return True

        for window_start in self._decision.charge_windows:
            window_end = window_start + timedelta(hours=1)
            if window_start <= now < window_end:
                return True

        return False

    def _calculate_available_charge_power(self, ev_power_w: float) -> float:
        """Calculate available battery charge power respecting peak limit.

        If peak_limit is configured and EV is charging:
        - EV gets priority (if configured) — battery gets remainder
        - Or proportional split
        """
        max_power = self._config.battery_max_charge_power_w

        if self._config.peak_limit_w <= 0:
            return max_power

        # Available = peak limit - EV consumption - safety margin
        available = self._config.peak_limit_w - ev_power_w - 200  # 200W safety

        if self._config.ev_priority:
            # EV takes what it needs, battery gets the rest
            return max(0, min(max_power, available))
        else:
            # Proportional: battery gets half of available
            return max(0, min(max_power, available * 0.5))

    def reset(self) -> None:
        """Reset scheduler to idle state (call when night ends)."""
        if self._adapter.is_active:
            _LOGGER.warning("Resetting scheduler while charge still active")
        self._decision = SchedulerDecision(state=SchedulerState.IDLE)
        self._charge_started_at = None

    def should_trigger_evaluation(self, now: Optional[datetime] = None) -> bool:
        """Check if it's time to run the daily evaluation.

        Returns True once per day at the configured trigger time.
        """
        if now is None:
            now = dt_util.now()

        if now.hour != self._config.trigger_hour or now.minute != self._config.trigger_minute:
            return False

        # Only trigger once per day
        if self._last_evaluation_date and self._last_evaluation_date.date() == now.date():
            return False

        return True
