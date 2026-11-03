"""#1299 — the replay gate compares what SEM would command.

``no_writes`` counted service calls on a coordinator that never decided
anything, so it passed every branch on every day. Now the real pure
deciders run on each recorded cycle and the branch's would-send rows are
compared with the base's: same rows, same order, none added, none
dropped. A day with nothing to compare says so instead of passing.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from custom_components.solar_energy_management.tools.replay import invariants as inv
from custom_components.solar_energy_management.tools.replay.commands import (
    replay_commands,
)
from custom_components.solar_energy_management.tools.replay.engine import (
    DayRun, replay_day,
)
from custom_components.solar_energy_management.tools.replay.recorded_day import (
    load_day,
)

FIX = Path(__file__).parent / "fixtures" / "replay"


def _fixture(name):
    return load_day(next((FIX / name).glob("*.json.gz")))


ROWS = [[0, "car", "IDLE", 0], [0, "battery", "NORMAL", 0, 0],
        [600, "battery", "LIMIT_DISCHARGE", 1500, 0]]


# ── the check compares rosters ─────────────────────────────────────────

def test_same_rows_pass_with_evidence():
    r = inv.no_writes(DayRun("d", [], commands=list(ROWS)), DayRun("d", [], commands=list(ROWS)))
    assert r.ok and r.evidence_n == 3


def test_a_changed_decision_refuses():
    mine = [ROWS[0], ROWS[1], [600, "battery", "NORMAL", 0, 0]]
    r = inv.no_writes(DayRun("d", [], commands=mine), DayRun("d", [], commands=list(ROWS)))
    assert not r.ok and r.kind == "exact"
    assert "row 2" in r.detail and r.evidence[0]["branch"][2] == "NORMAL"


def test_an_added_or_dropped_row_refuses():
    assert not inv.no_writes(DayRun("d", [], commands=ROWS + [[900, "car", "CHARGE_AT_AMPS", 6]]),
                             DayRun("d", [], commands=list(ROWS))).ok
    assert not inv.no_writes(DayRun("d", [], commands=ROWS[:2]),
                             DayRun("d", [], commands=list(ROWS))).ok


def test_nothing_to_compare_is_said_not_passed_silently():
    r = inv.no_writes(DayRun("d", [], commands=[]), DayRun("d", [], commands=[]))
    assert r.ok and r.evidence_n == 0 and "neither" in r.detail


def test_a_tree_without_deciders_is_noted_not_blamed():
    r = inv.no_writes(DayRun("d", [], commands=None), DayRun("d", [], commands=list(ROWS)))
    assert r.ok and r.evidence_n == 0 and "no decision roster" in r.detail


def test_a_decider_that_raises_fails_the_gate():
    r = inv.no_writes(DayRun("d", [], decision_error="KeyError: 'x'"),
                      DayRun("d", [], commands=list(ROWS)))
    assert not r.ok and "raised" in r.detail


def test_a_real_service_call_still_fails():
    assert not inv.no_writes(DayRun("d", [], writes=1, commands=[]), DayRun("d", [], commands=[])).ok


# ── the roster comes from the real deciders on a recorded day ──────────

def test_a_recorded_day_gives_a_roster_from_the_real_deciders():
    day = _fixture("battery_stop")
    rows = replay_commands(day, None)
    who = {r[1] for r in rows}
    assert who == {"car", "battery"}
    assert rows[0][2] in ("IDLE", "CHARGE_AT_AMPS", "CHARGE_MAX")
    assert all(len(r) >= 4 for r in rows)


def test_replay_day_carries_the_roster_and_no_error():
    run = replay_day(_fixture("battery_stop"))
    assert run.commands is not None and run.decision_error == "" and run.writes == 0


def test_the_roster_lists_decisions_not_every_watt():
    from custom_components.solar_energy_management.tools.replay import commands as cm
    assert cm._step(1491) == 1500 and cm._step(1449) == 1400 and cm._step(0) == 0


@pytest.mark.parametrize("bad", [None, "x"])
def test_an_unreadable_decision_error_never_hides_a_result(bad):
    r = inv.no_writes(DayRun("d", [], commands=list(ROWS), decision_error=bad or ""),
                      DayRun("d", [], commands=list(ROWS)))
    assert r.ok is (not bad)
