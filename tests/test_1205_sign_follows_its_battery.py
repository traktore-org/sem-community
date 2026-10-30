"""#1205 — a saved battery sign moved to another battery.

SEM learns the sign of each combined battery power sensor and saves it by
the battery's id: ``b1``, ``b2`` … That id is the battery's place in the
Energy Dashboard's list, not the battery. When a battery was removed, every
battery after it moved up one place and took the saved sign of the battery
that had been there. A battery whose sensor reads + while discharging (HA's
sign) is saved as "negate"; the next battery then read discharge as charge.

The one-battery sign had the same shape: it was kept when the one battery
was read from another sensor (a battery replaced, or the second of two left
after the first was removed).

Now the store records the sensor each sign was learned on
(``battery_learned_on``), and each Energy Dashboard read moves every sign
to its sensor's place, as the per-battery settings do (#1195). The
one-battery sign is learned again on another sensor, as the grid's is
(#1103).

Links, each driven for real through ``read_power`` and the store:

* a battery removed, added in front, two swapped, no change;
* the one-battery sign on another sensor, on the same one, through the pick;
* a store from an older build (no record) is taken where it stands;
* a read with no combined battery, or a gap, moves nothing;
* every per-battery record moves (a source scan fails on a new one);
* the real integration starts from a store saved before a battery was
  removed.
"""
from __future__ import annotations

import ast
import importlib.util
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import _parse_prefs

ROOT = Path(__file__).resolve().parent.parent
FLEET = "__fleet__"
_HAS_REAL_HA = importlib.util.find_spec(
    "pytest_homeassistant_custom_component") is not None

SOLAR = {"type": "solar", "stat_energy_from": "sensor.pv_energy",
         "stat_rate": "sensor.pv_power"}
GRID = {"type": "grid", "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
        "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
        "stat_rate": "sensor.grid_power"}


def _battery(name):
    return {"type": "battery",
            "stat_energy_from": f"sensor.{name}_discharged",
            "stat_energy_to": f"sensor.{name}_charged",
            "stat_rate": f"sensor.{name}_power"}


PAIR = {"type": "battery",
        "stat_energy_from": "sensor.verto_discharged",
        "stat_energy_to": "sensor.verto_charged",
        "power_config": {"stat_rate_from": "sensor.verto_discharge_power",
                         "stat_rate_to": "sensor.verto_charge_power"}}


def _ed(names, pair=False):
    sources = [SOLAR, GRID, *(_battery(n) for n in names)]
    if pair:
        sources.append(PAIR)
    return _parse_prefs(MagicMock(), {"energy_sources": sources,
                                      "device_consumption": []}, quiet=True)


def _w(value):
    return MagicMock(state=str(value), attributes={"unit_of_measurement": "W"})


def _kwh(value):
    return MagicMock(state=str(value), attributes={"unit_of_measurement": "kWh"})


#: Every battery DISCHARGES 1500 W. Battery a's sensor shows that as +1500
#: (HA's sign), so its sign is "negate"; b's and c's show -1500 (SEM's sign).
RAW = {"a": 1500, "b": -1500, "c": -1500}


class _Home:
    def __init__(self, names, store=None, config=None, pair=False):
        self.ed = _ed(names, pair)
        self.states = {"sensor.pv_power": _w(0), "sensor.grid_power": _w(0),
                       "sensor.verto_charge_power": _w(0),
                       "sensor.verto_discharge_power": _w(0)}
        self.states.update({f"sensor.{n}_power": _w(w) for n, w in RAW.items()})
        self.kwh = {f"sensor.{n}_{k}": 100.0
                    for n in (*RAW, "verto") for k in ("charged", "discharged")}
        hass = MagicMock()
        hass.states.get = self._get
        hass.states.async_all = MagicMock(return_value=[])
        self.reader = SensorReader(hass, dict(config or {}))
        self.reader._entity_owner = lambda eid: (None, None)   # no brand seed
        if store is not None:
            self.reader.restore_sign_state(store)
        self.reader.set_energy_dashboard_config(self.ed)
        self.reader._sign_vote_warmup = 0

    def _get(self, eid):
        if eid in self.kwh:
            return _kwh(self.kwh[eid])
        return self.states.get(eid)

    def cycle(self, n=1):
        readings = None
        for _ in range(n):
            readings = self.reader.read_power()
            for name in RAW:
                self.kwh[f"sensor.{name}_discharged"] += 0.1
        return readings

    def signs(self):
        r = self.reader
        return {b: r._battery_sign_inverted[b]
                for b, det in r._battery_sign_detected.items() if det}


def _learned(names, **kw):
    """What SEM saves after it learned every sign on this home."""
    home = _Home(names, **kw)
    home.cycle(8)
    return home, home.reader.export_sign_state()


# ── 1. Each combined battery's sign follows it ─────────────────────────────

def test_the_first_battery_removed_hands_its_sign_to_nobody(caplog):
    """The #1205 case. On the old code b1 (now battery b) took battery a's
    "negate" and read its discharge as +1500 W charge."""
    home, store = _learned(["a", "b", "c"])
    assert home.signs() == {"b1": True, "b2": False, "b3": False}
    assert store["battery_learned_on"] == {
        "b1": "sensor.a_power", "b2": "sensor.b_power", "b3": "sensor.c_power"}

    caplog.set_level(logging.INFO)
    after = _Home(["b", "c"], store=store)
    p = after.cycle()
    assert after.signs() == {"b1": False, "b2": False}
    assert p.batteries["b1"].power_w == -1500.0
    assert p.batteries["b2"].power_w == -1500.0
    assert p.battery_power == -3000.0
    assert after.reader.export_sign_state()["battery_learned_on"] == {
        "b1": "sensor.b_power", "b2": "sensor.c_power"}
    said = [r.getMessage() for r in caplog.records if "#1205" in r.getMessage()]
    assert any("sensor.a_power" in m and "dropped" in m for m in said)
    assert any("sensor.b_power" in m and "from b2 to b1" in m for m in said)


def test_a_battery_added_in_front_learns_its_own_sign():
    """On the old code battery a took b's "no correction" at b1 and was
    locked with it: its discharge read as charge for good."""
    _, store = _learned(["b", "c"])
    after = _Home(["a", "b", "c"], store=store)
    p = after.cycle()
    assert after.signs() == {"b2": False, "b3": False}, "a has no sign yet"
    assert p.batteries["b2"].power_w == p.batteries["b3"].power_w == -1500.0
    p = after.cycle(8)
    assert after.signs() == {"b1": True, "b2": False, "b3": False}
    assert p.batteries["b1"].power_w == -1500.0


def test_two_batteries_that_swap_places_keep_their_signs():
    _, store = _learned(["a", "b"])
    after = _Home(["b", "a"], store=store)
    p = after.cycle()
    assert after.signs() == {"b1": False, "b2": True}
    assert p.batteries["b1"].power_w == p.batteries["b2"].power_w == -1500.0


def test_no_change_moves_nothing_and_says_nothing(caplog):
    _, store = _learned(["a", "b", "c"])
    caplog.set_level(logging.INFO)
    after = _Home(["a", "b", "c"], store=store)
    after.cycle(3)
    assert after.signs() == {"b1": True, "b2": False, "b3": False}
    assert not [r for r in caplog.records if "#1205" in r.getMessage()]


def test_a_change_while_sem_runs_moves_what_it_learned():
    """The dashboard edit listener (#923) hands the reader the new list; the
    next read moves the signs and what was learned toward one."""
    home, _ = _learned(["a", "b", "c"])
    r = home.reader
    r._battery_sign_evidence["b3"] = 42.0
    home.ed = _ed(["b", "c"])
    r.set_energy_dashboard_config(home.ed)
    p = home.cycle()
    assert home.signs() == {"b1": False, "b2": False}
    assert r._battery_sign_evidence["b2"] == 42.0
    assert p.batteries["b1"].power_w == -1500.0


def test_a_store_from_an_older_build_is_taken_where_it_stands():
    """No record: nothing says which battery a sign was learned on, so each
    stays at its place, as before. A sign past the last battery has no
    battery and goes. The next save has the record."""
    store = {"battery_detected": {"b1": True, "b2": True, "b3": True},
             "battery_inverted": {"b1": True, "b2": False, "b3": True},
             "battery_basis": "sensor", "battery_counters": "own"}
    after = _Home(["a", "b"], store=store)
    p = after.cycle()
    assert after.signs() == {"b1": True, "b2": False}
    assert p.batteries["b1"].power_w == -1500.0
    assert after.reader.export_sign_state()["battery_learned_on"] == {
        "b1": "sensor.a_power", "b2": "sensor.b_power"}


@pytest.mark.parametrize("names, pair", [([], True), ([], False)])
def test_a_read_with_no_combined_battery_moves_nothing(names, pair):
    _, store = _learned(["a", "b"])
    after = _Home(names, store=store, pair=pair)
    after.cycle()
    assert after.signs() == {"b1": True, "b2": False}
    assert after.reader.export_sign_state()["battery_learned_on"] == {
        "b1": "sensor.a_power", "b2": "sensor.b_power"}


def test_a_read_with_a_gap_is_no_answer():
    _, store = _learned(["a", "b"])
    after = _Home(["b"], store=store)
    after.ed.battery_power_list[:] = ["", "sensor.b_power"]
    after.reader._signs_follow_their_battery(after.ed, None)
    assert after.signs() == {"b1": True, "b2": False}


def test_every_record_of_a_battery_moves_with_it():
    """Each per-battery record (sign, evidence, counter baselines, brand
    seed, the #647 audit, the #1193 marks) follows the battery; a gone
    battery's are dropped; the one-battery records stay."""
    r = SensorReader(MagicMock(), {})
    r._battery_lock_sensors = {"b1": "sensor.a_power", "b2": "sensor.b_power",
                               "b3": "sensor.c_power", FLEET: "sensor.x"}
    for name in SensorReader._BID_STATE:
        store = getattr(r, name)
        for bid in ("b1", "b2", "b3", FLEET):
            if isinstance(store, dict):
                store[bid] = f"{name}:{bid}"
            else:
                store.add(bid)
    r._signs_follow_their_battery(_ed(["c", "b"]), None)
    for name in SensorReader._BID_STATE:
        store = getattr(r, name)
        if isinstance(store, dict):
            assert store == {"b1": f"{name}:b3", "b2": f"{name}:b2",
                             FLEET: f"{name}:{FLEET}"}, name
        else:
            assert store == {"b1", "b2", FLEET}, name
    assert r._battery_lock_sensors == {
        "b1": "sensor.c_power", "b2": "sensor.b_power", FLEET: "sensor.x"}


def test_the_waiting_and_kept_marks_are_saved_at_the_new_place():
    store = {"battery_detected": {"b1": True, "b2": True},
             "battery_inverted": {"b1": True, "b2": False},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_counters_pending": ["b2"],
             "battery_sign_kept": {"b3": True},
             "battery_learned_on": {"b1": "sensor.a_power",
                                      "b2": "sensor.b_power",
                                      "b3": "sensor.c_power"}}
    after = _Home(["c", "b"], store=store,
                  config={"battery_sign_user_flip": True})   # the check waits
    after.cycle()
    saved = after.reader.export_sign_state()
    assert {b for b, d in saved["battery_detected"].items() if d} == {"b2"}
    assert saved["battery_counters_pending"] == ["b2"]
    assert saved["battery_sign_kept"] == {"b1": True}
    assert saved["battery_learned_on"] == {"b1": "sensor.c_power",
                                             "b2": "sensor.b_power"}


@pytest.mark.parametrize("saved", ["sensor.a_power", ["b1"], {"b1": 5},
                                   {3: "sensor.a_power"}, {"b1": ""}])
def test_a_damaged_record_is_no_record(saved):
    store = {"battery_detected": {"b1": True}, "battery_inverted": {"b1": True},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_learned_on": saved}
    after = _Home(["a", "b"], store=store)
    after.cycle()
    assert after.signs() == {"b1": True}


def test_reset_forgets_the_record():
    home, _ = _learned(["a", "b"])
    home.reader.reset_sign_state()
    assert home.reader.export_sign_state()["battery_learned_on"] == {}
    assert home.reader._battery_lock_sensors == {}


# ── 2. The one-battery sign is about the sensor the battery is read from ────

def test_the_one_battery_sign_is_learned_again_on_another_sensor(caplog):
    """Battery a replaced by battery b: on the old code b took a's "negate"
    and read its discharge as +1500 W charge."""
    home, store = _learned(["a"])
    assert home.signs() == {FLEET: True}
    assert store["battery_learned_on"] == {FLEET: "sensor.a_power"}
    caplog.set_level(logging.INFO)
    after = _Home(["b"], store=store)
    p = after.cycle()
    assert after.signs() == {}
    assert p.battery_power == -1500.0
    assert any("sensor.a_power" in r.getMessage()
               and "learning the sign again" in r.getMessage()
               for r in caplog.records)
    after.cycle(8)
    assert after.signs() == {FLEET: False}


def test_the_one_battery_sign_stays_on_its_sensor():
    _, store = _learned(["a"])
    after = _Home(["a"], store=store)
    p = after.cycle()
    assert after.signs() == {FLEET: True}
    assert p.battery_power == -1500.0


def test_the_one_battery_sign_waits_while_each_battery_is_read():
    """Battery a alone, then b added, then a removed. The one-battery sign
    was learned on a; it waits through the two-battery reads and is learned
    again when b is read alone. The old code read b with a's sign."""
    _, store = _learned(["a"])
    two = _Home(["a", "b"], store=store)
    two.cycle(8)
    store = two.reader.export_sign_state()
    assert store["battery_detected"][FLEET] is True
    assert store["battery_learned_on"][FLEET] == "sensor.a_power"
    after = _Home(["b"], store=store)
    p = after.cycle()
    assert FLEET not in after.signs()
    assert p.battery_power == -1500.0


def test_the_sensor_read_is_the_pick_when_one_is_set():
    """SEM reads its own pick before the dashboard's sensor: the sign is
    about the pick, and stays while the pick does."""
    _, store = _learned(["a"], config={"battery_power_sensor": "sensor.a_power"})
    assert store["battery_learned_on"][FLEET] == "sensor.a_power"
    after = _Home(["b"], store=store,
                  config={"battery_power_sensor": "sensor.a_power"})
    p = after.cycle()
    assert after.signs()[FLEET] is True
    assert p.battery_power == -1500.0


def test_an_older_one_battery_sign_is_taken_where_it_stands():
    store = {"battery_detected": {FLEET: True}, "battery_inverted": {FLEET: True},
             "battery_basis": "sensor", "battery_counters": "own"}
    after = _Home(["a"], store=store)
    p = after.cycle()
    assert after.signs() == {FLEET: True}
    assert p.battery_power == -1500.0
    assert after.reader.export_sign_state()["battery_learned_on"][FLEET] == (
        "sensor.a_power")


def test_a_two_sensor_battery_keeps_the_one_battery_sign_waiting():
    """A pair takes no sign (#1215); the saved one stays about its sensor."""
    _, store = _learned(["a"])
    after = _Home([], store=store, pair=True)
    after.cycle()
    assert after.reader.export_sign_state()["battery_learned_on"][FLEET] == (
        "sensor.a_power")
    assert after.signs()[FLEET] is True


def test_the_one_battery_sign_waits_while_fix_battery_sign_is_on():
    """Review: "Fix battery sign" is not bound to a sensor. It was set
    against what the saved sign read, so a sign learned again under it is
    turned over. The saved one is kept (as before) until the flip is off."""
    store = {"battery_detected": {FLEET: True},
             "battery_inverted": {FLEET: False},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_learned_on": {FLEET: "sensor.x_power"}}
    flip = {"battery_sign_user_flip": True}
    after = _Home(["a"], store=store, config=flip)
    p = after.cycle(8)
    assert after.signs() == {FLEET: False}
    assert p.battery_power == -1500.0
    assert after.reader.export_sign_state()["battery_learned_on"] == {
        FLEET: "sensor.x_power"}
    off = _Home(["a"], store=after.reader.export_sign_state())
    p = off.cycle()
    assert off.signs() == {}, "with the flip off it is learned again"
    off.cycle(8)
    assert off.signs() == {FLEET: True}
    assert off.cycle().battery_power == -1500.0


def test_a_battery_sign_on_a_sensor_gone_waits_while_fix_battery_sign_is_on():
    """Second review: the same for each battery. b1's sign was learned on
    sensor x, which SEM no longer finds (renamed, or the battery replaced).
    Learned again under the flip, battery a read +1500 W while discharging.
    It stays where it stands until the flip is off, then is learned again."""
    store = {"battery_detected": {"b1": True, "b2": True},
             "battery_inverted": {"b1": False, "b2": True},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_learned_on": {"b1": "sensor.x_power",
                                    "b2": "sensor.y_power"}}
    flip = {"battery_sign_user_flip": True}
    after = _Home(["a", "b"], store=store, config=flip)
    p = after.cycle(9)
    assert after.signs() == {"b1": False, "b2": True}
    assert p.batteries["b1"].power_w == p.batteries["b2"].power_w == -1500.0
    saved = after.reader.export_sign_state()
    assert saved["battery_learned_on"] == {"b1": "sensor.x_power",
                                           "b2": "sensor.y_power"}
    off = _Home(["a", "b"], store=saved)
    off.cycle()
    assert off.signs() == {}, "with the flip off both are learned again"
    p = off.cycle(9)
    assert off.signs() == {"b1": True, "b2": False}
    assert p.batteries["b1"].power_w == p.batteries["b2"].power_w == -1500.0


def test_under_the_flip_a_gone_sensor_does_not_keep_another_battery_place():
    """The wait keeps a sign at its own place only while no saved battery
    claims it: battery b moved to b1 keeps b's sign there."""
    store = {"battery_detected": {"b1": True, "b2": True},
             "battery_inverted": {"b1": True, "b2": False},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_learned_on": {"b1": "sensor.x_power",
                                    "b2": "sensor.b_power"}}
    after = _Home(["b"] + ["c"], store=store,
                  config={"battery_sign_user_flip": True})
    after.cycle()
    assert after.signs() == {"b1": False}
    assert after.reader._battery_lock_sensors["b1"] == "sensor.b_power"


def test_with_no_saved_sign_the_flip_does_not_hold_the_old_sensor():
    """Second review: with no sign to keep, the record follows the sensor
    read, so a sign learned on it is saved as learned on it."""
    home = _Home(["a"], config={"battery_sign_user_flip": True})
    home.reader._battery_lock_sensors = {FLEET: "sensor.x_power"}
    home.cycle()
    assert home.reader._battery_lock_sensors[FLEET] == "sensor.a_power"


def test_the_audit_of_a_battery_that_moved_is_not_pruned_by_count():
    """Review: the #647 prune ran before the move and dropped audits by
    count, so battery c lost its audit when battery a was removed."""
    home, _ = _learned(["a", "b", "c"])
    r = home.reader
    audits = {b: r._battery_audit_for(b) for b in ("b1", "b2", "b3")}
    home.ed = _ed(["b", "c"])
    r.set_energy_dashboard_config(home.ed)
    assert set(r._battery_sign_audits) == {"b2", "b3"}, "a's goes at once"
    r._signs_follow_their_battery(home.ed, None)
    assert r._battery_sign_audits["b2"] is audits["b3"]
    assert r._battery_sign_audits["b1"] is audits["b2"]


@pytest.mark.parametrize("key", ["b\u00b2", "b01", "b0", "bx", "b"])
def test_a_damaged_battery_id_stops_nothing(key):
    """Review: a damaged id in the store must not stop the read."""
    store = {"battery_detected": {key: True, "b2": True},
             "battery_inverted": {key: True, "b2": False},
             "battery_basis": "sensor", "battery_counters": "own",
             "battery_learned_on": {key: "sensor.c_power",
                                      "b2": "sensor.b_power"}}
    after = _Home(["b", "c"], store=store)
    p = after.cycle()
    assert p.batteries["b1"].power_w == p.batteries["b2"].power_w == -1500.0
    assert after.reader._battery_sign_detected.get("b1") is True
    assert after.reader._battery_sign_detected.get(key) is True, "left alone"


def test_a_split_pair_audit_is_about_its_two_sensors():
    """Review: a two-sensor battery's id is a place too. Another pair at the
    same id starts its own count; it does not take the last pair's votes."""
    r = SensorReader(MagicMock(), {})
    for _ in range(3):
        r._audit_split_pair("b2", "Battery b2", 800.0, "sensor.p1_from",
                            900.0, "sensor.p1_to")
    assert r._split_pair_audits["b2"].votes == 3
    for _ in range(4):
        r._audit_split_pair("b2", "Battery b2", 800.0, "sensor.p2_from",
                            900.0, "sensor.p2_to")
    audit = r._split_pair_audits["b2"]
    assert audit.votes == 4 and not audit.flagged
    r._audit_split_pair("b2", "Battery b2", 800.0, "sensor.p2_from",
                        900.0, "sensor.p2_to")
    assert r._split_pair_audits["b2"].flagged, "its own five votes"


# ── 3. Guard: a new per-battery record must move too ───────────────────────

#: Read or written by a battery id in SensorReader, but not moved, and why.
NOT_MOVED = {
    # the record of which sensor each id is about: rebuilt by the move
    "_battery_lock_sensors": "the move's own record",
}


def _bid_keyed_attributes():
    tree = ast.parse((ROOT / "coordinator" / "sensor_reader.py").read_text())
    cls = next(n for n in tree.body
               if isinstance(n, ast.ClassDef) and n.name == "SensorReader")
    ids = {"bid", "fleet", "old"}
    found = set()

    def is_id(node):
        return (isinstance(node, ast.Name) and node.id in ids) or (
            isinstance(node, ast.Attribute) and node.attr == "_FLEET_BID")

    def own(node):
        return (isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name) and node.value.id == "self"
                and node.attr.startswith("_battery"))

    for node in ast.walk(cls):
        if isinstance(node, ast.Subscript) and own(node.value) and is_id(node.slice):
            found.add(node.value.attr)
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and own(node.func.value) and node.args and is_id(node.args[0])
                and node.func.attr in ("get", "setdefault", "pop", "add",
                                       "discard")):
            found.add(node.func.value.attr)
        if (isinstance(node, ast.Compare) and len(node.ops) == 1
                and isinstance(node.ops[0], (ast.In, ast.NotIn))
                and is_id(node.left) and own(node.comparators[0])):
            found.add(node.comparators[0].attr)
    return found


def test_every_record_kept_by_a_battery_id_is_moved():
    found = _bid_keyed_attributes()
    assert {"_battery_sign_inverted", "_battery_sign_audits",
            "_battery_sign_kept"} <= found, "the scan sees the known ones"
    missing = found - set(SensorReader._BID_STATE) - set(NOT_MOVED)
    assert not missing, (
        f"{sorted(missing)} is kept by battery id but not moved when the "
        "batteries move (#1205): add it to SensorReader._BID_STATE, or to "
        "NOT_MOVED with why")


# ── 4. The real integration ─────────────────────────────────────────────────

_needs_real_hass = pytest.mark.skipif(
    not _HAS_REAL_HA,
    reason="pytest-homeassistant-custom-component not installed; CI runs these")


@_needs_real_hass
@pytest.mark.asyncio
async def test_the_integration_starts_with_each_sign_on_its_battery(
    sem_real_hass, sem_config_entry, hass_storage,
) -> None:
    """Saved on a home of a, b, c; battery a is removed before the start."""
    from homeassistant.components.energy.data import async_get_manager

    from custom_components.solar_energy_management.const import DOMAIN

    hass = sem_real_hass
    hass.config.components.add("energy")
    manager = await async_get_manager(hass)
    await manager.async_update({"energy_sources": [
        dict(SOLAR), dict(GRID), _battery("b"), _battery("c")],
        "device_consumption": []})
    for eid, value in (("sensor.pv_power", "3000"), ("sensor.grid_power", "0"),
                       ("sensor.b_power", "-1500"), ("sensor.c_power", "-1500")):
        hass.states.async_set(eid, value, {"unit_of_measurement": "W"})

    entry = sem_config_entry
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, data={
        k: v for k, v in entry.data.items() if k != "battery_power_sensor"})
    key = f"{DOMAIN}_{entry.entry_id}_energy"
    hass_storage[key] = {"version": 1, "minor_version": 1, "key": key, "data": {
        "sign_state": {
            "grid_detected": False, "grid_inverted": False,
            "battery_detected": {"b1": True, "b2": True, "b3": True},
            "battery_inverted": {"b1": True, "b2": False, "b3": False},
            "battery_basis": "sensor", "battery_counters": "own",
            "battery_learned_on": {"b1": "sensor.a_power",
                                     "b2": "sensor.b_power",
                                     "b3": "sensor.c_power"}}}}

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    coordinator = entry.runtime_data
    reader = coordinator._sensor_reader
    assert reader._energy_dashboard_config.battery_power_list == [
        "sensor.b_power", "sensor.c_power"]
    readings = reader.read_power()
    assert reader._battery_sign_inverted.get("b1") is False
    assert readings.batteries["b1"].power_w == -1500.0
    assert readings.batteries["b2"].power_w == -1500.0

    await coordinator._storage.async_save_energy_now()
    saved = hass_storage[key]["data"]["sign_state"]
    assert {b for b, d in saved["battery_detected"].items() if d} == {"b1", "b2"}
    assert {b: saved["battery_inverted"][b] for b in ("b1", "b2")} == {
        "b1": False, "b2": False}
    assert saved["battery_learned_on"] == {"b1": "sensor.b_power",
                                             "b2": "sensor.c_power"}
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
