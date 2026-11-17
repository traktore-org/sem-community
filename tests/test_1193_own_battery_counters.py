"""#1193 — the battery sign check used another battery's energy counters.

SEM learns the sign of each combined battery power sensor from which of the
battery's energy counters rises. It found the counters by place: battery bN
got entry N of ``battery_charge_energy_list`` / ``…discharge…``. Those lists
follow the Energy Dashboard's battery order and hold every battery with a
counter, two-sensor batteries and batteries with no power sensor too, while
bN counts combined sensors first. On a home with a two-sensor battery listed
first, b1 was judged by the two-sensor battery's counters; when one charged
while the other discharged, SEM flipped b1. The one-battery read had the
same shape: it was judged by the FIRST counters in the dashboard, which can
be those of a battery with no power sensor.

Now the parser keeps each battery's own counters (``battery_unit_counters``)
and every reader asks ``unit_energy_counters``. A lock saved by the old code
on another battery's counters is learned again, once.

Links, each driven for real:

* the parser, from HA's own prefs layout (pair first, a battery with no
  power sensor, a derived sensor, one sensor named twice);
* ``read_power`` on the mixed home and the one-battery home: the sign stays
  right where the old pairing flipped it;
* the #647 audit judges each battery by its own counters;
* the saved lock: dropped when its old counters were another battery's,
  kept otherwise, kept under "Fix battery sign", and the store says so;
* the setup summary and both diagnostics name each battery's own counters;
* an AST check: no new code reads the counter lists for one battery.
"""
from __future__ import annotations

import ast
import logging
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    _parse_prefs,
    battery_units,
    unit_energy_counters,
)

ROOT = Path(__file__).resolve().parent.parent
FLEET = "__fleet__"

SOLAR = {"type": "solar", "stat_energy_from": "sensor.pv_energy",
         "stat_rate": "sensor.pv_power"}
GRID = {"type": "grid",
        "flow_from": [{"stat_energy_from": "sensor.grid_import"}],
        "flow_to": [{"stat_energy_to": "sensor.grid_export"}],
        "stat_rate": "sensor.grid_power"}

PAIR = {"type": "battery",
        "stat_energy_from": "sensor.verto_discharged",
        "stat_energy_to": "sensor.verto_charged",
        "power_config": {"stat_rate_from": "sensor.verto_discharge_power",
                         "stat_rate_to": "sensor.verto_charge_power"}}
SESSY = {"type": "battery",
         "stat_energy_from": "sensor.sessy_discharged",
         "stat_energy_to": "sensor.sessy_charged",
         "stat_rate": "sensor.sessy_power"}
SESSY2 = {"type": "battery",
          "stat_energy_from": "sensor.sessy2_discharged",
          "stat_energy_to": "sensor.sessy2_charged",
          "stat_rate": "sensor.sessy2_power"}
# A battery whose integration gives energy only (no power sensor).
OLD = {"type": "battery",
       "stat_energy_from": "sensor.old_discharged",
       "stat_energy_to": "sensor.old_charged"}

HOMES = {
    # the pair is listed first, so counters[0] is the pair's, b1 is Sessy
    "pair_first": [PAIR, SESSY],
    # one battery with power; the first counters are the old one's
    "energy_only_first": [OLD, SESSY],
    # every battery is combined: entry N of the lists IS bN's (unaffected)
    "two_combined": [SESSY, SESSY2],
    # one battery, listed first: its counters ARE the first (unaffected)
    "one_battery_first": [SESSY, OLD],
    # the same Sessy marked "Inverted" in HA, after the old battery (#1194)
    "inverted_after_old": [OLD, {
        "type": "battery", "stat_energy_from": "sensor.sessy_discharged",
        "stat_energy_to": "sensor.sessy_charged",
        "power_config": {"stat_rate_inverted": "sensor.sessy_power"}}],
}


def _ed(home):
    return _parse_prefs(MagicMock(), {"energy_sources": [SOLAR, GRID, *HOMES[home]],
                                      "device_consumption": []}, quiet=True)


def _kwh(value):
    return MagicMock(state=str(value), attributes={"unit_of_measurement": "kWh"})


def _w(value):
    return MagicMock(state=str(value), attributes={"unit_of_measurement": "W"})


class _Home:
    """A reader on one of the homes, with counters that move each cycle.

    Sessy DISCHARGES 1500 W, and its sensor is already in SEM's sign (minus
    = discharging), so it must never be flipped. The other battery CHARGES
    at the same time.
    """

    def __init__(self, home, config=None, store=None):
        self.ed = _ed(home)
        self.states = {
            "sensor.pv_power": _w(0), "sensor.grid_power": _w(0),
            "sensor.sessy_power": _w(-1500), "sensor.sessy2_power": _w(-1500),
            "sensor.verto_charge_power": _w(1200),
            "sensor.verto_discharge_power": _w(0),
        }
        self.kwh = {e: 100.0 for e in (
            "sensor.sessy_charged", "sensor.sessy_discharged",
            "sensor.sessy2_charged", "sensor.sessy2_discharged",
            "sensor.verto_charged", "sensor.verto_discharged",
            "sensor.old_charged", "sensor.old_discharged")}
        hass = MagicMock()
        hass.states.get = self._get
        hass.states.async_all = MagicMock(return_value=[])
        self.reader = SensorReader(hass, dict(config or {}))
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
            # what really happened this cycle
            for e in ("sensor.sessy_discharged", "sensor.sessy2_discharged",
                      "sensor.verto_charged", "sensor.old_charged"):
                self.kwh[e] += 0.1
        return readings


# ── 1. The parser keeps each battery's own counters ─────────────────────────

def test_the_parser_gives_each_battery_its_own_counters():
    ed = _ed("pair_first")
    assert battery_units(ed) == ["sensor.sessy_power", "sensor.verto_charge_power"]
    # the old pairing: entry 0 of the lists is the pair's, not b1's
    assert ed.battery_charge_energy_list[0] == "sensor.verto_charged"
    assert unit_energy_counters(ed, "sensor.sessy_power") == (
        "sensor.sessy_charged", "sensor.sessy_discharged")
    assert unit_energy_counters(ed, "sensor.verto_charge_power") == (
        "sensor.verto_charged", "sensor.verto_discharged")


def test_a_battery_with_no_power_sensor_is_no_unit_and_owns_no_counters():
    ed = _ed("energy_only_first")
    assert battery_units(ed) == ["sensor.sessy_power"]
    assert ed.battery_charge_energy == "sensor.old_charged", "the first counters"
    assert unit_energy_counters(ed, "sensor.sessy_power") == (
        "sensor.sessy_charged", "sensor.sessy_discharged")
    assert set(ed.battery_unit_counters) == {"sensor.sessy_power"}


def test_an_inverted_sensor_and_a_sensor_named_twice():
    inverted = {"type": "battery", "stat_energy_from": "sensor.inv_discharged",
                "stat_energy_to": "sensor.inv_charged",
                "power_config": {"stat_rate_inverted": "sensor.inv_power"}}
    twice = {**SESSY, "stat_energy_from": "sensor.other_discharged",
             "stat_energy_to": "sensor.other_charged"}
    ed = _parse_prefs(MagicMock(), {"energy_sources": [inverted, SESSY, twice],
                                    "device_consumption": []}, quiet=True)
    assert unit_energy_counters(ed, "sensor.inv_power") == (
        "sensor.inv_charged", "sensor.inv_discharged")
    # one sensor is one battery: the first source's counters stay
    assert unit_energy_counters(ed, "sensor.sessy_power") == (
        "sensor.sessy_charged", "sensor.sessy_discharged")


def test_a_derived_power_sensor_owns_the_counters_it_was_found_from(monkeypatch):
    from custom_components.solar_energy_management import ha_energy_reader as her
    monkeypatch.setattr(her, "_find_power_sensor_on_device",
                        lambda hass, energy, rules: "sensor.old_power")
    ed = _parse_prefs(MagicMock(), {"energy_sources": [OLD],
                                    "device_consumption": []}, quiet=True)
    assert battery_units(ed) == ["sensor.old_power"]
    assert unit_energy_counters(ed, "sensor.old_power") == (
        "sensor.old_charged", "sensor.old_discharged")


def test_no_record_is_no_answer():
    ed = _ed("pair_first")
    assert unit_energy_counters(ed, "sensor.nobody") is None
    assert unit_energy_counters(ed, None) is None
    assert unit_energy_counters(MagicMock(), "sensor.sessy_power") is None
    assert unit_energy_counters(None, "sensor.sessy_power") is None


# ── 2. The sign check judges each battery by its own counters ──────────────

def test_the_mixed_home_keeps_a_right_battery_right():
    """The #1193 case. On the old code b1 (Sessy) was judged by the pair's
    charge counter while it discharged, and flipped to +1500 W."""
    home = _Home("pair_first")
    p = home.cycle(8)
    r = home.reader
    assert r._battery_sign_detected.get("b1") is True, "it was judged at all"
    assert r._battery_sign_inverted["b1"] is False
    assert p.batteries["b1"].power_w == -1500.0
    assert p.batteries["b2"].power_w == 1200.0
    assert p.battery_power == -300.0


def test_the_mixed_home_still_flips_a_battery_its_own_counters_disprove():
    """The positive twin: a Sessy whose sensor is + while discharging is
    still found and flipped, from its own counters."""
    home = _Home("pair_first")
    home.states["sensor.sessy_power"] = _w(1500)
    p = home.cycle(8)
    assert home.reader._battery_sign_inverted["b1"] is True
    assert p.batteries["b1"].power_w == -1500.0


def test_the_one_battery_home_is_judged_by_its_own_battery():
    """The old battery with no power sensor is listed first and charges; the
    one read battery discharges. The old code judged it by the first
    counters, the old battery's, and flipped it."""
    home = _Home("energy_only_first")
    p = home.cycle(8)
    r = home.reader
    assert r._battery_sign_detected.get(FLEET) is True
    assert r._battery_sign_inverted[FLEET] is False
    assert p.battery_power == -1500.0


def test_the_setup_saved_pick_is_the_same_battery():
    """Setup saves the dashboard's battery sensor as ``battery_power_sensor``
    (``to_dict``), so on most homes the one-battery read comes through that
    pick. It is still the dashboard's battery and is judged by its own
    counters (review: the first cut skipped every such home)."""
    ed = _ed("energy_only_first")
    assert ed.to_dict()["battery_power_sensor"] == "sensor.sessy_power"
    home = _Home("energy_only_first", config=ed.to_dict())
    p = home.cycle(8)
    assert home.reader._battery_sign_inverted[FLEET] is False
    assert p.battery_power == -1500.0


def test_a_pick_the_dashboard_does_not_list_keeps_the_first_counters():
    home = _Home("energy_only_first",
                 config={"battery_power_sensor": "sensor.inverter_battery_power"})
    assert home.reader._one_battery_own_counters(home.ed) is None
    two = _Home("two_combined", config={"battery_power_sensor": "sensor.sessy_power"})
    assert two.reader._one_battery_own_counters(two.ed) is None, (
        "with two batteries the fleet value is their sum")


# ── 3. The #647 audit asks the same counters ───────────────────────────────

def _audit_cycles(home, n, rising=("sensor.sessy_discharged",
                                   "sensor.verto_charged", "sensor.old_charged")):
    for _ in range(n):
        home.reader.read_power()
        for e in rising:
            home.kwh[e] += 0.1


def test_a_right_lock_is_not_called_wrong_by_another_batterys_counters():
    home = _Home("pair_first")
    home.reader._battery_sign_detected["b1"] = True
    home.reader._battery_sign_inverted["b1"] = False
    _audit_cycles(home, 8)
    assert home.reader.battery_sign_contradiction_bids == []


def test_a_wrong_lock_is_still_caught_on_its_own_counters():
    home = _Home("pair_first")
    home.reader._battery_sign_detected["b1"] = True
    home.reader._battery_sign_inverted["b1"] = True        # wrong: -1500 → +1500
    _audit_cycles(home, 8)
    assert home.reader.battery_sign_contradiction_bids == ["b1"]


def test_the_one_battery_audit_is_not_fooled_by_the_old_battery():
    """Only the old battery's charge counter moves. The old audit summed it
    in and called the right lock wrong."""
    home = _Home("energy_only_first")
    home.reader._battery_sign_detected[FLEET] = True
    home.reader._battery_sign_inverted[FLEET] = False
    _audit_cycles(home, 8, rising=("sensor.old_charged",))
    assert home.reader.battery_sign_contradiction_bids == []


def test_the_one_battery_audit_catches_a_wrong_lock_on_its_own_counters():
    """Both batteries' counters move. The old audit saw charge AND discharge
    rise, sat every cycle out, and never caught the wrong lock."""
    home = _Home("energy_only_first")
    home.reader._battery_sign_detected[FLEET] = True
    home.reader._battery_sign_inverted[FLEET] = True       # wrong
    _audit_cycles(home, 8)
    assert home.reader.battery_sign_contradiction_bids == [FLEET]


# ── 4. A lock the old code saved on another battery's counters ─────────────

OLD_B1 = {"battery_detected": {"b1": True}, "battery_inverted": {"b1": True},
          "battery_basis": "sensor"}
OLD_FLEET = {"battery_detected": {FLEET: True}, "battery_inverted": {FLEET: True},
             "battery_basis": "sensor"}


def test_a_lock_learned_on_the_pairs_counters_is_judged_again(caplog):
    home = _Home("pair_first", store=dict(OLD_B1))
    assert home.reader.export_sign_state()["battery_counters_pending"] == ["b1"]
    with caplog.at_level(logging.INFO):
        p = home.cycle(1)
    r = home.reader
    assert r._battery_sign_detected["b1"] is False, "no longer a lock"
    # the sign stays the start value: nothing reads differently yet
    assert r._battery_sign_inverted["b1"] is True
    assert p.batteries["b1"].power_w == 1500.0
    assert "sensor.verto_charged" in caplog.text and "#1193" in caplog.text
    assert "battery_counters_pending" not in r.export_sign_state()
    p = home.cycle(8)
    assert r._battery_sign_detected["b1"] is True
    assert r._battery_sign_inverted["b1"] is False, "learned on its own counters"
    assert p.batteries["b1"].power_w == -1500.0


def test_a_right_lock_judged_again_keeps_its_sign_throughout():
    """Most such locks were right. Sessy reads + while discharging and its
    saved lock negates it: the check takes the lock away, and the reading
    never changes while the sign is judged again."""
    home = _Home("pair_first", store=dict(OLD_B1))
    home.states["sensor.sessy_power"] = _w(1500)
    for _ in range(8):
        p = home.cycle(1)
        assert p.batteries["b1"].power_w == -1500.0
    assert home.reader._battery_sign_detected["b1"] is True
    assert home.reader._battery_sign_inverted["b1"] is True


def test_a_restart_before_the_first_read_still_checks_the_lock():
    early = _Home("pair_first", store=dict(OLD_B1)).reader.export_sign_state()
    home = _Home("pair_first", store=early)
    home.cycle(1)
    assert home.reader._battery_sign_detected["b1"] is False


def test_the_one_battery_lock_learned_on_the_old_batterys_counters():
    home = _Home("energy_only_first", store=dict(OLD_FLEET))
    home.cycle(1)
    assert home.reader._battery_sign_detected[FLEET] is False
    home.cycle(8)
    assert home.reader._battery_sign_inverted[FLEET] is False


def test_the_setup_saved_pick_lock_is_checked_too():
    ed = _ed("energy_only_first")
    home = _Home("energy_only_first", config=ed.to_dict(), store=dict(OLD_FLEET))
    home.cycle(1)
    assert home.reader._battery_sign_detected[FLEET] is False


@pytest.mark.parametrize("home_name,store", [
    # entry N of the lists was bN's own: the lock was learned right
    ("two_combined", OLD_B1),
    # the store already judged each battery by its own counters
    ("pair_first", {**OLD_B1, "battery_counters": "own"}),
    # one battery, and the first counters are its own
    ("one_battery_first", OLD_FLEET),
])
def test_a_lock_learned_on_its_own_counters_stays(home_name, store):
    home = _Home(home_name, store=dict(store))
    bid = next(iter(store["battery_detected"]))
    home.cycle(1)
    assert home.reader._battery_sign_detected[bid] is True
    assert home.reader._battery_sign_inverted[bid] is True
    assert "battery_counters_pending" not in home.reader.export_sign_state()


def test_a_fleet_lock_waits_while_the_home_reads_per_battery():
    """A home that once had one battery keeps its fleet lock; it is unused
    while two batteries are read, so it waits for its check, and the b1 lock
    judged again is not judged again after a restart."""
    store = {"battery_detected": {FLEET: True, "b1": True},
             "battery_inverted": {FLEET: True, "b1": True}, "battery_basis": "sensor"}
    home = _Home("pair_first", store=store)
    home.cycle(9)
    r = home.reader
    assert r._battery_sign_detected["b1"] is True
    assert r._battery_sign_inverted["b1"] is False, "judged again, on its own"
    saved = r.export_sign_state()
    assert saved["battery_counters_pending"] == [FLEET]
    again = _Home("pair_first", store=saved)
    again.cycle(1)
    assert again.reader._battery_sign_detected["b1"] is True
    assert again.reader._battery_sign_inverted["b1"] is False
    assert again.reader.export_sign_state()["battery_counters_pending"] == [FLEET]
    # back to one battery, read with another battery's counters first: checked
    one = _Home("energy_only_first", store=saved)
    one.cycle(1)
    assert one.reader._battery_sign_detected[FLEET] is False
    assert "battery_counters_pending" not in one.reader.export_sign_state()


def test_the_1194_move_runs_first_and_its_value_is_kept():
    """A store from before #1194 and #1193, one Inverted battery listed after
    a battery with no power sensor. #1194 turns the fleet lock over; the
    check then takes the lock away and keeps that turned value."""
    home = _Home("inverted_after_old", store={
        "battery_detected": {FLEET: True}, "battery_inverted": {FLEET: False}})
    assert home.ed.battery_power_inverted is True
    home.cycle(1)
    assert home.reader._battery_sign_detected[FLEET] is False
    assert home.reader._battery_sign_inverted[FLEET] is True, "the #1194 value"


def test_fix_battery_sign_on_keeps_every_lock_until_it_is_off():
    """The user set the flip against what SEM showed; a new lock under it
    would undo what they set. The check waits, and runs once it is off.
    (#1375) The flip is per battery now: the tap names Sessy."""
    home = _Home("pair_first",
                 config={"battery_sign_user_flip_sensors": ["sensor.sessy_power"]},
                 store=dict(OLD_B1))
    home.cycle(3)
    assert home.reader._battery_sign_detected["b1"] is True
    saved = home.reader.export_sign_state()
    assert saved["battery_counters_pending"] == ["b1"]
    off = _Home("pair_first", store=saved)
    off.cycle(1)
    assert off.reader._battery_sign_detected["b1"] is False


def test_a_restart_before_it_is_learned_again_keeps_the_sign():
    """The kept start value is saved: a restart between the check and the
    new lock does not fall back to "no correction" (second review)."""
    home = _Home("pair_first", store=dict(OLD_B1))
    home.states["sensor.sessy_power"] = _w(1500)      # + while discharging
    p = home.cycle(1)
    assert home.reader._battery_sign_detected["b1"] is False
    assert p.batteries["b1"].power_w == -1500.0
    saved = home.reader.export_sign_state()
    assert saved["battery_sign_kept"] == {"b1": True}
    after = _Home("pair_first", store=saved)
    after.states["sensor.sessy_power"] = _w(1500)
    for _ in range(8):
        p = after.cycle(1)
        assert p.batteries["b1"].power_w == -1500.0
    assert after.reader._battery_sign_detected["b1"] is True
    assert "battery_sign_kept" not in after.reader.export_sign_state()


def test_a_brand_default_does_not_move_the_kept_sign(monkeypatch):
    """GoodWe's brand default negates. The kept value (no correction) stays
    the start value, before and after a restart, until the counters say."""
    store = {"battery_detected": {"b1": True}, "battery_inverted": {"b1": False},
             "battery_basis": "sensor"}
    home = _Home("pair_first", store=store)
    monkeypatch.setattr(home.reader, "_battery_brand", lambda bid, ent: "goodwe")
    p = home.cycle(1)
    assert home.reader._battery_sign_detected["b1"] is False
    assert home.reader._battery_sign_inverted["b1"] is False
    assert p.batteries["b1"].power_w == -1500.0
    after = _Home("pair_first", store=home.reader.export_sign_state())
    monkeypatch.setattr(after.reader, "_battery_brand", lambda bid, ent: "goodwe")
    p = after.cycle(1)
    assert after.reader._battery_sign_inverted["b1"] is False
    assert p.batteries["b1"].power_w == -1500.0


def test_kept_values_in_a_damaged_store_are_ignored():
    r = SensorReader(MagicMock(), {})
    r.restore_sign_state({"battery_counters": "own", "battery_sign_kept": [1, 2]})
    r.restore_sign_state({"battery_counters": "own",
                          "battery_sign_kept": {"b1": "yes", 5: True}})
    assert r._battery_sign_kept == set()
    assert "battery_sign_kept" not in r.export_sign_state()


def test_reset_and_a_fresh_store_are_marked():
    r = _Home("pair_first", store=dict(OLD_B1)).reader
    r.reset_sign_state()
    assert r.export_sign_state()["battery_counters"] == "own"
    assert "battery_counters_pending" not in r.export_sign_state()
    kept = _Home("pair_first", store=dict(OLD_B1))
    kept.cycle(1)
    kept.reader.reset_sign_state()
    assert "battery_sign_kept" not in kept.reader.export_sign_state()
    assert SensorReader(MagicMock(), {}).export_sign_state()["battery_counters"] == "own"
    fresh = _Home("pair_first", store={})
    assert fresh.reader.export_sign_state()["battery_counters"] == "own"


# ── 5. What a person sees names the battery's own counters ─────────────────
# (#1213) The setup screen shows watts, not sensor names, so it is no
# longer a place that names counters.

def test_the_sign_payload_names_each_batterys_counters():
    home = _Home("pair_first")
    home.cycle(8)
    per_bid = home.reader.battery_sign_diagnostics()["per_bid"]
    assert per_bid["b1"]["counters"] == ["sensor.sessy_charged",
                                         "sensor.sessy_discharged"]
    one = _Home("energy_only_first")
    one.cycle(8)
    assert one.reader.battery_sign_diagnostics()["per_bid"][FLEET]["counters"] == [
        "sensor.sessy_charged", "sensor.sessy_discharged"]


@pytest.mark.asyncio
async def test_the_diagnostics_dump_holds_each_batterys_counters():
    from custom_components.solar_energy_management.diagnostics import (
        async_get_config_entry_diagnostics,
    )
    coordinator = MagicMock()
    coordinator._energy_dashboard_config = _ed("pair_first")
    entry = MagicMock()
    entry.entry_id = "e1193"
    entry.data, entry.options = {}, {}
    entry.runtime_data = coordinator
    hass = MagicMock()
    hass.data = {"solar_energy_management": {"e1193": coordinator}}
    hass.states.get = lambda eid: None

    result = await async_get_config_entry_diagnostics(hass, entry)

    assert result["energy_dashboard"]["per_source_lists"]["battery_unit_counters"] == {
        "sensor.sessy_power": ["sensor.sessy_charged", "sensor.sessy_discharged"],
        "sensor.verto_charge_power": ["sensor.verto_charged",
                                      "sensor.verto_discharged"],
    }


# ── 6. Guard: who may read the counter lists ───────────────────────────────

# Every function that reads ``battery_charge_energy_list`` or
# ``battery_discharge_energy_list`` itself, and why it may. One battery's
# counters are ``unit_energy_counters``; a new reader fails until sorted.
DECLARED_COUNTER_LIST_READERS = {
    ("ha_energy_reader.py", "_extract_battery_config"):
        "the parser that fills them",
    ("coordinator/sensor_reader.py", "battery_sign_diagnostics"):
        "the sign payload lists every counter",
    ("coordinator/sensor_reader.py", "_audit_battery_sign_lock"):
        "the fleet audit sums every counter when no one battery is read",
    ("coordinator/sensor_reader.py", "_drop_locks_on_other_counters"):
        "rebuilds the old pairing on purpose, to find locks learned on it",
}
_COUNTER_LISTS = {"battery_charge_energy_list", "battery_discharge_energy_list"}


def _counter_list_readers_in(rel, source):
    found = set()
    for func in ast.walk(ast.parse(source)):
        if not isinstance(func, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for node in ast.walk(func):
            if ((isinstance(node, ast.Attribute) and node.attr in _COUNTER_LISTS)
                    or (isinstance(node, ast.Constant)
                        and node.value in _COUNTER_LISTS)):
                found.add((rel, func.name))
    return found


def test_every_reader_of_the_counter_lists_is_declared():
    found = set()
    for path in ROOT.rglob("*.py"):
        rel = path.relative_to(ROOT).as_posix()
        if not rel.startswith("tests/"):
            found |= _counter_list_readers_in(rel, path.read_text(encoding="utf-8"))
    assert found - set(DECLARED_COUNTER_LIST_READERS) == set(), (
        "a new reader of the counter lists: one battery's counters are "
        "unit_energy_counters (#1193); declare why if the lists are meant")
    assert set(DECLARED_COUNTER_LIST_READERS) - found == set(), "stale entry"


def test_the_guard_fires_on_the_old_pairing():
    old = textwrap_dedent("""
        def read_power(self, ed, idx):
            return ed.battery_charge_energy_list[idx]
    """)
    assert _counter_list_readers_in("coordinator/sensor_reader.py", old) == {
        ("coordinator/sensor_reader.py", "read_power")}
    assert ("coordinator/sensor_reader.py", "read_power") not in (
        DECLARED_COUNTER_LIST_READERS)


def textwrap_dedent(text):
    import textwrap
    return textwrap.dedent(text)
