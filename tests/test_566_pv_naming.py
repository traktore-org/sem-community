"""#566 — custom PV-string display names (East/South/West …)."""
import pytest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from homeassistant.components.sensor import SensorEntityDescription

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.sensor import SEMSolarSensor
from custom_components.solar_energy_management.config_flow import OptionsFlowHandler
from custom_components.solar_energy_management.const import DOMAIN


# ---------------------------------------------------------------------------
# Reader: names + display helper
# ---------------------------------------------------------------------------

def _reader():
    return SensorReader(MagicMock(), {})


def test_set_names_filters_blanks():
    r = _reader()
    r.set_pv_string_names({"pv1": "East", "pv2": "  ", "pv3": "", "pv4": None})
    assert r._pv_string_names == {"pv1": "East"}


def test_display_name_custom_else_compact():
    r = _reader()
    r.set_pv_string_names({"pv1": "East"})
    assert r.pv_string_display_name("pv1") == "East"
    assert r.pv_string_display_name("pv2") == "PV2"   # unnamed → compact default
    assert r.pv_string_display_name("pv3") == "PV3"


def test_set_names_none_clears():
    r = _reader()
    r.set_pv_string_names({"pv1": "East"})
    r.set_pv_string_names(None)
    assert r._pv_string_names == {}
    assert r.pv_string_display_name("pv1") == "PV1"


# ---------------------------------------------------------------------------
# Sensor: string_name attribute
# ---------------------------------------------------------------------------

def _pv_sensor(mock_coordinator, key, names):
    reader = _reader()
    reader.set_pv_string_names(names)
    mock_coordinator._sensor_reader = reader
    mock_coordinator.data = {"last_update": "x"}
    desc = SensorEntityDescription(key=key, name="x")
    return SEMSolarSensor(coordinator=mock_coordinator, description=desc,
                          entry_id="e")


def test_power_sensor_exposes_custom_string_name(mock_coordinator):
    s = _pv_sensor(mock_coordinator, "pv_string_pv1_power", {"pv1": "East"})
    assert s.extra_state_attributes["string_name"] == "East"


def test_energy_sensor_exposes_string_name(mock_coordinator):
    s = _pv_sensor(mock_coordinator, "pv_string_pv2_daily_energy", {"pv1": "East"})
    # pv2 unnamed → compact default
    assert s.extra_state_attributes["string_name"] == "PV2"


def test_non_pv_sensor_has_no_string_name(mock_coordinator):
    s = _pv_sensor(mock_coordinator, "solar_power", {"pv1": "East"})
    assert "string_name" not in s.extra_state_attributes


# ---------------------------------------------------------------------------
# Options flow step
# ---------------------------------------------------------------------------

def _flow_with_strings(mock_hass, config_entry, pv_strings, saved=None):
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    flow._data = {}
    reader = SimpleNamespace(_pv_strings=dict(pv_strings))
    coord = SimpleNamespace(_sensor_reader=reader)
    mock_hass.data = {DOMAIN: {config_entry.entry_id: coord}}
    config_entry.data = {}
    config_entry.options = {"pv_string_names": saved or {}}
    return flow


@pytest.mark.asyncio
async def test_pv_naming_shows_form_when_2_plus(mock_hass, config_entry):
    flow = _flow_with_strings(
        mock_hass, config_entry,
        {"pv1": "sensor.inv_pv1_power", "pv2": "sensor.inv_pv2_power"},
    )
    mock_hass.states.get = lambda e: SimpleNamespace(state="3200")
    with patch.object(type(flow), "config_entry", config_entry):
        res = await flow.async_step_pv_naming()
    assert res["type"] == "form"
    assert res["step_id"] == "pv_naming"


@pytest.mark.asyncio
async def test_pv_naming_skips_when_under_2(mock_hass, config_entry):
    flow = _flow_with_strings(mock_hass, config_entry, {"pv1": "sensor.only"})
    with patch.object(type(flow), "config_entry", config_entry):
        with patch.object(OptionsFlowHandler, "async_step_notifications",
                          return_value={"type": "form", "step_id": "notifications"}) as nxt:
            res = await flow.async_step_pv_naming()
    nxt.assert_called_once()
    assert res["step_id"] == "notifications"


@pytest.mark.asyncio
async def test_skip_path_preserves_saved_names(mock_hass, config_entry):
    """<2 strings must NOT wipe previously-saved names (async_create_entry
    replaces the whole options dict)."""
    flow = _flow_with_strings(
        mock_hass, config_entry, {"pv1": "sensor.only"},
        saved={"pv1": "East", "pv2": "West"},
    )
    with patch.object(type(flow), "config_entry", config_entry):
        with patch.object(OptionsFlowHandler, "async_step_notifications",
                          return_value={"type": "form", "step_id": "notifications"}):
            await flow.async_step_pv_naming()
    assert flow._data["pv_string_names"] == {"pv1": "East", "pv2": "West"}


@pytest.mark.asyncio
async def test_pv_naming_stores_names_on_submit(mock_hass, config_entry):
    flow = _flow_with_strings(
        mock_hass, config_entry,
        {"pv1": "sensor.inv_pv1_power", "pv2": "sensor.inv_pv2_power"},
    )
    with patch.object(type(flow), "config_entry", config_entry):
        with patch.object(OptionsFlowHandler, "async_step_notifications",
                          return_value={"type": "form", "step_id": "notifications"}):
            await flow.async_step_pv_naming(
                user_input={"pv_name_pv1": "East", "pv_name_pv2": "  "}
            )
    # East kept, blank dropped
    assert flow._data["pv_string_names"] == {"pv1": "East"}


# ---------------------------------------------------------------------------
# #566 follow-up — discoverable "Rename PV strings" charger-menu shortcut
# ---------------------------------------------------------------------------

def _menu_option_values(res):
    """Pull the action-selector option values out of a shown menu form."""
    schema = res["data_schema"].schema
    for _key, sel in schema.items():
        cfg = getattr(sel, "config", None)
        if cfg and "options" in cfg:
            return [o["value"] for o in cfg["options"]]
    return []


@pytest.mark.asyncio
async def test_menu_offers_rename_when_2_plus(mock_hass, config_entry):
    flow = _flow_with_strings(mock_hass, config_entry, {"pv1": "a", "pv2": "b"})
    with patch.object(type(flow), "config_entry", config_entry):
        res = await flow.async_step_ev_charger_menu()
    assert "rename_pv" in _menu_option_values(res)


@pytest.mark.asyncio
async def test_menu_hides_rename_when_under_2(mock_hass, config_entry):
    flow = _flow_with_strings(mock_hass, config_entry, {"pv1": "a"})
    with patch.object(type(flow), "config_entry", config_entry):
        res = await flow.async_step_ev_charger_menu()
    assert "rename_pv" not in _menu_option_values(res)


@pytest.mark.asyncio
async def test_menu_rename_routes_straight_to_pv_naming(mock_hass, config_entry):
    flow = _flow_with_strings(mock_hass, config_entry, {"pv1": "a", "pv2": "b"})
    mock_hass.states.get = lambda e: SimpleNamespace(state="100")
    with patch.object(type(flow), "config_entry", config_entry):
        res = await flow.async_step_ev_charger_menu(user_input={"action": "rename_pv"})
    assert res["step_id"] == "pv_naming"
    assert flow._pv_naming_return == "menu"


@pytest.mark.asyncio
async def test_shortcut_finalize_preserves_other_options(mock_hass, config_entry):
    """The menu shortcut must save names WITHOUT wiping the rest of the
    options (it skips the settings forms, so it merges onto existing options
    instead of replacing with the partial self._data)."""
    flow = _flow_with_strings(mock_hass, config_entry, {"pv1": "a", "pv2": "b"})
    config_entry.options = {"target_peak_limit": 7.0, "battery_buffer_soc": 55,
                            "pv_string_names": {}}
    flow._pv_naming_return = "menu"
    captured = {}
    with patch.object(type(flow), "config_entry", config_entry):
        with patch.object(flow, "async_create_entry",
                          side_effect=lambda data: captured.update(data=data)
                          or {"type": "create_entry", "data": data}):
            res = await flow.async_step_pv_naming(
                user_input={"pv_name_pv1": "East", "pv_name_pv2": ""})
    assert res["type"] == "create_entry"
    saved = captured["data"]
    # existing options preserved, only the names updated
    assert saved["target_peak_limit"] == 7.0
    assert saved["battery_buffer_soc"] == 55
    assert saved["pv_string_names"] == {"pv1": "East"}
