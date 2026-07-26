"""Multi-charger canonical-budget ratchet (#282 Phase D.2, trimmed by #651).

Original scope (v1.6.0–v1.6.2): the Phase B unification routed the
single-charger path through the canonical ``EVBudget``; Phase B.5 wired
the multi-charger distribution at ``coordinator.py:966`` to read
``_cycle_ev_budget.net_w``; Phase D.2 removed the legacy fallback so a
missing budget fails safe to 0 W instead of re-deriving via a divergent
formula.

#651 deleted that multi-charger distribution branch: the value it
computed flowed into ``SurplusController.distribute_ev_budget`` →
``pcc.budget_w`` → no reader. So three of the four tests here have no
subject any more, and they are worth a note on the way out:

they did not call production code. The file defined a local
``_select_multi_charger_total_budget`` that, in its own words, "inline[d]
the relevant lines verbatim" from the coordinator — a hand-copy of the
branch, asserted against itself. That construction cannot fail when the
branch is wrong, cannot fail when the branch is deleted, and passed
green through both. It is the #660 tautology class in its purest form:
a check whose outcome does not depend on the system under test.

What survives is the one assertion that was always about the real
object: Phase D.2's guarantee that the legacy divergent-formula method
stays deleted. ``_cycle_ev_budget`` itself is still live — computed in
``_build_charging_context`` and read for ``safe_discharge_power`` — it
is only the multi-charger distribution consumer that is gone.
"""
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator import SEMCoordinator


class TestLegacyBudgetMethodStaysDeleted:
    def test_legacy_method_attribute_does_not_exist_post_d2(self):
        """Defining property of Phase D.2: the legacy mixin method that
        the pre-D.2 fallback called is GONE. If a future refactor
        re-introduces it as a fallback (or anywhere on the coordinator),
        this test fails and forces a conscious decision."""
        with patch.object(SEMCoordinator, "__init__", return_value=None):
            coord = SEMCoordinator.__new__(SEMCoordinator)
        coord._ev_devices = {"ev_charger_0": MagicMock()}

        assert not hasattr(coord, "_calculate_solar_ev_budget"), (
            "`_calculate_solar_ev_budget` was removed in Phase D.2 (#282); "
            "re-introducing it resurrects the disagreement-formula bug "
            "class. Use the canonical EVBudget instead."
        )
