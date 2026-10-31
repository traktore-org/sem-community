"""#1236 — a second row whose kWh is not inside the power SEM reads.

A second inverter or battery whose counter sits on a device SEM already reads
(a Shelly 2PM channel, a Deye BAT2), or beside a link SEM cannot place (a
template, a site meter), gets no power sensor: a second one could count the
same watts twice. Its counter still shows the truth. The reader sets the kWh
of all counters of the kind against the power it read over the same time.
When the set-aside counters gained and that power explains under half of it,
a Repair names them. No reading is ever changed. A link that already holds
both rows leaves no gap, and nothing is raised.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.ha_energy_reader import (
    _parse_prefs,
    left_alone_counters,
    unsourced_counters,
)

from .test_1226_every_unit_power import (
    _KWH,
    _W,
    _battery,
    _device,
    _entity,
    _inverter,
    _prefs,
    _reader,
    _solar,
    _batt,
)

MONO = "time.monotonic"


def _issue(hass, kind):
    return ir.async_get(hass).async_get_issue(DOMAIN, f"unseen_power_row_{kind}")


def _run(hass, reader, *, minutes, counters, watts, power, start=0.0,
         step=60.0, hold=None):
    """One cycle a minute: each counter gains its row's power over the step,
    ``power`` is what the linked sensor reads. Returns the last readings."""
    t = start
    readings = None
    for _ in range(int(minutes * 60 / step)):
        t += step
        for eid, w in zip(counters, watts, strict=True):
            old = float(hass.states.get(eid).state)
            hass.states.async_set(eid, f"{old + w * step / 3_600_000.0:.5f}", _KWH)
        for eid, value in power.items():
            hass.states.async_set(eid, str(value), _W)
        with patch(MONO, return_value=t):
            readings = reader.read_power()
    return readings, t


async def _shelly(hass, *, p1=3000, p2=2000):
    """One device: channel 1 with power and counter, channel 2 counter only."""
    entry, dev = _device(hass, "shelly")
    for eid, dc, value in [("sensor.shelly_ch1_energy", "energy", 100),
                           ("sensor.shelly_ch2_energy", "energy", 80),
                           ("sensor.shelly_ch1_power", "power", p1)]:
        _entity(hass, entry, dev, eid, dc, value)
    ed = _parse_prefs(hass, _prefs(
        _solar("sensor.shelly_ch1_energy", "sensor.shelly_ch1_power"),
        _solar("sensor.shelly_ch2_energy")), quiet=True)
    return ed


async def test_the_derive_names_the_counter_it_set_aside(hass):
    ed = await _shelly(hass)
    assert left_alone_counters(ed, "solar") == ["sensor.shelly_ch2_energy"]
    # …and does not call it missing: that is the #1226 rule, unchanged
    assert unsourced_counters(ed, "solar") == []


async def test_a_second_channel_the_power_does_not_hold_raises_once(hass):
    ed = await _shelly(hass)
    reader = _reader(hass, ed)
    _, t = _run(hass, reader, minutes=20,
                counters=["sensor.shelly_ch1_energy", "sensor.shelly_ch2_energy"],
                watts=[3000, 2000], power={"sensor.shelly_ch1_power": 3000})
    issue = _issue(hass, "solar")
    assert issue is not None
    assert issue.translation_key == "unseen_power_row"
    assert issue.translation_placeholders["energy_entity"] == "sensor.shelly_ch2_energy"
    assert issue.translation_placeholders["power_entity"] == "sensor.shelly_ch1_power"
    assert issue.is_fixable is False and issue.is_persistent is False


async def test_the_power_is_never_changed(hass):
    """The gap is said, not filled: solar stays the one linked sensor."""
    ed = await _shelly(hass)
    reader = _reader(hass, ed)
    readings, _ = _run(hass, reader, minutes=20,
                       counters=["sensor.shelly_ch1_energy",
                                 "sensor.shelly_ch2_energy"],
                       watts=[3000, 2000],
                       power={"sensor.shelly_ch1_power": 3000})
    assert _issue(hass, "solar") is not None
    assert readings.solar_power == pytest.approx(3000)


async def test_a_site_total_that_holds_both_rows_raises_nothing(hass):
    """Row A links a site meter (another device) that reads BOTH rows; row B
    has its counter only. The counters gain what the total shows."""
    a_counter, _ = _inverter(hass, "inv_a")
    b_counter, _ = _inverter(hass, "inv_b")
    entry, dev = _device(hass, "home_manager")
    _entity(hass, entry, dev, "sensor.home_manager_pv_power", "power", 5000)
    ed = _parse_prefs(hass, _prefs(
        _solar(a_counter, "sensor.home_manager_pv_power"),
        _solar(b_counter)), quiet=True)
    assert left_alone_counters(ed, "solar") == [b_counter]
    reader = _reader(hass, ed)
    readings, _ = _run(hass, reader, minutes=30, counters=[a_counter, b_counter],
                       watts=[3000, 2000],
                       power={"sensor.home_manager_pv_power": 5000})
    assert _issue(hass, "solar") is None
    assert readings.solar_power == pytest.approx(5000)


async def test_a_site_total_that_holds_one_row_raises(hass):
    """The same homes, but the total is row A alone (3000 W); row B gains."""
    a_counter, _ = _inverter(hass, "inv_a")
    b_counter, _ = _inverter(hass, "inv_b")
    entry, dev = _device(hass, "home_manager")
    _entity(hass, entry, dev, "sensor.home_manager_pv_power", "power", 3000)
    ed = _parse_prefs(hass, _prefs(
        _solar(a_counter, "sensor.home_manager_pv_power"),
        _solar(b_counter)), quiet=True)
    reader = _reader(hass, ed)
    _run(hass, reader, minutes=30, counters=[a_counter, b_counter],
         watts=[3000, 2000], power={"sensor.home_manager_pv_power": 3000})
    issue = _issue(hass, "solar")
    assert issue is not None
    assert issue.translation_placeholders["energy_entity"] == b_counter


async def test_a_second_battery_the_power_does_not_hold_raises(hass):
    a_counters, _ = _battery(hass, "pack_a")
    b_counters, _ = _battery(hass, "pack_b")
    entry, dev = _device(hass, "home_manager")
    _entity(hass, entry, dev, "sensor.all_batteries_power", "power", 1500)
    ed = _parse_prefs(hass, _prefs(
        _batt(a_counters, "sensor.all_batteries_power"), _batt(b_counters)),
        quiet=True)
    assert set(left_alone_counters(ed, "battery")) == set(b_counters)
    reader = _reader(hass, ed)
    # pack A charges at 1500 W (the link), pack B at 1500 W (unseen)
    _run(hass, reader, minutes=40,
         counters=[a_counters[0], a_counters[1], b_counters[0], b_counters[1]],
         watts=[1500, 0, 1500, 0],
         power={"sensor.all_batteries_power": 1500})
    issue = _issue(hass, "battery")
    assert issue is not None
    assert issue.translation_placeholders["power_entity"] == "sensor.all_batteries_power"


async def test_a_second_battery_inside_the_total_raises_nothing(hass):
    a_counters, _ = _battery(hass, "pack_a")
    b_counters, _ = _battery(hass, "pack_b")
    entry, dev = _device(hass, "home_manager")
    _entity(hass, entry, dev, "sensor.all_batteries_power", "power", 3000)
    ed = _parse_prefs(hass, _prefs(
        _batt(a_counters, "sensor.all_batteries_power"), _batt(b_counters)),
        quiet=True)
    reader = _reader(hass, ed)
    _run(hass, reader, minutes=40,
         counters=[a_counters[0], a_counters[1], b_counters[0], b_counters[1]],
         watts=[1500, 0, 1500, 0],
         power={"sensor.all_batteries_power": 3000})
    assert _issue(hass, "battery") is None


async def test_a_small_gain_is_noise(hass):
    ed = await _shelly(hass)
    reader = _reader(hass, ed)
    _run(hass, reader, minutes=20,
         counters=["sensor.shelly_ch1_energy", "sensor.shelly_ch2_energy"],
         watts=[3000, 100], power={"sensor.shelly_ch1_power": 3000})
    assert _issue(hass, "solar") is None


async def test_a_gap_in_the_look_is_not_counted(hass):
    """SEM watched only every ten minutes: the power it did not read must
    not look like power it could not see."""
    ed = await _shelly(hass)
    reader = _reader(hass, ed)
    _run(hass, reader, minutes=120, step=600.0,
         counters=["sensor.shelly_ch1_energy", "sensor.shelly_ch2_energy"],
         watts=[3000, 2000], power={"sensor.shelly_ch1_power": 3000})
    assert _issue(hass, "solar") is None


async def test_a_new_reader_clears_what_an_older_one_raised(hass):
    ed = await _shelly(hass)
    ir.async_create_issue(
        hass, DOMAIN, "unseen_power_row_solar", is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key="unseen_power_row",
        translation_placeholders={"energy_entity": "x", "power_entity": "y"})
    assert _issue(hass, "solar") is not None
    reader = _reader(hass, ed)
    with patch(MONO, return_value=1.0):
        reader.read_power()
    assert _issue(hass, "solar") is None


async def test_the_repair_goes_when_nothing_is_set_aside(hass):
    ed = await _shelly(hass)
    reader = _reader(hass, ed)
    _run(hass, reader, minutes=20,
         counters=["sensor.shelly_ch1_energy", "sensor.shelly_ch2_energy"],
         watts=[3000, 2000], power={"sensor.shelly_ch1_power": 3000})
    assert _issue(hass, "solar") is not None
    ed.left_alone_counters.clear()
    with patch(MONO, return_value=99999.0):
        reader.read_power()
    assert _issue(hass, "solar") is None


async def test_one_inverter_alone_has_nothing_to_watch(hass):
    a_counter, a_power = _inverter(hass, "inv_a", 3000)
    ed = _parse_prefs(hass, _prefs(_solar(a_counter, a_power)), quiet=True)
    assert left_alone_counters(ed, "solar") == []
    reader = _reader(hass, ed)
    _run(hass, reader, minutes=20, counters=[a_counter], watts=[3000],
         power={a_power: 3000})
    assert _issue(hass, "solar") is None
