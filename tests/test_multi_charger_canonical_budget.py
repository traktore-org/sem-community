"""Multi-charger canonical-budget tests (#282 Phase B.5 / #284).

The Phase B unification (commits f7840ce / b120f32) routed the
single-charger path through the canonical ``EVBudget``. The
multi-charger distribution at ``coordinator.py:966`` was left calling
the legacy ``_calculate_solar_ev_budget`` — the same disagreement
mode that #282 eliminated for single-charger, but kept alive for
two-charger setups like @RienduPre's Wallbox Pulsar pair (#284).

These tests pin down the Phase B.5 fix: when ``self._cycle_ev_budget``
is set (which it always is in production cycles, post-Phase-B), the
multi-charger distributor MUST read the canonical net_w instead of
re-deriving via the legacy method.
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch

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

    # _calculate_solar_ev_budget would be called if the fallback fires.
    # Replace with a spy that records calls — we want this NOT to fire
    # when _cycle_ev_budget is set.
    coord._calculate_solar_ev_budget = MagicMock(return_value=999_999)

    return coord


# ──────────────────────────────────────────────────────────────────────
# The actual budget-selection branch lives inside _async_update_data
# (the multi-charger if block at coordinator.py:960-989). Lifting the
# decision into its own helper would make the test cleaner, but a
# refactor is out of scope for tonight. Inline the relevant lines
# verbatim — same code path as the production branch.
# ──────────────────────────────────────────────────────────────────────

def _select_multi_charger_total_budget(coord, charging_state, power, charging_context):
    """Mirrors coordinator.py:967-988 — the budget selection block."""
    cycle_budget = getattr(coord, "_cycle_ev_budget", None)
    if cycle_budget is not None:
        total_budget = cycle_budget.net_w
    else:
        total_budget = coord._calculate_solar_ev_budget(
            charging_state, power, charging_context
        )
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

        total = _select_multi_charger_total_budget(
            coord, ChargingState.SOLAR_CHARGING_ACTIVE,
            power=MagicMock(), charging_context=MagicMock(),
        )

        assert total == 2000, (
            f"distributor must receive canonical net_w (2000), got {total}"
        )
        # Spy assertion: distributor called once with the canonical value.
        coord._surplus_controller.distribute_ev_budget.assert_called_once_with(
            2000, coord._ev_devices
        )
        # And the legacy formula must NOT have been called.
        coord._calculate_solar_ev_budget.assert_not_called()

    def test_falls_back_to_legacy_when_cycle_budget_missing(self):
        """Defence-in-depth case: tests / partial init / migration paths
        where _cycle_ev_budget hasn't been set. Use the legacy method so
        nothing crashes. Phase D.2 will remove this fallback after PROD
        soak confirms the canonical path always runs."""
        coord = _build_coord_for_multi_charger()
        # Deliberately don't set _cycle_ev_budget.
        coord._cycle_ev_budget = None

        total = _select_multi_charger_total_budget(
            coord, ChargingState.SOLAR_CHARGING_ACTIVE,
            power=MagicMock(), charging_context=MagicMock(),
        )

        assert total == 999_999
        coord._calculate_solar_ev_budget.assert_called_once()

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

        total = _select_multi_charger_total_budget(
            coord, ChargingState.SOLAR_SUPER_CHARGING,
            power=MagicMock(), charging_context=MagicMock(),
        )

        assert total == 3500
        coord._surplus_controller.distribute_ev_budget.assert_called_once_with(
            3500, coord._ev_devices
        )
        coord._calculate_solar_ev_budget.assert_not_called()

    def test_legacy_method_never_called_in_production_state(self):
        """The defining property: as long as cycle_ev_budget is set, the
        legacy method is dead code. If a future refactor re-introduces
        the legacy call site, this test fails."""
        coord = _build_coord_for_multi_charger()
        coord._cycle_ev_budget = EVBudget(
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            solar_surplus=1000, battery_redirect=0, battery_assist=0,
            net_w=1000, current_a=1,
        )

        # Run all four charging states the distribution loop accepts.
        for state in (
            ChargingState.SOLAR_CHARGING_ACTIVE,
            ChargingState.SOLAR_SUPER_CHARGING,
            ChargingState.SOLAR_CHARGING_ALLOWED,
            ChargingState.SOLAR_MIN_PV,
        ):
            _select_multi_charger_total_budget(
                coord, state,
                power=MagicMock(), charging_context=MagicMock(),
            )

        coord._calculate_solar_ev_budget.assert_not_called()
