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
from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any, Optional

from homeassistant.util import dt as dt_util

from ..const import (
    ChargingState,
    DEFAULT_BATTERY_CAPACITY_KWH,
    DEFAULT_EV_TARGET_TIME,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VOLTAGE_PER_PHASE,
    EV_DEADLINE_LOOKAHEAD_HOURS,
)
from .types import PowerReadings, PowerFlows, SessionData
from .charging_control import ChargingContext
from .ev_tariff_planner import NightChargePlan, plan_night_charge

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

    def _get_active_charger_config(self) -> dict:
        """Get config dict for the currently active charger (#193).

        Returns the per-charger config from ev_chargers[] if available,
        otherwise an empty dict (caller falls back to global config).
        """
        ev_device = getattr(self, '_ev_device', None)
        if ev_device is None:
            return {}
        device_id = getattr(ev_device, 'device_id', None)
        if device_id is None:
            return {}
        ev_chargers = self.config.get("ev_chargers", [])
        for cfg in ev_chargers:
            if cfg.get("id") == device_id:
                return cfg
        return {}

    def _tariff_optimized_for(self, charger_cfg: dict) -> bool:
        """True when tariff-optimized timing is enabled for this charger (#247).

        Per-charger ``switch.sem_charger_{id}_tariff_optimized`` (opt-in,
        default OFF) — created in ``switch.py`` for every config-flow charger.
        Returns False when there is no charger config (``ev_chargers`` empty),
        which can only happen pre-setup; #281/S2 removed the dead legacy
        ``switch.sem_tariff_optimized`` fallback (that switch was never created).
        """
        hass = getattr(self, "hass", None)
        if hass is None:
            return False
        cid = charger_cfg.get("id") if charger_cfg else None
        if not cid:
            return False
        return hass.states.is_state(
            f"switch.sem_charger_{cid}_tariff_optimized", "on"
        )

    def _charger_target_time(self, charger_cfg: dict) -> str:
        """Per-charger ``HH:MM`` charge-by deadline (#246), or global / default."""
        cfg = charger_cfg or {}
        val = cfg.get("ev_target_time")
        if val is None:
            val = self.config.get("ev_target_time", DEFAULT_EV_TARGET_TIME)
        return val or DEFAULT_EV_TARGET_TIME

    def _compute_night_plan(
        self, charger_cfg: dict, remaining_to_min_kwh: float, energy: Any = None,
    ) -> NightChargePlan:
        """Build the per-charger night charge plan (deadline + tariff) (#246/#247).

        Gathers the inputs (deadline, charger current limits, tariff price
        window) and delegates the decision to the pure ``plan_night_charge``.
        Safe to call every cycle — degrades to a plain "charge now" plan when no
        deadline / tariff data is available.
        """
        cfg = charger_cfg or {}

        def _pc(key, default):
            v = cfg.get(key)
            return v if v is not None else self.config.get(key, default)

        min_amps = int(_pc("ev_min_current", 6))
        max_amps = int(self.config.get("ev_max_current", 32))
        ev = getattr(self, "_ev_device", None)
        if ev is not None:
            max_amps = int(getattr(ev, "max_current", max_amps))
        phases = int(_pc("ev_phases", 3))
        watts_per_amp = phases * DEFAULT_VOLTAGE_PER_PHASE

        tariff_optimized = self._tariff_optimized_for(cfg)
        target_time = self._charger_target_time(cfg)
        # Split try blocks (#281/D4): a single try around both would let a
        # later failure overwrite an earlier successful read.
        try:
            night_end = self.time_manager.get_night_end_time()
        except (ValueError, AttributeError):
            night_end = DEFAULT_EV_TARGET_TIME
        try:
            window_h = self.time_manager.get_night_window_hours()
        except (ValueError, AttributeError):
            window_h = 8.0

        # Realistic peak-managed rate (#274/C1): night charging is sized from the
        # house load to keep grid import <= the peak limit, so the rate the car
        # actually sustains is (peak_limit - expected home consumption) / W-per-A,
        # NOT the charger max. Using the learned overnight consumption pattern (or
        # the rolling monthly average) here is what stops the planner waiting for a
        # cheap window it can't fill at the peak-limited rate and then missing Min.
        peak_limit_w = self._get_peak_limit_w()
        expected_home_w = self._expected_night_home_w(energy, window_h)
        # Subtract draw already committed to higher-priority chargers this cycle
        # so the fleet shares one peak budget (#274/H1).
        committed_w = getattr(self, "_night_committed_w", 0.0)
        peak_managed_amps = max(
            min_amps,
            min(max_amps, round((peak_limit_w - expected_home_w - committed_w) / watts_per_amp)),
        )
        peak_rate_kw = max(0.1, peak_managed_amps * watts_per_amp / 1000.0)

        # Cheapest contiguous window covering the remaining need (block-wise) (#247).
        # Size the request at the realistic peak-managed rate so we fetch enough
        # cheap hours to actually cover Min (#274/H2 slot length inferred below).
        #
        # Cap the lookahead at hours-to-deadline (#281): otherwise a post-deadline
        # price dip (e.g. 08:00–10:00 cheapest when deadline is 07:00) can be
        # selected as "the cheap window". The planner then clips it to 0
        # deliverable kWh and silently falls back to charge-now — ignoring the
        # real pre-deadline cheap window. Bound the request to the actual window
        # we can charge in.
        cheap_slots = None
        slot_hours = 1.0
        if tariff_optimized and remaining_to_min_kwh > 0.1:
            tariff = getattr(self, "_tariff_provider", None)
            if tariff is not None and hasattr(tariff, "find_cheapest_hours"):
                try:
                    hours_needed = max(1, int(remaining_to_min_kwh / peak_rate_kw + 0.999))
                    # Pre-deadline horizon — fall back to the global lookahead
                    # only when the deadline can't be resolved (target_time blank).
                    from .ev_tariff_planner import resolve_deadline, _hours_between
                    now = dt_util.now()
                    deadline_dt = (
                        resolve_deadline(now, target_time)
                        or resolve_deadline(now, night_end)
                    )
                    if deadline_dt is not None:
                        hours_to_deadline = max(
                            1, int(_hours_between(now, deadline_dt) + 0.999),
                        )
                        lookahead = min(
                            int(EV_DEADLINE_LOOKAHEAD_HOURS), hours_to_deadline,
                        )
                    else:
                        lookahead = int(EV_DEADLINE_LOOKAHEAD_HOURS)
                    points = tariff.find_cheapest_hours(
                        hours_needed,
                        within_hours=lookahead,
                        prefer_consecutive=True,
                    )
                    cheap_slots = [p.timestamp for p in points] if points else None
                    # Infer slot length from the consecutive block (#274/H2):
                    # 30/15-min markets must not be counted as full hours.
                    if cheap_slots and len(cheap_slots) >= 2:
                        gap = (cheap_slots[1] - cheap_slots[0]).total_seconds() / 3600.0
                        if 0 < gap <= 1.0:
                            slot_hours = gap
                except (ValueError, TypeError, AttributeError) as e:
                    _LOGGER.debug("Tariff cheap-window lookup failed: %s", e)

        plan = plan_night_charge(
            now=dt_util.now(),
            remaining_to_min_kwh=remaining_to_min_kwh,
            min_amps=min_amps,
            max_amps=max_amps,
            watts_per_amp=watts_per_amp,
            target_time=target_time,
            night_end=night_end,
            tariff_optimized=tariff_optimized,
            cheap_slots=cheap_slots,
            slot_hours=slot_hours,
            peak_managed_amps=peak_managed_amps,
        )

        # Hysteresis (#274/M4): hold the previous wait↔charge decision until the
        # dwell elapses, so a price hovering at the cheap/expensive boundary
        # doesn't stop/start the charger (contactor cycling) every cycle.
        if tariff_optimized:
            cid = cfg.get("id", "ev_charger")
            dwell = int(self.config.get("ev_tariff_dwell_seconds", 600))
            decisions = getattr(self, "_tariff_decision_per_charger", None)
            if decisions is None:
                decisions = self._tariff_decision_per_charger = {}
            now_ts = dt_util.now().timestamp()
            prev = decisions.get(cid)
            if (prev is not None
                    and plan.should_wait_for_cheap != prev[0]
                    and (now_ts - prev[1]) < dwell):
                plan.should_wait_for_cheap = prev[0]  # hold within dwell
            if prev is None or prev[0] != plan.should_wait_for_cheap:
                decisions[cid] = (plan.should_wait_for_cheap, now_ts)

        return plan

    def _expected_night_home_w(self, energy: Any, window_hours: float = 8.0) -> float:
        """Expected average home consumption (W) over the upcoming night window.

        Reuses the learned hourly consumption pattern (ConsumptionPredictor) when
        it's trained — averaging the first ``window_hours`` of its 24h forecast,
        which are the night hours — then falls back to the rolling monthly-average
        daily home / 24h, then the config estimate. Same sources
        ``_calculate_forecast_night_target`` already uses; pulled out so the
        peak-aware night plan (#274/C1) sizes the charge rate from real data.
        """
        now = dt_util.now()
        predictor = getattr(self, "_predictor", None)
        if predictor is not None:
            try:
                hourly = predictor.predict_consumption_24h(now)  # W per hour
                n = max(1, min(len(hourly), int(round(window_hours)) or 1))
                window = [v for v in hourly[:n] if v is not None]
                if window:
                    return max(0.0, sum(window) / len(window))
            except Exception:
                pass
        day = now.day
        if energy is not None and day >= 7 and getattr(energy, "monthly_home", 0) > 0:
            return max(0.0, energy.monthly_home / day / 24.0 * 1000.0)
        return max(0.0, self.config.get("daily_home_consumption_estimate", 18.0) / 24.0 * 1000.0)

    async def _maybe_warn_unreachable_deadline(
        self, cid: str, charger_cfg: dict, plan: NightChargePlan,
    ) -> None:
        """Notify (once) when a charge target can't be met by its deadline (#246).

        Clears the warning flag the moment the deadline becomes reachable again,
        so a forecast that flips reachable/unreachable doesn't spam.
        """
        nm = getattr(self, "_notification_manager", None)
        if nm is None or plan.deadline_dt is None:
            return
        name = (charger_cfg or {}).get("name") or "EV"
        flag_key = cid or (charger_cfg or {}).get("id") or name  # dedup by id (#274/M3)
        # Only warn when the user opted into deadline/tariff behaviour (#274/C1) —
        # plan.should_warn_unreachable already encodes (not reachable) AND
        # (forcing OR tariff). Otherwise clear any prior warning.
        if not plan.should_warn_unreachable:
            nm.clear_deadline_warning(charger_name=name, flag_key=flag_key)
            return
        try:
            await nm.notify_ev_deadline_unreachable(
                remaining_kwh=plan.remaining_kwh,
                hours_left=plan.hours_to_deadline or 0.0,
                deadline=plan.deadline_dt.strftime("%H:%M"),
                charger_name=name,
                flag_key=flag_key,
            )
        except Exception as e:  # notifications must never break the control loop
            _LOGGER.debug("Deadline-unreachable notify failed: %s", e)

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
            # Multi-charger (#112): use per-charger night target if distributed
            per_charger_night = getattr(self, "_night_target_per_charger", None)
            remaining_kwh = per_charger_night if per_charger_night is not None else context.night_target_kwh

            # Guard: target reached
            if remaining_kwh <= 0.1:
                if ev._session_active:
                    await ev.stop_session()
                return

            # Detect already-charging after SEM reload (don't interrupt)
            if not ev._session_active and power.ev_power > 50:
                ev._session_active = True
                _LOGGER.info("Night: KEBA already active (%.0fW), resuming", power.ev_power)

            # Read configurable EV parameters — per-charger overrides (#193)
            charger_cfg = self._get_active_charger_config()
            initial_amps = int(charger_cfg.get(
                "ev_night_initial_current",
                self.config.get("ev_night_initial_current", 10),
            ))
            min_amps = int(charger_cfg.get(
                "ev_min_current",
                self.config.get("ev_min_current", 6),
            ))
            stall_cooldown = int(self.config.get("ev_stall_cooldown", 120))

            # Deadline floor (#246): the planner's required current to reach Min
            # by the target time. When active, it overrides both the gentle ramp
            # and the peak cap (the user opted into "be ready by HH:MM", so the
            # car may draw grid above the peak limit to make the deadline).
            deadline_amps = int(getattr(context, "night_deadline_amps", 0) or 0)
            deadline_active = bool(getattr(context, "night_deadline_active", False))
            deadline_floor = min(deadline_amps, ev.max_current) if deadline_active else 0

            if not ev._session_active:
                # Fresh start: set_current BEFORE start_session
                # (KEBA ignores enable at 0A). Cap the kickstart to the peak
                # headroom too: the car is not drawing yet, so estimate W/A from
                # phases*voltage. Without this the first cycle starts at
                # initial_amps (default 10A ~ 6.9kW) which alone can exceed the
                # peak limit before the dynamic loop takes over.
                est_wpa = ev.phases * ev.voltage
                peak_amps = self._night_peak_managed_amps(
                    power, est_wpa, min_amps, ev.max_current)
                initial_current = min(initial_amps, peak_amps)
                if deadline_floor > initial_current:
                    initial_current = deadline_floor  # deadline overrides gentle start
                await ev._set_current(initial_current)
                await ev.start_session(energy_target_kwh=0)
                self._ev_last_change_time = dt_util.now()
                _LOGGER.info(
                    "Night start: %dA, target=%.1fkWh%s", initial_current, remaining_kwh,
                    f" (deadline floor {deadline_floor}A)" if deadline_floor else "",
                )
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
                    target = self._night_peak_managed_amps(
                        power, watts_per_amp, min_amps, ev.max_current)
                    peak_limit_w = self._get_peak_limit_w()  # for the log line

                    # Ramp limit: configurable ±N amps per cycle
                    ramp_rate = int(self.config.get("ev_ramp_rate_amps", 2))
                    current = ev._current_setpoint
                    if target > current:
                        target = min(target, current + ramp_rate)
                    elif target < current:
                        target = max(target, current - ramp_rate)

                    # Deadline floor (#246): raise to the required current,
                    # jumping past the gentle ramp limit when time is short.
                    if deadline_floor > target:
                        target = deadline_floor

                    if abs(target - current) >= 1:
                        _LOGGER.info(
                            "Night adjust: %dA->%dA (peak=%.0fW, grid=%.0fW%s)",
                            current, target, peak_limit_w, power.grid_import_power,
                            f", deadline floor {deadline_floor}A" if deadline_floor else "",
                        )
                        await ev._set_current(target)

            _LOGGER.debug("Night EV: %dA, %.0fW, remaining=%.1fkWh",
                          ev._current_setpoint, power.ev_power, remaining_kwh)
            return

        # === NIGHT WAITING STATES: stop session if running ===
        # TARIFF_WAITING_FOR_CHEAP (#247) waits for a cheaper price window — the
        # Min floor is still guaranteed before the deadline (the planner only
        # parks here when waiting can still meet Min in time).
        if state in (ChargingState.NIGHT_WAITING_FOR_WINDOW,
                     ChargingState.NIGHT_TIME_EXPIRED,
                     ChargingState.TARIFF_WAITING_FOR_CHEAP):
            if ev._session_active:
                await ev.stop_session()
            return

        # === SOLAR CHARGING (unified, with evcc-style enable/disable delays) ===
        if state in self.SOLAR_CHARGING_STATES:
            # Multi-charger (#112): use pre-distributed budget if available
            per_charger_budget = getattr(self, "_current_charger_budget", None)
            if per_charger_budget is not None:
                budget_w = per_charger_budget
            else:
                # Canonical EV budget (#282 unification, Phase B). The
                # coordinator caches `self._cycle_ev_budget` per cycle —
                # it's an EVBudget instance carrying the same value the
                # state machine just used to decide we should be charging,
                # so the actuator and the state machine can never
                # disagree about how much power is available.
                #
                # The three legacy ad-hoc paths this replaces:
                #   - self_consumption-via-reason-text match (the path
                #     that disagreed with the state machine, root of #282)
                #   - _calculate_solar_ev_budget (still callable for now;
                #     removed in Phase D)
                #   - the inline "solar - home - batt_charge" arithmetic
                # All three are now in flow_calculator.calculate_canonical_ev_budget.
                cycle_budget = getattr(self, "_cycle_ev_budget", None)
                if cycle_budget is not None:
                    budget_w = cycle_budget.net_w
                else:
                    # Fallback for paths where the canonical budget wasn't
                    # computed (shouldn't happen in normal operation — guard
                    # for tests or partial init).
                    budget_w = self._calculate_solar_ev_budget(state, power, context)

            # Phase switching: auto-switch 1p/3p based on available surplus
            await ev.check_phase_switch(budget_w)
            now_ts = dt_util.now().timestamp()
            enable_delay = self.config.get("ev_enable_delay_seconds", 60)
            disable_delay = self.config.get("ev_disable_delay_seconds", 300)

            # Now mode and Min+PV overrides remain HERE (not in the
            # canonical budget) because they depend on PER-CHARGER
            # parameters (ev.max_current, ev.min_power_threshold) that
            # the cycle-level budget doesn't see — multi-charger fleets
            # have different overrides per charger.
            if context.charging_strategy == "now":
                budget_w = ev.max_current * ev.phases * ev.voltage
                enable_delay = 0
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
        self._ev_reenable_attempts = 0
        self._ev_charge_refused = False

    def _get_peak_limit_w(self) -> float:
        """Get peak limit in watts from load manager or config."""
        if self._load_manager:
            try:
                lm_info = self._load_manager.get_load_management_data()
                return lm_info.get("target_peak_limit", 5.0) * 1000
            except Exception:
                pass
        return self.config.get("target_peak_limit", 5.0) * 1000

    def _night_peak_managed_amps(
        self,
        power: PowerReadings,
        watts_per_amp: float,
        min_amps: int,
        max_amps: int,
    ) -> int:
        """Charging current that keeps grid import <= the peak limit at night.

        Sized from the pure house load (``home_consumption_power``), NOT from
        ``grid_import - ev_power``. The latter equals ``home + batt_charge -
        batt_discharge`` (see ``PowerReadings.calculate_derived``), so battery
        discharge drives it negative and inflates the apparent headroom — the EV
        ramps up while the battery is discharging, then grid import overshoots
        the peak the instant the battery backs off (observed on PROD: EV 10kW /
        grid 10kW against a 6kW limit). ``home_consumption_power`` excludes both
        EV and battery, so ``grid = home + ev`` stays <= peak regardless of what
        the battery does — night charging must not lean on the home battery
        (the battery may still reduce grid below peak, it is just never relied
        upon). Result is clamped to ``[min_amps, max_amps]``.

        Residual limitation: if the inverter autonomously charges the battery
        from the grid during the night window (e.g. a dynamic-tariff or timed
        grid-charge SEM does not command), ``grid = peak + net_batt_charge`` and
        the peak may still be exceeded by that charge. SEM cannot size around
        inverter-managed charging it doesn't control.

        Multi-charger (#274/H1): also subtract the draw already committed to
        higher-priority chargers this cycle (``_night_committed_w``), so a fleet
        of chargers shares one peak budget instead of each independently sizing to
        the full ``peak - home`` headroom and summing past the limit.
        """
        committed_w = getattr(self, "_night_committed_w", 0.0)
        headroom_w = self._get_peak_limit_w() - power.home_consumption_power - committed_w
        target = round(headroom_w / max(1.0, watts_per_amp))
        return min(max_amps, max(min_amps, target))

    def _calculate_solar_ev_budget(
        self, state: str, power: PowerReadings, context: ChargingContext,
    ) -> float:
        """Calculate watts available for EV from solar + optional battery discharge.

        Base budget comes from FlowCalculator.calculate_ev_budget(). For
        ``charging_strategy == "solar_only"`` we pass ``solar_only=True``
        so the budget is hard-capped at ``solar - home`` and the actuator
        can never silently leak grid into the EV (#282 / Scenario 0).
        For SOLAR_SUPER_CHARGING (battery-assist mode), the proportional
        battery discharge branch below still adds on top.

        Args:
            state: Current charging state.
            power: Current sensor readings (for battery discharge measurement).
            context: Charging context. ``context.charging_strategy`` selects
                surplus-only vs legacy semantics.

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

        # Hard surplus cap when strategy is solar_only. Without this, the
        # budget falls back to the legacy ``ev_power + grid_export`` baseline
        # which silently allows the EV to keep drawing whatever the car asks
        # for, with grid filling any gap.
        solar_only_active = (
            getattr(context, "charging_strategy", None) == "solar_only"
        )

        # Base budget: grid export + forecast-aware battery charge redirect.
        # When solar_only is active, calculate_ev_budget enforces the
        # surplus ceiling via max(0, solar - home) instead of ev_power.
        base = self._flow_calculator.calculate_ev_budget(
            power, forecast_remaining, power.battery_soc, battery_capacity,
            solar_only=solar_only_active,
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

        False-stall guard (#243): a car left plugged in at ~100% SOC never
        draws power despite an offered current, which would otherwise re-enable
        (and log a warning) on every cycle forever. After a few failed
        re-enables we conclude the car is not accepting charge (likely full),
        latch ``_ev_charge_refused``, log once, and go quiet. The latch clears
        the moment the car actually draws power (>=50 W), is unplugged, or SEM
        stops offering current — so genuine stalls still self-heal within the
        first few attempts and a re-plug starts fresh. Charger-agnostic; does
        not depend on SOC estimation.
        """
        ev = self._ev_device
        if not ev._session_active:
            return False
        # SEM set current >= min but charger reports no power → stalled
        if (ev._current_setpoint >= ev.min_current
                and power.ev_power < 50
                and power.ev_connected):
            # Car already deemed not-accepting this session — stay quiet
            if getattr(self, "_ev_charge_refused", False):
                return False
            if self._ev_stalled_since is None:
                self._ev_stalled_since = dt_util.now().timestamp()
                return False
            if dt_util.now().timestamp() - self._ev_stalled_since > 30:
                self._ev_stalled_since = None
                max_attempts = int(self.config.get("ev_max_reenable_attempts", 3))
                self._ev_reenable_attempts = getattr(self, "_ev_reenable_attempts", 0) + 1
                if self._ev_reenable_attempts > max_attempts:
                    # Car keeps refusing — likely full. Stop re-enabling.
                    self._ev_charge_refused = True
                    _LOGGER.info(
                        "EV not accepting charge after %d re-enable attempts "
                        "(setpoint=%.0fA, power=%.0fW) — car likely full; "
                        "pausing re-enable until power resumes or car unplugged",
                        max_attempts, ev._current_setpoint, power.ev_power,
                    )
                    return False
                _LOGGER.warning(
                    "EV charger stalled (setpoint=%.0fA, power=%.0fW) — "
                    "re-enabling (attempt %d/%d)",
                    ev._current_setpoint, power.ev_power,
                    self._ev_reenable_attempts, max_attempts,
                )
                return True
        else:
            # Healthy: car drawing power, disconnected, or no current offered.
            self._ev_stalled_since = None
            self._ev_reenable_attempts = 0
            self._ev_charge_refused = False
        return False

    def _calculate_forecast_night_target(
        self, remaining_kwh: float, energy: Any, charger_cfg: dict | None = None,
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

        # EV Intelligence SOC-based skip runs FIRST — independent of forecast (#106)
        # This must be before the forecast check, because forecast may be unavailable
        ev_taper = getattr(self, "_ev_taper_detector", None)
        if ev_taper and (ev_taper.last_full_timestamp or ev_taper._soc_anchored):
            now = dt_util.now()
            estimated_soc = ev_taper.get_virtual_soc(
                getattr(self, "_cycle_vehicle_soc", None)
            )
            # Per-car target/capacity (one car per charger); fall back to global.
            _cfg = charger_cfg or {}
            def _pc(key, default):
                v = _cfg.get(key)
                return v if v is not None else self.config.get(key, default)
            target_soc = _pc("ev_target_soc", 80)
            min_soc = _pc("ev_min_soc_threshold", 20)
            capacity = _pc("ev_battery_capacity_kwh", 40)

            predicted_daily = 0.0
            predictor = getattr(self, "_predictor", None)
            if predictor:
                predicted_daily = predictor.predict_ev_consumption_tomorrow(now)

            predicted_soc_drop = (predicted_daily / capacity * 100) if capacity > 0 else 0

            if estimated_soc > target_soc:
                _LOGGER.info(
                    "EV charge skip: SOC %.0f%% > target %d%%, skipping night charge",
                    estimated_soc, target_soc,
                )
                return 0.0

            safety = 1.3
            if predicted_soc_drop > 0 and (estimated_soc - predicted_soc_drop * safety) > min_soc:
                nights = int((estimated_soc - min_soc) / predicted_soc_drop)
                _LOGGER.info(
                    "EV charge skip: SOC %.0f%%, predicted daily %.0f%%, %d nights range",
                    estimated_soc, predicted_soc_drop, nights,
                )
                return 0.0

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

        adjusted = max(0, remaining_kwh - reduction)

        return adjusted

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
