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
from custom_components.solar_energy_management.coordinator.overnight_actuation import (
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
        _overnight_plan_gate helper every other consumer uses — one gate,
        one coverage log."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._run_battery_pipeline)
        assert '_overnight_plan_gate("battery")' in src


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
