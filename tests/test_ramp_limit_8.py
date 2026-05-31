"""Unit tests for ``_apply_ramp_limit`` (#8, v1.6.13).

Closes the long-standing PROD-observed bug: ``_apply_ramp_limit`` used
to short-circuit on ``current < 1`` and return ``target_current``
directly, so a cold-start cycle commanded e.g. 14 A to a KEBA sitting
at 0 A — the charger's ~30 s physical actuator lag then caused a
~4.4 kW grid-import overshoot.

These tests pin the v1.6.13 semantic:

1. Cold start (current=0) → command ``min_current`` (gentle ramp-up).
2. Steady-state ramp UP capped at ``±ramp_rate``.
3. Steady-state ramp DOWN capped at ``±ramp_rate``.
4. Stop-fast (target < 1) → immediate drop to 0, regardless of current.
5. End-to-end: cold start → next-cycle climb → target.

The harness mocks ``EVControlMixin._ev_device`` + ``self.config`` —
only the attributes the method reads. Keeps the fixture small so
unrelated coordinator refactors don't flake these tests.
"""
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)


def _make_mixin(current_setpoint: float, min_current: float = 6.0,
                ramp_rate: int = 2):
    """Build a minimal stub that exposes the surface ``_apply_ramp_limit``
    reads: ``self._ev_device._current_setpoint``,
    ``self._ev_device.min_current``, ``self.config[...]``."""
    mixin = EVControlMixin.__new__(EVControlMixin)
    mixin._ev_device = MagicMock()
    mixin._ev_device._current_setpoint = current_setpoint
    mixin._ev_device.min_current = min_current
    mixin.config = {"ev_ramp_rate_amps": ramp_rate}
    return mixin


class TestColdStart:
    """Cold start (current=0) commands ``min_current``, NOT ``target``.

    This is the load-bearing change in #8 / v1.6.13. Pre-fix the
    method returned ``target_current`` directly on cold start, which
    is what caused KEBA to receive a 14 A command from 0 and overshoot
    during its physical ramp.
    """

    def test_zero_to_high_target_clamps_to_min(self):
        mx = _make_mixin(current_setpoint=0.0)
        out = mx._apply_ramp_limit(target_current=14.0)
        assert out == 6.0  # min_current, not 14

    def test_zero_to_medium_target_clamps_to_min(self):
        mx = _make_mixin(current_setpoint=0.0)
        out = mx._apply_ramp_limit(target_current=8.0)
        assert out == 6.0

    def test_zero_to_target_equal_to_min_lands_at_min(self):
        """Cold start with target already at min — return min."""
        mx = _make_mixin(current_setpoint=0.0)
        out = mx._apply_ramp_limit(target_current=6.0)
        assert out == 6.0

    def test_near_zero_current_treated_as_cold_start(self):
        """``current < 1`` is the cold-start guard (KEBA's handshake
        idle can pop the setpoint to ~0.5 A briefly — treat that as
        cold-start for ramp purposes)."""
        mx = _make_mixin(current_setpoint=0.5)
        out = mx._apply_ramp_limit(target_current=14.0)
        assert out == 6.0


class TestSteadyStateRamp:
    """Once current > 1 the standard ``±ramp_rate`` clamp drives the
    cycle-to-cycle change."""

    def test_ramp_up_by_rate(self):
        mx = _make_mixin(current_setpoint=6.0, ramp_rate=2)
        out = mx._apply_ramp_limit(target_current=14.0)
        assert out == 8.0  # 6 + 2

    def test_ramp_down_by_rate(self):
        mx = _make_mixin(current_setpoint=14.0, ramp_rate=2)
        out = mx._apply_ramp_limit(target_current=6.0)
        assert out == 12.0  # 14 - 2

    def test_target_within_ramp_window_returns_target(self):
        """When the requested change is within ``±ramp_rate`` the
        target itself is returned — no over-/under-shoot."""
        mx = _make_mixin(current_setpoint=10.0, ramp_rate=2)
        out = mx._apply_ramp_limit(target_current=11.0)
        assert out == 11.0


class TestStopFast:
    """The stop-fast branch must stay: ``target < 1`` returns 0
    immediately. Don't gently ramp down to 0 — that would leave KEBA
    pulling power during the disable_delay window."""

    def test_target_zero_returns_zero_from_high_current(self):
        mx = _make_mixin(current_setpoint=14.0)
        out = mx._apply_ramp_limit(target_current=0.0)
        assert out == 0

    def test_target_zero_returns_zero_from_already_zero(self):
        mx = _make_mixin(current_setpoint=0.0)
        out = mx._apply_ramp_limit(target_current=0.0)
        assert out == 0


class TestColdStartSequence:
    """End-to-end multi-cycle ramp: cold start → next cycle climbs by
    ``ramp_rate`` → reaches target. Pins the user-visible behaviour:
    the spike is smaller because the first cycle hands KEBA
    ``min_current`` rather than ``target``."""

    def test_three_cycle_climb_to_target(self):
        # Cycle 1: cold start, target 14 → returns 6 (min_current).
        mx = _make_mixin(current_setpoint=0.0, ramp_rate=2)
        c1 = mx._apply_ramp_limit(14.0)
        assert c1 == 6.0

        # Cycle 2: ev._current_setpoint=6 (committed by actuator); 6 → 8.
        mx._ev_device._current_setpoint = c1
        c2 = mx._apply_ramp_limit(14.0)
        assert c2 == 8.0

        # Cycle 3: 8 → 10.
        mx._ev_device._current_setpoint = c2
        c3 = mx._apply_ramp_limit(14.0)
        assert c3 == 10.0

    def test_custom_ramp_rate_climbs_faster(self):
        mx = _make_mixin(current_setpoint=0.0, ramp_rate=4)
        # Cycle 1: still min_current — cold-start branch is independent
        # of ramp_rate (the ramp is for cycle 2+).
        assert mx._apply_ramp_limit(14.0) == 6.0
        # Cycle 2: 6 → 10 with ramp_rate=4.
        mx._ev_device._current_setpoint = 6.0
        assert mx._apply_ramp_limit(14.0) == 10.0


class TestCustomMinCurrent:
    """``ev.min_current`` is read per call — different chargers may
    have different minimums and the cold-start return must honour
    that. Wallbox Pulsar EU is 6 A; Tesla Wall Connector goes down to
    1 A on some firmware; OpenEVSE config is user-settable."""

    def test_higher_min_current_used(self):
        mx = _make_mixin(current_setpoint=0.0, min_current=10.0)
        assert mx._apply_ramp_limit(14.0) == 10.0

    def test_lower_min_current_used(self):
        mx = _make_mixin(current_setpoint=0.0, min_current=4.0)
        assert mx._apply_ramp_limit(14.0) == 4.0
