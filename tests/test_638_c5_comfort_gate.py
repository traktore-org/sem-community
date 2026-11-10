"""#638 one-gate C5 — comfort joins the gate; the ID mismatch dies.

Comfort demands pack as ``comfort:{did}`` (coordinator collector), but the
window collector only ever asked the gate for ``load:{did}`` — so a comfort
block could not reach its device: banking runs never actuated. The merge:

* ``PlanVerdict`` carries ``in_block`` — the run half of the verdict.
* ``_energy_plan_load_windows`` asks BOTH gates per device and merges:
  either demand in-block → a run verdict; a hold only when EVERY covered
  demand holds (an uncovered/no-authority demand keeps its reactive layer);
  the earliest ``next_block_start`` wins the ``until``.
* ``compute_load_intent`` gains the ONE sanctioned place the plan CREATES
  a run: a ``willing`` comfort band inside its block runs from
  "cheap_grid" — banking has no reactive run reason at all (a willing
  room otherwise only rides free surplus). Forced rooms stay reactive.
* the dead ``load_window`` helper and the legacy ``plan_window`` bool
  param are deleted — the verdict is the only plan input left.
"""

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    PlanGate,
    load_verdict,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    NO_OPINION,
    PlanVerdict,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
)

NOW = datetime(2026, 8, 11, 13, 30)


@pytest.mark.unit
class TestTheVerdictCarriesTheRunHalf:
    def test_in_block_defaults_false_and_no_opinion_is_unchanged(self):
        assert PlanVerdict().in_block is False
        assert NO_OPINION.in_block is False

    def test_load_verdict_marks_the_open_block(self):
        g = PlanGate(covered=True, in_block=True, block_power_w=1000.0)
        v = load_verdict(g, deficit_kwh=1.0)
        assert v.in_block is True and v.hold is False


def _win_dev(did="heizband"):
    return SimpleNamespace(
        device_id=did, daily_min_runtime_sec=3600,
        _daily_runtime_accumulated_sec=0, rated_power=1000.0,
    )


def _win_self(gates):
    """A fake whose _energy_plan_gate answers from a dict."""
    from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
        UNCOVERED,
    )
    fake = SimpleNamespace(
        _energy_plan_actuation=True,
        _energy_plan_shadow={"computed_at": "x"},
        _energy_plan_gate=lambda demand_id, now=None: gates.get(
            demand_id, UNCOVERED),
    )
    return fake


def _windows(fake, devices):
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    return SEMCoordinator._energy_plan_load_windows(fake, devices)


@pytest.mark.unit
class TestTheCollectorMergesBothDemands:
    def test_a_comfort_only_block_reaches_the_device(self):
        """The ID-mismatch bug: a device with ONLY a comfort demand must
        get a verdict when its comfort block opens."""
        gates = {"comfort:heizband": PlanGate(
            covered=True, in_block=True, block_power_w=1000.0)}
        w = _windows(_win_self(gates), [_win_dev()])
        assert "heizband" in w
        assert w["heizband"].in_block is True
        assert w["heizband"].comfort_in_block is True

    def test_either_block_open_is_a_run_verdict(self):
        gates = {
            "load:heizband": PlanGate(covered=True, in_block=False,
                                      remaining_kwh=5.0, remaining_h=5.0),
            "comfort:heizband": PlanGate(covered=True, in_block=True,
                                         block_power_w=1000.0),
        }
        w = _windows(_win_self(gates), [_win_dev()])
        assert w["heizband"].in_block is True
        assert w["heizband"].comfort_in_block is True
        assert w["heizband"].hold is False

    def test_the_runtime_block_is_not_the_comfort_block(self):
        """(#1102) Only the comfort block may start a banking run: the
        runtime block lifts the hold and says which block it is."""
        gates = {
            "load:heizband": PlanGate(covered=True, in_block=True,
                                      block_power_w=1000.0),
            "comfort:heizband": PlanGate(covered=True, in_block=False,
                                         remaining_kwh=1.0, remaining_h=1.0),
        }
        w = _windows(_win_self(gates), [_win_dev()])
        assert w["heizband"].in_block is True
        assert w["heizband"].hold is False
        assert w["heizband"].comfort_in_block is False

    def test_a_hold_needs_every_covered_demand_to_hold(self):
        """The load's verdict fails open (deficit undeliverable) — comfort
        alone must not hold the device's reactive deficit run."""
        gates = {
            "load:heizband": PlanGate(covered=True, in_block=False,
                                      remaining_kwh=0.1, remaining_h=0.1),  # < 1 h deficit
            "comfort:heizband": PlanGate(covered=True, in_block=False,
                                         next_block_start=NOW),
        }
        w = _windows(_win_self(gates), [_win_dev()])
        assert "heizband" not in w

    def test_both_holding_holds_with_the_earliest_until(self):
        early = datetime(2026, 8, 11, 14, 0)
        late = datetime(2026, 8, 11, 16, 0)
        gates = {
            "load:heizband": PlanGate(covered=True, in_block=False,
                                      remaining_kwh=5.0, remaining_h=5.0,
                                      next_block_start=late),
            "comfort:heizband": PlanGate(covered=True, in_block=False,
                                         next_block_start=early),
        }
        w = _windows(_win_self(gates), [_win_dev()])
        assert w["heizband"].hold is True
        assert w["heizband"].until == early

    def test_uncovered_everything_stays_absent(self):
        w = _windows(_win_self({}), [_win_dev()])
        assert w == {}


def _comfort_dev(*, willing=True, active=False):
    dev = MagicMock()
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.is_active = active
    dev.get_current_consumption = MagicMock(return_value=0.0)
    dev.rated_power = 1000.0
    dev.min_power_threshold = 1000.0
    dev.has_runtime_deficit = False
    dev.daily_max_runtime_reached = False
    dev.stop_condition_met = False
    dev.is_deadline_approaching = False
    dev.daily_targets_met = False
    dev.battery_eligible_overnight = False
    dev.top_up_policy = "solar_only"
    dev.comfort_state = "willing" if willing else "forced"
    # (#1102) the ladder reads the band itself: a willing tank below Keep at,
    # a forced one past its limit
    dev._comfort_reading = MagicMock(return_value=45.0 if willing else 34.0)
    dev._comfort_thresholds_c = MagicMock(return_value=(50.0, 5.0, 36.0))
    dev._comfort_direction = MagicMock(return_value="heat")
    return dev


@pytest.mark.unit
class TestComfortBankingRunsInItsBlock:
    def test_willing_plus_in_block_runs_from_cheap_grid(self):
        v = PlanVerdict(in_block=True, comfort_in_block=True,
                        reason="comfort block open")
        intent = compute_load_intent(
            _comfort_dev(), remaining_surplus_w=0.0, is_night=False, plan=v)
        assert intent.on is True
        assert intent.source == "cheap_grid"

    def test_willing_outside_the_block_does_not_run(self):
        intent = compute_load_intent(
            _comfort_dev(), remaining_surplus_w=0.0, is_night=False,
            plan=NO_OPINION)
        assert intent.on is False

    def test_willing_in_the_runtime_block_does_not_bank(self):
        """(#1102) The runtime block is not a banking block."""
        v = PlanVerdict(in_block=True, reason="runtime block open")
        intent = compute_load_intent(
            _comfort_dev(), remaining_surplus_w=0.0, is_night=False, plan=v)
        assert intent.on is False

    def test_a_forced_room_is_the_floor_rung_not_the_banking_clause(self):
        """(#1102) Forced = too cold. It used to wait for the user's paid
        deficit sources (and on a solar-only boiler never ran). The heater
        ladder's floor rung now runs it at once — not as plan banking."""
        from custom_components.solar_energy_management.coordinator import reason_codes as RC
        v = PlanVerdict(in_block=True, comfort_in_block=True,
                        reason="comfort block open")
        dev = _comfort_dev(willing=False)
        intent = compute_load_intent(
            dev, remaining_surplus_w=0.0, is_night=False, plan=v)
        assert intent.on is True and intent.code == RC.LOAD_COMFORT_FLOOR

    def test_peak_freeze_still_blocks_the_banking_start(self):
        v = PlanVerdict(in_block=True, comfort_in_block=True,
                        reason="comfort block open")
        intent = compute_load_intent(
            _comfort_dev(), remaining_surplus_w=0.0, is_night=False,
            peak_freeze=True, plan=v)
        assert intent.on is False


@pytest.mark.unit
class TestTheLegacySurfacesAreGone:
    def test_load_window_is_deleted(self):
        import custom_components.solar_energy_management.coordinator.energy_plan_actuation as oa
        assert not hasattr(oa, "load_window")

    def test_plan_window_param_is_deleted(self):
        import inspect
        assert "plan_window" not in inspect.signature(
            compute_load_intent).parameters

    def test_the_one_engine_has_the_comfort_clause(self):
        """(#1335) Every install runs the three layers: the banking run
        lives in layer 1, the one place a run reason docks."""
        from custom_components.solar_energy_management.coordinator.surplus_controller import (
            compute_load_intent,
        )
        from custom_components.solar_energy_management.tests.ast_contracts import (
            reads_attribute,
        )
        assert reads_attribute(compute_load_intent, "plan", "comfort_in_block")
        assert reads_attribute(compute_load_intent, "RC", "LOAD_COMFORT_GOAL")
