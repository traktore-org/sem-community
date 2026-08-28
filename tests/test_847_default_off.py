"""#847 — two refinements behind the beta.20 ownership-gate fix.

1. A newly registered device starts in **Off** (monitor only): the user
   opts a device in deliberately — the #805 principle
   (DEFAULT_DISCOVERED_CONTROL_MODE = "off") now also covers
   service/card-registered devices. Legacy persisted specs that predate
   the stored mode keep the "surplus" they always ran under.
2. Commanded vs adopted: opt-out (mode → Off) may undo only what SEM
   itself started. ``record_activated`` marks a load COMMANDED; adoption
   (a running load claimed under Surplus so goal gates can stop it)
   never does — releasing an adopted load writes nothing.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)


def _registry_fixture():
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
    reg.hass = hass
    reg._service_registrations = {}
    reg._control_mode_overrides = {}
    reg._device_goals = {}
    reg._dependency_overrides = {}
    reg._surplus_controller = MagicMock()
    reg._surplus_controller._devices = {}
    reg._dependency_would_cycle = MagicMock(return_value=False)
    reg._apply_goals = MagicMock()
    reg._drop_discovered_duplicates = MagicMock()
    reg._save_storage = AsyncMock()
    return reg


# ── creation default ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_new_device_without_a_mode_choice_starts_off():
    reg = _registry_fixture()
    await reg.async_register_service_device({
        "device_id": "pool_pump", "entity_id": "switch.pool",
    })
    assert reg._service_registrations["pool_pump"]["control_mode"] == "off"
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
    assert reg._service_registrations["pool_pump"]["control_mode"] == "off"
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


# ── commanded vs adopted lifecycle ──────────────────────────────────

def _live_device():
    from custom_components.solar_energy_management.devices.base import (
        SwitchDevice,
    )
    hass = MagicMock()
    hass.states.get = MagicMock(return_value=None)
    return SwitchDevice(hass=hass, device_id="d1", name="D1",
                        entity_id="switch.d1", rated_power=1000)


def test_record_activated_marks_commanded_and_adoption_does_not():
    d = _live_device()
    d.record_activated()
    assert d._sem_owned and d._sem_commanded
    d.record_deactivated()
    assert not d._sem_owned and not d._sem_commanded
    d.control_mode = DeviceControlMode.SURPLUS
    assert d._adopt_ownership() is True
    assert d._sem_owned and not d._sem_commanded    # adopted, never commanded


# ── the release intent: opt-out undoes only SEM's own action ────────

def _off_device(*, active, owned, commanded):
    return SimpleNamespace(
        control_mode=DeviceControlMode.OFF,
        is_active=active, _sem_owned=owned, _sem_commanded=commanded,
        _offpeak_forced=True, _batt_overnight_forced=True,
        get_current_consumption=lambda: 500.0,
    )


def test_opt_out_ends_a_sem_started_run():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        compute_load_intent,
    )
    d = _off_device(active=True, owned=True, commanded=True)
    intent = compute_load_intent(d, remaining_surplus_w=0.0)
    assert intent.on is False
    assert "SEM-started" in intent.reason


def test_opt_out_releases_an_adopted_load_without_a_write():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        compute_load_intent,
    )
    d = _off_device(active=True, owned=True, commanded=False)
    intent = compute_load_intent(d, remaining_surplus_w=0.0)
    assert intent.on is True                    # stays exactly as it is
    assert intent.reason == "off — monitor only"
    assert d._sem_owned is False                # claim released
    assert d._offpeak_forced is False           # markers cleared
    assert d._batt_overnight_forced is False


def test_off_mode_user_load_never_owned_stays_untouched():
    from custom_components.solar_energy_management.coordinator.surplus_controller import (
        compute_load_intent,
    )
    d = _off_device(active=True, owned=False, commanded=False)
    intent = compute_load_intent(d, remaining_surplus_w=0.0)
    assert intent.on is True
    assert d._offpeak_forced is True            # nothing touched at all
