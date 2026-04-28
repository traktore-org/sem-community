"""Tests for NotificationManager from coordinator/notifications.py."""
import time
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
    _FLAP_STABILITY_SECONDS,
)
from custom_components.solar_energy_management.const import ChargingState


# ──────────────────────────────────────────────
# Fixtures
# ──────────────────────────────────────────────

@pytest.fixture
def hass():
    """Return a mocked Home Assistant instance."""
    h = MagicMock()
    h.config = MagicMock()
    h.config.config_dir = "/config"
    h.states = MagicMock()
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    h.services.has_service = MagicMock(return_value=True)
    h.bus = MagicMock()
    h.bus.async_fire = MagicMock()
    h.data = {}
    return h


@pytest.fixture
def config():
    """Return a default notification config (both enabled)."""
    return {
        "daily_ev_target": 10,
        "battery_priority_soc": 80,
        "mobile_notification_service": "notify.mobile_app_phone",
        "enable_keba_notifications": True,
        "enable_mobile_notifications": True,
    }


@pytest.fixture
def notifier(hass, config):
    """Return a NotificationManager with both KEBA and mobile enabled."""
    nm = NotificationManager(hass, config)
    # Pre-validate services to skip cached validation in tests
    nm._keba_service_checked = True
    nm._keba_service_available = True
    nm._keba_service_name = "keba_display"
    nm._mobile_service_checked = True
    nm._mobile_service_available = True
    nm._mobile_service_name = "mobile_app_phone"
    return nm


@pytest.fixture
def sample_data():
    """Return sample notification data."""
    return {
        "battery_soc": 65,
        "calculated_current": 10,
        "available_power": 3000,
        "ev_session_energy": 5.2,
        "daily_ev_energy": 7.5,
        "discharge_limit": 800,
    }


def _make_notifier(hass, config, keba_on=True, mobile_on=True):
    """Helper to create notifier with specific notification settings."""
    cfg = {**config, "enable_keba_notifications": keba_on, "enable_mobile_notifications": mobile_on}
    nm = NotificationManager(hass, cfg)
    # Pre-validate services to skip cached validation in tests
    nm._keba_service_checked = True
    nm._keba_service_available = True
    nm._keba_service_name = "keba_display"
    nm._mobile_service_checked = True
    nm._mobile_service_available = True
    nm._mobile_service_name = "mobile_app_phone"
    return nm


def _bypass_flap_suppression(notifier, state):
    """Pre-set pending state so flap suppression is satisfied on next call.

    For cooldown states, the manager requires the state to be stable for 60s.
    This helper sets the pending state as if it has been pending for long enough.
    """
    notifier._pending_state = state
    notifier._pending_state_since = time.monotonic() - _FLAP_STABILITY_SECONDS - 1


# ──────────────────────────────────────────────
# Basic initialization
# ──────────────────────────────────────────────

def test_init(notifier):
    """Test default initialization."""
    assert notifier._last_notified_state is None
    assert notifier.config is not None
    assert notifier.hass is not None


# ──────────────────────────────────────────────
# State change notifications
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_state_change_solar_charging(notifier, sample_data):
    """Test KEBA and mobile messages for solar charging."""
    _bypass_flap_suppression(notifier, ChargingState.SOLAR_CHARGING_ACTIVE)
    await notifier.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    assert notifier._last_notified_state == ChargingState.SOLAR_CHARGING_ACTIVE
    # Should have called KEBA + mobile = 2 calls
    assert notifier.hass.services.async_call.call_count == 2


@pytest.mark.asyncio
async def test_notify_state_change_night_charging(notifier, sample_data):
    """Test night charging notification with discharge limit."""
    await notifier.notify_state_change(ChargingState.NIGHT_CHARGING_ACTIVE, sample_data)
    calls = notifier.hass.services.async_call.call_args_list
    # KEBA message should include discharge limit
    keba_call = calls[0]
    assert "Night:" in keba_call[0][2]["message"]
    # Mobile should include "Night charging started"
    mobile_call = calls[1]
    assert "Night charging started" in mobile_call[0][2]["message"]


@pytest.mark.asyncio
async def test_notify_state_change_night_charging_no_limit(notifier, sample_data):
    """Test night charging notification without discharge limit."""
    sample_data.pop("discharge_limit", None)
    sample_data["discharge_limit"] = None
    await notifier.notify_state_change(ChargingState.NIGHT_CHARGING_ACTIVE, sample_data)
    calls = notifier.hass.services.async_call.call_args_list
    keba_call = calls[0]
    assert "Night:" in keba_call[0][2]["message"]


@pytest.mark.asyncio
async def test_notify_state_change_target_reached(notifier, sample_data):
    """Test solar target reached notification."""
    await notifier.notify_state_change(ChargingState.SOLAR_TARGET_REACHED, sample_data)
    calls = notifier.hass.services.async_call.call_args_list
    keba_call = calls[0]
    assert keba_call[0][2]["message"] == "Target reached"


@pytest.mark.asyncio
async def test_notify_state_change_pause_low_battery(notifier, sample_data):
    """Test pause low battery notification."""
    await notifier.notify_state_change(ChargingState.SOLAR_PAUSE_LOW_BATTERY, sample_data)
    calls = notifier.hass.services.async_call.call_args_list
    keba_call = calls[0]
    assert "65%" in keba_call[0][2]["message"]


@pytest.mark.asyncio
async def test_notify_state_change_idle_with_session(notifier, sample_data):
    """Test SOLAR_IDLE with session energy generates messages."""
    _bypass_flap_suppression(notifier, ChargingState.SOLAR_IDLE)
    await notifier.notify_state_change(ChargingState.SOLAR_IDLE, sample_data)
    calls = notifier.hass.services.async_call.call_args_list
    assert len(calls) == 2  # keba + mobile
    keba_call = calls[0]
    assert keba_call[0][2]["message"] == "Session done"


@pytest.mark.asyncio
async def test_notify_state_change_idle_no_session(notifier):
    """Test SOLAR_IDLE without session energy generates no messages."""
    _bypass_flap_suppression(notifier, ChargingState.SOLAR_IDLE)
    data = {"battery_soc": 65, "calculated_current": 0, "available_power": 0,
            "ev_session_energy": 0, "daily_ev_energy": 0}
    await notifier.notify_state_change(ChargingState.SOLAR_IDLE, data)
    notifier.hass.services.async_call.assert_not_called()


# ──────────────────────────────────────────────
# Duplicate suppression
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_duplicate_suppressed(notifier, sample_data):
    """Test same state twice sends only one notification."""
    _bypass_flap_suppression(notifier, ChargingState.SOLAR_CHARGING_ACTIVE)
    await notifier.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    count_after_first = notifier.hass.services.async_call.call_count
    await notifier.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    assert notifier.hass.services.async_call.call_count == count_after_first


# ──────────────────────────────────────────────
# Switch enable/disable
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_notify_both_disabled(hass, config, sample_data):
    """Test no notifications when both switches off."""
    nm = _make_notifier(hass, config, keba_on=False, mobile_on=False)
    _bypass_flap_suppression(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
    await nm.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_notify_keba_only(hass, config, sample_data):
    """Test only KEBA notification when mobile disabled."""
    nm = _make_notifier(hass, config, keba_on=True, mobile_on=False)
    _bypass_flap_suppression(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
    await nm.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    calls = hass.services.async_call.call_args_list
    assert len(calls) == 1
    assert calls[0][0][1] == "keba_display"


@pytest.mark.asyncio
async def test_notify_mobile_only(hass, config, sample_data):
    """Test only mobile notification when KEBA disabled."""
    nm = _make_notifier(hass, config, keba_on=False, mobile_on=True)
    _bypass_flap_suppression(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
    await nm.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    calls = hass.services.async_call.call_args_list
    assert len(calls) == 1
    assert calls[0][0][1] == "mobile_app_phone"


@pytest.mark.asyncio
async def test_notify_mobile_no_service(hass, sample_data):
    """Test no mobile notification when no service configured."""
    cfg = {"daily_ev_target": 10, "battery_priority_soc": 80, "mobile_notification_service": ""}
    nm = _make_notifier(hass, cfg, keba_on=False, mobile_on=True)
    _bypass_flap_suppression(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
    await nm.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    # Only the KEBA display is not enabled, and mobile has no service -> no calls
    hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_notify_mobile_service_not_found(hass, config, sample_data):
    """Test mobile notification skipped when service validation fails."""
    hass.services.has_service = MagicMock(return_value=False)
    nm = _make_notifier(hass, config, keba_on=False, mobile_on=True)
    # Override cached service availability to let validation run
    nm._mobile_service_checked = False
    nm._keba_service_checked = False
    _bypass_flap_suppression(nm, ChargingState.SOLAR_CHARGING_ACTIVE)
    await nm.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    hass.services.async_call.assert_not_called()


# ──────────────────────────────────────────────
# Error handling
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_keba_notification_error(notifier, sample_data):
    """Test KEBA service call error is handled gracefully."""
    notifier.hass.services.async_call = AsyncMock(side_effect=Exception("KEBA offline"))
    _bypass_flap_suppression(notifier, ChargingState.SOLAR_CHARGING_ACTIVE)
    # Should not raise
    await notifier.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    assert notifier._last_notified_state == ChargingState.SOLAR_CHARGING_ACTIVE


# ──────────────────────────────────────────────
# Reset
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_reset(notifier, sample_data):
    """Test reset clears last notified state."""
    _bypass_flap_suppression(notifier, ChargingState.SOLAR_CHARGING_ACTIVE)
    await notifier.notify_state_change(ChargingState.SOLAR_CHARGING_ACTIVE, sample_data)
    assert notifier._last_notified_state is not None
    notifier.reset()
    assert notifier._last_notified_state is None


# ──────────────────────────────────────────────
# Message coverage
# ──────────────────────────────────────────────

def test_messages_all_states(notifier, sample_data):
    """Test KEBA messages exist for states that generate them."""
    states_with_keba = [
        ChargingState.SOLAR_CHARGING_ACTIVE,
        ChargingState.SOLAR_SUPER_CHARGING,
        ChargingState.SOLAR_PAUSE_LOW_BATTERY,
        ChargingState.SOLAR_TARGET_REACHED,
        ChargingState.SOLAR_WAITING_BATTERY_PRIORITY,
        ChargingState.NIGHT_CHARGING_ACTIVE,
        ChargingState.NIGHT_TARGET_REACHED,
        ChargingState.NIGHT_DISABLED,
        ChargingState.NIGHT_IDLE,
        ChargingState.TARGET_REACHED,
    ]
    for state in states_with_keba:
        messages = notifier._get_notification_messages(state, sample_data)
        assert "keba" in messages, f"Missing KEBA message for {state}"

    # Only important states get mobile notifications
    states_with_mobile = [
        ChargingState.SOLAR_CHARGING_ACTIVE,
        ChargingState.SOLAR_TARGET_REACHED,
        ChargingState.NIGHT_CHARGING_ACTIVE,
        ChargingState.NIGHT_TARGET_REACHED,
        ChargingState.TARGET_REACHED,
    ]
    for state in states_with_mobile:
        messages = notifier._get_notification_messages(state, sample_data)
        assert "mobile" in messages, f"Missing mobile message for {state}"


def test_messages_solar_idle_with_session(notifier):
    """Test SOLAR_IDLE generates messages only with session energy."""
    data_with = {"ev_session_energy": 5.0, "battery_soc": 50, "calculated_current": 0,
                 "available_power": 0, "daily_ev_energy": 5.0}
    msgs = notifier._get_notification_messages(ChargingState.SOLAR_IDLE, data_with)
    assert "keba" in msgs

    data_without = {"ev_session_energy": 0, "battery_soc": 50, "calculated_current": 0,
                    "available_power": 0, "daily_ev_energy": 0}
    msgs = notifier._get_notification_messages(ChargingState.SOLAR_IDLE, data_without)
    assert msgs == {}


def test_messages_idle_with_session(notifier):
    """Test legacy IDLE generates messages only with session energy."""
    data_with = {"ev_session_energy": 3.0, "battery_soc": 50, "calculated_current": 0,
                 "available_power": 0, "daily_ev_energy": 3.0}
    msgs = notifier._get_notification_messages(ChargingState.IDLE, data_with)
    assert "keba" in msgs
    assert msgs["keba"] == "Complete"

    data_without = {"ev_session_energy": 0, "battery_soc": 50, "calculated_current": 0,
                    "available_power": 0, "daily_ev_energy": 0}
    msgs = notifier._get_notification_messages(ChargingState.IDLE, data_without)
    assert msgs == {}


# ──────────────────────────────────────────────
# EV Intelligence Notifications (#106)
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_ev_nearly_full_sends_once(notifier, hass):
    """notify_ev_nearly_full fires once, then deduplicates."""
    await notifier.notify_ev_nearly_full(3.0)
    assert hass.bus.async_fire.call_count == 1
    event_data = hass.bus.async_fire.call_args[0][1]
    assert event_data["event"] == "ev_nearly_full"
    assert event_data["minutes_remaining"] == 3.0

    # Second call should be deduplicated
    hass.bus.async_fire.reset_mock()
    await notifier.notify_ev_nearly_full(2.0)
    assert hass.bus.async_fire.call_count == 0


@pytest.mark.asyncio
async def test_ev_nearly_full_resets_when_above_threshold(notifier, hass):
    """notify_ev_nearly_full resets flag when minutes > 10."""
    await notifier.notify_ev_nearly_full(3.0)
    assert "ev_nearly_full" in notifier._notified_flags

    # Above threshold: flag should be cleared
    await notifier.notify_ev_nearly_full(15.0)
    assert "ev_nearly_full" not in notifier._notified_flags

    # Now it can fire again
    hass.bus.async_fire.reset_mock()
    await notifier.notify_ev_nearly_full(4.0)
    assert hass.bus.async_fire.call_count == 1


@pytest.mark.asyncio
async def test_ev_charge_skip_sends_once(notifier, hass):
    """notify_ev_charge_skip fires once per night."""
    await notifier.notify_ev_charge_skip(85.0, 3)
    assert hass.bus.async_fire.call_count == 1
    event_data = hass.bus.async_fire.call_args[0][1]
    assert event_data["event"] == "ev_charge_skip"
    assert event_data["estimated_soc"] == 85
    assert event_data["nights_remaining"] == 3

    # Deduplicated
    hass.bus.async_fire.reset_mock()
    await notifier.notify_ev_charge_skip(85.0, 3)
    assert hass.bus.async_fire.call_count == 0


@pytest.mark.asyncio
async def test_ev_charge_recommended_sends_once(notifier, hass):
    """notify_ev_charge_recommended fires once per night."""
    await notifier.notify_ev_charge_recommended(25.0)
    assert hass.bus.async_fire.call_count == 1
    event_data = hass.bus.async_fire.call_args[0][1]
    assert event_data["event"] == "ev_charge_recommended"
    assert event_data["estimated_soc"] == 25

    # Deduplicated
    hass.bus.async_fire.reset_mock()
    await notifier.notify_ev_charge_recommended(25.0)
    assert hass.bus.async_fire.call_count == 0


@pytest.mark.asyncio
async def test_ev_notifications_reset_on_notifier_reset(notifier, hass):
    """All EV flags should clear on notifier.reset()."""
    await notifier.notify_ev_nearly_full(3.0)
    await notifier.notify_ev_charge_skip(85.0, 3)
    await notifier.notify_ev_charge_recommended(25.0)
    assert len(notifier._notified_flags) >= 3

    notifier.reset()
    assert len(notifier._notified_flags) == 0
