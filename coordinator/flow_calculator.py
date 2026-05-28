"""Power and energy flow calculation module for SEM coordinator.

This module calculates how energy flows between sources and destinations
using proportional allocation. This is more physically accurate than
priority-based allocation because electricity naturally mixes.

Sources: Solar, Grid Import, Battery Discharge
Destinations: Home, EV, Battery Charge, Grid Export
"""
from __future__ import annotations

import logging
from datetime import date
from typing import Dict

from homeassistant.util import dt as dt_util

from .types import PowerReadings, PowerFlows, EnergyTotals, EnergyFlows

_LOGGER = logging.getLogger(__name__)


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
                           battery_capacity_kwh: float = 15) -> float:
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
        """
        # Source 1: Grid export — always redirectable
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
        self, available_power: float, voltage: float = 230, phases: int = 3
    ) -> float:
        """Calculate EV charging current from available power."""
        if available_power <= 0:
            return 0.0

        # I = P / (V * phases)
        current = available_power / (voltage * phases)

        # Round to nearest amp, min 6A, max 16A
        current = round(current)
        current = max(0, min(16, current))

        return current
