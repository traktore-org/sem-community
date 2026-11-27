"""#1440 (point 4) — when the thin-sun rule holds back, the charger says why.

The plan booked a sun + grid block; the live rule said no (the home
battery took the sun, the price, the peak limit, a price it could not
read). The charger kept the sun-only reason, "not enough spare sun", so
nothing said what held the block. Now the rule's own cause is the code
the card shows. The decision itself is unchanged: only its reason.
"""
from __future__ import annotations

import ast
import inspect
import json
from dataclasses import fields, replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator import decide as decide_mod
from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator import thin_sun as ts
from custom_components.solar_energy_management.coordinator.decide import (
    THIN_SUN_HELD_CODES, THIN_SUN_KEEPS_CODE, THIN_SUN_NOT_ASKED,
    ChargerIntent, decide,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.coordinator.thin_sun import ThinSun

from .test_1411_thin_sun_rule import FLAT, _view

ROOT = Path(decide_mod.__file__).resolve().parents[1]
NEW_CODES = (
    RC.CHARGER_THIN_SUN_BATTERY, RC.CHARGER_THIN_SUN_BATTERY_PAYS,
    RC.CHARGER_THIN_SUN_LATER, RC.CHARGER_THIN_SUN_SUN_LATER,
    RC.CHARGER_THIN_SUN_PEAK, RC.CHARGER_THIN_SUN_UNKNOWN,
)


def _same_but_reason(a, b):
    """Every field of the two decisions but the reason ones is equal."""
    skip = {"reason", "reason_code", "reason_params"}
    for f in fields(a):
        if f.name not in skip:
            assert getattr(a, f.name) == getattr(b, f.name), f.name


def _outside_block(v):
    return replace(v, thin_sun=replace(v.thin_sun, in_block=False))


@pytest.mark.unit
class TestTheHeldBlockSaysWhy:
    @pytest.mark.parametrize("kw, thin, code, why", [
        # the home battery charges from that sun
        (dict(battery_soc=50, battery_charge_w=900.0), FLAT,
         RC.CHARGER_THIN_SUN_BATTERY, "battery_takes_sun"),
        # a full pack past its gate would pay the grid's share
        (dict(battery_soc=95, solar_w=2500.0, home_w=500.0), FLAT,
         RC.CHARGER_THIN_SUN_BATTERY_PAYS, "battery_would_pay"),
        # strong sun later today covers the car for free
        ({}, replace(FLAT, strong_sun_kwh=12.0),
         RC.CHARGER_THIN_SUN_SUN_LATER, "forecast_covers"),
        # net metering: the blend is never cheaper
        ({}, ThinSun(export_price=0.30, import_now=0.30, cheapest_later=0.30,
                     strong_sun_kwh=0.0, in_block=True),
         RC.CHARGER_THIN_SUN_LATER, "not_cheaper"),
        # no export price
        ({}, replace(FLAT, export_price=None),
         RC.CHARGER_THIN_SUN_UNKNOWN, "export_unknown"),
        # no forecast
        ({}, replace(FLAT, strong_sun_kwh=None),
         RC.CHARGER_THIN_SUN_UNKNOWN, "forecast_unknown"),
        # (review) an import price or the later hour not read: a start
        # never buys on it, and the card says the price is unknown — not
        # "later is cheaper"
        ({}, replace(FLAT, import_now=None),
         RC.CHARGER_THIN_SUN_UNKNOWN, "price_unread"),
        ({}, replace(FLAT, cheapest_later=None),
         RC.CHARGER_THIN_SUN_UNKNOWN, "price_unread"),
    ])
    def test_each_cause_in_a_booked_block(self, kw, thin, code, why):
        v = _view(thin_sun=thin, **kw)
        d = decide(v)
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code == code
        assert d.reason_params == {}
        assert f"thin sun held: {why}" in d.reason
        # outside the block the rule was not asked: the sun-only answer,
        # and the same decision but for its reason
        base = decide(_outside_block(v))
        assert base.reason_code not in NEW_CODES
        assert "thin sun held" not in base.reason
        _same_but_reason(d, base)
        assert d.reason.replace(f" — thin sun held: {why}", "") == base.reason

    def test_no_room_under_the_peak_limit(self):
        v = _view()
        v = replace(v, fleet=replace(v.fleet, peak_slot_allowed_w=1000.0))
        d = decide(v)
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code == RC.CHARGER_THIN_SUN_PEAK
        assert "no_grid_room" in d.reason

    def test_a_session_stopped_by_the_peak_limit_says_so(self):
        """A running session outside its block (the minimum block after
        it): the hard limit ends it and the charger names the limit."""
        v = _view(thin_sun=replace(FLAT, in_block=False, session_s=1200.0))
        v = replace(v, power=replace(v.power, charging=True, power_w=4100.0),
                    fleet=replace(v.fleet, peak_state="shedding"))
        d = decide(v)
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code == RC.CHARGER_THIN_SUN_PEAK
        assert "peak_limit" in d.reason

    def test_a_peak_limit_outside_any_block_claims_no_block(self):
        v = _view(thin_sun=replace(FLAT, in_block=False))
        v = replace(v, fleet=replace(v.fleet, peak_state="shedding"))
        d = decide(v)
        assert d.reason_code not in NEW_CODES
        assert "thin sun held" not in d.reason


@pytest.mark.unit
class TestAShortPriceGapIsBridged:
    """(review) Past the minimum block one unread price stopped a running
    session as ``not_cheaper``; the window (``price_unknown``) is what
    ends it."""
    PAST = replace(FLAT, session_s=1200.0, min_block_s=900.0)

    def test_the_verdict(self):
        for gap in (dict(import_now=None), dict(cheapest_later=None),
                    dict(export_price=None)):
            t = replace(self.PAST, **gap)
            assert ts.thin_sun_verdict(t, sun_w=1000.0, min_w=4140.0,
                                       need_kwh=5.0, running=True) == (True, "bridged"), gap
            # mostly unreadable over the window ends it
            assert ts.thin_sun_verdict(replace(t, price_blind_share=0.6),
                                       sun_w=1000.0, min_w=4140.0, need_kwh=5.0,
                                       running=True) == (False, "price_unknown")
            # a start never buys on it
            assert ts.thin_sun_verdict(replace(t, session_s=None), sun_w=1000.0,
                                       min_w=4140.0, need_kwh=5.0)[0] is False

    def test_the_car_keeps_charging(self):
        v = _view(thin_sun=replace(self.PAST, import_now=None))
        v = replace(v, power=replace(v.power, charging=True, power_w=4100.0))
        d = decide(v)
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.reason_code == RC.CHARGER_SUN_PLUS_GRID
        assert "prices not read this cycle" in d.reason
        assert "price gap: bridged" in d.reason

    def test_a_long_gap_ends_it_and_says_so(self):
        v = _view(thin_sun=replace(self.PAST, import_now=None,
                                   price_blind_share=0.6))
        v = replace(v, power=replace(v.power, charging=True, power_w=4100.0))
        d = decide(v)
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code == RC.CHARGER_THIN_SUN_UNKNOWN
        assert "price_unknown" in d.reason


@pytest.mark.unit
class TestBatteryHelpOn:
    def test_only_the_reason_changes(self):
        """The help-on strategy runs the same day rule: in a block, the
        held reason replaces the sun-only one, never the decision."""
        v = _view(mode="min_plus_solar", battery_soc=50, battery_charge_w=900.0)
        d = decide(v)
        base = decide(_outside_block(v))
        assert d.reason_code == RC.CHARGER_THIN_SUN_BATTERY
        _same_but_reason(d, base)


@pytest.mark.unit
class TestTheSunOnlyReasonStands:
    def test_no_rule_inputs(self):
        d = decide(_view(thin_sun=None))
        assert d.reason_code == RC.CHARGER_LOW_SUN
        assert "thin sun held" not in d.reason

    def test_nothing_to_buy(self):
        d = decide(_view(target_kwh=0.0))
        assert d.reason_code not in NEW_CODES
        assert "thin sun held" not in d.reason

    def test_too_little_sun_keeps_its_code_and_names_the_word(self):
        d = decide(_view(solar_w=600.0, home_w=500.0))       # 100 W spare
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code == RC.CHARGER_LOW_SUN
        assert "thin sun held: no_sun" in d.reason

    def test_a_plan_hold_says_the_plan_waits(self):
        """The rule fires but the plan holds the charge for later: the
        plan's own word, on the sun-only IDLE."""
        until = datetime(2026, 11, 27, 14, 0, tzinfo=timezone.utc)
        v = _view(plan=PlanVerdict(hold=True, until=until, reason="later block"))
        d = decide(v)
        assert d.intent is ChargerIntent.IDLE
        assert d.reason_code == RC.CHARGER_PLAN_WAIT_UNTIL
        assert d.reason_params == {"time": "14:00"}
        _same_but_reason(d, decide(_outside_block(v)))

    def test_a_firing_rule_is_unchanged(self):
        d = decide(_view())
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d.reason_code == RC.CHARGER_SUN_PLUS_GRID


# ── guards ────────────────────────────────────────────────────────────

def _verdict_no_words():
    """Every word ``thin_sun_verdict`` answers "no" with, read from its
    source, plus the hard words ``_thin_sun_top_up`` hands it."""
    words = set()
    tree = ast.parse(inspect.getsource(ts.thin_sun_verdict))
    returns = [n.value for n in ast.walk(tree)
               if isinstance(n, ast.Return) and n.value is not None]
    for value in returns:           # a tuple anywhere in it: `a if c else b`
        for node in ast.walk(value):
            if isinstance(node, ast.Tuple) and len(node.elts) == 2:
                first, second = node.elts
                if (isinstance(first, ast.Constant) and first.value is False
                        and isinstance(second, ast.Constant)):
                    words.add(second.value)
    tree = ast.parse(inspect.getsource(decide_mod._thin_sun_top_up))
    for node in ast.walk(tree):
        if (isinstance(node, ast.Assign)
                and any(getattr(t, "id", None) == "hard" for t in node.targets)
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, str)):
            words.add(node.value.value)
    return words


def test_every_no_of_the_rule_is_placed_once():
    """A new "no" in the rule must say where its reason goes, or CI fails."""
    words = _verdict_no_words()
    assert {"battery_takes_sun", "peak_limit", "battery_pays",
            "no_plan_block", "not_cheaper", "price_unread"} <= words  # the scan works
    held, keeps, not_asked = (set(THIN_SUN_HELD_CODES), set(THIN_SUN_KEEPS_CODE),
                              set(THIN_SUN_NOT_ASKED))
    assert not (held & keeps) and not (held & not_asked) and not (keeps & not_asked)
    assert words == held | keeps | not_asked, words ^ (held | keeps | not_asked)
    # the hard limits the rule itself answers are all placed
    assert {w for w in ts.HARD_LIMITS
            if w not in ("car_absent", "peak_hour")} <= held | keeps | not_asked


def test_every_held_code_is_a_known_code_with_a_sentence_everywhere():
    data = json.loads((ROOT / "dashboard" / "translations.json")
                      .read_text(encoding="utf-8"))
    assert set(THIN_SUN_HELD_CODES.values()) == set(NEW_CODES)
    for code in NEW_CODES:
        assert code in RC.ALL_CODES
        assert code not in RC.PARAMS            # no placeholders
        en = data["en"][RC.catalogue_key(code)]
        for lang, table in data.items():
            text = table.get(RC.catalogue_key(code))
            assert isinstance(text, str) and text.strip(), (lang, code)
            assert "{" not in text, (lang, code)
            if lang != "en":
                assert text != en, (lang, code)
