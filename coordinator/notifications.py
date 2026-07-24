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
from __future__ import annotations

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
        # v1.6.9: per-charger flap suppression. The fleet sentinel
        # ``"_fleet"`` is the back-compat slot for callers that don't
        # pass a ``charger_id`` (single-charger setups + the existing
        # global state-change call site at coordinator.py:2148).
        # Multi-charger callers pass each charger's id so a state
        # change on charger A doesn't suppress one on charger B
        # (separate ``_last_notified_state`` per key).
        #
        # Internal dicts are private. The ``_last_notified_state``,
        # ``_pending_state``, and ``_pending_state_since`` properties
        # below provide the legacy scalar API (targeting the fleet
        # slot) so existing tests and any external consumers continue
        # to work unchanged.
        self._last_notified_state_per_charger: Dict[str, Optional[str]] = {}
        self._pending_state_per_charger: Dict[str, Optional[str]] = {}
        self._pending_state_since_per_charger: Dict[str, float] = {}
        self._last_mobile_time: float = -(2 * _MOBILE_COOLDOWN_SECONDS)
        self._daily_summary_sent: Optional[str] = None
        self._notified_flags: set = set()
        # Service validation caching (#47)
        self._charger_notify_checked: bool = False
        self._charger_notify_available: bool = True
        self._charger_notify_service: str = ""
        self._mobile_service_checked: bool = False
        self._mobile_service_available: bool = True
        self._mobile_service_name: str = ""
        self._mobile_service_domain: str = "notify"
        self._mobile_service_is_companion: bool = False

    # ──────────────────────────────────────────────────────────────────
    # v1.6.8-compat shims for flap-suppression fields. Reads/writes
    # target the fleet sentinel key; multi-charger callers should use
    # the per-charger dicts directly.
    # ──────────────────────────────────────────────────────────────────

    @property
    def _last_notified_state(self) -> Optional[str]:
        return self._last_notified_state_per_charger.get("_fleet")

    @_last_notified_state.setter
    def _last_notified_state(self, value: Optional[str]) -> None:
        if value is None:
            self._last_notified_state_per_charger.pop("_fleet", None)
        else:
            self._last_notified_state_per_charger["_fleet"] = value

    @property
    def _pending_state(self) -> Optional[str]:
        return self._pending_state_per_charger.get("_fleet")

    @_pending_state.setter
    def _pending_state(self, value: Optional[str]) -> None:
        if value is None:
            self._pending_state_per_charger.pop("_fleet", None)
        else:
            self._pending_state_per_charger["_fleet"] = value

    @property
    def _pending_state_since(self) -> float:
        return self._pending_state_since_per_charger.get("_fleet", 0.0)

    @_pending_state_since.setter
    def _pending_state_since(self, value: float) -> None:
        self._pending_state_since_per_charger["_fleet"] = value

    async def notify_state_change(
        self,
        new_state: str,
        data: Dict[str, Any],
        *,
        charger_id: Optional[str] = None,
        charger_name: Optional[str] = None,
    ) -> None:
        """Send notifications based on charging state changes.

        Uses flap suppression (#35): for cooldown states (solar charging),
        the state must be stable for 60s before a notification is sent.

        v1.6.9 multi-charger: ``charger_id`` (when set) keys the flap
        suppression state per-charger so a state change on one charger
        doesn't suppress one on another. ``charger_name`` is used as the
        label in mobile notifications (e.g. ``[Wallbox Left] Solar
        charging active``). Single-charger callers omit both and the
        fleet sentinel key is used — identical behaviour to v1.6.8.
        """
        key = charger_id or "_fleet"

        if new_state == self._last_notified_state_per_charger.get(key):
            # Drop the pending-state entry rather than writing ``None`` —
            # keeps the dict free of orphan ``None`` slots so future
            # ``in`` checks are meaningful (reviewer NIT, v1.6.9).
            self._pending_state_per_charger.pop(key, None)
            return

        # Flap suppression for cooldown states
        if new_state in _COOLDOWN_STATES:
            now = time.monotonic()
            if self._pending_state_per_charger.get(key) != new_state:
                self._pending_state_per_charger[key] = new_state
                self._pending_state_since_per_charger[key] = now
                return
            if now - self._pending_state_since_per_charger.get(key, 0.0) < _FLAP_STABILITY_SECONDS:
                return

        # Same drop-not-write convention as above.
        self._pending_state_per_charger.pop(key, None)
        self._last_notified_state_per_charger[key] = new_state

        # Accept enable_charger_notifications (new) or enable_keba_notifications (legacy)
        keba_enabled = self.config.get("enable_charger_notifications",
                                       self.config.get("enable_keba_notifications", True))
        mobile_enabled = self.config.get("enable_mobile_notifications", False)

        if not (keba_enabled or mobile_enabled):
            return

        messages = self._get_notification_messages(
            new_state, {**data, "_charger_id": charger_id})

        # v1.6.9 multi-charger: prefix mobile messages with the charger
        # name in square brackets so the user knows which charger fired
        # the event. The charger-display message stays bare — the
        # charger already knows it's itself.
        #
        # Note: ``_last_mobile_time`` stays fleet-wide (not per-charger)
        # by design. Users want a quiet phone, not one push per charger
        # per state change. The KEBA notification IS per-charger though
        # — that one fires for every state change on every charger.
        if charger_name and messages.get("mobile"):
            messages["mobile"] = f"[{charger_name}] {messages['mobile']}"

        # Fire HA event for automation triggers (#47)
        if messages.get("mobile") or messages.get("charger"):
            self.hass.bus.async_fire(f"{DOMAIN}_notification", {
                "state": new_state,
                "message": messages.get("mobile") or messages.get("keba", ""),
                "category": "charging",
                "charger_id": charger_id,
                "charger_name": charger_name,
            })

        if keba_enabled and messages.get("charger"):
            await self._send_charger_notification(messages["charger"])

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
        """Send notification to EV charger display.

        Supports any charger that exposes a notify.* service (KEBA, Easee,
        Wallbox, etc.). Auto-detects available charger notification services.
        Falls back gracefully if none available.
        """
        if not self._charger_notify_checked:
            self._charger_notify_checked = True
            # Try configured service, then auto-detect from available notify services
            # charger_notification_service and keba_notification_service were never set via UI
            service = self._auto_detect_charger_notify_service()
            self._charger_notify_service = service
            self._charger_notify_available = bool(service) and self.hass.services.has_service("notify", service)
            if not self._charger_notify_available:
                _LOGGER.info("No charger notification service available")
            else:
                _LOGGER.info("Using charger notification service: notify.%s", service)

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

    def _auto_detect_charger_notify_service(self) -> str:
        """Auto-detect charger notification service from available notify services.

        Checks for known charger display services: KEBA, Easee, Wallbox, etc.
        Returns the first match or empty string if none found.
        """
        charger_patterns = [
            "keba_display", "keba",
            "easee", "wallbox", "goecharger", "go_echarger",
            "ocpp", "openevse", "zaptec",
        ]
        try:
            services = self.hass.services.async_services().get("notify", {})
            for pattern in charger_patterns:
                for service_name in services:
                    if pattern in service_name.lower():
                        return service_name
        except Exception:
            pass
        return ""

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

        from ..utils.translate import get_text
        service_call: Dict[str, Any] = {
            "message": message,
            "title": get_text(self.hass, "notif_title", "Solar Energy Management"),
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
        # (#631) Prefer the live per-charger night-target map — the SAME value
        # the night decision consumed — over the config snapshot, which goes
        # stale the moment the user edits the target entity (live: notification
        # said 8.0 kWh while the decision correctly charged 2.0).
        night_map = data.get("night_remaining_map") or {}
        _cid = data.get("_charger_id")
        if _cid and _cid in night_map:
            remaining_needed = night_map[_cid]
        elif night_map:
            remaining_needed = sum(night_map.values())
        else:
            remaining_needed = max(0, daily_ev_target - daily_ev_energy)

        from ..utils.translate import get_text
        _t = lambda key, default, **kw: get_text(self.hass, key, default, **kw)

        if state == ChargingState.SOLAR_CHARGING_ACTIVE:
            messages["charger"] = _t("notif_charger_solar",
                "Solar: {current}A", current=calculated_current)
            messages["mobile"] = _t("notif_solar_started",
                "Solar charging started: {current}A ({power:.0f}W)",
                current=calculated_current, power=available_power)

        elif state == ChargingState.SOLAR_SUPER_CHARGING:
            messages["charger"] = _t("notif_charger_bat_solar",
                "Bat+Sol: {current}A", current=calculated_current)

        elif state == ChargingState.SOLAR_PAUSE_LOW_BATTERY:
            messages["charger"] = _t("notif_charger_pause_bat",
                "Pause: Bat {soc}%", soc=battery_soc)

        elif state == ChargingState.SOLAR_TARGET_REACHED:
            messages["charger"] = _t("notif_charger_target", "Target reached")
            messages["mobile"] = _t("notif_target_reached",
                "Daily target reached: {charged:.1f}/{target}kWh",
                charged=daily_ev_energy, target=daily_ev_target)

        elif state == ChargingState.SOLAR_WAITING_BATTERY_PRIORITY:
            messages["charger"] = _t("notif_charger_wait_bat",
                "Wait: Bat {soc}%", soc=battery_soc)

        elif state == ChargingState.SOLAR_MIN_PV:
            messages["charger"] = _t("notif_charger_min_pv",
                "Min+PV: {current}A", current=calculated_current)

        elif state == ChargingState.SOLAR_IDLE:
            if ev_session_energy > 0:
                messages["charger"] = _t("notif_charger_session_done", "Session done")
                messages["mobile"] = _t("notif_solar_stopped",
                    "Solar charging stopped: {energy:.1f}kWh charged",
                    energy=ev_session_energy)

        elif state == ChargingState.NIGHT_CHARGING_ACTIVE:
            messages["charger"] = _t("notif_charger_night",
                "Night: {remaining:.0f}kWh", remaining=remaining_needed)
            messages["mobile"] = _t("notif_night_started",
                "Night charging started: {remaining:.1f}kWh remaining",
                remaining=remaining_needed)

        elif state == ChargingState.NIGHT_TARGET_REACHED:
            # #596: NIGHT_TARGET_REACHED completes on the night SOC/deadline
            # target, NOT the daily kWh target — so showing "charged/daily"
            # (e.g. "1.9/8.0kWh") falsely reads as a shortfall when the car is
            # simply full. Show only what was charged. (notif_target_reached
            # below keeps /target: that state IS the daily-kWh target.)
            messages["charger"] = _t("notif_charger_night_done", "Night: Done")
            messages["mobile"] = _t("notif_night_complete",
                "Night charging complete: {charged:.1f}kWh charged",
                charged=daily_ev_energy)

        elif state == ChargingState.NIGHT_DISABLED:
            messages["charger"] = _t("notif_charger_night_off", "Night: Off")

        elif state == ChargingState.NIGHT_IDLE:
            messages["charger"] = _t("notif_charger_night_no_ev", "Night: No EV")

        elif state == ChargingState.TARGET_REACHED:
            messages["charger"] = _t("notif_charger_target_done", "Target done")
            messages["mobile"] = _t("notif_target_reached",
                "Daily target reached: {charged:.1f}/{target}kWh",
                charged=daily_ev_energy, target=daily_ev_target)

        elif state == ChargingState.IDLE:
            if ev_session_energy > 0:
                messages["charger"] = _t("notif_charger_complete", "Complete")

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
            actions=[{"action": "URI", "title": get_text(self.hass, "notif_open_dashboard", "Open Dashboard"), "uri": "/sem-dashboard/overview"}],
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
            actions=[{"action": "URI", "title": get_text(self.hass, "notif_open_dashboard", "Open Dashboard"), "uri": "/sem-dashboard/overview"}],
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

        from ..utils.translate import get_text
        currency = self.hass.config.currency or "EUR"
        msg = get_text(self.hass, "notif_daily_summary",
            "Today: {solar:.1f} kWh solar · {autarky:.0f}% autarky · "
            "Saved {savings:.2f} {currency} · Net cost {net_cost:.2f} {currency}",
            solar=solar, autarky=autarky, savings=savings,
            net_cost=net_cost, currency=currency)
        if ev > 0:
            msg += get_text(self.hass, "notif_daily_summary_ev",
                " · EV {ev:.1f} kWh", ev=ev)
        if tomorrow > 0:
            msg += get_text(self.hass, "notif_daily_summary_tomorrow",
                "\nTomorrow: {tomorrow:.1f} kWh forecast", tomorrow=tomorrow)

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

    async def notify_ev_nearly_full(
        self, minutes_remaining: float, *, charger_name: str | None = None,
    ) -> None:
        """Notify user that EV is nearly full based on taper detection (#106, #193)."""
        flag = f"ev_nearly_full_{charger_name}" if charger_name else "ev_nearly_full"
        if minutes_remaining > 10:
            self._notified_flags.discard(flag)
            return
        if flag in self._notified_flags:
            return
        self._notified_flags.add(flag)

        label = charger_name or "EV"
        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "charging",
            "event": "ev_nearly_full",
            "charger_name": label,
            "minutes_remaining": round(minutes_remaining, 0),
        })
        from ..utils.translate import get_text
        await self._send_mobile_notification(
            get_text(self.hass, "notif_ev_nearly_full",
                "{name} nearly full — ~{minutes:.0f} min remaining",
                name=label, minutes=minutes_remaining),
            channel=_CHANNEL_CHARGING,
            group="sem_charging",
        )

    # (#440) ``notify_ev_charge_skip`` / ``notify_ev_charge_recommended``
    # were removed alongside the skip-decision wiring. Both fired based
    # on the estimated_soc-driven ``charge_needed`` flag, which is no
    # longer load-bearing in any decision path. Tests of the old
    # behaviour are updated to assert the methods are absent.

    async def notify_ev_deadline_unreachable(
        self, remaining_kwh: float, hours_left: float, deadline: str,
        *, charger_name: str | None = None, flag_key: str | None = None,
    ) -> None:
        """Notify that the EV charge target can't be reached by its deadline (#246).

        Fires once per charger until the deadline becomes reachable again
        (the coordinator clears the flag), so a borderline forecast that flips
        reachable/unreachable won't spam.

        ``flag_key`` (the charger id) keys the dedup flag so two chargers sharing
        a display name (or the default "EV") don't share one flag (#274/M3).
        """
        key = flag_key or charger_name
        flag = f"ev_deadline_unreachable_{key}" if key else "ev_deadline_unreachable"
        if flag in self._notified_flags:
            return
        self._notified_flags.add(flag)

        label = charger_name or "EV"
        self.hass.bus.async_fire(f"{DOMAIN}_notification", {
            "category": "charging",
            "event": "ev_deadline_unreachable",
            "charger_name": label,
            "remaining_kwh": round(remaining_kwh, 1),
            "hours_left": round(hours_left, 1),
            "deadline": deadline,
        })
        from ..utils.translate import get_text
        await self._send_mobile_notification(
            get_text(self.hass, "notif_ev_deadline_unreachable",
                "{name} can't reach its target by {deadline} — "
                "{kwh:.1f} kWh still needed in {hours:.1f} h",
                name=label, deadline=deadline, kwh=remaining_kwh, hours=hours_left),
            channel=_CHANNEL_CHARGING,
            group="sem_charging",
        )

    def clear_deadline_warning(
        self, charger_name: str | None = None, flag_key: str | None = None,
    ) -> None:
        """Clear the unreachable-deadline flag so it can fire again next time."""
        key = flag_key or charger_name
        flag = f"ev_deadline_unreachable_{key}" if key else "ev_deadline_unreachable"
        self._notified_flags.discard(flag)

    def reset(self) -> None:
        """Reset notification state."""
        self._last_notified_state = None
        self._notified_flags.clear()
