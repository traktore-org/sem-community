"""Consumption and solar predictor for SEM (#3).

Learns hourly patterns from historical data using pure Python
(no numpy/scikit-learn dependency). Provides next-24h predictions
for home consumption and solar production.

Architecture:
- Hourly profiles: 7 days × 24 hours = 168 bins
- Exponential weighted average (alpha=0.3) for gradual adaptation
- Cold start: returns 0 until at least 3 days of data
- Training: incremental (each hourly sample updates the profile)
- Memory: ~1.5KB (168 floats × 2 models)
"""
import logging
from datetime import datetime, timedelta
from typing import Any, Callable, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# Minimum days of data before predictions are useful
MIN_TRAINING_DAYS = 3
MAX_HISTORY_DAYS = 90
EWMA_ALPHA = 0.3  # Higher = more weight on recent data

# (#1082) Temperature. Home load rises when it is cold (heating, light,
# people inside). The weekday × hour profile already holds the USUAL load
# at the usual temperature of each hour; what the temperature adds is the
# difference between today's cold and that usual cold. Measured in degree
# hours below a base: HDD = max(0, base − T). One slope, W per degree,
# learned from the hours where the load and the cold both differed from
# their usual — a decaying least squares, so it follows the season.
HDD_BASE_C = 15.0
#: per-hour decay of the slope's sums (~6 days half-life)
TEMP_DECAY = 0.995
#: the slope is used only after this much spread in degree hours (sum of
#: squared differences) — a few days of real weather change
TEMP_MIN_SXX = 40.0
#: plausible slope band, W per degree below the base (0 = load does not
#: follow the cold; a big heat-pump house is a few hundred)
TEMP_SLOPE_MAX_W = 1500.0


class HourlyProfile:
    """Exponential weighted hourly profile for a week (168 bins).

    Each bin stores an EWMA of the observed values for that
    (day_of_week, hour) combination.
    """

    def __init__(self, alpha: float = EWMA_ALPHA):
        self._alpha = alpha
        # {(dow, hour): ewma_value}
        self._bins: Dict[tuple, float] = {}
        # {(dow, hour): sample_count}
        self._counts: Dict[tuple, int] = {}

    def update(self, dow: int, hour: int, value: float) -> None:
        """Update the profile with a new observation."""
        key = (dow, hour)
        count = self._counts.get(key, 0)
        if count == 0:
            self._bins[key] = value
        else:
            old = self._bins[key]
            self._bins[key] = self._alpha * value + (1 - self._alpha) * old
        self._counts[key] = count + 1

    def predict(self, dow: int, hour: int) -> Optional[float]:
        """Predict value for a given (day_of_week, hour).

        Returns None if no data for this bin.
        Falls back to same-hour any-day average if specific dow missing.
        """
        key = (dow, hour)
        if key in self._bins:
            return self._bins[key]

        # Fallback: average across all days for this hour
        hour_values = [
            v for (d, h), v in self._bins.items() if h == hour
        ]
        if hour_values:
            return sum(hour_values) / len(hour_values)

        return None

    def total_samples(self) -> int:
        """Total number of samples recorded."""
        return sum(self._counts.values())

    def unique_days(self) -> int:
        """Approximate number of unique days with data."""
        # Count unique (dow, hour=12) entries as proxy for full days
        return len(set(d for (d, h) in self._counts if h == 12))

    def get_state(self) -> Dict[str, Any]:
        """Export state for persistence."""
        return {
            "bins": {f"{d},{h}": v for (d, h), v in self._bins.items()},
            "counts": {f"{d},{h}": c for (d, h), c in self._counts.items()},
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persistence."""
        if not state:
            return
        bins = state.get("bins", {})
        counts = state.get("counts", {})
        self._bins = {
            (int(k.split(",")[0]), int(k.split(",")[1])): v
            for k, v in bins.items()
        }
        self._counts = {
            (int(k.split(",")[0]), int(k.split(",")[1])): v
            for k, v in counts.items()
        }


class ConsumptionPredictor:
    """Predicts home consumption and solar production using hourly profiles.

    Pure Python implementation — no external dependencies.
    Learns from hourly observations and provides 24h forecasts.
    """

    def __init__(self):
        self._consumption_profile = HourlyProfile()
        self._solar_profile = HourlyProfile()
        self._ev_profile = HourlyProfile()  # Daily EV consumption per weekday
        # (#1082) the usual degree hours of each (weekday, hour), and the
        # load-per-degree slope's decaying sums
        self._hdd_profile = HourlyProfile()
        self._t_sxx = 0.0
        self._t_sxy = 0.0
        self._t_samples = 0
        # set by the coordinator each cycle: the hour's temperature (°C) by
        # time, and whether the plans may use the temperature term (soak)
        self._temp_at: Optional[Callable[[datetime], Optional[float]]] = None
        self._temp_use = False
        self._last_temp_path: str = "no_temperature"
        self._last_observation_hour: Optional[int] = None
        self._last_ev_observation_day: Optional[int] = None
        self._training_status = "cold_start"

        # #425 — telemetry surface mirroring #359/#416/#420/#421
        # classifier_path / dampening_path patterns. Each prediction
        # call sets the corresponding ``*_path`` string so callers can
        # tell why a prediction was empty or fell back to defaults.
        self._last_consumption_prediction_path: str = "uninitialized"
        self._last_solar_prediction_path: str = "uninitialized"
        self._last_surplus_window_path: str = "uninitialized"
        self._last_ev_prediction_path: str = "uninitialized"
        self._last_observation_path: str = "uninitialized"

    @property
    def training_status(self) -> str:
        """Current training status: cold_start, learning, trained."""
        return self._training_status

    @property
    def model_accuracy_pct(self) -> float:
        """Rough accuracy estimate based on data coverage."""
        days = self._consumption_profile.unique_days()
        if days < MIN_TRAINING_DAYS:
            return 0.0
        # Coverage-based estimate: 100% after 30 days
        return min(100.0, round(days / 30 * 100, 1))

    def observe(self, dt: datetime, consumption_w: float, solar_w: float,
                temp_c: Optional[float] = None) -> None:
        """Record an hourly observation.

        Call this once per hour (or on each coordinator cycle — it deduplicates
        by hour so only the last value per hour is used).

        Records the observation path on
        ``self._last_observation_path`` (#425):
        ``deduplicated`` / ``recorded``.
        """
        hour = dt.hour
        dow = dt.weekday()  # 0=Mon, 6=Sun

        # Deduplicate: only update once per hour
        hour_key = dow * 100 + hour
        if hour_key == self._last_observation_hour:
            self._last_observation_path = "deduplicated"
            return
        self._last_observation_hour = hour_key

        if temp_c is not None:
            self._learn_temperature(dow, hour, consumption_w, temp_c)
        self._consumption_profile.update(dow, hour, consumption_w)
        self._solar_profile.update(dow, hour, solar_w)
        self._last_observation_path = "recorded"

        # Update training status
        days = self._consumption_profile.unique_days()
        if days >= 7:
            self._training_status = "trained"
        elif days >= MIN_TRAINING_DAYS:
            self._training_status = "learning"
        else:
            self._training_status = "cold_start"

    def predict_consumption_24h(self, from_dt: datetime) -> List[float]:
        """Predict next 24 hours of home consumption (W).

        Returns list of 24 hourly values starting from from_dt.
        Returns empty list if not enough training data.

        Records the prediction path on
        ``self._last_consumption_prediction_path`` (#425):
        ``cold_start_empty`` / ``trained_full`` / ``trained_with_fallback``.
        """
        if self._training_status == "cold_start":
            self._last_consumption_prediction_path = "cold_start_empty"
            return []

        predictions = []
        fallback_count = 0
        for i in range(24):
            dt = from_dt + timedelta(hours=i)
            value = self._consumption_profile.predict(dt.weekday(), dt.hour)
            if value is None:
                fallback_count += 1
                predictions.append(0.0)
            else:
                predictions.append(max(0.0, value + self.temperature_delta_w(dt)))
        if fallback_count == 0:
            self._last_consumption_prediction_path = "trained_full"
        elif fallback_count < 24:
            self._last_consumption_prediction_path = f"trained_with_fallback:{fallback_count}"
        else:
            self._last_consumption_prediction_path = "trained_all_fallback"
        return predictions

    def predict_solar_24h(self, from_dt: datetime) -> List[float]:
        """Predict next 24 hours of solar production (W).

        Returns list of 24 hourly values starting from from_dt.
        Returns empty list if not enough training data.

        Records the prediction path on
        ``self._last_solar_prediction_path`` (#425).
        """
        if self._training_status == "cold_start":
            self._last_solar_prediction_path = "cold_start_empty"
            return []

        predictions = []
        fallback_count = 0
        for i in range(24):
            dt = from_dt + timedelta(hours=i)
            value = self._solar_profile.predict(dt.weekday(), dt.hour)
            if value is None:
                fallback_count += 1
                predictions.append(0.0)
            else:
                predictions.append(value)
        if fallback_count == 0:
            self._last_solar_prediction_path = "trained_full"
        elif fallback_count < 24:
            self._last_solar_prediction_path = f"trained_with_fallback:{fallback_count}"
        else:
            self._last_solar_prediction_path = "trained_all_fallback"
        return predictions

    def predict_consumption_today_kwh(self, from_dt: datetime) -> float:
        """Predict remaining home consumption for today (kWh)."""
        hourly = self.predict_consumption_24h(from_dt)
        if not hourly:
            return 0.0
        # Sum only remaining hours today
        remaining_hours = 24 - from_dt.hour
        return sum(hourly[:remaining_hours]) / 1000.0

    def predict_surplus_window(self, from_dt: datetime) -> str:
        """Predict the best surplus window based on learned patterns.

        Returns time window string like "10:00-14:00" or "" if unknown.

        Records the path on ``self._last_surplus_window_path`` (#425):
        ``no_data`` / ``no_surplus`` / ``found_window``.
        """
        solar = self.predict_solar_24h(from_dt)
        consumption = self.predict_consumption_24h(from_dt)
        if not solar or not consumption:
            self._last_surplus_window_path = "no_data"
            return ""

        # Find the window with highest surplus (solar - consumption)
        surplus = [s - c for s, c in zip(solar, consumption, strict=False)]
        if max(surplus) <= 0:
            self._last_surplus_window_path = "no_surplus"
            return ""

        # Find contiguous window of positive surplus
        best_start = -1
        best_end = -1
        best_total = 0
        current_start = -1
        current_total = 0

        for i, s in enumerate(surplus):
            if s > 0:
                if current_start == -1:
                    current_start = i
                current_total += s
            else:
                if current_total > best_total:
                    best_start = current_start
                    best_end = i
                    best_total = current_total
                current_start = -1
                current_total = 0

        if current_total > best_total:
            best_start = current_start
            best_end = len(surplus)

        if best_start >= 0:
            start_h = (from_dt.hour + best_start) % 24
            end_h = (from_dt.hour + best_end) % 24
            self._last_surplus_window_path = "found_window"
            return f"{start_h:02d}:00-{end_h:02d}:00"

        self._last_surplus_window_path = "no_contiguous_window"
        return ""

    # ── (#1082) temperature ────────────────────────────────────────
    def set_temperature(self, temp_at: Optional[Callable[[datetime], Optional[float]]],
                        use: bool) -> None:
        """The hour's temperature by time (forecast ahead, measured now),
        and whether the plans may use it (the soak flag)."""
        self._temp_at = temp_at
        self._temp_use = bool(use)

    @staticmethod
    def _hdd(temp_c: float) -> float:
        return max(0.0, HDD_BASE_C - float(temp_c))

    def _learn_temperature(self, dow: int, hour: int, load_w: float, temp_c: float) -> None:
        """One hour's lesson: how far the load and the cold were from their
        usual for this weekday and hour. Learns whether or not the plans
        use it, so the slope is ready when the soak flag flips."""
        hdd = self._hdd(temp_c)
        usual_load = self._consumption_profile.predict(dow, hour)
        usual_hdd = self._hdd_profile.predict(dow, hour)
        if usual_load is not None and usual_hdd is not None:
            dx = hdd - usual_hdd
            dy = float(load_w) - usual_load
            self._t_sxx = self._t_sxx * TEMP_DECAY + dx * dx
            self._t_sxy = self._t_sxy * TEMP_DECAY + dx * dy
            self._t_samples += 1
        self._hdd_profile.update(dow, hour, hdd)

    @property
    def temperature_slope_w(self) -> Optional[float]:
        """W of home load per degree below the base, or None until the
        weather has varied enough to tell. Never below 0, never above the
        plausible band (one odd week cannot make a giant slope)."""
        if self._t_sxx < TEMP_MIN_SXX:
            return None
        return min(TEMP_SLOPE_MAX_W, max(0.0, self._t_sxy / self._t_sxx))

    def temperature_delta_w(self, dt: datetime) -> float:
        """What the temperature adds (or takes) at ``dt`` against the usual
        for that weekday and hour, in W. 0 when the flag is off, the slope
        is not known yet, the hour has no temperature, or no usual exists."""
        if not self._temp_use or self._temp_at is None:
            self._last_temp_path = "off" if not self._temp_use else "no_temperature"
            return 0.0
        slope = self.temperature_slope_w
        if slope is None:
            self._last_temp_path = "learning"
            return 0.0
        try:
            t = self._temp_at(dt)
        except Exception:  # noqa: BLE001 — a missing forecast hour is no temperature
            t = None
        usual_hdd = self._hdd_profile.predict(dt.weekday(), dt.hour)
        if t is None or usual_hdd is None:
            self._last_temp_path = "no_temperature"
            return 0.0
        self._last_temp_path = "applied"
        return slope * (self._hdd(t) - usual_hdd)

    def observe_ev(self, dt: datetime, daily_ev_kwh: float) -> None:
        """Record daily EV consumption for weekday-based prediction.

        Call once per day (at day rollover). Uses (dow, hour=12) as the
        bin key — one value per day-of-week.

        Args:
            dt: Current datetime (day-of-week determines the bin).
            daily_ev_kwh: Total EV energy consumed today (kWh).
        """
        dow = dt.weekday()
        day_key = dt.toordinal()

        # Deduplicate: only one observation per calendar day
        if day_key == self._last_ev_observation_day:
            return
        self._last_ev_observation_day = day_key

        self._ev_profile.update(dow, 12, daily_ev_kwh)
        _LOGGER.debug(
            "EV predictor: observed %.1f kWh on %s (dow=%d)",
            daily_ev_kwh, dt.strftime("%A"), dow,
        )

    def predict_ev_consumption_tomorrow(self, from_dt: datetime) -> float:
        """Predict tomorrow's EV consumption in kWh.

        Uses the learned weekday profile. Returns 0.0 if no data
        for tomorrow's day-of-week.

        Records the prediction path on
        ``self._last_ev_prediction_path`` (#425):
        ``weekday_match`` / ``hour_fallback`` / ``no_data``.
        """
        tomorrow = from_dt + timedelta(days=1)
        dow = tomorrow.weekday()
        value = self._ev_profile.predict(dow, 12)
        if value is None:
            self._last_ev_prediction_path = "no_data"
            return 0.0
        # HourlyProfile.predict returns the dow-exact bin if present,
        # else a hour-only average. Detect which path fired by
        # re-checking the exact bin.
        if (dow, 12) in self._ev_profile._bins:
            self._last_ev_prediction_path = "weekday_match"
        else:
            self._last_ev_prediction_path = "hour_fallback"
        return round(value, 1)

    def get_diagnostics(self) -> Dict[str, Any]:
        """Return the audit telemetry surface (#425).

        Used by the coordinator to expose the ``*_path`` strings on the
        existing consumption-prediction sensors. Mirrors the
        ``get_data`` pattern in ``forecast_tracker.py`` from #416.
        """
        return {
            "consumption_prediction_path": self._last_consumption_prediction_path,
            "solar_prediction_path": self._last_solar_prediction_path,
            "surplus_window_path": self._last_surplus_window_path,
            "ev_prediction_path": self._last_ev_prediction_path,
            "observation_path": self._last_observation_path,
            "training_status": self._training_status,
            "consumption_samples": self._consumption_profile.total_samples(),
            "consumption_unique_days": self._consumption_profile.unique_days(),
            # (#1082)
            "temperature_path": self._last_temp_path,
            "temperature_slope_w_per_k": (None if self.temperature_slope_w is None
                                          else round(self.temperature_slope_w, 1)),
            "temperature_samples": self._t_samples,
            "temperature_in_plans": self._temp_use,
        }

    def get_state(self) -> Dict[str, Any]:
        """Export state for persistence."""
        return {
            "consumption": self._consumption_profile.get_state(),
            "solar": self._solar_profile.get_state(),
            "ev": self._ev_profile.get_state(),
            "training_status": self._training_status,
            # (#1082)
            "hdd": self._hdd_profile.get_state(),
            "t_sxx": self._t_sxx, "t_sxy": self._t_sxy, "t_samples": self._t_samples,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persistence."""
        if not state:
            return
        self._consumption_profile.restore_state(state.get("consumption", {}))
        self._solar_profile.restore_state(state.get("solar", {}))
        self._ev_profile.restore_state(state.get("ev", {}))
        self._training_status = state.get("training_status", "cold_start")
        # (#1082) absent in a store from before: starts learning from zero
        self._hdd_profile.restore_state(state.get("hdd", {}))
        try:
            self._t_sxx = float(state.get("t_sxx", 0.0) or 0.0)
            self._t_sxy = float(state.get("t_sxy", 0.0) or 0.0)
            self._t_samples = int(state.get("t_samples", 0) or 0)
        except (TypeError, ValueError):
            self._t_sxx = self._t_sxy = 0.0
            self._t_samples = 0
