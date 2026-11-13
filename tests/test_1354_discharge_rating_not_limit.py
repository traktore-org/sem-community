"""#1354 — setup read the inverter's discharge LIMIT (a writable number,
last written e.g. 750 W) as the battery's RATING and stored it in both
discharge settings; the 1000 W-minimum field then showed 1000 while SEM
used 750. A number's rating is its ``max``; values land inside the
settings' own ranges.
"""
from __future__ import annotations

from types import SimpleNamespace

from .test_848_registry_specs import _detect, _ent, _num, _state


def test_registry_number_uses_its_max_not_its_state():
    states = {"number.lim": _num("number.lim", 750, 5000)}
    entries = [_ent("number.lim", "huawei_solar",
                    tk="storage_maximum_discharging_power")]
    d = _detect(states, entries)
    assert d["battery_max_discharge_power"] == 5000
    assert d["battery_assist_max_power"] == 5000


def test_glob_number_uses_its_max_not_its_state():
    states = {"number.batterie_maximale_entladeleistung":
              _num("number.batterie_maximale_entladeleistung", 750, 2500)}
    d = _detect(states, [])
    assert d["battery_max_discharge_power"] == 2500
    assert d["battery_assist_max_power"] == 2500


def test_a_number_without_max_places_nothing():
    st = SimpleNamespace(entity_id="number.x_max_discharge", state="750",
                         attributes={"unit_of_measurement": "W"})
    d = _detect({"number.x_max_discharge": st}, [])
    assert "battery_max_discharge_power" not in d
    assert "battery_assist_max_power" not in d


def test_a_sensor_rating_keeps_its_state():
    states = {"sensor.bat_max_discharge_power":
              _state("sensor.bat_max_discharge_power", 3300, "W")}
    assert _detect(states, [])["battery_max_discharge_power"] == 3300


def test_values_land_inside_each_settings_range():
    states = {"sensor.bat_max_discharge_power":
              _state("sensor.bat_max_discharge_power", 700, "W")}
    d = _detect(states, [])
    assert d["battery_max_discharge_power"] == 700
    assert d["battery_assist_max_power"] == 1000   # the field's floor
    states = {"sensor.bat_max_discharge_power":
              _state("sensor.bat_max_discharge_power", 90000, "W")}
    d = _detect(states, [])
    assert d["battery_max_discharge_power"] == 25000
