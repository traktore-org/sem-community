"""EV taper detection, virtual SOC estimation, and battery health tracking.

Detects the characteristic power staircase when an EV's BMS reduces
charging current as the battery approaches full (CC-CV transition).
Discriminates BMS-initiated power reductions from SEM setpoint changes
by tracking the charger's commanded current separately.

Real-world example (KEBA P30 + VW):
    13:46  6290W → 5580W → 4970W → 4340W → 3740W → 3120W → 2550W → 1960W → 0W
    Each step ~600W, 1-3 min hold, total taper ~17 min.

Virtual SOC estimation:
    Tracks cumulative energy between full-charge detections to estimate
    the car's state of charge without needing a vehicle API.

Battery health:
    Compares energy accepted during full-cycle charges against the
    configured capacity over months.
"""
from __future__ import annotations

import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .types import EVTaperData
from .units import power_unit_scale

_LOGGER = logging.getLogger(__name__)

# Buffer and detection constants
BUFFER_SIZE = 120          # 120 samples × 10s = 20 minutes
MIN_SAMPLES = 12           # At least 2 min of BMS-only data for regression
SETTLING_CYCLES = 3        # Ignore 3 cycles (30s) after SEM setpoint change
TAPER_SLOPE_THRESHOLD = -5.0   # W/min — steeper than this = declining
FULL_POWER_THRESHOLD = 50      # W — below this after declining = car full
SESSION_PEAK_MIN = 500         # W — minimum peak to consider a real session
FULL_SESSION_ENERGY_MIN_KWH = 1.0  # #438 — upper bound of the session-energy
                                    # floor below which taper-to-full cannot
                                    # fire. We chose 1.0 over the 2.0 suggested
                                    # in the original test prose: 2.0 blocks
                                    # legitimate full-anchors on small-battery
                                    # cars (24 kWh LEAF arriving at 95 % only
                                    # needs ~1.2 kWh to top up). The PROD bug
                                    # was 0.19 kWh — well under 1.0 — so the
                                    # safety margin is comfortable. Used as a
                                    # CAP; the per-vehicle effective floor is
                                    # ``min(constant, capacity_kwh * 0.025)``
                                    # — see ``_session_energy_floor_kwh``.
FULL_SESSION_ENERGY_FRAC_OF_CAPACITY = 0.025  # 2.5 % of pack capacity. Below
                                              # this any "taper to zero" is
                                              # noise, not a completed charge.
TAPER_RATIO_NEARLY_FULL = 50   # % — below this = nearly full
TAPER_RATIO_DETECTED = 70     # % — below this + declining = taper confirmed
CHARGE_EFFICIENCY = 0.92       # #708 — AC-side delivered → DC-pack fraction.
                               # Default for the booked deficit (overridable via
                               # ``ev_charger_efficiency``) AND the fixed value
                               # for the stop ceiling (not overridable).
                               #
                               # #735 — why the ceiling refuses the override.
                               # It feeds ``max(sensor, ceiling)``, so a LOWER
                               # efficiency means a lower ceiling, more remaining
                               # need, and a LONGER charge. The two errors are not
                               # the same size: stopping early is recovered by the
                               # next sensor reading (need goes positive, charging
                               # resumes), while stopping late has already put the
                               # energy in the pack — that is the #708 report, a
                               # 30-min-stale reading at 11.5 kW running a 60 %
                               # target to 67 %. So the ceiling sits at the
                               # optimistic end of the realistic 0.85–0.95 band
                               # and stays there: dialling it down would ship the
                               # unrecoverable direction as a setting.
                               # Hard-coded by decision — no config knob.
MAX_ETA_MINUTES = 60           # Cap completion estimate
MAX_HEALTH_SAMPLES = 20        # Bounded battery health sample buffer

CHARGE_EFFICIENCY_MIN = 0.5    # #735 — the accepted band for the override.
CHARGE_EFFICIENCY_MAX = 1.0    # The options dialog offers 50–100 %; anything
                               # outside is a typo, not a rough install.


def resolve_charge_efficiency(raw: Any) -> float:
    """Validate an ``ev_charger_efficiency`` value, or fall back to the default.

    Module-level on purpose: the config flow needs the same answer the
    detector will act on (#735). It converts the dialog's whole-percent
    figure into this fraction and renders the stored value back, so if it
    validated separately the two could disagree about which settings are
    real — a user's 45 % accepted by the form and silently ignored by the
    booking. One band, one bool rule, one caller-visible default.

    Anything outside the band means somebody typed a percentage, a sign, or
    a word: 3.0 would claim the pack absorbed three times what the meter
    measured, and 0.001 would stall the estimate near its starting value for
    a whole session while looking like it worked. The floor is 0.5 rather
    than a bare ``> 0`` because no EV onboard charger throws away half its
    input.

    ``bool`` is rejected before the float conversion — the values can arrive
    from ``.storage/core.config_entries``, which is JSON, so a hand-edited
    ``true`` becomes Python ``True`` and ``float(True)`` is a perfectly
    valid-looking 1.0.
    """
    if raw is None or isinstance(raw, bool):
        return CHARGE_EFFICIENCY
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return CHARGE_EFFICIENCY
    # NaN fails both comparisons, so this also screens it out.
    if not CHARGE_EFFICIENCY_MIN <= value <= CHARGE_EFFICIENCY_MAX:
        return CHARGE_EFFICIENCY
    return value


@dataclass
class PowerSample:
    """Single power reading with context for BMS/SEM discrimination."""
    timestamp: float         # monotonic seconds
    ev_power: float          # Measured EV power (W)
    current_setpoint: float  # SEM's commanded current (A)
    sem_changed: bool        # True if SEM changed setpoint recently


class EVTaperDetector:
    """Detects EV BMS taper and tracks virtual SOC.

    Called every coordinator cycle (~10s). Maintains a 20-minute power
    history buffer and detects when the car's BMS reduces charging power
    independently of SEM's setpoint changes.

    Attributes:
        estimated_soc: Current virtual SOC estimate (0-100%).
        last_full_timestamp: ISO timestamp of last detected full charge.
        energy_since_full: kWh consumed since last detected full charge.
        full_detected: True when a full charge was detected this session.
    """

    def __init__(self, config: Dict[str, Any]):
        self._config = config
        self._buffer: deque = deque(maxlen=BUFFER_SIZE)

        # Session state
        self._session_peak_w: float = 0.0
        self._declining_phase: bool = False
        self._full_detected: bool = False
        self._last_setpoint: float = 0.0
        self._settling_counter: int = 0
        # #708 — has SEM offered current at any point this session? Gates
        # the taper-to-full anchor: see the withdrawal note in ``update``.
        self._sem_has_offered: bool = False
        # #438 — current-session energy accumulator, integrated from
        # the per-call (power, timestamp) tuples. The taper-to-full
        # gate requires this to exceed FULL_SESSION_ENERGY_MIN_KWH
        # before anchoring full — a tiny oscillation session can
        # satisfy the power-pattern check but cannot physically have
        # filled the battery. Reset by ``reset_session()`` on disconnect.
        self._current_session_energy_kwh: float = 0.0
        self._last_energy_timestamp: Optional[datetime] = None
        self._last_energy_power_w: float = 0.0

        # Persistent state (restored from storage)
        self._last_full_timestamp: Optional[str] = None
        self._energy_since_full: float = 0.0
        self._estimated_soc: float = 0.0
        self._battery_health_samples: List[Dict] = []
        self._battery_health_pct: float = 0.0
        # SOC anchor: set True after first reliable SOC reference point
        # (taper detection, car API calibration, or first session bootstrap)
        self._soc_anchored: bool = False

        # SOC calibration: track real SOC for syncing virtual SOC
        self._last_real_soc: Optional[float] = None
        # Session SOC tracking for partial-charge health estimates
        self._session_start_soc: Optional[float] = None
        # #708 — energy-accounted SOC anchor: the last sensor VALUE and the
        # session-energy reading at the moment that value arrived. Between
        # sensor updates the pack can only be FULLER than the anchor by what
        # we measurably delivered — that bound is the overshoot guard for
        # slow/polled SOC sensors (OnStar: 30-min poll ⇒ 7 % overshoot at
        # 11.5 kW). Session-scoped: cleared on disconnect, never persisted —
        # after a restart the ceiling stays inactive until the next anchor,
        # which is the pre-#708 behaviour (fail-open to the known state).
        self._soc_anchor_value: Optional[float] = None
        self._soc_anchor_session_kwh: Optional[float] = None
        # #708 — session latch: the estimate (not the sensor) ended a charge.
        # Read by the notification layer; cleared on resume or disconnect.
        self._estimate_stop_active: bool = False
        # Hardware counter tracking for drift-free energy accounting
        self._hw_total_at_full: Optional[float] = None  # Charger total kWh when SOC was 100%
        self._hw_total_last: Optional[float] = None  # Last known charger total kWh

    def _session_energy_floor_kwh(self) -> float:
        """Per-vehicle effective floor for the taper-to-full gate (#438).

        Returns ``min(FULL_SESSION_ENERGY_MIN_KWH, capacity * 0.025)``.
        The 1.0 kWh cap protects against handshake-floor oscillations
        (the PROD bug was 0.19 kWh). The 2.5 %-of-capacity scaling
        prevents false-negatives on small-battery cars: a 24 kWh LEAF
        arriving at 99 % only needs ~0.24 kWh to complete and would
        otherwise be locked out of the full-anchor by a fixed 1.0 kWh
        floor. For 40 kWh+ packs the cap binds; for smaller packs
        the proportional term binds.

        Returns:
            Minimum session-delivered energy (kWh) required before
            ``_full_detected`` can be anchored from a taper pattern.
        """
        capacity = float(self._config.get("ev_battery_capacity_kwh", 40))
        proportional = capacity * FULL_SESSION_ENERGY_FRAC_OF_CAPACITY
        return min(FULL_SESSION_ENERGY_MIN_KWH, proportional)

    # ------------------------------------------------------------------
    # Public API — called each coordinator cycle
    # ------------------------------------------------------------------

    def diagnostics_view(self) -> dict:
        """(#708) The stop-decision internals for the diagnostics download.

        Every report of the taper family needed someone reading the source
        to guess what should have happened — the give-up machinery lives in
        charge_stability, but the latch, the peak and the anchor live here.
        """
        return {
            "declining_phase": bool(self._declining_phase),
            "session_peak_w": float(self._session_peak_w),
            "soc_anchored": bool(self._soc_anchored),
            "soc_anchor_value": self._soc_anchor_value,
            "soc_anchor_session_kwh": self._soc_anchor_session_kwh,
            "last_full_at": self._last_full_timestamp,
            "estimated_soc": self._estimated_soc,
            "energy_since_full_kwh": round(
                float(self._energy_since_full or 0.0), 3),
        }

    def update(
        self,
        ev_power: float,
        current_setpoint: float,
        ev_connected: bool,
        timestamp: datetime,
    ) -> EVTaperData:
        """Record a power sample and analyze for taper.

        Args:
            ev_power: Current measured EV charging power (W).
            current_setpoint: SEM's commanded charging current (A).
            ev_connected: Whether the EV is plugged in.
            timestamp: Current datetime.

        Returns:
            EVTaperData with current taper analysis.
        """
        if not ev_connected:
            return EVTaperData()

        # #438 — integrate current-session energy from per-call dt
        # using the wall-clock timestamp the caller provides.
        # Trapezoidal: (prev_power + curr_power) / 2 × dt_hours.
        if self._last_energy_timestamp is not None:
            dt_s = (timestamp - self._last_energy_timestamp).total_seconds()
            if 0 < dt_s < 600:  # ignore stale gaps / restart jumps > 10 min
                avg_w = (self._last_energy_power_w + ev_power) / 2.0
                self._current_session_energy_kwh += avg_w * dt_s / 3_600_000.0
        self._last_energy_timestamp = timestamp
        self._last_energy_power_w = ev_power

        mono = time.monotonic()

        # Detect SEM setpoint changes
        sem_changed = False
        if abs(current_setpoint - self._last_setpoint) > 0.5:
            sem_changed = True
            self._settling_counter = SETTLING_CYCLES
        elif self._settling_counter > 0:
            sem_changed = True
            self._settling_counter -= 1
        self._last_setpoint = current_setpoint

        # #708 — SEM's own hand on the charge. Every stop path in
        # devices/base.py (deactivate, the session stop, the quota-hold
        # branch) zeroes ``_current_setpoint``, so a withdrawal is visible
        # right here. Once SEM has taken back an offer it made, the 0 W
        # that follows is SEM's doing and carries no information about the
        # pack — a car finishing and a charger SEM switched off read
        # identically at the meter.
        #
        # ABSENCE of an offer is not WITHDRAWAL of one. Observer mode
        # zeroes every setpoint (_zero_charger_setpoints) and an
        # uncontrolled box never had one; there SEM withdrew nothing, the
        # taper is the only evidence available, and it must still count.
        # That is why the term is a transition, not ``setpoint > 0``.
        if current_setpoint > 0:
            self._sem_has_offered = True
        sem_withdrew_offer = self._sem_has_offered and current_setpoint <= 0

        # Track session peak (only from sustained readings > threshold)
        if ev_power > self._session_peak_w and ev_power > SESSION_PEAK_MIN:
            self._session_peak_w = ev_power

        # #708 — the decline belongs to the charge that produced it.
        # ``_analyze`` latches ``_declining_phase`` on the first declining
        # five-minute window and nothing short of ``reset_session`` clears
        # it, so a car that dips and then comes back to full tilt is still
        # remembered as tapering — and the next pause it takes reads as
        # the end of the charge.
        #
        # The threshold is TAPER_RATIO_DETECTED read backwards: below 70 %
        # of session peak *plus* a declining trend is what confirms a
        # taper, so at or above 70 % the charge is by definition not in
        # one. A genuine taper passing back down through that band clears
        # the latch here and is re-latched by ``_analyze`` at the end of
        # this same cycle, while the trend is still declining.
        if (self._declining_phase
                and self._session_peak_w > 0
                and ev_power >= self._session_peak_w
                * TAPER_RATIO_DETECTED / 100.0):
            self._declining_phase = False

        # Append sample
        self._buffer.append(PowerSample(
            timestamp=mono,
            ev_power=ev_power,
            current_setpoint=current_setpoint,
            sem_changed=sem_changed,
        ))

        # Check for full charge (0W after declining from a real charging session)
        # Require peak > 3000W and 3 consecutive low-power samples (~30s)
        # to avoid false triggers from brief BMS power dips — and (#708)
        # that SEM has not just withdrawn the offer that was feeding it.
        if (self._declining_phase
                and ev_power < FULL_POWER_THRESHOLD
                and self._session_peak_w > 3000
                and not sem_withdrew_offer):
            self._full_confirm_count = getattr(self, '_full_confirm_count', 0) + 1
        else:
            self._full_confirm_count = 0

        # #438 / ADR 0010 — session-energy floor. A tiny session
        # (e.g. ~0.2 kWh of oscillation at a sub-handshake offer)
        # satisfies the "peak > 3 kW + 3 low samples" pattern but
        # cannot physically have filled the battery. Gate the full
        # anchor on a sane minimum session energy delivered — scaled
        # per-vehicle so small-battery cars at very high SOC don't
        # get false-negatives.
        if self._full_confirm_count >= 3 and not self._full_detected:
            floor_kwh = self._session_energy_floor_kwh()
            if self._current_session_energy_kwh >= floor_kwh:
                self._full_detected = True
                self._last_full_timestamp = timestamp.isoformat()
                self._energy_since_full = 0.0
                self._estimated_soc = 100.0
                self._soc_anchored = True
                # Snapshot hardware counter at full for drift-free tracking
                if self._hw_total_last is not None:
                    self._hw_total_at_full = self._hw_total_last
                _LOGGER.info(
                    # (#708) report the OBSERVATION — "anchored at 100%"
                    # asserted something SEM cannot know.
                    "EV charge complete at %s (peak=%.0fW, session=%.2fkWh ≥ floor=%.2fkWh, hw_total=%.1f)",
                    self._last_full_timestamp, self._session_peak_w,
                    self._current_session_energy_kwh, floor_kwh,
                    self._hw_total_at_full if self._hw_total_at_full is not None else 0,
                )
            else:
                _LOGGER.debug(
                    "EV taper-to-full pattern met but session=%.2fkWh < %.2fkWh floor "
                    "(capacity=%.0fkWh) — not anchoring full (likely a "
                    "handshake-floor oscillation, not a real end-of-charge)",
                    self._current_session_energy_kwh, floor_kwh,
                    self._config.get("ev_battery_capacity_kwh", 40),
                )

        return self._analyze(ev_power)

    def apply_daily_decay(
        self,
        predicted_daily_kwh: float,
        fallback_kwh: float,
        temp_correction: float = 1.0,
    ) -> None:
        """Decay virtual SOC by predicted daily consumption.

        Called once per day at rollover when the car is NOT connected.
        Simulates driving consumption during the blind period when SEM
        can't see actual energy use. Temperature-corrected for seasonal
        variation (winter heating, summer AC).

        Args:
            predicted_daily_kwh: EWMA-predicted consumption for today's weekday.
            fallback_kwh: Config daily_ev_target, used if predictor has no data.
            temp_correction: Temperature factor (1.0=baseline, 1.5=cold winter).
        """
        decay = predicted_daily_kwh if predicted_daily_kwh > 0 else fallback_kwh
        decay *= temp_correction
        self._energy_since_full += decay

        capacity = self._config.get("ev_battery_capacity_kwh", 40)
        # Cap at capacity
        self._energy_since_full = min(self._energy_since_full, capacity)
        if capacity > 0:
            self._estimated_soc = max(
                0.0, 100.0 - (self._energy_since_full / capacity * 100.0)
            )

        _LOGGER.info(
            "Virtual SOC decay: -%.1f kWh (predicted=%.1f, fallback=%.1f, "
            "temp_factor=%.2f) → SOC %.1f%%",
            decay, predicted_daily_kwh, fallback_kwh,
            temp_correction, self._estimated_soc,
        )

    @staticmethod
    def temperature_correction_factor(outdoor_temp_c: float) -> float:
        """Calculate temperature correction factor for EV consumption.

        Based on peer-reviewed fleet data (Recurrent Auto, 30k+ vehicles):
        - Optimal range 10-28°C: factor 1.0
        - Below 10°C: +0.048 per °C (≈+2.4 kWh/100km per 5°C drop)
        - Above 28°C: +0.046 per °C (≈+2.3 kWh/100km per 5°C rise)

        Examples: -5°C → 1.72, 0°C → 1.48, 20°C → 1.0, 35°C → 1.32
        """
        if outdoor_temp_c < 10:
            return 1.0 + (10 - outdoor_temp_c) * 0.048
        if outdoor_temp_c > 28:
            return 1.0 + (outdoor_temp_c - 28) * 0.046
        return 1.0

    def _charge_efficiency(self) -> float:
        """AC→DC fraction used when BOOKING delivered energy (#735).

        The single resolver for ``ev_charger_efficiency``. Two sites answer
        the same question about the same session — ``update_energy`` every
        cycle and ``on_session_end``'s bootstrap — and #708 is the standing
        reminder of what happens when two halves of one calculation drift.

        NOT used by ``energy_accounted_soc``: the stop ceiling deliberately
        stays on the constant. See the CHARGE_EFFICIENCY comment for why the
        override is refused there specifically.
        """
        return resolve_charge_efficiency(self._config.get("ev_charger_efficiency"))

    def update_energy(
        self,
        ev_energy_increment_kwh: float,
        hw_total_energy_kwh: Optional[float] = None,
    ) -> None:
        """Book delivered energy against the deficit below full.

        ``_energy_since_full`` is how many kWh the pack sits BELOW full:
        ``apply_daily_decay`` adds driving consumption to it, the sensor
        calibration sets it to ``(100 − soc)/100 × capacity``, the taper/stall
        anchor zeroes it at 100 %, and every display divides it out of 100.
        Charging therefore SUBTRACTS, and this is the ONLY path that books it:
        ``on_session_end`` used to subtract the session total again at
        disconnect, which was the other half of a cancelling pair (see there).

        This path used to add the delivered kWh instead, so a live charge
        walked the estimate down by exactly what went into the pack (#708).
        It stayed hidden because a session that reaches full resets the
        deficit to zero anyway; it takes a charge that stops short AND a
        vehicle-SOC sensor that goes quiet to leave the inverted value on
        screen. 11.5 kWh into a blinded 85 kWh pack read 24 % instead of 50 %.

        The hardware total-energy counter is still tracked (the taper anchor
        ``_hw_total_at_full`` needs it) but no longer books the deficit. It
        measures energy put back IN, never how far the car was driven — that
        mismatch IS the sign error. Its per-cycle delta is not a safe
        substitute either: a counter that goes unavailable for a stretch and
        then returns re-books the whole gap the integral already covered, and
        nothing normalizes its unit, so a charger publishing Wh delivers
        ~4 Wh cycles as the bare number 4.0 — under any plausible sanity
        bound, and enough to fill the pack in a handful of cycles.

        Args:
            ev_energy_increment_kwh: Power-integrated increment — the source.
            hw_total_energy_kwh: Current charger lifetime total, tracked only.
        """
        capacity = self._config.get("ev_battery_capacity_kwh", 40)

        # Always track hardware counter (even after full detection)
        if hw_total_energy_kwh is not None and hw_total_energy_kwh > 0:
            self._hw_total_last = hw_total_energy_kwh

        if self._full_detected:
            # Still update hw_total_at_full if car keeps charging after taper
            # (false taper: BMS briefly reduced then resumed)
            if self._hw_total_at_full is not None and hw_total_energy_kwh is not None:
                extra = hw_total_energy_kwh - self._hw_total_at_full
                if extra > 0.5:
                    # Car charged more after taper — update the anchor
                    self._hw_total_at_full = hw_total_energy_kwh
                    _LOGGER.info(
                        "Post-taper charging detected: +%.1f kWh — updating hw anchor to %.1f",
                        extra, hw_total_energy_kwh,
                    )
            return

        if capacity <= 0:
            return

        # #245: an unanchored detector has no reference to move. Booking into
        # it would write ``_estimated_soc = 100`` — and that field is
        # PERSISTED, so it would outlive the ``_soc_anchored`` display gate
        # that is currently the only thing hiding it. An install with no
        # vehicle-SOC sensor gets anchored by its first COMPLETED session
        # (``on_session_end``'s bootstrap), not mid-charge.
        if not self._soc_anchored:
            return

        if ev_energy_increment_kwh <= 0:
            return

        efficiency = self._charge_efficiency()
        self._energy_since_full = max(
            0.0, self._energy_since_full - ev_energy_increment_kwh * efficiency
        )
        self._estimated_soc = min(
            100.0, 100.0 - (self._energy_since_full / capacity * 100.0)
        )

    def get_virtual_soc(self, vehicle_soc: Optional[float] = None) -> float:
        """Get estimated SOC, preferring real vehicle SOC if available.

        When real SOC is available, calibrates internal state so the
        virtual SOC stays accurate when the car API goes offline.
        """
        capacity = self._config.get("ev_battery_capacity_kwh", 40)

        if vehicle_soc is not None:
            # Calibrate: sync internal state to real SOC so virtual
            # continues accurately when car API goes offline
            if self._last_real_soc is None or abs(vehicle_soc - self._last_real_soc) > 0.5:
                self._estimated_soc = vehicle_soc
                if capacity > 0:
                    self._energy_since_full = (100.0 - vehicle_soc) / 100.0 * capacity
                _LOGGER.debug(
                    "SOC calibrated from vehicle: %.1f%% (energy_since_full=%.1f kWh)",
                    vehicle_soc, self._energy_since_full,
                )
                # #708 — every fresh sensor value re-anchors the
                # energy-accounted SOC; the sensor always wins.
                self._soc_anchor_value = vehicle_soc
                self._soc_anchor_session_kwh = self._current_session_energy_kwh
            elif self._soc_anchor_value is None:
                # #708 — session-start bootstrap: after a disconnect cleared
                # the anchor, the first present reading anchors even without
                # a value change. While the car is not charging its SOC does
                # not move, so a reading that is minutes old is still the
                # truth at plug-in — without this, a session whose target
                # lies inside the sensor's first polling window would run
                # entirely unguarded.
                self._soc_anchor_value = vehicle_soc
                self._soc_anchor_session_kwh = self._current_session_energy_kwh
            self._last_real_soc = vehicle_soc
            self._soc_anchored = True
            # Track session start SOC for health calculation
            if self._session_start_soc is None:
                self._session_start_soc = vehicle_soc
            return vehicle_soc

        if capacity <= 0:
            return 0.0

        # After a full charge anchor, treat < 0.1 kWh as still at 100%
        # (prevents noise/rounding from drifting SOC on restarts)
        if self._soc_anchored and self._energy_since_full < 0.1:
            self._estimated_soc = 100.0
            return 100.0

        self._estimated_soc = max(
            0.0,
            min(100.0, 100.0 - (self._energy_since_full / capacity * 100.0)),
        )
        return self._estimated_soc

    def energy_accounted_soc(self) -> Optional[float]:
        """The pack cannot be emptier than the last reading plus what we
        measurably delivered since — the #708 overshoot guard.

        ``anchor + delivered_since_anchor × CHARGE_EFFICIENCY / capacity``,
        capped at 100. Returns ``None`` when no anchor exists (no sensor
        reading this session, capacity unconfigured, or just after a
        restart) — callers fall back to pre-#708 behaviour.

        This is deliberately NOT the virtual SOC: ``get_virtual_soc``
        carries speculative terms (daily driving decay, temperature,
        self-heal) and is walled off from steering (#440/#446). This
        estimate contains only measured quantities from the current
        plugged session, which is what makes it safe to let it CAP —
        never replace — the sensor in the stop decision.
        """
        if self._soc_anchor_value is None or self._soc_anchor_session_kwh is None:
            return None
        capacity = float(self._config.get("ev_battery_capacity_kwh", 40) or 0)
        if capacity <= 0:
            return None
        delivered = max(
            0.0, self._current_session_energy_kwh - self._soc_anchor_session_kwh
        )
        return min(
            100.0,
            self._soc_anchor_value + delivered * CHARGE_EFFICIENCY / capacity * 100.0,
        )

    def on_session_end(self, session_energy_kwh: float, end_soc: Optional[float] = None) -> None:
        """Record completed session for battery health tracking.

        Supports two health estimation methods:
        1. Full-cycle: taper detected (end ≈ 100%), uses full session energy
        2. Partial-cycle: real SOC at start and end known, uses SOC delta

        Method 2 works for any charge (40%→80%), so nobody needs to
        drive to empty for health tracking.
        """
        if session_energy_kwh < 1.0 or self._session_peak_w < SESSION_PEAK_MIN:
            self._session_start_soc = None
            return

        capacity = self._config.get("ev_battery_capacity_kwh", 40)
        if capacity <= 0:
            self._session_start_soc = None
            return

        sample = None

        # Method 1: Full-cycle (taper detected → end SOC ≈ 100%)
        if self._full_detected:
            sample = {
                "method": "full_cycle",
                "energy_kwh": round(session_energy_kwh, 2),
                "capacity_estimate_kwh": round(session_energy_kwh, 2),
                "peak_w": round(self._session_peak_w, 0),
            }

        # Method 2: Partial-cycle (real SOC at start + end known)
        if (
            sample is None
            and self._session_start_soc is not None
            and end_soc is not None
        ):
            soc_delta = end_soc - self._session_start_soc
            if soc_delta > 5:  # Need at least 5% delta for meaningful estimate
                # capacity_estimate = energy / (delta% / 100)
                capacity_estimate = session_energy_kwh / (soc_delta / 100.0)
                # Sanity check: estimate should be within 50-150% of configured
                if 0.5 * capacity <= capacity_estimate <= 1.5 * capacity:
                    sample = {
                        "method": "partial_cycle",
                        "energy_kwh": round(session_energy_kwh, 2),
                        "soc_start": round(self._session_start_soc, 1),
                        "soc_end": round(end_soc, 1),
                        "capacity_estimate_kwh": round(capacity_estimate, 2),
                    }

        if sample:
            self._battery_health_samples.append(sample)
            if len(self._battery_health_samples) > MAX_HEALTH_SAMPLES:
                self._battery_health_samples = self._battery_health_samples[-MAX_HEALTH_SAMPLES:]
            self._calculate_battery_health()

        # Bootstrap: the first completed session anchors SOC when nothing
        # else can. This block used to ALSO subtract the session energy for
        # an already-anchored detector, and that was the other half of a
        # cancelling pair (#708): the live path added it (wrong sign), this
        # one took it away, so the value at disconnect landed near the truth
        # while the on-screen number stayed inverted for the whole charge.
        # With ``update_energy`` booking each cycle correctly, subtracting
        # the total again here is a straight double-count — 5 kWh into a
        # 40 kWh pack at 50 % would read 73 % instead of 61.5 %. The
        # bootstrap stays because ``update_energy`` is deliberately inert
        # while unanchored, which makes this the only path a sensorless
        # install ever gets a reference from.
        if not self._full_detected and not self._soc_anchored \
                and session_energy_kwh > 0 and capacity > 0:
            efficiency = self._charge_efficiency()
            energy_to_battery = session_energy_kwh * efficiency
            # Assume car arrived at target_soc minus what it accepted
            target = self._config.get("ev_target_soc", 80)
            soc_added = energy_to_battery / capacity * 100.0
            pre_charge_soc = max(0, target - soc_added)
            self._estimated_soc = min(100.0, pre_charge_soc + soc_added)
            self._energy_since_full = (100.0 - self._estimated_soc) / 100.0 * capacity
            self._soc_anchored = True
            _LOGGER.info(
                "SOC bootstrapped from first session: %.1f kWh delivered "
                "(%.1f%% added) → estimated SOC %.1f%%",
                session_energy_kwh, soc_added, self._estimated_soc,
            )

        self._session_start_soc = None

    def reset_session(self) -> None:
        """Reset session-specific state (called when EV disconnects)."""
        self._buffer.clear()
        self._session_peak_w = 0.0
        self._declining_phase = False
        self._full_detected = False
        self._full_confirm_count = 0
        self._settling_counter = 0
        self._last_setpoint = 0.0
        self._sem_has_offered = False  # #708 — withdrawal is session-scoped
        self._session_start_soc = None
        # #708 — the anchor is meaningless across sessions (unknown car,
        # unknown driving in between); the bootstrap in get_virtual_soc
        # re-arms it from the first reading of the next session.
        self._soc_anchor_value = None
        self._soc_anchor_session_kwh = None
        self._estimate_stop_active = False
        # #438 — reset session-energy accumulator + integration state
        self._current_session_energy_kwh = 0.0
        self._last_energy_timestamp = None
        self._last_energy_power_w = 0.0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------
    #
    # (#440) ``calculate_nights_until_charge`` / ``record_skip`` /
    # ``reset_skips`` and the ``_consecutive_skips`` field were removed.
    # The charge mode is the sole authority on whether to charge — the
    # taper detector is display-only now (taper trend, estimated SOC,
    # battery health).

    def get_state(self) -> Dict[str, Any]:
        """Export persistent state for storage."""
        return {
            "last_full_charge": self._last_full_timestamp,
            "energy_since_full": round(self._energy_since_full, 3),
            "estimated_soc": round(self._estimated_soc, 1),
            "battery_health_samples": self._battery_health_samples,
            "battery_health_pct": round(self._battery_health_pct, 1),
            "soc_anchored": self._soc_anchored,
            "hw_total_at_full": self._hw_total_at_full,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore persistent state from storage. (#440) ``consecutive_skips``
        is silently ignored on restore — older payloads remain compatible
        but the field is no longer tracked."""
        self._last_full_timestamp = state.get("last_full_charge")
        self._energy_since_full = state.get("energy_since_full", 0.0)
        self._estimated_soc = state.get("estimated_soc", 0.0)
        self._battery_health_samples = state.get("battery_health_samples", [])
        self._battery_health_pct = state.get("battery_health_pct", 0.0)
        self._soc_anchored = state.get("soc_anchored", False)
        self._hw_total_at_full = state.get("hw_total_at_full")

    # ------------------------------------------------------------------
    # History seeding — bootstrap from recorder on startup
    # ------------------------------------------------------------------

    async def async_seed_from_history(
        self,
        hass: "HomeAssistant",
        ev_power_entity: Optional[str],
        days: int = 60,
    ) -> Optional[Dict[str, Any]]:
        """Seed EV intelligence from recorder history on startup.

        Queries the last `days` of EV charging power to detect:
        1. Charge sessions (power > 0.5 kW for > 5 minutes)
        2. Last full charge (taper pattern: peak > 3 kW declining to 0)
        3. Energy since last full charge
        4. Daily consumption per weekday (for skip logic predictor)

        Only updates fields that improve on existing data — never overwrites
        a more recent last_full_charge with an older one from history.

        Returns dict with 'weekday_totals' for predictor seeding, or None
        if no useful history found.
        """
        if not ev_power_entity:
            return None

        try:
            from homeassistant.components.recorder import get_instance
            from homeassistant.components.recorder.history import state_changes_during_period
            from homeassistant.util import dt as dt_util
            from datetime import timedelta as _timedelta

            end = dt_util.utcnow()
            start = end - _timedelta(days=days)

            history = await get_instance(hass).async_add_executor_job(
                state_changes_during_period,
                hass, start, end, str(ev_power_entity),
            )

            states = history.get(ev_power_entity, [])
            if len(states) < 10:
                _LOGGER.debug("EV history: only %d entries, skipping seed", len(states))
                return None

        except Exception as e:
            _LOGGER.debug("Could not read EV history from recorder: %s", e)
            # (HA Repairs, 2026-06-06) Surface a one-time Repair so the
            # user knows EV / forecast bootstrap won't work until the
            # recorder integration is healthy. Idempotent.
            try:
                from . import repair_issues as _ri
                _ri.raise_no_recorder(hass)
            except Exception:  # noqa: BLE001
                pass
            return None

        # Detect sensor unit to apply correct scale factor. Some EV power
        # sensors report in W (e.g. KEBA actual_power), others in kW. The
        # thresholds below are in kW, so this converts to kW.
        #
        # #641 — this was its own sixth match rule: ``== "w"``, with everything
        # else (including "kw", "KW", "kilowatt" AND an unlabelled sensor)
        # assumed to be kW. Two consequences it now stops having:
        #   * an MQTT/template sensor labelled "kw" was already kW and was left
        #     alone by luck, but a "W "-with-trailing-space sensor was read
        #     1000x too high;
        #   * an UNLABELLED sensor was assumed kW here while
        #     ``sensor_reader._read_sensor`` — reading the very same entity on
        #     the live path — assumes W. The history bootstrap and the live
        #     reader disagreed by 1000x about one sensor. Shared rule now, so
        #     unlabelled means W in both.
        entity = hass.states.get(ev_power_entity)
        w_per_unit = power_unit_scale(entity)

        # Parse into (timestamp, power_kw) pairs
        readings = []
        for state in states:
            try:
                val = float(state.state) * w_per_unit / 1000.0
                readings.append((state.last_changed, val))
            except (ValueError, TypeError):
                continue

        if not readings:
            return None

        # Detect sessions: power > 0.5 kW sustained > 5 minutes
        sessions = []
        in_session = False
        session_start = None
        peak_kw = 0.0
        energy_kwh = 0.0
        prev_time = None
        prev_val = 0.0
        had_decline = False  # Track if power declined from peak (taper)

        for ts, val in readings:
            if val > 0.5 and not in_session:
                in_session = True
                session_start = ts
                peak_kw = val
                energy_kwh = 0.0
                prev_time = ts
                prev_val = val
                had_decline = False
            elif val > 0.5 and in_session:
                if val < peak_kw * 0.7:
                    had_decline = True
                peak_kw = max(peak_kw, val)
                if prev_time:
                    dt_hours = (ts - prev_time).total_seconds() / 3600
                    if 0 < dt_hours < 1:  # Skip gaps > 1 hour
                        energy_kwh += (prev_val + val) / 2 * dt_hours
                prev_time = ts
                prev_val = val
            elif val <= 0.5 and in_session:
                in_session = False
                duration_min = (ts - session_start).total_seconds() / 60
                if duration_min > 5 and energy_kwh > 0.3:
                    # Detect taper-to-full: peak > 3 kW, power declined, ended at ~0
                    is_full = peak_kw > 3.0 and had_decline and val < 0.1
                    sessions.append({
                        "start": session_start,
                        "end": ts,
                        "energy_kwh": energy_kwh,
                        "peak_kw": peak_kw,
                        "weekday": session_start.weekday(),
                        "is_full": is_full,
                    })

        if not sessions:
            _LOGGER.debug("EV history: no charge sessions found in %d days", days)
            return None

        improved = False

        # Find last full charge from history
        full_sessions = [s for s in sessions if s["is_full"]]
        if full_sessions:
            latest_full = full_sessions[-1]
            latest_full_ts = latest_full["end"].isoformat()

            # Only update if we don't have a last_full_charge or history has a newer one
            if (not self._last_full_timestamp
                    or latest_full_ts > self._last_full_timestamp):
                self._last_full_timestamp = latest_full_ts
                # Sum energy from all sessions after this full charge
                energy_after = sum(
                    s["energy_kwh"] for s in sessions
                    if s["end"] > latest_full["end"]
                )
                capacity = self._config.get("ev_battery_capacity_kwh", 40)
                # Cold-start seed, NOT the deficit accumulator (#708). At boot
                # all recorder history offers is "the car took this much back
                # since it was last full"; how far it was driven in between is
                # unknowable, so this is a heuristic stand-in, not a measured
                # deficit. Do not "correct" it to subtract like update_energy
                # does — that yields SOC 100 % forever, the #245 failure. The
                # first real SOC reading or taper overwrites it either way.
                self._energy_since_full = energy_after
                self._estimated_soc = max(
                    0.0, 100.0 - (energy_after / capacity * 100.0)
                ) if capacity > 0 else 0.0
                self._soc_anchored = True
                improved = True
                _LOGGER.info(
                    "EV history seed: last full charge at %s (peak %.0fkW), "
                    "%.1f kWh since → SOC %.0f%%",
                    latest_full_ts[:16], latest_full["peak_kw"],
                    energy_after, self._estimated_soc,
                )

        # Seed daily consumption per weekday (EWMA-compatible averages)
        from collections import defaultdict
        weekday_energy: dict[int, list[float]] = defaultdict(list)
        # Group sessions by day, sum per day
        day_totals: dict[str, float] = defaultdict(float)
        day_weekdays: dict[str, int] = {}
        for s in sessions:
            day_key = s["start"].strftime("%Y-%m-%d")
            day_totals[day_key] += s["energy_kwh"]
            day_weekdays[day_key] = s["weekday"]

        for day_key, total in day_totals.items():
            weekday_energy[day_weekdays[day_key]].append(total)

        # Build weekday averages for predictor seeding
        weekday_averages: Dict[int, float] = {}
        for dow, values in weekday_energy.items():
            weekday_averages[dow] = round(sum(values) / len(values), 1)

        if weekday_averages:
            avg_daily = sum(weekday_averages.values()) / len(weekday_averages)
            _LOGGER.info(
                "EV history seed: avg daily consumption %.1f kWh across %d days "
                "(Mon=%.1f, Tue=%.1f, Wed=%.1f, Thu=%.1f, Fri=%.1f, Sat=%.1f, Sun=%.1f)",
                avg_daily, len(day_totals),
                weekday_averages.get(0, 0), weekday_averages.get(1, 0),
                weekday_averages.get(2, 0), weekday_averages.get(3, 0),
                weekday_averages.get(4, 0), weekday_averages.get(5, 0),
                weekday_averages.get(6, 0),
            )

        _LOGGER.info(
            "EV history seed complete: %d sessions found, %d full charges, "
            "%d weekdays with data",
            len(sessions), len(full_sessions), len(weekday_energy),
        )

        # (HA Repairs) Recorder is clearly healthy — clear any prior issue.
        try:
            from . import repair_issues as _ri
            _ri.clear_no_recorder(hass)
        except Exception:  # noqa: BLE001
            pass
        return {
            "improved": improved,
            "weekday_totals": weekday_averages,
            "session_count": len(sessions),
        }

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def last_full_timestamp(self) -> Optional[str]:
        """ISO timestamp of last detected full charge."""
        return self._last_full_timestamp

    @property
    def energy_since_full(self) -> float:
        """kWh consumed since last detected full charge."""
        return self._energy_since_full

    @property
    def estimated_soc(self) -> float:
        """Current virtual SOC estimate (0-100%)."""
        return self._estimated_soc

    @property
    def full_detected(self) -> bool:
        """Whether a full charge was detected this session."""
        return self._full_detected

    @property
    def still_full(self) -> bool:
        """Anchored at a completed charge with nothing drawn since (#756).

        The same predicate the SOC estimate pins itself to 100 % on
        (``_soc_anchored and _energy_since_full < 0.1``), published under
        one honest name so the night demand collector does not reach into
        privates. An unanchored detector has no completed-charge reference
        and therefore no opinion — it must never read as a full car.
        """
        return bool(self._soc_anchored) and float(self._energy_since_full) < 0.1

    @property
    def battery_health_pct(self) -> float:
        """Estimated EV battery health (%)."""
        return self._battery_health_pct

    # ------------------------------------------------------------------
    # Internal analysis
    # ------------------------------------------------------------------

    def _analyze(self, current_power: float) -> EVTaperData:
        """Run taper analysis on BMS-only samples."""
        if self._session_peak_w < SESSION_PEAK_MIN:
            return EVTaperData()

        taper_ratio = (current_power / self._session_peak_w * 100.0) if self._session_peak_w > 0 else 0.0

        # Filter to BMS-only samples (last 5 minutes)
        bms_samples = self._get_bms_samples(minutes=5)

        if len(bms_samples) < MIN_SAMPLES:
            return EVTaperData(
                trend="unknown",
                taper_ratio_pct=round(taper_ratio, 1),
                ev_full_detected=self._full_detected,
            )

        slope = self._linear_regression(bms_samples)
        trend = self._classify_trend(slope)

        if trend == "declining":
            self._declining_phase = True

        minutes_to_full = 0.0
        if trend == "declining" and slope < 0 and current_power > FULL_POWER_THRESHOLD:
            minutes_to_full = min(MAX_ETA_MINUTES, current_power / abs(slope))

        taper_detected = (
            trend == "declining"
            and taper_ratio < TAPER_RATIO_DETECTED
        )

        return EVTaperData(
            trend=trend,
            taper_ratio_pct=round(taper_ratio, 1),
            slope_w_per_min=round(slope, 1),
            minutes_to_full=round(minutes_to_full, 1),
            ev_full_detected=self._full_detected,
        )

    def _get_bms_samples(self, minutes: float = 5.0) -> List[Tuple[float, float]]:
        """Get BMS-only samples as (elapsed_minutes, power_w) tuples.

        Filters out samples where SEM changed the setpoint (settling window).
        Only returns samples from the last `minutes` of data.
        """
        if not self._buffer:
            return []

        cutoff = time.monotonic() - minutes * 60
        result = []
        ref_time = None

        for sample in self._buffer:
            if sample.timestamp < cutoff:
                continue
            if sample.sem_changed:
                continue
            if ref_time is None:
                ref_time = sample.timestamp
            elapsed_min = (sample.timestamp - ref_time) / 60.0
            result.append((elapsed_min, sample.ev_power))

        return result

    @staticmethod
    def _linear_regression(samples: List[Tuple[float, float]]) -> float:
        """OLS linear regression slope (W/min). Pure Python, no numpy.

        Args:
            samples: List of (elapsed_minutes, power_w) tuples.

        Returns:
            Slope in W/min (negative = power declining).
        """
        n = len(samples)
        if n < 2:
            return 0.0

        sum_t = sum(s[0] for s in samples)
        sum_p = sum(s[1] for s in samples)
        sum_tp = sum(s[0] * s[1] for s in samples)
        sum_t2 = sum(s[0] ** 2 for s in samples)

        denom = n * sum_t2 - sum_t ** 2
        if abs(denom) < 1e-10:
            return 0.0

        return (n * sum_tp - sum_t * sum_p) / denom

    @staticmethod
    def _classify_trend(slope_w_per_min: float) -> str:
        """Classify power trend from regression slope."""
        if slope_w_per_min < TAPER_SLOPE_THRESHOLD:
            return "declining"
        if slope_w_per_min > abs(TAPER_SLOPE_THRESHOLD):
            return "rising"
        return "stable"

    def _calculate_battery_health(self) -> None:
        """Estimate battery health from charge session data.

        Uses capacity estimates from both full-cycle and partial-cycle
        sessions. Health = average estimated capacity / rated capacity.
        """
        if len(self._battery_health_samples) < 3:
            return

        capacity = self._config.get("ev_battery_capacity_kwh", 40)
        if capacity <= 0:
            return

        # Use the last 10 samples — each has a capacity_estimate_kwh
        recent = self._battery_health_samples[-10:]
        estimates = [s["capacity_estimate_kwh"] for s in recent if "capacity_estimate_kwh" in s]

        if not estimates:
            return

        avg_capacity = sum(estimates) / len(estimates)
        self._battery_health_pct = min(100.0, round(avg_capacity / capacity * 100.0, 1))
