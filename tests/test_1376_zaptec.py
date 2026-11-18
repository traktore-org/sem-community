"""#1376 — a Zaptec Go 2 on a home with no battery.

The reporter's diagnostics (17.11): Solar + cheapest hours charged at once
and ignored a cheap window; switching to it did not pause a running charge;
Always (max) sat at 20 A / 4.1 kW.

Causes found in the diagnostics:

* ``battery_charge_platform: "generic"`` was the only battery wiring in the
  options (the options form saved it as its default before #900). It made
  the battery PRESENT, so ``battery_soc_ready_for_plan`` waited for a SOC
  that never comes and NO night plan was ever made ("plan_coverage: no
  plan"). Without a plan the night path charges at its deadline floor now.
* The car draws one phase (204.8 W/A at 20 A); SEM believed three. The
  phase verdict could not see it because the 6-10 A setpoints, read while
  the car was still ramping, spoiled the agreement of the ladder.
* The box's own control number caps at 20 A; the decision text did not say
  who holds the line.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerIntent,
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    battery_soc_ready_for_plan,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    ev_overlay,
    plan_gate,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module,
    Presence,
    module_verdict,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.coordinator.watts_per_amp import (
    WattsPerAmpLearner,
)

CID = "zaptec_9330108264"

# The reporter's options, cut to what the module verdict and the car read.
REPORTER = {
    "has_battery": False,
    "battery_capacity_kwh": 1.0,
    "battery_charge_platform": "generic",
    "battery_charge_scheduler_enabled": False,
    "battery_operating_mode_entity": None,
    "battery_power_sensor": None,
    "battery_discharge_control_entity": None,
    "battery_charge_power_limit_entity": None,
    "ev_chargers": [{
        "id": CID, "charge_mode": "solar_plus_cheap",
        "ev_max_current": 48, "ev_min_current": 6,
        "ev_target_time": "06:30",
    }],
}
ED_NO_BATTERY = SimpleNamespace(has_battery=False, has_ev=False)


class TestTheNightPlanIsMade:
    def test_the_saved_default_platform_is_no_battery(self):
        verdict = module_verdict(REPORTER, ED_NO_BATTERY, True)
        assert verdict[Module.BATTERY] is Presence.ABSENT

    def test_a_home_without_a_battery_may_plan(self):
        """Before: PRESENT + no SOC reading = "not ready" for ever."""
        coord = SimpleNamespace(
            setup_presence=module_verdict(REPORTER, ED_NO_BATTERY, True),
            config=REPORTER, _boot_monotonic=0.0)
        power = SimpleNamespace(battery_soc_unavailable=True)
        assert battery_soc_ready_for_plan(coord, power) is True

    def test_a_brand_platform_still_waits_for_its_soc(self):
        cfg = {**REPORTER, "battery_charge_platform": "huawei"}
        coord = SimpleNamespace(
            setup_presence=module_verdict(cfg, ED_NO_BATTERY, True),
            config=cfg, _boot_monotonic=0.0)
        power = SimpleNamespace(battery_soc_unavailable=True)
        assert battery_soc_ready_for_plan(coord, power) is False


def _stamped_plan(now: datetime) -> dict:
    """The reporter's night: a cheap block 00:00-06:15, 19.1 kWh owed."""
    start = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0,
                                              microsecond=0)
    end = start.replace(hour=6, minute=15)
    return {
        "computed_at": now.isoformat(),
        "demands": [{"id": f"ev:{CID}", "status": "fits"}],
        "slots": [{"start": now.isoformat(), "end": end.isoformat()}],
        "blocks": [{"id": f"ev:{CID}", "start": start.isoformat(),
                    "end": end.isoformat(), "power_w": 4100.0}],
    }


class TestAPlanHoldsTheCharge:
    """With a plan, the car waits for the cheap block — and a charge that
    runs when the mode is switched is stopped."""

    def _decision(self, now, hold_view_plan):
        power = SimpleNamespace(
            solar_power=0.0, home_consumption_power=388.0,
            battery_power=0.0, battery_charge_power=0.0,
            battery_discharge_power=0.0, battery_soc=0.0,
            grid_import_power=4454.0, grid_export_power=0.0,
            ev_power=4066.0, ev_power_per_charger=None,
            ev_connected=True, ev_charging=True,
            ev_connected_per_charger=None, ev_charging_per_charger=None)
        view = build_charger_view(
            FleetCycleState(power=power, config=REPORTER, is_night=True),
            charger_id=CID, charger_cfg=REPORTER["ev_chargers"][0],
            mode="solar_plus_cheap", daily_ev_kwh=0.0, target_kwh=19.1,
            deadline_amps=20, top_up_amps=20, plan=hold_view_plan,
            hardware_max_a=20)
        return decide(view)

    def test_the_gate_waits_for_the_cheap_block(self):
        now = datetime(2026, 11, 17, 23, 9).astimezone()
        gate = plan_gate(_stamped_plan(now), f"ev:{CID}", now)
        wait, floor = ev_overlay(
            gate, remaining_kwh=19.1, reachable=True, deadline_active=False,
            watts_per_amp=690.0, min_amps=6, max_amps=20)
        assert (wait, floor) == (True, 0)

    def test_a_hold_idles_a_running_charge(self):
        now = datetime(2026, 11, 17, 23, 9).astimezone()
        hold = PlanVerdict(hold=True, until=now + timedelta(minutes=51),
                           reason="cheap block")
        d = self._decision(now, hold)
        assert d.intent is ChargerIntent.IDLE
        assert "waiting for the planned window" in d.reason

    def test_no_plan_charges_at_the_deadline_floor(self):
        """The reporter's symptom: the fallback has no cheap-hour opinion."""
        now = datetime(2026, 11, 17, 23, 9).astimezone()
        d = self._decision(now, PlanVerdict())
        assert d.intent is ChargerIntent.CHARGE_AT_AMPS


def _feed(learner, amps, implied, n):
    """``n`` steady cycles at ``amps`` drawing ``implied`` phases of 230 V
    under a three-phase belief."""
    for _ in range(n):
        learner.record(CID, phases=3, commanded_amps=amps,
                       observed_w=amps * 230.0 * implied, nominal_wpa=690.0)


class TestThePhaseVerdictSeesOneRealPhase:
    #: implied phases per setpoint, from the diagnostics (refused samples)
    LADDER = {20: 0.88, 18: 0.82, 16: 0.80, 14: 0.83, 12: 0.81,
              10: 0.67, 8: 0.49, 6: 0.62}

    def test_the_reporters_ladder_says_one_phase(self):
        learner = WattsPerAmpLearner()
        for amps, implied in self.LADDER.items():
            _feed(learner, amps, implied, 4)
        verdict = learner.phase_verdict(CID, 3)
        assert verdict is not None
        assert (verdict["believed"], verdict["measured"]) == (3, 1)

    def test_a_power_cap_is_still_not_a_phase_count(self):
        """A car that takes at most 4.1 kW on three phases: W/A falls as
        the offer rises. That is a cap, and says nothing about phases."""
        learner = WattsPerAmpLearner()
        for amps in (8, 10, 12, 16, 20):
            _feed(learner, amps, min(0.95, 4100.0 / (amps * 690.0)), 4)
        assert learner.phase_verdict(CID, 3) is None


class TestTheBoxLimitIsSaid:
    def _reason(self, hardware_max_a):
        cfg = {"id": CID, "ev_max_current": 48, "ev_min_current": 6}
        power = SimpleNamespace(
            solar_power=0.0, home_consumption_power=300.0,
            battery_power=0.0, battery_charge_power=0.0,
            battery_discharge_power=0.0, battery_soc=0.0,
            grid_import_power=300.0, grid_export_power=0.0, ev_power=0.0,
            ev_power_per_charger=None, ev_connected=True, ev_charging=False,
            ev_connected_per_charger=None, ev_charging_per_charger=None)
        view = build_charger_view(
            FleetCycleState(power=power, config={"ev_chargers": [cfg]},
                            is_night=True),
            charger_id=CID, charger_cfg=cfg, mode="always_max",
            daily_ev_kwh=0.0, hardware_max_a=hardware_max_a)
        return decide(view)

    def test_always_max_names_the_chargers_own_limit(self):
        d = self._reason(20)
        assert d.intent is ChargerIntent.CHARGE_MAX
        assert "charger's own limit is 20 A" in d.reason
        assert "48 A" in d.reason

    def test_no_note_when_nothing_caps_it(self):
        d = self._reason(48)
        assert d.reason == "always_max mode — charge at hardware maximum"
