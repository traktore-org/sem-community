"""#1102 round 3 — a tank in its comfort band skipped the daylight wait.

lostcontrol, 09.11.2026 (Fronius, no battery, hot water by a heat pump):
"Au moins 1 h" a day, "Finish overnight via: Grid", a comfort band of
Keep at 50 °C + 5 °C extra from surplus, forced below 36 °C. A Monday
calendar tariff is cheap from 12:00. The decision log:

    12:00:07  on   plan_window  "planned block"   sun 1714 W, surplus 0
    12:30:17  off  overnight_end "cheap-hours top-up ended — today's
                                  daylight can still finish the target"

The tank read 54.5 °C at noon — "willing" (between 36 and 55 °C), the
state a boiler is in most of the day. Two doors let the daily minimum buy
the grid at noon, past the #953 rule that the grid waits while the
remaining daylight can still deliver the hour owed:

* the comfort-banking pass started on ANY open plan block — the merged
  verdict said ``in_block`` for the runtime block too;
* ``grid_top_up_defers_to_sun`` exempted every "willing" band, so the
  cheap-hours pass would have started it as well.

Thirty minutes later (its minimum run) the band was full, the exemption
dropped, and the force-expiry twin ended the run with the daylight reason.
The banking exemption now needs the plan's COMFORT block
(``PlanVerdict.comfort_in_block``).

Also here: the goal-gate stops printed one code for four causes, so the
Why? card said "It ran long enough today" for the 06:05 stop of a tank
that had reached its temperature.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import (
    reason_codes as RC,
)
from custom_components.solar_energy_management.coordinator import (
    surplus_controller as sc_mod,
)
from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    UNCOVERED,
    PlanGate,
    merge_load_gates,
)
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
    compute_load_intent,
    solar_bounded_surplus,
)
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from homeassistant.util import dt as dt_util

H = 3600.0
# 12:00 on 9 November near Zurich: sunset ~16:55, so ~4.9 h of daylight.
DAYLIGHT_AT_NOON = 4.9 * H


def _boiler(*, comfort_state="willing", deficit_s=1 * H):
    """The reporter's hot water: a 3 kW switch, mode Solar only, 1 h a day,
    finished from the grid in cheap hours, a comfort band set."""
    d = MagicMock()
    d.device_id = "hot_water"
    d.name = "Eau chaude"
    d.priority = 1
    d.min_power_threshold = 3000
    d.rated_power = 3000
    d.is_enabled = True
    d.managed_externally = False
    d.is_active = False
    d.device_type = MagicMock(value="switch")
    d.control_mode = DeviceControlMode.SURPLUS
    d._sem_owned = False
    d.battery_assist_enabled = False
    d.battery_eligible_overnight = False
    d.top_up_policy = "cheap_hours"
    d.remaining_daily_runtime_sec = deficit_s
    d.has_runtime_deficit = deficit_s > 0
    d.needs_offpeak_activation = deficit_s > 0
    d.activate = AsyncMock(return_value=3000)
    d.adjust_power = AsyncMock(return_value=3000)
    d.get_current_consumption = MagicMock(return_value=0.0)
    d.can_activate = MagicMock(return_value=True)
    d.can_deactivate = MagicMock(return_value=True)
    d.status = MagicMock()
    d.status.allocated_power_w = 0.0
    d.status.state = MagicMock(value="idle")
    d._offpeak_forced = False
    d._offpeak_forced_date = None
    d._batt_overnight_forced = False
    d._batt_overnight_forced_date = None
    d._daily_runtime_meter_day = None
    d.daily_targets_met = False
    d.daily_max_runtime_reached = False
    d.stop_condition_met = False
    d.is_deadline_approaching = False
    d.start_reserve_w = 0.0
    d.comfort_state = comfort_state
    # (#1335) a real thermometer band (Keep at 50 °C, forced below 36 °C):
    # the layers read the band itself, not only its state name
    d._comfort_reading = lambda: {"willing": 45.0, "forced": 30.0,
                                  "banked": 56.0}.get(d.comfort_state)
    d._comfort_thresholds_c = lambda: (50.0, 5.0, 36.0)
    d._comfort_direction = lambda: "heat"
    d.runs_without_surplus = False
    d.locked_by_operator = False
    d.stop_entity = None
    d.depends_on = None
    d.__class__ = MagicMock

    async def _act(*_a, **_k):
        d.is_active = True
        d.needs_offpeak_activation = False
        return 3000

    async def _deact():
        d.is_active = False
    d.activate = AsyncMock(side_effect=_act)
    d.deactivate = AsyncMock(side_effect=_deact)
    return d


def _running(d):
    """The same boiler mid-run on a SEM grid top-up."""
    d.is_active = True
    d._sem_owned = True
    d._offpeak_forced = True
    d._daily_runtime_meter_day = dt_util.now().date()
    d._offpeak_forced_date = d._daily_runtime_meter_day
    d.needs_offpeak_activation = False
    d.get_current_consumption = MagicMock(return_value=3000.0)
    return d


def _verdict(*, load_open=False, comfort_open=False):
    """What the coordinator hands the controller: both demands merged."""
    load = (PlanGate(covered=True, in_block=True, block_power_w=3000.0)
            if load_open else UNCOVERED)
    comfort = (PlanGate(covered=True, in_block=True, block_power_w=3000.0)
               if comfort_open else UNCOVERED)
    return merge_load_gates(load, comfort, deficit_kwh=3.0, deficit_h=1.0)


@pytest.fixture
def notes(monkeypatch):
    """Every load command's reason code, as the Why? card gets it."""
    seen = []

    def _note(device, *, on, watts=None, reason_code="", text="",
              observer=False):
        seen.append((on, reason_code, text))
    monkeypatch.setattr(sc_mod, "_note_load", _note)
    return seen


async def _cycle(sc, *, daylight_s, is_night=False, plan=None, solar_w=1714.0):
    surplus = solar_bounded_surplus(
        grid_export_w=0.0, active_draw_w=sc.active_surplus_draw_w(),
        solar_w=solar_w)
    await sc.update(
        surplus, price_level="cheap", reclaim_w=0.0, battery_priority=100,
        battery_soc=None, battery_reserve_soc=10.0, is_night=is_night,
        daylight_remaining_s=daylight_s,
        plan_windows=({"hot_water": plan} if plan is not None else None))


@pytest.mark.unit
class TestTheMergedVerdictSaysWhichBlock:
    def test_the_runtime_block_is_not_a_comfort_block(self):
        v = _verdict(load_open=True)
        assert v.in_block is True and v.hold is False
        assert v.comfort_in_block is False

    def test_the_comfort_block_says_so(self):
        assert _verdict(comfort_open=True).comfort_in_block is True
        assert _verdict(load_open=True, comfort_open=True).comfort_in_block

    def test_no_opinion_has_no_comfort_block(self):
        assert PlanVerdict().comfort_in_block is False


@pytest.mark.unit
class TestTheReportersNoon:
    async def test_the_runtime_block_waits_for_the_sun(self, mock_hass, notes):
        # Pre-fix: the banking pass started it here, "planned block".
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _boiler()
        sc.register_device(boiler)
        for _ in range(3):
            await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                         plan=_verdict(load_open=True))
        assert not boiler.activate.called
        assert boiler._offpeak_forced is False

    async def test_without_a_plan_it_waits_too(self, mock_hass, notes):
        # Pre-fix: the cheap-hours pass started it, the willing band exempt.
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _boiler()
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON)
        assert not boiler.activate.called

    async def test_a_plain_load_already_waited(self, mock_hass, notes):
        # The same boiler without a band — the #953 behaviour the band
        # now shares, so the wait is not new.
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _boiler(comfort_state="")
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                     plan=_verdict(load_open=True))
        assert not boiler.activate.called

    async def test_the_end_of_the_day_still_buys_the_hour(self, mock_hass, notes):
        # Not a blanket refusal: once the sun has no time left, the cheap
        # hour finishes the minimum, under the cheap-hours code. (#1102/
        # #1335) For a load without a thermometer band: with one, the band
        # leads and the run time asks nothing (the heater ladder).
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _boiler(comfort_state="")
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=0.5 * H, plan=_verdict(load_open=True))
        boiler.activate.assert_awaited_once()
        assert boiler._offpeak_forced is True
        assert (True, RC.LOAD_CHEAP_GRID,
                "cheap-hours grid — runtime deficit") in notes

    async def test_the_night_block_runs_as_cheap_hours(self, mock_hass, notes):
        # The 05:12 run: the night is the overnight promise, unchanged —
        # only its label moves from "planned block" to "cheap hours".
        # (#1335) a load without a band: with one, the band leads and the
        # plan places no runtime block for it (the heater ladder)
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _boiler(comfort_state="")
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=12 * H, is_night=True, solar_w=0.0,
                     plan=_verdict(load_open=True))
        boiler.activate.assert_awaited_once()
        assert [n[1] for n in notes if n[0]] == [RC.LOAD_CHEAP_GRID]


@pytest.mark.unit
class TestTheComfortBlockStillBanks:
    async def test_it_starts_in_its_block(self, mock_hass, notes):
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _boiler()
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                     plan=_verdict(comfort_open=True))
        boiler.activate.assert_awaited_once()
        # (#1335) the layers name the banking rung its own code
        assert [n[1] for n in notes if n[0]] == [RC.LOAD_COMFORT_GOAL]

    async def test_the_expiry_twin_leaves_it_in_its_block(self, mock_hass, notes):
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler())
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                     plan=_verdict(comfort_open=True))
        assert not boiler.deactivate.called

    async def test_a_runtime_run_by_day_is_still_ended(self, mock_hass, notes):
        # Start and stop read the same terms: the run the start now
        # refuses is the run the expiry twin ends.
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler())
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                     plan=_verdict(load_open=True))
        boiler.deactivate.assert_awaited()
        assert [n[1] for n in notes if not n[0]] == [RC.LOAD_OVERNIGHT_END]


@pytest.mark.unit
class TestTheDesiredStateTwin:
    def _intent(self, plan, **kw):
        return compute_load_intent(
            _boiler(), remaining_surplus_w=0.0, price_is_cheap=True,
            is_night=False, daylight_remaining_s=DAYLIGHT_AT_NOON,
            plan=plan, **kw)

    def test_the_runtime_block_at_noon_is_off(self):
        assert self._intent(_verdict(load_open=True)).on is False

    def test_the_comfort_block_at_noon_banks(self):
        i = self._intent(_verdict(comfort_open=True))
        assert i.on is True and i.source == "cheap_grid"


@pytest.mark.unit
class TestEachStopSaysItsOwnCause:
    """The 06:05 stop: a full tank, printed as "It ran long enough today"."""

    async def _stop(self, mock_hass, notes, plan=None, **state):
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler())
        for k, v in state.items():
            setattr(boiler, k, v)
        sc.register_device(boiler)
        # the night: the force-expiry pass has no cause of its own
        await _cycle(sc, daylight_s=12 * H, is_night=True, solar_w=0.0,
                     plan=plan)
        boiler.deactivate.assert_awaited()
        return [n[1] for n in notes if not n[0]]

    async def test_a_full_tank_is_its_stop_condition(self, mock_hass, notes):
        assert await self._stop(mock_hass, notes, stop_condition_met=True,
                                comfort_state="banked") == [
            RC.LOAD_STOP_CONDITION]

    async def test_the_minimum_met_is_target_met(self, mock_hass, notes):
        assert await self._stop(mock_hass, notes, daily_targets_met=True,
                                has_runtime_deficit=False) == [
            RC.LOAD_TARGET_MET]

    async def test_the_cap_is_daily_max(self, mock_hass, notes):
        assert await self._stop(mock_hass, notes,
                                daily_max_runtime_reached=True) == [
            RC.LOAD_DAILY_MAX]

    async def test_a_closed_window_is_plan_closed(self, mock_hass, notes):
        assert await self._stop(
            mock_hass, notes,
            plan=PlanVerdict(hold=True, reason="joint energy plan: later"),
        ) == [RC.LOAD_PLAN_CLOSED]


@pytest.mark.unit
class TestTheFloorDoesNotCutABankingRun:
    """Sibling of the same mix-up: ``_offpeak_forced`` marks a banking run
    and a minimum-run top-up alike. With the minimum met, the floor clause
    ended the banking run after its minimum run, and the banking pass
    started it again after the minimum pause — on/off through the block."""

    async def test_in_its_block_it_runs_on(self, mock_hass, notes):
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler(deficit_s=0.0))
        boiler.daily_targets_met = True
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                     plan=_verdict(comfort_open=True))
        assert not boiler.deactivate.called

    async def test_a_battery_run_in_the_block_goes_on_from_the_grid(self, mock_hass, notes):
        # Banking never runs on the battery. (#1335) In its comfort block a
        # Tier-2 run past its minimum is not stopped and started again (the
        # old passes ended it, and the banking pass restarted it one minimum
        # pause later): it goes on as the plan's banking run, on the grid.
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler(deficit_s=0.0))
        boiler._offpeak_forced = False
        boiler._offpeak_forced_date = None
        boiler._batt_overnight_forced = True
        boiler._batt_overnight_forced_date = boiler._daily_runtime_meter_day
        boiler.battery_eligible_overnight = True
        boiler.daily_targets_met = True
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=12 * H, is_night=True, solar_w=0.0,
                     plan=_verdict(comfort_open=True))
        assert not boiler.deactivate.called
        assert boiler._batt_overnight_forced is False
        assert boiler._offpeak_forced is True

    async def test_a_battery_run_past_its_floor_ends_outside_the_block(self, mock_hass, notes):
        # …and with no comfort block it is the floor's to end (#688, class 18)
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler(deficit_s=0.0))
        boiler._offpeak_forced = False
        boiler._offpeak_forced_date = None
        boiler._batt_overnight_forced = True
        boiler._batt_overnight_forced_date = boiler._daily_runtime_meter_day
        boiler.battery_eligible_overnight = True
        boiler.daily_targets_met = True
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=12 * H, is_night=True, solar_w=0.0)
        boiler.deactivate.assert_awaited()
        assert [n[1] for n in notes if not n[0]] == [RC.LOAD_TARGET_MET]

    async def test_outside_its_block_the_floor_still_ends_it(self, mock_hass, notes):
        sc = SurplusController(mock_hass, regulation_offset=0)
        boiler = _running(_boiler(deficit_s=0.0))
        boiler.daily_targets_met = True
        sc.register_device(boiler)
        await _cycle(sc, daylight_s=DAYLIGHT_AT_NOON,
                     plan=_verdict(load_open=True))
        boiler.deactivate.assert_awaited()
        assert [n[1] for n in notes if not n[0]] == [RC.LOAD_TARGET_MET]


_SC = (__import__("pathlib").Path(__file__).resolve().parent.parent
       / "coordinator" / "surplus_controller.py")


def _sc_tree():
    import ast
    return ast.parse(_SC.read_text(encoding="utf-8"))


@pytest.mark.unit
class TestTheControllerReadsOneWordPerQuestion:
    """The guard for the class: the load controller may start or spare a
    run on the COMFORT block only. ``in_block`` answers "is any block of
    this device open" and lifts holds; nothing here may read it."""

    def test_no_load_pass_reads_the_merged_word(self):
        import ast
        bad = []
        for node in ast.walk(_sc_tree()):
            if isinstance(node, ast.Attribute) and node.attr == "in_block":
                bad.append(node.lineno)
            if (isinstance(node, ast.Call)
                    and getattr(node.func, "id", "") == "getattr"
                    and len(node.args) >= 2
                    and isinstance(node.args[1], ast.Constant)
                    and node.args[1].value == "in_block"):
                bad.append(node.lineno)
        assert bad == [], f"surplus_controller reads in_block at {bad}"

    def test_every_daylight_wait_is_told_about_the_comfort_block(self):
        import ast
        calls = [n for n in ast.walk(_sc_tree())
                 if isinstance(n, ast.Call)
                 and getattr(n.func, "id", "") == "grid_top_up_defers_to_sun"]
        # (#1335) one engine: layer 1 is the one site (start and stop alike)
        assert len(calls) >= 1
        missing = [c.lineno for c in calls
                   if "comfort_block_open" not in {k.arg for k in c.keywords}]
        assert missing == [], f"no comfort_block_open at {missing}"
        # …and each one reads the plan's comfort block, not a constant
        src = _SC.read_text(encoding="utf-8")
        constant = [c.lineno for c in calls for k in c.keywords
                    if k.arg == "comfort_block_open"
                    and "comfort_in_block" not in ast.get_source_segment(
                        src, k.value)]
        assert constant == [], f"comfort_block_open not read at {constant}"
