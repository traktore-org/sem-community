"""#1258 — Reconfigure for a charger kept in the charger list.

The page asked for three required EV sensors in flat keys that a list-format
charger does not have, with no way to fill them and no word why. Saving them
would split the charger in two. The three are left off and the page says
where the charger is set up.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management.utils.translate import get_text

from .schema_fields import field_list
from .test_990_no_charger_dialog import _browser_submit, _entry, _installed_data

NOTE_KEY = "flow_charger_in_configure"
TRIO = ("ev_connected_sensor", "ev_charging_sensor", "ev_charging_power_sensor")
LISTED = {"id": "wb1", "name": "Garage", "ev_connected_sensor": "binary_sensor.a",
          "ev_charging_sensor": "binary_sensor.b",
          "ev_charging_power_sensor": "sensor.c"}


def _names(form):
    return {f["name"]: f for f in field_list(form["data_schema"])}


async def _form(hass, data):
    entry = _entry(data)
    entry.add_to_hass(hass)
    return entry, await entry.start_reconfigure_flow(hass)


@pytest.mark.asyncio
async def test_a_listed_charger_is_not_asked_for_the_flat_trio(sem_real_hass):
    _, form = await _form(sem_real_hass, _installed_data(ev_chargers=[LISTED]))
    fields = _names(form)
    assert not set(TRIO) & set(fields)
    assert not [n for n, f in fields.items() if f.get("required")]


@pytest.mark.asyncio
async def test_the_page_says_where_the_charger_is_set_up(sem_real_hass):
    _, form = await _form(sem_real_hass, _installed_data(ev_chargers=[LISTED]))
    note = get_text(sem_real_hass, NOTE_KEY, "")
    assert note
    assert form["description_placeholders"]["charger_note"].strip() == note.strip()


@pytest.mark.asyncio
async def test_a_listed_charger_saves_and_stays_whole(sem_real_hass):
    entry, form = await _form(sem_real_hass, _installed_data(ev_chargers=[LISTED]))
    with patch.object(sem_real_hass.config_entries, "async_schedule_reload"):
        done = await sem_real_hass.config_entries.flow.async_configure(
            form["flow_id"], user_input=_browser_submit(form, {}))
    assert done["type"] == FlowResultType.ABORT
    saved = {**entry.data, **entry.options}
    assert not [k for k in TRIO if saved.get(k)]
    assert saved["ev_chargers"] == [LISTED]


@pytest.mark.asyncio
async def test_a_flat_charger_keeps_its_required_trio_and_no_note(sem_real_hass):
    flat = {"ev_connected_sensor": "binary_sensor.a",
            "ev_charging_sensor": "binary_sensor.b",
            "ev_charging_power_sensor": "sensor.c"}
    _, form = await _form(sem_real_hass, _installed_data(**flat))
    fields = _names(form)
    assert all(fields[k].get("required") for k in TRIO)
    assert not form["description_placeholders"]["charger_note"]


@pytest.mark.asyncio
async def test_a_home_without_a_charger_is_as_before(sem_real_hass):
    _, form = await _form(sem_real_hass, _installed_data())
    fields = _names(form)
    assert set(TRIO) <= set(fields)
    assert not [k for k in TRIO if fields[k].get("required")]
    assert not form["description_placeholders"]["charger_note"]
