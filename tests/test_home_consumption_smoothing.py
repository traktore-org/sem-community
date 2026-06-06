"""Tests for transient home-consumption dip smoothing (#237, #444).

The energy balance clamps ``home_consumption_power`` to 0 when instantaneous sensor
readings momentarily lag a large load. ``_smooth_home_consumption()`` uses a
two-tier hold:

  * Transient hold (HOME_HOLD_MAX_CYCLES) when raw balance ≈ 0
  * Inconsistency hold (HOME_HOLD_INCONSISTENT_MAX) when raw balance is strongly
    negative — guaranteed-stale-sensor signal

Validated against a 2026-06-06 PROD recording: drops the zero-clamp rate from
37 % (single-tier 2-cycle baseline) to 3 % during active EV charging at variable
solar.
"""
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator


def _coord():
    return SEMCoordinator.__new__(SEMCoordinator)


def _p(home, solar=0.0, grid_import=0.0, grid_export=0.0,
       batt_charge=0.0, batt_discharge=0.0, ev=0.0):
    """Build a power readings stub. By default raw balance = 0 (transient-tier)."""
    return SimpleNamespace(
        home_consumption_power=home,
        solar_power=solar,
        grid_import_power=grid_import,
        grid_export_power=grid_export,
        battery_charge_power=batt_charge,
        battery_discharge_power=batt_discharge,
        ev_power=ev,
    )


# ── Tier 1: existing transient-zero behaviour preserved ──

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


def test_transient_hold_capped_at_max_cycles_then_reports_zero():
    """Raw balance near zero → transient hold (HOME_HOLD_MAX_CYCLES)."""
    coord = _coord()
    coord._smooth_home_consumption(_p(800.0))
    held = []
    # Pass exactly HOME_HOLD_MAX_CYCLES + 1 dips with raw balance == 0
    # (the default in _p()) so we trigger the transient cap, not the
    # inconsistency cap.
    for _ in range(SEMCoordinator.HOME_HOLD_MAX_CYCLES + 1):
        d = _p(0.0)
        coord._smooth_home_consumption(d)
        held.append(d.home_consumption_power)
    assert held[:SEMCoordinator.HOME_HOLD_MAX_CYCLES] == [800.0] * SEMCoordinator.HOME_HOLD_MAX_CYCLES
    assert held[-1] == 0.0   # sustained zero is real


def test_recovery_resets_hold():
    coord = _coord()
    coord._smooth_home_consumption(_p(700.0))
    coord._smooth_home_consumption(_p(0.0))      # 1 held (transient)
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
    assert d.home_consumption_power == 0.0   # nothing to hold


# ── Tier 2: inconsistency hold for strongly-negative raw balance ──

def test_strongly_negative_raw_balance_uses_inconsistent_hold():
    """When raw balance is strongly negative (sensors disagree), hold longer
    than the transient cap. Reproduces the dominant PROD-recording pattern:
    solar dropped to 4348 W but grid still shows the old 4901 W export →
    raw_in − raw_out = -700 W → guaranteed sensor staleness."""
    coord = _coord()
    coord._smooth_home_consumption(_p(900.0))   # establish last positive

    # Simulate a strongly-negative raw-balance dip 20 cycles long.
    # 20 exceeds HOME_HOLD_MAX_CYCLES (10) but is below
    # HOME_HOLD_INCONSISTENT_MAX (30). Every cycle should remain held.
    for i in range(20):
        d = _p(home=0.0, solar=4348.0, grid_export=4901.0)
        coord._smooth_home_consumption(d)
        assert d.home_consumption_power == 900.0, (
            f"Cycle {i+1}: inconsistent-tier hold should keep value, "
            f"got {d.home_consumption_power}"
        )


def test_inconsistent_hold_eventually_releases():
    """An inconsistency that persists past HOME_HOLD_INCONSISTENT_MAX is finally
    accepted as real."""
    coord = _coord()
    coord._smooth_home_consumption(_p(900.0))

    for i in range(SEMCoordinator.HOME_HOLD_INCONSISTENT_MAX):
        d = _p(home=0.0, solar=4348.0, grid_export=4901.0)
        coord._smooth_home_consumption(d)
        assert d.home_consumption_power == 900.0, f"Cycle {i+1} should hold"

    # The next cycle is past the cap → sustained inconsistency accepted as 0.
    d = _p(home=0.0, solar=4348.0, grid_export=4901.0)
    coord._smooth_home_consumption(d)
    assert d.home_consumption_power == 0.0


def test_mild_negative_raw_balance_uses_transient_hold():
    """Raw balance between SENSOR_INCONSISTENCY_THRESHOLD_W and 0 — call that
    a transient zero and only hold for HOME_HOLD_MAX_CYCLES cycles."""
    coord = _coord()
    coord._smooth_home_consumption(_p(900.0))

    # Build a row where raw_balance = -50 W (above the -100 W threshold).
    # solar 1000, grid_export 1050 → in=1000, out=1050, balance=-50.
    for i in range(SEMCoordinator.HOME_HOLD_MAX_CYCLES):
        d = _p(home=0.0, solar=1000.0, grid_export=1050.0)
        coord._smooth_home_consumption(d)
        assert d.home_consumption_power == 900.0, f"Cycle {i+1} should hold (transient)"

    # The cycle after the transient cap is real zero (NOT inconsistency tier).
    d = _p(home=0.0, solar=1000.0, grid_export=1050.0)
    coord._smooth_home_consumption(d)
    assert d.home_consumption_power == 0.0


def test_inconsistency_tier_recovers_when_balance_returns_to_zero():
    """Mid-hold the inputs catch up: raw balance recovers (becomes positive).
    The hold counter resets via the normal positive-value path."""
    coord = _coord()
    coord._smooth_home_consumption(_p(900.0))

    # Strongly-negative balance for 5 cycles
    for _ in range(5):
        d = _p(home=0.0, solar=4348.0, grid_export=4901.0)
        coord._smooth_home_consumption(d)
        assert d.home_consumption_power == 900.0

    # Sensors agree again → home consumption is positive → counter resets
    coord._smooth_home_consumption(_p(home=600.0, solar=5000.0, grid_export=4400.0))
    assert coord._home_hold_count == 0
    assert coord._last_home_consumption == 600.0
