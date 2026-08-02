"""#709 — read-only Deye diagnostics surface.

The diagnostics dump must expose enough to triage a Deye forced-charge
install from one payload: is forced charge currently available (and if
not, WHICH configured/state gate tripped), is the scope safety-latched
unsafe, and what the last recovery/actuation error was. This block is
READ-ONLY — it never triggers a write and must not leak the runtime
snapshot store or any secret.
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
    e.entry_id = "test_deye_diag"
    e.version = 16
    e.title = "Solar Energy Management"
    e.domain = "solar_energy_management"
    e.data = {"battery_charge_platform": "deye"}
    e.options = {
        "deye_observer_mode": False,
        "deye_actuation_enabled": True,
    }
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


def _make_adapter(unsafe=False, avail=True, reason="ok", last_error=None):
    cap = MagicMock()
    cap.available = avail
    cap.reason = reason
    cap.max_charge_current_a = 25.0
    cap.battery_voltage_age_s = 1.0
    cap.snapshot_supported = True
    cap.readback_supported = True
    cap.restore_supported = True
    adapter = MagicMock()
    type(adapter).__name__ = "DeyeBatteryAdapter"
    adapter.capability.return_value = cap
    adapter.unsafe_latched = unsafe
    adapter._last_error = last_error
    adapter._observer_mode = False
    adapter._actuation_enabled = True
    adapter._config_entry_id = "entry-deye-1"
    adapter._battery_id = "primary"
    return adapter


class TestDeyeDiagnostics:
    @pytest.mark.asyncio
    async def test_deye_block_surfaces_capability_and_latch(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ):
        _diag_coordinator._battery_adapters = {"primary": _make_adapter(unsafe=False, avail=True)}
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)

        deye_block = result["battery_control"]["deye"]
        assert deye_block["available"] is True
        assert deye_block["reason"] == "ok"
        assert deye_block["unsafe_latched"] is False
        assert deye_block["max_charge_current_a"] == 25.0

    @pytest.mark.asyncio
    async def test_unsafe_latched_and_reason_surface(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ):
        # A latched-unsafe scope: capability reports unavailable with the
        # gate reason and the recovery error is visible.
        _diag_coordinator._battery_adapters = {
            "primary": _make_adapter(
                unsafe=True, avail=False, reason="grid-charge switch state unavailable",
                last_error="Deye unsafe latch is set",
            )
        }
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        deye_block = result["battery_control"]["deye"]
        assert deye_block["unsafe_latched"] is True
        assert deye_block["available"] is False
        assert deye_block["reason"] == "grid-charge switch state unavailable"
        assert deye_block["recovery_error"] == "Deye unsafe latch is set"

    @pytest.mark.asyncio
    async def test_observer_and_actuation_gates_are_readonly(self, _diag_hass, _diag_entry, _diag_coordinator):
        _diag_coordinator._battery_adapters = {
            "primary": _make_adapter(),
        }
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        deye_block = result["battery_control"]["deye"]
        assert deye_block["observer_mode"] is False
        assert deye_block["actuation_enabled"] is True

    @pytest.mark.asyncio
    async def test_no_store_leak_in_deye_block(self, _diag_hass, _diag_entry, _diag_coordinator):
        _diag_coordinator._battery_adapters = {
            "primary": _make_adapter(),
        }
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        deye_block = result["battery_control"]["deye"]
        # The runtime store object / any secret must never be emitted.
        json_serialisable = {"available", "reason", "unsafe_latched",
                             "recovery_error", "observer_mode", "actuation_enabled",
                             "max_charge_current_a"}
        assert json_serialisable == set(deye_block.keys())
        assert "deye_snapshot_store" not in deye_block

    @pytest.mark.asyncio
    async def test_no_deye_adapters_omits_block(self, _diag_hass, _diag_entry, _diag_coordinator):
        _diag_coordinator._battery_adapters = {}
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        assert "deye" not in result["battery_control"]
