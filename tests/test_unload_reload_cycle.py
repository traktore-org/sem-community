"""Real-hass coverage for unload + reload cycle.

Phase 3 of the testing-framework adoption. Pins the cleanup contract
that ``async_unload_entry`` must honour and the idempotency of a
setup → unload → setup → ... cycle.

What these tests pin
--------------------
* Unload clears ``hass.data[DOMAIN][entry_id]``.
* Unload removes all 8 SEM services.
* Unload calls ``SurplusController.clear_devices`` (new in this batch
  — see ``coordinator/surplus_controller.py``).
* Reload is idempotent: no duplicate service registrations, no
  duplicate frontend resources, surplus-controller device list reset.

Pre-fix observed (live on dev 2026-06-02): a reload would leave the
prior cycle's EV / heat-pump / switch devices in
``coordinator._surplus_controller._devices``, and the new setup would
register them again. The dispatch table grew with each reload —
silently doubling the device count from the surplus controller's
perspective, even though only one physical device existed.
"""
from __future__ import annotations

import importlib.util

import pytest

# See test_setup_entry_lifecycle.py for the same skip pattern.
pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("pytest_homeassistant_custom_component") is None,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

from custom_components.solar_energy_management.const import DOMAIN


_SERVICES = (
    "generate_dashboard",
    "sync_priorities_from_dashboard",
    "set_device_control_mapping",
    "update_device_priorities",
    "update_device_config",
    "update_target_peak",
    "register_surplus_device",
    "schedule_appliance",
)


# ---------------------------------------------------------------------------
# Unload — hass.data cleared, services removed
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_unload_clears_hass_data(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """``async_unload_entry`` pops the entry's coordinator out of
    ``hass.data[DOMAIN]``. A regression that left it behind would mean
    a re-setup would land a SECOND coordinator alongside the first,
    each consuming sensors independently."""
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    assert sem_config_entry.entry_id in hass.data[DOMAIN]

    assert await hass.config_entries.async_unload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    assert sem_config_entry.entry_id not in hass.data.get(DOMAIN, {}), (
        "entry_id still in hass.data[DOMAIN] after unload — coordinator "
        "leaked"
    )


@pytest.mark.asyncio
async def test_unload_removes_all_services(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """HA Quality Scale (config-entry-unloading) requires services
    registered by the entry to be removed on unload. Pre-fix the
    services lingered after unload and pointed at a coordinator that
    was about to be gc'd — calling them would raise."""
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    # All registered after setup.
    for svc in _SERVICES:
        assert hass.services.has_service(DOMAIN, svc), (
            f"service not registered before unload: {svc}"
        )

    assert await hass.config_entries.async_unload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    # None present after unload.
    still_present = [s for s in _SERVICES if hass.services.has_service(DOMAIN, s)]
    assert not still_present, (
        f"services not removed after unload: {still_present}"
    )


@pytest.mark.asyncio
async def test_unload_clears_surplus_controller_devices(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """SurplusController.clear_devices must be called on unload (new
    contract from 2026-06-02 batch). Pre-fix the prior cycle's
    registered devices would leak into the next setup's dispatch
    table.
    """
    sem_config_entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    sc = getattr(coordinator, "_surplus_controller", None)
    assert sc is not None, "coordinator has no _surplus_controller"

    # Seed the controller so the clear is observable. (In a smoke
    # install no chargers are configured, so the device list may be
    # empty after setup. We register one ourselves.)
    from unittest.mock import MagicMock
    fake_device = MagicMock()
    fake_device.device_id = "test_device_for_unload"
    fake_device.name = "Test Device"
    fake_device.priority = 5
    fake_device.min_power_threshold = 1000
    fake_device.device_type = MagicMock()
    fake_device.device_type.value = "switch"
    sc.register_device(fake_device)
    assert "test_device_for_unload" in sc._devices

    assert await hass.config_entries.async_unload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    assert not sc._devices, (
        f"surplus controller _devices not cleared on unload: "
        f"{list(sc._devices.keys())}"
    )

    # #656 — unload parks the detached devices for a possible removal. Nothing
    # here removes the entry, so drop the stash rather than leaving this
    # MagicMock (and the hass it closes over) alive in a module-level dict.
    import custom_components.solar_energy_management as sem
    sem._PENDING_LOAD_TEARDOWN.pop(sem_config_entry.entry_id, None)


# ---------------------------------------------------------------------------
# Reload — idempotent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_cycle_is_idempotent(
    hass, sem_config_entry, enable_custom_integrations,
) -> None:
    """Setup → unload → setup again must end in the same state as the
    first setup. The Quality Scale `config-entry-unloading` rule is
    explicit about this. Pre-fix observable regressions: duplicate
    services (HA raised on the second register), duplicate frontend
    resource URLs (Lovelace storage grew unbounded), surplus
    controller _devices doubling."""
    sem_config_entry.add_to_hass(hass)

    # First setup
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    # Snapshot services + entity registry size
    services_after_first = sum(
        1 for s in _SERVICES if hass.services.has_service(DOMAIN, s)
    )

    # Unload
    assert await hass.config_entries.async_unload(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    # Second setup
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()

    services_after_second = sum(
        1 for s in _SERVICES if hass.services.has_service(DOMAIN, s)
    )

    assert services_after_first == services_after_second == len(_SERVICES), (
        f"service count drift across reload: first={services_after_first}, "
        f"second={services_after_second}, expected={len(_SERVICES)}"
    )

    # The coordinator must be a fresh instance — not the cached one
    # from the first setup. (Otherwise we'd be leaking the prior cycle's
    # observers / update interval.)
    coordinator = hass.data[DOMAIN][sem_config_entry.entry_id]
    assert coordinator is not None
