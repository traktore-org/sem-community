"""Regression: night-charge peak management must size the EV from the pure
house load, never from ``grid_import - ev_power``.

Live PROD bug (2026-05-26): with a 6kW peak limit the EV ramped to 10kW and grid
import hit ~10kW. Root cause: the night current was derived from
``grid_import_power - ev_power`` which equals ``home + batt_charge -
batt_discharge`` (see PowerReadings.calculate_derived). Battery discharge drove
that term negative and inflated the apparent headroom, so the EV ramped up while
the battery discharged and grid import overshot the peak the moment the battery
backed off.

``_night_peak_managed_amps`` now uses ``home_consumption_power`` (excludes both
EV and battery), so ``grid = home + ev`` stays <= peak regardless of the battery.
"""
from unittest.mock import Mock

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _amps(home_w, peak_w, wpa, *, min_a=6, max_a=16, ev_w=0.0, grid_w=0.0,
          batt_w=0.0):
    """Call the helper with a fake self that reports peak_w as the peak limit."""
    obj = Mock()
    obj._get_peak_limit_w = Mock(return_value=peak_w)
    p = PowerReadings()
    p.home_consumption_power = home_w
    p.ev_power = ev_w
    p.grid_import_power = grid_w
    p.battery_power = batt_w
    return EVControlMixin._night_peak_managed_amps(obj, p, wpa, min_a, max_a)


def test_target_uses_home_not_grid_minus_ev():
    """THE regression guard: battery discharge must not inflate the target.

    Scenario mirrors the PROD trace — EV pulling 10kW, battery covering 2.5kW so
    grid_import is 7.5kW (``grid - ev = -2500``), home only 0.5kW, 6kW peak.
    """
    amps = _amps(home_w=500.0, peak_w=6000.0, wpa=690.0,
                 ev_w=10000.0, grid_w=7500.0, batt_w=-2500.0)
    # home-based: (6000 - 500) / 690 = 7.97 -> 8A  (~5.5kW, grid stays <= peak)
    assert amps == 8
    # the OLD grid-minus-ev formula would give (6000 - (-2500)) / 690 = 12.3 ->
    # 12A (~8.3kW) and blow past the peak. Must NOT happen.
    assert amps != 12


def test_low_home_leaves_most_headroom():
    # 0.5kW home, 6kW peak -> ~5.5kW for the EV -> 8A at 690 W/A
    assert _amps(home_w=500.0, peak_w=6000.0, wpa=690.0) == 8


def test_high_home_clamps_to_min():
    # House already at/over the peak -> no headroom -> clamp to the min current
    assert _amps(home_w=6000.0, peak_w=6000.0, wpa=690.0, min_a=6) == 6
    assert _amps(home_w=9000.0, peak_w=6000.0, wpa=690.0, min_a=6) == 6


def test_clamps_to_max():
    # Huge headroom must not exceed the charger's max current
    assert _amps(home_w=0.0, peak_w=22000.0, wpa=690.0, max_a=16) == 16


def test_single_phase_estimate_yields_fewer_amps():
    """Kickstart uses est. W/A = phases*voltage; 1-phase (230) allows more amps
    of headroom for the same watts than 3-phase (690)."""
    three_phase = _amps(home_w=500.0, peak_w=6000.0, wpa=3 * 230.0)
    one_phase = _amps(home_w=500.0, peak_w=6000.0, wpa=1 * 230.0, max_a=32)
    # same ~5.5kW headroom: 3-phase -> 8A, 1-phase -> 24A
    assert three_phase == 8
    assert one_phase == 24


def test_battery_state_never_changes_result():
    """The result must be identical whether the battery is idle, charging, or
    discharging, for a fixed home load + peak + W/A."""
    base = _amps(home_w=700.0, peak_w=6000.0, wpa=690.0, batt_w=0.0)
    discharging = _amps(home_w=700.0, peak_w=6000.0, wpa=690.0, batt_w=-3000.0,
                        grid_w=2000.0, ev_w=5000.0)
    charging = _amps(home_w=700.0, peak_w=6000.0, wpa=690.0, batt_w=3000.0,
                     grid_w=8000.0, ev_w=5000.0)
    assert base == discharging == charging
