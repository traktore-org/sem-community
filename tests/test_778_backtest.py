"""#778 — replay history through the budget and count how often it was wrong.

Guido's point, and the real prize of the backfill: an install with months of
history does not just have enough evidence to START the budget, it has enough
to CHECK it. Every past night is a scenario with a known answer — the pack was
at some SOC at dusk, the house drew some amount overnight, the sun delivered
something the next day. So for every one of them we can ask the question the
feature exists to answer, and then look up what actually happened.

That gives the arc the one thing it has never had: an oracle. Until now
"the budget is right" rested on unit tests against the issue's own worked
examples — which is a test that the code does what I decided it should do, not
a test that what I decided was correct.

The failure the backtest hunts for is specific and asymmetric. Spending too
little costs a little export revenue and nobody notices. Spending too much
strands the house at its floor before dawn, on a night the user cannot
un-spend. So the number that matters is not average accuracy — it is **how
many nights would have breached the floor**, and by how much on the worst one.
"""

import pytest

from custom_components.solar_energy_management.coordinator.budget_backtest import (
    backtest,
    replay_night,
)


class TestOneNight:
    def test_a_comfortable_night_leaves_margin(self):
        """15 kWh pack at 90 % (13.5 stored), 3 kWh spent, the house then
        draws 4 kWh. Floor is 20 % = 3.0 kWh. 13.5 - 3 - 4 = 6.5, well clear."""
        out = replay_night(
            date="2026-08-20", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=3.0, actual_drain_kwh=4.0, static_floor_pct=20.0,
        )
        assert out.breached is False
        assert out.margin_kwh == pytest.approx(3.5)

    def test_spending_that_strands_the_house_is_a_breach(self):
        """Same pack, but the budget said 6 kWh and the house drew 6.
        13.5 - 6 - 6 = 1.5, below the 3.0 floor."""
        out = replay_night(
            date="2026-08-20", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=6.0, actual_drain_kwh=6.0, static_floor_pct=20.0,
        )
        assert out.breached is True
        assert out.margin_kwh == pytest.approx(-1.5)

    def test_landing_exactly_on_the_floor_is_not_a_breach(self):
        """The floor is a floor, not a fence — reaching it is the plan."""
        out = replay_night(
            date="2026-08-20", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=6.5, actual_drain_kwh=4.0, static_floor_pct=20.0,
        )
        assert out.margin_kwh == pytest.approx(0.0)
        assert out.breached is False

    def test_a_night_the_budget_declined_can_still_breach(self):
        """Spending nothing does not make a night safe: a 12 kWh draw on a
        13.5 kWh pack breaches the floor on its own. These nights must NOT be
        counted against the budget — it did nothing — but they must be visible,
        because a budget that never spends is not thereby correct."""
        out = replay_night(
            date="2026-08-20", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=0.0, actual_drain_kwh=12.0, static_floor_pct=20.0,
        )
        assert out.breached is True
        assert out.caused_by_budget is False

    def test_a_breach_the_budget_caused_is_attributed_to_it(self):
        out = replay_night(
            date="2026-08-20", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=6.0, actual_drain_kwh=6.0, static_floor_pct=20.0,
        )
        assert out.breached is True
        assert out.caused_by_budget is True, (
            "the night survives on 0 spend and breaches on this one — the "
            "budget is what made the difference")


class TestTheReport:
    def _nights(self, n, *, spend, drain):
        return [
            replay_night(date=f"2026-08-{d:02d}", capacity_kwh=15.0,
                         soc_start_pct=90.0, spendable_kwh=spend,
                         actual_drain_kwh=drain, static_floor_pct=20.0)
            for d in range(1, n + 1)
        ]

    def test_a_clean_run_reports_no_breaches(self):
        rep = backtest(self._nights(30, spend=3.0, drain=4.0))
        assert rep.nights == 30
        assert rep.breaches_caused == 0
        assert rep.worst_margin_kwh == pytest.approx(3.5)

    def test_breaches_are_counted_and_the_worst_is_kept(self):
        nights = self._nights(9, spend=3.0, drain=4.0)
        nights.append(replay_night(
            date="2026-08-10", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=6.0, actual_drain_kwh=7.0, static_floor_pct=20.0))
        rep = backtest(nights)
        assert rep.nights == 10
        assert rep.breaches_caused == 1
        assert rep.breach_rate == pytest.approx(0.1)
        assert rep.worst_margin_kwh == pytest.approx(-2.5)

    def test_an_empty_run_is_not_a_pass(self):
        """A backtest with no nights must not read as 'zero breaches'. It has
        proven nothing, and saying so is the entire point."""
        rep = backtest([])
        assert rep.nights == 0
        assert rep.breach_rate is None
        assert rep.verdict == "no evidence"

    def test_the_verdict_names_the_asymmetry(self):
        clean = backtest(self._nights(30, spend=3.0, drain=4.0))
        assert clean.verdict == "no breach"
        nights = self._nights(1, spend=6.0, drain=7.0)
        assert backtest(nights).verdict == "breached"


class TestJunk:
    def test_missing_capacity_is_unscorable_not_clean(self):
        out = replay_night(date="x", capacity_kwh=None, soc_start_pct=90.0,
                           spendable_kwh=1.0, actual_drain_kwh=1.0,
                           static_floor_pct=20.0)
        assert out.scorable is False
        rep = backtest([out])
        assert rep.nights == 0, "an unscorable night must not pad the sample"

    def test_missing_drain_is_unscorable(self):
        out = replay_night(date="x", capacity_kwh=15.0, soc_start_pct=90.0,
                           spendable_kwh=1.0, actual_drain_kwh=None,
                           static_floor_pct=20.0)
        assert out.scorable is False


class TestAFloorLimitedNight:
    """A pack that stopped AT its floor was not deepened by the budget.

    Found backtesting PROD: every "worst breach" showed ``margin == -spend``
    exactly, and depletion + spend summing to precisely the distance from dusk
    SOC down to the floor. The pack had stopped at 20.0% on the dot — because
    the hardware stops it there. That is the floor working, not the budget
    breaking it.

    On such a night the spend cannot make the discharge deeper; the battery
    will refuse. What it does instead is bring the moment of exhaustion
    FORWARD, so the house imports from the grid for longer. That is a cost to
    weigh, not a safety failure to prevent — and counting it as a breach both
    slanders the budget and, worse, drowns out the nights where the pack really
    did have room to go lower and the budget used it up.
    """

    FLOOR = 20.0
    CAP = 15.0

    def _night(self, soc_start, soc_low, spend):
        return replay_night(
            date="2026-06-19", capacity_kwh=self.CAP, soc_start_pct=soc_start,
            spendable_kwh=spend,
            actual_drain_kwh=self.CAP * (soc_start - soc_low) / 100.0,
            static_floor_pct=self.FLOOR, soc_low_pct=soc_low,
        )

    def test_a_pack_that_stopped_at_the_floor_is_not_a_breach(self):
        out = self._night(soc_start=100.0, soc_low=20.0, spend=0.96)
        assert out.floor_limited is True
        assert out.caused_by_budget is False, (
            "the pack stopped at its floor; the spend could not have taken it "
            "lower")

    def test_it_is_still_reported_as_a_shortened_night(self):
        """Not a breach, but not free either — the house lost battery support
        earlier than it otherwise would."""
        out = self._night(soc_start=100.0, soc_low=20.0, spend=0.96)
        assert out.shortened_kwh == pytest.approx(0.96)

    def test_a_pack_with_room_left_can_still_be_breached(self):
        """The case the metric exists for: the night ended well above the
        floor, so the budget genuinely had room to spend it away."""
        out = self._night(soc_start=100.0, soc_low=25.0, spend=2.0)
        assert out.floor_limited is False
        assert out.breached is True
        assert out.caused_by_budget is True

    def test_without_a_soc_low_the_old_behaviour_stands(self):
        """soc_low is optional — callers that cannot supply it (unit tests,
        installs with no SOC history) must keep working."""
        out = replay_night(
            date="x", capacity_kwh=15.0, soc_start_pct=90.0,
            spendable_kwh=6.0, actual_drain_kwh=6.0, static_floor_pct=20.0,
        )
        assert out.floor_limited is False
        assert out.breached is True

    def test_the_report_separates_the_two(self):
        nights = [self._night(100.0, 20.0, 1.0) for _ in range(5)]
        nights.append(self._night(100.0, 25.0, 2.0))
        rep = backtest(nights)
        assert rep.breaches_caused == 1, "floor-limited nights were counted"
        assert rep.floor_limited_nights == 5
