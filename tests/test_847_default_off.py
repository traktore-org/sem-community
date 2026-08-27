"""#847 — a newly registered device starts in Off (monitor only).

hoyte's fresh install: devices were added with the silent "surplus"
default, their already-running loads got ADOPTED (sem_owned), and the
moment the user set mode = Off the class-17 release switched them off —
SEM actuating on the opt-out of a load it never started.

The #805 principle (DEFAULT_DISCOVERED_CONTROL_MODE = "off": SEM does
not actuate what it found by itself until the user opts it in) now also
covers service/card-registered devices. Legacy persisted specs that
predate the stored mode keep the "surplus" they always ran under.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
)
from custom_components.solar_energy_management.features.device_registry import (
    DeviceRegistry,
)


def _registry_fixture():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    reg = DeviceRegistry.__new__(DeviceRegistry)
    reg.hass = hass
    reg._service_registrations = {}
    reg._control_mode_overrides = {}
    reg._dependency_overrides = {}
    reg._goal_overrides = {}
    reg._surplus_controller = MagicMock()
    reg._store = MagicMock()
    reg._store.async_delay_save = MagicMock()
    return reg


@pytest.mark.asyncio
async def test_a_new_device_without_a_mode_choice_starts_off():
    reg = _registry_fixture()
    await reg.async_register_service_device({
        "device_id": "pool_pump", "entity_id": "switch.pool",
    })
    stored = reg._service_registrations["pool_pump"]
    assert stored["control_mode"] == "off"
    dev = reg._surplus_controller.register_device.call_args[0][0]
    assert dev.control_mode == DeviceControlMode.OFF


@pytest.mark.asyncio
async def test_an_explicit_choice_is_honored():
    reg = _registry_fixture()
    await reg.async_register_service_device({
        "device_id": "pool_pump", "entity_id": "switch.pool",
        "control_mode": "surplus",
    })
    assert reg._service_registrations["pool_pump"]["control_mode"] == "surplus"


@pytest.mark.asyncio
async def test_garbage_mode_on_creation_normalizes_to_off():
    reg = _registry_fixture()
    await reg.async_register_service_device({
        "device_id": "pool_pump", "entity_id": "switch.pool",
        "control_mode": "banana",
    })
    stored = reg._service_registrations["pool_pump"]
    assert stored["control_mode"] == "off"
    dev = reg._surplus_controller.register_device.call_args[0][0]
    assert dev.control_mode == DeviceControlMode.OFF


def test_legacy_store_without_a_mode_stays_surplus():
    """A spec persisted before modes were stored ran as surplus for its
    whole life — restoring it as Off would CHANGE existing behavior."""
    reg = _registry_fixture()
    reg._service_registrations = {
        "old_boiler": {"entity_id": "switch.boiler", "name": "Boiler",
                       "priority": 5, "rated_power": 2000},
    }
    reg._register_service_devices()
    dev = reg._surplus_controller.register_device.call_args[0][0]
    assert dev.control_mode == DeviceControlMode.SURPLUS
