"""(#925 audit) A budget that has not been measured yet must not publish
a confident 0.0.

`SpendableBudget.spendable_kwh` is documented as "0.0 whenever anything is
unknown" — correct for the DECISION (spend nothing while you do not know)
and wrong for the DISPLAY, which is the #903 shape: a fallback rendered as
a reading. Its own sibling `floor_pct` returns None, and
`measured_capacity()` returns None deliberately "so a caller can tell
measured from assumed".

Only the battery card read the `phase` attribute and rendered "Learning,
n of 5 nights". Everything else — History, the Logbook, a generic entity
card, an automation, a voice query — saw `0.0 kWh` for a week on every new
battery install.
"""

from __future__ import annotations

from custom_components.solar_energy_management.coordinator.planning_phase import (
    planning_phase,
)


def _published(evidence: dict):
    """The publish rule, applied exactly as coordinator.py applies it."""
    spend = evidence.get("battery_spendable_kwh")
    return None if evidence.get("planning_phase") == "learning" else spend


class TestTheThreeStatesStayThree:

    def test_learning_publishes_unknown_not_zero(self):
        assert _published({"planning_phase": "learning",
                           "battery_spendable_kwh": 0.0}) is None

    def test_holding_publishes_a_real_zero(self):
        """`holding` means SEM measured, and the answer is nothing to spend.
        That IS a reading and must render as one."""
        assert _published({"planning_phase": "holding",
                           "battery_spendable_kwh": 0.0}) == 0.0

    def test_spending_publishes_the_number(self):
        assert _published({"planning_phase": "spending",
                           "battery_spendable_kwh": 4.2}) == 4.2

    def test_the_phase_really_does_separate_them(self):
        """The gate is only honest if `learning` and `holding` are actually
        distinguishable — otherwise this hides a real zero."""
        learning = planning_phase(nights_sealed=2, nights_required=5,
                                  overnight_need_kwh=3.0,
                                  usable_capacity_kwh=12.0, spendable_kwh=0.0)
        holding = planning_phase(nights_sealed=5, nights_required=5,
                                 overnight_need_kwh=3.0,
                                 usable_capacity_kwh=12.0, spendable_kwh=0.0)
        assert learning == "learning" and holding == "holding"

    def test_a_missing_phase_is_not_treated_as_learning(self):
        """Absent evidence entirely — publish whatever is there rather than
        inventing a learning state the classifier never claimed."""
        assert _published({"battery_spendable_kwh": 1.5}) == 1.5


class TestTheDecisionPathIsUntouched:

    def test_the_coordinator_gates_the_publish_not_the_evidence(self):
        """Decisions read `_planning_evidence`, which still carries the
        number — spending nothing while unknown stays correct. Only the
        published sensor changes."""
        from .ast_contracts import call_sites  # noqa: F401  (import guard)
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        assert 'result["battery_spendable_kwh"] = (' in src, (
            "the publish site no longer gates on the phase")
        assert '"battery_spendable_kwh": budget.spendable_kwh' in src, (
            "the evidence dict should still carry the raw number for the "
            "decision paths — gating THAT would change behaviour")
