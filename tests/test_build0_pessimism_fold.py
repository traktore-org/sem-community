"""Build 0 (2.1 plan) — caution is not counted twice once trust is measured.

The spendable chain stacked three safety layers:

  * ``UNTRUSTED_FACTOR`` (0.7) on the refill while no measured trust exists;
  * measured **p20 trust** on the refill once the ledger has evidence
    (bug class 52 — a LOW percentile of what the sun delivers);
  * ``pessimism`` (1.2) inflating the overnight reserve, always.

The third multiplied the second: after 116 measured days said "plan on 84 %
of the forecast", a hand-set 1.2 still inflated the reserve as if nothing had
been measured. Caution twice is not twice as safe — it is a budget that
never opens, wearing a calm face ("holding" — which reads as a decision).

The fold: pessimism stays exactly as it was while trust is UNEARNED, and
relaxes to 1.0 once a measured trust factor is applied to the refill — the
measurement takes over the same job. ``forecast_pessimism`` was never a
config-flow option (verified in the Build-0 audit), so no user surface
changes; the config key keeps working for anyone who set it by hand and is
then honoured in BOTH regimes (an explicit choice beats the fold).
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.spendable_budget import (
    DEFAULT_PESSIMISM,
    spendable_budget,
)


ARGS = dict(soc_pct=80.0, usable_capacity_kwh=15.0, overnight_need_kwh=5.0,
            expected_refill_kwh=10.0, static_floor_pct=10.0,
            discharge_efficiency=1.0)


class TestTheFold:
    def test_unearned_trust_keeps_the_default_margin(self):
        """No measured trust → the 1.2 margin stands, byte-for-byte."""
        b = spendable_budget(**ARGS, pessimism=None, refill_trusted=False)
        # stored 12.0 − need 5.0*1.2 − floor 1.5 = 4.5
        assert abs(b.spendable_kwh - 4.5) < 0.01

    def test_measured_trust_relaxes_the_margin_to_one(self):
        """Measured trust on the refill → pessimism folds to 1.0: the p20
        measurement now does that job."""
        b = spendable_budget(**ARGS, pessimism=None, refill_trusted=True)
        # stored 12.0 − need 5.0*1.0 − floor 1.5 = 5.5
        assert abs(b.spendable_kwh - 5.5) < 0.01, (
            f"{b.spendable_kwh} — caution is being counted twice (Build 0)"
        )

    def test_an_explicit_hand_set_value_wins_in_both_regimes(self):
        """Somebody who typed forecast_pessimism into their config meant it."""
        for trusted in (False, True):
            b = spendable_budget(**ARGS, pessimism=1.5, refill_trusted=trusted)
            assert abs(b.spendable_kwh - (12.0 - 7.5 - 1.5)) < 0.01

    def test_default_constant_unchanged(self):
        assert DEFAULT_PESSIMISM == 1.2
