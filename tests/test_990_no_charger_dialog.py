"""#990 (round 2) — a home with no charger must get through the Configure dialog.

@damiano75: "I haven't any EV charger and in the setup flow I've only the EV
charger configuration, but I can't fill any field, if I click to send button
nothing happens." The options dialog is one chain, and its first page was the
primary charger with three REQUIRED fields. The slim install (#442) made the
charger optional, but the dialog still opened on that page — and Home
Assistant's frontend will not submit a page with a required field left empty.
So the home never reached the tariff, loads, heat pumps (where a second heat
pump is added), battery or notifications.

The guard walks the dialog the way the browser does: it reads the schema Home
Assistant serialises for the frontend, fills in only what the page itself
pre-fills, and fails on any page that still has an empty required field. Any
future page that requires a part a home may not own fails here.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import voluptuous as vol
import voluptuous_serialize
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import config_validation as cv
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.config_flow import (
    OptionsFlowHandler,
    SolarEnergyManagementConfigFlow,
)
from custom_components.solar_energy_management.const import DOMAIN


def _installed_data(**extra) -> dict:
    """What the slim install writes for a home with no charger."""
    return {
        "solar_power_sensor": "sensor.solar_power",
        "grid_power_sensor": "sensor.grid_power",
        "battery_power_sensor": "sensor.battery_power",
        "battery_soc_sensor": "sensor.battery_soc",
        **SolarEnergyManagementConfigFlow._install_defaults(),
        **extra,
    }


def _entry(data: dict, options: dict | None = None) -> MockConfigEntry:
    return MockConfigEntry(domain=DOMAIN, version=12, minor_version=1,
                           data=data, options=options or {}, title="SEM")


def _browser_submit(result: dict, typed: dict | None = None) -> dict:
    """The data Home Assistant's frontend sends for a page.

    Mirrors ``computeInitialHaFormData`` + the submit check: a field starts
    at its suggested value, else its default; ``typed`` is what the user
    entered on top; empty values are not sent; a required field left empty
    blocks the submit ("nothing happens").
    """
    fields = voluptuous_serialize.convert(
        result["data_schema"], custom_serializer=cv.custom_serializer)
    typed = typed or {}
    data = {}
    for field in fields:
        name = field["name"]
        suggested = (field.get("description") or {}).get("suggested_value")
        value = suggested if suggested is not None else field.get("default")
        value = typed.get(name, value)
        if value in (None, ""):
            assert not field.get("required"), (
                f"page {result['step_id']!r} requires {name!r} and pre-fills "
                f"nothing — the browser will not submit it (#990)"
            )
            continue
        data[name] = value
    return data


async def _walk(hass, entry, answers: dict | None = None) -> tuple[list[str], dict]:
    """Walk the dialog to its end. ``answers`` maps a step to what the user
    types on each visit, in order; every other visit takes the page as
    shown (menus: Continue)."""
    answers = {k: list(v) for k, v in (answers or {}).items()}
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    seen: list[str] = []
    for _ in range(40):
        if result["type"] != FlowResultType.FORM:
            return seen, result
        assert not result.get("errors"), (result["step_id"], result["errors"])
        step = result["step_id"]
        seen.append(step)
        typed = answers[step].pop(0) if answers.get(step) else None
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=_browser_submit(result, typed))
    raise AssertionError(f"dialog never ended: {seen}")


@pytest.fixture
def _quiet_discovery():
    """No charger, no inverter on this box — discovery finds nothing."""
    with patch(
        "custom_components.solar_energy_management.hardware_detection."
        "discover_all_ev_chargers_from_registry", return_value=[],
    ):
        yield


@pytest.mark.asyncio
async def test_a_home_without_a_charger_walks_the_whole_dialog(
        sem_real_hass, _quiet_discovery):
    """The reporter's case: no charger, the dialog must reach the end."""
    seen, result = await _walk(sem_real_hass, _entry(_installed_data()))
    assert seen[0] == "ev_charger_menu"
    assert "ev_charger" not in seen
    assert "heat_pump_menu" in seen, seen   # where a second heat pump is added
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ev_chargers"] == []
    assert not result["data"].get("ev_charging_power_sensor")


@pytest.mark.asyncio
async def test_a_home_without_a_charger_adds_a_heat_pump_and_a_charger(
        sem_real_hass, _quiet_discovery):
    """What the reporter came for: the second heat pump. And the first
    charger, from the menu the dialog now opens on."""
    seen, result = await _walk(sem_real_hass, _entry(_installed_data()), {
        "ev_charger_menu": [{"action": "add_charger"}],
        "ev_charger_add": [{
            "charger_name": "Garage",
            "ev_connected_sensor": "binary_sensor.garage_plug",
            "ev_charging_sensor": "binary_sensor.garage_charging",
            "ev_charging_power_sensor": "sensor.garage_power"}],
        "heat_pump_menu": [{"action": "add_heat_pump"}],
        "heat_pump_unit": [{"heat_pump_climate_entity": "climate.pool"}],
    })
    assert seen.count("ev_charger_menu") == 2, seen
    assert "heat_pump_unit" in seen, seen
    assert result["type"] == FlowResultType.CREATE_ENTRY
    saved = result["data"]
    assert [c["id"] for c in saved["ev_chargers"]] == ["ev_charger_0"]
    assert saved["ev_chargers"][0]["ev_charging_power_sensor"] == "sensor.garage_power"
    assert [p.get("heat_pump_climate_entity") for p in saved["heat_pumps"]] == [
        "climate.pool"]


@pytest.mark.asyncio
async def test_a_saved_none_on_the_skipped_page_does_not_break_adding(
        sem_real_hass, _quiet_discovery):
    """The skipped page's saved values are kept apart from the draft: the add
    page reads the draft for its defaults, and ``None`` is not one (#73)."""
    seen, result = await _walk(
        sem_real_hass, _entry(_installed_data(), {"ev_target_soc": None}), {
            "ev_charger_menu": [{"action": "add_charger"}],
            "ev_charger_add": [{
                "ev_connected_sensor": "binary_sensor.plug",
                "ev_charging_sensor": "binary_sensor.charging",
                "ev_charging_power_sensor": "sensor.ev_power"}],
        })
    assert "ev_charger_add" in seen
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"]["ev_target_soc"] is None     # kept as saved


@pytest.mark.asyncio
async def test_a_home_with_a_charger_still_opens_on_its_page(
        sem_real_hass, _quiet_discovery):
    entry = _entry(_installed_data(ev_chargers=[{
        "id": "ev_charger", "name": "Box",
        "ev_connected_sensor": "binary_sensor.plug",
        "ev_charging_sensor": "binary_sensor.charging",
        "ev_charging_power_sensor": "sensor.ev_power"}]))
    seen, result = await _walk(sem_real_hass, entry)
    assert seen[0] == "ev_charger"
    assert result["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.asyncio
async def test_a_flat_key_charger_still_opens_on_its_page(
        sem_real_hass, _quiet_discovery):
    """Older installs hold the charger in flat keys, with no list."""
    data = _installed_data(ev_charging_power_sensor="sensor.ev_power",
                           ev_connected_sensor="binary_sensor.plug",
                           ev_charging_sensor="binary_sensor.charging")
    data.pop("ev_chargers")
    entry = _entry(data)
    entry.add_to_hass(sem_real_hass)
    result = await sem_real_hass.config_entries.options.async_init(entry.entry_id)
    assert result["step_id"] == "ev_charger"


@pytest.mark.asyncio
async def test_the_skipped_page_changes_nothing_saved(
        sem_real_hass, _quiet_discovery):
    """Options replace wholesale on save (#690). A key the skipped page owns
    must not drop out and let ``entry.data``'s old charger show through."""
    data = _installed_data(
        ev_charging_power_sensor="sensor.old_ev_power",
        ev_chargers=[{"id": "ev_charger", "ev_charging_power_sensor": "sensor.old"}])
    options = {"ev_charging_power_sensor": None, "ev_chargers": [],
               "ev_target_soc": 70}
    seen, result = await _walk(sem_real_hass, _entry(data, options))
    assert seen[0] == "ev_charger_menu"
    saved = result["data"]
    assert saved["ev_chargers"] == []
    assert "ev_charging_power_sensor" in saved
    assert saved["ev_charging_power_sensor"] is None
    assert saved["ev_target_soc"] == 70


# ── the menu's first-charger label ───────────────────────────────────

def _menu_labels(form) -> dict:
    return {o["value"]: o["label"]
            for o in form["data_schema"].schema["action"].config["options"]}


def _flow(data: dict, options: dict | None = None) -> OptionsFlowHandler:
    flow = OptionsFlowHandler.__new__(OptionsFlowHandler)
    flow._data = {}
    flow.hass = MagicMock(config=None, data={})
    entry = MagicMock(data=data, options=options or {}, entry_id="e1")
    type(flow).config_entry = property(lambda self: entry)
    return flow


@pytest.mark.asyncio
async def test_the_first_charger_is_not_another():
    flow = _flow(_installed_data())
    try:
        form = await flow.async_step_init()
        assert form["step_id"] == "ev_charger_menu"
        assert _menu_labels(form)["add_charger"] == "Add an EV charger"
        flow._data["ev_chargers"] = [{"id": "ev_charger_0", "name": "Box"}]
        form = await flow.async_step_ev_charger_menu()
        assert _menu_labels(form)["add_charger"] == "Add another EV charger"
    finally:
        del type(flow).config_entry


def test_every_language_has_the_first_charger_label():
    import json
    from pathlib import Path
    path = Path(__file__).resolve().parent.parent / "dashboard" / "translations.json"
    table = json.loads(path.read_text(encoding="utf-8"))
    missing = [lang for lang, words in table.items()
               if not words.get("flow_add_first_charger")]
    assert not missing


# ── the sibling: the Reconfigure page had the same three required fields ──

def _required(form) -> set[str]:
    return {str(k) for k in form["data_schema"].schema
            if isinstance(k, vol.Required)}


async def _reconfigure(hass, entry, typed: dict | None = None):
    entry.add_to_hass(hass)
    form = await entry.start_reconfigure_flow(hass)
    assert form["step_id"] == "reconfigure"
    with patch.object(hass.config_entries, "async_schedule_reload"):
        done = await hass.config_entries.flow.async_configure(
            form["flow_id"], user_input=_browser_submit(form, typed))
    return form, done


@pytest.mark.asyncio
async def test_reconfigure_without_a_charger_can_be_saved(sem_real_hass):
    entry = _entry(_installed_data())
    form, done = await _reconfigure(sem_real_hass, entry)
    assert not _required(form) & {"ev_connected_sensor", "ev_charging_sensor",
                                  "ev_charging_power_sensor"}
    assert done["type"] == FlowResultType.ABORT
    assert done["reason"] == "reconfigure_successful"
    assert not entry.data.get("ev_charging_power_sensor")


@pytest.mark.asyncio
async def test_reconfigure_with_a_list_charger_shows_its_sensors(sem_real_hass):
    """A charger kept only in the list (what "Add an EV charger" makes) has
    no flat keys; its required fields must still come up filled."""
    entry = _entry(_installed_data(ev_chargers=[{
        "id": "ev_charger_0", "name": "Box",
        "ev_connected_sensor": "binary_sensor.plug",
        "ev_charging_sensor": "binary_sensor.charging",
        "ev_charging_power_sensor": "sensor.ev_power"}]))
    sem_real_hass.states.async_set("binary_sensor.plug", "off")
    sem_real_hass.states.async_set("binary_sensor.charging", "off")
    sem_real_hass.states.async_set("sensor.ev_power", "0",
                                   {"unit_of_measurement": "W"})
    form, done = await _reconfigure(sem_real_hass, entry)
    assert _required(form) >= {"ev_connected_sensor", "ev_charging_sensor",
                               "ev_charging_power_sensor"}
    assert done["type"] == FlowResultType.ABORT, done.get("errors")


@pytest.mark.asyncio
async def test_reconfigure_half_a_charger_is_still_checked(sem_real_hass):
    """Once the user starts filling the three in, all three are checked."""
    entry = _entry(_installed_data())
    with patch.object(sem_real_hass.config_entries, "async_schedule_reload"):
        _, done = await _reconfigure(
            sem_real_hass, entry, {"ev_charging_power_sensor": "sensor.ev_power"})
    assert done["type"] == FlowResultType.FORM
    assert {"ev_connected_sensor", "ev_charging_sensor"} <= set(done["errors"])
    assert not entry.data.get("ev_charging_power_sensor")


# ── the sibling of round 1: charger ids came from the list position ──

@pytest.mark.asyncio
async def test_adding_after_a_remove_never_reuses_a_charger_id():
    """Remove charger 2 of 3, add one: ``ev_charger_{len}`` was the id the
    third charger already had — two chargers, one device id."""
    flow = _flow(_installed_data())
    flow._discovered_pv_strings = lambda: {}
    flow._data["ev_chargers"] = [
        {"id": "ev_charger", "name": "A"},
        {"id": "ev_charger_1", "name": "B"},
        {"id": "ev_charger_2", "name": "C"}]
    try:
        await flow.async_step_ev_charger_remove({"charger_to_remove": "ev_charger_1"})
        await flow.async_step_ev_charger_add({
            "charger_name": "D",
            "ev_connected_sensor": "binary_sensor.d_plug",
            "ev_charging_sensor": "binary_sensor.d_charging",
            "ev_charging_power_sensor": "sensor.d_power"})
        ids = [c["id"] for c in flow._data["ev_chargers"]]
        assert ids == ["ev_charger", "ev_charger_2", "ev_charger_3"]
    finally:
        del type(flow).config_entry


@pytest.mark.asyncio
async def test_a_growing_list_keeps_the_old_ids():
    flow = _flow(_installed_data())
    flow._discovered_pv_strings = lambda: {}
    flow._data["ev_chargers"] = []
    try:
        for name in ("A", "B"):
            await flow.async_step_ev_charger_add({
                "charger_name": name,
                "ev_connected_sensor": f"binary_sensor.{name}_plug",
                "ev_charging_sensor": f"binary_sensor.{name}_charging",
                "ev_charging_power_sensor": f"sensor.{name}_power"})
        assert [c["id"] for c in flow._data["ev_chargers"]] == [
            "ev_charger_0", "ev_charger_1"]
    finally:
        del type(flow).config_entry


@pytest.mark.asyncio
async def test_a_box_removed_in_this_dialog_does_not_hand_on_its_id():
    """Remove the last of three saved chargers, add one: the new box must
    not take ``ev_charger_2`` — that id's entities and stored state belong
    to the box just removed."""
    saved = [{"id": "ev_charger", "name": "A"},
             {"id": "ev_charger_1", "name": "B"},
             {"id": "ev_charger_2", "name": "C"}]
    flow = _flow(_installed_data(), {"ev_chargers": saved})
    flow._discovered_pv_strings = lambda: {}
    flow._data["ev_chargers"] = [dict(c) for c in saved]
    try:
        await flow.async_step_ev_charger_remove({"charger_to_remove": "ev_charger_2"})
        await flow.async_step_ev_charger_add({
            "charger_name": "D",
            "ev_connected_sensor": "binary_sensor.d_plug",
            "ev_charging_sensor": "binary_sensor.d_charging",
            "ev_charging_power_sensor": "sensor.d_power"})
        ids = [c["id"] for c in flow._data["ev_chargers"]]
        assert ids == ["ev_charger", "ev_charger_1", "ev_charger_3"]
    finally:
        del type(flow).config_entry
