"""(#1353) The crawler proposes a thermometer for a heater; the user confirms.

A heater shows its temperature questions only with a thermometer. The finder
looks on the heater's own device, else in its own area, for a temperature
sensor whose own or device name says tank / boiler / hot water. It only
proposes: the card shows it and the user's click writes the setting.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er

from custom_components.solar_energy_management.consts.core import DOMAIN
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)
from custom_components.solar_energy_management import hardware_detection as hd
from custom_components.solar_energy_management.hardware_detection import (
    find_heater_thermometer,
)

HEATER = "switch.heater_relay"


def _st(eid, state=55.0, name=None, unit="°C", dc="temperature"):
    a = {"unit_of_measurement": unit, "friendly_name": name or eid}
    if dc:
        a["device_class"] = dc
    return SimpleNamespace(entity_id=eid, state=str(state), attributes=a)


class _Hass:
    def __init__(self, states):
        self._s = {s.entity_id: s for s in states}
        self.states = self

    def async_all(self, domain=None):
        return [s for e, s in self._s.items() if domain is None or e.startswith(domain + ".")]

    def get(self, eid):
        return self._s.get(eid)


class _Reg:
    """Entity registry: eid -> (device_id, area_id, platform)."""

    def __init__(self, rows):
        self._r = rows

    def async_get(self, eid):
        row = self._r.get(eid)
        if row is None:
            return None
        dev, area, platform = (tuple(row) + (None, None))[:3]
        return SimpleNamespace(device_id=dev, area_id=area, platform=platform or "other")


class _DevReg:
    def __init__(self, devs):
        self._d = devs

    def async_get(self, did):
        row = self._d.get(did)
        if row is None:
            return None
        name, area = row
        return SimpleNamespace(name=name, name_by_user=None, model=None, area_id=area)


@pytest.fixture
def house(monkeypatch):
    """Install fake registries for one test (monkeypatch undoes them)."""
    def install(states, ents, devs=None):
        monkeypatch.setattr(er, "async_get", lambda hass: _Reg(ents))
        monkeypatch.setattr(dr, "async_get", lambda hass: _DevReg(devs or {}))
        return _Hass(states)
    return install


def _eids(found):
    return [r["entity_id"] for r in found]


@pytest.mark.unit
class TestTheFinder:

    def test_same_device_wins_over_same_area(self, house):
        hass = house(
            [_st("sensor.tank_temp"), _st("sensor.boiler_area_temp")],
            {HEATER: ("d1", "cellar"), "sensor.tank_temp": ("d1", "cellar"),
             "sensor.boiler_area_temp": ("d2", "cellar")},
            {"d1": ("Relay", "cellar"), "d2": ("Other", "cellar")})
        found = find_heater_thermometer(hass, [HEATER])
        assert _eids(found) == ["sensor.tank_temp", "sensor.boiler_area_temp"]
        assert [r["why"] for r in found] == ["device", "area"]

    @pytest.mark.parametrize("name", [
        "Tank temperature", "DHW temperature", "Boiler Temperatur",
        "Hot water temperature", "Warmwasser Temperatur", "Speicher oben",
        "Ballon température", "Eau chaude température", "Warm water temp",
        "Varmtvand temperatur",
    ])
    def test_the_words_in_several_languages(self, house, name):
        hass = house([_st("sensor.t1", name=name)],
                     {HEATER: (None, "cellar"), "sensor.t1": (None, "cellar")})
        assert _eids(find_heater_thermometer(hass, [HEATER])) == ["sensor.t1"]

    def test_the_device_name_can_carry_the_word(self, house):
        hass = house([_st("sensor.temperature", name="Temperature")],
                     {HEATER: ("d1", None), "sensor.temperature": ("d1", None)},
                     {"d1": ("Hot water tank", None)})
        assert _eids(find_heater_thermometer(hass, [HEATER])) == ["sensor.temperature"]

    @pytest.mark.parametrize("name", [
        "Outdoor boiler temperature",      # outside
        "Boiler room temperature",         # a room
        "Boiler CPU temperature",          # electronics
        "Boiler flow temperature",         # a pipe, not the tank
    ])
    def test_outdoor_room_and_electronics_are_never_proposed(self, house, name):
        hass = house([_st("sensor.t1", name=name)],
                     {HEATER: ("d1", "a"), "sensor.t1": ("d1", "a")})
        assert find_heater_thermometer(hass, [HEATER]) == []

    def test_a_plugs_own_temperature_without_tank_words_is_not_proposed(self, house):
        hass = house([_st("sensor.plug_temperature", name="Plug temperature")],
                     {HEATER: ("d1", "a"), "sensor.plug_temperature": ("d1", "a")},
                     {"d1": ("Smart plug", "a")})
        assert find_heater_thermometer(hass, [HEATER]) == []

    def test_sems_own_sensor_is_never_proposed(self, house):
        hass = house([_st("sensor.sem_boiler_temp", name="SEM boiler temp")],
                     {HEATER: ("d1", "a"),
                      "sensor.sem_boiler_temp": ("d1", "a", DOMAIN)})
        assert find_heater_thermometer(hass, [HEATER]) == []

    def test_a_sensor_bound_to_another_device_is_never_proposed(self, house):
        hass = house([_st("sensor.tank_a"), _st("sensor.tank_b")],
                     {HEATER: ("d1", "a"), "sensor.tank_a": ("d1", "a"),
                      "sensor.tank_b": ("d1", "a")})
        got = find_heater_thermometer(hass, [HEATER], exclude={"sensor.tank_a"})
        assert _eids(got) == ["sensor.tank_b"]

    def test_a_sensor_in_another_area_is_not_proposed(self, house):
        hass = house([_st("sensor.tank_temp")],
                     {HEATER: ("d1", "cellar"), "sensor.tank_temp": ("d2", "attic")})
        assert find_heater_thermometer(hass, [HEATER]) == []

    def test_a_reading_sensor_comes_before_a_dead_one_and_order_is_stable(self, house):
        hass = house([_st("sensor.tank_a", "unavailable"), _st("sensor.tank_c"),
                      _st("sensor.tank_b")],
                     {HEATER: ("d1", "a"), "sensor.tank_a": ("d1", "a"),
                      "sensor.tank_b": ("d1", "a"), "sensor.tank_c": ("d1", "a")})
        assert _eids(find_heater_thermometer(hass, [HEATER])) == [
            "sensor.tank_b", "sensor.tank_c", "sensor.tank_a"]

    def test_a_non_temperature_sensor_is_skipped(self, house):
        hass = house([_st("sensor.tank_energy", unit="kWh", dc="energy")],
                     {HEATER: ("d1", "a"), "sensor.tank_energy": ("d1", "a")})
        assert find_heater_thermometer(hass, [HEATER]) == []

    def test_an_unreadable_registry_gives_nothing_and_never_raises(self, monkeypatch):
        def boom(hass):
            raise RuntimeError("no registry")
        monkeypatch.setattr(er, "async_get", boom)
        assert find_heater_thermometer(_Hass([_st("sensor.tank_t")]), [HEATER]) == []
        assert find_heater_thermometer(None, [HEATER]) == []
        assert find_heater_thermometer(_Hass([]), []) == []

    def test_no_brand_names_in_the_vocabulary(self):
        brands = ("huawei", "keba", "viessmann", "stiebel", "shelly", "tasmota")
        words = " ".join(hd.TANK_WORDS) + " ".join(a + b for p in hd.TANK_PAIRS for a, b in [p])
        assert not any(b in words for b in brands)


def _live(**over):
    base = dict(comfort_state="disengaged", entity_id=HEATER, power_entity_id=None,
                temperature_entity_id=None, _comfort_reading=lambda: None)
    base.update(over)
    return SimpleNamespace(**base)


def _registry(hass, goals=None):
    reg = UnifiedDeviceRegistry(MagicMock(), MagicMock(), MagicMock(), MagicMock())
    reg.hass = hass
    reg._device_goals = goals or {}
    return reg


@pytest.mark.unit
class TestThePublishedProposal:

    def _hass(self, house):
        return house([_st("sensor.tank_temp", name="Tank temperature")],
                     {HEATER: ("d1", "a"), "sensor.tank_temp": ("d1", "a")})

    def test_the_device_carries_the_proposal(self, house):
        reg = _registry(self._hass(house), {"hw": {}})
        got = reg._thermometer_proposal_payload("hw", {}, _live())
        assert got == {"thermometer_proposal": {
            "entity_id": "sensor.tank_temp", "name": "Tank temperature", "why": "device"}}

    def test_nothing_when_the_heater_has_a_thermometer(self, house):
        reg = _registry(self._hass(house))
        assert reg._thermometer_proposal_payload(
            "hw", {"comfort_entity": "sensor.mine"}, _live()) == {}
        assert reg._thermometer_proposal_payload(
            "hw", {}, _live(_comfort_reading=lambda: 48.0)) == {}
        assert reg._thermometer_proposal_payload(
            "hw", {}, _live(temperature_entity_id="sensor.cfg")) == {}

    def test_a_load_that_is_no_heater_gets_none(self, house):
        reg = _registry(self._hass(house))
        assert reg._thermometer_proposal_payload("x", {}, SimpleNamespace(entity_id=HEATER)) == {}
        assert reg._thermometer_proposal_payload("x", {}, None) == {}

    def test_a_sensor_another_device_uses_is_not_proposed(self, house):
        reg = _registry(self._hass(house),
                        {"other": {"comfort_entity": "sensor.tank_temp"}})
        assert reg._thermometer_proposal_payload("hw", {}, _live()) == {}

    def test_the_crawl_is_rate_limited(self, house, monkeypatch):
        reg = _registry(self._hass(house))
        calls = []
        real = hd.find_heater_thermometer

        def spy(*a, **k):
            calls.append(1)
            return real(*a, **k)
        from custom_components.solar_energy_management.features import device_registry as m
        monkeypatch.setattr(m, "find_heater_thermometer", spy)
        for _ in range(5):
            reg._thermometer_proposal_payload("hw", {}, _live())
        assert len(calls) == 1
