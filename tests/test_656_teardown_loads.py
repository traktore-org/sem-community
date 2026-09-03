"""#656 — loads must not be stranded ON when SEM goes away.

`deactivate_all()` existed for exactly this and had zero production callers:
`async_unload_entry` issued `command_normal()` to the battery adapters (#589
Part B) and then dropped the device references with `clear_devices()`, so a
hot-water boost temperature, an SG-Ready relay or a SEM-forced switch stayed
commanded with nothing left to expire it. Ledger class 4 — strand-across-
restart, the load-side sibling of the battery case.

Reinstalling doesn't heal it either: `DeviceReconciler` classifies a
leftover-ON load as `external_on`, marks it not-SEM-owned and deliberately
refuses to fight it. So the strand outlives the integration.

The teardown paths differ and the tests pin all four:

    reload      → no deactivation (a bounce per options change is not safety)
    disabled    → deactivate now (nothing is coming back)
    removed     → deactivate from the stash unload parked for us

HA shutdown isn't a fourth case: HA fires ``EVENT_HOMEASSISTANT_STOP`` →
``ConfigEntries._async_shutdown`` → ``entry.async_shutdown()`` and never calls
``async_unload_entry``, so nothing here runs and the load is left as-is until
SEM comes back.
"""
from __future__ import annotations

import contextlib

import pytest
from unittest.mock import AsyncMock, MagicMock, Mock

import custom_components.solar_energy_management as sem
from custom_components.solar_energy_management import (
    async_remove_entry,
    async_setup_entry,
    async_unload_entry,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)

DOMAIN = "solar_energy_management"


def _device(device_id="hot_water", priority=2, is_active=True, **kw):
    d = MagicMock()
    d.device_id = device_id
    d.priority = priority
    d.is_active = is_active
    d.is_enabled = kw.get("is_enabled", True)
    d.managed_externally = kw.get("managed_externally", False)
    # (#908) These fixtures model the strands #656 exists to clear — loads
    # SEM COMMANDED on (a hot-water boost, an SG-Ready relay, a forced
    # switch). Teardown now releases only commanded loads, so make ownership
    # explicit rather than leaning on MagicMock's truthy auto-attribute.
    d._sem_commanded = kw.get("_sem_commanded", True)
    d.deactivate = AsyncMock()
    return d


def _controller_with(*devices):
    sc = SurplusController(MagicMock())
    for d in devices:
        sc._devices[d.device_id] = d
    return sc


def _hass_and_entry(sc, entry_id="entry-1", disabled_by=None):
    coord = MagicMock()
    coord._battery_adapters = {}
    coord._surplus_controller = sc

    hass = MagicMock()
    hass.data = {DOMAIN: {entry_id: coord}}
    hass.config_entries = MagicMock()
    hass.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    hass.services = MagicMock()
    hass.services.async_remove = Mock()

    entry = MagicMock()
    entry.entry_id = entry_id
    entry.disabled_by = disabled_by
    return hass, entry


@pytest.fixture(autouse=True)
def _clean_stash():
    sem._PENDING_LOAD_TEARDOWN.clear()
    yield
    sem._PENDING_LOAD_TEARDOWN.clear()


@pytest.mark.unit
class TestDeactivateAllCoverage656:
    """The method itself — it has to reach the devices that strand."""

    @pytest.mark.asyncio
    async def test_it_deactivates_a_running_load(self):
        hw = _device()
        await _controller_with(hw).deactivate_all()
        hw.deactivate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_it_leaves_an_already_off_load_alone(self):
        off = _device(is_active=False)
        await _controller_with(off).deactivate_all()
        off.deactivate.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_disabled_device_that_is_latched_on_is_still_released(self):
        """``get_devices_sorted()`` filters these out. A device SEM switched on
        and that was then disabled is precisely a strand candidate — teardown
        has to reach it, so this iterates the raw registry."""
        latched = _device(device_id="pool_pump", is_enabled=False)
        await _controller_with(latched).deactivate_all()
        latched.deactivate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_an_externally_managed_device_that_is_on_is_still_released(self):
        latched = _device(device_id="ev", managed_externally=True)
        await _controller_with(latched).deactivate_all()
        latched.deactivate.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_one_failing_device_does_not_strand_the_others(self):
        """The failure mode this replaces is an unattended heating device left
        on, so a flaky first device must not abort the loop."""
        bad = _device(device_id="a", priority=1)
        bad.deactivate = AsyncMock(side_effect=RuntimeError("relay offline"))
        good = _device(device_id="b", priority=2)
        await _controller_with(bad, good).deactivate_all()
        good.deactivate.assert_awaited_once()


@pytest.mark.unit
class TestTeardownPaths656:
    @pytest.mark.asyncio
    async def test_a_reload_does_not_bounce_a_running_load(self):
        """Unload runs on every options change. Turning the hot-water boost off
        and straight back on again would trip the device's anti-short-cycle
        timer for no safety gain."""
        hw = _device()
        sc = _controller_with(hw)
        hass, entry = _hass_and_entry(sc)

        assert await async_unload_entry(hass, entry) is True
        hw.deactivate.assert_not_called()
        # ...but the devices are parked, in case this turns out to be a
        # removal rather than a reload. The registry is still cleared —
        # the reload-leak contract from 2026-06-02 is unchanged.
        assert sem._PENDING_LOAD_TEARDOWN["entry-1"] == [hw]
        assert sc._devices == {}

    @pytest.mark.asyncio
    async def test_removal_releases_the_load(self):
        hw = _device()
        sc = _controller_with(hw)
        hass, entry = _hass_and_entry(sc)

        await async_unload_entry(hass, entry)
        await async_remove_entry(hass, entry)

        hw.deactivate.assert_awaited_once()
        assert "entry-1" not in sem._PENDING_LOAD_TEARDOWN

    @pytest.mark.asyncio
    async def test_removal_leaves_an_uncommanded_load_alone(self):
        """(#908) markusschloesser's fridge/freezer: ON before SEM, adopted but
        never COMMANDED. The real removal path must not switch it off — the
        gate holds through ``async_unload_entry`` → ``async_remove_entry``,
        not only in a direct ``deactivate_devices`` call."""
        adopted = _device(device_id="freezer", _sem_commanded=False)
        sc = _controller_with(adopted)
        hass, entry = _hass_and_entry(sc)

        await async_unload_entry(hass, entry)
        await async_remove_entry(hass, entry)

        adopted.deactivate.assert_not_called()
        assert "entry-1" not in sem._PENDING_LOAD_TEARDOWN

    @pytest.mark.asyncio
    async def test_disabling_leaves_an_uncommanded_load_alone(self):
        """(#908) Disabling SEM must not turn off the user's own loads either."""
        from homeassistant.config_entries import ConfigEntryDisabler

        adopted = _device(device_id="freezer", _sem_commanded=False)
        sc = _controller_with(adopted)
        hass, entry = _hass_and_entry(sc, disabled_by=ConfigEntryDisabler.USER)

        assert await async_unload_entry(hass, entry) is True
        adopted.deactivate.assert_not_called()

    @pytest.mark.asyncio
    async def test_disabling_the_integration_releases_the_load_immediately(self):
        """Nothing follows a disable — no setup, no remove — so the deactivation
        cannot be deferred to ``async_remove_entry``."""
        from homeassistant.config_entries import ConfigEntryDisabler

        hw = _device()
        sc = _controller_with(hw)
        hass, entry = _hass_and_entry(sc, disabled_by=ConfigEntryDisabler.USER)

        assert await async_unload_entry(hass, entry) is True
        hw.deactivate.assert_awaited_once()
        assert "entry-1" not in sem._PENDING_LOAD_TEARDOWN

    @pytest.mark.asyncio
    async def test_remove_without_a_stash_is_a_no_op(self):
        """Setup can fail before a controller ever exists; removal must not
        raise on the way out."""
        hass, entry = _hass_and_entry(None)
        await async_remove_entry(hass, entry)  # must not raise

    @pytest.mark.asyncio
    async def test_a_failing_device_does_not_break_removal(self):
        hw = _device()
        hw.deactivate = AsyncMock(side_effect=RuntimeError("boiler unreachable"))
        sc = _controller_with(hw)
        hass, entry = _hass_and_entry(sc)

        await async_unload_entry(hass, entry)
        await async_remove_entry(hass, entry)  # must not raise
        assert "entry-1" not in sem._PENDING_LOAD_TEARDOWN


@pytest.mark.unit
class TestStashHygiene656:
    @pytest.mark.asyncio
    async def test_setup_drops_the_stash_without_deactivating(self):
        """A stash that survives to the next setup means a reload happened.
        Drop it — but do NOT deactivate, or every options change bounces the
        device the moment SEM comes back."""
        hw = _device()
        sem._PENDING_LOAD_TEARDOWN["entry-1"] = [hw]

        hass = MagicMock()
        hass.data = {}
        entry = MagicMock()
        entry.entry_id = "entry-1"

        # Full setup needs far more of HA than this fixture provides and will
        # blow up somewhere downstream; we only care that the stash handling at
        # the very top ran first, so don't pin *how* it fails (or that it does).
        with contextlib.suppress(Exception):
            await async_setup_entry(hass, entry)

        assert "entry-1" not in sem._PENDING_LOAD_TEARDOWN
        hw.deactivate.assert_not_called()

    @pytest.mark.asyncio
    async def test_the_stash_is_per_entry(self):
        a, b = _device(device_id="a"), _device(device_id="b")
        sc_a, sc_b = _controller_with(a), _controller_with(b)

        hass_a, entry_a = _hass_and_entry(sc_a, entry_id="A")
        hass_b, entry_b = _hass_and_entry(sc_b, entry_id="B")
        await async_unload_entry(hass_a, entry_a)
        await async_unload_entry(hass_b, entry_b)

        await async_remove_entry(hass_a, entry_a)

        a.deactivate.assert_awaited_once()
        b.deactivate.assert_not_called()
        assert sem._PENDING_LOAD_TEARDOWN["B"] == [b]

    @pytest.mark.asyncio
    async def test_an_install_with_no_devices_parks_nothing(self):
        """Most installs have no surplus loads at all — don't leave empty
        entries behind for every unload."""
        hass, entry = _hass_and_entry(_controller_with())
        await async_unload_entry(hass, entry)
        assert sem._PENDING_LOAD_TEARDOWN == {}
