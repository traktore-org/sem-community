"""#1386 — a charger can be renamed from the Devices screen.

The card writes ``set_option {ev_chargers: [{id, name}]}``. The merge keys on
the id, so on a two-charger home only the named charger changes. The reload
that follows shows the new name on the charger's sensors; no entity id moves.
"""
from __future__ import annotations

import pytest
from homeassistant.helpers import entity_registry as er

from custom_components.solar_energy_management.const import DOMAIN

from .test_services_real import _seed_sem_input_sensors, _setup_sem


def _seed_two_wallboxes(hass) -> None:
    _seed_sem_input_sensors(hass)
    for side in ("left", "right"):
        hass.states.async_set(f"sensor.test_wb_{side}_charging_power", "0", {"unit_of_measurement": "W"})
        hass.states.async_set(f"number.test_wb_{side}_max_current", "0", {"unit_of_measurement": "A"})
        hass.states.async_set(f"binary_sensor.test_wb_{side}_cable_connected", "off")
        hass.states.async_set(f"sensor.test_wb_{side}_status", "idle")


def _rename(hass, cid: str, name: str):
    return hass.services.async_call(
        DOMAIN, "set_option",
        {"options": {"ev_chargers": [{"id": cid, "name": name}]}}, blocking=True)


@pytest.mark.asyncio
async def test_rename_writes_that_chargers_name_only(
    sem_real_hass, sem_multi_wallbox_config_entry,
) -> None:
    _seed_two_wallboxes(sem_real_hass)
    entry = sem_multi_wallbox_config_entry
    await _setup_sem(sem_real_hass, entry)
    before = {c["id"]: dict(c) for c in entry.options["ev_chargers"]}
    ids_before = {e.entity_id for e in er.async_entries_for_config_entry(
        er.async_get(sem_real_hass), entry.entry_id)}

    await _rename(sem_real_hass, "ev_charger_1", "  Garage   right ")
    await sem_real_hass.async_block_till_done()

    after = {c["id"]: c for c in entry.options["ev_chargers"]}
    assert after["ev_charger_1"]["name"] == "Garage right"
    assert after["ev_charger"].get("name") == before["ev_charger"].get("name")
    assert {k: v for k, v in after["ev_charger_1"].items() if k != "name"} == \
        {k: v for k, v in before["ev_charger_1"].items() if k != "name"}
    ids_after = {e.entity_id for e in er.async_entries_for_config_entry(
        er.async_get(sem_real_hass), entry.entry_id)}
    assert ids_after == ids_before


@pytest.mark.asyncio
async def test_card_reads_the_new_name_from_the_power_sensor(
    sem_real_hass, sem_multi_wallbox_config_entry,
) -> None:
    _seed_two_wallboxes(sem_real_hass)
    await _setup_sem(sem_real_hass, sem_multi_wallbox_config_entry)
    await _rename(sem_real_hass, "ev_charger", "Carport")
    await sem_real_hass.async_block_till_done()
    state = sem_real_hass.states.get("sensor.sem_charger_ev_charger_power")
    assert state is not None
    assert state.attributes["charger_name"] == "Carport"
