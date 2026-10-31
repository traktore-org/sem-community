"""#1247 — the Reconfigure page changes what SEM runs.

SEM reads the first charger's own saved copy (``ev_chargers[0]``) before the
top-level keys. The page wrote the top-level keys only, so a changed sensor
or service took effect only where the copy had no value.
"""
from __future__ import annotations

import pytest

from .test_1214_fields_can_be_emptied import OLD, TRIO, _reconfigure, _states
from .test_990_no_charger_dialog import _entry, _installed_data

NEW_POWER = "sensor.abb_new_power"


def _card(**extra):
    return {"id": "ev_charger", "name": "EV Charger", **TRIO,
            "ev_charger_service": OLD, "ev_min_current": 6, **extra}


def _home(card, *, in_options=False, **flat):
    data = _installed_data(**TRIO, ev_charger_service=OLD, **flat)
    if in_options:
        return _entry(data, {"ev_chargers": [card]})
    return _entry({**data, "ev_chargers": [card]})


def _chargers(entry):
    return {**entry.data, **entry.options}["ev_chargers"]


@pytest.mark.asyncio
@pytest.mark.parametrize("in_options", [False, True])
async def test_a_changed_sensor_reaches_the_charger_card(sem_real_hass, in_options):
    _states(sem_real_hass)
    sem_real_hass.states.async_set(NEW_POWER, "0", {"unit_of_measurement": "W",
                                                    "device_class": "power"})
    entry = _home(_card(), in_options=in_options)
    saved = await _reconfigure(sem_real_hass, entry,
                               {"ev_charging_power_sensor": NEW_POWER})
    assert saved["ev_charging_power_sensor"] == NEW_POWER
    first = _chargers(entry)[0]
    assert first["ev_charging_power_sensor"] == NEW_POWER
    assert first["ev_connected_sensor"] == TRIO["ev_connected_sensor"]
    assert first["ev_min_current"] == 6, "the card keeps what the page never offers"


@pytest.mark.asyncio
async def test_an_emptied_service_is_emptied_in_the_card_too(sem_real_hass):
    _states(sem_real_hass)
    entry = _home(_card())
    await _reconfigure(sem_real_hass, entry, {"ev_charger_service": ""})
    assert not _chargers(entry)[0].get("ev_charger_service")


@pytest.mark.asyncio
async def test_a_new_service_takes_nothing_from_the_old_one(sem_real_hass):
    _states(sem_real_hass)
    card = _card(ev_service_param_name="charger_id",
                 ev_charger_service_data='{"x": 1}', ev_service_device_id="dev_old")
    entry = _home(card, ev_service_param_name="charger_id")
    saved = await _reconfigure(sem_real_hass, entry,
                               {"ev_charger_service": "keba.set_current"})
    first = _chargers(entry)[0]
    assert first["ev_charger_service"] == "keba.set_current"
    for k in ("ev_service_param_name", "ev_charger_service_data", "ev_service_device_id"):
        assert not first.get(k), k
        assert not saved.get(k), k


@pytest.mark.asyncio
async def test_a_save_with_no_edit_leaves_the_cards_alone(sem_real_hass):
    _states(sem_real_hass)
    second = {"id": "wall2", "name": "Wall 2", "ev_charger_service": "x.y"}
    entry = _entry({**_installed_data(**TRIO, ev_charger_service=OLD),
                    "ev_chargers": [_card(), second]})
    await _reconfigure(sem_real_hass, entry, None)
    assert _chargers(entry) == [_card(), second]


@pytest.mark.asyncio
async def test_the_page_shows_the_cards_value_first(sem_real_hass):
    """The page offers what SEM runs: the card's value, not a stale flat one."""
    _states(sem_real_hass)
    entry = _home(_card(ev_charger_service="keba.set_current"))
    entry.add_to_hass(sem_real_hass)
    form = await entry.start_reconfigure_flow(sem_real_hass)
    shown = {str(k): (k.description or {}).get("suggested_value")
             for k in form["data_schema"].schema}
    assert shown["ev_charger_service"] == "keba.set_current"
