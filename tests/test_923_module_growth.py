"""#923 — a module that appears after setup (a battery added to HA's Energy
Dashboard changes no SEM option) gets its entities through ONE reload.

Guarded: only ABSENT → PRESENT counts, once per transition, and at most one
module-driven reload per 10 minutes across reloads."""
from __future__ import annotations

import importlib.util
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.install_modules import (
    MODULE_RELOAD_MIN_INTERVAL_S, Module, Presence, module_reload_due, modules_grown,
)

ABSENT = {m: Presence.ABSENT for m in Module}
BATTERY_NOW = {**ABSENT, Module.BATTERY: Presence.PRESENT}


class TestTheGuard:

    def test_absent_to_present_is_growth(self):
        assert modules_grown(ABSENT, BATTERY_NOW) == (Module.BATTERY,)

    def test_absent_to_unknown_is_not_growth(self):
        # A failed re-read is not new hardware.
        assert modules_grown(ABSENT, {**ABSENT, Module.BATTERY: Presence.UNKNOWN}) == ()

    def test_present_to_absent_never_reloads(self):
        assert modules_grown(BATTERY_NOW, ABSENT) == ()

    def test_first_reload_is_due(self):
        assert module_reload_due(ABSENT, BATTERY_NOW, 1000.0, None) == (Module.BATTERY,)

    def test_a_second_within_the_interval_is_not(self):
        assert module_reload_due(ABSENT, BATTERY_NOW, 1000.0, 1000.0 - 60) == ()

    def test_after_the_interval_it_is_again(self):
        last = 1000.0 - MODULE_RELOAD_MIN_INTERVAL_S - 1
        assert module_reload_due(ABSENT, BATTERY_NOW, 1000.0, last) == (Module.BATTERY,)


def _stub(setup_presence, now_presence):
    stub = MagicMock()
    stub.setup_presence = setup_presence
    stub.install_presence.return_value = now_presence
    stub.config_entry = SimpleNamespace(entry_id="e923")
    stub.hass.data = {}
    return stub


class TestTheCoordinatorAsksOnce:

    def test_growth_schedules_one_reload(self):
        stub = _stub(ABSENT, BATTERY_NOW)
        SEMCoordinator._check_module_growth(stub)
        SEMCoordinator._check_module_growth(stub)   # rate-limited
        stub.hass.config_entries.async_schedule_reload.assert_called_once_with("e923")

    def test_no_verdict_yet_means_still_setting_up(self):
        stub = _stub(None, BATTERY_NOW)
        SEMCoordinator._check_module_growth(stub)
        stub.hass.config_entries.async_schedule_reload.assert_not_called()

    def test_nothing_grown_nothing_done(self):
        stub = _stub(BATTERY_NOW, BATTERY_NOW)
        SEMCoordinator._check_module_growth(stub)
        stub.hass.config_entries.async_schedule_reload.assert_not_called()


_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None


@pytest.mark.skipif(not _PHACC, reason="pytest-homeassistant-custom-component not installed")
@pytest.mark.asyncio
async def test_an_energy_dashboard_edit_rereads_it_once(hass):
    from homeassistant.components.energy.data import async_get_manager
    from homeassistant.config_entries import ConfigEntryState
    from pytest_homeassistant_custom_component.common import MockConfigEntry

    from custom_components.solar_energy_management import _async_listen_energy_prefs

    entry = MockConfigEntry(domain=DOMAIN, data={}, options={})
    entry.add_to_hass(hass)
    coordinator = MagicMock()
    coordinator.async_initialize_energy_dashboard = AsyncMock()
    entry.runtime_data = coordinator
    entry.mock_state(hass, ConfigEntryState.LOADED)
    hass.config.components.add("energy")

    await _async_listen_energy_prefs(hass)
    await _async_listen_energy_prefs(hass)   # a reload must not add a second listener

    manager = await async_get_manager(hass)
    await manager.async_update({"device_consumption": []})
    await hass.async_block_till_done()
    coordinator.async_initialize_energy_dashboard.assert_awaited_once_with(quiet=True)
