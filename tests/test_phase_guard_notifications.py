"""Phase-guard alerting stays active independently of EV connection state."""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.notifications import (
    NotificationManager,
)


_ROOT = Path(__file__).resolve().parents[1]


def _snapshot(*, safe: bool, fresh: bool = True, authorized: bool = True, reason: str = ""):
    return {
        "mode": "enforcing_armed" if authorized else "enforcing_blocked",
        "safe": safe,
        "data_fresh": fresh,
        "control_authorized": authorized,
        "stop_reason": reason,
        "grid": {
            "l1": {"current_a": 8.0, "margin_a": 8.0},
            "l2": {"current_a": 17.2 if not safe else 9.0, "margin_a": -1.2 if not safe else 7.0},
            "l3": {"current_a": 7.0, "margin_a": 9.0},
        },
        "inverter": {
            "l1": {"current_a": 6.0, "margin_a": 10.0},
            "l2": {"current_a": 5.0, "margin_a": 11.0},
            "l3": {"current_a": 4.0, "margin_a": 12.0},
        },
    }


def _manager(**config):
    hass = MagicMock()
    hass.bus.async_fire = MagicMock()
    manager = NotificationManager(
        hass,
        {
            "phase_guard_notifications_enabled": True,
            "enable_mobile_notifications": True,
            **config,
        },
    )
    manager._send_mobile_notification = AsyncMock()
    return manager


@pytest.mark.asyncio
async def test_guard_alerts_without_any_ev_state_and_deduplicates_incident():
    manager = _manager()
    unsafe = _snapshot(safe=False, authorized=False, reason="grid:l2:over_limit")

    await manager.notify_phase_guard_transition(unsafe)
    await manager.notify_phase_guard_transition(unsafe)

    manager._send_mobile_notification.assert_awaited_once()
    message = manager._send_mobile_notification.await_args.args[0]
    assert "grid L2" in message
    assert "17.2 A" in message
    manager.hass.bus.async_fire.assert_called_once()
    event_name, payload = manager.hass.bus.async_fire.call_args.args
    assert event_name == "solar_energy_management_notification"
    assert payload["category"] == "alerts"
    assert payload["state"] == "phase_guard_blocked"


@pytest.mark.asyncio
async def test_guard_recovery_waits_until_active_gate_is_rearmed():
    manager = _manager()
    await manager.notify_phase_guard_transition(
        _snapshot(safe=False, authorized=False, reason="grid:l2:over_limit")
    )
    await manager.notify_phase_guard_transition(
        _snapshot(safe=True, authorized=False, reason="recovery_hold:2/3")
    )
    assert manager._send_mobile_notification.await_count == 1

    await manager.notify_phase_guard_transition(_snapshot(safe=True, authorized=True))

    assert manager._send_mobile_notification.await_count == 2
    assert "restored" in manager._send_mobile_notification.await_args.args[0].lower()
    states = [call.args[1]["state"] for call in manager.hass.bus.async_fire.call_args_list]
    assert states == ["phase_guard_blocked", "phase_guard_recovered"]


@pytest.mark.asyncio
async def test_observer_recovery_message_does_not_claim_gate_is_armed():
    manager = _manager()
    unsafe = _snapshot(safe=False, authorized=True, reason="grid:l2:over_limit")
    unsafe["read_only"] = True
    safe = _snapshot(safe=True, authorized=True)
    safe["read_only"] = True

    await manager.notify_phase_guard_transition(unsafe)
    await manager.notify_phase_guard_transition(safe)

    message = manager._send_mobile_notification.await_args.args[0].lower()
    assert "safe levels" in message
    assert "armed" not in message


@pytest.mark.asyncio
async def test_stale_sensor_alert_names_failed_phase_not_another_hot_phase():
    manager = _manager()
    stale = _snapshot(safe=False, fresh=False, authorized=False, reason="grid:l2:stale")
    stale["grid"]["l1"]["current_a"] = 15.9
    stale["grid"]["l2"]["current_a"] = None

    await manager.notify_phase_guard_transition(stale)

    message = manager._send_mobile_notification.await_args.args[0]
    assert "grid L2 sensor" in message
    assert "15.9 A" not in message


@pytest.mark.asyncio
async def test_disabled_phase_guard_never_alerts_even_if_snapshot_is_unsafe():
    manager = _manager()

    await manager.notify_phase_guard_transition(
        _snapshot(safe=False, authorized=False, reason="not_configured"),
        enabled=False,
    )

    manager._send_mobile_notification.assert_not_awaited()
    manager.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_guard_notifications_can_be_disabled_independently():
    manager = _manager(phase_guard_notifications_enabled=False)

    await manager.notify_phase_guard_transition(
        _snapshot(safe=False, authorized=False, reason="grid:l2:over_limit")
    )

    manager._send_mobile_notification.assert_not_awaited()
    manager.hass.bus.async_fire.assert_not_called()


@pytest.mark.asyncio
async def test_ha_event_failure_does_not_break_cycle_or_mobile_alert():
    manager = _manager()
    manager.hass.bus.async_fire.side_effect = RuntimeError("event bus unavailable")

    await manager.notify_phase_guard_transition(
        _snapshot(safe=False, authorized=False, reason="grid:l2:over_limit")
    )

    manager._send_mobile_notification.assert_awaited_once()


def test_guard_monitor_and_alert_run_before_ev_presence_check():
    source = (_ROOT / "coordinator" / "coordinator.py").read_text()
    update = "phase_guard_snapshot = update_active_phase_guard(self)"
    notify = "await self._notification_manager.notify_phase_guard_transition("
    retry = "if not self._ev_device and not self._ev_devices:"

    assert update in source
    assert notify in source
    update_index = source.index(update)
    notify_index = source.index(notify, update_index)
    retry_index = source.index(retry, notify_index)
    assert update_index < notify_index < retry_index
