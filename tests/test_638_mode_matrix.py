"""#638 one-gate — the MODE MATRIX pins.

The unification moves WHERE the night window comes from; it must move
NOTHING else. Every mode's contract is pinned here BEFORE the retirement
commits, so a regression reads as a failed pin, not as a soak surprise:

* ``always_max`` never waits — not for a plan verdict, not for a tariff.
* ``solar_only`` never charges at night, plan or no plan.
* ``solar_plus_cheap`` daytime is REACTIVE (live tariff level), and its
  night path is the ONE shared seam (`_MIN_PLUS_SOLAR._decide_night`) —
  no private per-mode copies.
* battery user force modes (`force_charge`/`force_discharge`/`off`) are
  SENIOR to the scheduler and (post-C4) to the plan — user intent is a
  guarantee, not a schedule entry.
* the gate's authority already spans the DAY (horizon-spanning plan), so
  C5's comfort windows ride existing mechanics, not new ones.
"""

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.decide import (
    AlwaysMaxMode,
    SolarPlusCheapMode,
    _MIN_PLUS_SOLAR,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    ChargerIntent,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.overnight_actuation import (
    plan_gate,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)

from .test_decide import _view


_HOLD = PlanVerdict(hold=True, reason="joint overnight plan: outside window")


@pytest.mark.unit
class TestAlwaysMaxNeverWaits:
    """'Always (max)' is a promise. No planning layer may hold it."""

    def test_a_plan_hold_does_not_gate_always_max_at_night(self):
        v = _view("always_max", is_night=True, solar_w=0.0, plan=_HOLD)
        d = AlwaysMaxMode().decide(v)
        assert d.intent == ChargerIntent.CHARGE_MAX

    def test_nor_during_the_day(self):
        v = _view("always_max", is_night=False, plan=_HOLD)
        assert AlwaysMaxMode().decide(v).intent == ChargerIntent.CHARGE_MAX


@pytest.mark.unit
class TestSolarOnlyNeverNightCharges:
    """solar_only's contract: never grid, never night — with or without
    a plan. (PROD's own mode; its nights must stay untouched.)"""

    def test_night_no_surplus_is_idle_without_a_plan(self):
        v = _view("solar_only", is_night=True, solar_w=0.0)
        from custom_components.solar_energy_management.coordinator.decide import (
            SolarOnlyMode,
        )
        assert SolarOnlyMode().decide(v).intent == ChargerIntent.IDLE

    def test_a_plan_verdict_changes_nothing(self):
        from custom_components.solar_energy_management.coordinator.decide import (
            SolarOnlyMode,
        )
        v = _view("solar_only", is_night=True, solar_w=0.0, plan=_HOLD)
        assert SolarOnlyMode().decide(v).intent == ChargerIntent.IDLE


@pytest.mark.unit
class TestSolarPlusCheapDayStaysReactive:
    """The daytime price gate is a LIVE gate, not window selection —
    it survives the retirement untouched."""

    def test_expensive_day_pauses_grid(self):
        v = _view("solar_plus_cheap", is_night=False, tariff_level="expensive",
                  solar_w=0.0)
        d = SolarPlusCheapMode().decide(v)
        assert d.intent == ChargerIntent.IDLE
        assert "pausing" in d.reason

    def test_night_goes_through_the_one_shared_seam(self):
        """Structural: the night branch delegates to the shared decision —
        no mode-private copy of the verdict check may reappear."""
        import inspect
        src = inspect.getsource(SolarPlusCheapMode.decide)
        assert "_MIN_PLUS_SOLAR._decide_night" in src


def _bview(*, mode="auto", reserve=None, soc=80.0, sched=None):
    cfg = {"battery_max_discharge_power": 4000,
           "battery_max_charge_power_w": 5000,
           "battery_mode": mode}
    if reserve is not None:
        cfg["battery_reserve_soc"] = reserve
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config=cfg,
        fleet=FleetContext(),
        charging_state="idle",
        ev_charging=False,
        home_consumption_w=500.0,
        scheduler_decision=sched,
    )


def _scheduled():
    """A SCHEDULED verdict shaped like the scheduler's decision."""
    return SimpleNamespace(
        state=SimpleNamespace(value="scheduled"),
        target_soc=90.0, charge_power_w=3000.0, duration_min=120,
        schedule=SimpleNamespace(is_active_now=lambda now=None: True),
    )


@pytest.mark.unit
class TestBatteryUserForceModesAreSenior:
    """A user-chosen manual mode wins over the scheduler — and after C4,
    over the plan. The reason string proves WHICH branch fired."""

    def test_force_charge_beats_a_scheduled_window(self):
        d = decide_battery(_bview(mode="force_charge", sched=_scheduled()))
        assert d.intent == BatteryIntent.FORCE_CHARGE
        assert "mode=force_charge" in d.reason

    def test_force_discharge_above_reserve_beats_the_scheduler(self):
        d = decide_battery(_bview(mode="force_discharge", reserve=20.0,
                                  soc=80.0, sched=_scheduled()))
        assert d.intent == BatteryIntent.FORCE_DISCHARGE
        assert "mode=force_discharge" in d.reason

    def test_off_is_fully_hands_off(self):
        d = decide_battery(_bview(mode="off", sched=_scheduled()))
        assert d.intent == BatteryIntent.OFF


@pytest.mark.unit
class TestTheGateAlreadySpansTheDay:
    """The horizon-spanning plan gives daytime blocks the same authority
    mechanics as night ones — C5 rides this, it does not invent it."""

    def test_a_daytime_block_is_covered_and_in_block(self):
        stamp = datetime(2026, 8, 11, 7, 30)
        noonish = datetime(2026, 8, 11, 14, 30)
        slots = []
        t = stamp
        while t < datetime(2026, 8, 12, 7, 0):
            e = t + timedelta(hours=1)
            slots.append({"start": t.isoformat(), "end": e.isoformat()})
            t = e
        plan = {
            "computed_at": stamp.isoformat(),
            "demands": [{"id": "load:heizband", "status": "fits"}],
            "slots": slots,
            "blocks": [{"id": "load:heizband",
                        "start": datetime(2026, 8, 11, 14, 0).isoformat(),
                        "end": datetime(2026, 8, 11, 15, 0).isoformat(),
                        "power_w": 1000.0}],
        }
        g = plan_gate(plan, "load:heizband", noonish)
        assert g.covered and g.in_block

    def test_load_windows_are_not_night_gated(self):
        """Structural: the collector consults the plan whenever actuation
        is on — day or night. A night-only guard here would orphan every
        daytime comfort/cheap window C5 adds."""
        import inspect
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        src = inspect.getsource(SEMCoordinator._overnight_load_windows)
        assert "is_night" not in src
