"""#685 — several heat pumps, each its own SurplusController device.

The flat ``heat_pump_*`` keys stay the PRIMARY unit (device_id
"heat_pump" — every existing reader untouched); additional units live in
the ``heat_pumps`` list with the same key names. Rows without a control
path (both relays / climate / #801 service) are skipped, mirroring the
single-unit #437 gate.
"""
from __future__ import annotations

from types import MethodType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management import (
    _heat_pump_row_controllable,
    _heat_pump_rows,
)


# ── row building ────────────────────────────────────────────────────

def test_flat_keys_stay_the_primary_unit():
    rows = _heat_pump_rows({
        "heat_pump_relay1_entity": "switch.r1",
        "heat_pump_relay2_entity": "switch.r2",
        "heat_pump_priority": 3,
    })
    assert len(rows) == 1
    assert rows[0]["id"] == "heat_pump"          # compat: never renamed
    assert rows[0]["heat_pump_priority"] == 3


def test_list_units_follow_with_their_own_ids():
    rows = _heat_pump_rows({
        "heat_pump_climate_entity": "climate.main",
        "heat_pumps": [
            {"name": "Cellar", "heat_pump_climate_entity": "climate.cellar"},
            {"id": "hp_attic", "heat_pump_sg_ready_service": "ems_esp.send_command"},
        ],
    })
    assert [r["id"] for r in rows] == ["heat_pump", "heat_pump_2", "hp_attic"]
    assert rows[1]["name"] == "Cellar"
    assert rows[2]["name"] == "Heat Pump 3"      # synthesized


def test_garbage_list_entries_are_ignored():
    rows = _heat_pump_rows({"heat_pumps": ["nope", None, 42]})
    assert len(rows) == 1                        # only the (empty) primary


# ── the control-path gate ───────────────────────────────────────────

@pytest.mark.parametrize("row,ok", [
    ({"heat_pump_relay1_entity": "switch.a", "heat_pump_relay2_entity": "switch.b"}, True),
    ({"heat_pump_climate_entity": "climate.x"}, True),
    ({"heat_pump_sg_ready_service": "ems_esp.send_command"}, True),   # #801
    ({"heat_pump_relay1_entity": "switch.a"}, False),                 # partial
    ({"heat_pump_sg_ready_service": "   "}, False),                   # blank
    ({}, False),
])
def test_a_row_needs_a_control_path(row, ok):
    assert _heat_pump_row_controllable(row) is ok


# ── the flow: unit editor + menu (real methods, stub self) ──────────

def _flow_self(data=None, options=None):
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    stub = SimpleNamespace(
        _data=dict(data or {}),
        config_entry=SimpleNamespace(data={}, options=dict(options or {})),
        _edit_hp_index=None,
        shown=None,
    )
    def async_show_form(self, **kw):
        self.shown = kw
        return {"type": "form", **kw}
    stub.async_show_form = MethodType(async_show_form, stub)
    for name in ("async_step_heat_pump_menu", "async_step_heat_pump_unit"):
        setattr(stub, name, MethodType(getattr(OptionsFlowHandler, name), stub))
    stub.async_step_battery_scheduler = AsyncMock(return_value={"type": "next"})
    return stub


@pytest.mark.asyncio
async def test_unit_editor_rejects_a_row_with_no_control_path():
    f = _flow_self()
    result = await f.async_step_heat_pump_unit({"name": "Cellar"})
    assert result["errors"] == {"base": "heat_pump_no_control"}


@pytest.mark.asyncio
async def test_unit_editor_rejects_bad_service_and_bad_json():
    f = _flow_self()
    r1 = await f.async_step_heat_pump_unit(
        {"heat_pump_sg_ready_service": "not-a-service"})
    assert r1["errors"] == {"base": "heat_pump_service_invalid"}
    r2 = await f.async_step_heat_pump_unit(
        {"heat_pump_sg_ready_service": "ems_esp.send_command",
         "heat_pump_sg_ready_service_data": "{broken"})
    assert r2["errors"] == {"base": "heat_pump_service_data_invalid"}


@pytest.mark.asyncio
async def test_unit_editor_appends_then_edits_in_place():
    f = _flow_self()
    await f.async_step_heat_pump_unit(
        {"heat_pump_climate_entity": "climate.cellar"})
    assert f._data["heat_pumps"][0]["id"] == "heat_pump_2"
    f._edit_hp_index = 0
    await f.async_step_heat_pump_unit(
        {"name": "Cellar", "heat_pump_climate_entity": "climate.cellar2"})
    pumps = f._data["heat_pumps"]
    assert len(pumps) == 1                       # edited, not appended
    assert pumps[0]["heat_pump_climate_entity"] == "climate.cellar2"
    assert pumps[0]["id"] == "heat_pump_2"       # id survives the edit


@pytest.mark.asyncio
async def test_menu_lists_edit_and_remove_per_unit():
    f = _flow_self(options={"heat_pumps": [
        {"id": "heat_pump_2", "name": "Cellar",
         "heat_pump_climate_entity": "climate.c"}]})
    form = await f.async_step_heat_pump_menu(None)
    values = [o["value"] for o in
              form["data_schema"].schema["action"].config["options"]]
    assert values == ["continue", "edit_heat_pump:0",
                      "remove_heat_pump:0", "add_heat_pump"]


@pytest.mark.asyncio
async def test_menu_remove_then_continue():
    f = _flow_self(data={"heat_pumps": [
        {"id": "heat_pump_2", "heat_pump_climate_entity": "climate.c"}]})
    await f.async_step_heat_pump_menu({"action": "remove_heat_pump:0"})
    assert f._data["heat_pumps"] == []
    result = await f.async_step_heat_pump_menu({"action": "continue"})
    assert result == {"type": "next"}            # forwards to battery_scheduler


# ── registered controllers carry the row values (#801 included) ─────

def test_rows_construct_distinct_controllers():
    from custom_components.solar_energy_management.devices.heat_pump_controller import (
        HeatPumpController,
    )
    hass = MagicMock(); hass.services.async_call = AsyncMock()
    rows = _heat_pump_rows({
        "heat_pump_relay1_entity": "switch.r1",
        "heat_pump_relay2_entity": "switch.r2",
        "heat_pumps": [{
            "heat_pump_sg_ready_service": "ems_esp.send_command",
            "heat_pump_priority": 6,
        }],
    })
    built = [
        HeatPumpController(
            hass=hass, device_id=r["id"], name=r["name"],
            priority=int(r.get("heat_pump_priority", 4)),
            relay1_entity_id=r.get("heat_pump_relay1_entity"),
            relay2_entity_id=r.get("heat_pump_relay2_entity"),
            sg_ready_service=r.get("heat_pump_sg_ready_service"),
        )
        for r in rows if _heat_pump_row_controllable(r)
    ]
    assert [d.device_id for d in built] == ["heat_pump", "heat_pump_2"]
    assert built[1].sg_ready_service == "ems_esp.send_command"
    assert built[1].priority == 6
