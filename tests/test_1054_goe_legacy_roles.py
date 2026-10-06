"""#1054 (weindler, 06.10.2026) — a go-eCharger on the HACS ``goecharger``
integration (cathiele/homeassistant-goecharger, 502 installs) read as "no
role matched".

What the integration really offers (its own source, pinned in the rig):

* power ``p_all`` in kW with NO device class;
* the car status as a plain text sensor (``car_status``: "charging",
  "Waiting for vehicle", …) with no options list;
* ``switch.…_allow_charging`` — start/stop;
* the current only through ``goecharger.set_max_current``, registered with
  NO schema; its fields (``charger_name``, ``max_current``) exist only in
  its services.yaml, and ``charger_name`` names WHICH box.

The crawler learned four generic things, no brand code: a unit says the
class when the integration set none; "all" is the total over the phases; a
car-status sensor read by its state when the device has no other plug or
charging source; a service field that names the box is filled with the
device's own identifier, and SEM sends it with every current write.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.hardware_detection import (
    _roles_dc,
    propose_roles_from_roster,
)
from custom_components.solar_energy_management.utils.service_data import (
    service_extra_data,
)

from .integrations_rig.rig import crawl, load_capture, replay

BOX = "wallbox_go_e"
P = f"goecharger_{BOX}"


def _offer(rep):
    offers = [n["suggested_charger"] for n in rep["near_misses"]
              if n["platform"] == "goecharger" and n["suggested_charger"]]
    assert len(offers) == 1, rep["near_misses"]
    return offers[0]


async def test_the_reporters_box_is_a_complete_offer(hass):
    await replay(hass, load_capture("goecharger"))
    o = _offer(crawl(hass))
    assert o["ev_charging_power_sensor"] == f"sensor.{P}_p_all"
    assert o["ev_connected_sensor"] == f"sensor.{P}_car_status"
    assert o["ev_charging_sensor"] == f"sensor.{P}_car_status"
    assert o["ev_start_stop_entity"] == f"switch.{P}_allow_charging"
    assert o["ev_charger_service"] == "goecharger.set_max_current"
    assert o["ev_service_param_name"] == "max_current"
    assert json.loads(o["ev_charger_service_data"]) == {"charger_name": BOX}
    assert o["ev_session_energy_sensor"] == f"sensor.{P}_current_session_charged_energy"
    assert o["ev_total_energy_sensor"] == f"sensor.{P}_energy_total"
    # never one phase leg, never the neutral, never the absolute ceiling
    assert "p_l" not in o["ev_charging_power_sensor"]
    assert "absolute" not in json.dumps(o)


async def test_the_proposal_row_is_no_longer_hand_wiring(hass):
    await replay(hass, load_capture("goecharger"))
    rows = [r for r in crawl(hass).get("roster_proposals") or []
            if r.get("domain") == "goecharger" or r.get("platform") == "goecharger"]
    ctl = None
    for r in rows:
        for role in r.get("roles") or []:
            if role.get("role") == "ev_current_control":
                ctl = role
    if ctl is None:  # the shape of the row: find the proposal anywhere
        ctl = json.dumps(rows)
        assert "needs_hand_wiring" not in ctl
    else:
        assert ctl.get("action") != "needs_hand_wiring"


def _entry(eid, dc=None, unit=None, uid=None):
    return SimpleNamespace(entity_id=eid, original_device_class=dc,
                           unit_of_measurement=unit, translation_key=None,
                           unique_id=uid or eid.split(".", 1)[1],
                           device_id="dev1", platform="goecharger",
                           capabilities=None, entity_category=None)


class TestTheUnitSaysTheClass:
    def test_kw_without_a_class_is_power(self):
        assert _roles_dc(_entry("sensor.x_p_all", unit="kW")) == "power"
        assert _roles_dc(_entry("sensor.x_p", unit="W")) == "power"

    def test_kwh_without_a_class_is_energy(self):
        assert _roles_dc(_entry("sensor.x_e", unit="kWh")) == "energy"

    def test_a_set_class_wins(self):
        assert _roles_dc(_entry("sensor.x", dc="voltage", unit="kW")) == "voltage"

    def test_other_units_say_nothing(self):
        assert _roles_dc(_entry("sensor.x_i", unit="A")) == ""
        assert _roles_dc(_entry("sensor.x_t")) == ""


class TestTheBoxNameField:
    def _proposal(self, ident):
        ents = [_entry(f"sensor.{P}_p_all", unit="kW")]
        live = MagicMock()
        from custom_components.solar_energy_management.hardware_detection import (
            _ServiceNames,
        )
        names = _ServiceNames({"set_max_current": ["charger_name", "max_current"]})
        live = lambda domain: names  # noqa: E731
        return propose_roles_from_roster(ents, "goecharger", services_of=live,
                                         device_ident=ident).get("ev_current_control")

    def test_filled_with_the_device_identifier(self):
        p = self._proposal(BOX)
        assert p["action"] == "per_charger"
        assert p["data"] == {"charger_name": BOX}

    def test_without_an_identifier_it_stays_hand_wiring(self):
        """No guess: unknown box name = a proposal to wire by hand."""
        p = self._proposal(None)
        assert p["action"] == "needs_hand_wiring"
        assert "charger_name" in p["reason"]


async def test_service_fields_come_from_the_description_when_no_schema(hass):
    """go-e registers set_max_current with NO schema; Home Assistant knows
    its fields only from services.yaml (the description cache)."""
    from homeassistant.helpers.service import SERVICE_DESCRIPTION_CACHE

    from custom_components.solar_energy_management.hardware_detection import (
        _services_of,
    )

    async def _noop(call):
        return None

    hass.services.async_register("goecharger", "set_max_current", _noop)
    hass.data.setdefault(SERVICE_DESCRIPTION_CACHE, {})[
        ("goecharger", "set_max_current")] = {
            "fields": {"charger_name": {}, "max_current": {}}}
    live = _services_of(hass)("goecharger")
    assert "set_max_current" in live
    assert live.get("set_max_current") == ["charger_name", "max_current"]


async def test_without_a_description_a_schemaless_service_has_no_fields(hass):
    from custom_components.solar_energy_management.hardware_detection import (
        _services_of,
    )

    async def _noop(call):
        return None

    hass.services.async_register("goecharger", "set_cable_lock_mode", _noop)
    assert _services_of(hass)("goecharger").get("set_cable_lock_mode") == []


class TestTheServiceData:
    def test_json_object(self):
        assert service_extra_data('{"charger_name": "box"}') == {"charger_name": "box"}

    def test_anything_else_is_nothing(self):
        assert service_extra_data("") == {}
        assert service_extra_data(None) == {}
        assert service_extra_data("not json") == {}
        assert service_extra_data("[1, 2]") == {}
        assert service_extra_data({"a": 1}) == {"a": 1}


@pytest.mark.asyncio
async def test_every_current_write_names_the_box():
    """The runtime half: the amps go out WITH the box's name, and the name
    can never overwrite the amps."""
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    hass = MagicMock()
    hass.services.async_call = AsyncMock(return_value=None)
    hass.services.has_service = MagicMock(return_value=True)
    hass.states.get = MagicMock(return_value=None)
    d = CurrentControlDevice(
        hass=hass, device_id="goecharger_dev1", name="go-e", priority=3,
        min_current=6.0, max_current=16.0, phases=3, voltage=230.0,
        power_entity_id=f"sensor.{P}_p_all",
        charger_service="goecharger.set_max_current",
    )
    d.service_param_name = "max_current"
    d.service_extra_data = service_extra_data(
        json.dumps({"charger_name": BOX, "max_current": 99}))
    await d._set_current(10)
    calls = [c for c in hass.services.async_call.await_args_list
             if c.args[:2] == ("goecharger", "set_max_current")]
    assert calls, hass.services.async_call.await_args_list
    data = calls[-1].args[2]
    assert data["charger_name"] == BOX
    assert data["max_current"] == 10
