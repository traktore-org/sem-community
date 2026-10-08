"""#1055 follow-up — saving the grid limit on the Configuration tab.

With load management off there is no load manager, so ``set_option`` sent
``target_peak_limit`` down the unrouted path: one entry write and a full
integration reload. ``peak_limit_unlimited`` took that path on every home.
#913 took the same reload out of the Control-tab slider; the Config tab kept
it. Both keys are read live (``_target_peak_limit_kw`` /
``_peak_limit_unlimited``), so a save must reach them without a reload.

Real HA: the coordinator object must stay the same, and the published
sensor must carry the saved value.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.const import DOMAIN

from .test_services_real import _seed_sem_input_sensors


async def _setup(hass, entry, **options):
    _seed_sem_input_sensors(hass)
    entry.add_to_hass(hass)
    if options:
        hass.config_entries.async_update_entry(
            entry, options={**(entry.options or {}), **options})
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


async def _save(hass, options):
    await hass.services.async_call(
        DOMAIN, "set_option", {"options": options}, blocking=True)
    await hass.async_block_till_done()


async def _published(hass, coordinator):
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    return hass.states.get("sensor.sem_target_peak_limit")


@pytest.mark.asyncio
async def test_limit_saved_without_load_management_does_not_reload(
    sem_real_hass, sem_config_entry,
) -> None:
    coordinator = await _setup(sem_real_hass, sem_config_entry,
                               load_management_enabled=False)
    assert coordinator._load_manager is None, "precondition: load management off"

    await _save(sem_real_hass, {"target_peak_limit": 8.5})

    assert sem_config_entry.runtime_data is coordinator, "the save reloaded SEM"
    assert sem_config_entry.options["target_peak_limit"] == 8.5
    assert coordinator._target_peak_limit_kw() == 8.5
    state = await _published(sem_real_hass, coordinator)
    assert float(state.state) == 8.5


@pytest.mark.asyncio
async def test_no_limit_saved_without_load_management_does_not_reload(
    sem_real_hass, sem_config_entry,
) -> None:
    coordinator = await _setup(sem_real_hass, sem_config_entry,
                               load_management_enabled=False)

    await _save(sem_real_hass, {"peak_limit_unlimited": True})
    assert sem_config_entry.runtime_data is coordinator, "the save reloaded SEM"
    assert sem_config_entry.options["peak_limit_unlimited"] is True
    assert coordinator._peak_limit_unlimited() is True
    state = await _published(sem_real_hass, coordinator)
    assert state.attributes["peak_limit_unlimited"] is True

    # A YAML call sends the word, not a boolean.
    await _save(sem_real_hass, {"peak_limit_unlimited": "false"})
    assert sem_config_entry.runtime_data is coordinator
    assert coordinator._peak_limit_unlimited() is False


@pytest.mark.asyncio
async def test_no_limit_saved_with_load_management_reaches_the_manager(
    sem_real_hass, sem_config_entry,
) -> None:
    coordinator = await _setup(sem_real_hass, sem_config_entry,
                               load_management_enabled=True,
                               target_peak_limit=7.0)
    lm = coordinator._load_manager
    assert lm is not None, "precondition: load management on"

    await _save(sem_real_hass, {"peak_limit_unlimited": True})
    assert sem_config_entry.runtime_data is coordinator, "the save reloaded SEM"
    assert lm._peak_unlimited is True
    assert coordinator._peak_limit_unlimited() is True
    # The limit is kept, only the flag moved.
    assert coordinator._target_peak_limit_kw() == 7.0

    # Both keys in one save: the limit in the save wins, not the old one.
    await _save(sem_real_hass, {"peak_limit_unlimited": False, "target_peak_limit": 9.0})
    assert sem_config_entry.runtime_data is coordinator
    assert lm._peak_unlimited is False
    assert coordinator._target_peak_limit_kw() == 9.0
    state = await _published(sem_real_hass, coordinator)
    assert float(state.state) == 9.0
    assert state.attributes["peak_limit_unlimited"] is False


@pytest.mark.asyncio
async def test_a_level_saved_without_load_management_does_not_reload(
    sem_real_hass, sem_config_entry,
) -> None:
    coordinator = await _setup(sem_real_hass, sem_config_entry,
                               load_management_enabled=False)
    await _save(sem_real_hass, {"warning_peak_level": 3.5})
    assert sem_config_entry.runtime_data is coordinator, "the save reloaded SEM"
    assert sem_config_entry.options["warning_peak_level"] == 3.5
