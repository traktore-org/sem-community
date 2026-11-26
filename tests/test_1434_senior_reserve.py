"""(#1434) An idle senior load holds back only sun it can start with.

Found live on the .175 rig (26.11): a heat pump at the top of the device list,
in Surplus mode, rated 2.0 kW and idle, reserved all 900 W of spare sun. It can
never start on 900 W, so it stayed off, every junior (a car in Sun + tariff
among them) saw 0 W, and the sun was exported.
"""
from types import SimpleNamespace
from datetime import datetime

from custom_components.solar_energy_management.coordinator.surplus_controller import (
    surplus_reserved_w,
)


def _senior(priority=1, *, rated=2000.0, min_w=0.0, active=False,
            dwell=None, name="hp"):
    return SimpleNamespace(
        device_id=name, name=name, priority=priority, is_active=active,
        battery_assist_enabled=False, battery_eligible_overnight=False,
        rated_power=rated, min_power_threshold=min_w, _tier1_batt_w=0.0,
        control_mode="surplus", daily_max_runtime_reached=False,
        _external_off_until=None, _surplus_since=dwell,
        can_activate=lambda: (_ for _ in ()).throw(AssertionError("no")),
    )


def _reserve(devices, available, below=8):
    return surplus_reserved_w(devices, below_priority=below, available_w=available)


def test_the_rig_case_reserves_nothing():
    """Heat pump needs 2000 W to start, 900 W is spare: hold back nothing."""
    assert _reserve([_senior(rated=2000.0)], 900.0) == 0.0


def test_enough_to_start_still_reserves():
    assert _reserve([_senior(rated=2000.0)], 2500.0) == 2000.0


def test_just_at_the_threshold_reserves():
    assert _reserve([_senior(rated=2000.0)], 2000.0) == 2000.0


def test_the_start_threshold_wins_over_the_rating():
    """A modulating load that starts at 800 W reserves on 900 W of sun."""
    assert _reserve([_senior(rated=2000.0, min_w=800.0)], 900.0) == 900.0


def test_a_running_senior_still_reserves_nothing_on_the_solar_axis():
    assert _reserve([_senior(rated=2000.0, active=True)], 900.0) == 0.0


def test_a_senior_waiting_on_its_start_delay_keeps_its_claim():
    """The reservation exists to protect a senior about to start: one whose
    sustained-surplus clock already runs keeps its claim, so a junior cannot
    take the sun during the senior's debounce."""
    assert _reserve([_senior(rated=2000.0, dwell=datetime.now())], 900.0) == 900.0


def test_two_seniors_each_judged_on_what_is_left():
    small = _senior(priority=1, rated=600.0, name="plug")
    big = _senior(priority=2, rated=2000.0, name="hp")
    # 600 W reserved for the plug; 300 W left cannot start the heat pump.
    assert _reserve([small, big], 900.0) == 600.0
    # Plenty: both reserve.
    assert _reserve([small, big], 3000.0) == 2600.0


def test_flapping_around_the_threshold_is_monotonic():
    """More sun never means less for the senior: the reservation does not
    jump back and forth between two values while the sun only grows."""
    seen = [_reserve([_senior(rated=2000.0)], w) for w in range(1500, 2600, 50)]
    for a, b in zip(seen, seen[1:], strict=False):
        assert b >= a
