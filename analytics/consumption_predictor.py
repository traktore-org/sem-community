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
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

_LOGGER = logging.getLogger(__name__)

# Minimum days of data before predictions are useful
MIN_TRAINING_DAYS = 3
MAX_HISTORY_DAYS = 90
EWMA_ALPHA = 0.3  # Higher = more weight on recent data


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
        self._last_observation_hour: Optional[int] = None
        self._training_status = "cold_start"

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

    def observe(self, dt: datetime, consumption_w: float, solar_w: float) -> None:
        """Record an hourly observation.

        Call this once per hour (or on each coordinator cycle — it deduplicates
        by hour so only the last value per hour is used).
        """
        hour = dt.hour
        dow = dt.weekday()  # 0=Mon, 6=Sun

        # Deduplicate: only update once per hour
        hour_key = dow * 100 + hour
        if hour_key == self._last_observation_hour:
            return
        self._last_observation_hour = hour_key

        self._consumption_profile.update(dow, hour, consumption_w)
        self._solar_profile.update(dow, hour, solar_w)

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
        """
        if self._training_status == "cold_start":
            return []

        predictions = []
        for i in range(24):
            dt = from_dt + timedelta(hours=i)
            value = self._consumption_profile.predict(dt.weekday(), dt.hour)
            predictions.append(value if value is not None else 0.0)
        return predictions

    def predict_solar_24h(self, from_dt: datetime) -> List[float]:
        """Predict next 24 hours of solar production (W).

        Returns list of 24 hourly values starting from from_dt.
        Returns empty list if not enough training data.
        """
        if self._training_status == "cold_start":
            return []

        predictions = []
        for i in range(24):
            dt = from_dt + timedelta(hours=i)
            value = self._solar_profile.predict(dt.weekday(), dt.hour)
            predictions.append(value if value is not None else 0.0)
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
        """
        solar = self.predict_solar_24h(from_dt)
        consumption = self.predict_consumption_24h(from_dt)
        if not solar or not consumption:
            return ""

        # Find the window with highest surplus (solar - consumption)
        surplus = [s - c for s, c in zip(solar, consumption)]
        if max(surplus) <= 0:
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
            return f"{start_h:02d}:00-{end_h:02d}:00"

        return ""

    def get_state(self) -> Dict[str, Any]:
        """Export state for persistence."""
        return {
            "consumption": self._consumption_profile.get_state(),
            "solar": self._solar_profile.get_state(),
            "training_status": self._training_status,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persistence."""
        if not state:
            return
        self._consumption_profile.restore_state(state.get("consumption", {}))
        self._solar_profile.restore_state(state.get("solar", {}))
        self._training_status = state.get("training_status", "cold_start")
