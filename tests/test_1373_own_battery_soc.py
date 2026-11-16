"""#1373 — a second battery read 0 % though its SOC sensor read 60 %.

@BerndWilli60's home: b1 a combined battery, b2 a two-sensor battery whose
device registers ``soc_status`` and ``soc_limit`` (codes with no unit, 0
while all is well) before its level ``electric_level`` (%, battery). He had
picked ``electric_level`` as b2's SOC in HA's battery dialog (``stat_soc``).

Two faults, both driven here for real:

* SEM read ``stat_soc`` only on a one-battery home. Each battery of a fleet
  took a guess from its device. Now the parser keeps each battery's own
  ``stat_soc`` (``battery_unit_soc``) and the guess is never asked for it.
* The guess took the first sensor on the device whose id holds "soc", with
  no unit check: ``soc_status`` = 0 read as 0 %, and the fleet SOC was the
  average of 80 % and 0 %. Now a name counts only in % (or as a battery
  level), in detection and in the existence probe alike.
"""
from __future__ import annotations

import ast
import re
from datetime import timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    _parse_prefs,
    battery_units,
    unit_soc_sensor,
    yield_found_units_to_picks,
)

ROOT = Path(__file__).resolve().parent.parent
MONO = "time.monotonic"

_W = {"device_class": "power", "unit_of_measurement": "W",
      "state_class": "measurement"}
_KWH = {"device_class": "energy", "unit_of_measurement": "kWh",
        "state_class": "total_increasing"}
_PCT = {"device_class": "battery", "unit_of_measurement": "%",
        "state_class": "measurement"}
_CODE: dict = {}                   # a status code: no unit, no device class

GRID = {"type": "grid",
        "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
        "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
        "power": [{"stat_rate": "sensor.grid_power"}]}

# b2's device, in the order its integration registers the sensors
FLOW = "solarflow_2400_pro"
FLOW_LEVEL = f"sensor.{FLOW}_electric_level"
FLOW_STATUS = f"sensor.{FLOW}_soc_status"
FLOW_LIMIT = f"sensor.{FLOW}_soc_limit"
FLOW_FROM = f"sensor.{FLOW}_pack_input_power"      # out of the pack
FLOW_TO = f"sensor.{FLOW}_output_pack_power"       # into the pack
FLOW_COUNTERS = (f"sensor.{FLOW}_aggr_charge", f"sensor.{FLOW}_aggr_discharge")

# b1's device
EDGE_POWER = "sensor.seu25_i1_dc_power_2"
EDGE_SOC = "sensor.seu25_b1_state_of_energy"
EDGE_COUNTERS = ("sensor.seu25_b1_energy_import_2", "sensor.seu25_b1_energy_export_2")


def _device(hass, name):
    entry = MockConfigEntry(domain="test_battery", unique_id=name)
    entry.add_to_hass(hass)
    dev = dr.async_get(hass).async_get_or_create(
        config_entry_id=entry.entry_id,
        identifiers={("test_battery", name)}, name=name)
    return entry, dev


def _entity(hass, entry, dev, entity_id, attrs, value):
    """Registered on ``dev`` with the unit and class its state carries;
    ``value`` None leaves it with no state yet (a cold start)."""
    domain, object_id = entity_id.split(".", 1)
    er.async_get(hass).async_get_or_create(
        domain, "test_battery", f"{entry.unique_id}_{object_id}",
        suggested_object_id=object_id, config_entry=entry, device_id=dev.id,
        original_device_class=attrs.get("device_class"),
        unit_of_measurement=attrs.get("unit_of_measurement"))
    if value is not None:
        hass.states.async_set(entity_id, str(value), attrs)


def _flow(hass, level=60, *, status=0, limit=0, level_loaded=True):
    """b2's device: the two codes first, then the level, as registered."""
    entry, dev = _device(hass, FLOW)
    _entity(hass, entry, dev, FLOW_STATUS, _CODE, status)
    _entity(hass, entry, dev, FLOW_LIMIT, _CODE, limit)
    _entity(hass, entry, dev, FLOW_LEVEL, _PCT, level if level_loaded else None)
    _entity(hass, entry, dev, FLOW_TO, _W, 0)
    _entity(hass, entry, dev, FLOW_FROM, _W, 256)
    for counter in FLOW_COUNTERS:
        _entity(hass, entry, dev, counter, _KWH, 10)


def _edge(hass, level=80):
    entry, dev = _device(hass, "seu25")
    _entity(hass, entry, dev, EDGE_POWER, _W, 472)
    _entity(hass, entry, dev, EDGE_SOC, _PCT, level)
    for counter in EDGE_COUNTERS:
        _entity(hass, entry, dev, counter, _KWH, 100)


def _edge_src(soc=EDGE_SOC):
    src = {"type": "battery", "stat_energy_to": EDGE_COUNTERS[0],
           "stat_energy_from": EDGE_COUNTERS[1], "stat_rate": EDGE_POWER}
    if soc:
        src["stat_soc"] = soc
    return src


def _flow_src(soc=FLOW_LEVEL):
    src = {"type": "battery", "stat_energy_to": FLOW_COUNTERS[0],
           "stat_energy_from": FLOW_COUNTERS[1],
           "power_config": {"stat_rate_from": FLOW_FROM,
                            "stat_rate_to": FLOW_TO}}
    if soc:
        src["stat_soc"] = soc
    return src


def _ed(hass, *sources):
    return _parse_prefs(hass, {"energy_sources": [GRID, *sources],
                               "device_consumption": []}, quiet=True)


def _reader(hass, ed, **config) -> SensorReader:
    hass.states.async_set("sensor.grid_power", "0", _W)
    r = SensorReader(hass, {"update_interval": 10, **config})
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(ed)
    return r


def _bare(hass) -> SensorReader:
    """A reader with no Energy Dashboard: only the guess answers."""
    return SensorReader(hass, {"update_interval": 10})


def _read(r, cycles=3):
    readings = None
    for n in range(cycles):
        with patch(MONO, return_value=1000.0 + 10 * n):
            readings = r.read_power()
    return readings


# ── 1. the parser keeps each battery's own stat_soc ─────────────────────


def test_each_battery_keeps_its_own_stat_soc():
    """The pair is listed first and b1 has no stat_soc: entry 0 of
    ``battery_soc_list`` is the pair's, which is battery b2."""
    ed = _parse_prefs(MagicMock(), {"energy_sources": [
        GRID, _flow_src(), _edge_src(soc=None)], "device_consumption": []},
        quiet=True)
    assert battery_units(ed) == [EDGE_POWER, FLOW_TO]
    assert ed.battery_soc_list == [FLOW_LEVEL]
    assert unit_soc_sensor(ed, FLOW_TO) == FLOW_LEVEL
    assert unit_soc_sensor(ed, EDGE_POWER) is None


def test_both_batteries_with_stat_soc():
    ed = _parse_prefs(MagicMock(), {"energy_sources": [
        GRID, _edge_src(), _flow_src()], "device_consumption": []}, quiet=True)
    assert unit_soc_sensor(ed, EDGE_POWER) == EDGE_SOC
    assert unit_soc_sensor(ed, FLOW_TO) == FLOW_LEVEL
    # the discharge side of the pair is no battery of its own
    assert unit_soc_sensor(ed, FLOW_FROM) is None


def test_no_record_is_no_answer():
    assert unit_soc_sensor(None, EDGE_POWER) is None
    assert unit_soc_sensor(MagicMock(battery_unit_soc=None), EDGE_POWER) is None
    assert unit_soc_sensor(MagicMock(battery_unit_soc={EDGE_POWER: ""}),
                           EDGE_POWER) is None


async def test_a_battery_with_no_power_sensor_keeps_its_stat_soc(hass):
    """The derive finds its power sensor; the stat_soc goes with it."""
    _edge(hass)
    entry, dev = _device(hass, "old_pack")
    _entity(hass, entry, dev, "sensor.old_pack_charged", _KWH, 5)
    _entity(hass, entry, dev, "sensor.old_pack_discharged", _KWH, 4)
    _entity(hass, entry, dev, "sensor.old_pack_battery_power", _W, -300)
    # its level is a helper on no device: only the pick can find it
    hass.states.async_set("sensor.old_pack_level_helper", "35", _PCT)
    ed = _ed(hass, _edge_src(), {
        "type": "battery", "stat_energy_to": "sensor.old_pack_charged",
        "stat_energy_from": "sensor.old_pack_discharged",
        "stat_soc": "sensor.old_pack_level_helper"})
    assert battery_units(ed) == [EDGE_POWER, "sensor.old_pack_battery_power"]
    assert unit_soc_sensor(ed, "sensor.old_pack_battery_power") == (
        "sensor.old_pack_level_helper")
    readings = _read(_reader(hass, ed))
    assert readings.batteries["b2"].soc_pct == pytest.approx(35)


async def test_a_dropped_found_battery_drops_its_stat_soc(hass):
    """A battery pick that stands for the battery takes the found unit out;
    its SOC record goes with it."""
    entry, dev = _device(hass, "old_pack")
    _entity(hass, entry, dev, "sensor.old_pack_charged", _KWH, 5)
    _entity(hass, entry, dev, "sensor.old_pack_discharged", _KWH, 4)
    _entity(hass, entry, dev, "sensor.old_pack_battery_power", _W, -300)
    _entity(hass, entry, dev, "sensor.old_pack_level", _PCT, 35)
    _edge(hass)
    ed = _ed(hass, {"type": "battery", "stat_energy_to": EDGE_COUNTERS[0],
                    "stat_energy_from": EDGE_COUNTERS[1]}, {
        "type": "battery", "stat_energy_to": "sensor.old_pack_charged",
        "stat_energy_from": "sensor.old_pack_discharged",
        "stat_soc": "sensor.old_pack_level"})
    found = "sensor.old_pack_battery_power"
    assert found in battery_units(ed)
    assert unit_soc_sensor(ed, found) == "sensor.old_pack_level"
    yield_found_units_to_picks(ed, battery_pick="sensor.house_battery_total")
    assert found not in battery_units(ed)
    assert unit_soc_sensor(ed, found) is None


# ── 2. the reporter's home: b2 reads its own level ──────────────────────


async def test_the_reporters_home_reads_b2_from_its_stat_soc(hass):
    """Before: b2 0 % (``soc_status``), the fleet 40 %."""
    _edge(hass, 80)
    _flow(hass, 60)
    ed = _ed(hass, _edge_src(), _flow_src())
    r = _reader(hass, ed)
    readings = _read(r)
    assert readings.batteries["b1"].soc_pct == pytest.approx(80)
    assert readings.batteries["b2"].soc_pct == pytest.approx(60)
    assert readings.battery_soc == pytest.approx(70)
    assert readings.battery_soc_units_read == 2


async def test_a_pick_the_guess_would_not_find_is_read(hass):
    """The pick is read, though the device holds another level."""
    _edge(hass, 80)
    _flow(hass, 60)
    hass.states.async_set("sensor.flow_level_smoothed", "62", _PCT)
    ed = _ed(hass, _edge_src(), _flow_src(soc="sensor.flow_level_smoothed"))
    readings = _read(_reader(hass, ed))
    assert readings.batteries["b2"].soc_pct == pytest.approx(62)
    assert readings.battery_soc == pytest.approx(71)


async def test_the_picked_sensor_wins_over_a_saved_guess(hass):
    """A guess made before is not kept over the user's pick."""
    _edge(hass, 80)
    _flow(hass, 60)
    ed = _ed(hass, _edge_src(), _flow_src())
    r = _reader(hass, ed)
    r._soc_entity_by_power[FLOW_TO] = FLOW_STATUS     # the old build's pick
    assert r._auto_detect_battery_soc(FLOW_TO) == FLOW_LEVEL
    assert _read(r).batteries["b2"].soc_pct == pytest.approx(60)


async def test_a_dark_picked_sensor_is_no_reading_and_no_guess(hass):
    """The picked level not up yet: b2 has no SOC (the card shows —), not
    a guess from its device and not 0 %."""
    _edge(hass, 80)
    _flow(hass, level_loaded=False)
    ed = _ed(hass, _edge_src(), _flow_src())
    r = _reader(hass, ed)
    readings = _read(r)
    assert readings.batteries["b2"].soc_pct is None
    assert readings.battery_soc == pytest.approx(80)
    # known and unread: a warm-up gap, not a config gap
    assert readings.battery_soc_units_expected == 2
    assert readings.battery_soc_units_read == 1
    hass.states.async_set(FLOW_LEVEL, "60", _PCT)
    r._unit_soc_cycle = {}
    assert _read(r).batteries["b2"].soc_pct == pytest.approx(60)


# ── 3. no stat_soc: the guess skips the codes ───────────────────────────


async def test_with_no_stat_soc_the_guess_reads_the_level_not_the_code(hass):
    """Before: ``soc_status`` (0, no unit) was the first "soc" on the
    device and b2 read 0 %."""
    _edge(hass, 80)
    _flow(hass, 60)
    ed = _ed(hass, _edge_src(soc=None), _flow_src(soc=None))
    r = _reader(hass, ed)
    assert r._auto_detect_battery_soc(FLOW_TO) == FLOW_LEVEL
    readings = _read(r)
    assert readings.batteries["b2"].soc_pct == pytest.approx(60)
    assert readings.battery_soc == pytest.approx(70)


@pytest.mark.parametrize("status,limit", [(0, 0), (1, 2), (0, 1)])
async def test_a_code_is_never_a_level(hass, status, limit):
    """Whatever the codes say, with no level on the device nothing is
    found and nothing is waited for."""
    entry, dev = _device(hass, FLOW)
    _entity(hass, entry, dev, FLOW_STATUS, _CODE, status)
    _entity(hass, entry, dev, FLOW_LIMIT, _CODE, limit)
    _entity(hass, entry, dev, FLOW_TO, _W, 0)
    r = _bare(hass)
    assert r._auto_detect_battery_soc(FLOW_TO) is None
    assert r._soc_candidate_exists(FLOW_TO) is False


async def test_a_soc_name_in_percent_is_still_found(hass):
    """The name path stays: a SOC sensor with no battery class, in %."""
    entry, dev = _device(hass, "pack_x")
    _entity(hass, entry, dev, "sensor.pack_x_soc_status", _CODE, 0)
    _entity(hass, entry, dev, "sensor.pack_x_battery_soc_value",
            {"unit_of_measurement": "%"}, 47)
    _entity(hass, entry, dev, "sensor.pack_x_power", _W, 0)
    r = _bare(hass)
    assert r._auto_detect_battery_soc("sensor.pack_x_power") == (
        "sensor.pack_x_battery_soc_value")


async def test_the_probe_still_waits_for_a_level_not_up_yet(hass):
    """Registered with %, no state yet: known, so the fleet waits."""
    entry, dev = _device(hass, "pack_y")
    _entity(hass, entry, dev, "sensor.pack_y_soc_status", _CODE, 0)
    _entity(hass, entry, dev, "sensor.pack_y_soc_value",
            {"unit_of_measurement": "%"}, None)
    _entity(hass, entry, dev, "sensor.pack_y_power", _W, 0)
    r = _bare(hass)
    assert r._auto_detect_battery_soc("sensor.pack_y_power") is None
    assert r._soc_candidate_exists("sensor.pack_y_power") is True


# ── 4. one battery: unchanged ───────────────────────────────────────────


async def test_one_battery_reads_its_stat_soc_as_before(hass):
    _flow(hass, 60)
    ed = _ed(hass, _flow_src())
    readings = _read(_reader(hass, ed))
    assert readings.battery_soc == pytest.approx(60)


async def test_sems_own_soc_pick_still_wins(hass):
    _edge(hass, 80)
    _flow(hass, 60)
    hass.states.async_set("sensor.house_soc", "55", _PCT)
    ed = _ed(hass, _edge_src(), _flow_src())
    readings = _read(_reader(hass, ed, battery_soc_sensor="sensor.house_soc"))
    assert readings.battery_soc == pytest.approx(55)
    assert readings.batteries["b2"].soc_pct == pytest.approx(60)


async def test_one_battery_read_takes_its_own_pick_not_the_first(hass):
    """A battery with counters and no power sensor is listed first, with
    its own stat_soc. SEM reads the other battery alone: its SOC is that
    battery's pick, not the first source's."""
    entry, dev = _device(hass, "old_pack")
    _entity(hass, entry, dev, "sensor.old_pack_charged", _KWH, 5)
    _entity(hass, entry, dev, "sensor.old_pack_discharged", _KWH, 4)
    _entity(hass, entry, dev, "sensor.old_pack_level", _PCT, 15)
    _flow(hass, 60)
    ed = _ed(hass, {
        "type": "battery", "stat_energy_to": "sensor.old_pack_charged",
        "stat_energy_from": "sensor.old_pack_discharged",
        "stat_soc": "sensor.old_pack_level"}, _flow_src())
    assert battery_units(ed) == [FLOW_TO]
    assert ed.battery_soc == "sensor.old_pack_level"
    readings = _read(_reader(hass, ed))
    assert readings.battery_soc == pytest.approx(60)


async def test_one_battery_with_no_pick_never_takes_another_sources(hass):
    """The battery listed first has a pick and no power sensor; the battery
    SEM reads has no pick. Its SOC is guessed from its own device, not
    taken from the other battery (review, #1373)."""
    entry, dev = _device(hass, "old_pack")
    _entity(hass, entry, dev, "sensor.old_pack_charged", _KWH, 5)
    _entity(hass, entry, dev, "sensor.old_pack_discharged", _KWH, 4)
    _entity(hass, entry, dev, "sensor.old_pack_level", _PCT, 15)
    _edge(hass, 80)
    ed = _ed(hass, {
        "type": "battery", "stat_energy_to": "sensor.old_pack_charged",
        "stat_energy_from": "sensor.old_pack_discharged",
        "stat_soc": "sensor.old_pack_level"}, _edge_src(soc=None))
    assert battery_units(ed) == [EDGE_POWER]
    assert ed.battery_soc == "sensor.old_pack_level"
    readings = _read(_reader(hass, ed))
    assert readings.battery_soc == pytest.approx(80)


def test_a_config_with_no_record_keeps_the_first_pick():
    """A config built without the per-battery record answers as before."""
    from custom_components.solar_energy_management.ha_energy_reader import (
        EnergyDashboardConfig,
        one_battery_soc,
    )
    cfg = EnergyDashboardConfig()
    cfg.battery_power = "sensor.batt"
    cfg.battery_power_list = ["sensor.batt"]
    cfg.battery_soc = "sensor.soc"
    assert one_battery_soc(cfg) == "sensor.soc"
    cfg.battery_power_list = []
    assert one_battery_soc(cfg) == "sensor.soc"
    cfg.battery_power_list = ["sensor.batt", "sensor.batt2"]
    assert one_battery_soc(cfg) is None


async def test_one_battery_of_a_fleet_never_takes_the_houses_one_soc(hass):
    """No picks; b2's level not up yet. The only SOC sensor in the house is
    b1's: b2 has no SOC until its own comes up, then it reads 60 % (review:
    the whole-house scan gave b2 b1's sensor, and kept it)."""
    _edge(hass, 80)
    _flow(hass, level_loaded=False)
    ed = _ed(hass, _edge_src(soc=None), _flow_src(soc=None))
    r = _reader(hass, ed)
    assert r._auto_detect_battery_soc(FLOW_TO) is None
    readings = _read(r)
    assert readings.batteries["b2"].soc_pct is None
    hass.states.async_set(FLOW_LEVEL, "60", _PCT)
    assert _read(r).batteries["b2"].soc_pct == pytest.approx(60)


async def test_one_battery_still_finds_its_soc_on_another_device(hass):
    """The whole-house scan stays for a home with one battery (#529)."""
    entry, dev = _device(hass, "pack_z")
    _entity(hass, entry, dev, "sensor.pack_z_power", _W, 0)
    hass.states.async_set("sensor.house_battery_state_of_charge", "44", _PCT)
    ed = _ed(hass, {"type": "battery", "stat_rate": "sensor.pack_z_power"})
    r = _reader(hass, ed)
    assert r._auto_detect_battery_soc("sensor.pack_z_power") == (
        "sensor.house_battery_state_of_charge")


async def test_a_declared_level_beats_a_soc_name_in_percent(hass):
    """A limit in % registered first is not the level (review, #1373)."""
    entry, dev = _device(hass, "pk")
    _entity(hass, entry, dev, "sensor.pk_min_soc",
            {"unit_of_measurement": "%"}, 10)
    _entity(hass, entry, dev, "sensor.pk_level", _PCT, 70)
    _entity(hass, entry, dev, "sensor.pk_power", _W, 0)
    assert _bare(hass)._auto_detect_battery_soc("sensor.pk_power") == (
        "sensor.pk_level")


async def test_a_declared_soc_name_beats_a_declared_other(hass):
    """Two declared levels: the one whose name says SOC wins."""
    entry, dev = _device(hass, "pk")
    _entity(hass, entry, dev, "sensor.pk_state_of_health", _PCT, 97)
    _entity(hass, entry, dev, "sensor.pk_battery_soc", _PCT, 41)
    _entity(hass, entry, dev, "sensor.pk_power", _W, 0)
    assert _bare(hass)._auto_detect_battery_soc("sensor.pk_power") == (
        "sensor.pk_battery_soc")


# ── 5. setup: the screen and the picker ─────────────────────────────────


async def test_the_setup_screen_shows_the_fleet_average(hass):
    from custom_components.solar_energy_management.setup_check import (
        build_setup_check,
    )
    _edge(hass, 80)
    _flow(hass, 60)
    two = _ed(hass, _edge_src(), _flow_src())
    assert build_setup_check(hass, two).soc == pytest.approx(70)
    # a fleet with no pick at all shows no level, not one battery's
    none = _ed(hass, _edge_src(soc=None), _flow_src(soc=None))
    assert build_setup_check(hass, none).soc is None
    # a pick for b2 only is part of the fleet: no level either
    part = _ed(hass, _edge_src(soc=None), _flow_src())
    assert build_setup_check(hass, part).soc is None


async def test_the_setup_screen_shows_the_one_batterys_own_pick(hass):
    from custom_components.solar_energy_management.setup_check import (
        build_setup_check,
    )
    entry, dev = _device(hass, "old_pack")
    _entity(hass, entry, dev, "sensor.old_pack_charged", _KWH, 5)
    _entity(hass, entry, dev, "sensor.old_pack_discharged", _KWH, 4)
    _entity(hass, entry, dev, "sensor.old_pack_level", _PCT, 15)
    _flow(hass, 60)
    ed = _ed(hass, {
        "type": "battery", "stat_energy_to": "sensor.old_pack_charged",
        "stat_energy_from": "sensor.old_pack_discharged",
        "stat_soc": "sensor.old_pack_level"}, _flow_src())
    assert build_setup_check(hass, ed).soc == pytest.approx(60)


class _Picker:
    """The setup flow's own methods on a stand-in with a dashboard config."""

    def __init__(self, ed):
        from custom_components.solar_energy_management.config_flow import (
            SolarEnergyManagementConfigFlow as Flow,
        )
        self._energy_dashboard_config = ed
        self._setup_check = MagicMock(grid_entity="sensor.grid_power")
        self._found_sources = Flow._found_sources.__get__(self)
        self._own_sensor_picks = Flow._own_sensor_picks.__get__(self)
        self._check = Flow._check.__get__(self)
        self._one_solar = lambda: True
        self._one_combined_battery = Flow._one_combined_battery.__get__(self)


def test_the_picker_offers_no_one_sensor_as_found_on_a_fleet():
    """On a fleet SEM reads the average: b1's pick is not "what SEM reads",
    so it is not the prefill, and a pick of it is saved as a pick."""
    two = _parse_prefs(MagicMock(), {"energy_sources": [
        GRID, _edge_src(), _flow_src()], "device_consumption": []}, quiet=True)
    fleet = _Picker(two)
    assert fleet._found_sources()["battery_soc_sensor"] is None
    assert fleet._own_sensor_picks(
        {"own_sensors": {"battery_soc_sensor": EDGE_SOC}}) == {
            "battery_soc_sensor": EDGE_SOC}
    # one battery: its pick is what SEM reads; sent back unchanged, no pin
    one = _Picker(_parse_prefs(MagicMock(), {"energy_sources": [
        GRID, _flow_src()], "device_consumption": []}, quiet=True))
    assert one._found_sources()["battery_soc_sensor"] == FLOW_LEVEL
    assert one._own_sensor_picks(
        {"own_sensors": {"battery_soc_sensor": FLOW_LEVEL}}) == {}


# ── 6. the diagnostics name each battery's SOC sensor ───────────────────


async def test_the_diagnostics_name_each_batterys_soc_sensor(hass, tmp_path):
    from custom_components.solar_energy_management.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    _edge(hass, 80)
    _flow(hass, 60)
    ed = _ed(hass, _edge_src(soc=None), _flow_src())
    r = _reader(hass, ed)
    _read(r)
    mock_hass = MagicMock()
    mock_hass.config.config_dir = str(tmp_path)

    async def _executor(func, *args, **kwargs):
        return func(*args, **kwargs)
    mock_hass.async_add_executor_job = _executor
    mock_hass.states.get = hass.states.get
    entry = MagicMock()
    entry.entry_id, entry.version, entry.domain = "e1373", 7, DOMAIN
    entry.title, entry.data, entry.options = "SEM", {}, {}
    coordinator = MagicMock()
    coordinator.last_update_success = True
    coordinator.update_interval = timedelta(seconds=10)
    coordinator._observer_mode = False
    coordinator._load_manager = None
    coordinator.data = {}
    coordinator._energy_dashboard_config = ed
    coordinator._sensor_reader = r
    entry.runtime_data = coordinator
    mock_hass.data = {DOMAIN: {entry.entry_id: coordinator}}

    result = await async_get_config_entry_diagnostics(mock_hass, entry)
    eds = result["energy_dashboard"]
    assert eds["per_source_lists"]["battery_unit_soc"] == {FLOW_TO: FLOW_LEVEL}
    socs = eds["per_source_readings"]["battery_soc"]
    assert socs[FLOW_TO]["entity"] == FLOW_LEVEL
    assert socs[FLOW_TO]["picked_in_ha"] is True
    assert socs[FLOW_TO]["state"] == "60"
    assert socs[EDGE_POWER]["entity"] == EDGE_SOC
    assert socs[EDGE_POWER]["picked_in_ha"] is False


# ── 7. AST: nothing reads the first stat_soc for one battery ──────────────────

#: Every function that reads a dashboard config's first ``stat_soc``
#: (``battery_soc``) or the list of all of them (``battery_soc_list``), and
#: why it may. Entry N of the list is not battery bN, and the first is not
#: the one battery SEM reads: ask ``unit_soc_sensor`` / ``one_battery_soc``.
DECLARED_SOC_FIELD_READERS = {
    "_extract_battery_config": "the parser fills them",
    "one_battery_soc": "the rule: the first only when no battery is read",
    "unpowered_battery_socs": "no battery power read: every pick, for the average",
    "_wired": "lists every SOC sensor of the dashboard, for no battery",
}
_SOC_FIELDS = {"battery_soc", "battery_soc_list"}
# Any name a dashboard config goes by: ``ed``, ``_ed``, ``ed_config``,
# ``cfg``, ``dashboard`` … (review: ``_ed`` in the coordinator was missed).
_CONFIG_NAME = re.compile(
    r"^_*(?:ed|cfg|config|dashboard)(?:_\w+)?$|_ed$|_cfg$|_config$")


def _is_config(node) -> bool:
    return ((isinstance(node, ast.Name) and _CONFIG_NAME.search(node.id))
            or (isinstance(node, ast.Attribute)
                and node.attr == "_energy_dashboard_config"))


def _soc_field_readers(source: str) -> set:
    found = set()
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if (isinstance(node, ast.Attribute) and node.attr in _SOC_FIELDS
                    and _is_config(node.value)):
                found.add(func.name)
            if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                    and node.func.id == "getattr" and len(node.args) >= 2
                    and _is_config(node.args[0])
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value in _SOC_FIELDS):
                found.add(func.name)
    return found


def test_no_function_reads_the_first_stat_soc_for_a_battery():
    found = set()
    for path in ROOT.rglob("*.py"):
        if {"tests", "scripts", "tools", "__pycache__"} & set(path.parts):
            continue
        found |= _soc_field_readers(path.read_text())
    assert found - set(DECLARED_SOC_FIELD_READERS) == set(), (
        "a new reader of the dashboard's battery_soc / battery_soc_list: "
        "the first pick is not battery b1's, nor the one battery SEM reads "
        "— use unit_soc_sensor(ed, unit) or one_battery_soc(ed)")
    assert set(DECLARED_SOC_FIELD_READERS) - found == set(), "stale entry"


def test_the_guard_finds_the_old_read():
    """Twin: the read this fix removed is found."""
    old = (
        "def read_power(self, ed):\n"
        "    ed_soc = ed.battery_soc\n"
        "def setup(hass, cfg):\n"
        "    return getattr(cfg, 'battery_soc', None)\n"
        "def other(self):\n"
        "    return self._energy_dashboard_config.battery_soc_list[1]\n"
        "def cycles(self, _ed):\n"
        "    return getattr(_ed, 'battery_soc', None) if _ed else None\n"
        "def fine(readings):\n"
        "    return readings.battery_soc\n")
    assert _soc_field_readers(old) == {"read_power", "setup", "other", "cycles"}


# ── 7. review round 2: a name two batteries share, settings, gone picks ──

HOME1 = "sensor.home_battery_power"
HOME1_SOC = "sensor.home_battery_soc"
HOME2 = "sensor.home_battery_2_power"
HOME2_SOC = "sensor.home_battery_2_soc"


def _homes(hass, *units):
    for unit in units:
        hass.states.async_set(unit, "0", _W)
    return _ed(hass, *({"type": "battery", "stat_rate": u} for u in units))


async def test_b2_never_takes_b1s_level_through_a_shared_name(hass):
    """``home_battery`` is the stem of both names. b2's own level is not up
    yet: b2 has no SOC, then its own. Before: b2 took b1's 80 % through the
    shorter stem and kept it."""
    hass.states.async_set(HOME1_SOC, "80", _PCT)
    r = _reader(hass, _homes(hass, HOME1, HOME2))
    assert r._auto_detect_battery_soc(HOME2) is None
    readings = _read(r)
    assert readings.batteries["b2"].soc_pct is None
    # the stem is b1's own: its name adds one word to it, b2's two
    assert readings.batteries["b1"].soc_pct == pytest.approx(80)
    hass.states.async_set(HOME2_SOC, "60", _PCT)
    assert r._auto_detect_battery_soc(HOME2) == HOME2_SOC
    readings = _read(r)
    assert readings.batteries["b2"].soc_pct == pytest.approx(60)
    assert readings.batteries["b1"].soc_pct == pytest.approx(80)


async def test_listed_the_other_way_b1_never_takes_b2s_level(hass):
    hass.states.async_set(HOME1_SOC, "80", _PCT)
    r = _reader(hass, _homes(hass, HOME2, HOME1))
    assert r._auto_detect_battery_soc(HOME2) is None
    assert not r._soc_candidate_exists(HOME2)
    assert r._auto_detect_battery_soc(HOME1) == HOME1_SOC


async def test_ha_numbered_twins_keep_the_first_level_for_b1(hass):
    """HA numbers a second entity of the same name: ``…_power_2``."""
    hass.states.async_set(HOME1_SOC, "80", _PCT)
    twin = "sensor.home_battery_power_2"
    r = _reader(hass, _homes(hass, HOME1, twin))
    assert r._auto_detect_battery_soc(HOME1) == HOME1_SOC
    assert r._auto_detect_battery_soc(twin) is None


async def test_a_guess_from_a_one_battery_home_is_dropped_when_b1_comes(hass):
    """Alone, b2's short name found ``home_battery_soc``; once b1 is added,
    that sensor is b1's."""
    hass.states.async_set(HOME1_SOC, "80", _PCT)
    r = _reader(hass, _homes(hass, HOME2))
    assert r._auto_detect_battery_soc(HOME2) == HOME1_SOC
    r.set_energy_dashboard_config(_homes(hass, HOME1, HOME2))
    assert r._auto_detect_battery_soc(HOME2) is None


async def test_on_their_own_devices_both_find_their_level(hass):
    """A name both share is left to the device: b1 still finds its level."""
    e1, d1 = _device(hass, "home1")
    _entity(hass, e1, d1, HOME1, _W, 0)
    _entity(hass, e1, d1, HOME1_SOC, _PCT, 80)
    e2, d2 = _device(hass, "home2")
    _entity(hass, e2, d2, HOME2, _W, 0)
    _entity(hass, e2, d2, HOME2_SOC, _PCT, 60)
    r = _reader(hass, _homes(hass, HOME1, HOME2))
    assert r._auto_detect_battery_soc(HOME1) == HOME1_SOC
    assert r._auto_detect_battery_soc(HOME2) == HOME2_SOC


async def test_one_battery_still_finds_its_level_by_the_short_name(hass):
    hass.states.async_set(HOME1_SOC, "80", _PCT)
    r = _reader(hass, _homes(hass, HOME2))
    assert r._auto_detect_battery_soc(HOME2) == HOME1_SOC


async def test_a_declared_setting_never_beats_the_declared_level(hass):
    """``min_soc`` declared a battery level in %, registered first; the
    word ``max`` in the device's name is no setting."""
    entry, dev = _device(hass, "inv_max")
    _entity(hass, entry, dev, "sensor.inv_max_min_soc", _PCT, 10)
    _entity(hass, entry, dev, "sensor.inv_max_bms_soc", _PCT, 55)
    _entity(hass, entry, dev, "sensor.inv_max_pbattery", _W, 0)
    assert _bare(hass)._auto_detect_battery_soc("sensor.inv_max_pbattery") == (
        "sensor.inv_max_bms_soc")


async def test_a_setting_alone_is_still_found_as_before(hass):
    entry, dev = _device(hass, "pk")
    _entity(hass, entry, dev, "sensor.pk_target_soc", _PCT, 90)
    _entity(hass, entry, dev, "sensor.pk_pwr", _W, 0)
    assert _bare(hass)._auto_detect_battery_soc("sensor.pk_pwr") == (
        "sensor.pk_target_soc")


async def test_a_pick_that_names_no_sensor_is_not_waited_for(hass):
    """b2's pick was renamed away: no SOC for b2, no guess from its device,
    and the fleet does not wait for it."""
    _edge(hass, 80)
    _flow(hass, 60)
    ed = _ed(hass, _edge_src(), _flow_src(soc="sensor.gone_level"))
    r = _reader(hass, ed)
    assert r._auto_detect_battery_soc(FLOW_TO) is None
    assert not r._soc_candidate_exists(FLOW_TO)
    readings = _read(r)
    assert readings.batteries["b2"].soc_pct is None
    assert readings.battery_soc_units_expected == 1
    assert readings.battery_soc_partial is False


async def test_a_yaml_pick_is_waited_for_until_ha_has_started(hass):
    """No registry entry and no state yet: while HA starts it may still
    come (a YAML sensor), so the fleet waits; once HA runs it is gone."""
    from homeassistant.core import CoreState
    _edge(hass, 80)
    _flow(hass, 60)
    ed = _ed(hass, _edge_src(), _flow_src(soc="sensor.yaml_level"))
    r = _reader(hass, ed)
    hass.set_state(CoreState.starting)
    try:
        assert r._auto_detect_battery_soc(FLOW_TO) == "sensor.yaml_level"
        assert _read(r).battery_soc_units_expected == 2
    finally:
        hass.set_state(CoreState.running)
    assert r._auto_detect_battery_soc(FLOW_TO) is None


async def test_a_pick_known_to_the_registry_is_waited_for(hass):
    """Registered and no state yet: a sensor coming up, not a gone one."""
    _edge(hass, 80)
    _flow(hass, level_loaded=False)
    r = _reader(hass, _ed(hass, _edge_src(), _flow_src()))
    assert r._auto_detect_battery_soc(FLOW_TO) == FLOW_LEVEL
    assert _read(r).battery_soc_units_expected == 2


def test_two_picks_and_no_power_give_no_home_soc():
    """No battery power read and two batteries picked a SOC: the first
    pick is one battery of two, not the home's level."""
    from custom_components.solar_energy_management.ha_energy_reader import (
        EnergyDashboardConfig,
        one_battery_soc,
    )
    cfg = EnergyDashboardConfig()
    cfg.battery_soc = "sensor.a_soc"
    cfg.battery_soc_list = ["sensor.a_soc", "sensor.b_soc"]
    assert one_battery_soc(cfg) is None
    cfg.battery_soc_list = ["sensor.a_soc"]
    assert one_battery_soc(cfg) == "sensor.a_soc"


async def test_two_picks_and_no_power_read_give_their_average(hass):
    """Counters only, no power sensor found: the home's level is the
    average of the two picks, and one down is a wait."""
    hass.states.async_set("sensor.a_soc", "80", _PCT)
    hass.states.async_set("sensor.b_soc", "40", _PCT)
    ed = _ed(hass,
             {"type": "battery", "stat_energy_to": "sensor.a_in",
              "stat_energy_from": "sensor.a_out", "stat_soc": "sensor.a_soc"},
             {"type": "battery", "stat_energy_to": "sensor.b_in",
              "stat_energy_from": "sensor.b_out", "stat_soc": "sensor.b_soc"})
    assert battery_units(ed) == []
    r = _reader(hass, ed)
    assert _read(r).battery_soc == pytest.approx(60)
    from custom_components.solar_energy_management.setup_check import (
        build_setup_check,
    )
    assert build_setup_check(hass, ed).soc == pytest.approx(60)
    hass.states.async_set("sensor.b_soc", "unavailable", {})
    assert _read(r).battery_soc == pytest.approx(60)    # held, not a's 80
    r2 = _reader(hass, ed)
    _read(r2)
    assert r2._last_valid_soc is None                   # never read
