"""(#1381 charger owner, final review) Decisions D19–D28.

Each test is one finding of the final independent review of e5b7a3a8
(``challenge-feature-charger-owner.md``, "final pass"). They were written
before the code that makes them pass.
"""
from __future__ import annotations

import ast
import itertools
from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts import ev_charge_modes as M
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.decide import (
    ChargerIntent, decide,
)

ROOT = Path(__file__).resolve().parents[1]
SIX = ("solar_only", "solar_plus_battery", "solar_plus_cheap",
       "min_plus_solar", "always_max", "off")


# ── D21: re-selecting the shown mode changes nothing ─────────────────────

@pytest.mark.parametrize("stored,never,remembered", itertools.product(
    SIX, (None, False, True), (None, False, True)))
def test_d21_reselecting_the_shown_mode_keeps_the_stored_strategy(
        stored, never, remembered):
    charger = {"id": "c", "charge_mode": stored}
    if never is not None:
        charger["ev_battery_may_assist"] = never
    if remembered is not None:
        charger[M.BATTERY_HELP_KEY] = remembered
    before = dict(charger)
    M.apply_user_mode_write(charger, "charge_mode", M.user_mode_of(stored))
    assert charger["charge_mode"] == stored
    assert charger == before


def test_d21_the_reviewers_case_keeps_the_min_floor():
    """stored min_plus_solar, per-charger "never" → shows Sun + tariff with
    help off; picking Sun + tariff again kept solar_plus_cheap before."""
    charger = {"id": "c", "charge_mode": "min_plus_solar",
               "ev_battery_may_assist": False}
    M.apply_user_mode_write(charger, "charge_mode", "sun_tariff")
    assert charger["charge_mode"] == "min_plus_solar"


# ── D24: battery help after Off / Now ────────────────────────────────────

def test_d24_leaving_off_keeps_the_last_explicit_help():
    charger = {"id": "c", "charge_mode": "solar_only"}
    M.apply_user_mode_write(charger, "charge_mode", "off")
    M.apply_user_mode_write(charger, "charge_mode", "sun")
    assert charger["charge_mode"] == "solar_only"


def test_d24_without_a_choice_the_new_install_default_helps():
    charger = {"id": "c", "charge_mode": "off"}
    M.apply_user_mode_write(charger, "charge_mode", "sun_tariff")
    assert charger["charge_mode"] == "min_plus_solar"


# ── D20: Now on an Off or paused charger charges ─────────────────────────

def _now_override(minutes=60, user_now=True):
    now = dt_util.utcnow()
    return po.set_override(
        {}, "c", "force", now + timedelta(minutes=minutes), now,
        user_now=user_now), now


def test_d20_users_now_lifts_off_for_its_duration():
    ov, now = _now_override()
    assert po.charger_mode_for(ov, "c", "off", now) == "always_max"


def test_d20_a_plan_force_still_leaves_off_alone():
    ov, now = _now_override(user_now=False)
    assert po.charger_mode_for(ov, "c", "off", now) == "off"


def test_d20_after_now_off_stays_off():
    ov, now = _now_override(minutes=10)
    later = now + timedelta(minutes=11)
    assert po.charger_mode_for(ov, "c", "off", later) == "off"


def test_d20_the_user_now_survives_a_restart():
    ov, now = _now_override()
    back = po.deserialize(po.serialize(ov))
    assert po.charger_mode_for(back, "c", "off", now) == "always_max"


# ── D22: Now ends at THIS car's next block, or after 120 min; on unplug ──

def _coord(blocks):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    c = SEMCoordinator.__new__(SEMCoordinator)
    c._energy_plan_shadow = {"blocks": blocks}
    return c


def test_d22_without_a_block_of_this_car_now_runs_120_minutes():
    now = dt_util.utcnow().replace(microsecond=0)
    c = _coord([
        {"id": "battery", "start": (now - timedelta(hours=1)).isoformat(),
         "end": (now + timedelta(hours=13)).isoformat()},
        {"id": "ev:c", "start": (now - timedelta(hours=1)).isoformat(),
         "end": (now + timedelta(hours=1)).isoformat()},
    ])
    assert c.now_minutes_for("c", now) == 120


def test_d22_unplug_ends_the_users_now():
    ov, now = _now_override()
    assert po.end_now_on_unplug(ov, "c", car_absent=True) == {}
    assert po.end_now_on_unplug(ov, "c", car_absent=False) == ov
    assert po.end_now_on_unplug(ov, "c", car_absent=None) == ov   # unknown plug


def test_d22_unplug_leaves_other_overrides():
    now = dt_util.utcnow()
    ov = po.set_override({}, "c", "skip", now + timedelta(minutes=60), now)
    assert po.end_now_on_unplug(ov, "c", car_absent=True) == ov
    plan_force = po.set_override({}, "c", "force", now + timedelta(minutes=60), now)
    assert po.end_now_on_unplug(plan_force, "c", car_absent=True) == {}


def test_d22_the_coordinator_ends_now_on_unplug():
    from .ast_contracts import call_sites
    files = {path for path, _line, _kw in call_sites("end_now_on_unplug")}
    assert any(str(f).endswith("coordinator/coordinator.py") for f in files), files


# ── D23: one day rule for Sun + tariff, battery switch = battery only ────

def _v(mode, **kw):
    from .test_decide import _view
    args = dict(is_night=False, tariff_level="flat", target_kwh=9.0,
                solar_w=600.0, home_w=500.0, battery_soc=0)
    args.update(kw)
    return _view(mode, **args)


def test_d23_without_battery_help_the_deadline_floor_charges_by_day():
    d = decide(_v("solar_plus_cheap", night_deliverable_kwh=3.0))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_MIN_TODAY
    assert d.commanded_amps == 6


def test_d23_the_floor_outranks_a_peak_hour():
    d = decide(_v("solar_plus_cheap", tariff_level="peak",
                  night_deliverable_kwh=3.0))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_MIN_TODAY


def test_d23_no_floor_when_the_night_can_deliver():
    d = decide(_v("solar_plus_cheap", night_deliverable_kwh=20.0))
    assert d.intent is ChargerIntent.IDLE


def test_d23_with_battery_help_the_thin_sun_rule_acts():
    from .test_1411_thin_sun_rule import FLAT
    v = replace(_v("min_plus_solar", solar_w=1500.0, battery_soc=50),
                thin_sun=FLAT)
    d = decide(v)
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.reason_code == RC.CHARGER_SUN_PLUS_GRID
    assert d.mode == "min_plus_solar"


def test_d23_with_battery_help_a_cheap_hour_tops_up():
    v = _v("min_plus_solar", tariff_level="cheap", battery_soc=50,
           deadline_amps=8)
    d = decide(v)
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS


def test_d23_battery_first_still_holds_with_help():
    d = decide(_v("min_plus_solar", battery_soc=5, night_deliverable_kwh=3.0))
    assert d.reason_code == RC.CHARGER_BATTERY_FIRST


def test_d23_the_planner_and_the_live_inputs_ask_one_predicate():
    from .ast_contracts import call_sites
    sites = [(str(p), line) for p, line, _kw in call_sites("_sun_tariff_day_of")]
    assert len(sites) == 2, sites       # the planner's booking and the live inputs
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    from .ast_contracts import calls
    assert calls(SEMCoordinator._thin_sun_for, "_sun_tariff_day_of")
    assert not calls(SEMCoordinator._thin_sun_for, "_tariff_optimized_for")


# ── D25: a withheld phase switch is not booked ───────────────────────────

def test_d25_note_switched_follows_a_real_send():
    tree = ast.parse((ROOT / "coordinator" / "ev_control.py").read_text())
    for fn in ast.walk(tree):
        if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = ast.unparse(fn)
        if "note_switched" not in body:
            continue
        lines = body.splitlines()
        for i, line in enumerate(lines):
            if "note_switched(" in line:
                above = " ".join(lines[max(0, i - 2):i])
                assert "sent" in above, line


# ── D27: the simulation card speaks the four modes ───────────────────────

def test_d27_the_simulation_card_lists_four_modes():
    src = (ROOT / "dashboard" / "card" / "src" / "util" / "simulation-rows.js").read_text()
    line = next(l for l in src.splitlines() if l.startswith("export const EV_MODES"))
    assert "'sun_tariff'" in line
    for old in ("solar_plus_cheap", "min_plus_solar", "solar_plus_battery", "solar_only"):
        assert old not in line, old
