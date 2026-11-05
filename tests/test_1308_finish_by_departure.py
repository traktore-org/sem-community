"""#1308 — *Finish by departure*: a set Charge by wins over the night end.

@Elmardus: 80 % by 08:15, Night latest end 07:00, Solar + cheapest hours.
Night charging ends at the night's end by design. At 07:01 SEM paused the
car with 15.7 kWh still owed, and the car left at 08:11 no fuller. The
plan fix in beta.5 made the plan count to 07:00 and warn; it did not give
the car the 75 minutes.

With ``finish_by_departure`` on for the charger, the plan counts the hours
to the departure, and after the night end the deadline floor keeps
charging from the grid, at the current that just makes the departure and
nothing faster. The sun still wins when it offers more. Off, the default,
leaves every install exactly as it is.
"""
from __future__ import annotations

import ast
import inspect
import math
from datetime import datetime
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingContext,
)
from custom_components.solar_energy_management.coordinator.decide import decide
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    NightChargePlan,
    plan_night_charge,
)

from .ast_contracts import call_kwargs

AMS = ZoneInfo("Europe/Amsterdam")
WPA_1P = 230.0
PLUG_IN = datetime(2026, 11, 4, 0, 20, tzinfo=AMS)
AFTER_NIGHT = datetime(2026, 11, 4, 7, 10, tzinfo=AMS)
DEPARTURE = datetime(2026, 11, 4, 8, 15, tzinfo=AMS)
NIGHT_END = datetime(2026, 11, 4, 7, 0, tzinfo=AMS)


def _plan(now=PLUG_IN, need=30.0, **kw):
    args = dict(
        now=now, remaining_to_min_kwh=need, min_amps=6, max_amps=28,
        watts_per_amp=WPA_1P, target_time="08:15", night_end="07:00",
        night_start="20:30", tariff_optimized=True, peak_managed_amps=28,
        deadline_at=DEPARTURE,
    )
    args.update(kw)
    return plan_night_charge(**args)


# ── the planner ────────────────────────────────────────────────────


def test_on_the_night_plan_counts_the_hours_to_the_departure():
    """30 kWh from 00:20 to 08:15: 17 A is enough, because charging goes
    on after 07:00. The night itself is not forced."""
    plan = _plan(finish_by_departure=True)
    assert plan.charge_end_dt == DEPARTURE
    hours = (DEPARTURE - PLUG_IN).total_seconds() / 3600.0
    assert plan.hours_to_deadline == pytest.approx(hours, abs=0.01)
    assert plan.deadline_amps == math.ceil(30_000 / hours / WPA_1P) == 17
    assert plan.deadline_active is False
    assert plan.reachable is True
    assert plan.to_departure is False


def test_after_the_night_end_the_floor_just_makes_the_departure():
    """07:10, 6 kWh owed, 65 minutes left: 25 A makes it. The floor forces,
    and there is no faster "finish early" rate at day price."""
    plan = _plan(now=AFTER_NIGHT, need=6.0, finish_by_departure=True,
                 night_over=True)
    hours = (DEPARTURE - AFTER_NIGHT).total_seconds() / 3600.0
    assert plan.charge_end_dt == DEPARTURE
    assert plan.deadline_amps == math.ceil(6_000 / hours / WPA_1P) == 25
    assert plan.deadline_active is True
    assert plan.to_departure is True
    assert plan.top_up_amps == 0
    assert plan.reachable is True
    assert "departure" in plan.reason


def test_after_the_night_end_the_floor_stops_at_the_charger_max():
    """The reporter's 15.7 kWh at 07:00 needs 55 A; the box gives 28. The
    plan says so, and the warning fires."""
    plan = _plan(now=NIGHT_END, need=15.7, finish_by_departure=True,
                 night_over=True)
    assert plan.deadline_amps == 28
    assert plan.reachable is False
    assert plan.should_warn_unreachable is True


def test_a_small_rest_after_the_night_end_still_forces_the_minimum():
    """0.3 kWh owed needs under 6 A; the floor is the minimum and still
    counts as forcing, so no plan gate holds the last minutes back."""
    plan = _plan(now=AFTER_NIGHT, need=0.3, finish_by_departure=True,
                 night_over=True)
    assert plan.deadline_amps == 6
    assert plan.deadline_active is True


def test_off_is_the_shipped_behaviour():
    """Without the switch the night plan stops at 07:00 (#1308, beta.5)."""
    plan = _plan()
    assert plan.charge_end_dt == NIGHT_END
    assert plan.to_departure is False
    assert plan.deadline_amps == 20


def test_night_over_without_the_switch_changes_nothing():
    """The gap flag alone sets nothing: no departure floor, and the
    peak-managed top-up rate stays."""
    plan = _plan(now=AFTER_NIGHT, need=6.0, night_over=True)
    assert plan.to_departure is False
    assert plan.top_up_amps == 28
    assert "departure" not in plan.reason


def test_the_plan_dataclass_keeps_the_flag():
    assert NightChargePlan().to_departure is False


# ── the gap: after the night end, before the departure ─────────────


class _Host(EVControlMixin):
    def __init__(self, tm, night_on=True):
        self.config = {"ev_target_time": "08:15"}
        self.time_manager = tm
        self._ev_device = None
        self._surplus_controller = None
        self._tariff_provider = None
        self._night_committed_w = 0.0
        self._night_on = night_on

    def _mode_allows_night_charging(self, charger_cfg):
        return self._night_on

    def _tariff_optimized_for(self, charger_cfg):
        return True

    def _planning_peak_w(self):
        return math.inf

    def _expected_night_home_w(self, energy, window_hours=8.0):
        return 300.0


def _tm(is_night=False):
    tm = MagicMock()
    tm.is_night_mode.return_value = is_night
    tm.get_night_window.return_value = ("20:30", "07:00")
    tm.get_night_end_time.return_value = "07:00"
    tm.get_night_window_hours.return_value = 10.5
    return tm


CFG = {"id": "smartevse", "ev_target_time": "08:15", "finish_by_departure": True,
       "ev_max_current": 28, "ev_phases": 1, "ev_voltage": 230}


def test_the_gap_is_open_after_the_night_end_before_the_departure():
    assert EVControlMixin._departure_gap_for(_Host(_tm()), CFG, AFTER_NIGHT) is True


def test_the_gap_is_shut_at_night():
    assert EVControlMixin._departure_gap_for(_Host(_tm(True)), CFG, PLUG_IN) is False


def test_the_gap_is_shut_with_the_switch_off():
    cfg = {**CFG, "finish_by_departure": False}
    assert EVControlMixin._departure_gap_for(_Host(_tm()), cfg, AFTER_NIGHT) is False
    cfg.pop("finish_by_departure")
    assert EVControlMixin._departure_gap_for(_Host(_tm()), cfg, AFTER_NIGHT) is False


def test_the_gap_is_shut_when_another_night_comes_first():
    """15:00, the car leaves tomorrow 08:15: tonight charges it. No grid
    charge at day price for a departure a night away."""
    noon = datetime(2026, 11, 4, 15, 0, tzinfo=AMS)
    assert EVControlMixin._departure_gap_for(_Host(_tm()), CFG, noon) is False


def test_the_gap_is_shut_for_a_mode_that_never_grids():
    assert EVControlMixin._departure_gap_for(
        _Host(_tm(), night_on=False), CFG, AFTER_NIGHT) is False


def test_the_coordinators_plan_in_the_gap_reaches_the_departure():
    """The real ``_compute_night_plan`` hands the planner the switch."""
    with patch("custom_components.solar_energy_management.coordinator."
               "ev_control.dt_util.now", return_value=AFTER_NIGHT):
        plan = EVControlMixin._compute_night_plan(
            _Host(_tm()), CFG, 6.0, night_over=True)
    assert plan.charge_end_dt == DEPARTURE
    assert plan.to_departure is True
    assert plan.deadline_amps == 25


def test_the_planner_is_given_both_flags():
    kwargs = call_kwargs(EVControlMixin._compute_night_plan, "plan_night_charge")
    assert kwargs and all(
        "finish_by_departure" in kw and "night_over" in kw for kw in kwargs)


# ── the decision ───────────────────────────────────────────────────


def _view(mode, *, solar_w=0.0, deadline_amps=9, departure_floor=True,
          is_night=False, tariff_level=None, target_kwh=6.0):
    return ChargerView(
        power=ChargerPower(charger_id="smartevse", power_w=0.0,
                           connected=True, charging=False),
        energy=ChargerEnergy(charger_id="smartevse"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 32},
        fleet=FleetContext(
            solar_w=solar_w, home_w=500.0, battery_charge_w=0.0,
            battery_discharge_w=0.0, battery_soc=75.0,
            is_night=is_night, tariff_level=tariff_level,
            battery_assist_max_power_w=4500.0,
            battery_assist_min_surplus_w=1200.0,
        ),
        target_kwh=target_kwh,
        deadline_amps=deadline_amps,
        departure_floor=departure_floor,
    )


GRID_MODES = ["solar_only", "min_plus_solar", "solar_plus_battery",
              "solar_plus_cheap"]


@pytest.mark.parametrize("mode", GRID_MODES)
def test_after_the_night_end_every_grid_mode_charges_at_the_floor(mode):
    d = decide(_view(mode))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps == 9
    assert d.reason_code == RC.CHARGER_DEADLINE
    assert "to departure" in d.reason


def test_an_expensive_hour_charges_at_the_floor_too():
    d = decide(_view("solar_plus_cheap", tariff_level="expensive"))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps == 9


def test_the_sun_wins_when_it_offers_more():
    """9 kW of sun: 12 A of surplus beats the 9 A floor, and the reason
    is the sun's, not the deadline's."""
    d = decide(_view("solar_only", solar_w=9000.0))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert d.commanded_amps >= 12
    assert d.reason_code != RC.CHARGER_DEADLINE


@pytest.mark.parametrize("mode", GRID_MODES)
def test_without_the_flag_the_day_is_unchanged(mode):
    d = decide(_view(mode, departure_floor=False))
    assert d.intent is ChargerIntent.IDLE


def test_at_night_the_night_path_decides():
    d = decide(_view("min_plus_solar", is_night=True))
    assert d.intent is ChargerIntent.CHARGE_AT_AMPS
    assert "night" in d.reason and "to departure" not in d.reason


def test_always_max_and_off_are_untouched():
    assert decide(_view("always_max")).intent is ChargerIntent.CHARGE_MAX
    off = decide(_view("off"))
    assert off.intent is not ChargerIntent.CHARGE_AT_AMPS


def test_nothing_owed_means_no_floor():
    d = decide(_view("solar_only", target_kwh=0.0))
    assert d.intent is ChargerIntent.IDLE


# ── the wiring ─────────────────────────────────────────────────────


def test_every_charger_view_the_coordinator_builds_carries_the_flag():
    """Three sites build a view (primary, per-charger, preview); a site
    without the flag would stop the car at the night end again."""
    from custom_components.solar_energy_management.coordinator import coordinator

    tree = ast.parse(inspect.getsource(coordinator))
    calls = [
        n for n in ast.walk(tree)
        if isinstance(n, ast.Call)
        and getattr(n.func, "id", getattr(n.func, "attr", "")) == "build_charger_view"
    ]
    assert len(calls) >= 2
    missing = [n.lineno for n in calls
               if "departure_floor" not in {k.arg for k in n.keywords}]
    assert not missing, f"build_charger_view without departure_floor at {missing}"


def test_the_context_carries_the_flag():
    assert ChargingContext().night_departure_floor is False


def test_the_setting_is_a_charger_field_in_the_flow_and_the_texts():
    import json
    from pathlib import Path

    from custom_components.solar_energy_management import config_flow

    src = inspect.getsource(config_flow)
    assert src.count('"finish_by_departure"') >= 3, (
        "the per-charger key list and both charger forms must know it")
    root = Path(config_flow.__file__).resolve().parent
    strings = json.loads((root / "strings.json").read_text(encoding="utf-8"))
    assert '"finish_by_departure"' in json.dumps(strings)
    for lang in sorted((root / "translations").glob("*.json")):
        assert "finish_by_departure" in lang.read_text(encoding="utf-8"), lang.name
