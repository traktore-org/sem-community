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
BOX2 = "garage_go_e"
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


# ═══════════════════════════════════════════════════════════════════════
# (#1054 review) end to end: what the add step saves is what SEM sends
# ═══════════════════════════════════════════════════════════════════════

_GOE_SERVICES = {"set_max_current": ("charger_name", "max_current"),
                 "set_absolute_max_current": ("charger_absolute_max_current",
                                              "charger_name"),
                 "set_cable_lock_mode": ("cable_lock_mode", "charger_name"),
                 "set_charge_limit": ("charge_limit", "charger_name")}


async def _two_goe_boxes(hass):
    """Two go-e boxes on the one integration, its services registered
    schema-less the way it registers them, and a recorder on the current."""
    from homeassistant.helpers.service import SERVICE_DESCRIPTION_CACHE
    calls = []

    async def _record(call):
        calls.append(dict(call.data))

    for name, fields in _GOE_SERVICES.items():
        hass.services.async_register("goecharger", name,
                                     _record if name == "set_max_current"
                                     else (lambda c: None))
        hass.data.setdefault(SERVICE_DESCRIPTION_CACHE, {})[
            ("goecharger", name)] = {"fields": {f: {} for f in fields}}
    cap = load_capture("goecharger")
    await replay(hass, cap)
    # the second box as the integration names it: its own name in every id
    await replay(hass, json.loads(json.dumps(cap).replace(BOX, BOX2)))
    return calls


def _submission(result) -> dict:
    """Submit the add form as the user would: every prefilled value kept."""
    out = {}
    for key in result["data_schema"].schema:
        name = str(key)
        default = key.default() if callable(getattr(key, "default", None)) else None
        suggested = (getattr(key, "description", None) or {}).get("suggested_value")
        val = suggested if suggested not in (None, "") else default
        if val not in (None, ""):
            out[name] = val
    return out


async def _add(flow):
    shown = await flow.async_step_ev_charger_add()
    assert shown["type"] == "form", shown
    await flow.async_step_ev_charger_add(_submission(shown))
    return flow._data["ev_chargers"][-1]


async def test_the_add_step_saves_the_wiring_and_each_box_sends_its_own_name(
        sem_real_hass, sem_config_entry):
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    from .test_services_real import _seed_sem_input_sensors

    from unittest.mock import patch

    hass = sem_real_hass
    calls = await _two_goe_boxes(hass)
    sem_config_entry.add_to_hass(hass)
    flow = OptionsFlowHandler(sem_config_entry)
    flow.hass = hass
    flow._data = {"ev_chargers": []}
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: sem_config_entry)):
        first = await _add(flow)
        second = await _add(flow)

    for saved, box in ((first, BOX), (second, BOX2)):
        assert saved.get("ev_charger_service"), (saved, flow._add_discovered)
        assert saved["ev_charger_service"] == "goecharger.set_max_current"
        assert saved["ev_service_param_name"] == "max_current"
        assert json.loads(saved["ev_charger_service_data"]) == {"charger_name": box}

    # SEM built from what was saved: the exact call each box gets
    _seed_sem_input_sensors(hass)
    for saved in (first, second):
        hass.states.async_set(saved["ev_charging_power_sensor"], "0",
                              {"unit_of_measurement": "kW"})
    data = dict(sem_config_entry.data)
    data["ev_chargers"] = [first, second]
    hass.config_entries.async_update_entry(
        sem_config_entry, data=data,
        options={**sem_config_entry.options, "observer_mode": False})
    assert await hass.config_entries.async_setup(sem_config_entry.entry_id)
    await hass.async_block_till_done()
    devices = sem_config_entry.runtime_data._ev_devices
    for cid, box in ((first["id"], BOX), (second["id"], BOX2)):
        dev = devices[cid]
        dev.observer_mode = False
        calls.clear()
        await dev._set_current(10)
        await hass.async_block_till_done()
        assert calls == [{"charger_name": box, "max_current": 10}], calls


async def test_a_user_who_picks_another_service_gets_no_stale_box_name(hass):
    from custom_components.solar_energy_management.config_flow import (
        _carry_hidden_wiring, _drop_stale_service_wiring,
    )
    found = {"ev_charger_service": "goecharger.set_max_current",
             "ev_service_param_name": "max_current",
             "ev_charger_service_data": '{"charger_name": "a"}',
             "ev_charging_power_sensor": "sensor.p"}
    saved = {}
    _carry_hidden_wiring(found, {"ev_charger_service": "other.set_current",
                                 "ev_charging_power_sensor": "sensor.p"}, saved)
    assert "ev_service_param_name" not in saved
    assert "ev_charger_service_data" not in saved
    # edit: changing the service drops the old one's wiring
    charger = dict(found)
    before = dict(charger)
    charger["ev_charger_service"] = "other.set_current"
    _drop_stale_service_wiring(before, {"ev_charger_service": "other.set_current"},
                               charger)
    assert "ev_charger_service_data" not in charger
    # edit: keeping the service keeps it
    charger = dict(found)
    _drop_stale_service_wiring(dict(found),
                               {"ev_charger_service": found["ev_charger_service"]},
                               charger)
    assert charger["ev_charger_service_data"] == found["ev_charger_service_data"]


# ═══════════════════════════════════════════════════════════════════════
# (#1054 review) a power class read from the unit alone picks only when
# it is unambiguous
# ═══════════════════════════════════════════════════════════════════════

def _pick(*entries):
    from custom_components.solar_energy_management.hardware_detection import (
        _charging_power,
    )
    return _charging_power(list(entries), vehicle=False)


def test_three_unnamed_kw_readings_pick_nothing():
    assert _pick(_entry("sensor.box_house_power", unit="kW"),
                 _entry("sensor.box_heatpump_power", unit="kW"),
                 _entry("sensor.box_meter_reading", unit="kW")) is None


def test_the_one_that_names_itself_is_picked():
    """The review's trio: two readings that say nothing, one that says it is
    the charger's. Never alphabetical luck (heatpump_power)."""
    assert _pick(_entry("sensor.box_house_power", unit="kW"),
                 _entry("sensor.box_heatpump_power", unit="kW"),
                 _entry("sensor.box_real_charger_reading", unit="kW")) == \
        "sensor.box_real_charger_reading"


def test_go_e_p_all_is_still_picked_over_its_phase_legs():
    legs = [_entry(f"sensor.{P}_p_l{i}", unit="kW") for i in (1, 2, 3)]
    assert _pick(*legs, _entry(f"sensor.{P}_p_n", unit="kW"),
                 _entry(f"sensor.{P}_p_all", unit="kW")) == f"sensor.{P}_p_all"


def test_a_declared_power_class_beats_any_unit_guess():
    assert _pick(_entry("sensor.box_total_kw", unit="kW"),
                 _entry("sensor.box_power", dc="power", unit="W")) == "sensor.box_power"


async def test_editing_a_go_e_charger_keeps_its_wiring(sem_real_hass, sem_config_entry):
    """Edit: submit the form unchanged — the service field and the box name
    the form does not show are still on the charger afterwards."""
    from unittest.mock import patch

    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    hass = sem_real_hass
    await _two_goe_boxes(hass)
    sem_config_entry.add_to_hass(hass)
    flow = OptionsFlowHandler(sem_config_entry)
    flow.hass = hass
    flow._data = {"ev_chargers": []}
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: sem_config_entry)):
        saved = await _add(flow)
        flow._edit_charger_id = saved["id"]
        shown = await flow.async_step_ev_charger_edit()
        assert shown["type"] == "form"
        await flow.async_step_ev_charger_edit(_submission(shown))
    after = flow._data["ev_chargers"][-1]
    assert after["ev_charger_service"] == "goecharger.set_max_current"
    assert after["ev_service_param_name"] == "max_current"
    assert json.loads(after["ev_charger_service_data"]) == {"charger_name": BOX}
