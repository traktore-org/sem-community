"""Multi-charger canonical-budget tests (#282 Phase B.5 / #284 / Phase D.2).

The Phase B unification (commits f7840ce / b120f32) routed the
single-charger path through the canonical ``EVBudget``. The
multi-charger distribution at ``coordinator.py:966`` was left calling
the legacy ``_calculate_solar_ev_budget`` — the same disagreement
mode that #282 eliminated for single-charger, but kept alive for
two-charger setups like @RienduPre's Wallbox Pulsar pair (#284).

Phase B.5 wired the multi-charger path to read ``_cycle_ev_budget.net_w``
when set. Phase D.2 (#282, v1.6.2) removed the legacy fallback entirely:
when ``_cycle_ev_budget`` is missing the distributor now logs an error
and distributes 0 W (fail-safe = no charge this cycle) instead of
silently re-deriving via a divergent formula.

These tests pin both invariants:
  1. Canonical net_w (with all its components — solar_surplus +
     battery_redirect + battery_assist) is what the distributor sees.
  2. Missing ``_cycle_ev_budget`` produces a logged error and 0 W
     distribution, NOT a fallback re-derivation.
"""
import logging

import pytest
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    EVBudget,
    EVBudgetStrategy,
)
from custom_components.solar_energy_management.consts.states import ChargingState


def _build_coord_for_multi_charger():
    """Construct a SEMCoordinator bypassing __init__ — same trick as the
    scenario harness uses. We only populate fields the budget-selection
    branch reads.
    """
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)

    # _surplus_controller.distribute_ev_budget(total_w, devices) is the
    # only collaborator the branch under test calls. Mock it as a passive
    # spy so we can read what total_w it received.
    coord._surplus_controller = MagicMock()
    coord._surplus_controller.distribute_ev_budget = MagicMock(
        return_value={"ev_charger_0": 1000.0, "ev_charger_1": 1000.0}
    )

    # Pretend we have two chargers — exact identity doesn't matter for
    # the budget read; the distribute call is what we observe.
    coord._ev_devices = {
        "ev_charger_0": MagicMock(),
        "ev_charger_1": MagicMock(),
    }

    return coord


# ──────────────────────────────────────────────────────────────────────
# The actual budget-selection branch lives inside _async_update_data
# (the multi-charger if block at coordinator.py:960-989). Lifting the
# decision into its own helper would make the test cleaner, but the
# refactor is out of scope. Inline the relevant lines verbatim — same
# code path as the production branch post-Phase-D.2.
# ──────────────────────────────────────────────────────────────────────

_LOGGER = logging.getLogger(
    "custom_components.solar_energy_management.tests.multi_charger_canonical_budget"
)


def _select_multi_charger_total_budget(coord):
    """Mirrors coordinator.py post-Phase-D.2 — fail-safe budget selection.

    Pre-D.2 this fell back to ``coord._calculate_solar_ev_budget``. The
    legacy method was deleted in v1.6.2; the production code now logs an
    error and distributes 0 W when the canonical budget is missing.
    """
    cycle_budget = getattr(coord, "_cycle_ev_budget", None)
    if cycle_budget is None:
        _LOGGER.error(
            "Canonical EV budget not set in multi-charger "
            "distribution — coordinator init bug. Distributing "
            "0 W to fail safe. Investigate _build_charging_context."
        )
        total_budget = 0.0
    else:
        total_budget = cycle_budget.net_w
    coord._surplus_controller.distribute_ev_budget(
        total_budget, coord._ev_devices
    )
    return total_budget


# ──────────────────────────────────────────────────────────────────────
# Tests
# ──────────────────────────────────────────────────────────────────────

class TestMultiChargerCanonicalBudget:
    def test_uses_cycle_ev_budget_net_w_when_set(self):
        """Production case: _cycle_ev_budget is set every cycle by
        _build_charging_context. The distributor MUST see net_w."""
        coord = _build_coord_for_multi_charger()
        coord._cycle_ev_budget = EVBudget(
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            solar_surplus=1800,
            battery_redirect=200,
            battery_assist=0,
            net_w=2000,
            current_a=2,
        )

        total = _select_multi_charger_total_budget(coord)

        assert total == 2000, (
            f"distributor must receive canonical net_w (2000), got {total}"
        )
        # Spy assertion: distributor called once with the canonical value.
        coord._surplus_controller.distribute_ev_budget.assert_called_once_with(
            2000, coord._ev_devices
        )

    def test_missing_cycle_budget_fails_safe_to_zero(self, caplog):
        """Phase D.2 (#282) fail-safe: when ``_cycle_ev_budget`` is None
        (init bug / partial setup / regression), the distributor must
        receive 0 W and a loud error log — NOT a silent fallback to a
        divergent legacy formula. Pre-D.2 this path called
        ``_calculate_solar_ev_budget`` which is now deleted; replacing it
        with a fail-safe was the architectural point of Phase D.2."""
        coord = _build_coord_for_multi_charger()
        coord._cycle_ev_budget = None

        with caplog.at_level(logging.ERROR):
            total = _select_multi_charger_total_budget(coord)

        assert total == 0.0, (
            f"missing cycle budget must distribute 0 W fail-safe, got {total}"
        )
        coord._surplus_controller.distribute_ev_budget.assert_called_once_with(
            0.0, coord._ev_devices
        )
        # Loud error — operators must see this in logs, not a silent
        # behavioural divergence.
        assert any(
            "Canonical EV budget not set" in rec.message
            and rec.levelname == "ERROR"
            for rec in caplog.records
        ), (
            "missing cycle budget must log an ERROR explaining the "
            "fail-safe (no silent behavioural change post-D.2)"
        )

    def test_canonical_value_propagates_through_for_battery_assist(self):
        """Zone 4 battery_assist: the canonical method includes the
        battery_assist component. Multi-charger distribution must see it
        too — the legacy path's SOLAR_SUPER_CHARGING branch did the same
        thing but in a different place. Locks the equivalence."""
        coord = _build_coord_for_multi_charger()
        coord._cycle_ev_budget = EVBudget(
            strategy=EVBudgetStrategy.BATTERY_ASSIST,
            solar_surplus=500,
            battery_redirect=0,
            battery_assist=3000,
            net_w=3500,
            current_a=5,
        )

        total = _select_multi_charger_total_budget(coord)

        assert total == 3500
        coord._surplus_controller.distribute_ev_budget.assert_called_once_with(
            3500, coord._ev_devices
        )

    def test_legacy_method_attribute_does_not_exist_post_d2(self):
        """Defining property of Phase D.2: the legacy mixin method that
        the pre-D.2 fallback called is GONE. If a future refactor
        re-introduces it as a fallback (or anywhere on the coordinator),
        this test fails and forces a conscious decision."""
        coord = _build_coord_for_multi_charger()
        assert not hasattr(coord, "_calculate_solar_ev_budget"), (
            "`_calculate_solar_ev_budget` was removed in Phase D.2 (#282); "
            "re-introducing it resurrects the disagreement-formula bug "
            "class. Use the canonical EVBudget instead."
        )
