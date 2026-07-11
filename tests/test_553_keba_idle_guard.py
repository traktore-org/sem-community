"""#553 — KEBA box-level RUNAWAY CAP via the session-energy register.

KEBA firmware auto-restarts a session at its stored setpoint when the car
retries (~every 10 min, #315) — even after ``keba.disable``. While SEM is
alive its policing (#552) kills each rogue start within a cycle; this guard
bounds the damage when SEM is NOT policing (down/restarting). 1 kWh is the
keba library MINIMUM (0 < energy < 1 is rejected — live-verified on a real
P30: 0.001 was a silent no-op).

The counterpart invariant: EVERY SEM start must release the guard —
``start_session()`` always writes the session-energy register (the real
target, or 0 = no limit). Without that, a real session would die at 1 Wh.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.consts.core import (
    KEBA_IDLE_GUARD_KWH,
)
from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.services.has_service = MagicMock(return_value=True)
    return hass


@pytest.fixture
def keba(mock_hass):
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


def _calls(mock_hass, service):
    return [
        c.args for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 2 and c.args[1] == service
    ]


@pytest.mark.asyncio
async def test_stop_session_arms_idle_guard(keba, mock_hass):
    await keba.stop_session()
    se = _calls(mock_hass, "set_energy")
    assert se, "stop_session must arm the set_energy idle-guard"
    # the guard value rides in the data dict (3rd positional arg)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": KEBA_IDLE_GUARD_KWH}]
    # and the disable still fired first
    assert _calls(mock_hass, "disable")


@pytest.mark.asyncio
async def test_start_session_releases_guard_without_target(keba, mock_hass):
    """No SEM target → start writes 0 (no limit), releasing the guard."""
    await keba.start_session(energy_target_kwh=0)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 0}]


@pytest.mark.asyncio
async def test_start_session_writes_real_target(keba, mock_hass):
    await keba.start_session(energy_target_kwh=7.5)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 7.5}]


@pytest.mark.asyncio
async def test_stop_then_start_cycle_releases_guard(keba, mock_hass):
    """The full loop: stop arms ~1 Wh, next start releases it — a real
    session can never inherit the guard."""
    await keba.stop_session()
    mock_hass.services.async_call.reset_mock()
    await keba.start_session(energy_target_kwh=0)
    data = [
        c.args[2] for c in mock_hass.services.async_call.call_args_list
        if len(c.args) >= 3 and c.args[1] == "set_energy"
    ]
    assert data == [{"energy": 0}]


@pytest.mark.asyncio
async def test_no_guard_when_set_energy_unsupported(keba, mock_hass):
    """Non-KEBA service sets (no set_energy) skip the guard cleanly."""
    mock_hass.services.has_service = MagicMock(
        side_effect=lambda d, s: s != "set_energy"
    )
    await keba.stop_session()
    assert not _calls(mock_hass, "set_energy")
    assert _calls(mock_hass, "disable")
