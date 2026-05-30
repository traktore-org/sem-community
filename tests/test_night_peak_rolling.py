"""Unit tests for the night peak-managed throttle's #288 fix.

Pre-#288, ``_night_peak_managed_amps`` sized EV current from the
*derived* ``power.home_consumption_power`` — sensor-lag-sensitive,
computed from ``solar + grid_import + batt_discharge − ev_power −
grid_export − batt_charge``. When any input lagged (the EV-power
sensor lagging by 5 kW was the smoking gun observed on PROD
2026-05-29), the derived home value was wildly wrong and the
throttle made decisions on bad inputs.

Post-#288, the formula reads from the load manager's
``consecutive_peak_15min`` — the same 15-min rolling grid-import
average most demand-charge tariffs bill on. Self-balancing: the
rolling already includes EV's draw, so as EV ramps the rolling
rises and headroom shrinks naturally.

Tests pin four corners (the issue's test plan):
  1. ``peak_15min_w << peak_limit_w`` → headroom > 0 → returns
     budget-limited (here clamped to ``max_amps``)
  2. ``peak_15min_w ≈ peak_limit_w`` → headroom near 0 → returns
     ``min_amps``
  3. ``peak_15min_w > peak_limit_w`` → headroom < 0 → returns
     ``min_amps`` (clamp floor)
  4. Load manager unavailable or sensor unparseable → falls back
     to the legacy ``home_consumption_power`` formula
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _build_coord(peak_15min_kw=None, target_peak_limit_kw=6.0):
    """Build a minimal SEMCoordinator stub focused on
    ``_night_peak_managed_amps`` and ``_get_peak_15min_w``.
    """
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)

    coord.config = {"target_peak_limit": target_peak_limit_kw}

    if peak_15min_kw is None:
        coord._load_manager = None
    else:
        lm = MagicMock()
        lm.get_load_management_data = MagicMock(return_value={
            "target_peak_limit": target_peak_limit_kw,
            "consecutive_peak_15min": peak_15min_kw,
        })
        coord._load_manager = lm

    # _night_committed_w defaults to 0 if not set.
    return coord


def _power(home_w=0.0):
    """Power readings stub — only home_consumption_power is read by
    the fallback path; everything else is irrelevant for these tests."""
    p = PowerReadings(
        solar_power=0.0, home_consumption_power=home_w, battery_power=0.0,
        battery_soc=80.0, ev_power=0.0, ev_connected=True, grid_power=0.0,
    )
    return p


# ──────────────────────────────────────────────────────────────────────
# Corner 1: rolling << peak_limit → large headroom → max_amps
# ──────────────────────────────────────────────────────────────────────

class TestRollingWellUnderLimit:
    def test_rolling_1kw_limit_6kw_returns_max_amps(self):
        """rolling 1 kW vs 6 kW limit → headroom 5 kW → 7 amps. Clamped
        to max_amps if smaller. Watts/amp = 230*3 = 690."""
        coord = _build_coord(peak_15min_kw=1.0, target_peak_limit_kw=6.0)
        result = coord._night_peak_managed_amps(
            power=_power(home_w=999_999),  # legacy fallback would clamp; we want to prove rolling wins
            watts_per_amp=690.0, min_amps=6, max_amps=16,
        )
        # headroom = 6000 - 1000 - 0 = 5000 → 5000/690 = 7.25 → round to 7
        # but clamped to max_amps if max < 7.
        assert result == 7, f"expected 7 A from rolling formula, got {result}"


# ──────────────────────────────────────────────────────────────────────
# Corner 2: rolling ≈ peak_limit → headroom near 0 → min_amps floor
# ──────────────────────────────────────────────────────────────────────

class TestRollingNearLimit:
    def test_rolling_at_limit_returns_min_amps(self):
        """rolling = limit → headroom = 0 → 0 A → clamped to min_amps."""
        coord = _build_coord(peak_15min_kw=6.0, target_peak_limit_kw=6.0)
        result = coord._night_peak_managed_amps(
            power=_power(home_w=0),
            watts_per_amp=690.0, min_amps=6, max_amps=16,
        )
        assert result == 6, "expected min_amps clamp when headroom = 0"


# ──────────────────────────────────────────────────────────────────────
# Corner 3: rolling > peak_limit → negative headroom → min_amps clamp
# ──────────────────────────────────────────────────────────────────────

class TestRollingOverLimit:
    def test_rolling_exceeds_limit_returns_min_amps(self):
        """rolling 8 kW vs 6 kW limit → headroom -2 kW → negative amps →
        clamped to min_amps. (We can't STOP charging from this primitive;
        the strategy / state machine is the right layer for "stop the
        session". Here we just refuse to over-allocate beyond the min.)"""
        coord = _build_coord(peak_15min_kw=8.0, target_peak_limit_kw=6.0)
        result = coord._night_peak_managed_amps(
            power=_power(home_w=0),
            watts_per_amp=690.0, min_amps=6, max_amps=16,
        )
        assert result == 6, (
            f"expected min_amps clamp when rolling exceeds limit, got {result}"
        )


# ──────────────────────────────────────────────────────────────────────
# Corner 4: rolling unavailable → fall back to legacy formula
# ──────────────────────────────────────────────────────────────────────

class TestRollingUnavailableFallback:
    def test_no_load_manager_falls_back_to_home_consumption(self):
        """Cold-start window: load manager hasn't been initialized yet
        (or hasn't accumulated samples). Formula must fall back to the
        pre-#288 ``peak_limit - home_consumption`` so we never end up
        without ANY peak protection."""
        coord = _build_coord(peak_15min_kw=None)  # _load_manager=None
        # home=2 kW, limit=6 kW → headroom = 4 kW → 4000/690 = 5.8 → 6 A
        result = coord._night_peak_managed_amps(
            power=_power(home_w=2000.0),
            watts_per_amp=690.0, min_amps=6, max_amps=16,
        )
        assert result == 6, (
            f"legacy fallback should compute headroom from home_consumption_power; "
            f"got {result}"
        )

    def test_load_manager_returns_none_falls_back(self):
        """Load manager is set but returns None for the rolling (cold
        start with 0 samples)."""
        coord = _build_coord(peak_15min_kw=None, target_peak_limit_kw=6.0)
        lm = MagicMock()
        lm.get_load_management_data = MagicMock(return_value={
            "target_peak_limit": 6.0,
            "consecutive_peak_15min": None,
        })
        coord._load_manager = lm

        result = coord._night_peak_managed_amps(
            power=_power(home_w=2000.0),
            watts_per_amp=690.0, min_amps=6, max_amps=16,
        )
        # Falls back to home_consumption path: 6000-2000=4000 W → 6 A
        assert result == 6


# ──────────────────────────────────────────────────────────────────────
# Multi-charger committed_w subtraction — must still work post-#288
# ──────────────────────────────────────────────────────────────────────

class TestCommittedSubtraction:
    def test_committed_w_reduces_headroom(self):
        """The #274/H1 fleet-sharing semantic: higher-priority chargers'
        committed draw must subtract from the headroom this charger sees."""
        coord = _build_coord(peak_15min_kw=1.0, target_peak_limit_kw=6.0)
        coord._night_committed_w = 3000.0  # 3 kW already committed elsewhere

        result = coord._night_peak_managed_amps(
            power=_power(home_w=0),
            watts_per_amp=690.0, min_amps=6, max_amps=16,
        )
        # headroom = 6000 - 1000 (rolling) - 3000 (committed) = 2000 W → 2.9 A → 3 A
        # clamped to min_amps=6
        assert result == 6, (
            f"committed_w should shrink headroom; expected min_amps clamp, got {result}"
        )
