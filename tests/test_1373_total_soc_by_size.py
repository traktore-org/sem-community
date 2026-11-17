"""#1373 — the total level of two batteries counts their sizes.

@BerndWilli60's home: 9.8 kWh at 38 % and 5.28 kWh at 17 %. The total read
28 % (the plain average, 27.5); by size it is 30.6 %.
"""
from __future__ import annotations

import logging

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    _parse_prefs,
)

_PCT = {"device_class": "battery", "unit_of_measurement": "%"}
_KWH = {"device_class": "energy", "unit_of_measurement": "kWh"}
_W = {"device_class": "power", "unit_of_measurement": "W"}
GRID = {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.gi"}],
        "flow_to": [{"stat_energy_to": "sensor.ge"}],
        "power": [{"stat_rate": "sensor.grid_power"}]}
UNITS = ["sensor.a_power", "sensor.b_power"]


def _reader(hass) -> SensorReader:
    return SensorReader(hass, {"update_interval": 10})


def _fleet(hass, monkeypatch, socs, sizes):
    """A reader whose two units read ``socs`` and hold ``sizes`` kWh."""
    r = _reader(hass)
    by_unit = dict(zip(UNITS, zip(socs, sizes, strict=True), strict=True))
    monkeypatch.setattr(r, "_auto_detect_battery_soc", lambda u: f"{u}_soc")
    monkeypatch.setattr(r, "_read_sensor", lambda e, *a, **k: by_unit[e[:-4]][0])
    monkeypatch.setattr(r, "_accept_unit_soc", lambda e, v: v)
    monkeypatch.setattr(r, "_unit_capacity_kwh", lambda u: by_unit[u][1])
    return r


def test_the_reporters_numbers_give_30_6(hass, monkeypatch):
    r = _fleet(hass, monkeypatch, [38, 17], [9.8, 5.28])
    assert r._read_battery_soc_average(UNITS) == pytest.approx(30.6, abs=0.05)


def test_equal_sizes_are_the_plain_average(hass, monkeypatch):
    r = _fleet(hass, monkeypatch, [38, 17], [5.0, 5.0])
    assert r._read_battery_soc_average(UNITS) == pytest.approx(27.5)


def test_a_changed_size_changes_the_total(hass, monkeypatch):
    a = _fleet(hass, monkeypatch, [38, 17], [9.8, 5.28])
    b = _fleet(hass, monkeypatch, [38, 17], [5.0, 10.0])
    assert (a._read_battery_soc_average(UNITS)
            != pytest.approx(b._read_battery_soc_average(UNITS)))


def test_one_size_unknown_is_the_plain_average_said_once(
        hass, monkeypatch, caplog):
    r = _fleet(hass, monkeypatch, [38, 17], [9.8, 0.0])
    with caplog.at_level(logging.INFO):
        assert r._read_battery_soc_average(UNITS) == pytest.approx(27.5)
        r._read_battery_soc_average(UNITS)
    said = [m for m in caplog.messages if "plain average" in m]
    assert len(said) == 1 and "1373" in said[0]


def test_an_unread_battery_stays_out_of_the_total(hass, monkeypatch):
    r = _fleet(hass, monkeypatch, [38, None], [9.8, 5.28])
    assert r._read_battery_soc_average(UNITS) == pytest.approx(38)
    # its size is not needed when it reads nothing; the others weigh
    r3 = _reader(hass)
    assert r3._soc_by_size([38, 17], [9.8, 5.28]) == pytest.approx(30.6, abs=0.05)


def test_one_battery_is_unchanged(hass):
    r = _reader(hass)
    assert r._soc_by_size([42.0], [9.8]) == 42.0
    assert r._soc_by_size([42.0], [0.0]) == 42.0


def _device_pick(hass, name, soc, kwh):
    entry = MockConfigEntry(domain="test_battery", unique_id=name)
    entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test_battery", name)}, name=name)
    reg = er.async_get(hass)
    for eid, attrs, val in ((f"sensor.{name}_level", _PCT, soc),
                            (f"sensor.{name}_battery_capacity", _KWH, kwh)):
        if val is None:
            continue
        reg.async_get_or_create(
            "sensor", "test_battery", f"{name}_{eid}", suggested_object_id=eid[7:],
            config_entry=entry, device_id=dev.id)
        hass.states.async_set(eid, str(val), attrs)


def _two_unpowered(hass, kwh_b):
    _device_pick(hass, "a", 38, 9.8)
    _device_pick(hass, "b", 17, kwh_b)
    src = lambda n: {"type": "battery", "stat_energy_to": f"sensor.{n}_in",
                     "stat_energy_from": f"sensor.{n}_out",
                     "stat_soc": f"sensor.{n}_level"}
    ed = _parse_prefs(hass, {"energy_sources": [GRID, src("a"), src("b")],
                             "device_consumption": []}, quiet=True)
    hass.states.async_set("sensor.grid_power", "0", _W)
    r = _reader(hass)
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(ed)
    return r


def _read(r):
    from unittest.mock import patch
    out = None
    for n in range(3):
        with patch("time.monotonic", return_value=1000.0 + 10 * n):
            out = r.read_power()
    return out


async def test_the_no_power_path_weights_by_size(hass):
    r = _two_unpowered(hass, 5.28)
    assert _read(r).battery_soc == pytest.approx(30.6, abs=0.05)


async def test_the_no_power_path_with_one_size_unknown_is_plain(hass):
    r = _two_unpowered(hass, None)
    assert _read(r).battery_soc == pytest.approx(27.5)
