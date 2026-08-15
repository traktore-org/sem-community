"""#638 one-gate C4 — the battery seam: scheduler owns WHAT, plan owns WHEN.

`evaluate()` keeps every economic guarantee — deficit, break-even, the
anchored target SOC, charge power, the negative-price override, the replan
triggers. What it no longer owns is the WINDOW: `decide_battery` reads the
joint plan's gate for the ``battery`` demand and force-charges only inside
a planned block.

The fail-open direction here is deliberately INVERTED vs the EV: the EV's
floor is a guarantee (uncovered → charge), but pre-charge is an
optimization — an uncovered night simply doesn't force-charge, and the
named reason makes the non-event visible. The one exception is the
negative-price override (``price_forced``): being PAID to consume is a
reactive price gate, not window selection, and it bypasses the gate.

User force modes (`force_charge`/`force_discharge`/`off`) stay senior to
all of this — pinned in test_638_mode_matrix.
"""

from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    PlanGate,
)


def _sched(*, price_forced=False, power=3000.0):
    d = SimpleNamespace(
        state=SimpleNamespace(value="scheduled"),
        target_soc=90.0, charge_power_w=power, duration_min=120,
        schedule=None, charge_windows=[],
    )
    if price_forced:
        d.price_forced = True
    return d


def _view(*, sched=None, gate=None, soc=50.0):
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 4000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto"},
        fleet=FleetContext(),
        charging_state="idle",
        ev_charging=False,
        home_consumption_w=500.0,
        scheduler_decision=sched,
        plan_gate=gate,
    )


def _covered(*, in_block, block_power_w=2500.0, next_start=None):
    return PlanGate(covered=True, in_block=in_block,
                    block_power_w=block_power_w if in_block else 0.0,
                    remaining_kwh=3.0, next_block_start=next_start)


@pytest.mark.unit
class TestScheduledFollowsThePlan:
    def test_in_block_force_charges_at_the_granted_power(self):
        """The packer granted block power under the peak headroom — the
        force charge must not exceed it (nor the hardware's own cap)."""
        d = decide_battery(_view(sched=_sched(power=5000.0),
                                 gate=_covered(in_block=True,
                                               block_power_w=2500.0)))
        assert d.intent == BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == 2500.0

    def test_the_hardware_cap_still_binds(self):
        d = decide_battery(_view(sched=_sched(power=2000.0),
                                 gate=_covered(in_block=True,
                                               block_power_w=9999.0)))
        assert d.intent == BatteryIntent.FORCE_CHARGE
        assert d.charge_power_w == 2000.0

    def test_outside_the_block_stops_the_force(self):
        d = decide_battery(_view(sched=_sched(),
                                 gate=_covered(in_block=False)))
        assert d.intent == BatteryIntent.STOP_FORCE_CHARGE

    def test_uncovered_does_not_force_charge_and_says_why(self):
        """THE deliberate behavior change of C4: pre-charge is optimization,
        not guarantee — an uncovered night stays un-forced, visibly."""
        d = decide_battery(_view(sched=_sched(),
                                 gate=PlanGate(reason="no plan")))
        assert d.intent == BatteryIntent.STOP_FORCE_CHARGE
        assert "does not cover" in d.reason

    def test_a_missing_gate_reads_as_uncovered(self):
        d = decide_battery(_view(sched=_sched(), gate=None))
        assert d.intent == BatteryIntent.STOP_FORCE_CHARGE
        assert "does not cover" in d.reason

    def test_negative_price_bypasses_the_gate(self):
        """Being PAID to consume is a reactive price gate, not window
        selection — it fires even on an uncovered night."""
        d = decide_battery(_view(sched=_sched(price_forced=True),
                                 gate=PlanGate(reason="no plan")))
        assert d.intent == BatteryIntent.FORCE_CHARGE


@pytest.mark.unit
class TestTheWindowCheckerIsGone:
    def test_now_in_window_no_longer_exists(self):
        import custom_components.solar_energy_management.coordinator.decide_battery as db
        assert not hasattr(db, "_now_in_window")


@pytest.mark.unit
class TestTheCoordinatorWiresTheGate:
    def test_the_battery_view_carries_the_battery_gate(self):
        """Structural: the pipeline populates plan_gate from the same
        _energy_plan_gate helper every other consumer uses — one gate,
        one coverage log."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._run_battery_pipeline)
        assert '_energy_plan_gate("battery")' in src


@pytest.mark.unit
class TestNegativePriceMarksItself:
    def test_evaluate_sets_price_forced_on_the_negative_override(self):
        """The scheduler's negative-price SCHEDULED must carry the flag
        decide_battery uses to bypass the gate."""
        import inspect
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            BatteryChargeScheduler,
        )
        src = inspect.getsource(BatteryChargeScheduler.evaluate)
        neg = src.index("Negative tariff override")
        nxt = src.index("Forecast fallback")
        assert "price_forced=True" in src[neg:nxt]


@pytest.mark.unit
class TestTheSchedulerNoLongerPicksWindows:
    """C4b — evaluate() keeps the economics, loses the window pick and
    the phantom EV co-model (#652's model dies with it)."""

    def test_evaluate_has_no_phantom_ev_params(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            BatteryChargeScheduler,
        )
        params = inspect.signature(BatteryChargeScheduler.evaluate).parameters
        assert "ev_kwh_needed" not in params
        assert "ev_max_power_w" not in params

    def test_the_decision_has_no_window_fields(self):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            SchedulerDecision, SchedulerState,
        )
        d = SchedulerDecision(state=SchedulerState.IDLE)
        assert not hasattr(d, "charge_windows")
        assert not hasattr(d, "schedule")

    def test_the_schedule_classes_are_gone(self):
        import custom_components.solar_energy_management.coordinator.battery_charge_scheduler as bcs
        assert not hasattr(bcs, "NightChargeSchedule")
        assert not hasattr(bcs, "TimeSlot")


@pytest.mark.unit
class TestTheScheduleEntityDerivesFromThePlan:
    """C4c — sensor.battery_scheduler_schedule keeps its dict shape, now
    read from the stamped plan's battery blocks. ev_w is honestly 0: the
    joint plan carries EV blocks under their own ids."""

    def _plan(self):
        return {
            "computed_at": "2026-08-11T21:00:00+00:00",
            "blocks": [
                {"id": "battery", "start": "2026-08-12T03:00:00+00:00",
                 "end": "2026-08-12T05:00:00+00:00", "power_w": 3000.0,
                 "price": 0.12},
                {"id": "ev:keba", "start": "2026-08-12T01:00:00+00:00",
                 "end": "2026-08-12T02:00:00+00:00", "power_w": 4140.0,
                 "price": 0.10},
            ],
        }

    def test_shape_matches_the_old_entity(self):
        from datetime import datetime, timezone
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            schedule_view_from_plan,
        )
        now = datetime(2026, 8, 12, 3, 30, tzinfo=timezone.utc)
        view = schedule_view_from_plan(self._plan(), now)
        assert set(view) == {"slots", "total_battery_kwh", "total_ev_kwh",
                             "total_kwh", "estimated_cost", "peak_limit_w"}
        assert len(view["slots"]) == 1  # ONLY the battery's blocks
        s = view["slots"][0]
        assert set(s) == {"start", "end", "battery_w", "ev_w", "total_w",
                          "price", "active"}
        assert s["battery_w"] == 3000.0 and s["ev_w"] == 0
        assert s["active"] is True          # 03:30 is inside 03:00-05:00
        assert view["total_battery_kwh"] == 6.0
        assert view["estimated_cost"] == round(6.0 * 0.12, 3)

    def test_no_plan_is_an_empty_dict(self):
        from datetime import datetime, timezone
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            schedule_view_from_plan,
        )
        now = datetime(2026, 8, 12, 3, 30, tzinfo=timezone.utc)
        assert schedule_view_from_plan(None, now) == {}
        assert schedule_view_from_plan({"blocks": []}, now) == {}


@pytest.mark.unit
class TestTheVerdictSurvivesTheReboot:
    """C4c — the WHAT persists beside the plan: a reboot mid-block outside
    the evaluation window must still actuate the restored night."""

    def test_roundtrip(self):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            SchedulerDecision, SchedulerState,
            restore_battery_verdict, serialize_battery_verdict,
        )
        d = SchedulerDecision(
            state=SchedulerState.SCHEDULED, target_soc=85.0,
            deficit_kwh=4.2, charge_power_w=3000.0, duration_min=120,
        )
        payload = serialize_battery_verdict(d)
        assert payload["state"] == "scheduled"
        sched = SimpleNamespace(_decision=None)
        restore_battery_verdict(sched, payload)
        r = sched._decision
        assert r is not None
        assert r.state is SchedulerState.SCHEDULED
        assert r.target_soc == 85.0 and r.charge_power_w == 3000.0

    def test_non_scheduled_serializes_to_none(self):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            SchedulerDecision, SchedulerState, serialize_battery_verdict,
        )
        assert serialize_battery_verdict(
            SchedulerDecision(state=SchedulerState.NOT_NEEDED)) is None
        assert serialize_battery_verdict(None) is None

    def test_junk_restores_to_nothing(self):
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            restore_battery_verdict,
        )
        sched = SimpleNamespace(_decision=None)
        restore_battery_verdict(sched, {"state": "banana"})
        assert sched._decision is None
        restore_battery_verdict(sched, "not-a-dict")
        assert sched._decision is None
