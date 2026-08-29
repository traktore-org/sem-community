"""#778 — the reporter's and maintainer's own worked examples, as tests.

Every number here comes from the issue or from a real night, not from
imagination. Simulating them is what caught the additive-reserve bug: the
issue's arithmetic is ``28.5 − 7 − 2 = 19.5``, and an implementation taking
``max(night, floor)`` would have let the pack reach its emergency floor before
sunrise — the one thing the floor exists to prevent.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.spendable_budget import (
    spendable_budget,
)


@pytest.mark.unit
class TestTheReportersWorkedExample:
    """#778 body: 30 kWh pack at 95 %, 7 kWh overnight, 2 kWh safety reserve,
    tomorrow forecast 40 kWh PV against 12 kWh daytime load."""

    def test_it_reproduces_the_issue_arithmetic(self):
        r = spendable_budget(
            soc_pct=95.0, usable_capacity_kwh=30.0,
            overnight_need_kwh=7.0,
            expected_refill_kwh=28.0,          # 40 forecast − 12 daytime load
            static_floor_pct=2.0 / 30.0 * 100, # the 2 kWh safety reserve
            pessimism=1.0, discharge_efficiency=1.0,
        )
        # 28.5 stored − 7 overnight − 2 reserve = 19.5
        assert r.spendable_kwh == pytest.approx(19.5, abs=0.05)

    def test_tomorrows_surplus_is_enough_so_it_is_not_the_binding_limit(self):
        r = spendable_budget(
            soc_pct=95.0, usable_capacity_kwh=30.0, overnight_need_kwh=7.0,
            expected_refill_kwh=28.0, static_floor_pct=2.0 / 30.0 * 100,
            pessimism=1.0, discharge_efficiency=1.0,
        )
        assert "refill" not in r.reason, r.reason

    def test_a_poor_forecast_retains_more_energy(self):
        """'If tomorrow is forecast to have poor solar production, SEM should
        automatically retain more energy in the battery instead.'"""
        poor = spendable_budget(
            soc_pct=95.0, usable_capacity_kwh=30.0, overnight_need_kwh=7.0,
            expected_refill_kwh=5.0, static_floor_pct=2.0 / 30.0 * 100,
            pessimism=1.0, discharge_efficiency=1.0,
        )
        assert poor.spendable_kwh == pytest.approx(5.0, abs=0.05)
        assert "refill" in poor.reason


@pytest.mark.unit
class TestTheDynamicReserveIsActuallyDynamic:
    """#778: 'Tonight: minimum SOC 30 % because tomorrow is very sunny' vs
    'minimum SOC 70 % because tomorrow is cloudy.' The whole point is that this
    is computed, not configured."""

    def _floor(self, refill):
        return spendable_budget(
            soc_pct=95.0, usable_capacity_kwh=30.0, overnight_need_kwh=7.0,
            expected_refill_kwh=refill, static_floor_pct=2.0 / 30.0 * 100,
            pessimism=1.0, discharge_efficiency=1.0,
        ).floor_pct

    def test_a_sunny_tomorrow_gives_a_low_floor(self):
        assert self._floor(28.0) == pytest.approx(30.0, abs=1.0)

    def test_a_cloudy_tomorrow_gives_a_much_higher_floor(self):
        """Same pack, same night — only the forecast differs."""
        assert self._floor(7.0) > 70.0

    def test_the_floor_moves_with_the_forecast_not_the_config(self):
        assert self._floor(28.0) < self._floor(14.0) < self._floor(2.0)


@pytest.mark.unit
class TestTheEveningEvCase:
    """The maintainer's live PROD night: pack full by midday, an evening
    solar-min charge took it 100→81 %, and the house drained it to only 53 % by
    07:00 — half the pack rode unused into a morning whose forecast refilled it
    anyway."""

    def test_the_evening_has_a_real_budget_when_tomorrow_is_strong(self):
        r = spendable_budget(
            soc_pct=100.0, usable_capacity_kwh=30.0, overnight_need_kwh=8.0,
            expected_refill_kwh=25.0, static_floor_pct=20.0,
            pessimism=1.2, discharge_efficiency=0.95,
        )
        # 30 stored − (8/0.95×1.2 = 10.1) − 6 floor ≈ 13.9 kWh for the car
        assert r.spendable_kwh > 12.0
        assert r.floor_pct < 55.0, (
            "the pack should be free to end the night near its floor, which is "
            "the whole complaint — it rode 53% into a refilling morning"
        )

    def test_winter_night_keeps_the_pack_back(self):
        """Same code, same pack, a 14 kWh night and a weak forecast: the budget
        must reverse its answer without anyone reconfiguring anything."""
        r = spendable_budget(
            soc_pct=100.0, usable_capacity_kwh=30.0, overnight_need_kwh=14.0,
            expected_refill_kwh=4.0, static_floor_pct=20.0,
            pessimism=1.2, discharge_efficiency=0.95,
        )
        assert r.spendable_kwh <= 4.0
        assert r.floor_pct > 85.0


@pytest.mark.unit
class TestSafetyHoldsInEveryCase:

    def test_the_budget_never_makes_the_dawn_worse(self):
        """The honest contract. A 25 kWh night on a 30 kWh pack breaches a
        6 kWh floor whatever anyone decides — the budget cannot rescue a night
        bigger than the pack. What it MUST do is never contribute to the
        breach: where the night alone already lands at or under the floor, the
        spendable budget is zero."""
        cap, floor_pct = 30.0, 20.0
        floor_kwh = floor_pct / 100.0 * cap
        for need in (0.0, 4.0, 8.0, 14.0, 25.0):
            for refill in (0.0, 5.0, 15.0, 40.0, 999.0):
                r = spendable_budget(
                    soc_pct=100.0, usable_capacity_kwh=cap,
                    overnight_need_kwh=need, expected_refill_kwh=refill,
                    static_floor_pct=floor_pct,
                )
                dawn_without_spending = cap - need
                dawn_after_spending = dawn_without_spending - r.spendable_kwh

                if dawn_without_spending <= floor_kwh:
                    assert r.spendable_kwh == 0.0, (
                        f"need={need} already breaches the floor on its own — "
                        "the budget must not add to it"
                    )
                else:
                    assert dawn_after_spending >= floor_kwh - 0.35, (
                        f"need={need} refill={refill}: spending "
                        f"{r.spendable_kwh} would push dawn below the floor"
                    )

    def test_it_refuses_a_night_bigger_than_the_pack(self):
        r = spendable_budget(
            soc_pct=100.0, usable_capacity_kwh=30.0, overnight_need_kwh=25.0,
            expected_refill_kwh=40.0, static_floor_pct=20.0,
        )
        assert r.spendable_kwh == 0.0
        assert "nothing spendable" in r.reason
