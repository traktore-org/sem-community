"""#890 — the drag list must move service-registered devices too.

``priority_for`` is documented as THE single priority axis, and every ED
row, direct device and charger reads its slot from it. A device registered
through ``register_surplus_device`` did not: its live object was seeded
straight from the stored spec, the per-cycle refresh carved it out, and the
card payload read the spec as well. So a drag persisted an override that
three readers then ignored — success reported, nothing moved (found on
``.175`` while proving #885: the chosen test load was a ``sim_*`` device).
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


class _FakeSurplusController:
    def __init__(self):
        self._devices = {}

    def register_device(self, device):
        self._devices[device.device_id] = device

    def unregister_device(self, device_id):
        self._devices.pop(device_id, None)

    def get_device(self, device_id):
        return self._devices.get(device_id)


@pytest.fixture
def registry():
    reg = UnifiedDeviceRegistry(
        MagicMock(), _FakeSurplusController(), MagicMock(), MagicMock()
    )
    reg._store = AsyncMock()
    # The ED rebuild is not the path under test — and on an install with no
    # Energy Dashboard it returns early, which is exactly why the drag must
    # not depend on it.
    reg.async_refresh_devices = AsyncMock()
    return reg


POOL = {
    "device_id": "sim_pool_pump",
    "entity_id": "switch.sim_pool_pump",
    "name": "Pool Pump",
    "priority": 6,
    "rated_power": 1200,
    "control_mode": "surplus",
}


def _live_priority(registry, did="sim_pool_pump"):
    return registry._surplus_controller.get_device(did).priority


@pytest.mark.asyncio
async def test_drag_moves_a_service_registered_device(registry):
    """The headline: drag to 1 → the allocator AND the card see 1."""
    await registry.async_register_service_device(dict(POOL))
    assert _live_priority(registry) == 6

    await registry.async_update_priority_overrides(
        [{"device_id": "sim_pool_pump", "priority": 1}]
    )

    assert _live_priority(registry) == 1
    assert registry.get_devices_for_sensor()["sim_pool_pump"]["priority"] == 1


@pytest.mark.asyncio
async def test_the_override_survives_a_restart_rehydrate(registry):
    """Persisted override + persisted spec → the override wins at boot."""
    await registry.async_register_service_device(dict(POOL))
    registry._priority_overrides["sim_pool_pump"] = 1

    registry._surplus_controller._devices.clear()   # restart
    registry._register_service_devices()

    assert _live_priority(registry) == 1


@pytest.mark.asyncio
async def test_re_registering_keeps_the_dragged_slot(registry):
    """A second register_surplus_device call (same id, spec priority 6) must
    not silently undo the user's drag — the override outranks the seed."""
    registry._priority_overrides["sim_pool_pump"] = 2
    summary = await registry.async_register_service_device(dict(POOL))

    assert _live_priority(registry) == 2
    assert summary["priority"] == 2


@pytest.mark.asyncio
async def test_the_per_cycle_refresh_covers_service_devices(registry):
    """``refresh_direct_device_priorities`` runs every cycle for direct
    devices; the service-device carve-out is what left them stranded."""
    await registry.async_register_service_device(dict(POOL))
    registry._priority_overrides["sim_pool_pump"] = 1

    registry.refresh_direct_device_priorities()

    assert _live_priority(registry) == 1


@pytest.mark.asyncio
async def test_no_override_keeps_the_spec_seed(registry):
    """Nothing dragged → the priority the service call gave stands."""
    await registry.async_register_service_device(dict(POOL))
    registry.refresh_direct_device_priorities()
    assert _live_priority(registry) == 6
    assert registry.get_devices_for_sensor()["sim_pool_pump"]["priority"] == 6
