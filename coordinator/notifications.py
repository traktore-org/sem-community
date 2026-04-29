"""Notification module for SEM coordinator.

Handles notifications to KEBA display and mobile devices
based on charging state changes. Covers all charging states:
solar (active, super, min+pv, pause, target), night (active,
waiting for NT window, disabled, target), and legacy states.

Features (#47):
- Flap suppression: 60s stability for solar cooldown states (#35)
- Mobile cooldown: 10-minute minimum between mobile notifications
- Service validation: cached (check once per session)
- Android notification channels: group by category (charging, alerts, summary)
- Actionable notifications: buttons for dashboard navigation
- HA events: fires sem_notification for automation triggers
"""
import logging
import time
from typing import Dict, Any, Optional

from homeassistant.core import HomeAssistant

from ..const import (
    DOMAIN,
    ChargingState,
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
_FLAP_STABILITY_SECONDS = 60  # state must be stable this long before notifying

# Notification channels for Android companion app
_CHANNEL_CHARGING = "sem_charging"
_CHANNEL_ALERTS = "sem_alerts"
_CHANNEL_SUMMARY = "sem_summary"


class NotificationManager:
    """Manages notifications for charging events."""

    def __init__(self, hass: HomeAssistant, config: Dict[str, Any]):
        """Initialize notification manager."""
        self.hass = hass
        self.config = config
        self._last_notified_state: Optional[str] = None
        self._last_mobile_time: float = -(2 * _MOBILE_COOLDOWN_SECONDS)
        self._daily_summary_sent: Optional[str] = None
        self._notified_flags: set = set()
        # Flap suppression (#35)
        self._pending_state: Optional[str] = None
        self._pending_state_since: float = 0.0
        # Service validation caching (#47)
        self._charger_notify_checked: bool = False
        self._charger_notify_available: bool = True
        self._charger_notify_service: str = ""
        self._mobile_service_checked: bool = False
        self._mobile_service_available: bool = True
        self._mobile_service_name: str = ""
        self._mobile_service_domain: str = "notify"
        self._mobile_service_is_companion: bool = False

    async def notify_state_change(
        self,
        new_state: str,
        data: Dict[str, Any]
    ) -> None:
        """Send notifications based on charging state changes.

        Uses flap suppression (#35): for cooldown states (solar charging),
        the state must be stable for 60s before a notification is sent.
        """
        if new_state == self._last_notified_state:
            self._pending_state = None
            return

        # Flap suppression for cooldown states
        if new_state in _COOLDOWN_STATES:
            now = time.monotonic()
            if self._pending_state != new_state:
                self._pending_state = new_state
                self._pending_state_since = now
                return
            if now - self._pending_state_since < _FLAP_STABILITY_SECONDS:
                return

        self._pending_state = None
        self._last_notified_state = new_state

        # Backward compat: accept both enable_keba_notifications and enable_charger_notifications (#85)
        keba_enabled = self.config.get("enable_charger_notifications",
                                       self.config.get("enable_keba_notifications", True))
        mobile_enabled = self.config.get("enable_mobile_notifications", False)

        if not (keba_enabled or mobile_enabled):
            return

        messages = self._get_notification_messages(new_state, data)

        # Fire HA event for automation triggers (#47)
        if messages.get("mobile") or messages.get("keba"):
            self.hass.bus.async_fire(f"{DOMAIN}_notification", {
                "state": new_state,
                "message": messages.get("mobile") or messages.get("keba", ""),
                "category": "charging",
            })

        if keba_enabled and messages.get("keba"):
            await self._send_charger_notification(messages["keba"])

        if mobile_enabled and messages.get("mobile"):
            elapsed = time.monotonic() - self._last_mobile_time
            if elapsed < _MOBILE_COOLDOWN_SECONDS:
                _LOGGER.debug(
                    "Mobile notification suppressed (cooldown %ds remaining)",
                    int(_MOBILE_COOLDOWN_SECONDS - elapsed),
                )
            else:
                await self._send_mobile_notification(
                    messages["mobile"],
                    channel=_CHANNEL_CHARGING,
                    group="sem_charging",
                )

    async def _send_charger_notification(self, message: str) -> None:
        """Send notification to EV charger display (#85).

        Supports KEBA (notify service with min/max_time), and any other
        charger that exposes a notify.* service. Falls back gracefully
        if no charger notification service is available.
        """
        if not self._charger_notify_checked:
            self._charger_notify_checked = True
            # Try configured service, then KEBA default
            service = (self.config.get("charger_notification_service")
                       or self.config.get("keba_notification_service")
                       or "keba_display")
            self._charger_notify_service = service
            self._charger_notify_available = self.hass.services.has_service("notify", service)
            if not self._charger_notify_available:
                _LOGGER.info("Charger notification service 'notify.%s' not available", service)

        if not self._charger_notify_available:
            return

        try:
            service_data: dict = {"message": message}
            # KEBA-specific: display timing parameters
            if "keba" in self._charger_notify_service:
                service_data["data"] = {"min_time": 3, "max_time": 10}

            await self.hass.services.async_call(
                "notify", self._charger_notify_service, service_data,
            )
            _LOGGER.debug("Sent charger notification: %s", message)
        except Exception as e:
            _LOGGER.warning("Failed to send charger notification: %s", e)

    async def _send_mobile_notification(
        self,
        message: str,
        channel: str = _CHANNEL_CHARGING,
        group: str = "sem",
        actions: Optional[list] = None,
    ) -> None:
        """Send mobile notification with channel and optional action buttons (#47).

        Supports three service types:
        - notify.mobile_app_* — Android/iOS companion app (full data payload)
        - notify.* (other)     — REST/generic notify (message + title only)
        - rest_command.*       — direct REST command (message + title only)
        """
        mobile_service = self.config.get("mobile_notification_service", "")
        if not mobile_service:
            return

        # Cache service validation and type detection (#47)
        if not self._mobile_service_checked:
            self._mobile_service_checked = True
            service_name = mobile_service.replace("notify.", "").split(".")[-1]
            self._mobile_service_name = service_name

            # Detect service type: rest_command.* vs notify.*
            if self.hass.services.has_service("rest_command", service_name):
                self._mobile_service_domain = "rest_command"
                self._mobile_service_available = True
                self._mobile_service_is_companion = False
            elif self.hass.services.has_service("notify", service_name):
                self._mobile_service_domain = "notify"
                self._mobile_service_available = True
                # Only mobile_app_* services support Android notification channels
                self._mobile_service_is_companion = service_name.startswith("mobile_app_")
            else:
                self._mobile_service_domain = "notify"
                self._mobile_service_available = False
                self._mobile_service_is_companion = False
                _LOGGER.info("Notification service '%s' not available", mobile_service)

        if not self._mobile_service_available:
            return

        service_call: Dict[str, Any] = {
            "message": message,
            "title": "Solar Energy Management",
        }

        # Add Android companion app data for mobile_app_* services
        if self._mobile_service_is_companion:
            notification_data: Dict[str, Any] = {
                "group": group,
                "channel": channel,
                "importance": "default",
            }
            if actions:
                notification_data["actions"] = actions
            service_call["data"] = notification_data

        # Add routing fields for rest_command webhook relays
        if self._mobile_service_domain == "rest_command":
            service_call["type"] = "sem"
            service_call["severity"] = "info"

        try:
            await self.hass.services.async_call(
                self._mobile_service_domain,
                self._mobile_service_name,
                service_call,
            )
            self._last_mobile_time = time.monotonic()
            _LOGGER.debug("Sent notification via %s.%s: %s",
                          self._mobile_service_domain, self._mobile_service_name, message)
        except Exception as e:
            _LOGGER.debug("Failed to send notification: %s", e)

    def _get_notification_messages(
        self,
        state: str,
        data: Dict[str, Any]
    ) -> Dict[str, str]:
        """Generate notification messages for different platforms."""
        messages = {}

        battery_soc = data.get("battery_soc", 0)
        calculated_current = data.get("calculated_current", 0)
        available_power = data.get("available_power", 0)
        ev_session_energy = data.get("ev_session_energy", 0)
        daily_ev_energy = data.get("daily_ev_energy", 0)
        daily_ev_target = self.config.get("daily_ev_target", DEFAULT_DAILY_EV_TARGET)
        remaining_needed = max(0, daily_ev_target - daily_ev_energy)

        from ..utils.translate import get_text
        _t = lambda key, default, **kw: get_text(self.hass, key, default, **kw)

        if state == ChargingState.SOLAR_CHARGING_ACTIVE:
            messages["keba"] = f"Solar: {calculated_current}A"
            messages["mobile"] = _t("notif_solar_started",
                "Solar charging started: {current}A ({power:.0f}W)",
                current=calculated_current, power=available_power)

        elif state == ChargingState.SOLAR_SUPER_CHARGING:
            messages["keba"] = f"Bat+Sol: {calculated_current}A"

        elif state == ChargingState.SOLAR_PAUSE_LOW_BATTERY:
            messages["keba"] = f"Pause: Bat {battery_soc}%"

        elif state == ChargingState.SOLAR_TARGET_REACHED:
            messages["keba"] = "Target reached"
            messages["mobile"] = _t("notif_target_reached",
                "Daily target reached: {charged:.1f}/{target}kWh",
                charged=daily_ev_energy, target=daily_ev_target)

        elif state == ChargingState.SOLAR_WAITING_BATTERY_PRIORITY:
            messages["keba"] = f"Wait: Bat {battery_soc}%"

        elif state == ChargingState.SOLAR_MIN_PV:
            messages["keba"] = f"Min+PV: {calculated_current}A"

        elif state == ChargingState.SOLAR_IDLE:
            if ev_session_energy > 0:
                messages["keba"] = "Session done"
                messages["mobile"] = _t("notif_solar_stopped",
                    "Solar charging stopped: {energy:.1f}kWh charged",
                    energy=ev_session_energy)

        elif state == ChargingState.NIGHT_CHARGING_ACTIVE:
            messages["keba"] = f"Night: {remaining_needed:.0f}kWh"
            messages["mobile"] = _t("notif_night_started",
                "Night charging started: {remaining:.1f}kWh remaining",
                remaining=remaining_needed)

        elif state == ChargingState.NIGHT_TARGET_REACHED:
            messages["keba"] = "Night: Done"
            messages["mobile"] = _t("notif_night_complete",
                "Night charging complete: {charged:.1f}/{target}kWh",
                charged=daily_ev_energy, target=daily_ev_target)

        elif state == ChargingState.NIGHT_DISABLED:
            messages["keba"] = "Night: Off"

        elif state == ChargingState.NIGHT_IDLE:
            messages["keba"] = "Night: No EV"

        elif state == ChargingState.TARGET_REACHED:
            messages["keba"] = "Target done"
            messages["mobile"] = _t("notif_target_reached",
                "Daily target reached: {charged:.1f}/{target}kWh",
                charged=daily_ev_energy, target=daily_ev_target)

        elif state == ChargingState.IDLE:
            if ev_session_energy > 0:
                messages["keba"] = "Complete"

        return messages

    async def notify_battery_full(self, soc: float) -> None:
        """Send notification when battery reaches 100%."""
        if soc < 95:
            self._notified_flags.discard("battery_full")
            return
        if not self.config.get("enable_mobile_notifications", False):
            return
        if "battery_full" in self._notified_flags:
            return
        self._notified_flags.add("battery_full")

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "alerts",
            "event": "battery_full",
            "battery_soc": soc,
        })

        from ..utils.translate import get_text
        await self._send_mobile_notification(
            get_text(self.hass, "notif_battery_full",
                "Battery full ({soc:.0f}%) — surplus available for appliances or export.",
                soc=soc),
            channel=_CHANNEL_ALERTS,
            group="sem_alerts",
            actions=[{"action": "URI", "title": "Open Dashboard", "uri": "/sem-dashboard/overview"}],
        )

    async def notify_high_grid_import(self, power_w: float, peak_pct: float) -> None:
        """Send notification when grid import exceeds threshold."""
        if peak_pct < 70:
            self._notified_flags.discard("high_grid_import")
            return
        if not self.config.get("enable_mobile_notifications", False):
            return
        if "high_grid_import" in self._notified_flags:
            return
        self._notified_flags.add("high_grid_import")

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "alerts",
            "event": "high_grid_import",
            "power_w": power_w,
            "peak_pct": peak_pct,
        })

        from ..utils.translate import get_text
        await self._send_mobile_notification(
            get_text(self.hass, "notif_high_grid_import",
                "High grid import: {power_w:.0f}W ({peak_pct:.0f}% of peak limit). Consider reducing loads.",
                power_w=power_w, peak_pct=peak_pct),
            channel=_CHANNEL_ALERTS,
            group="sem_alerts",
            actions=[{"action": "URI", "title": "Open Dashboard", "uri": "/sem-dashboard/overview"}],
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

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "summary",
            "event": "daily_summary",
            "daily_solar": solar,
            "autarky_rate": autarky,
            "daily_savings": savings,
            "forecast_tomorrow": tomorrow,
        })

        await self._send_mobile_notification(
            msg,
            channel=_CHANNEL_SUMMARY,
            group="sem_summary",
        )

    async def notify_forecast_alert(self, tomorrow_kwh: float) -> None:
        """Send alert for unusually low solar forecast."""
        if tomorrow_kwh > 10:
            self._notified_flags.discard("forecast_low")
            return
        if not self.config.get("enable_mobile_notifications", False):
            return
        if "forecast_low" in self._notified_flags:
            return
        self._notified_flags.add("forecast_low")

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "alerts",
            "event": "forecast_low",
            "forecast_tomorrow_kwh": tomorrow_kwh,
        })

        from ..utils.translate import get_text
        await self._send_mobile_notification(
            get_text(self.hass, "notif_low_forecast",
                "Low solar forecast tomorrow: {tomorrow_kwh:.1f} kWh. Consider charging EV tonight.",
                tomorrow_kwh=tomorrow_kwh),
            channel=_CHANNEL_ALERTS,
            group="sem_alerts",
        )

    async def notify_ev_nearly_full(self, minutes_remaining: float) -> None:
        """Notify user that EV is nearly full based on taper detection (#106)."""
        if minutes_remaining > 10:
            self._notified_flags.discard("ev_nearly_full")
            return
        if "ev_nearly_full" in self._notified_flags:
            return
        self._notified_flags.add("ev_nearly_full")

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "charging",
            "event": "ev_nearly_full",
            "minutes_remaining": round(minutes_remaining, 0),
        })
        await self._send_mobile_notification(
            f"EV nearly full — ~{minutes_remaining:.0f} min remaining",
            channel=_CHANNEL_CHARGING,
            group="sem_charging",
        )

    async def notify_ev_charge_skip(
        self, estimated_soc: float, nights: int,
    ) -> None:
        """Notify user that night charge was skipped (#106)."""
        if "ev_charge_skip" in self._notified_flags:
            return
        self._notified_flags.add("ev_charge_skip")

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "charging",
            "event": "ev_charge_skip",
            "estimated_soc": round(estimated_soc, 0),
            "nights_remaining": nights,
        })
        await self._send_mobile_notification(
            f"Night charge skipped — EV SOC {estimated_soc:.0f}%, "
            f"{nights} night(s) range remaining",
            channel=_CHANNEL_CHARGING,
            group="sem_charging",
        )

    async def notify_ev_charge_recommended(self, estimated_soc: float) -> None:
        """Notify user that EV charging is recommended (#106)."""
        if "ev_charge_recommended" in self._notified_flags:
            return
        self._notified_flags.add("ev_charge_recommended")

        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "charging",
            "event": "ev_charge_recommended",
            "estimated_soc": round(estimated_soc, 0),
        })
        await self._send_mobile_notification(
            f"EV charge recommended tonight — estimated SOC {estimated_soc:.0f}%",
            channel=_CHANNEL_CHARGING,
            group="sem_charging",
        )

    def reset(self) -> None:
        """Reset notification state."""
        self._last_notified_state = None
        self._notified_flags.clear()
