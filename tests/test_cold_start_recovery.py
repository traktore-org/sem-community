"""Cold-start recovery for Energy Dashboard power sensors (#274).

On HA restart SEM can derive its real-time power sensors before the source
integration (e.g. solax-modbus) has registered its entities, so every reading
sits at 0 until a manual reload. The coordinator re-derives each update cycle
while resolution is incomplete; these tests cover that retry loop.
"""
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.const import ED_RESOLVE_MAX_ATTEMPTS


def _coord():
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        c = SEMCoordinator.__new__(SEMCoordinator)
    c._ed_resolve_pending = True
    c._ed_resolve_attempts = 0
    return c


@pytest.mark.asyncio
async def test_resolves_on_later_attempt():
    """Pending clears the cycle the source integration finally registers."""
    c = _coord()
    calls = {"n": 0}

    async def fake_init(quiet=False):
        calls["n"] += 1
        # Source registers on the 3rd attempt → derivation now succeeds.
        c._ed_resolve_pending = calls["n"] < 3

    c.async_initialize_energy_dashboard = AsyncMock(side_effect=fake_init)

    for _ in range(5):
        if c._ed_resolve_pending:
            await c._retry_energy_dashboard_resolution()

    assert c._ed_resolve_pending is False
    assert c._ed_resolve_attempts == 3          # stopped retrying once resolved
    assert calls["n"] == 3


@pytest.mark.asyncio
async def test_gives_up_after_max_attempts():
    """A genuinely power-less setup stops retrying instead of looping forever."""
    c = _coord()

    async def never_resolves(quiet=False):
        c._ed_resolve_pending = True  # still incomplete every time

    c.async_initialize_energy_dashboard = AsyncMock(side_effect=never_resolves)

    # Drive more cycles than the cap; the loop must terminate.
    for _ in range(ED_RESOLVE_MAX_ATTEMPTS + 5):
        if c._ed_resolve_pending:
            await c._retry_energy_dashboard_resolution()

    assert c._ed_resolve_pending is False               # gave up
    assert c._ed_resolve_attempts == ED_RESOLVE_MAX_ATTEMPTS


@pytest.mark.asyncio
async def test_init_exception_does_not_break_cycle():
    """A failure inside re-derivation must not raise into the update loop."""
    c = _coord()
    c.async_initialize_energy_dashboard = AsyncMock(side_effect=RuntimeError("boom"))
    await c._retry_energy_dashboard_resolution()  # must not raise
    assert c._ed_resolve_attempts == 1


@pytest.mark.asyncio
async def test_retry_uses_quiet_logging():
    """Re-derivation calls init with quiet=True to avoid per-cycle log spam."""
    c = _coord()

    async def ok(quiet=False):
        assert quiet is True
        c._ed_resolve_pending = False

    c.async_initialize_energy_dashboard = AsyncMock(side_effect=ok)
    await c._retry_energy_dashboard_resolution()
    c.async_initialize_energy_dashboard.assert_awaited_once_with(quiet=True)
