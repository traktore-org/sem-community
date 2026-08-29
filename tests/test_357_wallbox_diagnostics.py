"""Pin the #357 Wallbox adapter diagnostics surface.

@RienduPre reports that toggling ``charge_mode = off`` on his Wallbox
Pulsar doesn't actually stop charging. The strategy decision IS
correct (``OffMode.decide()`` returns ``DISABLE`` unconditionally);
the failure is downstream in the adapter — most likely the Wallbox
pause-resume switch couldn't be discovered, so ``command_disable``
silently no-ops on the pause action and the contactor stays closed.

This file pins that the new ``charger_adapters`` block in the
diagnostics dump captures:

  * The resolved adapter class (so we know SEM picked Wallbox vs the
    generic fallback)
  * Wallbox-specific: ``pause_switch_searched`` (did discovery run?)
    + ``pause_switch_entity`` (what did it find, or None)
    + ``pause_switch_discovered`` (the boolean for quick triage)

When @RienduPre's dump shows ``pause_switch_discovered: false``, we
know the brand-quirk is the issue and we can extend the discovery
pattern. When ``pause_switch_discovered: true`` but he still sees
charging continue, the bug is downstream (Wallbox integration not
honouring the switch, or HA registry refusing the service call).
Either way the dump points at the failing step in one shot.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
)


@pytest.fixture
def _diag_hass(tmp_path):
    h = MagicMock()
    h.config = MagicMock()
    h.config.config_dir = str(tmp_path)

    async def _executor(func, *args, **kwargs):
        return func(*args, **kwargs)

    h.async_add_executor_job = _executor
    return h


@pytest.fixture
def _diag_entry():
    e = MagicMock()
    e.entry_id = "test_entry_357"
    e.version = 7
    e.title = "Solar Energy Management"
    e.domain = "solar_energy_management"
    e.data = {"battery_capacity_kwh": 10}
    e.options = {}
    return e


@pytest.fixture
def _diag_coordinator():
    c = MagicMock()
    c.last_update_success = True
    c.update_interval = timedelta(seconds=10)
    c._observer_mode = False
    c._load_manager = None
    c._energy_dashboard_config = None
    c.data = {}
    return c


class Test357WallboxAdapterDiagnostics:
    @pytest.mark.asyncio
    async def test_wallbox_pause_switch_discovered_surfaces_entity(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """Happy path: Wallbox adapter found its pause switch. The dump
        records the entity id + boolean so triage can confirm the
        adapter is wired right and look further downstream."""
        device = MagicMock(name="Wallbox Pulsar")
        device.name = "Wallbox Pulsar"
        device.max_current = 32
        device.min_current = 6
        device.charger_service = "wallbox.set_charging_current"

        # The WallboxAdapter records its own discovery state on these
        # private fields; we don't have to instantiate a real adapter.
        adapter = MagicMock()
        adapter.__class__.__name__ = "WallboxAdapter"
        type(adapter).__name__ = "WallboxAdapter"
        adapter._pause_switch_searched = True
        adapter._pause_switch_entity = "switch.wallbox_pulsar_pause_resume"

        _diag_coordinator._ev_devices = {"ev_charger": device}
        _diag_coordinator._charger_adapters = {"ev_charger": adapter}
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)

        adapters = result.get("charger_adapters", {})
        assert "ev_charger" in adapters
        info = adapters["ev_charger"]
        assert info["adapter_class"] == "WallboxAdapter"
        assert info["device_name"] == "Wallbox Pulsar"
        assert info["device_max_current"] == 32
        assert "wallbox" in info
        wallbox = info["wallbox"]
        assert wallbox["pause_switch_searched"] is True
        assert wallbox["pause_switch_entity"] == "switch.wallbox_pulsar_pause_resume"
        assert wallbox["pause_switch_discovered"] is True

    @pytest.mark.asyncio
    async def test_wallbox_pause_switch_missing_surfaces_as_false(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """The @RienduPre-style failure case: discovery ran but didn't
        find a pause switch. ``pause_switch_discovered`` MUST be
        ``False`` so triage sees it at a glance.

        Pre-this-commit, the diagnostics dump showed nothing about
        the adapter, so a "charger keeps charging" report needed
        log dives to even identify the layer at fault. After: one
        boolean."""
        device = MagicMock(name="Wallbox Pulsar")
        device.name = "Wallbox Pulsar"
        device.max_current = 32
        device.min_current = 6
        device.charger_service = "wallbox.set_charging_current"

        adapter = MagicMock()
        type(adapter).__name__ = "WallboxAdapter"
        adapter._pause_switch_searched = True
        adapter._pause_switch_entity = None  # ← discovery couldn't find it

        _diag_coordinator._ev_devices = {"ev_charger": device}
        _diag_coordinator._charger_adapters = {"ev_charger": adapter}
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        wallbox = result["charger_adapters"]["ev_charger"]["wallbox"]
        assert wallbox["pause_switch_searched"] is True
        assert wallbox["pause_switch_entity"] is None
        assert wallbox["pause_switch_discovered"] is False  # the triage signal

    @pytest.mark.asyncio
    async def test_non_wallbox_adapter_omits_brand_block(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """KEBA / generic adapters don't have the ``wallbox`` sub-block —
        only the adapter_class + generic device info. Keeps the dump
        compact."""
        device = MagicMock(name="KEBA P30")
        device.name = "KEBA P30"
        device.max_current = 16
        device.min_current = 6
        device.charger_service = "keba.set_current"

        adapter = MagicMock()
        type(adapter).__name__ = "KebaAdapter"

        _diag_coordinator._ev_devices = {"ev_charger": device}
        _diag_coordinator._charger_adapters = {"ev_charger": adapter}
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        info = result["charger_adapters"]["ev_charger"]
        assert info["adapter_class"] == "KebaAdapter"
        assert "wallbox" not in info

    @pytest.mark.asyncio
    async def test_no_ev_devices_empty_block(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """Solar-only / no-EV installs get an empty ``charger_adapters``
        block, not a missing key. Simpler to consume downstream."""
        _diag_coordinator._ev_devices = {}
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        assert result["charger_adapters"] == {}


class TestItReadsTheCacheTheCoordinatorActuallyWrites:
    """(#764) Found while proving the observer seam on .175: every real
    dump reported ``adapter_class: null``, including for a charger SEM was
    demonstrably driving.

    The diagnostics read ``coordinator._ev_adapters``. Production has never
    had that attribute — the adapter cache is ``_charger_adapters``
    (coordinator.py, ev_control.py). So ``adapter_class`` has been null on
    every install since #357 shipped, and the Wallbox discovery block below
    it — the entire point of #357 — was unreachable on real hardware.

    The tests above did not catch it because each one ASSIGNED
    ``_ev_adapters`` to the mock coordinator: they proved the dump could read
    a field the test itself invented. They now use the real name; these pin
    it there.
    """

    @pytest.mark.asyncio
    async def test_the_adapter_class_comes_from_the_real_cache(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        device = MagicMock(name="Keba Charger")
        device.name = "Keba Charger"
        device.max_current = 32
        device.min_current = 6
        device.charger_service = "keba.set_current"
        adapter = MagicMock()
        type(adapter).__name__ = "KebaAdapter"

        _diag_coordinator._ev_devices = {"keba_fa87f74cd3": device}
        # The name the coordinator actually assigns — nothing else.
        _diag_coordinator._charger_adapters = {"keba_fa87f74cd3": adapter}
        del _diag_coordinator._ev_adapters
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)

        assert result["charger_adapters"]["keba_fa87f74cd3"]["adapter_class"] == (
            "KebaAdapter"
        )

    def test_the_dump_names_the_same_attribute_the_coordinator_sets(self):
        """A rename on either side must break this, not go quiet for a year."""
        import inspect
        from custom_components.solar_energy_management import diagnostics
        from custom_components.solar_energy_management.coordinator import ev_control

        dump = inspect.getsource(diagnostics)
        writer = inspect.getsource(ev_control)
        assert "_charger_adapters" in dump, (
            "diagnostics reads an adapter cache the coordinator never writes"
        )
        assert "_charger_adapters" in writer
