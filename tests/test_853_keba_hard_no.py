"""#853 — on KEBA a hard no (DISABLE) parks the box; only a pause quota-holds.

The other half of #846: park-on-disconnect stopped the INHERITED allowance,
but a fresh plug-in against a zero ask still got a fresh 1 kWh quota,
because ``command_disable`` routed to the quota-hold ``stop_session``.
Live PROD 28.08: plug 18:24:29 → quota 1.0 kWh at 18:25:11 → the box
charged 3.19 kW toward it while the daily target was 0.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_adapters.keba import (
    KebaAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
)


def _adapter():
    dev = MagicMock()
    dev.stop_session = AsyncMock()
    dev.park_off = AsyncMock()
    a = KebaAdapter.__new__(KebaAdapter)
    a._device = dev
    a._last_intent = None
    return a, dev


@pytest.mark.asyncio
async def test_disable_parks_the_box_and_writes_no_quota():
    a, dev = _adapter()
    await a.command_disable()
    dev.park_off.assert_awaited_once()
    dev.stop_session.assert_not_awaited()       # a hard no grants NOTHING
    assert a._last_intent is ChargerIntent.DISABLE


@pytest.mark.asyncio
async def test_idle_keeps_the_quota_hold():
    """A pause expects to resume — the quota-hold is its native language
    (#553/#829); parking here would fight every solar lull."""
    a, dev = _adapter()
    await a.command_idle()
    dev.stop_session.assert_awaited_once()
    dev.park_off.assert_not_awaited()
    assert a._last_intent is ChargerIntent.IDLE
