"""Round-trip tests for manual device-control mapping (#219).

The configure dialog lets a user map a control for a load device when
auto-discovery fails. These tests pin the persisted ``control`` dict shape for
every control type SEM can shed/restore — switch, current, input_boolean
(entity-based) and service (service-call based) — so a future change can't
silently drop the service fields the way the dialog silently dropped the
saved values before #219.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


@pytest.fixture
def registry():
    reg = UnifiedDeviceRegistry(
        MagicMock(), MagicMock(), MagicMock(), MagicMock()
    )
    # Isolate from real storage + device discovery.
    reg._store = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    return reg


@pytest.mark.asyncio
@pytest.mark.parametrize("ctype,entity", [
    ("switch", "switch.dryer"),
    ("current", "number.keba_current"),
    ("input_boolean", "input_boolean.heater"),
])
async def test_entity_mapping_persists(registry, ctype, entity):
    """Entity-based types store {type, entity} and persist to storage."""
    await registry.async_set_manual_mapping("sensor.dev_energy", entity, ctype)

    mapping = registry._manual_mappings["sensor.dev_energy"]
    assert mapping == {
        "type": ctype,
        "entity": entity,
        "discovered_via": "manual_mapping",
    }
    registry._store.async_save.assert_awaited_once()
    saved = registry._store.async_save.call_args[0][0]
    assert saved["mappings"]["sensor.dev_energy"]["entity"] == entity


@pytest.mark.asyncio
async def test_service_mapping_persists_service_fields(registry):
    """Service type stores the call definition, not an entity (KEBA/Easee)."""
    await registry.async_set_manual_mapping(
        "sensor.keba_energy", "", "service",
        service="keba.set_current", param="current",
        shed_value=6, restore_value=16,
    )

    mapping = registry._manual_mappings["sensor.keba_energy"]
    assert mapping["type"] == "service"
    assert mapping["service"] == "keba.set_current"
    assert mapping["param"] == "current"
    assert mapping["shed_value"] == 6
    assert mapping["restore_value"] == 16
    # Service mappings must NOT carry an entity key (would be meaningless).
    assert "entity" not in mapping


@pytest.mark.asyncio
async def test_service_mapping_defaults(registry):
    """Omitted service params fall back to sensible defaults."""
    await registry.async_set_manual_mapping(
        "sensor.easee_energy", "", "service",
        service="easee.set_charger_max_limit",
    )
    mapping = registry._manual_mappings["sensor.easee_energy"]
    assert mapping["param"] == "current"
    assert mapping["shed_value"] == 0
    assert mapping["restore_value"] == 16


@pytest.mark.asyncio
async def test_remapping_overwrites_previous(registry):
    """Re-configuring a device replaces the stored mapping (wrong-switch fix)."""
    await registry.async_set_manual_mapping("sensor.x", "switch.wrong", "switch")
    await registry.async_set_manual_mapping("sensor.x", "switch.right", "switch")
    assert registry._manual_mappings["sensor.x"]["entity"] == "switch.right"


@pytest.mark.asyncio
async def test_remove_manual_mapping(registry):
    """Removing a mapping clears it and persists (the Clear button, #219)."""
    await registry.async_set_manual_mapping("sensor.x", "switch.wrong", "switch")
    registry._store.async_save.reset_mock()

    removed = await registry.async_remove_manual_mapping("sensor.x")
    assert removed is True
    assert "sensor.x" not in registry._manual_mappings
    registry._store.async_save.assert_awaited_once()
    saved = registry._store.async_save.call_args[0][0]
    assert "sensor.x" not in saved["mappings"]


@pytest.mark.asyncio
async def test_remove_unknown_mapping_is_noop(registry):
    """Removing a non-existent mapping returns False and doesn't persist."""
    removed = await registry.async_remove_manual_mapping("sensor.nope")
    assert removed is False
    registry._store.async_save.assert_not_awaited()
