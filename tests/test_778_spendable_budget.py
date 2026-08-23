"""#778 — how much of the battery is genuinely surplus tonight?

The reporter's case: a 30 kWh pack, 5–10 kWh of overnight house load in
summer, and a battery that sits full at sunset for no reason. He wants the
excess sold into the best export window — **but only when tomorrow's sun can
put it back**.

This module answers only the first question of the budget triangle — HOW MUCH
is spendable (Guido's framing: HOW MUCH = the learner, WHO = the device list,
SAFETY = static floors). It decides nothing about *when* to sell or *who*
gets it; the sell path (#533) and the evening EV assist are the sinks, and
they already exist. The missing centre was the number.

Design rules, in priority order — each is a test below:

1. **The static floor is not negotiable.** A reserve SOC is a promise about
   blackouts and pack health; no forecast may spend through it.
2. **Keep the night.** Reserve the forecast overnight need, divided by
   discharge efficiency (you must store more than you draw) and inflated by
   the user's pessimism factor.
3. **Only spend what tomorrow can put back.** Selling energy the sun will not
   replace just moves the purchase to a worse hour.
4. **An unknown input spends nothing.** Missing forecast, missing capacity,
   unknown SOC → zero. #818's rule generalised: a dark input must never be
   read as permission.
5. **Say why.** Every result carries the binding constraint, because a number
   a user cannot explain is one they will not trust (#830).
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.spendable_budget import (
    SpendableBudget,
    spendable_budget,
    DEFAULT_STATIC_FLOOR_PCT,
)


def _b(**kw):
    """A comfortable summer night unless a test says otherwise: 30 kWh pack at
    90 %, 8 kWh of house load overnight, 25 kWh of surplus expected tomorrow."""
    args = dict(
        soc_pct=90.0,
        usable_capacity_kwh=30.0,
        overnight_need_kwh=8.0,
        expected_refill_kwh=25.0,
        static_floor_pct=20.0,
        pessimism=1.2,
        discharge_efficiency=0.95,
    )
    args.update(kw)
    return spendable_budget(**args)


@pytest.mark.unit
class TestTheSafetyFloorIsNotNegotiable:

    def test_never_spends_through_the_static_floor(self):
        r = _b(soc_pct=25.0, static_floor_pct=20.0, overnight_need_kwh=0.0)
        # 25% of 30 kWh = 7.5; floor 20% = 6.0 → at most 1.5 spendable
        assert r.spendable_kwh <= 1.5 + 1e-9
        assert r.floor_pct >= 20.0

    def test_at_the_floor_nothing_is_spendable(self):
        r = _b(soc_pct=20.0, static_floor_pct=20.0, overnight_need_kwh=0.0)
        assert r.spendable_kwh == 0.0

    def test_below_the_floor_never_goes_negative(self):
        r = _b(soc_pct=10.0, static_floor_pct=20.0)
        assert r.spendable_kwh == 0.0


@pytest.mark.unit
class TestKeepTheNight:

    def test_the_overnight_need_is_reserved(self):
        """8 kWh needed, 0.95 discharge efficiency, 1.2 pessimism
        → 8 / 0.95 * 1.2 = 10.10 kWh must stay in the pack."""
        r = _b(soc_pct=100.0, static_floor_pct=0.0, expected_refill_kwh=99.0)
        reserved = 8.0 / 0.95 * 1.2
        assert r.spendable_kwh == pytest.approx(30.0 - reserved, abs=0.01)

    def test_a_bigger_pessimism_reserves_more(self):
        cautious = _b(pessimism=2.0).spendable_kwh
        brave = _b(pessimism=1.0).spendable_kwh
        assert cautious < brave

    def test_efficiency_means_storing_more_than_you_draw(self):
        lossy = _b(discharge_efficiency=0.80).spendable_kwh
        ideal = _b(discharge_efficiency=1.00).spendable_kwh
        assert lossy < ideal


@pytest.mark.unit
class TestOnlySpendWhatTomorrowPutsBack:

    def test_capped_by_the_expected_refill(self):
        """The reporter's own condition: sell only when the sun replaces it."""
        r = _b(soc_pct=100.0, static_floor_pct=0.0, expected_refill_kwh=4.0)
        assert r.spendable_kwh == pytest.approx(4.0, abs=0.01)
        assert "refill" in r.reason

    def test_no_sun_tomorrow_means_no_spending(self):
        r = _b(expected_refill_kwh=0.0)
        assert r.spendable_kwh == 0.0

    def test_plenty_of_sun_falls_back_to_the_night_reserve(self):
        r = _b(soc_pct=100.0, static_floor_pct=0.0, expected_refill_kwh=999.0)
        assert r.spendable_kwh > 0
        assert "night" in r.reason or "reserve" in r.reason


@pytest.mark.unit
class TestAnUnknownInputSpendsNothing:
    """#818 generalised: a dark input is not permission."""

    @pytest.mark.parametrize("kw", [
        {"soc_pct": None},
        {"usable_capacity_kwh": None},
        {"overnight_need_kwh": None},
        {"expected_refill_kwh": None},
        {"usable_capacity_kwh": 0.0},
    ])
    def test_missing_input_yields_zero(self, kw):
        r = _b(**kw)
        assert r.spendable_kwh == 0.0
        assert r.floor_pct is None or r.floor_pct >= 0
        assert "unknown" in r.reason or "no " in r.reason

    def test_a_nonsense_value_is_treated_as_unknown(self):
        assert _b(soc_pct="n/a").spendable_kwh == 0.0


@pytest.mark.unit
class TestItSaysWhy:
    """A number a user cannot explain is one they will not trust (#830)."""

    def test_every_result_names_its_binding_constraint(self):
        for kw in ({}, {"expected_refill_kwh": 2.0}, {"soc_pct": 21.0},
                   {"expected_refill_kwh": 0.0}, {"soc_pct": None}):
            r = _b(**kw)
            assert isinstance(r, SpendableBudget)
            assert r.reason and len(r.reason) > 8, kw

    def test_the_floor_is_reported_as_a_percentage(self):
        r = _b()
        assert r.floor_pct is not None
        assert 0.0 <= r.floor_pct <= 100.0

    def test_the_floor_reflects_the_binding_constraint(self):
        """A big overnight need lifts the dynamic floor above the static one."""
        r = _b(overnight_need_kwh=20.0, static_floor_pct=10.0)
        assert r.floor_pct > 10.0


class TestAnUnknownFloorIsNotNoFloor:
    """An unconfigured reserve must not resolve to "spend to empty".

    Found by backtesting PROD: ``battery_reserve_soc`` is **None** there — the
    key exists with a null value, so ``config.get("battery_reserve_soc", 20)``
    returns None rather than the 20 the default was meant to supply, and the
    budget then read the floor as 0.0. The user's "never below this, ever"
    backstop, silently absent, on the one install with a real battery.

    The distinction that matters: an explicit 0 is a choice ("spend it all"),
    while None is an absence ("nobody said"). Collapsing the second into the
    first is how a safety default stops applying to precisely the installs
    that never touched it — the unconfigured-sibling class.
    """

    def test_none_falls_back_to_the_safe_default_not_zero(self):
        # The refill is deliberately generous so the FLOOR is the binding
        # term. With a small refill the budget is capped by tomorrow's sun in
        # every case and the floor never shows — a scenario that would pass
        # against the bug and prove nothing.
        b = spendable_budget(
            soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
            expected_refill_kwh=20.0, static_floor_pct=None,
        )
        floorless = spendable_budget(
            soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
            expected_refill_kwh=20.0, static_floor_pct=0.0,
        )
        assert b.spendable_kwh < floorless.spendable_kwh, (
            "an unconfigured floor spends as much as an explicitly zero one — "
            "the reserve default never applied")

    def test_none_matches_the_documented_default(self):
        assert spendable_budget(
            soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
            expected_refill_kwh=20.0, static_floor_pct=None,
        ).spendable_kwh == spendable_budget(
            soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
            expected_refill_kwh=20.0, static_floor_pct=DEFAULT_STATIC_FLOOR_PCT,
        ).spendable_kwh

    def test_an_explicit_zero_is_still_honoured(self):
        """Someone who deliberately sets 0 means it. The fix must not take
        that choice away — it only fills in for silence."""
        b = spendable_budget(
            soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
            expected_refill_kwh=20.0, static_floor_pct=0.0,
        )
        assert b.floor_pct is not None
        assert b.spendable_kwh > 0

    def test_junk_is_treated_as_silence(self):
        for bad in ("", "x", float("nan")):
            b = spendable_budget(
                soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
                expected_refill_kwh=20.0, static_floor_pct=bad,
            )
            assert b.spendable_kwh == spendable_budget(
                soc_pct=90.0, usable_capacity_kwh=15.0, overnight_need_kwh=3.0,
                expected_refill_kwh=20.0, static_floor_pct=DEFAULT_STATIC_FLOOR_PCT,
            ).spendable_kwh, f"{bad!r} was not treated as 'nobody said'"


class TestTheCallSitePassesAFloor:
    def test_the_coordinator_does_not_rely_on_dict_get_default(self):
        """``config.get(key, 20)`` returns None when the key is present and
        null — which is exactly how PROD is configured. The call site must
        say what it means."""
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        assert 'static_floor_pct=self.config.get("battery_reserve_soc", 20)' not in src, (
            "the coordinator still leans on a dict default that a null value "
            "silently defeats")
