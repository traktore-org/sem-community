"""#1249 — a new service on the first charger's Configure page keeps the old
service's field name, service data and box name, in the charger's own copy
AND in the top-level keys SEM falls back to."""
from __future__ import annotations

import pytest
from homeassistant.data_entry_flow import FlowResultType

from .test_990_no_charger_dialog import _entry, _installed_data, _walk
from .test_1214_fields_can_be_emptied import OLD, TRIO, _quiet  # noqa: F401

WIRING = {"ev_service_param_name": "charger_id",
          "ev_charger_service_data": "{\"x\": 1}",
          "ev_service_device_id": "dev_old"}


def _entry_with(flat_in_data=True):
    card = {"id": "ev_charger", "name": "EV Charger", **TRIO,
            "ev_charger_service": OLD, **WIRING}
    data = _installed_data(**TRIO, ev_charger_service=OLD,
                           **(WIRING if flat_in_data else {}))
    opts = {"ev_chargers": [card], "ev_charger_service": OLD,
            **({} if flat_in_data else WIRING)}
    return _entry(data, opts)


async def _save(hass, entry, typed):
    seen, done = await _walk(hass, entry, {"ev_charger": [typed]})
    assert seen[0] == "ev_charger"
    assert done["type"] == FlowResultType.CREATE_ENTRY
    return {**entry.data, **entry.options}, entry.options["ev_chargers"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("flat_in_data", [True, False])
async def test_a_new_service_drops_the_old_wiring_in_both_places(
        sem_real_hass, _quiet, flat_in_data):  # noqa: F811
    entry = _entry_with(flat_in_data)
    flat, card = await _save(sem_real_hass, entry,
                             {"ev_charger_service": "keba.set_current"})
    assert flat["ev_charger_service"] == "keba.set_current"
    for k in WIRING:
        assert not card.get(k), k
        assert not flat.get(k), k


@pytest.mark.asyncio
async def test_the_same_service_keeps_its_wiring(sem_real_hass, _quiet):  # noqa: F811
    entry = _entry_with()
    flat, card = await _save(sem_real_hass, entry, {})
    for k, v in WIRING.items():
        assert card[k] == v
        assert flat[k] == v
