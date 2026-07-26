"""#665 — the per-charger allocator the scenario harness never drove.

Until #651 the harness *looked* like it covered multi-charger allocation:
it drove ``SurplusController.distribute_ev_budget``, whose output went to
``pcc.budget_w`` and was read by nothing. Retiring those assertions
removed a false positive and left the real gap visible — the allocator
that DOES run is the per-charger loop in ``_async_update_data``:

    self._solar_committed_w_per_cycle = 0.0          # reset, top of loop
    for charger in priority order:
        view = build_charger_view(..., solar_committed_w=<running total>)
        decision = decide(view)
        <running total> += solar_commitment_w(decision, ...)

#665 closes the gap in two halves, because one alone is not enough:

  * BEHAVIOUR — the harness now runs that loop for real
    (``scenario_harness._run`` → ``per_charger_decisions``), accumulating
    through the same ``solar_commitment_w`` production calls. A wrong
    formula, or crediting an intent that shouldn't count, breaks both
    sides at once.
  * SOURCE — a harness that runs its own copy of the loop cannot notice
    the coordinator dropping the reset or the call entirely. That is what
    the AST guards below are for, and it is the acceptance criterion on
    the issue: break the accumulation block, a test goes red.

Also pins #678, found by the first half the moment it ran: the scenario
charger configured at 16 A came back commanded at 22 A, because
``decide()`` reads ``ev_max_current`` off a per-charger config dict that
nothing ever writes it into.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
    solar_commitment_w,
)

_COORD = (
    Path(__file__).resolve().parent.parent / "coordinator" / "coordinator.py"
)


def _decision(intent, *, amps=0, budget_w=0.0):
    return ChargerDecision(
        charger_id="wb", mode="solar_only", intent=intent,
        commanded_amps=amps, budget_w=budget_w, reason="test",
    )


@pytest.mark.unit
class TestSolarCommitment:
    """The arithmetic itself — one function, two callers, no drift."""

    def test_charge_at_amps_credits_the_amps(self):
        d = _decision(ChargerIntent.CHARGE_AT_AMPS, amps=16, budget_w=99_000)
        assert solar_commitment_w(
            d, phases=3, voltage=230, max_current_a=16,
        ) == pytest.approx(11040.0)

    def test_budget_caps_the_credit(self):
        # A floor (deadline / Min) can raise commanded_amps above what
        # solar funds; the extra is grid or battery watts, not solar.
        # Crediting them would shrink the surplus the NEXT charger sees
        # by watts the sun never produced.
        d = _decision(ChargerIntent.CHARGE_AT_AMPS, amps=16, budget_w=4000.0)
        assert solar_commitment_w(
            d, phases=3, voltage=230, max_current_a=16,
        ) == pytest.approx(4000.0)

    def test_charge_max_credits_nameplate(self):
        # commanded_amps is not meaningful for CHARGE_MAX — the adapter
        # resolves the actual current — so the ceiling is the credit.
        d = _decision(ChargerIntent.CHARGE_MAX, amps=0, budget_w=0.0)
        assert solar_commitment_w(
            d, phases=3, voltage=230, max_current_a=16,
        ) == pytest.approx(11040.0)

    @pytest.mark.parametrize("intent", [
        ChargerIntent.IDLE, ChargerIntent.DISABLE,
    ])
    def test_non_charging_intents_claim_nothing(self, intent):
        # An off-mode or idling charger must not shrink the surplus its
        # lower-priority siblings can see. The other side of this is
        # test_351_umbrella_regression.py::TestM5.
        d = _decision(intent, amps=0, budget_w=8000.0)
        assert solar_commitment_w(
            d, phases=3, voltage=230, max_current_a=16,
        ) == 0.0

    def test_never_negative(self):
        d = _decision(ChargerIntent.CHARGE_AT_AMPS, amps=16, budget_w=-500.0)
        assert solar_commitment_w(
            d, phases=3, voltage=230, max_current_a=16,
        ) == 0.0


# ---------------------------------------------------------------------------
# Source guards — the half the harness structurally cannot cover
# ---------------------------------------------------------------------------

def _coordinator_tree() -> ast.AST:
    return ast.parse(_COORD.read_text(encoding="utf-8"))


@pytest.mark.unit
class TestCoordinatorStillRunsTheLoop:
    """Deleting the accumulation block must go red. That is the #665
    acceptance criterion, and no behavioural test can carry it: the
    harness drives its own copy of the loop, so it would stay green
    while production stopped accumulating entirely."""

    def test_the_running_total_is_reset_each_cycle(self):
        # Without the reset, commitments accumulate across cycles and
        # every charger after the first cycle sees a surplus that has
        # already been spent — the fleet quietly stops charging.
        resets = [
            node for node in ast.walk(_coordinator_tree())
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Attribute)
                and t.attr == "_solar_committed_w_per_cycle"
                for t in node.targets
            )
        ]
        assert resets, (
            "coordinator.py no longer assigns _solar_committed_w_per_cycle. "
            "The per-cycle reset is gone: commitments now carry over "
            "between cycles and lower-priority chargers see a surplus "
            "that was spent minutes ago."
        )

    def test_the_total_is_accumulated_through_the_shared_helper(self):
        # An inline formula here would be invisible to the harness, which
        # is exactly the state #665 found. Keep it a call.
        augs = [
            node for node in ast.walk(_coordinator_tree())
            if isinstance(node, ast.AugAssign)
            and isinstance(node.target, ast.Attribute)
            and node.target.attr == "_solar_committed_w_per_cycle"
        ]
        assert augs, (
            "coordinator.py no longer accumulates "
            "_solar_committed_w_per_cycle. The priority cascade is dead: "
            "every charger now sees the full surplus and the fleet "
            "over-commits it N times over."
        )
        assert any(
            any(
                isinstance(sub, ast.Call)
                and getattr(sub.func, "id", getattr(sub.func, "attr", None))
                == "solar_commitment_w"
                for sub in ast.walk(node.value)
            )
            for node in augs
        ), (
            "_solar_committed_w_per_cycle is accumulated, but not through "
            "charger_types.solar_commitment_w. Re-inlining the formula "
            "puts production and tests/scenario_harness.py back on "
            "separate copies of the arithmetic — the drift #665 closed."
        )

    def test_the_running_total_is_threaded_into_each_view(self):
        # Accumulating a number nobody reads is the same as not
        # accumulating it.
        threaded = [
            node for node in ast.walk(_coordinator_tree())
            if isinstance(node, ast.Call)
            and getattr(node.func, "id", getattr(node.func, "attr", None))
            == "build_charger_view"
            and any(
                kw.arg == "solar_committed_w"
                and isinstance(kw.value, ast.Attribute)
                and kw.value.attr == "_solar_committed_w_per_cycle"
                for kw in node.keywords
            )
        ]
        assert threaded, (
            "No build_charger_view call passes "
            "solar_committed_w=self._solar_committed_w_per_cycle. The "
            "cascade is accumulated but never consumed — each charger "
            "sees the full surplus again."
        )


# ---------------------------------------------------------------------------
# #678 — the ceiling the view never carried
# ---------------------------------------------------------------------------

@pytest.mark.unit
class TestHardwareMaxReachesDecide:
    """A per-charger dict that lacks ``ev_max_current`` — i.e. every one
    verified on a live install — must still decide against the real
    ceiling, not decide's 32 A literal."""

    def _view(self, charger_cfg, fleet_cfg=None, hardware_max_a=None):
        from custom_components.solar_energy_management.coordinator.build_view import (
            build_charger_view,
        )
        from custom_components.solar_energy_management.coordinator.charger_types import (
            FleetCycleState,
        )
        from unittest.mock import MagicMock

        power = MagicMock()
        power.solar_power = 20000.0
        power.home_consumption_power = 500.0
        power.battery_soc = 50.0
        power.ev_power_per_charger = {}
        power.ev_connected_per_charger = {}
        power.ev_charging_per_charger = {}
        fleet_state = FleetCycleState(
            power=power,
            config=dict(fleet_cfg or {}),
            is_night=False,
            tariff_level=None,
            forecast_remaining_kwh=0.0,
        )
        return build_charger_view(
            fleet_state, charger_id="wb", charger_cfg=charger_cfg,
            mode="solar_only", daily_ev_kwh=0.0,
            hardware_max_a=hardware_max_a,
        )

    def test_absent_key_falls_back_to_the_adapter_ceiling(self):
        # THE live shape. HA-TEST's entry carries no ev_max_current at
        # either level; before #678 this view decided against 32 A.
        view = self._view({"id": "wb"}, hardware_max_a=16.0)
        assert view.config["ev_max_current"] == 16

    def test_fleet_config_fills_the_gap_when_there_is_no_adapter(self):
        # Observer mode / early boot: no device yet, so no hardware max.
        # The fleet value is still better than decide's literal.
        view = self._view({"id": "wb"}, fleet_cfg={"ev_max_current": 20})
        assert view.config["ev_max_current"] == 20

    def test_per_charger_value_wins_over_fleet(self):
        view = self._view(
            {"id": "wb", "ev_max_current": 10}, fleet_cfg={"ev_max_current": 20},
        )
        assert view.config["ev_max_current"] == 10

    def test_config_may_ask_for_less_than_the_hardware_allows(self):
        # A user throttling a shared supply. Config below hardware wins.
        view = self._view({"id": "wb", "ev_max_current": 10}, hardware_max_a=16.0)
        assert view.config["ev_max_current"] == 10

    def test_config_may_not_ask_for_more_than_the_hardware_allows(self):
        # Deciding above the clamp is the drift that over-credits the
        # cascade: the charger is commanded 32, draws 16, and the missing
        # 16 A of "committed solar" is taken off the next charger.
        view = self._view({"id": "wb", "ev_max_current": 32}, hardware_max_a=16.0)
        assert view.config["ev_max_current"] == 16

    def test_no_information_at_all_leaves_the_key_absent(self):
        # Nothing to say → say nothing, and decide's own default applies.
        # Inventing a ceiling here would be worse than the bug.
        view = self._view({"id": "wb"})
        assert "ev_max_current" not in view.config

    def test_the_other_three_hardware_keys_fill_too(self):
        view = self._view(
            {"id": "wb"},
            fleet_cfg={"ev_min_current": 8, "ev_phases": 1, "ev_voltage": 240},
        )
        assert view.config["ev_min_current"] == 8
        assert view.config["ev_phases"] == 1
        assert view.config["ev_voltage"] == 240
