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
