"""Pin the ``pv_strings_discovery`` diagnostics surface (#379 triage).

The diagnostics dump's new ``pv_strings_discovery`` top-level block
(shipped in v1.7.0-beta.6) captures the result of
``_sensor_reader._pv_strings`` (direct power) and
``_pv_vi_pairs`` (V+I synthesis). When a user reports "PV2 is
empty" (#379), this block is the triage signal:

  * empty dict → discovery missed entirely; entity-naming pattern
    not in ``hardware_detection._PV_STRING_PATTERNS``; needs
    a new pattern
  * partial dict → some strings matched, some didn't; either
    user-disabled some entities OR mixed naming patterns
  * full dict → discovery worked; bug is downstream in the
    dashboard card rendering

The companion test_diagnostics_per_source_lists.py covers the
battery / solar / grid per-source lists (different bug class).
This file covers the per-string discovery (the #379-class).

Same fixture shape as test_357_wallbox_diagnostics.py — local
fixture set, not promoted to conftest.py.
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
    e.entry_id = "test_entry_379"
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
    c._ev_devices = None
    c.data = {}
    return c


class Test379PVStringsDiscovery:
    """The new ``pv_strings_discovery`` block under the top-level
    diagnostics dump captures both discovery flavours."""

    @pytest.mark.asyncio
    async def test_direct_power_strings_discovered(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """Multi-inverter setup with per-string power sensors
        directly available — the classic Growatt / Huawei case."""
        reader = MagicMock()
        reader._pv_strings = {
            "pv1_power": "sensor.inverter_pv1_power",
            "pv2_power": "sensor.inverter_pv2_power",
        }
        reader._pv_vi_pairs = {}
        reader._split_grid_discovery = None
        _diag_coordinator._sensor_reader = reader
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)

        info = result.get("pv_strings_discovery", {})
        assert "discovered_direct" in info
        assert "discovered_vi_pairs" in info
        assert info["discovered_direct"] == {
            "pv1_power": "sensor.inverter_pv1_power",
            "pv2_power": "sensor.inverter_pv2_power",
        }
        assert info["discovered_vi_pairs"] == {}

    @pytest.mark.asyncio
    async def test_vi_synthesis_pairs_surface_as_lists(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """Huawei Solar Modbus + similar brands expose V + I per string
        but no power sensor. Diagnostics surfaces the discovered
        V+I tuples as lists (JSON-friendly)."""
        reader = MagicMock()
        reader._pv_strings = {}
        reader._pv_vi_pairs = {
            "pv1": ("sensor.inverter_pv1_voltage", "sensor.inverter_pv1_current"),
            "pv2": ("sensor.inverter_pv2_voltage", "sensor.inverter_pv2_current"),
        }
        reader._split_grid_discovery = None
        _diag_coordinator._sensor_reader = reader
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)

        vi = result["pv_strings_discovery"]["discovered_vi_pairs"]
        # Tuples become lists in the dump (JSON safety).
        assert vi == {
            "pv1": ["sensor.inverter_pv1_voltage", "sensor.inverter_pv1_current"],
            "pv2": ["sensor.inverter_pv2_voltage", "sensor.inverter_pv2_current"],
        }

    @pytest.mark.asyncio
    async def test_empty_discovery_surfaces_explicitly(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """The #379 triage signal: discovery returned NOTHING. Both
        dicts surface as ``{}`` so the user reporting "PV2 is empty"
        sees immediately that the naming pattern isn't matching
        anything in their HA registry."""
        reader = MagicMock()
        reader._pv_strings = {}
        reader._pv_vi_pairs = {}
        reader._split_grid_discovery = None
        _diag_coordinator._sensor_reader = reader
        _diag_entry.runtime_data = _diag_coordinator
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)

        info = result["pv_strings_discovery"]
        assert info["discovered_direct"] == {}
        assert info["discovered_vi_pairs"] == {}

    @pytest.mark.asyncio
    async def test_no_sensor_reader_surfaces_as_empty_block(
        self, _diag_hass, _diag_entry, _diag_coordinator,
    ) -> None:
        """If no SensorReader is attached (test stub / unusual setup),
        the diagnostics block surfaces as ``{}`` rather than crashing
        or being missing."""
        _diag_coordinator._sensor_reader = None
        _diag_entry.runtime_data = _diag_coordinator
        _diag_hass.data = {
            "solar_energy_management": {_diag_entry.entry_id: _diag_coordinator},
        }

        result = await async_get_config_entry_diagnostics(_diag_hass, _diag_entry)
        assert result["pv_strings_discovery"] == {}
