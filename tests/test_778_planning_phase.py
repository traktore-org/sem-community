"""#778 phase 6 — the state a card renders, published rather than inferred.

The six #778 sensors publish honest ``None``/``0.0`` while evidence is thin.
On a dashboard those are indistinguishable from a dead integration: HA renders
both as "Unavailable", and a bare 0.0 reads as "nothing to spend" rather than
"not enough evidence yet". Every fresh install sits in that state for its first
five nights, so it is the state that decides whether the feature looks alive.

The discriminator is PUBLISHED, never inferred from the reason string: those
strings are prose, they are translated into sixteen languages, and a card that
switched on their contents would break the moment one was reworded.
"""

import pytest

from custom_components.solar_energy_management.coordinator.planning_phase import (
    PHASE_HOLDING,
    PHASE_LEARNING,
    PHASE_SPENDING,
    planning_phase,
)


class TestLearning:
    """Evidence is not in yet — the answer is unknown, not zero."""

    def test_fewer_nights_than_required_is_learning(self):
        assert planning_phase(
            nights_sealed=2, nights_required=5, overnight_need_kwh=3.0,
            usable_capacity_kwh=15.0, spendable_kwh=0.0,
        ) == PHASE_LEARNING

    def test_the_rig_today_is_learning(self):
        """.175 right now: 2 sealed nights, no need envelope, budget 0.0.

        This is the exact state read back from the running instance, and the
        one the card currently renders as a bare zero.
        """
        assert planning_phase(
            nights_sealed=2, nights_required=5, overnight_need_kwh=None,
            usable_capacity_kwh=15.0, spendable_kwh=0.0,
        ) == PHASE_LEARNING

    def test_enough_nights_but_no_need_envelope_is_still_learning(self):
        """Nights can be sealed yet not qualify (short SOC span, untrainable).
        The count alone must not promote the phase."""
        assert planning_phase(
            nights_sealed=9, nights_required=5, overnight_need_kwh=None,
            usable_capacity_kwh=15.0, spendable_kwh=0.0,
        ) == PHASE_LEARNING

    def test_unknown_capacity_is_learning(self):
        assert planning_phase(
            nights_sealed=9, nights_required=5, overnight_need_kwh=3.0,
            usable_capacity_kwh=None, spendable_kwh=0.0,
        ) == PHASE_LEARNING


class TestHolding:
    """The question can be answered and the answer is genuinely nothing."""

    def test_a_real_zero_is_holding_not_learning(self):
        """The winter case: full evidence, weak forecast, nothing spare.
        A user must be able to tell this from 'still measuring'."""
        assert planning_phase(
            nights_sealed=30, nights_required=5, overnight_need_kwh=14.0,
            usable_capacity_kwh=15.0, spendable_kwh=0.0,
        ) == PHASE_HOLDING

    def test_exactly_at_the_night_threshold_counts(self):
        assert planning_phase(
            nights_sealed=5, nights_required=5, overnight_need_kwh=14.0,
            usable_capacity_kwh=15.0, spendable_kwh=0.0,
        ) == PHASE_HOLDING


class TestSpending:
    def test_a_positive_budget_is_spending(self):
        assert planning_phase(
            nights_sealed=30, nights_required=5, overnight_need_kwh=3.0,
            usable_capacity_kwh=15.0, spendable_kwh=5.96,
        ) == PHASE_SPENDING

    def test_a_budget_without_evidence_never_reports_spending(self):
        """Belt and braces: if a budget ever appeared while the evidence was
        thin, that is a bug upstream — the phase must not paper over it by
        rendering a confident 'Spending' card."""
        assert planning_phase(
            nights_sealed=1, nights_required=5, overnight_need_kwh=3.0,
            usable_capacity_kwh=15.0, spendable_kwh=5.96,
        ) == PHASE_LEARNING


class TestJunkInputs:
    """A phase is rendered on every cycle; it may never raise."""

    @pytest.mark.parametrize("bad", [None, "x", float("nan")])
    def test_junk_spendable_degrades_to_learning(self, bad):
        assert planning_phase(
            nights_sealed=30, nights_required=5, overnight_need_kwh=3.0,
            usable_capacity_kwh=15.0, spendable_kwh=bad,
        ) in (PHASE_LEARNING, PHASE_HOLDING)

    def test_junk_night_count_degrades_to_learning(self):
        assert planning_phase(
            nights_sealed=None, nights_required=5, overnight_need_kwh=3.0,
            usable_capacity_kwh=15.0, spendable_kwh=1.0,
        ) == PHASE_LEARNING
