"""Heartbeat write to KEBA-style chargers (#392).

KEBA's failsafe watchdog requires periodic *writes* — reads alone don't
refresh it (confirmed by KEBA Energy Automation support in
evcc-io/evcc#21093 comment 13094565). SEM's _set_current dedup used to
suppress writes when the commanded value hadn't changed, which silently
starved the watchdog during steady-state charging.

These tests pin the heartbeat behaviour in ``devices/base.py``:
- same-value re-requests within the heartbeat window are skipped
- once the window elapses, a same-value re-request goes through
- value changes always write regardless of timing
- inactive device writes regardless of timing (the dedup only ever fires
  while the device is active)
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
    DeviceState,
    WRITE_HEARTBEAT_INTERVAL_S,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    return hass


@pytest.fixture
def device(mock_hass):
    return CurrentControlDevice(
        hass=mock_hass,
        device_id="ev_charger",
        name="EV Charger",
        priority=5,
        min_current=6.0,
        max_current=32.0,
        phases=3,
        voltage=230.0,
        current_entity_id=None,
        charger_service="keba.set_current",
        charger_service_entity_id=None,
    )


def _set_clock(monkeypatch, t: float) -> None:
    """Pin time.monotonic so the heartbeat window is deterministic."""
    monkeypatch.setattr(
        "custom_components.solar_energy_management.devices.base.time.monotonic",
        lambda: t,
    )


@pytest.mark.asyncio
async def test_heartbeat_window_constant_is_sane():
    """The interval must be safely below KEBA's default 300 s failsafe
    timeout — half is the recommended margin per the evcc thread."""
    assert 30.0 <= WRITE_HEARTBEAT_INTERVAL_S <= 150.0


@pytest.mark.asyncio
async def test_same_value_within_window_skips_write(device, monkeypatch):
    """First write goes through; second same-value write within
    WRITE_HEARTBEAT_INTERVAL_S is suppressed (pre-#392 behaviour, still
    correct for rapid same-value calls)."""
    _set_clock(monkeypatch, 0.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 1
    assert device.is_active

    # Re-request the same value 30 s later — still inside the window.
    _set_clock(monkeypatch, 30.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 1, (
        "second same-value write inside the heartbeat window must be skipped"
    )


@pytest.mark.asyncio
async def test_same_value_past_window_writes_heartbeat(device, monkeypatch):
    """#392 fix: after WRITE_HEARTBEAT_INTERVAL_S a same-value re-request
    is no longer suppressed — the heartbeat write goes out and refreshes
    KEBA's failsafe watchdog."""
    _set_clock(monkeypatch, 0.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 1

    # Jump past the heartbeat window.
    _set_clock(monkeypatch, WRITE_HEARTBEAT_INTERVAL_S + 1.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 2, (
        "#392: heartbeat must fire once the window elapses"
    )


@pytest.mark.asyncio
async def test_repeated_heartbeats_at_window_boundaries(device, monkeypatch):
    """A long steady-state session should produce one heartbeat per
    window — not flood the integration, not starve it."""
    _set_clock(monkeypatch, 0.0)
    await device._set_current(16)  # 1st write
    assert device.hass.services.async_call.call_count == 1

    # Advance ~5 heartbeat windows. We expect 5 additional writes total.
    for i in range(1, 6):
        _set_clock(monkeypatch, i * (WRITE_HEARTBEAT_INTERVAL_S + 1.0))
        await device._set_current(16)
    assert device.hass.services.async_call.call_count == 6, (
        "#392: one heartbeat write per elapsed window — no flood, no skip"
    )


@pytest.mark.asyncio
async def test_value_change_writes_regardless_of_window(device, monkeypatch):
    """Value changes are not heartbeat-gated — they always go through."""
    _set_clock(monkeypatch, 0.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 1

    # Within the window, ask for a different value.
    _set_clock(monkeypatch, 5.0)
    await device._set_current(20)
    assert device.hass.services.async_call.call_count == 2


@pytest.mark.asyncio
async def test_inactive_device_writes_regardless_of_window(device, monkeypatch):
    """When the device is IDLE the dedup short-circuit never triggers —
    activation writes always go through. Guards against a stale
    _last_write_at preventing a fresh session start."""
    _set_clock(monkeypatch, 0.0)
    # Fake a stale write 1 s ago without setting is_active.
    device._current_setpoint = 16.0
    device._last_write_at = 0.0
    device._status.state = DeviceState.IDLE

    # Within the heartbeat window, asking for the same current must still
    # write because is_active=False.
    _set_clock(monkeypatch, 5.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 1


@pytest.mark.asyncio
async def test_stale_setpoint_resyncs_after_window(device, monkeypatch):
    """Companion bug to the heartbeat: if KEBA silently dropped to
    fallback (failsafe trip, replug fallback) while SEM still thinks it
    commanded 16 A, the pre-#392 dedup left the system stuck. After the
    fix, the same-value write within one window forces a re-sync."""
    _set_clock(monkeypatch, 0.0)
    await device._set_current(16)
    assert device.hass.services.async_call.call_count == 1

    # KEBA silently dropped to 6 A (failsafe trip). SEM doesn't know.
    # Time passes past the heartbeat window.
    _set_clock(monkeypatch, WRITE_HEARTBEAT_INTERVAL_S + 1.0)
    await device._set_current(16)
    # The heartbeat write goes through with value 16 — KEBA accepts it
    # and the device-side state re-converges. Without #392 this would
    # have stayed skipped indefinitely.
    assert device.hass.services.async_call.call_count == 2
    last_call = device.hass.services.async_call.call_args_list[-1]
    assert last_call.args[0] == "keba"
    assert last_call.args[1] == "set_current"
    assert last_call.args[2]["current"] == 16
