"""Notification module for SEM coordinator.

Handles notifications to KEBA display and mobile devices
based on charging state changes. Covers all charging states:
solar (active, super, min+pv, pause, target), night (active,
waiting for NT window, disabled, target), and legacy states.

Mobile notification cooldown: prevents spamming when the state
machine oscillates (e.g., cloud passing → pause → resume → pause).
Default cooldown is 10 minutes for solar charging states.
"""
import logging
import time
from typing import Dict, Any, Optional

from homeassistant.core import HomeAssistant

from ..const import (
    ChargingState,
    DEFAULT_BATTERY_PRIORITY_SOC,
    DEFAULT_DAILY_EV_TARGET,
)

_LOGGER = logging.getLogger(__name__)

# States that trigger frequent oscillation — apply cooldown to mobile
_COOLDOWN_STATES = {
    ChargingState.SOLAR_CHARGING_ACTIVE,
    ChargingState.SOLAR_SUPER_CHARGING,
    ChargingState.SOLAR_IDLE,
    ChargingState.SOLAR_MIN_PV,
}
_MOBILE_COOLDOWN_SECONDS = 600  # 10 minutes


class NotificationManager:
    """Manages notifications for charging events."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Initialize notification manager."""
        self.hass = hass
        self.config = config
        self._last_notified_state: Optional[str] = None
        self._last_mobile_time: float = -(2 * _MOBILE_COOLDOWN_SECONDS)  # ensure first notification is never suppressed
        self._daily_summary_sent: Optional[str] = None  # date string "YYYY-MM-DD"
        self._notified_flags: set = set()  # tracks one-shot notifications (battery_full, etc.)
        # Flap suppression: require state to be stable before notifying (#35)
        self._pending_state: Optional[str] = None
        self._pending_state_since: float = 0.0
        self._keba_service_checked: bool = False
        self._keba_service_available: bool = True

    async def notify_state_change(
        self,
        new_state: str,
        data: Dict[str, Any]
    ) -> None:
        """Send notifications based on charging state changes.

        Uses flap suppression (#35): for cooldown states (solar charging),
        the state must be stable for 60s before a notification is sent.
        This prevents spam when clouds cause rapid pause/resume cycles.
        """
        # Only notify on actual state changes
        if new_state == self._last_notified_state:
            self._pending_state = None
            return

        # Flap suppression for cooldown states (#35)
        if new_state in _COOLDOWN_STATES:
            now = time.monotonic()
            if self._pending_state != new_state:
                self._pending_state = new_state
                self._pending_state_since = now
                return  # Wait for stability
            if now - self._pending_state_since < 60:
                return  # Not stable yet

        self._pending_state = None
        self._last_notified_state = new_state

        # Check if notifications are enabled (from config, not switches)
        keba_enabled = self.config.get("enable_keba_notifications", True)
        mobile_enabled = self.config.get("enable_mobile_notifications", False)

        if not (keba_enabled or mobile_enabled):
            return

        # Generate messages
        messages = self._get_notification_messages(new_state, data)

        # Send KEBA display notification
        if keba_enabled and messages.get("keba"):
            await self._send_keba_notification(messages["keba"])

        # Send mobile notification (with cooldown for ALL states to prevent spam)
        if mobile_enabled and messages.get("mobile"):
            elapsed = time.monotonic() - self._last_mobile_time
            if elapsed < _MOBILE_COOLDOWN_SECONDS:
                    _LOGGER.debug(
                        "Mobile notification suppressed (cooldown %ds remaining)",
                        int(_MOBILE_COOLDOWN_SECONDS - elapsed),
                    )
                    messages.pop("mobile", None)
        if mobile_enabled and messages.get("mobile"):
            await self._send_mobile_notification(messages["mobile"])

    async def _send_keba_notification(self, message: str) -> None:
        """Send notification to KEBA display."""
        # Validate KEBA service exists (check once, #35)
        if not self._keba_service_checked:
            self._keba_service_checked = True
            self._keba_service_available = self.hass.services.has_service("notify", "keba_display")
            if not self._keba_service_available:
                _LOGGER.info("KEBA display notification service not available — KEBA notifications disabled")

        if not self._keba_service_available:
            return

        try:
            await self.hass.services.async_call(
                "notify",
                "keba_display",
                {
                    "message": message,
                    "data": {
                        "min_time": 3,
                        "max_time": 10,
                    }
                }
            )
            _LOGGER.debug("Sent KEBA notification: %s", message)
        except Exception as e:
            _LOGGER.warning("Failed to send KEBA notification: %s", e)

    async def _send_mobile_notification(self, message: str) -> None:
        """Send mobile notification."""
        mobile_service = self.config.get("mobile_notification_service", "")

        if not mobile_service:
            _LOGGER.debug("No mobile notification service configured")
            return

        # Validate service exists
        if not await self._validate_notification_service(mobile_service):
            _LOGGER.debug(f"Mobile notification service {mobile_service} not available")
            return

        service_name = mobile_service.replace("notify.", "").split(".")[-1]

        try:
            await self.hass.services.async_call(
                "notify",
                service_name,
                {
                    "message": message,
                    "title": "Solar Energy Management",
                }
            )
            self._last_mobile_time = time.monotonic()
            _LOGGER.debug(f"Sent mobile notification: {message}")
        except Exception as e:
            _LOGGER.debug(f"Failed to send mobile notification: {e}")

    async def _validate_notification_service(self, service_name: str) -> bool:
        """Validate that a notification service exists."""
        try:
            service_name = service_name.replace("notify.", "")
            return self.hass.services.has_service("notify", service_name)
        except Exception as e:
            _LOGGER.debug(f"Error validating notification service: {e}")
            return False

    def _get_notification_messages(
        self,
        state: str,
        data: Dict[str, Any]
    ) -> Dict[str, str]:
        """Generate notification messages for different platforms.

        KEBA display: all state changes (short text, charger display).
        Mobile: only important events (start, stop, target reached, errors).
        """
        messages = {}

        # Get data values with defaults
        battery_soc = data.get("battery_soc", 0)
        calculated_current = data.get("calculated_current", 0)
        available_power = data.get("available_power", 0)
        ev_session_energy = data.get("ev_session_energy", 0)
        daily_ev_energy = data.get("daily_ev_energy", 0)
        daily_ev_target = self.config.get("daily_ev_target", DEFAULT_DAILY_EV_TARGET)
        remaining_needed = max(0, daily_ev_target - daily_ev_energy)

        # Solar charging states
        if state == ChargingState.SOLAR_CHARGING_ACTIVE:
            messages["keba"] = f"Solar: {calculated_current}A"
            messages["mobile"] = f"Solar charging started: {calculated_current}A ({available_power:.0f}W)"

        elif state == ChargingState.SOLAR_SUPER_CHARGING:
            messages["keba"] = f"Bat+Sol: {calculated_current}A"
            # No mobile — just a mode switch, not important

        elif state == ChargingState.SOLAR_PAUSE_LOW_BATTERY:
            messages["keba"] = f"Pause: Bat {battery_soc}%"
            # No mobile — transient state

        elif state == ChargingState.SOLAR_TARGET_REACHED:
            messages["keba"] = "Target reached"
            messages["mobile"] = f"Daily target reached: {daily_ev_energy:.1f}/{daily_ev_target}kWh"

        elif state == ChargingState.SOLAR_WAITING_BATTERY_PRIORITY:
            messages["keba"] = f"Wait: Bat {battery_soc}%"
            # No mobile — transient state

        elif state == ChargingState.SOLAR_MIN_PV:
            messages["keba"] = f"Min+PV: {calculated_current}A"
            # No mobile — just a mode switch

        elif state == ChargingState.SOLAR_IDLE:
            if ev_session_energy > 0:
                messages["keba"] = "Session done"
                messages["mobile"] = f"Solar charging stopped: {ev_session_energy:.1f}kWh charged"

        # Night charging states
        elif state == ChargingState.NIGHT_CHARGING_ACTIVE:
            messages["keba"] = f"Night: {remaining_needed:.0f}kWh"
            messages["mobile"] = f"Night charging started: {remaining_needed:.1f}kWh remaining"

        elif state == ChargingState.NIGHT_TARGET_REACHED:
            messages["keba"] = "Night: Done"
            messages["mobile"] = f"Night charging complete: {daily_ev_energy:.1f}/{daily_ev_target}kWh"

        elif state == ChargingState.NIGHT_DISABLED:
            messages["keba"] = "Night: Off"
            # No mobile — user turned it off themselves

        elif state == ChargingState.NIGHT_IDLE:
            messages["keba"] = "Night: No EV"
            # No mobile — just waiting for plug

        # Legacy states
        elif state == ChargingState.TARGET_REACHED:
            messages["keba"] = "Target done"
            messages["mobile"] = f"Daily target reached: {daily_ev_energy:.1f}kWh"

        elif state == ChargingState.IDLE:
            if ev_session_energy > 0:
                messages["keba"] = "Complete"

        return messages

    async def notify_battery_full(self, soc: float) -> None:
        """Send notification when battery reaches 100%. Sent once until battery drops below 95%."""
        if soc < 95:
            self._notified_flags.discard("battery_full")
            return
        if not self.config.get("enable_mobile_notifications", False):
            return
        if "battery_full" in self._notified_flags:
            return
        self._notified_flags.add("battery_full")
        await self._send_mobile_notification(
            f"Battery full ({soc:.0f}%) — surplus power now available for appliances or export."
        )

    async def notify_high_grid_import(self, power_w: float, peak_pct: float) -> None:
        """Send notification when grid import exceeds threshold. Clears when below 70%."""
        if peak_pct < 70:
            self._notified_flags.discard("high_grid_import")
            return
        if not self.config.get("enable_mobile_notifications", False):
            return
        if "high_grid_import" in self._notified_flags:
            return
        self._notified_flags.add("high_grid_import")
        await self._send_mobile_notification(
            f"High grid import: {power_w:.0f}W ({peak_pct:.0f}% of peak limit). "
            f"Consider reducing load to avoid demand charges."
        )

    async def notify_daily_summary(self, data: Dict[str, Any]) -> None:
        """Send evening daily summary notification (once per day)."""
        if not self.config.get("enable_mobile_notifications", False):
            return
        from homeassistant.util import dt as dt_util
        today = dt_util.now().strftime("%Y-%m-%d")
        if self._daily_summary_sent == today:
            return
        self._daily_summary_sent = today
        solar = data.get("daily_solar", 0)
        home = data.get("daily_home", 0)
        autarky = data.get("autarky_rate", 0)
        savings = data.get("daily_savings", 0)
        ev = data.get("daily_ev", 0)
        net_cost = data.get("daily_net_cost", 0)
        tomorrow = data.get("forecast_tomorrow", 0)

        msg = (
            f"Today: {solar:.1f} kWh solar · {autarky:.0f}% autarky · "
            f"Saved {savings:.2f} CHF · Net cost {net_cost:.2f} CHF"
        )
        if ev > 0:
            msg += f" · EV {ev:.1f} kWh"
        if tomorrow > 0:
            msg += f"\nTomorrow: {tomorrow:.1f} kWh forecast"

        await self._send_mobile_notification(msg)

    async def notify_forecast_alert(self, tomorrow_kwh: float) -> None:
        """Send alert for unusually low solar forecast. Clears when forecast > 10 kWh."""
        if tomorrow_kwh > 10:
            self._notified_flags.discard("forecast_low")
            return
        if not self.config.get("enable_mobile_notifications", False):
            return
        if "forecast_low" in self._notified_flags:
            return
        self._notified_flags.add("forecast_low")
        await self._send_mobile_notification(
            f"Low solar forecast tomorrow: {tomorrow_kwh:.1f} kWh. "
            f"Consider charging EV tonight and deferring export."
        )

    def reset(self) -> None:
        """Reset notification state."""
        self._last_notified_state = None
        self._notified_flags.clear()
