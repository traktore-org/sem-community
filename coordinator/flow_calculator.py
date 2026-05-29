"""Power and energy flow calculation module for SEM coordinator.

This module calculates how energy flows between sources and destinations
using proportional allocation. This is more physically accurate than
priority-based allocation because electricity naturally mixes.

Sources: Solar, Grid Import, Battery Discharge
Destinations: Home, EV, Battery Charge, Grid Export
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional

from homeassistant.util import dt as dt_util

from .types import PowerReadings, PowerFlows, EnergyTotals, EnergyFlows

_LOGGER = logging.getLogger(__name__)


# ───────────────────────────────────────────────────────────────────────
# Canonical EV-budget calculation — the unified source of truth (#282)
#
# Background: SEM historically had THREE separate "how many watts can the
# EV draw right now" calculations that could (and did) disagree:
#   B1 coordinator.py:898 `available_power` → published sensors
#   B2 coordinator.py:2589 `ev_budget` in `_build_charging_context`
#                                          → state machine input
#   B3 ev_control.py:440-452 `budget_w` → the actuator
#
# Live evidence captured 2026-05-29 (PROD): state machine returned
# SOLAR_CHARGING_ACTIVE because its budget view included battery_redirect
# while the actuator's budget view didn't, leaving the dashboard label
# claiming "Charging active" while the car drew 0 W. Commit 1a9b3c9
# installed a sensor-level demotion guard as the cosmetic stopgap.
#
# This module defines the replacement: ONE method, ONE dataclass, used
# by all three former call sites. See docs/plans/2026-05-29_ev_budget_unification.md
# for the four-phase rollout. Phase A landed this code purely additively.
# ───────────────────────────────────────────────────────────────────────


class EVBudgetStrategy:
    """Strategy values the canonical budget dispatches on.

    These are the canonical names. The coordinator's legacy
    ``_determine_charging_strategy`` returns strings that map onto these
    via ``_strategy_from_legacy`` in coordinator.py (Phase B). The
    distinction between SOLAR_ONLY (Zone 3, redirect allowed) and
    SELF_CONSUMPTION (Zone 2, redirect denied) is now first-class — the
    legacy code conflated both as ``"solar_only"`` and used substring
    matching on the human-readable ``charging_strategy_reason`` to tell
    them apart, which was brittle and the proximate cause of the
    three-way disagreement (#282).
    """

    IDLE = "idle"
    """EV gets nothing. Strategy decided to not charge this cycle."""

    SELF_CONSUMPTION = "self_consumption"
    """Zone 2: surplus only, NO battery-charge redirect to EV. Battery
    still 'owns' any surplus while SOC is in the priority band."""

    SOLAR_ONLY = "solar_only"
    """Zone 3: solar surplus + forecast-aware battery-charge redirect."""

    BATTERY_ASSIST = "battery_assist"
    """Zone 4-ish: surplus + redirect + active battery DISCHARGE to EV.
    The battery is willing to power the EV directly because forecast
    or SOC makes that the right trade."""

    MIN_PV = "min_pv"
    """User asked: 'guarantee Min current, add surplus on top.' The
    canonical budget floors at ``min_power_floor_w``."""

    NOW = "now"
    """User asked: 'charge at maximum right now, regardless of solar.'
    Budget is the charger's full nameplate power; grid backfill is
    expected and intentional."""


@dataclass
class EVBudget:
    """Single source of truth for what the EV is allowed to draw right now.

    All consumers (published sensors, state machine, actuator) read from
    instances of this class. The decomposition exists so callers can
    introspect "where did this watt come from" without re-deriving:

    Attributes:
        strategy: The strategy this budget was computed for (see
            ``EVBudgetStrategy``).
        solar_surplus: ``max(0, solar - home - batt_charge)``. Always
            the "free" part — what solar could deliver without battery
            help. Same across all strategies (except ``IDLE`` and
            ``NOW``, where it is 0 because the strategy makes the
            surplus irrelevant).
        battery_redirect: How much battery-charge power can be diverted
            to the EV (forecast/SOC aware). Non-zero for ``SOLAR_ONLY``
            and ``BATTERY_ASSIST`` and ``MIN_PV``. Always zero for
            ``SELF_CONSUMPTION`` (Zone 2 — battery has priority).
        battery_assist: How much the battery can actively DISCHARGE to
            the EV. Non-zero only for ``BATTERY_ASSIST``.
        net_w: ``solar_surplus + battery_redirect + battery_assist``,
            clamped to ``>= 0``, with strategy-specific overrides
            applied:
              - IDLE: 0
              - MIN_PV: ``max(min_power_floor_w, sum)``
              - NOW: ``override_max_w`` (typically charger nameplate)
            This is the SETPOINT (target total watts) the charger is
            allowed to draw.
        current_a: ``net_w`` expressed as charger current (integer
            amps). Uses ``math.floor`` so the charger stays strictly
            under the budget — round-to-nearest was the source of the
            0.5 A grid-leak boundary issue, fixed in
            ``calculate_charging_current`` and preserved here. Clamped
            to ``[0, 16]`` (16 A is the SEM-supported per-phase limit).
    """

    strategy: str
    solar_surplus: float
    battery_redirect: float
    battery_assist: float
    net_w: float
    current_a: int

    def __post_init__(self):
        # Defensive: protect downstream from negative leaks.
        if self.net_w < 0:
            self.net_w = 0.0
        if self.current_a < 0:
            self.current_a = 0


class FlowCalculator:
    """Calculates power and energy flows using proportional allocation."""

    def __init__(self):
        """Initialize flow calculator."""
        # Accumulators for energy flows (reset daily)
        self._flow_accumulators: Dict[str, float] = {}
        self._current_date: date = dt_util.now().date()

    def calculate_power_flows(self, power: PowerReadings) -> PowerFlows:
        """Calculate instantaneous power flows using proportional allocation.

        Each source flows to ALL destinations based on demand percentages.
        This matches how electricity physically distributes in a system.
        """
        flows = PowerFlows()

        # Get source powers
        solar = power.solar_power
        grid_import = power.grid_import_power
        battery_discharge = power.battery_discharge_power

        # Get destination powers
        home = power.home_consumption_power
        ev = power.ev_power
        battery_charge = power.battery_charge_power
        grid_export = power.grid_export_power

        # Calculate total supply and demand
        total_supply = solar + grid_import + battery_discharge
        total_demand = home + ev + battery_charge + grid_export

        # Skip if no activity (prevents division by zero)
        if total_supply < 1 or total_demand < 1:
            return flows

        # Calculate demand percentages
        home_pct = home / total_demand
        ev_pct = ev / total_demand
        battery_charge_pct = battery_charge / total_demand
        grid_export_pct = grid_export / total_demand

        # Distribute solar proportionally to all destinations
        flows.solar_to_home = round(solar * home_pct, 1)
        flows.solar_to_ev = round(solar * ev_pct, 1)
        flows.solar_to_battery = round(solar * battery_charge_pct, 1)
        flows.solar_to_grid = round(solar * grid_export_pct, 1)

        # Grid import only flows to home, EV, battery (not back to grid)
        demand_without_export = home + ev + battery_charge
        if demand_without_export > 0:
            home_pct_no_export = home / demand_without_export
            ev_pct_no_export = ev / demand_without_export
            battery_pct_no_export = battery_charge / demand_without_export

            flows.grid_to_home = round(grid_import * home_pct_no_export, 1)
            flows.grid_to_ev = round(grid_import * ev_pct_no_export, 1)
            flows.grid_to_battery = round(grid_import * battery_pct_no_export, 1)

        # Battery discharge flows to home and EV (not to grid or battery charge)
        demand_for_battery = home + ev
        if demand_for_battery > 0:
            home_pct_battery = home / demand_for_battery
            ev_pct_battery = ev / demand_for_battery

            flows.battery_to_home = round(battery_discharge * home_pct_battery, 1)
            flows.battery_to_ev = round(battery_discharge * ev_pct_battery, 1)

        return flows

    # Attributes covered by the running accumulator. Defined as a tuple so
    # ``integrate_energy_flows`` and the storage hooks share one source of truth.
    _ACCUMULATED_ATTRS = (
        "solar_to_home", "solar_to_ev", "solar_to_battery", "solar_to_grid",
        "grid_to_home", "grid_to_ev", "grid_to_battery",
        "battery_to_home", "battery_to_ev",
    )

    def integrate_energy_flows(
        self, power_flows: PowerFlows, interval_seconds: float,
    ) -> EnergyFlows:
        """Time-integrate per-cycle power flows into daily energy flows (#282).

        Replaces ``calculate_energy_flows`` (proportional allocation across
        daily totals), which credited solar to the EV even when the EV
        wasn't drawing — a sunny day with a 30-min EV plug-in showed
        flow_solar_to_ev_energy ≈ daily_solar × (daily_ev / total_demand),
        which is fictional. The user's late-afternoon plug-in saw 85 %
        attributed-daily solar share while the actual session share was 12 %.

        This version integrates the instantaneous ``power_flows`` (already
        correctly attributed by ``calculate_power_flows`` based on the
        current cycle's demand) over time, so:

        * Solar that flowed to the GRID at noon while the EV was unplugged
          stays counted as solar_to_grid — not retroactively re-allocated.
        * Battery discharge in the afternoon shows up as battery_to_ev, with
          its origin (charged from morning solar) NOT re-credited as solar.

        The user sees small, honest numbers that match the session
        attribution. Bills + daily_solar_share now reflect what physically
        happened, not an aggregate average.

        Args:
            power_flows: Current cycle's instantaneous PowerFlows (watts).
            interval_seconds: Time since the last integration step
                (typically ``self.update_interval.total_seconds()``).

        Returns:
            EnergyFlows in kWh accumulated since the last day boundary.
        """
        # Day rollover — clear at local midnight. Solar-day or sunrise-based
        # rollover would shift this; keeping calendar-day for consistency with
        # daily_solar_energy / daily_grid_export_energy.
        today = dt_util.now().date()
        if today != self._current_date:
            self._flow_accumulators.clear()
            self._current_date = today

        hours = max(0.0, interval_seconds) / 3600.0
        for attr in self._ACCUMULATED_ATTRS:
            watts = getattr(power_flows, attr, 0.0) or 0.0
            self._flow_accumulators[attr] = (
                self._flow_accumulators.get(attr, 0.0) + watts * hours / 1000.0
            )

        flows = EnergyFlows()
        for attr in self._ACCUMULATED_ATTRS:
            setattr(flows, attr, round(self._flow_accumulators.get(attr, 0.0), 3))
        return flows

    def get_flow_accumulator_state(self) -> dict:
        """Snapshot for persistence (#282). Keys + date so restore can
        detect a stale snapshot from a previous day."""
        return {
            "date": self._current_date.isoformat(),
            "accumulators": dict(self._flow_accumulators),
        }

    def restore_flow_accumulator_state(self, state: dict) -> None:
        """Restore on coordinator startup so an HA restart mid-day doesn't
        reset the daily flow counters back to 0 (#282)."""
        if not isinstance(state, dict):
            return
        try:
            saved_date = date.fromisoformat(state.get("date", ""))
        except (TypeError, ValueError):
            return
        # If today is a different day, treat as stale — don't carry yesterday's
        # accumulator into today's counters.
        if saved_date != self._current_date:
            return
        acc = state.get("accumulators")
        if isinstance(acc, dict):
            for k in self._ACCUMULATED_ATTRS:
                v = acc.get(k)
                if isinstance(v, (int, float)):
                    self._flow_accumulators[k] = float(v)

    def calculate_energy_flows(self, energy: EnergyTotals) -> EnergyFlows:
        """Legacy proportional-allocation energy flows (kept for tests).

        ⚠️  Misleading attribution — use ``integrate_energy_flows`` instead.
        Spreads daily totals proportionally to demand without regard to
        timing, so a sunny morning with no EV charging still credits solar
        to a brief afternoon EV plug-in.

        Retained because some tests pin the old behaviour and because the
        function is mathematically valid as a Sankey-style aggregate when
        timing doesn't matter (full-day overviews). Not wired into the
        coordinator update cycle anymore (#282).
        """
        flows = EnergyFlows()

        # Get source energies
        solar = energy.daily_solar
        grid_import = energy.daily_grid_import
        battery_discharge = energy.daily_battery_discharge

        # Get destination energies
        home = energy.daily_home
        ev = energy.daily_ev
        battery_charge = energy.daily_battery_charge
        grid_export = energy.daily_grid_export

        # Calculate total demand
        total_demand = home + ev + battery_charge + grid_export

        if total_demand < 0.001:  # Less than 1Wh
            return flows

        # Calculate demand percentages
        home_pct = home / total_demand
        ev_pct = ev / total_demand
        battery_charge_pct = battery_charge / total_demand
        grid_export_pct = grid_export / total_demand

        # Distribute solar energy proportionally
        flows.solar_to_home = round(solar * home_pct, 3)
        flows.solar_to_ev = round(solar * ev_pct, 3)
        flows.solar_to_battery = round(solar * battery_charge_pct, 3)
        flows.solar_to_grid = round(solar * grid_export_pct, 3)

        # Grid import to destinations (excluding grid export)
        demand_without_export = home + ev + battery_charge
        if demand_without_export > 0.001:
            home_pct_no_export = home / demand_without_export
            ev_pct_no_export = ev / demand_without_export
            battery_pct_no_export = battery_charge / demand_without_export

            flows.grid_to_home = round(grid_import * home_pct_no_export, 3)
            flows.grid_to_ev = round(grid_import * ev_pct_no_export, 3)
            flows.grid_to_battery = round(grid_import * battery_pct_no_export, 3)

        # Battery discharge to home and EV
        demand_for_battery = home + ev
        if demand_for_battery > 0.001:
            home_pct_battery = home / demand_for_battery
            ev_pct_battery = ev / demand_for_battery

            flows.battery_to_home = round(battery_discharge * home_pct_battery, 3)
            flows.battery_to_ev = round(battery_discharge * ev_pct_battery, 3)

        # Verify energy balance and adjust if needed
        home_received = flows.solar_to_home + flows.grid_to_home + flows.battery_to_home
        if abs(home - home_received) > 0.001:
            # Absorb rounding difference into solar_to_home
            flows.solar_to_home = round(flows.solar_to_home + (home - home_received), 3)

        _LOGGER.debug(
            f"Energy flows calculated: "
            f"Solar→Home: {flows.solar_to_home:.3f}, "
            f"Solar→Grid: {flows.solar_to_grid:.3f}, "
            f"Grid→Home: {flows.grid_to_home:.3f}"
        )

        return flows

    def calculate_ev_budget(self, power: PowerReadings,
                           forecast_remaining_kwh: float = 0,
                           battery_soc: float = 0,
                           battery_capacity_kwh: float = 15,
                           solar_only: bool = False) -> float:
        """Power budget for EV, including forecast-aware battery charge redirect.

        Three sources of power for EV:
        1. Grid export (power going unused to grid)
        2. Redirectable battery charge (slow battery charging to free power for EV)
        3. Active battery discharge (handled separately in coordinator for battery-assist mode)

        Semantics: the returned value is the SETPOINT sent to the charger (total watts
        the charger is allowed to draw), NOT an increment on top of current consumption.
        When the EV is already charging at ev_power W and grid_export_power W is going to
        the grid unused, the new setpoint is ev_power + grid_export_power — this tells the
        charger to absorb all the surplus. The charger adjusts its draw from ev_power to
        the new setpoint, naturally consuming the exported surplus without importing. (#229)

        Args:
            solar_only: When True, enforce a hard surplus ceiling of
                ``max(0, solar - home)`` — the charger MUST NOT exceed what
                solar alone can supply. This is the regime the ``solar_only``
                strategy promises but historically didn't enforce: the base
                included ``power.ev_power`` (the current draw), so the charger
                was never asked to ramp DOWN when surplus dropped, silently
                letting grid backfill the gap. Captured by Scenario 0 (#282).
                Default False preserves legacy behaviour for the budget-as-
                informational-display callers.
        """
        if solar_only:
            # Hard surplus ceiling: only what solar can supply right now.
            # Subtract the home load and ALSO the active battery charge —
            # solar still "belongs" to the battery in this regime; the
            # redirect logic below decides whether some can be borrowed.
            true_surplus = max(
                0.0,
                power.solar_power - power.home_consumption_power
                - power.battery_charge_power,
            )
            # Allow the same forecast-aware battery-charge redirect when the
            # forecast/SOC math says the battery doesn't need this slice.
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            return round(max(0.0, true_surplus + redirect), 0)

        # Legacy path: setpoint = current EV draw + unused grid export + redirect.
        if power.ev_power > 0:
            # EV already charging: new setpoint = current draw + unused grid export
            # This is a SETPOINT (target total watts), not a delta to add to current draw.
            base = power.ev_power + power.grid_export_power
        else:
            base = power.grid_export_power

        # Source 2: Redirectable battery charge (forecast + SOC aware)
        redirect = self._calculate_battery_redirect(
            power.battery_charge_power, battery_soc,
            battery_capacity_kwh, forecast_remaining_kwh,
        )
        return round(max(0, base + redirect), 0)

    def _calculate_battery_redirect(self, battery_charge_w: float,
                                     battery_soc: float,
                                     battery_capacity_kwh: float,
                                     forecast_remaining_kwh: float) -> float:
        """How much battery charge power can be redirected to EV.

        Uses forecast when available: if remaining solar can still fill battery,
        redirect proportionally. Falls back to SOC threshold without forecast.
        """
        if battery_charge_w <= 0:
            return 0

        battery_need_kwh = max(0, (100 - battery_soc) / 100 * battery_capacity_kwh)

        if forecast_remaining_kwh > 0:
            # Forecast available: redirect proportional to excess forecast
            if forecast_remaining_kwh >= battery_need_kwh and battery_need_kwh > 0:
                # Forecast covers battery — redirect proportionally.
                # Use max(0.05, ratio) to always redirect at least 5% at the
                # exact boundary (forecast == battery_need gives ratio=0 without this).
                ratio = min(1.0, 1.0 - battery_need_kwh / forecast_remaining_kwh)
                return battery_charge_w * max(0.05, ratio)
            elif battery_need_kwh <= 0.5:
                # Battery nearly full — redirect all
                return battery_charge_w
            else:
                # Forecast can't cover battery need — keep charging
                return 0
        else:
            # No forecast — SOC threshold fallback
            if battery_soc >= 80:
                return battery_charge_w  # Battery full enough, redirect all
            return 0

    def calculate_available_power(self, power: PowerReadings) -> float:
        """Calculate power available for EV charging.

        Available = Solar - Home - Battery Charge + Battery Discharge (when assisting)
        Grid export is already a consequence of surplus, not additive.
        Battery discharge is included when the battery is actively discharging
        to assist loads — that power is available for the EV as well.
        """
        excess = (
            power.solar_power
            - power.home_consumption_power
            - power.battery_charge_power
        )
        available = max(0, excess)

        # Include battery discharge as available when battery is actively discharging
        if power.battery_discharge_power > 0:
            available += power.battery_discharge_power

        # Cap at solar + battery discharge (can't report more than combined sources)
        return round(min(available, power.solar_power + power.battery_discharge_power), 0)

    def calculate_charging_current(
        self, available_power: float, voltage: float = 230, phases: int = 3,
        round_down: bool = False,
    ) -> float:
        """Calculate EV charging current from available power.

        Args:
            round_down: When True (use this for surplus / solar_only budgets),
                floor instead of round-to-nearest. Round-to-nearest can push
                the actuator into grid territory by ~0.5 A at the boundary —
                e.g. 5200 W surplus → 7.53 A → rounds to 8 A → 5520 W → 320 W
                of grid backfill. Floor keeps the charger strictly under the
                budget. Captured by Scenario 0 (#282). Default False preserves
                legacy round-nearest behaviour for non-surplus paths.
        """
        if available_power <= 0:
            return 0.0

        # I = P / (V * phases)
        current = available_power / (voltage * phases)

        # Round to integer amps with the requested direction, then clamp.
        if round_down:
            current = math.floor(current)
        else:
            current = round(current)
        current = max(0, min(16, current))

        return current

    # ───────────────────────────────────────────────────────────────────
    # Canonical EV-budget calculation — Phase A of #282 unification
    # ───────────────────────────────────────────────────────────────────

    def calculate_canonical_ev_budget(
        self,
        power: PowerReadings,
        *,
        strategy: str,
        battery_soc: float = 0.0,
        battery_capacity_kwh: float = 15.0,
        forecast_remaining_kwh: float = 0.0,
        battery_auto_start_soc: float = 90.0,
        battery_buffer_soc: float = 70.0,
        battery_assist_floor_soc: float = 60.0,
        battery_assist_max_power_w: float = 4500.0,
        min_power_floor_w: float = 0.0,
        override_max_w: Optional[float] = None,
        voltage: float = 230.0,
        phases: int = 3,
    ) -> EVBudget:
        """The one method. Strategy-aware. Replaces the three legacy paths.

        Computes the canonical setpoint (watts) the EV charger is
        allowed to draw right now, broken down into its components so
        the caller can publish each piece as a diagnostic sensor.

        Args:
            power: This cycle's sensor readings.
            strategy: One of :class:`EVBudgetStrategy`'s constants.
                Each strategy has a single, well-defined formula —
                callers MUST translate their own (legacy) strategy
                names into one of these explicitly.
            battery_soc, battery_capacity_kwh, forecast_remaining_kwh:
                Inputs to the redirect/assist sub-calculations.
            battery_auto_start_soc, battery_buffer_soc,
                battery_assist_floor_soc, battery_assist_max_power_w:
                Strategy thresholds, normally read from config. Defaults
                match the SEM-wide defaults so calls without overrides
                still produce sensible numbers.
            min_power_floor_w: Set this when strategy is ``MIN_PV`` to
                guarantee a minimum setpoint (the "Min" part of Min+PV).
                Ignored for other strategies.
            override_max_w: Set this when strategy is ``NOW`` to bypass
                the surplus calculation entirely. Typically the
                charger's nameplate power (max_current * phases *
                voltage). Ignored for other strategies.
            voltage, phases: Charger electrical parameters for the
                amps conversion. Defaults match a 3-phase EU charger
                at 230 V — KEBA, Wallbox, etc.

        Returns:
            :class:`EVBudget` with all components filled in.

        Raises:
            ValueError: if ``strategy`` is unknown. We refuse to
                silently fall through to a "safe" default because every
                strategy must be mapped explicitly — silent fallthrough
                was exactly the #282 disagreement mode.
        """
        # Always compute the building blocks. Strategies that don't
        # consume a particular block get it set to 0 in the dataclass —
        # makes the diagnostic sensors honest about the decomposition.
        raw_surplus = max(
            0.0,
            power.solar_power
            - power.home_consumption_power
            - power.battery_charge_power,
        )

        # ─── IDLE ───────────────────────────────────────────────────
        if strategy == EVBudgetStrategy.IDLE:
            return EVBudget(
                strategy=strategy,
                solar_surplus=0.0,
                battery_redirect=0.0,
                battery_assist=0.0,
                net_w=0.0,
                current_a=0,
            )

        # ─── NOW ────────────────────────────────────────────────────
        # User-asked override. Grid backfill is intentional in this mode.
        if strategy == EVBudgetStrategy.NOW:
            net_w = override_max_w if override_max_w is not None else (
                16.0 * phases * voltage  # SEM upper bound
            )
            net_w = max(0.0, net_w)
            return EVBudget(
                strategy=strategy,
                solar_surplus=0.0,
                battery_redirect=0.0,
                battery_assist=0.0,
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # ─── SELF_CONSUMPTION (Zone 2) ──────────────────────────────
        # Surplus only. Battery has priority in this band — no redirect.
        # Special-case: when SOC >= auto_start_soc, the battery doesn't
        # need its share, so we don't subtract batt_charge from surplus.
        # This mirrors the legacy `_self_consumption_strategy` and the
        # legacy B3 actuator path (ev_control.py:447) that disagreed
        # with the state machine for years.
        if strategy == EVBudgetStrategy.SELF_CONSUMPTION:
            if battery_soc >= battery_auto_start_soc:
                surplus = max(
                    0.0,
                    power.solar_power - power.home_consumption_power,
                )
            else:
                surplus = raw_surplus
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(surplus, 0),
                battery_redirect=0.0,
                battery_assist=0.0,
                net_w=round(surplus, 0),
                current_a=self._watts_to_amps(surplus, voltage, phases),
            )

        # ─── SOLAR_ONLY (Zone 3) ────────────────────────────────────
        # Surplus + forecast-aware redirect.
        if strategy == EVBudgetStrategy.SOLAR_ONLY:
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            net_w = raw_surplus + redirect
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(raw_surplus, 0),
                battery_redirect=round(redirect, 0),
                battery_assist=0.0,
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # ─── BATTERY_ASSIST ─────────────────────────────────────────
        # Surplus + redirect + active battery discharge to EV.
        if strategy == EVBudgetStrategy.BATTERY_ASSIST:
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            assist = self._calculate_battery_assist_w(
                power, battery_soc,
                battery_auto_start_soc, battery_buffer_soc,
                battery_assist_floor_soc, battery_assist_max_power_w,
            )
            net_w = raw_surplus + redirect + assist
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(raw_surplus, 0),
                battery_redirect=round(redirect, 0),
                battery_assist=round(assist, 0),
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # ─── MIN_PV ─────────────────────────────────────────────────
        # Surplus + redirect, floored at min_power_floor_w (grid backfills
        # the difference when surplus is insufficient — by user request).
        if strategy == EVBudgetStrategy.MIN_PV:
            redirect = self._calculate_battery_redirect(
                power.battery_charge_power, battery_soc,
                battery_capacity_kwh, forecast_remaining_kwh,
            )
            surplus_plus_redirect = raw_surplus + redirect
            net_w = max(min_power_floor_w, surplus_plus_redirect)
            return EVBudget(
                strategy=strategy,
                solar_surplus=round(raw_surplus, 0),
                battery_redirect=round(redirect, 0),
                battery_assist=0.0,
                net_w=round(net_w, 0),
                current_a=self._watts_to_amps(net_w, voltage, phases),
            )

        # Unknown strategy — refuse to silently fall through. Silent
        # fallthrough was the #282 disagreement root cause; the unifier
        # must be loud.
        raise ValueError(
            f"calculate_canonical_ev_budget: unknown strategy {strategy!r}. "
            f"Map your legacy strategy to one of EVBudgetStrategy.* explicitly."
        )

    def _watts_to_amps(self, watts: float, voltage: float, phases: int) -> int:
        """Floor watts → integer amps, clamped to [0, 16].

        Floor (not round-to-nearest) because the actuator must stay
        strictly under the budget — round-to-nearest can push +0.5 A
        over the surplus floor and silently leak grid (#282 / Scenario 0).
        """
        if watts <= 0:
            return 0
        amps = math.floor(watts / (voltage * phases))
        return max(0, min(16, amps))

    def _calculate_battery_assist_w(
        self,
        power: PowerReadings,
        battery_soc: float,
        battery_auto_start_soc: float,
        battery_buffer_soc: float,
        battery_assist_floor_soc: float,
        battery_assist_max_power_w: float,
    ) -> float:
        """How much battery discharge to attribute to EV in battery_assist mode.

        Mirrors the legacy formula from `_calculate_solar_ev_budget` in
        ev_control.py (the only place this lived before unification):

        - SOC below assist floor: 0 (the battery shouldn't assist).
        - Battery already discharging (>= 100 W): use measured value.
        - Battery not yet discharging:
            - Zone 4 (SOC >= auto_start_soc): full assist.
            - Zone 3 (SOC >= buffer_soc):
                proportional ramp 0.5 → 1.0 across the [buffer, auto_start]
                band.
            - Zone 2 (SOC < buffer_soc): 0 (shouldn't reach here — the
                strategy decision should have chosen solar_only — but
                guard anyway).
        """
        if battery_soc <= battery_assist_floor_soc:
            return 0.0

        measured_discharge = max(0.0, power.battery_discharge_power)
        if measured_discharge >= 100:
            return measured_discharge

        if battery_soc >= battery_auto_start_soc:
            return battery_assist_max_power_w
        if battery_soc >= battery_buffer_soc:
            band = max(1.0, battery_auto_start_soc - battery_buffer_soc)
            ratio = (battery_soc - battery_buffer_soc) / band
            return battery_assist_max_power_w * (0.5 + 0.5 * ratio)
        return 0.0
