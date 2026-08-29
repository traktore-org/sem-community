"""#778 — trust is a LOW percentile, not an average.

Found by backfilling .175's own five months of history (Guido's idea): 139
settled forecast/actual pairs, and the distribution says something the mean
hides completely.

    mean ratio  1.050   ->  trust = min(1.0, mean) = 1.000
    p10  0.514   p20  0.734   p50  1.062   p90  1.502

The forecast is unbiased ON AVERAGE and wildly variable day to day. Under the
capped-mean rule SEM would spend against the full forecast — and on **58 of
those 139 days (42%)** the day delivered less than that. Nearly one day in two,
the battery would have been sold against energy that never arrived.

The codebase already contains the right argument, one module over:

    "Reserving the typical night leaves the pack short on half of them, and
     being short is not symmetric with being generous: one costs a little
     export revenue, the other strands the house at its floor before dawn."
                                        — measured_capacity.NEED_PERCENTILE

That asymmetry has a mirror image, and this is it. The need envelope takes a
HIGH percentile of what the house draws; the refill trust must take a LOW
percentile of what the sun delivers. Both answer "what if tomorrow is worse
than typical" — and only one of them was written that way.
"""

import pytest

from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    MIN_SAMPLES_FOR_TRUST,
    REFILL_TRUST_PERCENTILE,
    ForecastLedger,
)


def _ledger(ratios, horizon=1):
    """A ledger whose horizon-N ratios are exactly ``ratios``."""
    led = ForecastLedger()
    for i, r in enumerate(ratios):
        date = f"2026-0{1 + i // 28}-{1 + i % 28:02d}"
        led.record(date, horizon, 10.0)
        led.settle(date, 10.0 * r)
    return led


class TestTheMeanIsNotTheAnswer:
    def test_an_unbiased_but_volatile_forecast_is_not_fully_trusted(self):
        """The .175 shape in miniature: mean ~1.0, huge spread. The old rule
        returned 1.0 here — spend against the whole forecast."""
        ratios = [0.5, 0.6, 0.7, 1.0, 1.3, 1.4, 1.5]
        assert sum(ratios) / len(ratios) == pytest.approx(1.0, abs=0.01)
        trust = _ledger(ratios).trust(1)
        assert trust is not None
        assert trust < 0.75, (
            f"an unbiased forecast with a 3x spread was trusted at {trust} — "
            "the mean hides exactly the days that matter")

    def test_a_reliable_forecast_is_trusted_nearly_fully(self):
        """The rule must not punish a GOOD forecast. Tight around 1.0 →
        trust close to 1.0, because there is no bad case to reserve against."""
        trust = _ledger([0.97, 0.98, 0.99, 1.0, 1.01, 1.02, 1.03]).trust(1)
        assert trust >= 0.95

    def test_a_habitually_optimistic_forecast_is_heavily_discounted(self):
        trust = _ledger([0.4, 0.45, 0.5, 0.55, 0.6, 0.65, 0.7]).trust(1)
        assert trust <= 0.5

    def test_trust_is_still_capped_at_one(self):
        """A forecast that habitually UNDER-promises does not license spending
        more than it predicts."""
        assert _ledger([1.2, 1.3, 1.4, 1.5, 1.6, 1.7, 1.8]).trust(1) == 1.0


class TestTheRealDistribution:
    """.175's actual 139 pairs, reduced to the percentiles measured from them."""

    # The measured shape: p05 .461, p10 .514, p15 .607, p20 .734, p25 .829,
    # p30 .868, p50 1.062, mean 1.050.
    SHAPE = ([0.46] * 7 + [0.51] * 7 + [0.61] * 7 + [0.73] * 7 + [0.83] * 7
             + [0.87] * 14 + [1.06] * 28 + [1.30] * 34 + [1.50] * 28)

    def test_the_measured_distribution_does_not_yield_full_trust(self):
        trust = _ledger(self.SHAPE).trust(1)
        assert trust is not None
        assert trust < 0.9, (
            f"the real .175 distribution still trusts at {trust}; the whole "
            "point of the ledger is that this one must not read 1.0")

    def test_the_mean_of_that_distribution_really_is_about_one(self):
        """Guards the premise: if this drifts, the test above stops being the
        counter-example it claims to be."""
        assert sum(self.SHAPE) / len(self.SHAPE) == pytest.approx(1.05, abs=0.08)


class TestSharedWithAccuracy:
    def test_accuracy_still_reports_the_mean(self):
        """The mean stays available as a DIAGNOSTIC — it answers 'is the
        forecast biased', which is a real question. It just may not be the
        thing that decides spending."""
        acc = _ledger([0.5, 0.6, 0.7, 1.0, 1.3, 1.4, 1.5]).accuracy(1)
        assert acc.mean_ratio == pytest.approx(1.0, abs=0.01)
        assert acc.samples == 7

    def test_thin_evidence_still_returns_none(self):
        assert _ledger([1.0] * (MIN_SAMPLES_FOR_TRUST - 1)).trust(1) is None

    def test_the_percentile_is_low_by_construction(self):
        assert 0.0 < REFILL_TRUST_PERCENTILE <= 0.25
