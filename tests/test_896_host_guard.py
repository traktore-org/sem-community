"""#896 — a switch that looks like it powers the network or HA is never shed.

Names are read as whole words on generic nouns. The user can lift the guard;
their word, either way, beats the guess.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management.features.host_guard import (
    HOST_WORDS, looks_like_host,
)


@pytest.mark.parametrize("text", [
    "switch.switch_netzwerk", "switch.router_power", "Internet modem",
    "switch.ap_attic", "switch.nas", "Home Assistant host", "switch.homeassistant_pi",
    "switch.fritzbox", "switch.proxmox_node", "switch.ups_1", "switch.wlan_repeater",
    "Access Point Büro", "switch.ha_server", "switch.rpi4", "Raspberry Pi",
])
def test_network_and_host_names_are_caught(text):
    assert looks_like_host(text)


@pytest.mark.parametrize("text", [
    "switch.washing_machine", "switch.shaft_heater", "switch.map_light",
    "switch.hardware_lab", "sensor.hash", "switch.nasa_poster", "switch.pool_pump",
])
def test_ordinary_loads_are_not(text):
    assert not looks_like_host(text)


def test_the_domain_is_not_part_of_the_name():
    assert not looks_like_host("switch.kettle")


def test_one_constant_holds_the_words():
    assert "router" in HOST_WORDS and "ups" in HOST_WORDS


def _reg():
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    reg._critical_overrides = {}
    reg._control_mode_overrides = {}
    reg._service_registrations = {}
    reg._save_storage = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    return reg


def test_guard_makes_a_host_switch_critical_by_default():
    reg = _reg()
    crit, host = reg._critical_for("energy_dashboard_router", "Router", "switch.router")
    assert (crit, host) == (True, True)
    assert "energy_dashboard_router" in reg._host_guarded


def test_ordinary_switch_stays_sheddable():
    crit, host = _reg()._critical_for("energy_dashboard_dryer", "Dryer", "switch.dryer")
    assert (crit, host) == (False, False)


@pytest.mark.asyncio
async def test_user_can_allow_it_and_the_choice_sticks():
    reg = _reg()
    reg._critical_for("energy_dashboard_router", "Router", "switch.router")
    await reg.async_set_device_flag("energy_dashboard_router", "critical", False)
    crit, host = reg._critical_for("energy_dashboard_router", "Router", "switch.router")
    assert (crit, host) == (False, True)       # allowed; the warning no longer shows
    assert "energy_dashboard_router" not in reg._host_guarded


def test_user_marking_an_ordinary_load_critical_wins():
    reg = _reg()
    reg._critical_overrides["energy_dashboard_dryer"] = True
    assert reg._critical_for("energy_dashboard_dryer", "Dryer", "switch.dryer")[0] is True


def test_surplus_mode_does_not_stop_a_guarded_load():
    """The surplus engine stops a load when the surplus ends: the same cut."""
    reg = _reg()
    reg._control_mode_overrides["energy_dashboard_router"] = "surplus"
    reg._critical_for("energy_dashboard_router", "Router", "switch.router")
    assert reg.control_mode_for("energy_dashboard_router") == "peak_only"
    reg._critical_overrides["energy_dashboard_router"] = False
    reg._critical_for("energy_dashboard_router", "Router", "switch.router")
    assert reg.control_mode_for("energy_dashboard_router") == "surplus"


def test_load_manager_rows_found_by_its_own_discovery_carry_the_guard():
    from custom_components.solar_energy_management.features.load_device_discovery import (
        looks_like_host as seen,
    )
    assert seen("switch.router") and not seen("switch.dryer")
