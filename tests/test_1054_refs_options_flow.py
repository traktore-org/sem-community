"""#1054 — the Configure dialog's add / edit / remove go through the charger
refs, on a real Home Assistant.

The dialog still writes the legacy ``options.ev_chargers`` list (one release);
the reload after its save folds that into ``options.ev_charger_refs``. These
tests walk the dialog the way the browser does (``test_990``'s walker), let
the reload run, and read the refs.
"""
from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType

from custom_components.solar_energy_management.hardware_detection import (
    charger_is_complete,
)

from .integrations_rig.rig import load_capture, replay
from .test_990_no_charger_dialog import _browser_submit
from .test_1054_weindler_replay import _his_box, _seed, _sem_entry

#: a half card from an older detection, on no device at all — it survives
#: the migration as its own ref and sits FIRST, as weindler's did
HALF = {"id": "goecharger_28eb748ac3", "name": "Goecharger Charger",
        "ev_total_energy_sensor": "sensor.not_on_any_device_energy"}


async def _home(hass, base, chargers_of):
    """Set up SEM on the replayed go-e; ``chargers_of(new)`` is the stored
    list. Returns (entry, the go-e card)."""
    from .test_services_real import _setup_sem
    _seed(hass)
    dev, offer = await _his_box(hass)
    new = {**offer, "id": f"goecharger_{dev}", "name": "go-eCharger"}
    entry = _sem_entry(base, None, chargers_of(new))
    await _setup_sem(hass, entry)
    return entry, new


async def _walk(hass, entry, answers):
    """The dialog to its end; then the reload its save starts."""
    answers = {k: list(v) for k, v in answers.items()}
    result = await hass.config_entries.options.async_init(entry.entry_id)
    seen = []
    for _ in range(40):
        if result["type"] != FlowResultType.FORM:
            break
        step = result["step_id"]
        seen.append(step)
        typed = answers[step].pop(0) if answers.get(step) else None
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], user_input=_browser_submit(result, typed))
    else:
        raise AssertionError(f"dialog never ended: {seen}")
    assert result["type"] == FlowResultType.CREATE_ENTRY, seen
    await hass.async_block_till_done()
    return seen


def _refs(entry):
    return [r["id"] for r in entry.options["ev_charger_refs"]]


@pytest.mark.asyncio
async def test_a_half_primary_opens_on_the_list_and_can_be_removed(
    sem_real_hass, sem_multi_wallbox_config_entry,
):
    """weindler's dead end, through the dialog: the half card is first. The
    dialog opens on the charger list (its page has required fields the
    half card cannot fill) and offers the half card for removal."""
    h = sem_real_hass
    entry, new = await _home(h, sem_multi_wallbox_config_entry,
                             lambda new: [dict(HALF), dict(new)])
    assert _refs(entry) == [HALF["id"], new["id"]]

    seen = await _walk(h, entry, {
        "ev_charger_menu": [{"action": "remove_charger"}],
        "ev_charger_remove": [{"charger_to_remove": HALF["id"]}],
    })
    assert seen[0] == "ev_charger_menu", seen
    assert _refs(entry) == [new["id"]]
    assert list(entry.runtime_data._ev_devices) == [new["id"]]
    assert "ev_chargers" not in entry.data

    await h.config_entries.async_reload(entry.entry_id)
    await h.async_block_till_done()
    assert _refs(entry) == [new["id"]]


@pytest.mark.asyncio
async def test_add_through_the_dialog_is_a_ref(
    sem_real_hass, sem_multi_wallbox_config_entry,
):
    h = sem_real_hass
    entry, new = await _home(h, sem_multi_wallbox_config_entry,
                             lambda new: [dict(new)])
    from homeassistant.helpers import entity_registry as er
    er.async_get(h).async_get_or_create(
        "sensor", "garage_rig", "garage_power", suggested_object_id="garage_power",
        unit_of_measurement="W")
    for eid, val in (("binary_sensor.garage_plug", "off"),
                     ("binary_sensor.garage_charging", "off"),
                     ("sensor.garage_power", "0")):
        h.states.async_set(eid, val)
    seen = await _walk(h, entry, {
        "ev_charger": [{}],
        "ev_charger_menu": [{"action": "add_charger"}],
        "ev_charger_add": [{
            "charger_name": "Garage",
            "ev_connected_sensor": "binary_sensor.garage_plug",
            "ev_charging_sensor": "binary_sensor.garage_charging",
            "ev_charging_power_sensor": "sensor.garage_power"}],
    })
    assert "ev_charger_add" in seen, seen
    refs = entry.options["ev_charger_refs"]
    assert len(refs) == 2 and refs[0]["id"] == new["id"]
    garage = refs[1]
    assert garage["device_id"] is None            # entities on no device
    assert garage["overrides"]["ev_charging_power_sensor"] == "sensor.garage_power"


@pytest.mark.asyncio
async def test_edit_through_the_dialog_is_an_override_that_lasts(
    sem_real_hass, sem_multi_wallbox_config_entry,
):
    h = sem_real_hass
    entry, new = await _home(h, sem_multi_wallbox_config_entry,
                             lambda new: [dict(new)])
    h.states.async_set("sensor.my_meter", "0", {"unit_of_measurement": "W"})
    await _walk(h, entry, {
        "ev_charger": [{"ev_charging_power_sensor": "sensor.my_meter"}],
    })
    ref = entry.options["ev_charger_refs"][0]
    assert ref["id"] == new["id"]
    assert ref["overrides"].get("ev_charging_power_sensor") == "sensor.my_meter"
    card = entry.options["ev_chargers"][0]
    assert card["ev_charging_power_sensor"] == "sensor.my_meter"
    assert charger_is_complete(card)

    await h.config_entries.async_reload(entry.entry_id)
    await h.async_block_till_done()
    assert entry.options["ev_chargers"][0]["ev_charging_power_sensor"] == "sensor.my_meter"


@pytest.mark.asyncio
async def test_remove_through_the_dialog_is_final(
    sem_real_hass, sem_multi_wallbox_config_entry,
):
    h = sem_real_hass
    await replay(h, load_capture("keba"))
    keba = {"id": "keba_box", "name": "KEBA",
            "ev_charging_power_sensor": "sensor.keba_garage_power",
            "ev_charger_service": "keba.set_current"}
    entry, new = await _home(h, sem_multi_wallbox_config_entry,
                             lambda new: [dict(keba), dict(new)])
    assert _refs(entry) == ["keba_box", new["id"]]
    await _walk(h, entry, {
        "ev_charger": [{"ev_connected_sensor": "binary_sensor.x_plug",
                        "ev_charging_sensor": "binary_sensor.x_charging"}],
        "ev_charger_menu": [{"action": "remove_charger"}],
        "ev_charger_remove": [{"charger_to_remove": new["id"]}],
    })
    assert _refs(entry) == ["keba_box"]
    for _ in range(2):
        await h.config_entries.async_reload(entry.entry_id)
        await h.async_block_till_done()
        assert _refs(entry) == ["keba_box"]
