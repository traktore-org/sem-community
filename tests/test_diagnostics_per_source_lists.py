"""Per-source list capture in the diagnostics dump (#378 triage support).

The diagnostics endpoint previously captured the single cached
``solar_power`` / ``battery_power`` / ``grid_import_power`` entities
but NOT the underlying ``*_power_list`` lists. For multi-inverter /
multi-battery / multi-grid setups, those LISTS are what actually
feed the aggregated value SEM uses — if the user sees an
underreport (e.g. #378's "2 batteries but flow shows only one"),
the triage path requires knowing:

  1. Did the discovery / Energy Dashboard config find all the
     entities the user expects?
  2. Are any of those entities currently reading ``unavailable``
     or ``unknown``?

This file pins the new fields. Triage from a fresh diagnostics
dump becomes: open ``energy_dashboard.per_source_lists.battery_power_list``
and compare against what the user reports they have. If the list
is missing an entity, the bug is in discovery / config — not in
the aggregation. If the list has the entity but
``per_source_readings.battery[<eid>].state`` is ``unavailable``,
the bug is in the sensor source itself.
"""
from __future__ import annotations

from datetime import timedelta
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.diagnostics import (
    async_get_config_entry_diagnostics,
)


# Mirror the fixture set from tests/test_diagnostics.py. Inlined here
# rather than promoted to conftest.py to avoid affecting unrelated
# tests' fixture resolution.
@pytest.fixture
def _diag_mock_hass(tmp_path):
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
    e.entry_id = "test_entry_378"
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
    c.data = {}
    return c


@pytest.mark.asyncio
async def test_per_source_lists_field_present_in_diagnostics(
    _diag_mock_hass, _diag_entry, _diag_coordinator,
) -> None:
    """The new ``per_source_lists`` + ``per_source_readings`` blocks
    must appear under ``energy_dashboard`` when the coordinator has
    an Energy Dashboard config attached. This is the diagnostic
    surface #378-class bug reports need.
    """
    # Build a minimal EnergyDashboardConfig stub with 2 batteries.
    ed = MagicMock()
    ed.has_solar = True
    ed.has_grid = True
    ed.has_battery = True
    ed.has_ev = False
    ed.device_consumption = []
    ed.solar_power = "sensor.solar_total"
    ed.grid_import_power = "sensor.grid"
    ed.battery_power = "sensor.batt_combined"
    ed.solar_power_list = ["sensor.solar_total"]
    ed.battery_power_list = ["sensor.batt_1_power", "sensor.batt_2_power"]
    ed.grid_power_list = ["sensor.grid"]
    ed.solar_energy = "sensor.solar_energy"
    ed.grid_import_energy = "sensor.grid_import_energy"
    ed.grid_export_energy = "sensor.grid_export_energy"
    ed.battery_charge_energy = "sensor.batt_charge_energy"
    ed.battery_discharge_energy = "sensor.batt_discharge_energy"
    ed.derived_power = {}

    _diag_coordinator._energy_dashboard_config = ed
    _diag_entry.runtime_data = _diag_coordinator
    _diag_mock_hass.data = {"solar_energy_management": {_diag_entry.entry_id: _diag_coordinator}}

    # Seed states for the per-battery sensors so per_source_readings
    # has something to surface.
    def fake_state(eid):
        states = {
            "sensor.batt_1_power": MagicMock(
                state="2000",
                attributes={"unit_of_measurement": "W"},
            ),
            "sensor.batt_2_power": MagicMock(
                state="2000",
                attributes={"unit_of_measurement": "W"},
            ),
            "sensor.solar_total": MagicMock(
                state="6000",
                attributes={"unit_of_measurement": "W"},
            ),
            "sensor.grid": MagicMock(
                state="-500",
                attributes={"unit_of_measurement": "W"},
            ),
        }
        return states.get(eid)

    _diag_mock_hass.states.get = MagicMock(side_effect=fake_state)

    result = await async_get_config_entry_diagnostics(_diag_mock_hass, _diag_entry)

    ed_block = result.get("energy_dashboard", {})
    assert "per_source_lists" in ed_block
    assert "per_source_readings" in ed_block

    # Lists round-trip the full per-source set.
    lists = ed_block["per_source_lists"]
    assert lists["battery_power_list"] == [
        "sensor.batt_1_power", "sensor.batt_2_power",
    ]
    assert lists["solar_power_list"] == ["sensor.solar_total"]
    assert lists["grid_power_list"] == ["sensor.grid"]

    # Individual readings are present (the triage payload).
    readings = ed_block["per_source_readings"]
    assert readings["battery"]["sensor.batt_1_power"]["state"] == "2000"
    assert readings["battery"]["sensor.batt_2_power"]["state"] == "2000"
    assert readings["solar"]["sensor.solar_total"]["state"] == "6000"
    assert readings["grid"]["sensor.grid"]["state"] == "-500"


@pytest.mark.asyncio
async def test_missing_entity_surfaces_as_missing_state(
    _diag_mock_hass, _diag_entry, _diag_coordinator,
) -> None:
    """A configured entity that's not in ``hass.states`` surfaces as
    ``{"state": "missing"}`` in the diagnostics dump. This is the
    diagnostic signal for the #378 root cause "discovery found the
    entity at config time, but it's not registering states now"."""
    ed = MagicMock()
    ed.has_solar = True
    ed.has_battery = True
    ed.device_consumption = []
    ed.solar_power = "sensor.solar"
    ed.battery_power = "sensor.batt_combined"
    ed.solar_power_list = ["sensor.solar"]
    ed.battery_power_list = ["sensor.batt_1", "sensor.batt_2_missing"]
    ed.grid_power_list = []
    ed.solar_energy = None
    ed.grid_import_energy = None
    ed.grid_export_energy = None
    ed.battery_charge_energy = None
    ed.battery_discharge_energy = None
    ed.grid_import_power = None
    ed.has_grid = False
    ed.has_ev = False
    ed.derived_power = {}

    _diag_coordinator._energy_dashboard_config = ed
    _diag_entry.runtime_data = _diag_coordinator
    _diag_mock_hass.data = {"solar_energy_management": {_diag_entry.entry_id: _diag_coordinator}}

    _diag_mock_hass.states.get = MagicMock(
        side_effect=lambda eid: MagicMock(
            state="2000", attributes={"unit_of_measurement": "W"},
        ) if eid == "sensor.batt_1" else None
    )

    result = await async_get_config_entry_diagnostics(_diag_mock_hass, _diag_entry)
    readings = result["energy_dashboard"]["per_source_readings"]["battery"]
    assert readings["sensor.batt_1"]["state"] == "2000"
    # The disappeared entity shows up explicitly.
    assert readings["sensor.batt_2_missing"] == {"state": "missing"}
