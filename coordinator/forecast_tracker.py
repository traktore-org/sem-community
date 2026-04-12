"""Forecast accuracy tracking and correction factor calculation.

Tracks hourly forecast vs actual solar production to:
1. Calculate daily/weekly forecast accuracy
2. Derive a rolling correction factor (actual/forecast ratio)
3. Store history for future ML training

The correction factor is a simple but effective approach:
- Tracks the ratio of actual solar production vs forecast per day
- Rolling 7-day average for smoothing
- Applied to raw forecasts to improve accuracy over time
"""
import logging
from collections import deque
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Dict, List, Optional

from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Maximum days of history to keep
MAX_HISTORY_DAYS = 90

# Minimum forecast value to compute ratio (avoid division by near-zero)
MIN_FORECAST_KWH = 0.5


@dataclass
class DailyForecastRecord:
    """One day's forecast vs actual record."""
    date: str  # YYYY-MM-DD
    forecast_kwh: float = 0.0
    actual_kwh: float = 0.0
    weather: str = "unknown"  # sunny, cloudy, rainy, etc.
    accuracy_pct: float = 0.0  # actual/forecast * 100
    correction_factor: float = 1.0  # actual/forecast ratio


class ForecastTracker:
    """Tracks forecast accuracy and computes correction factors."""

    def __init__(self):
        """Initialize forecast tracker."""
        self._history: deque = deque(maxlen=MAX_HISTORY_DAYS)
        self._today_forecast: float = 0.0
        self._today_actual: float = 0.0
        self._today_date: Optional[str] = None
        self._correction_factor: float = 1.0
        self._weather_today: str = "unknown"

    def update(
        self,
        forecast_today_kwh: float,
        actual_solar_kwh: float,
        weather_condition: str = "unknown",
    ) -> None:
        """Update tracker with current forecast and actual values.

        Called every coordinator cycle (~10s). Handles day rollover
        by saving yesterday's record to history.
        """
        today = dt_util.now().strftime("%Y-%m-%d")

        # Day rollover — save yesterday's record
        if self._today_date and self._today_date != today:
            self._save_day_record()

        # Update today's values
        self._today_date = today
        self._today_forecast = forecast_today_kwh
        self._today_actual = actual_solar_kwh
        self._weather_today = weather_condition

        # Recalculate correction factor from history
        self._update_correction_factor()

    def _save_day_record(self) -> None:
        """Save yesterday's forecast vs actual to history."""
        if not self._today_date or self._today_forecast < MIN_FORECAST_KWH:
            return

        accuracy = (self._today_actual / self._today_forecast * 100) if self._today_forecast > 0 else 0
        ratio = self._today_actual / self._today_forecast if self._today_forecast > MIN_FORECAST_KWH else 1.0

        record = DailyForecastRecord(
            date=self._today_date,
            forecast_kwh=round(self._today_forecast, 2),
            actual_kwh=round(self._today_actual, 2),
            weather=self._weather_today,
            accuracy_pct=round(accuracy, 1),
            correction_factor=round(ratio, 3),
        )
        self._history.append(record)
        _LOGGER.info(
            "Forecast record saved: %s forecast=%.1f actual=%.1f accuracy=%.0f%% factor=%.3f weather=%s",
            record.date, record.forecast_kwh, record.actual_kwh,
            record.accuracy_pct, record.correction_factor, record.weather,
        )

    def _update_correction_factor(self) -> None:
        """Calculate correction factor using weather-aware model.

        Tries increasingly specific correction factors:
        1. Same weather + same month (most specific)
        2. Same weather category (any month)
        3. Same month (any weather)
        4. Rolling 7-day average (fallback)
        """
        if not self._history:
            self._correction_factor = 1.0
            return

        now = dt_util.now()
        current_month = now.month
        current_weather = self._normalize_weather(self._weather_today)

        # Try weather + month match (most accurate)
        factor = self._factor_for_conditions(current_weather, current_month)

        if factor is None:
            # Try weather-only match
            factor = self._factor_for_conditions(current_weather, None)

        if factor is None:
            # Try month-only match
            factor = self._factor_for_conditions(None, current_month)

        if factor is None:
            # Fallback: rolling 7-day weighted average
            factor = self._rolling_7d_factor()

        self._correction_factor = max(0.3, min(2.0, factor))

    def _factor_for_conditions(
        self, weather: Optional[str], month: Optional[int]
    ) -> Optional[float]:
        """Calculate correction factor for specific conditions.

        Returns None if fewer than 3 matching records exist.
        """
        matching = []
        for record in self._history:
            if weather and self._normalize_weather(record.weather) != weather:
                continue
            if month and record.date and int(record.date.split("-")[1]) != month:
                continue
            if record.forecast_kwh >= MIN_FORECAST_KWH:
                matching.append(record.correction_factor)

        if len(matching) < 3:
            return None

        # Use last 10 matching records, weighted by recency
        recent = matching[-10:]
        total_weight = 0
        weighted_sum = 0
        for i, factor in enumerate(recent):
            weight = i + 1
            weighted_sum += factor * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else None

    def _rolling_7d_factor(self) -> float:
        """Simple rolling 7-day weighted average fallback."""
        recent = list(self._history)[-7:]
        valid = [r for r in recent if r.forecast_kwh >= MIN_FORECAST_KWH]
        if not valid:
            return 1.0

        total_weight = 0
        weighted_sum = 0
        for i, record in enumerate(valid):
            weight = i + 1
            weighted_sum += record.correction_factor * weight
            total_weight += weight

        return weighted_sum / total_weight if total_weight > 0 else 1.0

    @staticmethod
    def _normalize_weather(condition: str) -> str:
        """Normalize weather conditions into categories.

        HA weather states → 3 categories for grouping:
        - sunny: clear-night, sunny
        - cloudy: cloudy, partlycloudy, fog, windy
        - rainy: rainy, pouring, snowy, lightning, hail, etc.
        """
        c = (condition or "unknown").lower().replace("-", "")
        if c in ("sunny", "clearnight"):
            return "sunny"
        if c in ("cloudy", "partlycloudy", "fog", "windy", "windyvariant"):
            return "cloudy"
        if c in ("rainy", "pouring", "snowy", "snowyrainy", "lightning", "lightningrainy", "hail"):
            return "rainy"
        return "unknown"

    def apply_correction(self, forecast_kwh: float) -> float:
        """Apply correction factor to a forecast value."""
        return round(forecast_kwh * self._correction_factor, 2)

    @property
    def correction_factor(self) -> float:
        """Current correction factor (1.0 = no correction)."""
        return round(self._correction_factor, 3)

    @property
    def accuracy_today(self) -> float:
        """Today's forecast accuracy percentage."""
        if self._today_forecast < MIN_FORECAST_KWH:
            return 0.0
        return round(self._today_actual / self._today_forecast * 100, 1)

    @property
    def accuracy_7d(self) -> float:
        """Average forecast accuracy over last 7 days."""
        recent = list(self._history)[-7:]
        valid = [r.accuracy_pct for r in recent if r.forecast_kwh >= MIN_FORECAST_KWH]
        if not valid:
            return 0.0
        return round(sum(valid) / len(valid), 1)

    @property
    def deviation_today(self) -> float:
        """Today's deviation: actual - forecast (positive = better than forecast)."""
        return round(self._today_actual - self._today_forecast, 2)

    @property
    def weather_category(self) -> str:
        """Current weather category used for correction."""
        return self._normalize_weather(self._weather_today)

    def get_data(self) -> Dict[str, Any]:
        """Return current tracker data for sensors."""
        return {
            "forecast_accuracy_today": self.accuracy_today,
            "forecast_accuracy_7d": self.accuracy_7d,
            "forecast_correction_factor": self.correction_factor,
            "forecast_deviation_kwh": self.deviation_today,
            "forecast_weather_category": self.weather_category,
            "forecast_corrected_today": self.apply_correction(self._today_forecast),
            "forecast_corrected_tomorrow": 0.0,  # Set by caller
            "forecast_history_days": len(self._history),
        }

    def get_state(self) -> Dict[str, Any]:
        """Export state for persistence."""
        return {
            "history": [
                {
                    "date": r.date,
                    "forecast": r.forecast_kwh,
                    "actual": r.actual_kwh,
                    "weather": r.weather,
                    "accuracy": r.accuracy_pct,
                    "factor": r.correction_factor,
                }
                for r in self._history
            ],
            "correction_factor": self._correction_factor,
        }

    def restore_state(self, state: Dict[str, Any]) -> None:
        """Restore state from persistence."""
        if not state:
            return
        for record in state.get("history", []):
            self._history.append(DailyForecastRecord(
                date=record["date"],
                forecast_kwh=record.get("forecast", 0),
                actual_kwh=record.get("actual", 0),
                weather=record.get("weather", "unknown"),
                accuracy_pct=record.get("accuracy", 0),
                correction_factor=record.get("factor", 1.0),
            ))
        self._correction_factor = state.get("correction_factor", 1.0)
        _LOGGER.info(
            "Restored forecast tracker: %d days history, correction factor %.3f",
            len(self._history), self._correction_factor,
        )
