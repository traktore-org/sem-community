"""#778 — "will it refill" is not a scalar question.

Guido pinned this before anyone built it: the morning solar is also claimed by
tomorrow's packed EV blocks and loads. A 40 kWh day owing the house 12 kWh and
the car 10 kWh refills the pack with 18 kWh, not 40 — and a budget handed the
raw number would sell energy that was never coming back.

The clipping case is the sharpest thing in the whole issue: surplus the pack
cannot physically hold is thrown away tomorrow *unless room is made tonight*.
Spending that is not a bet on the forecast — it is a bet against waste.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.refill_estimate import (
    UNTRUSTED_FACTOR,
    estimate_refill,
)


@pytest.mark.unit
class TestTomorrowsClaimsAreSubtracted:

    def test_the_house_takes_its_share(self):
        r = estimate_refill(40.0, house_tomorrow_kwh=12.0, trust=1.0)
        assert r.refill_kwh == pytest.approx(28.0, abs=0.05)

    def test_committed_demands_take_theirs_too(self):
        """The subtraction a scalar forecast cannot do."""
        r = estimate_refill(40.0, house_tomorrow_kwh=12.0,
                            committed_demand_kwh=10.0, trust=1.0)
        assert r.refill_kwh == pytest.approx(18.0, abs=0.05)
        assert "committed" in r.reason

    def test_a_day_that_owes_more_than_it_makes_refills_nothing(self):
        r = estimate_refill(10.0, house_tomorrow_kwh=12.0,
                            committed_demand_kwh=5.0, trust=1.0)
        assert r.refill_kwh == 0.0


@pytest.mark.unit
class TestTrustIsAppliedAndDeclared:

    def test_a_measured_trust_factor_scales_the_forecast(self):
        r = estimate_refill(40.0, house_tomorrow_kwh=10.0, trust=0.8)
        assert r.refill_kwh == pytest.approx(40.0 * 0.8 - 10.0, abs=0.05)
        assert r.trusted is True
        assert "measured" in r.reason

    def test_without_evidence_it_is_conservative_and_says_so(self):
        """Refusing to estimate until a season has passed would mean the
        feature never starts; believing an untested forecast is how a battery
        ends the night at its floor. So: a pessimistic constant, declared."""
        r = estimate_refill(40.0, house_tomorrow_kwh=10.0, trust=None)
        assert r.trusted is False
        assert r.refill_kwh == pytest.approx(40.0 * UNTRUSTED_FACTOR - 10.0, abs=0.05)
        assert "unproven" in r.reason
        assert UNTRUSTED_FACTOR < 1.0

    def test_an_untrusted_estimate_is_never_more_optimistic_than_a_trusted_one(self):
        untrusted = estimate_refill(40.0, 10.0, trust=None).refill_kwh
        full = estimate_refill(40.0, 10.0, trust=1.0).refill_kwh
        assert untrusted < full


@pytest.mark.unit
class TestClippingIsTheStrongestArgument:

    def test_surplus_beyond_the_pack_is_reported_as_clipped(self):
        r = estimate_refill(40.0, house_tomorrow_kwh=5.0,
                            pack_headroom_kwh=10.0, trust=1.0)
        assert r.refill_kwh == pytest.approx(10.0, abs=0.05)
        assert r.clipped_kwh == pytest.approx(25.0, abs=0.05)

    def test_it_says_the_spend_costs_nothing(self):
        r = estimate_refill(40.0, 5.0, pack_headroom_kwh=10.0, trust=1.0)
        assert "clipped" in r.reason and "nothing" in r.reason

    def test_no_clipping_when_the_pack_can_hold_it(self):
        r = estimate_refill(20.0, 5.0, pack_headroom_kwh=30.0, trust=1.0)
        assert r.clipped_kwh == 0.0

    def test_unknown_headroom_claims_no_clipping(self):
        """Never assert 'free' without knowing the pack can't hold it."""
        r = estimate_refill(40.0, 5.0, pack_headroom_kwh=None, trust=1.0)
        assert r.clipped_kwh == 0.0


@pytest.mark.unit
class TestUnknownInputsRefuse:

    def test_no_forecast_is_none_not_zero(self):
        r = estimate_refill(None, 10.0)
        assert r.refill_kwh is None
        assert "unknown" in r.reason

    def test_no_house_expectation_is_none(self):
        r = estimate_refill(40.0, None)
        assert r.refill_kwh is None

    def test_none_is_distinguishable_from_a_genuine_zero(self):
        """A budget must tell 'no idea' from 'nothing coming' — the first means
        spend nothing, the second is a fact about tomorrow."""
        assert estimate_refill(None, 10.0).refill_kwh is None
        assert estimate_refill(5.0, 10.0, trust=1.0).refill_kwh == 0.0
