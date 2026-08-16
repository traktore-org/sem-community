"""#755 pillar 3 — the learner.

The recorder writes what each demand actually did. This is the layer that
reads it back and answers one question per demand: *when this thing asks for
X, what does it really need?*

The whole design turns on one hazard. ``actual_kwh`` is **censored** — by the
packer above, and by the ask itself below:

* a night the packer promised less than was asked, or delivered less than it
  promised, says nothing about the need. Learning "asked 10, took 6, so it
  only needs 6" from a night where 6 was all it was OFFERED is the plan's own
  constraint teaching the plan to ask for less — a downward ratchet that
  converges on nothing, silently, over weeks. It is #744's bug (an estimate
  teaching a model) wearing the plan's own uniform;
* a night that ran right up to the ask proves the need was *at least* that
  much and possibly more. It may raise a suggestion; it may never lower one.

So only nights where the demand was offered everything it asked for **and
stopped on its own** teach the ask. Everything else is a floor.

The second rule is cold start: until enough such nights exist, the suggestion
IS the configured ask. A model that starts guessing on night two is a model
that is wrong in public.

The third rule is that this layer only ever SUGGESTS. Nothing in the demand
collection path reads it — the user owns their target, and a learner that
quietly rewrites it is not a feature anybody asked for.
"""

from datetime import datetime, timezone

import pytest

from custom_components.solar_energy_management.coordinator.demand_outcome import (
    DemandRecord,
)
from custom_components.solar_energy_management.coordinator.demand_learner import (
    DEFAULT_MIN_NIGHTS,
    AskSuggestion,
    suggest_ask,
    teaches_the_ask,
)


def _night(actual, *, asked=10.0, planned=None, status="fits",
           measured=True, samples=10, gap_s=0.0, night="2026-08-01"):
    return DemandRecord(
        demand_id="ev:keba", kind="ev", night=night,
        asked_kwh=asked,
        planned_kwh=asked if planned is None else planned,
        status=status, actual_kwh=actual,
        measured=measured, samples=samples, gap_s=gap_s,
    )


class TestWhatMayTeach:
    def test_a_night_that_stopped_on_its_own_teaches(self):
        assert teaches_the_ask(_night(7.0)) is True

    def test_a_partial_night_never_teaches(self):
        """The packer promised 6 of a 10 kWh ask. The car took 6 because 6
        was all it was given — not because 6 was enough. Reading that as
        'over-asking' is the plan teaching itself to ask for less."""
        assert teaches_the_ask(
            _night(6.0, planned=6.0, status="partial")) is False

    def test_a_night_with_a_hole_in_it_never_teaches(self):
        """A restart or a dead sensor leaves a gap the recorder refuses to
        integrate across. The kWh on the other side of that hole are real
        energy that was never counted, so a low ``actual`` here means
        'we looked away', not 'it was satisfied'. Unlike the promised-vs-
        delivered case — which is indistinguishable from a satisfied night
        by energy alone — a gap is *detectable*, so it is refused."""
        r = _night(6.0, gap_s=900.0)
        assert r.delivered_ratio == pytest.approx(0.6)
        assert teaches_the_ask(r) is False

    def test_a_night_that_ran_to_the_ask_never_teaches(self):
        """Taking all 10 of a 10 kWh ask means the need was at least 10 and
        may have been more. It is a floor, never a reduction."""
        assert teaches_the_ask(_night(10.0)) is False

    def test_an_unmeasured_night_never_teaches(self):
        """The guard is already nailed shut at the recorder. Pinned again at
        this door because this is the one that leads into a model."""
        assert teaches_the_ask(_night(7.0, measured=False)) is False

    def test_a_night_with_no_samples_never_teaches(self):
        assert teaches_the_ask(_night(0.0, samples=0)) is False


class TestColdStart:
    def test_below_the_threshold_the_configured_ask_stands(self):
        s = suggest_ask("ev:keba", [_night(7.0)] * (DEFAULT_MIN_NIGHTS - 1),
                        configured_kwh=10.0)
        assert s.suggested_kwh == pytest.approx(10.0)
        assert s.confident is False
        assert s.basis == "cold_start"

    def test_no_history_at_all_is_the_configured_ask(self):
        s = suggest_ask("ev:keba", [], configured_kwh=10.0)
        assert s.suggested_kwh == pytest.approx(10.0)
        assert s.confident is False

    def test_censored_nights_do_not_count_toward_the_threshold(self):
        """Five partial nights are five nights of no information. A learner
        that counted them would go 'confident' on a diet of its own
        constraints."""
        s = suggest_ask(
            "ev:keba",
            [_night(6.0, planned=6.0, status="partial")] * 8,
            configured_kwh=10.0)
        assert s.confident is False
        assert s.nights_used == 0


class TestTheSuggestion:
    def test_it_learns_the_upper_end_of_what_was_actually_taken(self):
        """Not the mean. Under-asking means the car does not reach target —
        a real harm — while over-asking costs a little scheduling slack. The
        asymmetry belongs in the statistic, not in a fudge factor."""
        s = suggest_ask("ev:keba",
                        [_night(v) for v in (5.0, 6.0, 6.5, 7.0, 8.0)],
                        configured_kwh=10.0)
        assert s.confident is True
        assert s.nights_used == 5
        assert s.suggested_kwh == pytest.approx(7.0)

    def test_it_never_suggests_less_than_a_night_actually_took(self):
        """One 9.5 kWh night proves the need reaches 9.5, whatever the quiet
        nights say. A suggestion below it would strand the car on the next
        night that looks like that one."""
        records = [_night(v) for v in (5.0, 5.5, 6.0, 6.5, 7.0)]
        records.append(_night(9.5, planned=9.5, status="partial"))
        s = suggest_ask("ev:keba", records, configured_kwh=10.0)
        assert s.suggested_kwh == pytest.approx(9.5)
        assert s.basis == "floor"
        assert s.censored_floor_kwh == pytest.approx(9.5)

    def test_a_ceiling_night_raises_rather_than_lowers(self):
        """Five quiet nights then one that ran the ask dry. The dry night is
        the informative one."""
        records = [_night(v) for v in (4.0, 4.5, 5.0, 5.5, 6.0)]
        records.append(_night(10.0))          # hit the 10 kWh ask exactly
        s = suggest_ask("ev:keba", records, configured_kwh=10.0)
        assert s.suggested_kwh == pytest.approx(10.0)

    def test_the_suggestion_carries_its_own_evidence(self):
        s = suggest_ask("ev:keba", [_night(v) for v in (5, 6, 6.5, 7, 8)],
                        configured_kwh=10.0)
        assert isinstance(s, AskSuggestion)
        assert s.demand_id == "ev:keba"
        assert s.configured_kwh == pytest.approx(10.0)
        assert s.delta_kwh == pytest.approx(-3.0)
        assert 0.0 < s.saving_ratio < 1.0

    def test_a_demand_that_needs_more_than_it_asks_says_so(self):
        """The interesting direction is not always down. Every night ran the
        ask dry: the ask is too small and the user should hear it."""
        s = suggest_ask("ev:keba", [_night(10.0) for _ in range(6)],
                        configured_kwh=10.0)
        assert s.suggested_kwh >= 10.0
        assert s.delta_kwh >= 0.0

    def test_a_configured_ask_of_zero_is_not_a_division(self):
        s = suggest_ask("load:x", [_night(2.0, asked=0.0)],
                        configured_kwh=0.0)
        assert s.saving_ratio is None


class TestItOnlySuggests:
    def test_nothing_in_the_plan_build_consumes_the_learner(self):
        """The user owns their target. A learner that quietly rewrote the ask
        would change what the hardware does on the strength of a model nobody
        agreed to — and it would do it invisibly, which is worse."""
        import inspect
        from custom_components.solar_energy_management.coordinator \
            .coordinator import SEMCoordinator

        src = inspect.getsource(SEMCoordinator._shadow_energy_plan)
        assert "suggest_ask" not in src, (
            "the plan must be built from the CONFIGURED ask; the learner "
            "surfaces a suggestion, it does not apply one")
