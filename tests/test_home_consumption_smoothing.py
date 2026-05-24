"""Tests for transient home-consumption dip smoothing (#237).

The energy balance clamps home_consumption_power to 0 when instantaneous sensor
readings momentarily lag a large load. _smooth_home_consumption() holds the last
positive value through brief dips, but reports a sustained zero as real.
"""
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator


def _coord():
    return SEMCoordinator.__new__(SEMCoordinator)


def _p(home):
    return SimpleNamespace(home_consumption_power=home)


def test_positive_value_passes_through_and_is_remembered():
    coord = _coord()
    p = _p(900.0)
    coord._smooth_home_consumption(p)
    assert p.home_consumption_power == 900.0
    assert coord._last_home_consumption == 900.0


def test_single_cycle_dip_holds_last_value():
    coord = _coord()
    coord._smooth_home_consumption(_p(900.0))   # establish last
    dip = _p(0.0)
    coord._smooth_home_consumption(dip)
    assert dip.home_consumption_power == 900.0   # held, not 0


def test_hold_capped_at_max_cycles_then_reports_zero():
    coord = _coord()
    coord._smooth_home_consumption(_p(800.0))
    # Dips: first HOME_HOLD_MAX_CYCLES are held, the next is reported as real 0
    held = []
    for _ in range(SEMCoordinator.HOME_HOLD_MAX_CYCLES + 1):
        d = _p(0.0)
        coord._smooth_home_consumption(d)
        held.append(d.home_consumption_power)
    assert held[:SEMCoordinator.HOME_HOLD_MAX_CYCLES] == [800.0] * SEMCoordinator.HOME_HOLD_MAX_CYCLES
    assert held[-1] == 0.0  # sustained zero is real


def test_recovery_resets_hold():
    coord = _coord()
    coord._smooth_home_consumption(_p(700.0))
    coord._smooth_home_consumption(_p(0.0))      # 1 held
    coord._smooth_home_consumption(_p(1200.0))   # recovers
    assert coord._home_hold_count == 0
    # A subsequent dip is held again from the fresh value
    d = _p(0.0)
    coord._smooth_home_consumption(d)
    assert d.home_consumption_power == 1200.0


def test_zero_with_no_prior_value_stays_zero():
    coord = _coord()
    d = _p(0.0)
    coord._smooth_home_consumption(d)
    assert d.home_consumption_power == 0.0  # nothing to hold
