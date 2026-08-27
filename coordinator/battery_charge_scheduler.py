"""Battery charge scheduler — decides when and how much to charge from grid.

The scheduler runs a rolling-horizon evaluation: the nightly
planning window opens at the trigger time (default 21:00) and the plan
is re-evaluated every ``replan_interval_min`` minutes until the window
closes (default 9 h later, 06:00). Each evaluation:
1. Calculates energy deficit: expected consumption - corrected solar forecast
2. Converts deficit to target SOC
3. Performs break-even check: only charge if night rate/efficiency +
   degradation cost < daytime rate (both derived from the actual
   day-ahead price series when a dynamic tariff is configured)
4. Selects the cheapest contiguous price window (dynamic tariff) or
   uses the full NT window (static)
5. Publishes SchedulerDecision — the battery pipeline actuates it (#624)
6. Monitors SOC and stops when target reached

Re-plans immediately on day-ahead price updates, SOC drift and EV
plug events. Coordinates with EV night charging via shared peak limit.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import Optional

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util


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
    DISCHARGING_ARBITRAGE = "discharging_arbitrage"
    """#523 — the scheduler decided to SELL stored energy to the grid
    this cycle (export price beats the recharge cost). The mirror of
    SCHEDULED: same price economics, opposite direction."""


@dataclass
class SchedulerDecision:
    """Result of the daily charge evaluation."""

    state: SchedulerState
    target_soc: float = 0.0
    deficit_kwh: float = 0.0
    hours_needed: int = 0
    discharge_power_w: float = 0.0
    """Used iff state == DISCHARGING_ARBITRAGE (#523) — battery→grid power."""
    floor_soc: float = 0.0
    """Used iff state == DISCHARGING_ARBITRAGE (#523) — reserve floor."""
    charge_power_w: float = 0.0
    """Used iff state == SCHEDULED — grid→battery charge power. decide_battery
    reads this to actuate FORCE_CHARGE; without it the scheduled charge would
    issue 0 W (B1). Populated from ``SchedulerConfig.battery_max_charge_power_w``."""
    duration_min: int = 60
    """Used iff state == SCHEDULED — force-charge safety timeout (minutes)."""
    from_arbitrage: bool = False
    """True for every verdict produced by ``evaluate_arbitrage`` (#533),
    firing or not. Lets ``decide_battery`` route the STOP correctly: an
    arbitrage non-firing verdict (not_profitable / not_needed-at-reserve) must
    STOP_FORCE_DISCHARGE, whereas the night scheduler's same-named states stop
    a force-CHARGE. Without this the stop relied on a Huawei-only coincidence
    (its stop-charge service also clears a forcible discharge)."""
    from_forecast_spend: bool = False
    """(#778) True on verdicts from ``evaluate_forecast_sell`` — the
    forecast-led spend trigger. decide_battery then checks the SPEND plan
    gate (``view.forecast_sell``) and the SPEND master switch
    (``forecast_spending_enabled``) instead of arbitrage's; everything
    else (floors, budget cap, permissions, fleet split) is shared."""
    price_forced: bool = False
    """(#638 one-gate C4) True only on the negative-price override —
    being PAID to consume is a reactive price gate, so decide_battery
    bypasses the plan gate for it. Every other SCHEDULED verdict
    force-charges only inside the joint plan's battery block."""
    reason: str = ""
    evaluated_at: Optional[datetime] = None

    @property
    def should_charge(self) -> bool:
        """Whether the scheduler decided to charge."""
        return self.state in (SchedulerState.SCHEDULED, SchedulerState.WAITING_FOR_SLOT, SchedulerState.CHARGING)


@dataclass
class SchedulerConfig:
    """Configuration for the battery charge scheduler."""

    # Feature toggle
    enabled: bool = False  # Off by default — user must opt in

    # Battery parameters
    battery_capacity_kwh: float = 10.0
    battery_usable_capacity_kwh: float = 9.5  # Accounting for min SOC
    battery_min_soc: float = 5.0  # Don't plan below this
    battery_max_charge_power_w: float = 5000.0
    roundtrip_efficiency: float = 0.92  # Round-trip (charge + discharge losses)

    # Degradation cost: battery_price / (capacity * 2 * rated_cycles)
    # Example LUNA2000 10kWh, 6000 cycles, 8000 EUR → 0.067 EUR/kWh
    # Runtime fallback is 0.0 (check disabled) so upgrading installs
    # that never set the key keep their pre-v1.7.3 break-even behavior
    # (#485 F5 — a silent 0.02 default flipped thin-margin nights to
    # NOT_PROFITABLE). New configs get 0.02 suggested in the form
    # (config_flow), where the value is visible before it applies.
    battery_cycle_cost: float = 0.0  # Cost per kWh throughput (half-cycle)

    # Scheduling parameters
    trigger_hour: int = 21  # Hour the nightly planning window opens (0-23)
    trigger_minute: int = 0
    min_deficit_kwh: float = 2.0  # Don't bother charging less than this
    forecast_confidence: float = 0.8  # Safety margin on forecast (use 80%)
    max_target_soc: float = 95.0  # Never plan above this

    # Rolling horizon: instead of a single 21:00 decision the
    # scheduler re-evaluates every ``replan_interval_min`` minutes for
    # ``planning_window_hours`` after the trigger time (21:00 → 06:00 by
    # default), picking up price updates, forecast refreshes and SOC
    # drift the way receding-horizon (MPC-style) schedulers do.
    replan_interval_min: int = 30
    planning_window_hours: int = 9

    # Block-wise cheapest-window selection (#247): charge in one
    # contiguous block instead of scattered cheapest slots — avoids
    # start/stop cycling on the inverter at slightly higher cost.
    prefer_consecutive_window: bool = True

    # Forecast fallback
    forecast_fallback_soc: float = 70.0  # Target SOC when forecast unavailable
    stale_forecast_hours: int = 6  # Hours before forecast considered stale
    pessimism_weight: float = 0.3  # 0.0 = trust forecast, 1.0 = full pessimistic

    # Re-plan triggers
    replan_soc_deviation_pct: float = 5.0  # Re-evaluate if SOC deviates this much
    replan_on_ev_change: bool = True  # Re-evaluate when EV connects/disconnects

    # Peak management
    peak_limit_w: float = 0.0  # 0 = no limit
    max_grid_import_w: float = 0.0  # 0 = no limit; cap total grid draw during charge
    # #604: internal planner knob — the legacy ``ev_priority_over_battery``
    # config key no longer feeds it (it was never reachable from any UI, so
    # this always held its default True; the v14→v15 migration deletes the
    # key). The list-based replacement is the unified device-priority list
    # (#576): the battery's list position vs the charger's, once the
    # battery's position is plumbed into this planner.
    ev_priority: bool = True  # EV gets priority over battery in peak conflicts

    # Negative tariff handling
    force_charge_on_negative_price: bool = True  # Always charge during negative prices

    # #523 — export arbitrage (battery → grid). The mirror of charge-on-
    # cheap: sell stored energy when the dynamic export price beats the
    # cost of recharging it later (reusing roundtrip_efficiency +
    # battery_cycle_cost). Opt-in; never sells below the reserve floor.
    arbitrage_enabled: bool = False
    arbitrage_min_export_price: float = 0.20  # /kWh floor worth cycling for
    arbitrage_reserve_soc: float = 50.0       # never sell below this SOC
    max_discharge_power_w: float = 5000.0     # battery→grid power when selling
    arbitrage_max_export_w: float = 0.0       # #533: cap the sell power so
    # arbitrage can't create a billed grid peak (capacity-tariff markets). 0 =
    # no cap. Defaults to the configured grid export limit (max_export_power).

    @classmethod
    def from_config(cls, config: dict) -> "SchedulerConfig":
        """Create from HA config entry options."""
        return cls(
            enabled=config.get("battery_charge_scheduler_enabled", False),
            battery_capacity_kwh=config.get("battery_capacity_kwh", 10.0),
            battery_usable_capacity_kwh=config.get("battery_usable_capacity_kwh", 9.5),
            battery_min_soc=config.get("battery_min_soc", 5.0),
            battery_max_charge_power_w=config.get("battery_max_charge_power_w", 5000.0),
            roundtrip_efficiency=config.get("battery_roundtrip_efficiency", 0.92),
            battery_cycle_cost=config.get("battery_cycle_cost", 0.0),
            # int(float()) coercion is load-bearing (#493): the
            # options-flow NumberSelector stores floats (21.0) and
            # datetime.replace(hour=21.0) raises TypeError — killing the
            # scheduler evaluation on every cycle for any user who ever
            # saved the battery-scheduler options page. The float() hop
            # also survives string-shaped storage ("21.0"), which a bare
            # int() would re-crash on with ValueError.
            trigger_hour=int(float(config.get("battery_precharge_trigger_hour", 21))),
            trigger_minute=int(float(config.get("battery_precharge_trigger_minute", 0))),
            replan_interval_min=max(5, int(config.get("battery_replan_interval_min", 30))),
            planning_window_hours=max(1, min(24, int(config.get("battery_planning_window_hours", 9)))),
            prefer_consecutive_window=config.get("battery_prefer_consecutive_window", True),
            min_deficit_kwh=config.get("battery_min_deficit_kwh", 2.0),
            forecast_confidence=config.get("battery_forecast_confidence", 0.8),
            max_target_soc=config.get("battery_max_target_soc", 95.0),
            forecast_fallback_soc=config.get("battery_forecast_fallback_soc", 70.0),
            stale_forecast_hours=config.get("battery_stale_forecast_hours", 6),
            pessimism_weight=config.get("battery_pessimism_weight", 0.3),
            replan_soc_deviation_pct=config.get("battery_replan_soc_deviation", 5.0),
            replan_on_ev_change=config.get("battery_replan_on_ev_change", True),
            # #693 — the cap must come from a key installs actually carry.
            # ``peak_limit_w`` was written by NOTHING (not the config flow,
            # not a migration), so the peak-aware slot distribution ran with
            # ``0 = no limit`` on every install. ``target_peak_limit`` is the
            # install-flow key, in kW (shared with load management).
            # (#716) An install that declared no grid ceiling seeds this
            # planner's own ``0 = no limit`` sentinel. The flag is translated
            # here rather than passed through: this dataclass field is
            # consumed by slot arithmetic that has no infinity handling, and
            # 0 is the no-limit value it already understands.
            peak_limit_w=0.0 if config.get(
                "peak_limit_unlimited", False
            ) else float(config.get("target_peak_limit", 0.0) or 0.0) * 1000.0,
            max_grid_import_w=config.get("battery_max_grid_import_w", 0.0),
            force_charge_on_negative_price=config.get("battery_force_charge_negative_price", True),
            arbitrage_enabled=config.get("battery_grid_arbitrage_enabled", False),
            arbitrage_min_export_price=config.get("battery_arbitrage_min_export_price", 0.20),
            arbitrage_reserve_soc=config.get("battery_arbitrage_reserve_soc", 50.0),
            max_discharge_power_w=config.get("battery_max_discharge_power", 5000.0),
            # #533: cap the arbitrage sell power. Explicit key wins; else fall
            # back to the grid export limit (max_export_power); 0 = uncapped.
            arbitrage_max_export_w=float(
                config.get("battery_arbitrage_max_export_w",
                           config.get("max_export_power", 0.0)) or 0.0
            ),
        )


class BatteryChargeScheduler:
    """Daily battery charge scheduler using forecast + tariff optimization.

    Lifecycle:
    - Created once when coordinator initializes
    - `evaluate()` called at trigger time (21:00) to make the daily
      charge decision; `evaluate_arbitrage()` mirrors it for discharge
    - The verdict is actuated through ``decide_battery`` /
      ``actuate_battery`` every coordinator cycle (~10s)
    - `reset()` called when night ends or manually
    """

    def __init__(
        self,
        hass: HomeAssistant,
        scheduler_config: SchedulerConfig,
    ) -> None:
        # (#624) The scheduler is a pure planner: it produces
        # SchedulerDecision; actuation belongs to the battery pipeline
        # (decide_battery -> actuate_battery -> BatteryControlAdapter).
        # The old standalone BatteryChargeAdapter dependency was
        # vestigial (its is_active was always False here).
        self.hass = hass
        self._config = scheduler_config
        self._decision: SchedulerDecision = SchedulerDecision(state=SchedulerState.IDLE)
        self._last_evaluation_date: Optional[datetime] = None
        self._charge_started_at: Optional[datetime] = None
        self._planned_soc: Optional[float] = None  # For re-plan deviation check
        self._last_ev_connected: Optional[bool] = None  # For re-plan on EV change
        self._price_fingerprint: Optional[int] = None  # For re-plan on price updates
        # Rolling-horizon anchor (#485 F1): the SOC at the FIRST
        # evaluation of the night's planning window. Re-evaluations
        # compute the charge target from this anchor, not from the
        # live SOC — otherwise every replan re-adds the full deficit
        # on top of the energy already grid-charged tonight and the
        # target ratchets toward max_target_soc.
        self._window_anchor_soc: Optional[float] = None
        self._window_anchor_at: Optional[datetime] = None

    @property
    def enabled(self) -> bool:
        """Whether the scheduler feature is enabled."""
        return self._config.enabled

    @property
    def decision(self) -> SchedulerDecision:
        """Current scheduler decision."""
        return self._decision

    @property
    def state(self) -> SchedulerState:
        """Current scheduler state."""
        return self._decision.state

    @property
    def has_price_fingerprint(self) -> bool:
        """Whether a price fingerprint was captured at evaluation time.

        The coordinator skips computing the live series fingerprint
        when there is nothing to compare it against (#485 F2).
        """
        return self._price_fingerprint is not None

    def evaluate(
        self,
        current_soc: float,
        forecast_tomorrow_kwh: float,
        expected_consumption_kwh: float,
        off_peak_rate: Optional[float],
        peak_rate: Optional[float],
        tariff_provider=None,
        correction_factor: float = 1.0,
        forecast_available: bool = True,
        forecast_age_hours: float = 0.0,
        current_price: float = 0.0,
    ) -> SchedulerDecision:
        """Run the daily charge evaluation.

        Args:
            current_soc: Current battery SOC (0-100%)
            forecast_tomorrow_kwh: Raw solar forecast for the upcoming solar day
            expected_consumption_kwh: Expected daily consumption
            off_peak_rate: Effective night charge rate per kWh (None = unknown)
            peak_rate: Effective daytime rate per kWh (None = unknown)
            tariff_provider: Optional DynamicTariffProvider for cheapest-hour scheduling
            correction_factor: Forecast correction factor from ForecastTracker
            forecast_available: Whether a solar forecast is available
            forecast_age_hours: How old the forecast is (hours since last update)
            current_price: Current electricity price (for negative tariff detection)

        Returns:
            SchedulerDecision with the charge plan
        """
        now = dt_util.now()
        self._last_evaluation_date = now

        # Anchor the night's target on the SOC at the first evaluation
        # of this planning window (#485 F1). Later re-evaluations keep
        # the anchor: fresh prices/forecasts can still change the plan,
        # but charging progress must not inflate the target.
        window_start = self._window_start(now)
        if self._window_anchor_at != window_start or self._window_anchor_soc is None:
            self._window_anchor_soc = current_soc
            self._window_anchor_at = window_start
        anchor_soc = self._window_anchor_soc

        # Capture the price-series fingerprint so should_replan() can
        # detect day-ahead price updates that arrive after this plan.
        self._price_fingerprint = None
        if tariff_provider is not None and hasattr(tariff_provider, "price_series_fingerprint"):
            try:
                self._price_fingerprint = tariff_provider.price_series_fingerprint()
            except (ValueError, TypeError, AttributeError):
                self._price_fingerprint = None

        # Feature toggle check
        if not self._config.enabled:
            self._decision = SchedulerDecision(
                state=SchedulerState.IDLE,
                reason="Battery charge scheduler is disabled",
                evaluated_at=now,
            )
            return self._decision

        # Negative tariff override — always charge during negative prices
        if (
            self._config.force_charge_on_negative_price
            and current_price < 0
            and current_soc < self._config.max_target_soc
        ):
            target_soc = self._config.max_target_soc
            actual_charge_kwh = (target_soc - current_soc) / 100 * self._config.battery_usable_capacity_kwh
            charge_power_kw = self._config.battery_max_charge_power_w / 1000
            hours_needed = max(1, int(actual_charge_kwh / charge_power_kw + 0.5))

            self._decision = SchedulerDecision(
                state=SchedulerState.SCHEDULED,
                target_soc=target_soc,
                deficit_kwh=actual_charge_kwh,
                hours_needed=hours_needed,
                charge_power_w=self._config.battery_max_charge_power_w,
                price_forced=True,
                reason=f"Negative price ({current_price:.3f}/kWh) — charging to {target_soc:.0f}%",
                evaluated_at=now,
            )
            self._planned_soc = current_soc
            return self._decision

        # Forecast fallback: 3-tier strategy
        effective_forecast = self._resolve_forecast(
            forecast_tomorrow_kwh,
            expected_consumption_kwh,
            correction_factor,
            forecast_available,
            forecast_age_hours,
        )

        # Calculate energy deficit
        deficit_kwh = expected_consumption_kwh - effective_forecast
        _LOGGER.debug(
            "Battery scheduler evaluation: consumption=%.1f kWh, forecast=%.1f kWh "
            "(raw=%.1f, correction=%.2f, confidence=%.0f%%, available=%s, age=%.1fh), "
            "deficit=%.1f kWh",
            expected_consumption_kwh,
            effective_forecast,
            forecast_tomorrow_kwh,
            correction_factor,
            self._config.forecast_confidence * 100,
            forecast_available,
            forecast_age_hours,
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

        # Price data missing — can't verify break-even, don't grid-charge
        # blind. The coordinator falls back to static config rates before
        # calling us, so this only fires when no rate is known at all
        # (previously a None rate crashed the division below).
        if off_peak_rate is None or peak_rate is None:
            self._decision = SchedulerDecision(
                state=SchedulerState.NOT_PROFITABLE,
                deficit_kwh=deficit_kwh,
                reason="Price data unavailable — cannot verify break-even, skipping grid charge",
                evaluated_at=now,
            )
            return self._decision

        # Break-even check: is grid charging profitable?
        # Include battery degradation cost: charge must save more than it wears
        effective_charge_cost = off_peak_rate / self._config.roundtrip_efficiency
        cycle_cost = self._config.battery_cycle_cost * 2  # Full cycle = 2x half-cycle
        total_charge_cost = effective_charge_cost + cycle_cost

        if total_charge_cost >= peak_rate:
            self._decision = SchedulerDecision(
                state=SchedulerState.NOT_PROFITABLE,
                deficit_kwh=deficit_kwh,
                reason=(
                    f"Not profitable: charge cost {total_charge_cost:.3f}/kWh "
                    f"(off-peak {effective_charge_cost:.3f} + degradation {cycle_cost:.3f}) "
                    f">= peak rate {peak_rate:.3f}/kWh"
                ),
                evaluated_at=now,
            )
            return self._decision

        # Calculate target SOC from the window anchor, NOT the live SOC
        # (#485 F1): re-evaluations during an active charge would
        # otherwise stack the deficit on top of the charging progress.
        soc_increase_needed = (deficit_kwh / self._config.battery_usable_capacity_kwh) * 100
        target_soc = min(
            self._config.max_target_soc,
            anchor_soc + soc_increase_needed,
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

        # Calculate hours needed for charging. Keep the fractional value
        # for the cheapest-window request (a 1.2 h charge should not book
        # 2 h of slots); the rounded-up integer is for display + the
        # adapter's safety duration.
        actual_charge_kwh = (target_soc - current_soc) / 100 * self._config.battery_usable_capacity_kwh
        charge_power_kw = self._config.battery_max_charge_power_w / 1000
        hours_needed_f = actual_charge_kwh / charge_power_kw
        hours_needed = max(1, int(-(-hours_needed_f // 1)))  # ceil
        self._planned_soc = current_soc

        # (#638 one-gate C4) The window pick is GONE — this used to call
        # find_cheapest_hours + _plan_night_schedule here, the second
        # selector beside the joint planner. A SCHEDULED verdict now means
        # exactly: "economics cleared; pre-charge deficit_kwh to target_soc
        # at charge_power_w — whenever the plan's battery block says".
        self._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=target_soc,
            deficit_kwh=deficit_kwh,
            hours_needed=hours_needed,
            charge_power_w=self._config.battery_max_charge_power_w,
            reason=(
                f"Charge {actual_charge_kwh:.1f} kWh "
                f"({current_soc:.0f}% → {target_soc:.0f}%) "
                f"in {hours_needed}h"
            ),
            evaluated_at=now,
        )
        _LOGGER.info(
            "Battery charge scheduled: %s (window: the joint plan's battery block)",
            self._decision.reason,
        )
        return self._decision

    def evaluate_arbitrage(
        self,
        current_soc: float,
        export_rate: float,
        import_forecast_min: Optional[float],
        enabled_override: Optional[bool] = None,
    ) -> SchedulerDecision:
        """Per-cycle export-arbitrage check (#523) — the discharge mirror
        of ``evaluate()``'s charge planning, using the SAME economic model
        (``roundtrip_efficiency`` + ``battery_cycle_cost``).

        Sell stored energy to the grid when the dynamic export price beats
        the cost of recharging it later. Returns a DISCHARGING_ARBITRAGE
        decision when worthwhile, else a non-firing state.

        Stateless and cheap — the coordinator calls it every cycle (unlike
        ``evaluate()``, which plans the night at the trigger). It never
        runs while a charge is planned/active; the coordinator gates that.
        """
        now = dt_util.now()
        cfg = self._config

        # Every verdict from this method carries from_arbitrage=True (#533) so
        # decide_battery routes a non-firing stop to STOP_FORCE_DISCHARGE (not
        # the night scheduler's STOP_FORCE_CHARGE).
        def _v(**kw) -> SchedulerDecision:
            return SchedulerDecision(from_arbitrage=True, evaluated_at=now, **kw)

        # ``enabled_override`` lets the coordinator run the economic check
        # even when the GLOBAL toggle is off — needed for per-battery
        # ``allow_arbitrage`` mode (#523). decide_battery then gates WHICH
        # battery acts on the verdict, so producing it here is safe.
        enabled = cfg.arbitrage_enabled if enabled_override is None else enabled_override
        if not enabled:
            return _v(state=SchedulerState.IDLE, reason="export arbitrage disabled")
        # Reserve floor — never sell the backup reserve.
        if current_soc <= cfg.arbitrage_reserve_soc:
            return _v(
                state=SchedulerState.NOT_NEEDED,
                reason=(
                    f"SOC {current_soc:.0f}% at/below reserve "
                    f"{cfg.arbitrage_reserve_soc:.0f}%"
                ),
            )
        # Export must clear the configured floor to bother cycling.
        if export_rate < cfg.arbitrage_min_export_price:
            return _v(
                state=SchedulerState.NOT_PROFITABLE,
                reason=(
                    f"export {export_rate:.3f} < floor "
                    f"{cfg.arbitrage_min_export_price:.3f}/kWh"
                ),
            )
        # Profitability — the symmetric break-even to charge-on-cheap:
        # selling now must beat buying back later (cheapest upcoming import
        # ÷ round-trip efficiency) plus the battery degradation cost.
        #
        # #523: with NO import forecast we can't prove selling beats buying
        # back, so don't fire — without this the check was skipped and
        # arbitrage sold on the export floor alone (too eager; e.g. NL export
        # spot−margin is well below import all-in). Conservative default.
        if import_forecast_min is None:
            return _v(
                state=SchedulerState.NOT_PROFITABLE,
                reason="no import-price forecast — can't prove profitable, holding",
            )
        recharge_cost = (
            float(import_forecast_min) / cfg.roundtrip_efficiency
            + cfg.battery_cycle_cost * 2
        )
        if export_rate <= recharge_cost:
            return _v(
                state=SchedulerState.NOT_PROFITABLE,
                reason=(
                    f"export {export_rate:.3f} ≤ recharge break-even "
                    f"{recharge_cost:.3f}/kWh"
                ),
            )
        # #533: cap the sell power so arbitrage can't create a billed grid peak
        # (capacity-tariff markets). 0 = uncapped.
        sell_w = cfg.max_discharge_power_w
        if cfg.arbitrage_max_export_w > 0:
            sell_w = min(sell_w, cfg.arbitrage_max_export_w)
        return _v(
            state=SchedulerState.DISCHARGING_ARBITRAGE,
            discharge_power_w=sell_w,
            floor_soc=cfg.arbitrage_reserve_soc,
            reason=(
                f"export arbitrage: {export_rate:.3f}/kWh ≥ floor "
                f"{cfg.arbitrage_min_export_price:.3f}, SOC {current_soc:.0f}% > "
                f"reserve {cfg.arbitrage_reserve_soc:.0f}% → sell "
                f"{sell_w:.0f} W to grid"
            ),
        )

    def _resolve_forecast(
        self,
        forecast_tomorrow_kwh: float,
        expected_consumption_kwh: float,
        correction_factor: float,
        forecast_available: bool,
        forecast_age_hours: float,
    ) -> float:
        """3-tier forecast fallback strategy.

        Tier 1 (primary): Fresh forecast available — apply correction + confidence + pessimism
        Tier 2 (degraded): Forecast stale (>6h old) — use it but increase pessimism
        Tier 3 (offline): No forecast — charge conservatively to fallback SOC
        """
        conf = self._config

        if not forecast_available or forecast_tomorrow_kwh <= 0:
            # Tier 3: No forecast at all — return 0 so deficit = full consumption
            # The fallback SOC is handled by the evaluate caller or by planning
            # a conservative target
            _LOGGER.warning(
                "Battery scheduler: no forecast available, using conservative fallback"
            )
            return 0.0

        if forecast_age_hours > conf.stale_forecast_hours:
            # Tier 2: Stale forecast — trust it less (double pessimism weight)
            pessimism = min(1.0, conf.pessimism_weight * 2)
            effective = forecast_tomorrow_kwh * correction_factor * (1.0 - pessimism) * conf.forecast_confidence
            _LOGGER.info(
                "Battery scheduler: stale forecast (%.1fh old), using degraded "
                "confidence: %.1f kWh effective (raw=%.1f)",
                forecast_age_hours,
                effective,
                forecast_tomorrow_kwh,
            )
            return effective

        # Tier 1: Fresh forecast — apply standard correction + pessimism blend
        # pessimism_weight 0.3 means: 70% forecast + 30% pessimistic (lower) estimate
        optimistic = forecast_tomorrow_kwh * correction_factor * conf.forecast_confidence
        pessimistic = forecast_tomorrow_kwh * correction_factor * conf.forecast_confidence * 0.5
        effective = optimistic * (1.0 - conf.pessimism_weight) + pessimistic * conf.pessimism_weight

        return effective

    def should_replan(
        self,
        current_soc: float,
        ev_connected: bool,
        price_fingerprint: Optional[int] = None,
    ) -> bool:
        """Check if conditions changed enough to warrant re-evaluation.

        Triggers:
        1. Price series changed since the plan was made — new
           day-ahead prices can invalidate the chosen window AND flip a
           NOT_PROFITABLE / NOT_NEEDED verdict, so this fires for any
           completed evaluation, not only active charge plans.
        2. SOC deviated significantly from when plan was made
        3. EV connected/disconnected since last evaluation
        """
        # A re-plan is already pending (the coordinator clears
        # _last_evaluation_date to arm one) or no evaluation has run
        # yet — nothing new to detect. Without this, a price update
        # arriving outside the planning window re-fired the trigger
        # (and its INFO line) every coordinator cycle until the window
        # opened, ~2 lines per 10s for hours (#485 F2).
        if self._last_evaluation_date is None:
            return False

        if (
            price_fingerprint is not None
            and self._price_fingerprint is not None
            and price_fingerprint != self._price_fingerprint
            and self._decision.state not in (
                SchedulerState.IDLE,
                SchedulerState.TARGET_REACHED,
            )
        ):
            # Consume the change: one trigger per series update. The
            # next evaluate() re-captures the authoritative value.
            self._price_fingerprint = price_fingerprint
            _LOGGER.info(
                "Battery scheduler re-plan triggered: price series updated"
            )
            return True

        if not self._decision.should_charge:
            return False

        # SOC deviation check
        if self._planned_soc is not None:
            deviation = abs(current_soc - self._planned_soc)
            if deviation >= self._config.replan_soc_deviation_pct:
                _LOGGER.info(
                    "Battery scheduler re-plan triggered: SOC deviation %.1f%% "
                    "(was %.1f%%, now %.1f%%)",
                    deviation,
                    self._planned_soc,
                    current_soc,
                )
                return True

        # EV change check
        if self._config.replan_on_ev_change and self._last_ev_connected is not None:
            if ev_connected != self._last_ev_connected:
                _LOGGER.info(
                    "Battery scheduler re-plan triggered: EV %s",
                    "connected" if ev_connected else "disconnected",
                )
                self._last_ev_connected = ev_connected
                return True

        self._last_ev_connected = ev_connected
        return False

    def reset(self) -> None:
        """Reset scheduler to idle state (call when night ends)."""
        self._decision = SchedulerDecision(state=SchedulerState.IDLE)
        self._charge_started_at = None
        self._planned_soc = None
        self._last_ev_connected = None
        self._price_fingerprint = None
        self._window_anchor_soc = None
        self._window_anchor_at = None

    def _window_start(self, now: datetime) -> datetime:
        """Start of the current (or most recent) planning window."""
        start = now.replace(
            hour=self._config.trigger_hour,
            minute=self._config.trigger_minute,
            second=0,
            microsecond=0,
        )
        if start > now:
            start -= timedelta(days=1)
        return start

    def _in_planning_window(self, now: datetime) -> bool:
        """Whether ``now`` falls inside the nightly planning window."""
        start = self._window_start(now)
        return start <= now < start + timedelta(hours=self._config.planning_window_hours)

    def should_trigger_evaluation(self, now: Optional[datetime] = None) -> bool:
        """Check if it's time to run an evaluation.

        Rolling horizon: the first evaluation of the night runs
        when the planning window opens (trigger time, default 21:00);
        after that the scheduler re-evaluates every
        ``replan_interval_min`` minutes until the window closes
        (``planning_window_hours`` later, default 06:00) — picking up
        price updates, forecast refreshes and consumption surprises the
        way receding-horizon schedulers do. An externally requested
        re-plan (``_last_evaluation_date = None``, set by the
        coordinator when ``should_replan()`` fires) triggers on the
        next cycle inside the window — the legacy code armed it but
        only re-evaluated at the next day's trigger minute.
        """
        if not self._config.enabled:
            return False

        if now is None:
            now = dt_util.now()

        if not self._in_planning_window(now):
            return False

        # Re-plan requested (or first run after startup) inside the window
        if self._last_evaluation_date is None:
            return True

        # First evaluation of tonight's window
        if self._last_evaluation_date < self._window_start(now):
            return True

        # Rolling re-evaluation within the window
        elapsed_min = (now - self._last_evaluation_date).total_seconds() / 60
        return elapsed_min >= self._config.replan_interval_min


# ─────────────────────────────────────────────────────────────────
# (#638 one-gate C4c) — plan-derived entity view + verdict persistence
# ─────────────────────────────────────────────────────────────────

def schedule_view_from_plan(plan, now) -> dict:
    """The ``battery_scheduler_schedule`` entity payload, read from the
    stamped joint plan's ``battery`` blocks.

    Keeps the exact dict shape the deleted ``NightChargeSchedule.as_dict``
    published, so every dashboard consumer keeps working. ``ev_w`` is
    honestly 0 — the joint plan carries EV blocks under their own ids.
    Returns ``{}`` when there is no plan or no battery block: the entity
    reads "no schedule", same as a night the scheduler declined.
    """
    if not isinstance(plan, dict):
        return {}
    slots = []
    total_kwh = 0.0
    cost = 0.0
    for b in plan.get("blocks") or []:
        if b.get("id") != "battery":
            continue
        try:
            start = datetime.fromisoformat(str(b["start"]))
            end = datetime.fromisoformat(str(b["end"]))
            power = float(b.get("power_w") or 0.0)
        except (KeyError, TypeError, ValueError):
            continue
        hours = max(0.0, (end - start).total_seconds() / 3600.0)
        kwh = power * hours / 1000.0
        total_kwh += kwh
        price = float(b.get("price") or 0.0)
        cost += kwh * price
        try:
            active = bool(start <= now < end)
        except TypeError:  # naive/aware mismatch — honest False
            active = False
        slots.append({
            "start": start.isoformat(),
            "end": end.isoformat(),
            "battery_w": power,
            "ev_w": 0,
            "total_w": power,
            "price": price,
            "active": active,
        })
    if not slots:
        return {}
    return {
        "slots": slots,
        "total_battery_kwh": round(total_kwh, 2),
        "total_ev_kwh": 0.0,
        "total_kwh": round(total_kwh, 2),
        "estimated_cost": round(cost, 3),
        "peak_limit_w": 0.0,
    }


def serialize_battery_verdict(decision) -> Optional[dict]:
    """The WHAT half of a SCHEDULED night, shaped for the plan stash.

    Only a SCHEDULED verdict is worth persisting — a reboot mid-block
    outside the evaluation window must still actuate the restored night
    (the scheduler's decision is memory-only; the plan already survives).
    """
    if decision is None:
        return None
    state = getattr(decision, "state", None)
    if getattr(state, "value", state) != "scheduled":
        return None
    return {
        "state": "scheduled",
        "target_soc": float(getattr(decision, "target_soc", 0.0) or 0.0),
        "deficit_kwh": float(getattr(decision, "deficit_kwh", 0.0) or 0.0),
        "charge_power_w": float(
            getattr(decision, "charge_power_w", 0.0) or 0.0),
        "duration_min": int(getattr(decision, "duration_min", 60) or 60),
        "evaluated_at": (
            decision.evaluated_at.isoformat()
            if getattr(decision, "evaluated_at", None) else None),
    }


def restore_battery_verdict(scheduler, payload) -> None:
    """Re-seat a persisted SCHEDULED verdict on the scheduler at boot.

    Per-entry repair (the #563 rule): junk restores to nothing rather
    than raising — the next evaluation window re-derives the WHAT.
    """
    if not isinstance(payload, dict):
        return
    if payload.get("state") != "scheduled":
        return
    try:
        evaluated_at = (
            datetime.fromisoformat(str(payload["evaluated_at"]))
            if payload.get("evaluated_at") else None)
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=float(payload.get("target_soc", 0.0) or 0.0),
            deficit_kwh=float(payload.get("deficit_kwh", 0.0) or 0.0),
            charge_power_w=float(
                payload.get("charge_power_w", 0.0) or 0.0),
            duration_min=int(payload.get("duration_min", 60) or 60),
            reason="restored from the stamped plan (reboot)",
            evaluated_at=evaluated_at,
        )
    except (TypeError, ValueError):
        return
