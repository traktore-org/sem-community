"""EV control methods extracted from SEMCoordinator.

Mixin class providing all EV charging control logic:
- Night charging: dynamic peak-aware current every cycle
- Solar charging: hysteresis enable/disable delays with ramp limiting
- Min+PV mode: guaranteed minimum from grid + solar surplus
- Session cost tracking (per-session energy, cost, solar share)
- Self-healing via KEBA stall detection
- Solar EV budget calculation (grid export + forecast-aware battery redirect)
- Forecast-aware night target reduction
"""
from __future__ import annotations

import logging
import math
from typing import Any, Optional

from homeassistant.util import dt as dt_util

from ..const import (
    ChargingState,
    DEFAULT_EV_TARGET_TIME,
    DEFAULT_MAX_CHARGING_CURRENT,
    DEFAULT_PEAK_LIMIT_UNLIMITED,
    DEFAULT_PHASES,
    DEFAULT_UPDATE_INTERVAL,
    DEFAULT_VOLTAGE_PER_PHASE,
)
from .types import PowerReadings, PowerFlows, SessionData
from .ev_tariff_planner import NightChargePlan, plan_night_charge
from .units import power_state_to_watts

_LOGGER = logging.getLogger(__name__)


def amps_from_headroom(
    headroom_w: float,
    watts_per_amp: float,
    min_amps: int,
    max_amps: int,
) -> int:
    """Convert available watts to a charger current, clamped to [min, max].

    The clamp happens BEFORE the round, which is the whole point (#716).
    An install with no grid ceiling reports ``math.inf`` headroom, and
    ``round(float('inf'))`` raises ``OverflowError`` — rounding first would
    crash the EV control loop on exactly the installs the unlimited flag
    exists to serve. Saturating first also costs nothing on the finite path:
    a headroom that already exceeds ``max_amps`` was going to be clamped down
    anyway.

    ``watts_per_amp`` is floored at 1.0 to keep a zero/absent voltage config
    from dividing by zero.
    """
    amps = headroom_w / max(1.0, watts_per_amp)
    if amps >= max_amps:
        return max_amps
    if amps <= min_amps:
        return min_amps
    return min(max_amps, max(min_amps, round(amps)))


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

        # (#440 ADR 0010 #3) effective min = max(loadpoint_min, vehicle_min).
        # Fall through to the global ``ev_min_current`` when neither
        # per-charger value is set.
        from .decide import effective_min_amps
        _effective_cfg = {
            "ev_min_current": _pc("ev_min_current", 6),
            "vehicle_min_current": cfg.get("vehicle_min_current"),
        }
        min_amps = effective_min_amps(_effective_cfg, 6)
        # Hardware limits resolve per-charger-then-fleet, same as everything
        # else here (#716). Reading ``ev_max_current`` off the fleet plans a
        # 16 A box as if it were the 32 A one; the device's own rating still
        # gets the last word below, because config can out-claim the box.
        max_amps = int(_pc("ev_max_current", DEFAULT_MAX_CHARGING_CURRENT))
        ev = getattr(self, "_ev_device", None)
        if ev is not None:
            max_amps = int(getattr(ev, "max_current", max_amps))
        phases = int(_pc("ev_phases", 3))
        # ``ev_voltage`` is read by every other watts-per-amp conversion in
        # the codebase — decide.py, the energy calculator, and
        # ``_night_deliverable_kwh`` in this very file. This one alone
        # hardcoded 230, so a 240 V install was planned 4% short (#716).
        #
        # A non-positive or unparseable value falls back to the default
        # rather than through to ``amps_from_headroom``'s 1.0 W/A floor:
        # that floor would not crash, it would saturate the charger to max
        # current on a junk config value — the same fails-open shape the
        # peak limit was hardened against in this issue.
        try:
            voltage = float(_pc("ev_voltage", DEFAULT_VOLTAGE_PER_PHASE))
        except (TypeError, ValueError):
            voltage = float(DEFAULT_VOLTAGE_PER_PHASE)
        if voltage <= 0:
            voltage = float(DEFAULT_VOLTAGE_PER_PHASE)
        watts_per_amp = phases * voltage

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
        peak_limit_w = self._planning_peak_w()
        expected_home_w = self._expected_night_home_w(energy, window_h)
        # Subtract draw already committed to higher-priority chargers this cycle
        # so the fleet shares one peak budget (#274/H1).
        committed_w = getattr(self, "_night_committed_w", 0.0)
        # (#630) running cheap-hours loads keep their power — the EV's
        # headroom is what's left AFTER them (device-priority agreement:
        # a load already on is never squeezed by the EV's top-up rate).
        _sc = getattr(self, "_surplus_controller", None)
        if _sc is not None:
            try:
                committed_w += float(_sc.grid_funded_draw_w() or 0.0)
            except (TypeError, ValueError, AttributeError):
                pass  # no controller / mock host — no load draw to reserve
        peak_managed_amps = amps_from_headroom(
            peak_limit_w - expected_home_w - committed_w,
            watts_per_amp,
            min_amps,
            max_amps,
        )

        # Cheapest contiguous window covering the remaining need (block-wise) (#247).
        # (#638 one-gate C3) The private cheap-window selection is RETIRED.
        # The joint plan's blocks are the only WHEN for the night — the
        # overlay (both coordinator sites) is the sole writer of
        # ``should_wait_for_cheap``/``next_cheap_start``, so an uncovered
        # night fails open to CHARGING at the deadline/top-up floor. The
        # dwell hysteresis died with the selector: it damped the selector's
        # own price flapping, and plan blocks do not flap — the packer's
        # min_run/min_gap quantization protects the contactor instead.
        plan = plan_night_charge(
            now=dt_util.now(),
            remaining_to_min_kwh=remaining_to_min_kwh,
            min_amps=min_amps,
            max_amps=max_amps,
            watts_per_amp=watts_per_amp,
            target_time=target_time,
            night_end=night_end,
            tariff_optimized=tariff_optimized,
            peak_managed_amps=peak_managed_amps,
        )
        return plan

    def _night_deliverable_kwh(self, charger_cfg: dict) -> float:
        """Energy tonight's window can deliver to this charger (#501).

        Hours from the night-window start to the charger's ``Charge by``
        deadline (clamped to the window) × max current. Feeds the
        daytime ``min_plus_solar`` floor gate in ``decide.py`` — the
        floor only engages when the remaining Min exceeds this, i.e.
        when deferring to the night top-up would risk the guarantee.

        Uses max current (the rate a forcing deadline can ramp to),
        not the peak-managed rate: the night planner's own reachability
        check + "can't reach Min in time" notification remain the
        backstop for peak-constrained nights. Errs toward
        self-consumption (``inf`` on any parse failure = floor stays
        off), matching the mode's documented daytime behaviour.
        """
        try:
            night_start, night_end = self.time_manager.get_night_window()
            window_h = self.time_manager.get_night_window_hours()
            cfg = charger_cfg if isinstance(charger_cfg, dict) else {}
            deadline = str(cfg.get("ev_target_time") or night_end)
            sh, sm = night_start.split(":")[:2]
            dh, dm = deadline.split(":")[:2]
            start_min = int(sh) * 60 + int(sm)
            deadline_min = int(dh) * 60 + int(dm)
            hours = ((deadline_min - start_min) % (24 * 60)) / 60.0
            hours = min(hours, window_h)
            # (#789) The same three constants the ceiling above is planned
            # from. Nothing writes ``ev_max_current`` — there is no config
            # field for it (#746) — so this fallback IS the normal path, and
            # it used to read 16 while ``_compute_night_plan`` forty lines up
            # read 32. On a 32 A charger the night looked half as deliverable
            # as it is, so SEM started earlier and booked more cheap slots
            # than the night needed. Same shape as #716, which fixed the
            # hardcoded 230 in the plan and left its twin here.
            max_a = float(
                cfg.get("ev_max_current")
                or self.config.get("ev_max_current", DEFAULT_MAX_CHARGING_CURRENT)
            )
            phases = int(
                cfg.get("ev_phases") or self.config.get("ev_phases", DEFAULT_PHASES)
            )
            voltage = float(
                cfg.get("ev_voltage")
                or self.config.get("ev_voltage", DEFAULT_VOLTAGE_PER_PHASE)
            )
            return hours * max_a * phases * voltage / 1000.0
        except (ValueError, TypeError, AttributeError):
            return float("inf")

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

    def _get_peak_limit_w(self) -> float:
        """Get peak limit in watts from load manager or config.

        Returns ``math.inf`` when the install declared it has no grid ceiling
        (#716, ``peak_limit_unlimited``). Callers must size against this via
        :func:`amps_from_headroom`, which saturates before rounding —
        ``round(float('inf'))`` raises ``OverflowError``.

        Note what does NOT make this unlimited: ``load_management_enabled =
        False``. That switch governs whether SEM *sheds* to defend the ceiling;
        the ceiling itself still constrains anything SEM *sizes*. Unlimited is
        an explicit boolean and never inferred — a limit that fails open is how
        a 5 kW house got handed a 10 kW EV slot (#638 finding #5).
        """
        if self._peak_limit_unlimited():
            return math.inf
        if self._load_manager:
            try:
                lm_info = self._load_manager.get_load_management_data()
                return lm_info.get("target_peak_limit", 5.0) * 1000
            except Exception:
                pass
        return self.config.get("target_peak_limit", 5.0) * 1000

    def _planning_peak_w(self) -> float:
        """The peak level PLANNING may size against — cap minus hysteresis.

        The limit is a SHED THRESHOLD, not a target to sit on (#638 finding
        #6): LoadManager goes SHEDDING at ``peak >= target`` on the 15-minute
        rolling average, then sheds down to ``target - hysteresis``. An
        allocation booked AT the cap is exactly the one execution kills, so
        everything forward-looking — the night ledger's headroom AND the EV's
        peak-managed rate — sizes against this ONE number. Two copies of the
        subtraction is how the plan and the EV drifted a hysteresis band
        apart (one-gate build, 2026-08-11).

        Semantics carried over from the ledger's inline block:
        ``math.inf`` (unlimited) passes through; 0 stays 0 (the packer's
        "no limit configured" sentinel); a cap smaller than the hysteresis
        clamps at 1 W, never 0 — collapsing to the sentinel would flip a
        TIGHT house into an unlimited one.
        """
        from ..consts.core import DEFAULT_PEAK_HYSTERESIS
        try:
            peak_w = float(self._get_peak_limit_w())
        except Exception:  # noqa: BLE001 — no load manager yet (early startup)
            peak_w = float(
                self.config.get("target_peak_limit", 0.0) or 0.0) * 1000.0
        if peak_w > 0.0 and math.isfinite(peak_w):
            hyst_w = float(self.config.get(
                "peak_hysteresis", DEFAULT_PEAK_HYSTERESIS) or 0.0) * 1000.0
            peak_w = max(1.0, peak_w - hyst_w)
        return peak_w

    def _peak_limit_unlimited(self) -> bool:
        """True when this install declared it has no grid ceiling (#716).

        Prefers the live ``LoadManagementCoordinator`` value over
        ``self.config`` — same reason ``_get_peak_limit_w()`` prefers it for
        ``target_peak_limit`` three lines above: the Control-tab slider
        writes through ``update_target_peak_limit()`` and deliberately skips
        the config-entry reload (to avoid a full coordinator rebuild on
        every drag), so ``self.config`` can sit stale — in either direction —
        until the next restart. Reading ``self.config`` only here let the EV
        controller miss a live "Uncapped" flip, and worse, keep charging
        past a limit the user had just restored.
        """
        if self._load_manager:
            try:
                lm_info = self._load_manager.get_load_management_data()
                return bool(
                    lm_info.get("peak_limit_unlimited", DEFAULT_PEAK_LIMIT_UNLIMITED)
                )
            except Exception:
                pass
        return bool(
            self.config.get("peak_limit_unlimited", DEFAULT_PEAK_LIMIT_UNLIMITED)
        )

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

    # Dead in the cycle: superseded by the planner's top_up_amps path (#630).
    # Kept for reference until the #629 arc's final sweep; do not wire it back
    # without removing the grid_funded double-count noted in the #630 review.
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
        # (#630) running cheap-hours loads keep their power — the EV's
        # headroom is what's left AFTER them (device-priority agreement:
        # a load already on is never squeezed by the EV's top-up rate).
        _sc = getattr(self, "_surplus_controller", None)
        if _sc is not None:
            try:
                committed_w += float(_sc.grid_funded_draw_w() or 0.0)
            except (TypeError, ValueError, AttributeError):
                pass  # no controller / mock host — no load draw to reserve
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
        return amps_from_headroom(headroom_w, watts_per_amp, min_amps, max_amps)

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
        """Night-charge target = the user's Min slider minus what's already
        been delivered today. No EV-intelligence override, no solar-forecast
        reduction (#440).

        Per the v1.7.1-beta.4 truth model, only the user's sliders (Min/Max),
        the charge mode, and — for ``%`` target type — the real vehicle SOC
        determine charging. Estimated SOC, predicted daily consumption,
        consecutive-skip counters and tomorrow's forecast are diagnostic
        signals only; they do not override the user's stated mode.

        The function is kept as a thin method for call-site stability — the
        previous body shipped two override paths (SOC-based skip at lines
        847-885 of the pre-#440 file, solar-forecast-based reduction at
        lines 887-929) that violated the principle. Both are gone.

        Args:
            remaining_kwh: User's Min target minus today's delivered kWh.
            energy: unused — kept for call-site signature stability.
            charger_cfg: unused — kept for call-site signature stability.

        Returns:
            ``max(0, remaining_kwh)``.
        """
        return max(0.0, float(remaining_kwh))

    async def _police_opted_out_charger(
        self, cid: str, ev_dev, charger_cfg: dict, power,
    ) -> None:
        """Police a charger the #193 night gate is about to skip (#740).

        In NIGHT_CHARGING_ACTIVE / TARIFF_WAITING_FOR_CHEAP an ``off`` /
        ``solar_only`` charger is ``continue``d out of the per-charger
        loop — before its adapter, reconciler, decide() or actuate()
        run. "Skip" must mean "no night budget", NOT "no supervision":
        a box that auto-starts masterless at night (the #740 war) would
        otherwise draw unpoliced until a day state returns — the
        gate-blocks-activation-but-doesn't-stop-the-running-device
        class again.

        This is the minimal reconcile pass: OFF for ``off`` (immediate
        DISABLE while drawing), IDLE for ``solar_only`` (the #552
        idle-settled row gives a rogue self-start the same immediate
        DISABLE). Converged emits nothing — no churn against the
        quota-hold, which deliberately leaves the box enabled but
        suspended.
        """
        from .actuate import actuate
        from .charger_reconciler import (
            DEFAULT_IDLE_DISABLE_THRESHOLD,
            ChargerReconciler,
        )
        from .charger_types import ChargerDecision, ChargerIntent, ChargerPower

        # This charger's draw — build_view's own resolution: the
        # per-charger reading when sensor_reader has one, else the
        # fleet sum (single-charger setups: the sum IS this charger).
        per = getattr(power, "ev_power_per_charger", None) or {}
        if cid in per:
            this_w = float(per[cid] or 0.0)
        else:
            # FLEET-READ: single-charger fallback, same contract as
            # build_view.py:95-100 — multi-charger always has a
            # per-charger entry above.
            this_w = float(getattr(power, "ev_power", 0.0) or 0.0)

        adapter_cache = getattr(self, "_charger_adapters", None)
        if adapter_cache is None:
            adapter_cache = {}
            self._charger_adapters = adapter_cache
        adapter = adapter_cache.get(cid)
        if adapter is None or adapter._device is not ev_dev:
            from .charger_adapters import adapter_for
            adapter = adapter_for(ev_dev)
            adapter_cache[cid] = adapter

        rec_cache = getattr(self, "_charger_reconcilers", None)
        if rec_cache is None:
            rec_cache = {}
            self._charger_reconcilers = rec_cache
        reconciler = rec_cache.get(cid)
        if reconciler is None:
            reconciler = ChargerReconciler(
                charger_id=cid,
                heartbeat_s=float(
                    getattr(ev_dev, "watchdog_refresh_interval_s", 5.0),
                ),
                idle_disable_threshold=DEFAULT_IDLE_DISABLE_THRESHOLD,
            )
            rec_cache[cid] = reconciler

        mode = str(charger_cfg.get("charge_mode", "off"))
        intent = (
            ChargerIntent.DISABLE if mode == "off" else ChargerIntent.IDLE
        )
        decision = ChargerDecision(
            charger_id=cid,
            mode=mode,
            intent=intent,
            reason=f"night gate — {mode} opts out of night charging; "
                   "policing only (#740)",
            bridgeable=False,
        )
        cp = ChargerPower(
            charger_id=cid,
            power_w=this_w,
            connected=bool(
                (getattr(power, "ev_connected_per_charger", None) or {})
                .get(cid, getattr(power, "ev_connected", False)),
            ),
            charging=bool(
                (getattr(power, "ev_charging_per_charger", None) or {})
                .get(cid, getattr(power, "ev_charging", False)),
            ),
        )
        await actuate(
            decision, adapter, cp, reconciler,
            observer=self._observer_mode,
            controller=self._surplus_controller,
        )

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

        v1.6.14: when called from inside a ``PerChargerContext`` for
        the same ``ev``, returns the cached value
        ``self._current_pcc.this_power_w`` computed once at
        ``__enter__``. Outside the loop (single-charger path, post-loop
        helpers) the direct-compute branch below runs. The lint enforces
        that no callsite reads ``power.ev_power`` directly — they all
        funnel through here.
        """
        pcc = getattr(self, "_current_pcc", None)
        if (pcc is not None and pcc.ev_dev is ev
                and pcc.this_power_w is not None):
            return pcc.this_power_w
        try:
            charger_cfg = self._get_active_charger_config()
            cps = charger_cfg.get("ev_charging_power_sensor") if charger_cfg else None
            if cps and self.hass is not None:
                # #641 — was an exact-case ``== "kW"``, so a template/MQTT
                # charger sensor emitting ``"kw"`` read 11 W here while
                # ``sensor_reader`` (lowercase rule) read the same sensor as
                # 11000 W. One shared rule now.
                value = power_state_to_watts(self.hass.states.get(cps))
                if value is not None:
                    return value
        except (AttributeError, ValueError, TypeError):
            pass
        # Fallback: ``power.ev_power`` is already in watts (normalized by
        # sensor_reader). Correct for single-charger; for multi-charger
        # it's the sum (over-counts but only matters when no per-charger
        # sensor is configured — rare).
        # FLEET-READ: documented fallback when no per-charger sensor is
        # configured; in multi-charger setups this code path is only
        # reached when ``_get_active_charger_config`` lacks a
        # ``ev_charging_power_sensor`` entry (rare).
        return float(getattr(power, "ev_power", 0.0) or 0.0)

    def _confirm_ev_connection(self, power: PowerReadings) -> None:
        """(#638) Answer the plug question ONCE, for the whole cycle.

        Filters ``power`` in place the cycle it is read: every consumer
        downstream — the state machine, ``build_charger_view`` → ``decide``,
        the plan layer, the notification gate, the entities — then reads one
        answer. Before this, the debounce lived in
        ``_update_session_tracking`` and its result on
        ``_last_ev_connected_per_charger``, so only the consumers that read
        THAT map were protected; everything reading ``power.ev_connected``
        got the raw sensor. On .175 (15.08) that split showed as
        ``sensor.sem_charging_state`` flapping to "System ready" — the
        car-away face, and on real hardware a ``stop_session()`` — while
        the per-charger connected entity stayed on.

        Per charger, plus the flat fleet flag for installs without a
        per-charger sensor. The fleet answer is the OR of both: a fleet
        whose chargers blip in turn never reads "no car".
        """
        from .ev_availability import confirm_connection

        if not hasattr(self, "_ev_conn_confirmed"):
            self._ev_conn_confirmed = {}
            self._ev_conn_streak = {}
        import time as _time
        _boot = getattr(self, "_boot_monotonic", None)
        in_warmup = (_boot is not None and _time.monotonic() - _boot < 120.0)

        def _one(key: str, raw: bool) -> bool:
            confirmed, streak = confirm_connection(
                bool(self._ev_conn_confirmed.get(key, False)), bool(raw),
                int(self._ev_conn_streak.get(key, 0)), in_warmup,
            )
            self._ev_conn_confirmed[key] = confirmed
            self._ev_conn_streak[key] = streak
            if confirmed and not raw:
                _LOGGER.debug(
                    "Plug %s: missed poll %d/3 — holding connected (#638)",
                    key or "fleet", streak,
                )
            return confirmed

        raw_map = getattr(power, "ev_connected_per_charger", None) or {}
        confirmed_map = {cid: _one(str(cid), raw) for cid, raw in raw_map.items()}
        fleet = _one("", bool(getattr(power, "ev_connected", False)))
        if raw_map:
            power.ev_connected_per_charger = confirmed_map
        power.ev_connected = fleet or any(confirmed_map.values())

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

        # Detect session end: EV was connected, now disconnected.
        # (#753 / #638) ``power.ev_connected`` is already the CONFIRMED
        # answer — ``_confirm_ev_connection`` debounced it at the top of the
        # cycle (never inside the boot warm-up: PROD 2026-08-11, a restart's
        # warm-up 'unplug' finalized a 6 kWh session and restarted it at
        # 1.6 kWh; and only after three consecutive disconnected cycles,
        # absorbing the KEBA UDP blip family #35/#595). Debouncing again
        # here would cost a real unplug six cycles and split the cycle's one
        # answer back in two, which is the bug that moved it to the source.
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

        # Cost: direct grid at the current import rate, battery-sourced at
        # what its stored energy cost to put in — the provenance pool's rate,
        # the same one the battery savings price from. (#793: this increment
        # was priced at ZERO, so a car charged off a grid-filled battery
        # looked free while the grid purchase sat in the import cost.)
        import_rate = self._energy_calculator._import_rate
        self._session_data.cost_chf += (
            grid_increment * import_rate
            + battery_increment * self._energy_calculator.ev_battery_cost_rate()
        )

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
