"""#778 — what is a percent of this battery actually worth?

Guido, 23.08: *"Does the battery SOC = energy also get a ledger, to have it all
there — or would that be too complicated?"*

Not complicated, and it needs **no new recording**: every sealed night from
#800 already carries `drain_kwh`, `soc_start`, `soc_morning`, `outdoor_temp_c`
and a `trainable` quality flag. So kWh-per-percent is arithmetic over records
SEM already writes — a reader, not a fourth ledger.

It matters more than the forecast ledger does. The budget's
`usable_capacity_kwh` is a configured **nameplate**. If a 30 kWh pack really
delivers 0.24 kWh/% against a nominal 0.30, every spendable number is 20 % too
generous — and it fails in the dangerous direction, selling energy the pack
did not have. Measuring it also tracks degradation for free: an ageing pack
simply reports fewer kWh per percent and the budget tightens itself.

Same shape as the other two quantities, deliberately: median over
quality-gated samples, `None` until there is evidence, never a confident
default.

The gates exist because of how the inputs really behave:
  * SOC is usually integer-resolution, so a small span is noise, not a
    measurement;
  * the curve is not linear at the extremes (top-balancing, BMS reserve);
  * a night that did not actually discharge measures nothing.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.measured_capacity import (
    MIN_SAMPLES,
    MIN_SOC_SPAN_PCT,
    measured_capacity,
)


def _night(soc_start=90.0, soc_morning=60.0, drain_kwh=7.5, trainable=True, **kw):
    """A clean night: 30 % of SOC delivered 7.5 kWh → 0.25 kWh per percent."""
    r = {"soc_start": soc_start, "soc_morning": soc_morning,
         "drain_kwh": drain_kwh, "trainable": trainable}
    r.update(kw)
    return r


@pytest.mark.unit
class TestItMeasuresWhatAPercentIsWorth:

    def test_a_clean_run_of_nights_yields_kwh_per_percent(self):
        m = measured_capacity([_night() for _ in range(MIN_SAMPLES)])
        assert m is not None
        assert m.kwh_per_pct == pytest.approx(0.25, abs=0.005)
        assert m.samples == MIN_SAMPLES

    def test_it_reports_the_implied_usable_capacity(self):
        m = measured_capacity([_night() for _ in range(MIN_SAMPLES)])
        assert m.usable_kwh == pytest.approx(25.0, abs=0.5)

    def test_the_median_survives_one_bad_night(self):
        """One freak reading must not move policy — the reason the shape is a
        median rather than a mean."""
        nights = [_night() for _ in range(MIN_SAMPLES)]
        nights.append(_night(drain_kwh=30.0))      # absurd outlier
        m = measured_capacity(nights)
        assert m.kwh_per_pct == pytest.approx(0.25, abs=0.02)

    def test_a_degrading_pack_reports_less(self):
        aged = [_night(drain_kwh=6.0) for _ in range(MIN_SAMPLES)]   # 0.20/%
        m = measured_capacity(aged)
        assert m.kwh_per_pct == pytest.approx(0.20, abs=0.005)


@pytest.mark.unit
class TestQualityGates:

    def test_untrainable_nights_are_ignored(self):
        assert measured_capacity(
            [_night(trainable=False) for _ in range(MIN_SAMPLES + 3)]) is None

    def test_a_small_soc_span_is_noise_not_a_measurement(self):
        """Integer-resolution SOC: a 3 % span cannot measure anything."""
        tiny = [_night(soc_start=70.0, soc_morning=67.0, drain_kwh=0.75)
                for _ in range(MIN_SAMPLES + 3)]
        assert measured_capacity(tiny) is None

    def test_the_span_threshold_is_the_boundary(self):
        ok = [_night(soc_start=90.0, soc_morning=90.0 - MIN_SOC_SPAN_PCT,
                     drain_kwh=0.25 * MIN_SOC_SPAN_PCT)
              for _ in range(MIN_SAMPLES)]
        assert measured_capacity(ok) is not None

    def test_a_night_with_no_discharge_measures_nothing(self):
        assert measured_capacity(
            [_night(drain_kwh=0.0) for _ in range(MIN_SAMPLES + 3)]) is None

    def test_a_rising_soc_is_rejected(self):
        """Charging overnight is not a discharge measurement."""
        assert measured_capacity(
            [_night(soc_start=40.0, soc_morning=80.0) for _ in range(MIN_SAMPLES + 3)]
        ) is None

    def test_missing_fields_are_skipped_not_guessed(self):
        bad = [{"trainable": True} for _ in range(MIN_SAMPLES + 3)]
        assert measured_capacity(bad) is None


@pytest.mark.unit
class TestUnknownUntilThereIsEvidence:
    """Same rule as the forecast ledger: a confident default before evidence
    is worse than admitting ignorance."""

    def test_no_records_is_none(self):
        assert measured_capacity([]) is None
        assert measured_capacity(None) is None

    def test_below_the_sample_threshold_is_none(self):
        assert measured_capacity([_night() for _ in range(MIN_SAMPLES - 1)]) is None

    def test_it_never_invents_a_nameplate(self):
        """It must not fall back to the configured capacity — the caller needs
        to know the difference between measured and assumed."""
        assert measured_capacity([]) is None


@pytest.mark.unit
class TestItSaysWhy:

    def test_the_result_explains_itself(self):
        m = measured_capacity([_night() for _ in range(MIN_SAMPLES)])
        assert m.reason and str(MIN_SAMPLES) in m.reason or "night" in m.reason

    def test_it_can_be_compared_against_the_nameplate(self):
        """The interesting number for a user is the DIFFERENCE."""
        m = measured_capacity([_night() for _ in range(MIN_SAMPLES)])
        drift = m.drift_vs(nameplate_kwh=30.0)
        assert drift == pytest.approx((25.0 - 30.0) / 30.0, abs=0.02)


@pytest.mark.unit
class TestTheOvernightNeedIsAnEnvelopeNotAnAverage:
    """Guido's framing on #778: the learner-safe ENVELOPE. Reserving the
    typical night leaves the pack short on half of them — and short is not
    symmetric with generous. One costs a little export revenue; the other
    strands the house at its floor before dawn."""

    def _nights(self, drains):
        return [{"soc_start": 90.0, "soc_morning": 60.0, "drain_kwh": d,
                 "trainable": True} for d in drains]

    def test_it_reserves_above_the_median(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            expected_overnight_need,
        )
        need = expected_overnight_need(self._nights([4, 5, 6, 7, 8, 9, 20]))
        assert need is not None
        assert need > 7, "an average would under-reserve on the bad nights"

    def test_thin_evidence_is_none_not_a_guess(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            MIN_NEED_SAMPLES, expected_overnight_need,
        )
        assert expected_overnight_need(self._nights([5] * (MIN_NEED_SAMPLES - 1))) is None

    def test_untrainable_nights_are_ignored(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            expected_overnight_need,
        )
        bad = [{"drain_kwh": 5.0, "trainable": False} for _ in range(9)]
        assert expected_overnight_need(bad) is None


class TestTheEnvelopePercentileIsMeasured:
    """(#778) p85, and the number came from data rather than taste.

    The envelope was p80 by judgement — "a high percentile, because being short
    is not symmetric with being generous". Correct in direction, unargued in
    magnitude. Backtesting 211 real PROD nights priced every candidate:

        pctile  spending nights  total spent  breaches  worst
        p70     103              74.0 kWh     3 (3%)    -0.48 kWh
        p80      97              63.6 kWh     3 (3%)    -0.40 kWh
        p85      90              53.5 kWh     2 (2%)    -0.12 kWh
        p90      68              30.0 kWh     1 (1%)    -0.05 kWh
        p95       5               0.3 kWh     0         -

    p85 is the knee: the worst floor violation drops 70% (400 Wh -> 120 Wh, on
    a 15 kWh pack) while 84% of the energy survives. p90 costs HALF the value
    for a further 70 Wh, and p95 is a cliff — the feature stops working, five
    nights out of two hundred and eleven.

    One install's data, so the value is a default and not a law; the sweep that
    produced it ships as ``scripts/backtest_budget.py --need-pctile`` so any
    install can price its own.
    """

    def test_the_envelope_is_p85(self):
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            NEED_PERCENTILE,
        )
        assert NEED_PERCENTILE == 0.85

    def test_it_is_a_high_percentile_not_an_average(self):
        """The property that must survive any future retuning: the envelope
        reserves for a HEAVY night, never a typical one."""
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            NEED_PERCENTILE,
        )
        assert NEED_PERCENTILE > 0.5

    def test_it_reserves_above_the_median_of_real_drains(self):
        drains = [3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 20.0]
        records = [{"date": f"2026-08-{i:02d}", "drain_kwh": d,
                    "soc_start": 90.0, "soc_morning": 60.0, "trainable": True}
                   for i, d in enumerate(drains, start=1)]
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            expected_overnight_need,
        )
        need = expected_overnight_need(records)
        median = sorted(drains)[len(drains) // 2]
        assert need > median, (
            "the envelope reserves the typical night, which leaves the pack "
            "short on half of them")

    def test_it_does_not_simply_take_the_worst_night(self):
        """p100 reserved everything and spent nothing — five spending nights
        out of 211. An envelope that never releases energy is not safe, it is
        absent."""
        drains = [3.0] * 9 + [30.0]
        records = [{"date": f"2026-08-{i:02d}", "drain_kwh": d,
                    "soc_start": 90.0, "soc_morning": 60.0, "trainable": True}
                   for i, d in enumerate(drains, start=1)]
        from custom_components.solar_energy_management.coordinator.measured_capacity import (
            expected_overnight_need,
        )
        assert expected_overnight_need(records) < 30.0
