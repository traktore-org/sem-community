"""(#1266) The delayed device re-discovery still waits 35 s on a real install.

Tests let that wait end when the entry's setup is done (conftest), because
35 real seconds per setup was 94 % of the suite's time. This file pins the
production side: the wait is 35 s, and the re-discovery runs after it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.features import (
    device_registry as dr,
)


@pytest.mark.unit
def test_the_delay_is_35_seconds():
    assert dr.REDISCOVERY_DELAY_S == 35


@pytest.mark.asyncio
@pytest.mark.real_rediscovery_wait
async def test_production_waits_the_delay(monkeypatch):
    slept = []

    async def _sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(dr, "asyncio", SimpleNamespace(sleep=_sleep))
    await dr.UnifiedDeviceRegistry._rediscovery_wait(SimpleNamespace())
    assert slept == [dr.REDISCOVERY_DELAY_S]


@pytest.mark.unit
def test_the_rediscovery_runs_after_the_wait():
    from .ast_contracts import calls

    assert calls(dr.UnifiedDeviceRegistry.async_initialize, "_rediscovery_wait")
    assert calls(dr.UnifiedDeviceRegistry.async_initialize, "async_refresh_devices")


@pytest.mark.asyncio
async def test_in_tests_the_wait_ends_when_setup_is_done():
    """The conftest stand-in returns at once on a hass with no entry in setup."""
    hass = SimpleNamespace(config_entries=SimpleNamespace(async_entries=lambda d: []))
    await dr.UnifiedDeviceRegistry._rediscovery_wait(SimpleNamespace(hass=hass))
