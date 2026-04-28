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
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from .types import EVTaperData

_LOGGER = logging.getLogger(__name__)

# Buffer and detection constants
BUFFER_SIZE = 120          # 120 samples × 10s = 20 minutes
MIN_SAMPLES = 12           # At least 2 min of BMS-only data for regression
SETTLING_CYCLES = 3        # Ignore 3 cycles (30s) after SEM setpoint change
TAPER_SLOPE_THRESHOLD = -5.0   # W/min — steeper than this = declining
FULL_POWER_THRESHOLD = 50      # W — below this after declining = car full
SESSION_PEAK_MIN = 500         # W — minimum peak to consider a real session
TAPER_RATIO_NEARLY_FULL = 50   # % — below this = nearly full
TAPER_RATIO_DETECTED = 70     # % — below this + declining = taper confirmed
MAX_ETA_MINUTES = 60           # Cap completion estimate
MAX_HEALTH_SAMPLES = 20        # Bounded battery health sample buffer


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
        # Consecutive night charge skip counter (safety net)
        self._consecutive_skips: int = 0
        # Session SOC tracking for partial-charge health estimates
        self._session_start_soc: Optional[float] = None

    # ------------------------------------------------------------------
    # Public API — called each coordinator cycle
    # ------------------------------------------------------------------

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

        # Track session peak (only from sustained readings > threshold)
        if ev_power > self._session_peak_w and ev_power > SESSION_PEAK_MIN:
            self._session_peak_w = ev_power

        # Append sample
        self._buffer.append(PowerSample(
            timestamp=mono,
            ev_power=ev_power,
            current_setpoint=current_setpoint,
            sem_changed=sem_changed,
        ))

        # Check for full charge (0W after declining from a real charging session)
        # Require peak > 3000W to avoid false triggers from night charging toggles
        if (self._declining_phase
                and ev_power < FULL_POWER_THRESHOLD
                and self._session_peak_w > 3000):
            if not self._full_detected:
                self._full_detected = True
                self._last_full_timestamp = timestamp.isoformat()
                self._energy_since_full = 0.0
                self._estimated_soc = 100.0
                self._soc_anchored = True
                _LOGGER.info(
                    "EV full charge detected at %s (peak was %.0fW) — SOC anchored at 100%%",
                    self._last_full_timestamp, self._session_peak_w,
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

    def update_energy(self, ev_energy_increment_kwh: float) -> None:
        """Accumulate energy consumed since last full charge.

        Called each coordinator cycle with the incremental EV energy.
        """
        if ev_energy_increment_kwh > 0:
            self._energy_since_full += ev_energy_increment_kwh

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
            self._last_real_soc = vehicle_soc
            self._soc_anchored = True
            # Track session start SOC for health calculation
            if self._session_start_soc is None:
                self._session_start_soc = vehicle_soc
            return vehicle_soc

        if capacity <= 0:
            return 0.0

        self._estimated_soc = max(
            0.0,
            min(100.0, 100.0 - (self._energy_since_full / capacity * 100.0)),
        )
        return self._estimated_soc

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

        # Update virtual SOC: charging adds energy back
        # (taper/full detection already handled above — this covers partial charges)
        if not self._full_detected and session_energy_kwh > 0 and capacity > 0:
            efficiency = self._config.get("ev_charger_efficiency", 0.92)
            energy_to_battery = session_energy_kwh * efficiency
            self._energy_since_full = max(0, self._energy_since_full - energy_to_battery)
            self._estimated_soc = min(
                100.0, 100.0 - (self._energy_since_full / capacity * 100.0)
            )
            # Bootstrap: first session anchors SOC if no prior reference
            if not self._soc_anchored:
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
            else:
                _LOGGER.info(
                    "SOC updated after charge: +%.1f kWh (%.0f%% eff) → SOC %.1f%%",
                    session_energy_kwh, efficiency * 100, self._estimated_soc,
                )

        self._session_start_soc = None

    def reset_session(self) -> None:
        """Reset session-specific state (called when EV disconnects)."""
        self._buffer.clear()
        self._session_peak_w = 0.0
        self._declining_phase = False
        self._full_detected = False
        self._settling_counter = 0
        self._last_setpoint = 0.0
        self._session_start_soc = None

    # ------------------------------------------------------------------
    # Night charge skip helpers
    # ------------------------------------------------------------------

    def calculate_nights_until_charge(
        self,
        predicted_daily_kwh: float,
        vehicle_soc: Optional[float] = None,
    ) -> Tuple[int, bool, str]:
        """Calculate nights until charge is needed.

        Returns:
            (nights_remaining, charge_needed, skip_reason)
        """
        capacity = self._config.get("ev_battery_capacity_kwh", 40)
        target_soc = self._config.get("ev_target_soc", 80)
        min_soc = self._config.get("ev_min_soc_threshold", 20)

        # No anchor yet (no taper, no car API, no session) → safe default
        if not self._soc_anchored and vehicle_soc is None:
            return (0, True, "No charge history yet")

        # Safety net: max 3 consecutive skips, then force charge
        max_skips = self._config.get("ev_max_consecutive_skips", 3)
        if self._consecutive_skips >= max_skips:
            return (0, True, f"Safety: {self._consecutive_skips} consecutive skips reached")

        soc = self.get_virtual_soc(vehicle_soc)

        if capacity <= 0 or predicted_daily_kwh <= 0:
            return (99, False, "Insufficient data")

        predicted_soc_drop = predicted_daily_kwh / capacity * 100.0
        safety = 1.3  # 30% safety margin

        # Already above target
        if soc > target_soc:
            nights = max(0, int((soc - min_soc) / predicted_soc_drop)) if predicted_soc_drop > 0 else 99
            return (nights, False, f"SOC {soc:.0f}% above target {target_soc}%")

        # Enough range with safety margin
        if soc - predicted_soc_drop * safety > min_soc:
            nights = max(0, int((soc - min_soc) / predicted_soc_drop)) if predicted_soc_drop > 0 else 0
            return (nights, False, f"SOC {soc:.0f}%, {nights} nights range")

        # Charge needed
        return (0, True, f"SOC {soc:.0f}% — charge recommended")

    def record_skip(self) -> None:
        """Record that tonight's night charge was skipped."""
        self._consecutive_skips += 1
        _LOGGER.debug("Consecutive night charge skips: %d", self._consecutive_skips)

    def reset_skips(self) -> None:
        """Reset skip counter (called when charging happens)."""
        if self._consecutive_skips > 0:
            _LOGGER.debug("Consecutive skip counter reset (was %d)", self._consecutive_skips)
        self._consecutive_skips = 0

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def get_state(self) -> Dict[str, Any]:
        """Export persistent state for storage."""
        return {
            "last_full_charge": self._last_full_timestamp,
            "energy_since_full": round(self._energy_since_full, 3),
            "estimated_soc": round(self._estimated_soc, 1),
            "battery_health_samples": self._battery_health_samples,
            "battery_health_pct": round(self._battery_health_pct, 1),
            "consecutive_skips": self._consecutive_skips,
            "soc_anchored": self._soc_anchored,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore persistent state from storage."""
        self._last_full_timestamp = state.get("last_full_charge")
        self._energy_since_full = state.get("energy_since_full", 0.0)
        self._estimated_soc = state.get("estimated_soc", 0.0)
        self._battery_health_samples = state.get("battery_health_samples", [])
        self._battery_health_pct = state.get("battery_health_pct", 0.0)
        self._consecutive_skips = state.get("consecutive_skips", 0)
        self._soc_anchored = state.get("soc_anchored", False)

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
