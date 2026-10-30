"""#1210 — the battery sign audit was picked by a saved lock, not by the read.

``_audit_battery_sign_lock`` (#589, #647) checks each lock SEM applies
against the battery's own energy counters. It chose between the one-battery
check and the per-battery check by asking whether the one-battery
(``__fleet__``) lock was saved. A home that started with one battery and
added a second keeps that lock in storage, but reads each battery on its own
(b1, b2 …). The audit took the one-battery branch, judged the sum, and
returned: a wrong b1 or b2 sign was never seen.

Now one rule, ``_reads_per_battery``, answers "does this read sign each
battery?" for the read and for its audit. An audit of the other way of
reading can never be fed again, so it is dropped: a flag it raised would
stay lit for ever. The diagnostics sensor shows the locks the read applies.

Each test drives the real ``read_power`` on a home parsed from HA's prefs.
"""
from __future__ import annotations

import ast
from pathlib import Path
from unittest.mock import MagicMock

from .test_1193_own_battery_counters import FLEET, HOMES, PAIR, _ed, _Home, _w

ROOT = Path(__file__).resolve().parent.parent

# Saved by a build that had both: an old one-battery lock beside b1/b2 ones.
# ``battery_counters: "own"`` — the #1193 check is done, nothing waits.
def _store(fleet_inverted, b1_inverted, b2_inverted=False):
    return {
        "battery_detected": {FLEET: True, "b1": True, "b2": True},
        "battery_inverted": {FLEET: fleet_inverted, "b1": b1_inverted,
                             "b2": b2_inverted},
        "battery_basis": "sensor", "battery_counters": "own",
    }


def _cycles(home, n, rising=("sensor.sessy_discharged",
                             "sensor.sessy2_discharged")):
    for _ in range(n):
        home.reader.read_power()
        for e in rising:
            home.kwh[e] += 0.1


# ── 1. The audit follows the read ──────────────────────────────────────────

def test_a_wrong_battery_sign_is_caught_beside_an_old_one_battery_lock():
    """The #1210 case. Both batteries discharge 1500 W; b1's saved lock is
    wrong and reads it as charging. The old audit saw the one-battery lock,
    judged the sum (+1500 − 1500 = 0 W, "idle") and never looked at b1."""
    home = _Home("two_combined", store=_store(False, True))
    _cycles(home, 8)
    r = home.reader
    assert r.battery_sign_contradiction_bids == ["b1"]
    assert r._battery_sign_contradiction is True


def test_right_battery_signs_beside_an_old_lock_stay_quiet():
    """The old one-battery lock says "negate", which would be wrong for the
    sum. It is not applied to this read, so it gets no audit of its own (the
    old code kept one, judged on the read's sum)."""
    home = _Home("two_combined", store=_store(True, False))
    _cycles(home, 8)
    r = home.reader
    assert r.battery_sign_contradiction_bids == []
    assert FLEET not in r._battery_sign_audits
    assert set(r._battery_sign_audits) == {"b1", "b2"}, "each battery checked"


def test_the_one_battery_home_still_checks_its_lock():
    """The twin: a home that reads one battery still has its lock checked,
    and an old b1 lock beside it changes nothing."""
    store = _store(True, False)                  # fleet lock wrong
    home = _Home("one_battery_first", store=store)
    _cycles(home, 8)
    assert home.reader.battery_sign_contradiction_bids == [FLEET]


def test_a_dark_battery_does_not_reset_the_other_batterys_count():
    """The drop must not fire on a cycle where one battery reads nothing: it
    still counts as read (0 W, #1167), so the home still reads each battery
    and b1's count goes on. Reset there, a wrong b1 might never reach five."""
    home = _Home("two_combined", store={
        "battery_detected": {"b1": True, "b2": True},
        "battery_inverted": {"b1": True, "b2": False},
        "battery_basis": "sensor", "battery_counters": "own"})
    _cycles(home, 3)                              # 1 to start, 2 counted
    home.states["sensor.sessy2_power"] = MagicMock(state="unavailable",
                                                   attributes={})
    _cycles(home, 1)
    home.states["sensor.sessy2_power"] = _w(-1500)
    _cycles(home, 2)
    assert home.reader.battery_sign_contradiction_bids == ["b1"]


# ── 2. An audit of the other way of reading is dropped ─────────────────────

def _flag(home, rising):
    _cycles(home, 8, rising)
    assert home.reader._battery_sign_contradiction is True


def test_a_second_battery_drops_the_one_battery_flag():
    """Raised while the home read one battery; once it reads each battery,
    nothing feeds that audit again. Kept, it would stay lit for ever."""
    home = _Home("one_battery_first", store={
        "battery_detected": {FLEET: True}, "battery_inverted": {FLEET: True},
        "battery_basis": "sensor", "battery_counters": "own"})
    _flag(home, ("sensor.sessy_discharged",))
    r = home.reader
    assert r.battery_sign_contradiction_bids == [FLEET]

    r.set_energy_dashboard_config(_ed("two_combined"))
    _cycles(home, 1)
    assert FLEET not in r._battery_sign_audits
    assert r._battery_sign_contradiction is False
    assert r._battery_sign_detected[FLEET] is True, "the lock itself is kept"


def test_back_to_one_battery_drops_the_per_battery_flag():
    """b1 raised its flag on a two-battery home. The setter keeps b1's audit
    (b1 is still there); the one-battery read never feeds it again."""
    home = _Home("two_combined", store={
        "battery_detected": {"b1": True, "b2": True},
        "battery_inverted": {"b1": True, "b2": False},
        "battery_basis": "sensor", "battery_counters": "own"})
    _flag(home, ("sensor.sessy_discharged", "sensor.sessy2_discharged"))
    r = home.reader
    assert r.battery_sign_contradiction_bids == ["b1"]

    r.set_energy_dashboard_config(_ed("one_battery_first"))
    _cycles(home, 1)
    assert r._battery_sign_audits.keys() <= {FLEET}
    assert r._battery_sign_contradiction is False
    assert r._battery_sign_detected["b1"] is True, "the lock itself is kept"


def test_a_one_battery_pair_is_not_judged_by_an_old_lock(monkeypatch):
    """A battery read as a two-sensor pair takes no lock (#1215); each pair of
    a fleet is not audited (#647). The one-battery pair was audited all the
    same, and its warning told the user to reset a lock that does nothing."""
    monkeypatch.setitem(HOMES, "pair_alone", [PAIR])
    home = _Home("pair_alone", store={
        "battery_detected": {FLEET: True}, "battery_inverted": {FLEET: False},
        "battery_basis": "sensor", "battery_counters": "own"})
    # the pair reads +1200 W (charging); its discharge counter rises
    _cycles(home, 8, ("sensor.verto_discharged",))
    r = home.reader
    assert r._battery_read_is_pair is True
    assert r.battery_sign_contradiction_bids == []
    assert FLEET not in r._battery_sign_audits


# ── 3. The diagnostics sensor shows what the read applies ──────────────────

def _diag(home):
    from custom_components.solar_energy_management.coordinator.publish_diag import (
        build_diagnostics,
    )
    from .test_620_device_goal_model import TestPublishDiag625
    coord = TestPublishDiag625()._coord()
    coord._sensor_reader = home.reader
    return build_diagnostics(coord)["diag_battery_sign"]


def test_the_diagnostics_sensor_leaves_out_a_lock_the_read_does_not_use():
    two = _Home("two_combined", store=_store(True, True))
    _cycles(two, 1)
    assert _diag(two) == "b1: negated, b2: normal"

    one = _Home("one_battery_first", store=_store(False, True))
    _cycles(one, 1)
    assert _diag(one) == "normal"

    # a removed third battery, and a lock on the id a two-sensor battery has
    gone = _store(False, False)
    gone["battery_detected"]["b3"] = True
    gone["battery_inverted"]["b3"] = True
    three = _Home("two_combined", store=gone)
    _cycles(three, 1)
    assert _diag(three) == "b1: normal, b2: normal"

    pair = _Home("pair_first", store=_store(False, False, True))
    _cycles(pair, 1)
    assert _diag(pair) == "normal", "b2 is the pair: no lock, b1 alone"


def test_the_diagnostics_sensor_before_the_first_read_shows_the_store():
    home = _Home("two_combined", store=_store(True, True))
    assert "__fleet__" in _diag(home), "nothing read yet: nothing to leave out"


# ── 4. One rule for the read and its audit ─────────────────────────────────

def _function(name):
    src = (ROOT / "coordinator" / "sensor_reader.py").read_text()
    for node in ast.walk(ast.parse(src)):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{name} not found")


def _calls(fn, name):
    return [n for n in ast.walk(fn) if isinstance(n, ast.Call)
            and isinstance(n.func, ast.Attribute) and n.func.attr == name]


def test_the_read_and_its_audit_ask_one_rule():
    for fn in ("read_power", "_audit_battery_sign_lock"):
        assert _calls(_function(fn), "_reads_per_battery"), fn


def test_the_audit_does_not_pick_its_branch_by_a_saved_lock():
    """The old shape: ``if self._battery_sign_detected.get(self._FLEET_BID):``
    as the branch. A saved lock may still be asked INSIDE the one-battery
    branch (is there a lock to check?), never to choose the branch."""
    fn = _function("_audit_battery_sign_lock")
    branches = [n for n in fn.body if isinstance(n, ast.If)]
    assert branches
    for branch in branches:
        assert "_battery_sign_detected" not in ast.unparse(branch.test)
    assert any("per_battery" in ast.unparse(b.test) for b in branches)
