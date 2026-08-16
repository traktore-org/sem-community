"""#638 — the uncovered path must NAME its reason, once per transition.

The audit (2026-08-11) found the fail-open fallback invisible: when the gate
declines, ev_control's own cheap-window selector silently drives the
hardware, and no artifact records that the night was legacy-driven. Before
the one-gate unification can retire that selector, every night must say
which layer decided.

Two pure surfaces:

* ``plan_gate`` returns a gate whose ``reason`` names the doubt — "no
  plan", "stale stamp", "outside span", "not in plan", "verdict yields",
  "malformed block". A covered gate carries no doubt (``reason == ""``).
* ``coverage_transition`` — the once-per-change log guard. First sight
  logs, a repeat is silent, a change (including recovery to covered) logs
  again. The per-cycle callers stay log-quiet across 8640 cycles a night.
"""
from datetime import timedelta

import pytest

from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    PlanGate,
    coverage_transition,
    plan_gate,
)

from .test_638_actuation import NOW, _block, _plan


@pytest.mark.unit
class TestTheGateNamesItsDoubt:
    def test_no_plan(self):
        g = plan_gate(None, "ev:ch1", NOW)
        assert g.covered is False and g.reason == "no plan"
        assert plan_gate("not-a-dict", "ev:ch1", NOW).reason == "no plan"

    def test_stale_stamp(self):
        old = _plan(computed_at=NOW - timedelta(hours=30))
        g = plan_gate(old, "ev:ch1", NOW)
        assert g.covered is False and g.reason == "stale stamp"

    def test_outside_span(self):
        afternoon = NOW.replace(hour=15)
        g = plan_gate(_plan(), "ev:ch1", afternoon)
        assert g.covered is False and g.reason == "outside span"

    def test_demand_not_in_plan(self):
        g = plan_gate(_plan(), "ev:other", NOW)
        assert g.covered is False and g.reason == "not in plan"

    def test_verdict_carries_the_status(self):
        for status in ("yields", "partial"):
            g = plan_gate(_plan(status=status), "ev:ch1", NOW)
            assert g.covered is False and g.reason == f"verdict {status}"

    def test_malformed_block(self):
        p = _plan(blocks=[{"id": "ev:ch1", "start": "not-a-date",
                           "end": None, "power_w": "x"}])
        g = plan_gate(p, "ev:ch1", NOW)
        assert g.covered is False and g.reason == "malformed block"

    def test_covered_has_no_doubt(self):
        p = _plan(blocks=[_block("ev:ch1", 23, 1, 4140)])
        g = plan_gate(p, "ev:ch1", NOW)
        assert g.covered is True and g.reason == ""


@pytest.mark.unit
class TestOncePerTransition:
    def test_first_sight_logs_and_names_the_reason(self):
        seen = {}
        msg = coverage_transition(seen, "ev:ch1", PlanGate(reason="no plan"))
        assert msg is not None
        assert "ev:ch1" in msg and "no plan" in msg

    def test_a_repeat_is_silent(self):
        seen = {}
        gate = PlanGate(reason="stale stamp")
        assert coverage_transition(seen, "ev:ch1", gate) is not None
        for _ in range(5):
            assert coverage_transition(seen, "ev:ch1", gate) is None

    def test_a_changed_reason_logs_again(self):
        seen = {}
        coverage_transition(seen, "ev:ch1", PlanGate(reason="no plan"))
        msg = coverage_transition(
            seen, "ev:ch1", PlanGate(reason="outside span"))
        assert msg is not None and "outside span" in msg

    def test_recovery_to_covered_logs(self):
        seen = {}
        coverage_transition(seen, "ev:ch1", PlanGate(reason="no plan"))
        msg = coverage_transition(seen, "ev:ch1", PlanGate(covered=True))
        assert msg is not None and "COVER" in msg.upper()

    def test_demands_are_tracked_independently(self):
        seen = {}
        gate = PlanGate(reason="no plan")
        assert coverage_transition(seen, "ev:ch1", gate) is not None
        assert coverage_transition(seen, "load:heizband", gate) is not None
        assert coverage_transition(seen, "ev:ch1", gate) is None

    def test_the_uncovered_message_says_who_decides(self):
        """The soak reads this line to attribute the night — it must say
        the reactive layer is driving, not merely that the plan is not."""
        msg = coverage_transition({}, "ev:ch1", PlanGate(reason="no plan"))
        assert "reactive" in msg.lower()


class TestTheLogTagIsTheHonestMode:
    """(15.08, PROD first actuation-ON night) Six planner log lines
    hardcoded ``(shadow #638)`` — written in the shadow soak and never
    re-tagged when actuation shipped, so a REAL actuating night logged
    its no-demands answer as shadow. The tick's own comment states the
    contract: the tag is the honest mode of THIS stamp. Every planner
    line must interpolate the tag; none may bake the mode in."""

    def test_no_planner_line_hardcodes_the_mode(self):
        import inspect

        from custom_components.solar_energy_management.coordinator import (
            coordinator as mod,
        )
        src = inspect.getsource(mod)
        assert 'ENERGY-PLAN (shadow' not in src, (
            "a planner log line bakes in 'shadow' — interpolate the tag")
        assert 'ENERGY-PLAN (active' not in src, (
            "a planner log line bakes in 'active' — interpolate the tag")
