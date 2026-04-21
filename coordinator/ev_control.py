"""EV control methods extracted from SEMCoordinator.

Mixin class providing all EV charging control logic:
- Night charging: dynamic peak-aware current every cycle
- Solar charging: evcc-style enable/disable delays with ramp limiting
- Min+PV mode: guaranteed minimum from grid + solar surplus
- Session cost tracking (per-session energy, cost, solar share)
- Self-healing via KEBA stall detection
- Solar EV budget calculation (grid export + forecast-aware battery redirect)
- Forecast-aware night target reduction
"""
import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.util import dt as dt_util

from ..const import (
    ChargingState,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_UPDATE_INTERVAL,
)
from .types import PowerReadings, PowerFlows, SessionData
from .charging_control import ChargingContext

_LOGGER = logging.getLogger(__name__)


class EVControlMixin:
    """EV control methods for SEMCoordinator.

    Expects the coordinator to have these attributes:
    - _ev_device, _ev_stalled_since, _ev_enable_surplus_since
    - _ev_charge_started_at, _ev_last_change_time
    - _flow_calculator, _forecast_reader, _load_manager
    - _energy_calculator, _session_data, _last_ev_connected
    - config, hass
    """

    SOLAR_CHARGING_STATES = {
        ChargingState.SOLAR_CHARGING_ACTIVE,
        ChargingState.SOLAR_SUPER_CHARGING,
        ChargingState.SOLAR_CHARGING_ALLOWED,
        ChargingState.SOLAR_MIN_PV,
    }

    SOLAR_PAUSE_STATES = {
        ChargingState.SOLAR_PAUSE_LOW_BATTERY,
        ChargingState.SOLAR_WAITING_BATTERY_PRIORITY,
    }

    async def _execute_ev_control(
        self,
        state: str,
        power: PowerReadings,
        energy: Any,
        context: ChargingContext,
    ) -> None:
        """Unified EV control: coordinator always owns EV via CurrentControlDevice.

        State-based dispatch:
        - NIGHT_CHARGING_ACTIVE: dynamic peak-aware current every cycle.
        - NIGHT_WAITING_FOR_WINDOW / NIGHT_TIME_EXPIRED: stop session, wait.
        - SOLAR_CHARGING_STATES (incl. SOLAR_MIN_PV): ramp-limited current
          with evcc-style enable/disable delays.
        - SOLAR_PAUSE_STATES: zero current, keep session alive.
        - Terminal states: stop session.

        SurplusController manages all other devices (hot water, heat pump, etc.).

        Args:
            state: Current charging state from state machine.
            power: Current sensor readings.
            energy: Daily/monthly energy totals.
            context: Charging context with strategy, targets, and night fields.
        """
        ev = self._ev_device
        ev.managed_externally = True  # ALWAYS — coordinator owns EV

        # === NIGHT CHARGING (peak-managed, ramp-limited) ===
        # Design: evcc-style ramp, configurable min current, IEC 61851 compliant
        if state == ChargingState.NIGHT_CHARGING_ACTIVE:
            remaining_kwh = context.night_target_kwh

            # Guard: target reached
            if remaining_kwh <= 0.1:
                if ev._session_active:
                    await ev.stop_session()
                return

            # Detect already-charging after SEM reload (don't interrupt)
            if not ev._session_active and power.ev_power > 50:
                ev._session_active = True
                _LOGGER.info("Night: KEBA already active (%.0fW), resuming", power.ev_power)

            # Read configurable EV parameters
            initial_amps = int(self.config.get("ev_night_initial_current", 10))
            min_amps = int(self.config.get("ev_min_current", 6))
            stall_cooldown = int(self.config.get("ev_stall_cooldown", 120))

            if not ev._session_active:
                # Fresh start: set_current BEFORE start_session
                # (KEBA ignores enable at 0A)
                initial_current = min(ev.max_current, initial_amps)
                await ev._set_current(initial_current)
                await ev.start_session(energy_target_kwh=0)
                self._ev_last_change_time = dt_util.now()
                _LOGGER.info("Night start: %dA, target=%.1fkWh", initial_current, remaining_kwh)
            else:
                # Stall detection: car stopped drawing despite setpoint
                last_change = getattr(self, '_ev_last_change_time', None)
                cooldown_ok = (last_change is None or
                               (dt_util.now() - last_change).total_seconds() > stall_cooldown)
                if cooldown_ok and self._should_reenable_charger(power):
                    _LOGGER.info("Night: charger stalled, re-enabling")
                    await ev._set_current(ev._current_setpoint or initial_amps)
                    await ev.start_session(energy_target_kwh=0)
                    self._ev_last_change_time = dt_util.now()

                # Dynamic peak-managed current (only when car is actually drawing)
                if power.ev_power > 100:
                    # W/A from actual charger readings (adapts to any car)
                    watts_per_amp = power.ev_power / max(1, ev._current_setpoint)

                    peak_limit_w = self._get_peak_limit_w()
                    headroom_w = peak_limit_w - power.grid_import_power
                    target = headroom_w / max(1, watts_per_amp)

                    # Clamp: configurable min current, max from charger config
                    target = min(ev.max_current, max(min_amps, round(target)))

                    # Ramp limit: configurable ±N amps per cycle
                    ramp_rate = int(self.config.get("ev_ramp_rate_amps", 2))
                    current = ev._current_setpoint
                    if target > current:
                        target = min(target, current + ramp_rate)
                    elif target < current:
                        target = max(target, current - ramp_rate)

                    if abs(target - current) >= 1:
                        _LOGGER.info("Night adjust: %dA->%dA (peak=%.0fW, grid=%.0fW)",
                                     current, target, peak_limit_w, power.grid_import_power)
                        await ev._set_current(target)

            _LOGGER.debug("Night EV: %dA, %.0fW, remaining=%.1fkWh",
                          ev._current_setpoint, power.ev_power, remaining_kwh)
            return

        # === NIGHT WAITING STATES: stop session if running ===
        if state in (ChargingState.NIGHT_WAITING_FOR_WINDOW,
                     ChargingState.NIGHT_TIME_EXPIRED):
            if ev._session_active:
                await ev.stop_session()
            return

        # === SOLAR CHARGING (unified, with evcc-style enable/disable delays) ===
        if state in self.SOLAR_CHARGING_STATES:
            charging_mode = self.config.get("ev_charging_mode", "pv")
            if charging_mode in ("self_consumption", "auto") and "self_consumption" in (context.charging_strategy_reason or ""):
                # Self-consumption mode (#67): EV gets only true solar surplus
                # No ev_power add-back (causes feedback loop inflating budget)
                # No battery discharge for EV (that's pv/battery_assist mode)
                auto_start_soc = self.config.get("battery_auto_start_soc", 90)
                budget_w = power.solar_power - power.home_consumption_power
                if power.battery_soc < auto_start_soc:
                    budget_w -= power.battery_charge_power  # battery charges first
                # Zone 4 (≥90%): don't subtract battery_charge — redirect to EV
                budget_w = max(0, budget_w)
            else:
                budget_w = self._calculate_solar_ev_budget(state, power, context)

            # Phase switching: auto-switch 1p/3p based on available surplus
            await ev.check_phase_switch(budget_w)
            now_ts = dt_util.now().timestamp()
            enable_delay = self.config.get("ev_enable_delay_seconds", 60)
            disable_delay = self.config.get("ev_disable_delay_seconds", 300)

            # Now mode: charge at max power immediately
            if context.charging_strategy == "now":
                budget_w = ev.max_current * ev.phases * ev.voltage
                enable_delay = 0
            # Min+PV: guarantee minimum from grid, add surplus on top
            elif state == ChargingState.SOLAR_MIN_PV:
                budget_w = max(ev.min_power_threshold, budget_w)
                enable_delay = 0  # No enable delay — guaranteed charge

            if budget_w >= ev.min_power_threshold:
                # Surplus is sufficient — track how long it's been sufficient
                self._ev_enable_surplus_since = self._ev_enable_surplus_since or now_ts

                if ev._session_active and power.ev_power > 100:
                    # Already charging — update current immediately, reset disable timer
                    target_current = min(ev.max_current,
                                         max(ev.min_current, ev.watts_to_current(budget_w)))
                    target_current = self._apply_ramp_limit(target_current)
                    await ev._set_current(target_current)
                    self._ev_charge_started_at = self._ev_charge_started_at or now_ts
                elif (now_ts - self._ev_enable_surplus_since) >= enable_delay:
                    # Surplus persisted long enough — start charging
                    target_current = min(ev.max_current,
                                         max(ev.min_current, ev.watts_to_current(budget_w)))
                    await ev._set_current(target_current)

                    if not ev._session_active or self._should_reenable_charger(power):
                        await ev.start_session(energy_target_kwh=0)
                    self._ev_charge_started_at = now_ts
                    _LOGGER.debug(
                        "Solar EV: enable delay passed (%.0fs) — starting at %.0fW, %.0fA",
                        now_ts - self._ev_enable_surplus_since, budget_w,
                        ev._current_setpoint,
                    )
                else:
                    _LOGGER.debug(
                        "Solar EV: budget=%.0fW OK, waiting enable delay (%.0fs of %ds)",
                        budget_w, now_ts - self._ev_enable_surplus_since, enable_delay,
                    )
            else:
                # Surplus insufficient — reset enable timer
                self._ev_enable_surplus_since = None

                if (self._ev_charge_started_at
                        and (now_ts - self._ev_charge_started_at) < disable_delay
                        and power.ev_power > 100):
                    # Within disable delay and actually charging — hold at minimum current
                    if ev._current_setpoint != ev.min_current:
                        await ev._set_current(ev.min_current)
                    _LOGGER.debug(
                        "Solar EV: budget=%.0fW < threshold, disable delay active "
                        "(%.0fs of %ds) — holding min current",
                        budget_w, now_ts - self._ev_charge_started_at, disable_delay,
                    )
                else:
                    # Disable delay expired or not charging — zero current
                    if ev._current_setpoint > 0:
                        await ev._set_current(0)
                    self._ev_charge_started_at = None

            _LOGGER.debug(
                "Solar EV: budget=%.0fW (%s), current=%.0fA, ev_power=%.0fW, session=%s",
                budget_w, state, ev._current_setpoint, power.ev_power,
                "active" if ev._session_active else "inactive",
            )
            return

        # === PAUSE STATES: zero current, keep session ===
        if state in self.SOLAR_PAUSE_STATES:
            if ev._current_setpoint > 0:
                await ev._set_current(0)
            return

        # === TERMINAL STATES: full stop (EV disconnected, target reached, etc.) ===
        if ev._session_active:
            await ev.stop_session()
        self._ev_stalled_since = None

    def _get_peak_limit_w(self) -> float:
        """Get peak limit in watts from load manager or config."""
        if self._load_manager:
            try:
                lm_info = self._load_manager.get_load_management_data()
                return lm_info.get("target_peak_limit", 5.0) * 1000
            except Exception:
                pass
        return self.config.get("target_peak_limit", 5.0) * 1000

    def _calculate_solar_ev_budget(
        self, state: str, power: PowerReadings, context: ChargingContext,
    ) -> float:
        """Calculate watts available for EV from solar + optional battery discharge.

        Base budget comes from FlowCalculator.calculate_ev_budget() (grid export +
        forecast-aware battery redirect). For SOLAR_SUPER_CHARGING, adds proportional
        battery discharge based on SOC zone (Zone 4: 100%, Zone 3: 50-100% ramp).

        Args:
            state: Current charging state.
            power: Current sensor readings (for battery discharge measurement).
            context: Charging context (unused directly, reserved for future use).

        Returns:
            Available power for EV in watts (>= 0).
        """
        # Read forecast for smart battery redirect
        forecast_remaining = 0
        try:
            forecast = self._forecast_reader.read_forecast()
            if forecast.available:
                forecast_remaining = forecast.forecast_remaining_today_kwh
        except Exception:
            pass

        battery_capacity = self.config.get("battery_capacity_kwh", DEFAULT_BATTERY_CAPACITY_KWH)

        # Base budget: grid export + forecast-aware battery charge redirect
        base = self._flow_calculator.calculate_ev_budget(
            power, forecast_remaining, power.battery_soc, battery_capacity,
        )

        # Battery-assist mode: ALSO add active battery discharge (proportional to SOC zone)
        if state == ChargingState.SOLAR_SUPER_CHARGING:
            floor_soc = self.config.get("battery_assist_floor_soc", 60)
            buffer_soc = self.config.get("battery_buffer_soc", 70)
            auto_start_soc = self.config.get("battery_auto_start_soc", 90)
            max_assist = self.config.get("battery_assist_max_power",
                                        self.config.get("super_charger_power", 4500))

            if power.battery_soc > floor_soc:
                battery_discharge = max(0, power.battery_discharge_power)
                if battery_discharge >= 100:
                    # Battery already discharging — use actual measured value
                    base += battery_discharge
                else:
                    # Battery not yet discharging — estimate proportional assist by SOC zone
                    if power.battery_soc >= auto_start_soc:
                        # Zone 4: full assist
                        base += max_assist
                    elif power.battery_soc >= buffer_soc:
                        # Zone 3: proportional ramp (50% at buffer_soc → 100% at auto_start_soc)
                        ratio = (power.battery_soc - buffer_soc) / max(1, auto_start_soc - buffer_soc)
                        base += max_assist * (0.5 + 0.5 * ratio)
                    # Zone 2 (below buffer_soc): no assist added — shouldn't reach here
                    # since strategy would be solar_only, but guard anyway

        return max(0, base)

    def _should_reenable_charger(self, power: PowerReadings) -> bool:
        """Detect if EV charger was externally disabled and needs re-enabling.

        Works with any charger (KEBA, Wallbox, Easee, etc.) — if SEM set
        a current >= min but the charger reports no power, it may have been
        externally disabled or stalled. Re-enable after cooldown.
        """
        ev = self._ev_device
        if not ev._session_active:
            return False
        # SEM set current >= min but charger reports no power → stalled
        if (ev._current_setpoint >= ev.min_current
                and power.ev_power < 50
                and power.ev_connected):
            if self._ev_stalled_since is None:
                self._ev_stalled_since = dt_util.now().timestamp()
                return False
            if dt_util.now().timestamp() - self._ev_stalled_since > 30:
                _LOGGER.warning("EV charger stalled (setpoint=%.0fA, power=%.0fW) — re-enabling",
                                ev._current_setpoint, power.ev_power)
                self._ev_stalled_since = None
                return True
        else:
            self._ev_stalled_since = None
        return False

    def _calculate_forecast_night_target(
        self, remaining_kwh: float, energy: Any,
    ) -> float:
        """Reduce night charging target based on tomorrow's solar forecast.

        Uses history-based daily averages for home consumption and battery charge,
        and adjusts for weekday vs weekend (car availability differs).

        Weekdays: car arrives ~17:00, only ~20% of surplus reachable
        Weekends: car connected all day, ~70% of surplus reachable

        Args:
            remaining_kwh: Raw remaining EV energy need (daily_target - daily_ev).
            energy: EnergyData with monthly_home, monthly_battery_charge.

        Returns:
            Adjusted remaining kWh for night charging.
        """
        if remaining_kwh <= 0:
            return 0

        try:
            forecast = self._forecast_reader.read_forecast()
            if not forecast.available or forecast.forecast_tomorrow_kwh <= 0:
                return remaining_kwh
        except Exception:
            return remaining_kwh

        now = dt_util.now()
        tomorrow = now + timedelta(days=1)
        is_weekend = tomorrow.weekday() >= 5

        # Use real monthly averages if enough data (7+ days), else config defaults
        day_of_month = now.day
        if day_of_month >= 7 and energy.monthly_home > 0:
            avg_daily_home = energy.monthly_home / day_of_month
            avg_daily_battery = energy.monthly_battery_charge / day_of_month
        else:
            avg_daily_home = self.config.get("daily_home_consumption_estimate", 18.0)
            avg_daily_battery = self.config.get("daily_battery_consumption_estimate", 10.0)

        # Surplus available for EV tomorrow
        available_for_ev = max(0, forecast.forecast_tomorrow_kwh - avg_daily_home - avg_daily_battery)

        if is_weekend:
            ev_expected = available_for_ev * 0.7
        else:
            ev_expected = available_for_ev * 0.2

        reduction = min(remaining_kwh, ev_expected)
        day_type = "weekend" if is_weekend else "weekday"

        if reduction > 0.5:
            _LOGGER.info(
                "Night forecast adjustment (%s): -%.1fkWh "
                "(tomorrow=%.1fkWh, avg_home=%.1fkWh, avg_battery=%.1fkWh, "
                "available=%.1fkWh, ev_expected=%.1fkWh)",
                day_type, reduction, forecast.forecast_tomorrow_kwh,
                avg_daily_home, avg_daily_battery, available_for_ev, ev_expected,
            )

        return max(0, remaining_kwh - reduction)

    def _apply_ramp_limit(self, target_current: float) -> float:
        """Limit current changes to ±ramp_rate per cycle during solar charging.

        Prevents sudden jumps that stress inverter/grid. Starting from 0A jumps
        directly (can't ramp below min_current). Stopping drops immediately.
        Config: ev_ramp_rate_amps (default 2).

        Args:
            target_current: Desired current in amps.

        Returns:
            Ramp-limited current in amps.
        """
        ev = self._ev_device
        current = ev._current_setpoint
        ramp = self.config.get("ev_ramp_rate_amps", 2)

        if current < 1.0:       # Starting from 0 → jump directly
            return target_current
        if target_current < 1.0:  # Stopping → drop immediately
            return 0

        return max(current - ramp, min(current + ramp, target_current))

    def _update_session_tracking(self, power: PowerReadings, power_flows: PowerFlows) -> None:
        """Track per-session energy, cost, and source attribution.

        Runs every cycle. Detects session start (ev_power > 50W), accumulates
        solar/grid/battery energy from power flows, calculates cost and solar
        share. Session ends when EV disconnects (data kept for display).

        Args:
            power: Current sensor readings (ev_power, ev_connected).
            power_flows: Instantaneous power flow distribution (solar/grid/battery to EV).
        """
        update_interval = self.config.get("update_interval", DEFAULT_UPDATE_INTERVAL)
        hours = update_interval / 3600.0

        # Detect session end: EV was connected, now disconnected
        if self._last_ev_connected and not power.ev_connected:
            # Session ended — update lifetime stats and keep data for display
            if self._session_data.active and self._session_data.energy_kwh > 0.1:
                if self._storage:
                    self._storage.update_lifetime_ev_stats(
                        session_energy=self._session_data.energy_kwh,
                        solar_energy=self._session_data.solar_energy_kwh,
                        grid_energy=self._session_data.grid_energy_kwh,
                        battery_energy=self._session_data.battery_energy_kwh,
                        cost=self._session_data.cost_chf,
                    )
                    _LOGGER.info(
                        "Session ended: %.1fkWh (%.0f%% solar), lifetime: %s",
                        self._session_data.energy_kwh,
                        self._session_data.solar_share_pct,
                        self._storage.get_lifetime_ev_stats(),
                    )
            self._session_data.active = False
            self._last_ev_connected = False
            return

        self._last_ev_connected = power.ev_connected

        # Detect session start: EV charging and no active session
        if power.ev_power > 50 and not self._session_data.active:
            self._session_data = SessionData(
                active=True,
                start_time=dt_util.now().isoformat(),
            )

        if not self._session_data.active:
            return

        # Accumulate energy from flow sources (W → kWh)
        solar_increment = power_flows.solar_to_ev * hours / 1000.0
        grid_increment = power_flows.grid_to_ev * hours / 1000.0
        battery_increment = power_flows.battery_to_ev * hours / 1000.0

        self._session_data.solar_energy_kwh += solar_increment
        self._session_data.grid_energy_kwh += grid_increment
        self._session_data.battery_energy_kwh += battery_increment
        self._session_data.energy_kwh = (
            self._session_data.solar_energy_kwh
            + self._session_data.grid_energy_kwh
            + self._session_data.battery_energy_kwh
        )

        # Cost: grid portion × current import rate
        import_rate = self._energy_calculator._import_rate
        self._session_data.cost_chf += grid_increment * import_rate

        # Solar share
        if self._session_data.energy_kwh > 0:
            self._session_data.solar_share_pct = round(
                self._session_data.solar_energy_kwh / self._session_data.energy_kwh * 100, 1
            )

        # Duration and average power
        try:
            from datetime import datetime
            start = datetime.fromisoformat(self._session_data.start_time)
            now = dt_util.now()
            self._session_data.duration_minutes = round(
                (now - start).total_seconds() / 60.0, 1
            )
        except (ValueError, TypeError):
            pass

        if self._session_data.duration_minutes > 0:
            self._session_data.avg_power_w = round(
                self._session_data.energy_kwh * 60000.0 / self._session_data.duration_minutes, 0
            )
