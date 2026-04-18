"""Solar forecast reader for Solar Energy Management.

Reads forecast data from existing HA integrations:
- Solcast PV Solar (HACS) — sensor.solcast_pv_forecast_*
- Forecast.Solar (built-in) — sensor.energy_production_*
- Custom sensors via configuration

Provides remaining-today and tomorrow forecasts for:
- Charging planning (enough solar to skip night charging?)
- Device scheduling (when will surplus be available?)
- PV performance analysis (actual vs expected)
"""
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from homeassistant.core import HomeAssistant
from homeassistant.const import STATE_UNKNOWN, STATE_UNAVAILABLE
from homeassistant.util import dt as dt_util

_LOGGER = logging.getLogger(__name__)

# Known forecast entity patterns
SOLCAST_ENTITIES = {
    "forecast_today": "sensor.solcast_pv_forecast_forecast_today",
    "forecast_tomorrow": "sensor.solcast_pv_forecast_forecast_tomorrow",
    "forecast_remaining": "sensor.solcast_pv_forecast_forecast_remaining_today",
    "power_now": "sensor.solcast_pv_forecast_power_now",
    "power_next_hour": "sensor.solcast_pv_forecast_power_next_hour",
    "peak_power_today": "sensor.solcast_pv_forecast_peak_forecast_today",
    "peak_time_today": "sensor.solcast_pv_forecast_peak_time_today",
}

FORECAST_SOLAR_ENTITIES = {
    "forecast_today": "sensor.energy_production_today",
    "forecast_tomorrow": "sensor.energy_production_tomorrow",
    "power_now": "sensor.energy_production_now",
}


@dataclass
class ForecastData:
    """Solar forecast data."""
    # Energy forecasts (kWh)
    forecast_today_kwh: float = 0.0
    forecast_tomorrow_kwh: float = 0.0
    forecast_remaining_today_kwh: float = 0.0

    # Power forecasts (W)
    power_now_w: float = 0.0
    power_next_hour_w: float = 0.0
    peak_power_today_w: float = 0.0
    peak_time_today: Optional[str] = None

    # Source info
    source: str = "none"
    available: bool = False
    last_update: Optional[datetime] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "forecast_today_kwh": round(self.forecast_today_kwh, 2),
            "forecast_tomorrow_kwh": round(self.forecast_tomorrow_kwh, 2),
            "forecast_remaining_today_kwh": round(self.forecast_remaining_today_kwh, 2),
            "forecast_power_now_w": round(self.power_now_w, 0),
            "forecast_power_next_hour_w": round(self.power_next_hour_w, 0),
            "forecast_peak_power_today_w": round(self.peak_power_today_w, 0),
            "forecast_peak_time_today": self.peak_time_today,
            "forecast_source": self.source,
            "forecast_available": self.available,
        }


class ForecastReader:
    """Reads solar production forecasts from HA integrations."""

    def __init__(
        self,
        hass: HomeAssistant,
        custom_entities: Optional[Dict[str, str]] = None,
    ):
        self.hass = hass
        self._custom_entities = custom_entities or {}
        self._source: Optional[str] = None
        self._entities: Dict[str, str] = {}
        self._last_data = ForecastData()

    @property
    def forecast_data(self) -> ForecastData:
        return self._last_data

    @property
    def source(self) -> Optional[str]:
        return self._source

    def detect_source(self) -> Optional[str]:
        """Auto-detect available forecast integration."""
        # Check custom entities first
        if self._custom_entities:
            self._entities = self._custom_entities
            self._source = "custom"
            _LOGGER.info("Using custom forecast entities")
            return self._source

        # Check Solcast
        test_entity = SOLCAST_ENTITIES["forecast_today"]
        state = self.hass.states.get(test_entity)
        if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            self._entities = SOLCAST_ENTITIES
            self._source = "solcast"
            _LOGGER.info("Detected Solcast PV Solar integration")
            return self._source

        # Check Forecast.Solar
        test_entity = FORECAST_SOLAR_ENTITIES["forecast_today"]
        state = self.hass.states.get(test_entity)
        if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            self._entities = FORECAST_SOLAR_ENTITIES
            self._source = "forecast_solar"
            _LOGGER.info("Detected Forecast.Solar integration")
            return self._source

        _LOGGER.info("No solar forecast integration detected")
        return None

    def read_forecast(self) -> ForecastData:
        """Read current forecast data from detected source.

        Caches the detected source — only re-detects if source becomes
        unavailable (#26).
        """
        if not self._source:
            self.detect_source()
        elif self._source != "custom":
            # Verify cached source is still valid (entity may have disappeared)
            test_entity = self._entities.get("forecast_today")
            if test_entity:
                state = self.hass.states.get(test_entity)
                if state is None or state.state in (STATE_UNKNOWN, STATE_UNAVAILABLE):
                    self._source = None
                    self.detect_source()

        if not self._source:
            return ForecastData()

        data = ForecastData(
            source=self._source,
            available=True,
            last_update=datetime.now(),
        )

        # Read forecast today
        data.forecast_today_kwh = self._read_float(
            self._entities.get("forecast_today"), 0.0
        )

        # Read forecast tomorrow
        data.forecast_tomorrow_kwh = self._read_float(
            self._entities.get("forecast_tomorrow"), 0.0
        )

        # Read remaining today
        remaining_entity = self._entities.get("forecast_remaining")
        if remaining_entity:
            data.forecast_remaining_today_kwh = self._read_float(remaining_entity, 0.0)
        else:
            # Estimate remaining from today total and current production
            # This is a rough estimate — actual remaining depends on time of day
            data.forecast_remaining_today_kwh = max(
                0, data.forecast_today_kwh * self._remaining_day_fraction()
            )

        # Read power now
        data.power_now_w = self._read_float(
            self._entities.get("power_now"), 0.0
        )
        # Solcast reports in kW, convert if needed
        if self._source == "solcast" and data.power_now_w < 100:
            data.power_now_w *= 1000

        # Read power next hour
        data.power_next_hour_w = self._read_float(
            self._entities.get("power_next_hour"), 0.0
        )
        if self._source == "solcast" and data.power_next_hour_w < 100:
            data.power_next_hour_w *= 1000

        # Peak power
        data.peak_power_today_w = self._read_float(
            self._entities.get("peak_power_today"), 0.0
        )
        if self._source == "solcast" and data.peak_power_today_w < 100:
            data.peak_power_today_w *= 1000

        # Peak time
        peak_time_entity = self._entities.get("peak_time_today")
        if peak_time_entity:
            state = self.hass.states.get(peak_time_entity)
            if state and state.state not in ("unknown", "unavailable"):
                data.peak_time_today = state.state

        self._last_data = data
        return data

    def _read_float(self, entity_id: Optional[str], default: float) -> float:
        """Read a float value from a HA entity."""
        if not entity_id:
            return default
        state = self.hass.states.get(entity_id)
        if state and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE, None):
            try:
                return float(state.state)
            except (ValueError, TypeError):
                pass
        return default

    def _remaining_day_fraction(self) -> float:
        """Estimate fraction of daylight remaining (rough)."""
        now = dt_util.now()
        # Assume daylight 06:00-20:00
        sunrise_hour = 6
        sunset_hour = 20
        total_hours = sunset_hour - sunrise_hour
        current_hour = now.hour + now.minute / 60

        if current_hour <= sunrise_hour:
            return 1.0
        elif current_hour >= sunset_hour:
            return 0.0
        else:
            remaining = sunset_hour - current_hour
            return remaining / total_hours

    def get_charging_recommendation(
        self,
        daily_ev_target_kwh: float,
        current_ev_energy_kwh: float,
    ) -> str:
        """Recommend a charging strategy based on forecast.

        Returns:
            "solar_only" — enough solar expected
            "solar_plus_cheap" — partial solar, fill gap with cheap grid
            "immediate" — insufficient solar, charge now
        """
        remaining_need = daily_ev_target_kwh - current_ev_energy_kwh
        if remaining_need <= 0:
            return "target_reached"

        forecast = self._last_data
        if not forecast.available:
            return "no_forecast"

        # Rough estimate: available surplus = remaining forecast * self-consumption factor
        # Assume ~50% of remaining forecast is available as surplus for EV
        estimated_surplus_kwh = forecast.forecast_remaining_today_kwh * 0.5

        if estimated_surplus_kwh >= remaining_need:
            return "solar_only"
        elif estimated_surplus_kwh >= remaining_need * 0.5:
            return "solar_plus_cheap"
        else:
            return "immediate"
