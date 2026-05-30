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
          batt_w=0.0, committed_w=0.0):
    """Call the helper with a fake self that reports peak_w as the peak limit.

    These regression tests focus on the **legacy** ``home_consumption_power``
    formula (the pre-#288 path that becomes the fallback). To force that
    branch, explicitly stub ``_get_peak_15min_w`` to return None — a bare
    ``Mock`` would auto-generate it as a method returning another Mock,
    which would take the #288 rolling branch and fail the arithmetic.

    The #288 rolling formula has its own dedicated tests in
    ``test_night_peak_rolling.py`` — keep these focused on the legacy
    semantics so the original 2026-05-26 PROD regression is locked in
    even when the rolling sensor isn't available (cold-start window).
    """
    obj = Mock()
    obj._get_peak_limit_w = Mock(return_value=peak_w)
    # #288: pin the legacy fallback path so this test file keeps
    # asserting the home_consumption formula it was written to pin.
    obj._get_peak_15min_w = Mock(return_value=None)
    # Shared night peak budget (#274/H1): watts already committed to
    # higher-priority chargers. A real Mock would auto-create this as a Mock
    # object and break the arithmetic, so set it explicitly.
    obj._night_committed_w = committed_w
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


def test_shared_peak_budget_shrinks_headroom_for_later_chargers():
    """#274/H1: a sibling charger's committed draw reduces this charger's headroom.

    Same house load + peak, but with 4 kW already committed to a higher-priority
    charger the remaining headroom drops, so this charger is sized lower — the
    fleet stays under the shared peak instead of each grabbing the full headroom.
    """
    # 6 kW peak, 0.5 kW home → 5.5 kW headroom → 7A at 690 W/A (no sibling).
    alone = _amps(home_w=500.0, peak_w=6000.0, wpa=690.0, max_a=32)
    # 4 kW committed to a sibling → 1.5 kW headroom → ~2A → clamps to min 6.
    with_sibling = _amps(home_w=500.0, peak_w=6000.0, wpa=690.0, max_a=32,
                         committed_w=4000.0)
    assert with_sibling < alone
    # And two chargers must not each claim the full ~5.5 kW: alone≈8A (5.5kW),
    # second≈2A clamped to 6A min; combined draw stays bounded by peak intent.
    assert with_sibling == 6  # min-clamped, not another ~8A
