"""#939 — the estimate-stop announcement ping-ponged between two bounds.

Live 10.09.2026, 05:14–05:20 (Tesla, "at least 90 %, up to Full", sensor
89 %, SEM's measured estimate just past 90 %): the phone got "stopped at
~90 % (estimated)" and "car reported 89 % — topping up to your 100 %
target", alternating, several times a minute, until the owner moved the
Min slider.

The latch was one flag for two bounds. The announcement loops over Min then
Max: Min's stop condition set the flag, and on the next cycle Max's resume
condition — "the capped estimate has not reached 100 %", true all night —
released it. The next cycle Min set it again. The latch now holds WHICH
bound stopped, and only that bound's need re-opening resumes.

Guard: for any inputs, a latch that starts clear announces at most once
over repeated identical cycles, and no latch ever alternates. The vacuity
twin runs the old bare-flag rule through the same property and must fail
it on the live numbers.
"""
from __future__ import annotations

import itertools
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.ev_soc_need import (
    estimate_stop_step,
    soc_remaining_need,
)
from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)

CAP = 60.0
LIVE_BOUNDS = (("min", 90.0), ("max", 100.0))
LIVE_SENSOR = 89.0
LIVE_CEILING = 90.2


def _old_bare_flag_step(active, bounds, sensor, ceiling, cap):
    """The pre-#939 rule, verbatim in shape: one bool for both bounds."""
    for _name, target in bounds:
        need = soc_remaining_need(target, sensor, ceiling, cap)
        sensor_rem = need.sensor_kwh or 0.0
        eff_rem = need.effective_kwh or 0.0
        if not active and sensor_rem > 0.1 and eff_rem <= 0.1:
            return True, "stop", target
        if active and eff_rem > 0.1:
            return False, "resume", target
    return active, None, None


def _events(step, latch, bounds, sensor, ceiling, cycles=30):
    out = []
    for _ in range(cycles):
        latch, event, _target = step(latch, bounds, sensor, ceiling, CAP)
        if event is not None:
            out.append(event)
    return out


class TestTheLiveMorning:
    def test_one_stop_then_silence(self):
        latch, event, target = estimate_stop_step(
            None, LIVE_BOUNDS, LIVE_SENSOR, LIVE_CEILING, CAP)
        assert (latch, event, target) == ("min", "stop", 90.0)
        assert _events(estimate_stop_step, latch, LIVE_BOUNDS,
                       LIVE_SENSOR, LIVE_CEILING) == []

    def test_a_fresh_reading_below_the_bound_resumes(self):
        """The #708 resume the latch exists for: the car reports 87 %, the
        measured cap re-anchors on it, Min's need opens again."""
        assert estimate_stop_step("min", LIVE_BOUNDS, 87.0, 87.0, CAP) == (
            None, "resume", 90.0)

    def test_raising_the_stopped_bound_resumes_to_the_new_target(self):
        """What ended the storm live: Min moved 90 → 100."""
        raised = (("min", 100.0), ("max", 100.0))
        assert estimate_stop_step("min", raised, LIVE_SENSOR, LIVE_CEILING, CAP) == (
            None, "resume", 100.0)

    def test_a_stop_at_max_is_not_released_by_min(self):
        """Sensor already past Min, the cap past Max: stopped at Max, and
        Min — satisfied — has nothing to say about it."""
        latch, event, _ = estimate_stop_step(
            None, (("min", 80.0), ("max", 95.0)), 93.0, 96.0, CAP)
        assert (latch, event) == ("max", "stop")
        assert _events(estimate_stop_step, latch, (("min", 80.0), ("max", 95.0)),
                       93.0, 96.0) == []


# The class guard's input space: every ordering of sensor / cap / Min / Max
# that the loop can see, with Max >= Min as ``_resolve_target`` clamps it.
_SENSORS = (70.0, 85.0, 89.0, 90.0, 95.0, 100.0)
_CEILINGS = (None, 70.0, 89.5, 90.2, 95.0, 100.0)
_BOUND_PAIRS = [(lo, hi) for lo in (80.0, 90.0, 100.0)
                for hi in (80.0, 90.0, 95.0, 100.0) if hi >= lo]
_GRID = list(itertools.product(_SENSORS, _CEILINGS, _BOUND_PAIRS))


def _violations(step, clear_latch, latches):
    bad = []
    for sensor, ceiling, (lo, hi) in _GRID:
        bounds = (("min", lo), ("max", hi))
        from_clear = _events(step, clear_latch, bounds, sensor, ceiling)
        if len(from_clear) > 1:
            bad.append(("from clear", sensor, ceiling, lo, hi, from_clear))
        for latch in latches:
            seq = _events(step, latch, bounds, sensor, ceiling)
            # At most a resume and one new stop, then a fixed point — a latch
            # set under OLDER inputs may be released once; it never alternates.
            if len(seq) > 2:
                bad.append(("from latch", latch, sensor, ceiling, lo, hi, seq))
    return bad


class TestIdenticalInputsNeverAnnounceTwice:
    def test_the_rule_holds_over_the_whole_grid(self):
        assert _violations(estimate_stop_step, None, ("min", "max")) == []

    def test_vacuity_twin_the_old_rule_fails_it_on_the_live_numbers(self):
        seq = _events(_old_bare_flag_step, False, LIVE_BOUNDS,
                      LIVE_SENSOR, LIVE_CEILING)
        assert seq[:4] == ["stop", "resume", "stop", "resume"]
        assert _violations(_old_bare_flag_step, False, (True,)), (
            "the guard must be able to see the ping-pong it was written for"
        )


def _coord():
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.config = {}
    det = EVTaperDetector({"ev_battery_capacity_kwh": CAP})
    c._ev_taper_detectors = {"ev_charger": det}
    c._notification_manager = SimpleNamespace(
        notify_ev_estimate_stop=AsyncMock(),
        notify_ev_estimate_resume=AsyncMock(),
    )
    return c, det


_CFG = {"id": "ev_charger", "ev_target_type": "soc", "ev_target_soc": 90,
        "ev_target_soc_max": 100, "ev_battery_capacity_kwh": CAP}
_INTEL = {"vehicle_soc": LIVE_SENSOR, "energy_accounted_soc": LIVE_CEILING,
          "vehicle_soc_age_min": 14}


async def _cycles(c, n, cfg=_CFG, intel=_INTEL, connected=True):
    for _ in range(n):
        await SEMCoordinator._announce_estimate_stop(
            c, "ev_charger", intel, cfg, "EV Charger", connected)


class TestTheCoordinatorSendsOneMessage:
    async def test_thirty_cycles_of_the_live_morning_send_one_stop(self):
        c, det = _coord()
        await _cycles(c, 30)
        nm = c._notification_manager
        assert nm.notify_ev_estimate_stop.await_count == 1
        assert nm.notify_ev_estimate_stop.await_args.kwargs["target_soc"] == 90
        assert nm.notify_ev_estimate_resume.await_count == 0
        assert det._estimate_stop_active is True

    async def test_moving_min_ends_it_with_one_resume(self):
        c, det = _coord()
        await _cycles(c, 5)
        await _cycles(c, 10, cfg={**_CFG, "ev_target_soc": 100})
        nm = c._notification_manager
        assert nm.notify_ev_estimate_stop.await_count == 1
        assert nm.notify_ev_estimate_resume.await_count == 1
        assert nm.notify_ev_estimate_resume.await_args.kwargs["target_soc"] == 100
        assert det._estimate_stop_active is False

    @pytest.mark.parametrize("gate", ["kwh_target", "unplugged", "no_sensor"])
    async def test_the_gates_still_keep_it_quiet(self, gate):
        c, _det = _coord()
        cfg, intel, connected = dict(_CFG), dict(_INTEL), True
        if gate == "kwh_target":
            cfg["ev_target_type"] = "kwh"
        elif gate == "unplugged":
            connected = False
        else:
            intel["vehicle_soc"] = None
        await _cycles(c, 5, cfg=cfg, intel=intel, connected=connected)
        nm = c._notification_manager
        assert nm.notify_ev_estimate_stop.await_count == 0
        assert nm.notify_ev_estimate_resume.await_count == 0

    async def test_a_disconnect_clears_the_bound(self):
        c, det = _coord()
        await _cycles(c, 3)
        assert det._estimate_stop_bound == "min"
        det.reset_session()
        assert det._estimate_stop_bound is None
        assert det._estimate_stop_active is False
