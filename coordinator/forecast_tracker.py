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
from __future__ import annotations

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

# Real-time dampening: hours of solar production before fully trusting live data
CONFIDENCE_RAMP_HOURS = 3.0

# Outlier detection: cap actual at this multiple of forecast
MAX_ACTUAL_RATIO = 2.0  # Cap outlier days at 2× forecast (was 3.0)

# Daylight window for expected-fraction calculation
SUNRISE_HOUR = 6
SUNSET_HOUR = 20
DAYLIGHT_HOURS = SUNSET_HOUR - SUNRISE_HOUR  # 14


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
        self._hass: Any = None

    def set_hass(self, hass: Any) -> None:
        """Set Home Assistant instance for reading sun.sun entity."""
        self._hass = hass

    def _get_sun_hours(self) -> tuple[float, float]:
        """Get sunrise/sunset hours from sun.sun entity, fallback to defaults.

        Returns (sunrise_hour, sunset_hour) as fractional hours (e.g. 6.5 = 6:30).
        Falls back to module-level constants when sun.sun is unavailable (polar regions
        or HA startup). This prevents hardcoded 6/20 from being wrong in polar areas.
        """
        try:
            if self._hass is not None:
                sun = self._hass.states.get("sun.sun")
                if sun and sun.attributes:
                    rise_str = sun.attributes.get("next_rising", "")
                    sett_str = sun.attributes.get("next_setting", "")
                    if rise_str and sett_str:
                        rise = datetime.fromisoformat(rise_str.replace("Z", "+00:00"))
                        sett = datetime.fromisoformat(sett_str.replace("Z", "+00:00"))
                        # Convert to local time hours
                        local_rise = rise.astimezone(dt_util.DEFAULT_TIME_ZONE)
                        local_sett = sett.astimezone(dt_util.DEFAULT_TIME_ZONE)
                        return (
                            local_rise.hour + local_rise.minute / 60.0,
                            local_sett.hour + local_sett.minute / 60.0,
                        )
        except Exception:
            pass
        return float(SUNRISE_HOUR), float(SUNSET_HOUR)

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

        # Outlier detection: cap actual at MAX_ACTUAL_RATIO × forecast
        actual = self._today_actual
        if actual > self._today_forecast * MAX_ACTUAL_RATIO and self._today_forecast > MIN_FORECAST_KWH:
            _LOGGER.warning(
                "Outlier detected: actual=%.1f exceeds %.0fx forecast=%.1f, capping to %.1f",
                actual, MAX_ACTUAL_RATIO, self._today_forecast,
                self._today_forecast * MAX_ACTUAL_RATIO,
            )
            actual = self._today_forecast * MAX_ACTUAL_RATIO

        accuracy = (actual / self._today_forecast * 100) if self._today_forecast > 0 else 0
        ratio = actual / self._today_forecast if self._today_forecast > MIN_FORECAST_KWH else 1.0

        record = DailyForecastRecord(
            date=self._today_date,
            forecast_kwh=round(self._today_forecast, 2),
            actual_kwh=round(actual, 2),
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

        # Tighten bounds: ±40% max correction (industry standard is ±10-30%)
        factor = max(0.6, min(1.4, factor))
        # Decay toward neutral (1.0): 25% per day — converges in ~7 days
        # Fast enough to correct overcorrection, stable enough to hold genuine offsets
        DECAY = 0.75
        self._correction_factor = round(factor * DECAY + 1.0 * (1 - DECAY), 4)

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
        """Today's corrected forecast accuracy (actual / corrected forecast).

        Shows how accurate the forecast was AFTER correction — what the user sees.
        100% = perfect, >100% = underforecast, <100% = overforecast.
        """
        corrected = self._today_forecast * self._correction_factor
        if corrected < MIN_FORECAST_KWH:
            return 0.0
        return round(self._today_actual / corrected * 100, 1)

    @property
    def raw_accuracy_today(self) -> float:
        """Today's raw forecast accuracy (actual / raw forecast, no correction)."""
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

    @property
    def dampening_factor(self) -> float:
        """Real-time dampening factor blending historical correction with today's performance.

        Ramps from correction_factor (historical) to normalized live ratio
        as confidence increases through the day (0→1 over CONFIDENCE_RAMP_HOURS).
        Works bidirectionally: dampens overestimates AND boosts underestimates.
        """
        return round(self._calculate_dampening_factor(), 3)

    @staticmethod
    def _solar_curve_fraction(solar_hours: float) -> float:
        """Expected fraction of daily solar produced after `solar_hours` since sunrise.

        Uses a sine-curve model matching real solar production patterns:
        low in morning/evening, peak at solar noon. This is much more accurate
        than linear interpolation, which overestimates early morning production
        and leads to false dampening.

        At 1.5h (7:30 AM): ~3.5%   (linear would say 10.7%)
        At 4h   (10 AM):   ~25%    (linear: 28.6%)
        At 7h   (1 PM):    ~55%    (linear: 50%)
        At 10h  (4 PM):    ~82%    (linear: 71.4%)
        """
        import math
        if solar_hours <= 0:
            return 0.0
        if solar_hours >= DAYLIGHT_HOURS:
            return 1.0
        # Sine integral from 0 to t of sin(π·x/T) / integral from 0 to T
        # = (1 - cos(π·t/T)) / 2
        return (1 - math.cos(math.pi * solar_hours / DAYLIGHT_HOURS)) / 2

    @staticmethod
    def _solar_curve_fraction_dynamic(solar_hours: float, daylight_hours: float) -> float:
        """Expected fraction of daily solar using the actual day length.

        Same sine-curve model as _solar_curve_fraction but uses the real
        daylight_hours derived from sun.sun, so the curve is correct in
        polar regions where day length differs significantly from 14h.
        """
        import math
        if solar_hours <= 0:
            return 0.0
        if solar_hours >= daylight_hours:
            return 1.0
        return (1 - math.cos(math.pi * solar_hours / daylight_hours)) / 2

    def _calculate_dampening_factor(self) -> float:
        """Calculate the dampening factor from live data + history.

        Uses actual sunrise/sunset from sun.sun entity so the daylight window
        is correct in polar regions. Falls back to hardcoded defaults when
        sun.sun is unavailable (HA startup, polar night).
        """
        now = dt_util.now()
        hour = now.hour + now.minute / 60.0

        sunrise_hour, sunset_hour = self._get_sun_hours()
        daylight_hours = max(1.0, sunset_hour - sunrise_hour)

        # Outside daylight hours: use historical correction only
        if hour < sunrise_hour or hour > sunset_hour + 1:
            return self._correction_factor

        if self._today_forecast < MIN_FORECAST_KWH:
            return self._correction_factor

        # How many solar hours have elapsed
        solar_hours = max(0, hour - sunrise_hour)

        # Expected fraction using sine-curve model (not linear)
        expected_fraction = self._solar_curve_fraction_dynamic(solar_hours, daylight_hours)
        expected_so_far = self._today_forecast * expected_fraction

        # Too early to judge — not enough expected production yet
        if expected_so_far < MIN_FORECAST_KWH:
            return self._correction_factor

        # Confidence ramps from 0 to 1 over CONFIDENCE_RAMP_HOURS of solar time
        confidence = min(1.0, solar_hours / CONFIDENCE_RAMP_HOURS)

        # Normalized ratio: how today is performing relative to expectation
        # If actual/forecast matches expected_fraction, ratio = 1.0
        live_ratio = self._today_actual / self._today_forecast
        normalized_ratio = live_ratio / expected_fraction if expected_fraction > 0.01 else 1.0

        # Blend: historical correction × (1 - confidence) + live ratio × confidence
        blended = (1 - confidence) * self._correction_factor + confidence * normalized_ratio

        return max(0.5, min(1.5, blended))

    def apply_dampening(self, forecast_kwh: float) -> float:
        """Apply real-time dampening factor to a forecast value."""
        return round(forecast_kwh * self.dampening_factor, 2)

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
            "forecast_dampening_factor": self.dampening_factor,
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
