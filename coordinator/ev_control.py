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
        """True when this charger's mode defers to cheap tariff windows.

        Post-#277 Phase C: derived from the named ``charge_mode``
        (only ``solar_plus_cheap`` defers — every other mode either
        always charges, never charges, or follows zone/surplus rules
        without tariff awareness). The legacy
        ``switch.sem_charger_{id}_tariff_optimized`` was removed in
        Phase C; this helper kept the same name so the existing
        callers (``ev_control`` planner, today_plan composer, EV card
        attributes) didn't have to change.

        Returns False on missing config or hass — defensive only;
        every supported install has ``charge_mode`` set post-v5
        migration so the resolver always answers.
        """
        hass = getattr(self, "hass", None)
        if hass is None or not isinstance(charger_cfg, dict):
            return False
        from ..consts.ev_charge_modes import (
            MODE_USES_TARIFF,
            effective_charge_mode_for,
        )
        return effective_charge_mode_for(
            hass, self.config, charger_cfg,
        ) in MODE_USES_TARIFF

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

        # v1.6.8: cache this charger's power once per call. Avoids reading
        # the global fleet sum (``power.ev_power``) when we mean THIS
        # charger's draw — exactly the bug class that caused the v1.6.5
        # KEBA self-resume regression and the broader sweep this release
        # ships. See ``docs/MULTI_CHARGER.md`` for the invariant.
        this_power_w = self._this_charger_power(ev, power)

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
            if not ev._session_active and this_power_w > 50:
                ev._session_active = True
                _LOGGER.info("Night: KEBA already active (%.0fW), resuming", this_power_w)

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
                if this_power_w > 100:
                    # W/A from actual charger readings (adapts to any car)
                    watts_per_amp = this_power_w / max(1, ev._current_setpoint)
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
                          ev._current_setpoint, this_power_w, remaining_kwh)
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
                # Canonical EV budget — Phase D.2 cleanup (#282).
                # ``self._cycle_ev_budget`` is set unconditionally every
                # cycle by ``_build_charging_context``, so this branch's
                # only failure mode is "coordinator init incomplete"
                # (config-flow midway / fixture wrong shape / something
                # else loud). Fail-safe: log + return 0 W = no charge
                # this cycle. Was a legacy-formula fallback pre-D.2;
                # carrying two budget formulas was exactly the
                # disagreement-class root cause we removed in the
                # unification arc.
                cycle_budget = getattr(self, "_cycle_ev_budget", None)
                if cycle_budget is None:
                    _LOGGER.error(
                        "Canonical EV budget not set this cycle — "
                        "coordinator init bug. Falling through with 0 W "
                        "budget (no charge this cycle) to fail safe. "
                        "Investigate _build_charging_context."
                    )
                    budget_w = 0.0
                else:
                    budget_w = cycle_budget.net_w

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

                if ev._session_active and this_power_w > 100:
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
                        and this_power_w > 100):
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
                budget_w, state, ev._current_setpoint, this_power_w,
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
        elif (
            context.charging_strategy == "disabled"
            and self._this_charger_drawing_power(ev, power)
        ):
            # User intent is mode=off but the charger is physically drawing
            # real power that SEM doesn't own (#315). KEBA P30 is the
            # canonical example: its firmware self-resumes on plug-in or
            # after certain internal events using a stored setpoint,
            # completely independent of SEM. Since SEM never started a
            # session here, `_session_active` is False and the branch
            # above is skipped, but the charger keeps drawing. Force-call
            # stop_session to invoke the per-brand disable (e.g.
            # ``keba.disable``) every cycle until ev_power drops below
            # the 500 W threshold (handshake idle is 100–200 W; real
            # charging starts at 4140 W). Idempotent — safe to call on
            # an already-disabled charger.
            await ev.stop_session()
            # Suppress the per-cycle INFO log from stop_session() once
            # we've logged it for this self-resume episode. The
            # device's stop_session() emits an INFO line every call;
            # without throttling, a stuck-resuming KEBA would print
            # "Charging session stopped via keba.disable" every 10 s
            # for hours. Re-enable the log when ev_power finally
            # drops below threshold so the next episode is loud again.
            if getattr(self, "_off_mode_stop_logged_for", None) != ev.device_id:
                _LOGGER.warning(
                    "Charger %s self-resumed while mode=off (drawing %.0fW). "
                    "Calling stop_session() — will re-assert every cycle "
                    "until ev_power drops below 500W. (#315)",
                    ev.name, self._this_charger_power(ev, power),
                )
                self._off_mode_stop_logged_for = ev.device_id
        elif (
            context.charging_strategy == "disabled"
            and getattr(self, "_off_mode_stop_logged_for", None) == ev.device_id
        ):
            # Charger settled below threshold — clear the log-suppression
            # flag so the next self-resume episode logs loudly again.
            self._off_mode_stop_logged_for = None

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

    def _get_peak_15min_w(self) -> Optional[float]:
        """Read the rolling 15-min consecutive peak (#288), in watts.

        Returns ``None`` when the load manager hasn't been initialized or
        hasn't accumulated enough samples yet — the caller should fall back
        to the legacy ``home_consumption_power`` formula in that case.

        Why this metric: most demand-charge tariffs bill on a 15-min rolling
        average of grid import. Sizing EV current against this same metric
        means the per-cycle throttle decision agrees with the billing
        decision and naturally tolerates short stepovers (a one-cycle
        spike barely moves the rolling average). It also sidesteps the
        sensor-lag class of bugs in the derived ``home_consumption_power``
        — the rolling already smooths out individual sensor glitches.
        """
        if not self._load_manager:
            return None
        try:
            lm_info = self._load_manager.get_load_management_data()
            kw = lm_info.get("consecutive_peak_15min")
            if kw is None or kw < 0:
                return None
            return float(kw) * 1000.0
        except Exception:
            return None

    def _night_peak_managed_amps(
        self,
        power: PowerReadings,
        watts_per_amp: float,
        min_amps: int,
        max_amps: int,
    ) -> int:
        """Charging current that keeps grid import <= the peak limit at night.

        Sizing uses the **rolling 15-min consecutive grid-import peak**
        (#288) when available — the same metric most demand-charge
        tariffs bill on. This makes the per-cycle throttle decision
        agree with the billing decision, naturally tolerates short
        stepovers (a one-cycle spike barely moves a 15-min rolling
        average), and sidesteps the sensor-lag bugs in the derived
        ``home_consumption_power`` (observed on PROD 2026-05-29: brief
        7.9 kW grid spike during EV ramp-up because the EV-power sensor
        lagged by 5 kW for several seconds, deflating
        ``home_consumption_power`` toward 0 and giving the EV the full
        peak_limit as headroom).

        Self-balancing semantics: the rolling already INCLUDES the EV's
        current draw, so as EV ramps the rolling rises and the headroom
        shrinks — EV settles at the equilibrium where rolling ≈ peak
        limit. That's exactly what the user wants when paying on
        15-min demand charges.

        Fallback: when the load manager hasn't accumulated samples yet
        (first ~15 minutes after a restart), uses the legacy formula
        ``peak_limit - home_consumption_power - committed_w`` so we
        never end up with no peak protection at all.

        Multi-charger (#274/H1): also subtract the draw already
        committed to higher-priority chargers this cycle
        (``_night_committed_w``), so a fleet of chargers shares one
        peak budget instead of each independently sizing to the full
        headroom and summing past the limit.

        Residual limitation: if the inverter autonomously charges the
        battery from the grid during the night window (e.g. a
        dynamic-tariff or timed grid-charge SEM does not command),
        ``grid = peak + net_batt_charge`` and the peak may still be
        exceeded by that charge. SEM cannot size around
        inverter-managed charging it doesn't control.
        """
        committed_w = getattr(self, "_night_committed_w", 0.0)
        peak_15min_w = self._get_peak_15min_w()
        if peak_15min_w is not None:
            # Production path: bill-aligned 15-min rolling. Self-balancing —
            # rolling already includes EV's current draw.
            headroom_w = self._get_peak_limit_w() - peak_15min_w - committed_w
        else:
            # Fallback: legacy home_consumption_power formula. Pre-#288 the
            # only path. Kept for the cold-start window where rolling has
            # no samples yet, so we never end up entirely without a peak
            # protection.
            headroom_w = (
                self._get_peak_limit_w() - power.home_consumption_power - committed_w
            )
        target = round(headroom_w / max(1.0, watts_per_amp))
        return min(max_amps, max(min_amps, target))

    # ``_calculate_solar_ev_budget`` removed in Phase D.2 (#282).
    # Was the legacy actuator-side budget formula that ran alongside the
    # state machine's own ``calculate_ev_budget`` — exactly the kind of
    # duplication that produced the original #282 disagreement bugs.
    # Replaced by the canonical ``EVBudgetStrategy.{SOLAR_ONLY,
    # BATTERY_ASSIST,...}`` dispatch in ``FlowCalculator.calculate_canonical_ev_budget``,
    # whose output lives at ``self._cycle_ev_budget`` and is the single
    # source of truth for every consumer (publish path, state machine,
    # actuator, multi-charger distribution). Removed Phase D.2 once
    # v1.6.0/1.6.1 confirmed the canonical path holds through both
    # daytime battery_assist and nighttime MIN_PV cycles on real
    # hardware. The corresponding ``flow_calculator.calculate_ev_budget``
    # primitive went away in the same pass.

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
        # v1.6.8: per-charger power (not fleet sum). See ``docs/MULTI_CHARGER.md``.
        this_power_w = self._this_charger_power(ev, power)
        # SEM set current >= min but charger reports no power → stalled
        if (ev._current_setpoint >= ev.min_current
                and this_power_w < 50
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
                        max_attempts, ev._current_setpoint, this_power_w,
                    )
                    return False
                _LOGGER.warning(
                    "EV charger stalled (setpoint=%.0fA, power=%.0fW) — "
                    "re-enabling (attempt %d/%d)",
                    ev._current_setpoint, this_power_w,
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

    def _this_charger_power(self, ev, power) -> float:
        """Return the per-charger power reading in watts (#315 multi-charger fix).

        ``power.ev_power`` is the global SUM across all chargers in
        multi-charger setups (see ``sensor_reader.py:426-434``). Using it
        directly would falsely trigger the off-mode stop on charger[0]
        whenever charger[1] is actively charging. Read the THIS-charger
        ``ev_charging_power_sensor`` directly from HA state instead.

        **Unit-aware**: KEBA's native ``sensor.keba_p30_charging_power``
        reports in kW. Other charger integrations may report in W. Read
        the sensor's ``unit_of_measurement`` attribute and convert to W
        when needed. The first cut of this helper compared a raw 4.14
        (kW) to a 500 W threshold and silently failed every cycle —
        confirmed on PROD 2026-05-31, KEBA self-resumed at 15:26 and
        the v1.6.5 fix did not trigger for ~2 minutes until corrected.

        Single-charger setups: ``power.ev_power`` is already the single
        sensor reading (normalized to W by ``sensor_reader``), so the
        fallback path matches what the original code path was doing.
        """
        try:
            charger_cfg = self._get_active_charger_config()
            cps = charger_cfg.get("ev_charging_power_sensor") if charger_cfg else None
            if cps and self.hass is not None:
                state = self.hass.states.get(cps)
                if state is not None and state.state not in (None, "unknown", "unavailable"):
                    value = float(state.state)
                    unit = (state.attributes or {}).get("unit_of_measurement", "W")
                    if unit == "kW":
                        value *= 1000
                    return value
        except (AttributeError, ValueError, TypeError):
            pass
        # Fallback: ``power.ev_power`` is already in watts (normalized by
        # sensor_reader). Correct for single-charger; for multi-charger
        # it's the sum (over-counts but only matters when no per-charger
        # sensor is configured — rare).
        return float(getattr(power, "ev_power", 0.0) or 0.0)

    def _this_charger_drawing_power(self, ev, power) -> bool:
        """True iff THIS charger is drawing more than the 500 W threshold.

        Threshold rationale: KEBA's handshake idle draws 100–200 W
        continuously while plugged in (control-pilot duty cycle). Real
        charging starts at ev.min_current × phases × voltage (3 phases ×
        6 A × 230 V ≈ 4140 W). 500 W safely separates "actually pulling
        current" from "plugged in, not charging".
        """
        return self._this_charger_power(ev, power) > 500

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

        # Detect session start: EV charging and no active session.
        # v1.6.8: per-charger power. ``_update_session_tracking`` is called
        # from inside the per-charger loop in ``coordinator.py:970``, after
        # ``self._session_data`` has been swapped to this charger's
        # ``SessionData`` instance — so the start-detection threshold must
        # also key off THIS charger's draw, not the fleet sum.
        this_power_w = self._this_charger_power(self._ev_device, power)
        if this_power_w > 50 and not self._session_data.active:
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
