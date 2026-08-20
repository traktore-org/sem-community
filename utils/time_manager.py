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

        # #424 — telemetry surface mirroring #359/#416/#420/#421/#422/#423
        # classifier_path / dampening_path patterns. Each method sets the
        # corresponding ``*_path`` string so the coordinator can publish
        # them as a diagnostic attribute on the existing night-window /
        # forecast sensors. Without these, a wrong sunrise/sunset →
        # wrong night window → wrong EV / battery charging behavior, but
        # the symptom appears at the actuator with no breadcrumb trail.
        self._last_sunrise_source: str = "uninitialized"
        self._last_sunset_source: str = "uninitialized"
        self._last_sunrise_correction: str = "uninitialized"
        self._last_night_window_path: str = "uninitialized"
        self._last_meter_day_path: str = "uninitialized"
        self._last_night_hours_path: str = "uninitialized"
        self._last_offset_parse_path: str = "uninitialized"

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

        Records the branch on ``self._last_night_window_path`` (#424):
        ``pre_midnight_in_night`` / ``post_midnight_in_night`` /
        ``outside_night_window``.

        Returns:
            True if currently in night mode
        """
        current_time = dt_util.now().strftime("%H:%M")
        night_start, night_end = self.get_night_window()
        if current_time >= night_start:
            self._last_night_window_path = "pre_midnight_in_night"
            return True
        if current_time < night_end:
            # (#811, found live 20.08 06:22) At sunrise, sun.sun rolls
            # ``next_rising`` over to TOMORROW's — 1-2 minutes later on
            # the clock in the shrinking half of the year — and this
            # minute-granular compare would re-enter night for that
            # sliver: day at 06:22, night again seconds later, day at
            # 06:23. The #800 recorder sealed the real night on the
            # phantom re-entry and its morning verdict read a garbage
            # one-minute record. The sun's own state is authoritative
            # for "morning has broken": the ceiling (winter latest_end)
            # may end the night early, but a risen sun always ends it.
            try:
                sun = self.hass.states.get("sun.sun")
                if sun is not None and sun.state == "above_horizon":
                    self._last_night_window_path = (
                        "post_midnight_sun_already_up")
                    return False
            except Exception:  # noqa: BLE001 — veto only, never a crash
                pass
            self._last_night_window_path = "post_midnight_in_night"
            return True
        self._last_night_window_path = "outside_night_window"
        return False

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

        Records branch on ``self._last_night_hours_path`` (#424):
        ``crosses_midnight`` / ``same_day`` / ``parse_failed_fallback_8h``.

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
                self._last_night_hours_path = "crosses_midnight"
            else:
                duration = end_mins - start_mins
                self._last_night_hours_path = "same_day"
            return duration / 60.0
        except (ValueError, AttributeError):
            self._last_night_hours_path = "parse_failed_fallback_8h"
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

        Records the source on ``self._last_sunrise_source`` (#424):
        ``sun_integration`` / ``fallback_default``.

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
                    self._last_sunrise_source = "sun_integration"
                    return dt_util.as_local(next_rising).strftime("%H:%M")
        except Exception as e:
            _LOGGER.debug(f"Could not get sunrise time, using default: {e}")

        # Fallback to default
        self._last_sunrise_source = "fallback_default"
        return "06:00"

    def get_sunset_plus_10_time(self) -> str:
        """Get sunset + 10 minutes time from Home Assistant sun integration.

        Records the source on ``self._last_sunset_source`` (#424):
        ``sun_integration`` / ``fallback_default``.

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
                    self._last_sunset_source = "sun_integration"
                    return sunset_plus_10.strftime("%H:%M")
        except Exception as e:
            _LOGGER.debug(f"Could not get sunset time, using default: {e}")

        # Fallback to default
        self._last_sunset_source = "fallback_default"
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
                        # Same class of bug as #416 forecast_tracker.
                        # Tracking here so we can see how often the
                        # next_rising-is-tomorrow case fires in practice.
                        self._last_sunrise_correction = "next_rising_was_tomorrow"
                    else:
                        self._last_sunrise_correction = "none"

                    return sunrise
        except Exception as e:
            _LOGGER.debug(f"Could not get sunrise datetime, using default: {e}")

        # Fallback: 06:00 today in local time
        self._last_sunrise_correction = "fallback_default_06_00"
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
            self._last_meter_day_path = "before_sunrise"
            return (now.date() - timedelta(days=1))
        else:
            # After sunrise: in today's meter day
            self._last_meter_day_path = "after_sunrise"
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
            self._last_offset_parse_path = "parsed"
            return offset_time
        except (ValueError, AttributeError):
            _LOGGER.warning(f"Invalid offset format '{offset}', using midnight")
            self._last_offset_parse_path = "parse_failed_fallback_midnight"
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
            self._last_meter_day_path = "before_offset"
            return (now.date() - timedelta(days=1))
        else:
            # After offset time: in today's meter day
            self._last_meter_day_path = "after_offset"
            return now.date()

    def get_diagnostics(self) -> dict:
        """Return the audit telemetry surface (#424).

        Used by the coordinator to expose ``*_path`` strings on the
        existing night-window / forecast sensor surfaces. Mirrors the
        ``get_data`` pattern in ``forecast_tracker.py`` from #416.
        """
        return {
            "sunrise_source": self._last_sunrise_source,
            "sunset_source": self._last_sunset_source,
            "sunrise_correction": self._last_sunrise_correction,
            "night_window_path": self._last_night_window_path,
            "meter_day_path": self._last_meter_day_path,
            "night_hours_path": self._last_night_hours_path,
            "offset_parse_path": self._last_offset_parse_path,
        }
