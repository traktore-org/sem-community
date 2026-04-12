"""Time management utilities for Solar Energy Management.

This module handles all time-related calculations including sunrise/sunset,
night mode detection, night end time, and meter day calculations.

Key methods:
- is_night_mode(): sunset+10 (or 20:30) until sunrise (or 07:00)
- get_night_end_time(): min(sunrise, 07:00) — used by latest-start planning
- get_current_meter_day_sunrise_based(): daily bucket boundary for energy tracking
"""
import logging
from datetime import datetime, timedelta, date
from typing import TYPE_CHECKING

from homeassistant.util import dt as dt_util

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


class TimeManager:
    """Manages time-related calculations for solar energy management.

    Handles:
    - Sunrise/sunset times from Home Assistant sun integration
    - Night mode detection (sunset-based with configurable floor/ceiling)
    - Night window duration and sufficiency checks
    - Sunrise-based meter day calculations for daily energy tracking
    """

    def __init__(self, hass: "HomeAssistant", config: dict = None):
        """Initialize time manager.

        Args:
            hass: Home Assistant instance
            config: SEM config dict (for night window bounds)
        """
        self.hass = hass
        self._config = config or {}

    def _get_night_earliest_start(self) -> str:
        """Get the floor for night start as HH:MM.

        Reads from config `night_earliest_start` (float hours, e.g., 20.5 = 20:30).
        Default: 20:30.
        """
        from ..consts.core import DEFAULT_NIGHT_EARLIEST_START
        hours = self._config.get("night_earliest_start", DEFAULT_NIGHT_EARLIEST_START)
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h:02d}:{m:02d}"

    def _get_night_latest_end(self) -> str:
        """Get the ceiling for night end as HH:MM.

        Reads from config `night_latest_end` (float hours, e.g., 7.0 = 07:00).
        Default: 07:00.
        """
        from ..consts.core import DEFAULT_NIGHT_LATEST_END
        hours = self._config.get("night_latest_end", DEFAULT_NIGHT_LATEST_END)
        h = int(hours)
        m = int((hours - h) * 60)
        return f"{h:02d}:{m:02d}"

    def is_night_mode(self) -> bool:
        """Determine if we're in night mode based on sunrise/sunset.

        Night mode is defined as:
        - From max(sunset+10, earliest_start) until min(sunrise, latest_end)

        The earliest_start floor (default 20:30) prevents night mode during
        daytime. The latest_end ceiling (default 07:00) stops night charging
        even if sunrise is later in winter.

        Returns:
            True if currently in night mode
        """
        current_time = dt_util.now().strftime("%H:%M")
        night_start, night_end = self.get_night_window()
        return current_time >= night_start or current_time < night_end

    def get_night_window(self) -> tuple:
        """Get the computed night window (start, end) as HH:MM strings.

        Returns:
            (night_start, night_end) tuple of HH:MM strings
        """
        sunrise = self.get_sunrise_time()
        sunset_plus_10 = self.get_sunset_plus_10_time()
        earliest_start = self._get_night_earliest_start()
        latest_end = self._get_night_latest_end()

        night_start = max(sunset_plus_10, earliest_start)
        night_end = min(sunrise, latest_end)
        return night_start, night_end

    def get_night_window_hours(self) -> float:
        """Get the available night charging hours.

        Accounts for midnight crossing (e.g., 21:00 to 06:00 = 9 hours).

        Returns:
            Available hours as float (e.g., 9.5)
        """
        night_start, night_end = self.get_night_window()
        try:
            sh, sm = night_start.split(":")
            eh, em = night_end.split(":")
            start_mins = int(sh) * 60 + int(sm)
            end_mins = int(eh) * 60 + int(em)
            if end_mins <= start_mins:
                # Crosses midnight
                duration = (24 * 60 - start_mins) + end_mins
            else:
                duration = end_mins - start_mins
            return duration / 60.0
        except (ValueError, AttributeError):
            return 8.0  # Safe fallback

    def get_night_end_time(self) -> str:
        """Get when night mode ends: min(sunrise, latest_end).

        Returns:
            Night end time in HH:MM format (e.g., "06:30" or "07:00").
        """
        _, night_end = self.get_night_window()
        return night_end

    def get_sunrise_time(self) -> str:
        """Get sunrise time from Home Assistant sun integration.

        Returns:
            Sunrise time in HH:MM format (local time), or "06:00" as fallback
        """
        try:
            sun_state = self.hass.states.get("sun.sun")
            if sun_state and sun_state.attributes:
                next_rising = sun_state.attributes.get("next_rising")
                if next_rising:
                    # Handle both datetime and string formats
                    if isinstance(next_rising, str):
                        # Parse ISO format string to datetime
                        next_rising = datetime.fromisoformat(next_rising.replace('Z', '+00:00'))
                    # Convert to local time string
                    return dt_util.as_local(next_rising).strftime("%H:%M")
        except Exception as e:
            _LOGGER.debug(f"Could not get sunrise time, using default: {e}")

        # Fallback to default
        return "06:00"

    def get_sunset_plus_10_time(self) -> str:
        """Get sunset + 10 minutes time from Home Assistant sun integration.

        Returns:
            Sunset+10 time in HH:MM format (local time), or "20:30" as fallback
        """
        try:
            sun_state = self.hass.states.get("sun.sun")
            if sun_state and sun_state.attributes:
                next_setting = sun_state.attributes.get("next_setting")
                if next_setting:
                    # Handle both datetime and string formats
                    if isinstance(next_setting, str):
                        # Parse ISO format string to datetime
                        next_setting = datetime.fromisoformat(next_setting.replace('Z', '+00:00'))
                    # Add 10 minutes and convert to local time string
                    sunset_plus_10 = dt_util.as_local(next_setting) + timedelta(minutes=10)
                    return sunset_plus_10.strftime("%H:%M")
        except Exception as e:
            _LOGGER.debug(f"Could not get sunset time, using default: {e}")

        # Fallback to default
        return "20:30"

    def get_sunrise_datetime(self) -> datetime:
        """Get today's sunrise as a datetime object (local time).

        Returns:
            Sunrise datetime in local timezone, or 06:00 today as fallback
        """
        try:
            sun_state = self.hass.states.get("sun.sun")
            if sun_state and sun_state.attributes:
                next_rising = sun_state.attributes.get("next_rising")
                if next_rising:
                    # Handle both datetime and string formats
                    if isinstance(next_rising, str):
                        # Parse ISO format string to datetime
                        next_rising = datetime.fromisoformat(next_rising.replace('Z', '+00:00'))
                    # Convert to local time
                    sunrise = dt_util.as_local(next_rising)

                    # BUG FIX: next_rising can be tomorrow's sunrise if called after today's sunrise
                    # If sunrise is tomorrow, subtract 24 hours to get today's sunrise
                    now = dt_util.now()
                    if sunrise.date() > now.date():
                        sunrise = sunrise - timedelta(days=1)

                    return sunrise
        except Exception as e:
            _LOGGER.debug(f"Could not get sunrise datetime, using default: {e}")

        # Fallback: 06:00 today in local time
        now = dt_util.now()
        return now.replace(hour=6, minute=0, second=0, microsecond=0)

    def get_current_meter_day_sunrise_based(self) -> date:
        """Determine which 'meter day' we're in based on last sunrise.

        This enables daily energy tracking that resets at sunrise instead of a fixed time.
        - Before sunrise: still in yesterday's meter day
        - After sunrise: in today's meter day

        Returns:
            Date representing the current meter day

        Example:
            >>> # At 05:30 (before sunrise at 06:15):
            >>> time_manager.get_current_meter_day_sunrise_based()
            date(2024, 11, 17)  # Yesterday's date

            >>> # At 07:00 (after sunrise at 06:15):
            >>> time_manager.get_current_meter_day_sunrise_based()
            date(2024, 11, 18)  # Today's date
        """
        now = dt_util.now()
        sunrise_today = self.get_sunrise_datetime()

        if now < sunrise_today:
            # Before sunrise: still in yesterday's meter day
            return (now.date() - timedelta(days=1))
        else:
            # After sunrise: in today's meter day
            return now.date()

    def get_offset_time(self, offset: str = "00:00") -> datetime:
        """Get today's reset time based on offset.

        Args:
            offset: Time offset in HH:MM format (default: "00:00" for midnight)

        Returns:
            Datetime for today's reset time

        Example:
            >>> time_manager.get_offset_time("06:30")
            datetime(2024, 11, 18, 6, 30, 0)  # Today at 06:30
        """
        now = dt_util.now()

        try:
            hour, minute = offset.split(":")
            offset_time = now.replace(
                hour=int(hour),
                minute=int(minute),
                second=0,
                microsecond=0
            )
            return offset_time
        except (ValueError, AttributeError):
            _LOGGER.warning(f"Invalid offset format '{offset}', using midnight")
            return now.replace(hour=0, minute=0, second=0, microsecond=0)

    def get_current_meter_day_offset_based(self, offset: str = "00:00") -> date:
        """Determine which 'meter day' we're in based on a time offset.

        Args:
            offset: Time offset in HH:MM format for day reset

        Returns:
            Date representing the current meter day

        Example:
            >>> # At 05:30 with offset "06:00":
            >>> time_manager.get_current_meter_day_offset_based("06:00")
            date(2024, 11, 17)  # Yesterday (before 06:00 reset)

            >>> # At 07:00 with offset "06:00":
            >>> time_manager.get_current_meter_day_offset_based("06:00")
            date(2024, 11, 18)  # Today (after 06:00 reset)
        """
        now = dt_util.now()
        offset_time = self.get_offset_time(offset)

        if now < offset_time:
            # Before offset time: still in yesterday's meter day
            return (now.date() - timedelta(days=1))
        else:
            # After offset time: in today's meter day
            return now.date()
