"""#1234 — a residual clamp of 1 % of a 10 kW EV session is meter noise.

Two meters (wallbox and P1) never agree to the watt. The health check named
58-100 W clamps "stale or inverted sensor" while the EV drew 10 kW. The
tolerance is 50 W or 2 % of the largest demand term, whichever is larger; a
real sign error (thousands of watts) still fires.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


def _ev_session(*, solar, import_w, ev):
    p = PowerReadings()
    p.solar_power = solar
    p.grid_power = -import_w          # + = export, − = import
    p.ev_power = ev
    p.calculate_derived()
    return p


@pytest.mark.parametrize("import_w, ev, clamp", [
    (10103.0, 10256.0, 100.0),
    (10139.0, 10238.0, 92.0),
    (10277.0, 10335.0, 58.0),
])
def test_meter_noise_on_a_big_ev_session_is_quiet(import_w, ev, clamp):
    p = _ev_session(solar=ev - import_w - clamp, import_w=import_w, ev=ev)
    assert p.home_residual_clamped_w == pytest.approx(clamp)
    assert HealthCheck().check_power_balance(p) == []


def test_a_small_clamp_on_a_small_load_still_fires():
    p = _ev_session(solar=0.0, import_w=1000.0, ev=1100.0)
    assert p.home_residual_clamped_w == pytest.approx(100.0)
    assert HealthCheck().check_power_balance(p) != []


def test_a_real_sign_error_on_a_big_session_still_fires():
    p = _ev_session(solar=53.0, import_w=6000.0, ev=10256.0)
    violations = HealthCheck().check_power_balance(p)
    assert any("residual clamped" in v for v in violations), violations


def test_the_floor_is_still_fifty_watts():
    p = _ev_session(solar=0.0, import_w=1000.0, ev=1040.0)
    assert HealthCheck().check_power_balance(p) == []
