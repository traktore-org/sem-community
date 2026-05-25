"""Tests for Min/Max EV charge-target range (#245, Phase 1 of #239).

Covers the floor (Min) vs ceiling (Max) decoupling in _calculate_remaining_need:
- Max reuses the legacy single-value key (daily_ev_target / ev_target_soc), so
  pre-#245 installs are unchanged (the migration-free / identity guarantee).
- Min is the new *_min key (default 0). When Min is 0/unset the floor follows Max,
  so night charging still tops up to the single target.
- Min is clamped to <= Max.
- Floor drives night top-up; ceiling drives the ev_limit_surplus stop.
- kWh and SOC modes, plus per-charger overrides and global inheritance.
"""
import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


# ──────────────────────────────────────────────
# Helpers (mirror tests/test_ev_target_ux.py)
# ──────────────────────────────────────────────

def _make_coordinator(config=None):
    """Create a minimal SEMCoordinator with __new__ (no HA bus needed)."""
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = config or {
        "ev_target_soc": 80,
        "ev_battery_capacity_kwh": 40,
        "daily_ev_target": 10,
    }
    return coord


def _make_energy(daily_ev=0.0):
    energy = MagicMock()
    energy.daily_ev = daily_ev
    return energy


def _floor(coord, energy, vehicle_soc=None, charger_cfg=None):
    return coord._calculate_remaining_need(
        energy, vehicle_soc=vehicle_soc, charger_cfg=charger_cfg, bound="min"
    )


def _ceiling(coord, energy, vehicle_soc=None, charger_cfg=None):
    return coord._calculate_remaining_need(
        energy, vehicle_soc=vehicle_soc, charger_cfg=charger_cfg, bound="max"
    )


# ──────────────────────────────────────────────
# Backward-compat / migration-free identity guarantee
# ──────────────────────────────────────────────

class TestPreExistingBehaviourUnchanged:
    """With no *_min keys, floor == ceiling == old single-target behaviour."""

    def test_kwh_default_bound_is_max(self):
        coord = _make_coordinator({"daily_ev_target": 10})
        energy = _make_energy(daily_ev=3.0)
        # Default bound="max" matches the historical single-value result.
        assert coord._calculate_remaining_need(energy) == pytest.approx(7.0)

    def test_kwh_floor_follows_max_when_no_min(self):
        coord = _make_coordinator({"daily_ev_target": 10})
        energy = _make_energy(daily_ev=3.0)
        assert _floor(coord, energy) == pytest.approx(7.0)
        assert _ceiling(coord, energy) == pytest.approx(7.0)

    def test_kwh_floor_follows_max_when_min_zero(self):
        coord = _make_coordinator({"daily_ev_target": 10, "daily_ev_target_min": 0})
        energy = _make_energy(daily_ev=4.0)
        assert _floor(coord, energy) == pytest.approx(6.0)

    def test_soc_floor_follows_max_when_no_min(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        assert _floor(coord, energy, vehicle_soc=60.0) == pytest.approx(8.0)
        assert _ceiling(coord, energy, vehicle_soc=60.0) == pytest.approx(8.0)


# ──────────────────────────────────────────────
# kWh range: floor (Min) vs ceiling (Max)
# ──────────────────────────────────────────────

class TestKwhRange:

    def test_floor_and_ceiling_decoupled(self):
        coord = _make_coordinator({
            "daily_ev_target": 50, "daily_ev_target_min": 20,
        })
        energy = _make_energy(daily_ev=0.0)
        assert _floor(coord, energy) == pytest.approx(20.0)
        assert _ceiling(coord, energy) == pytest.approx(50.0)

    def test_remaining_subtracts_delivered_for_both_bounds(self):
        coord = _make_coordinator({
            "daily_ev_target": 50, "daily_ev_target_min": 20,
        })
        energy = _make_energy(daily_ev=5.0)
        assert _floor(coord, energy) == pytest.approx(15.0)   # 20 - 5
        assert _ceiling(coord, energy) == pytest.approx(45.0)  # 50 - 5

    def test_floor_satisfied_while_ceiling_open(self):
        """Daily > Min but < Max: night floor met (0), surplus still has room."""
        coord = _make_coordinator({
            "daily_ev_target": 50, "daily_ev_target_min": 20,
        })
        energy = _make_energy(daily_ev=25.0)
        assert _floor(coord, energy) == 0.0           # already above Min → no night charge
        assert _ceiling(coord, energy) == pytest.approx(25.0)  # surplus may add up to 25 more

    def test_min_clamped_to_max(self):
        """Misconfigured Min > Max is clamped to Max."""
        coord = _make_coordinator({
            "daily_ev_target": 30, "daily_ev_target_min": 60,
        })
        energy = _make_energy(daily_ev=0.0)
        assert _floor(coord, energy) == pytest.approx(30.0)
        assert _ceiling(coord, energy) == pytest.approx(30.0)


# ──────────────────────────────────────────────
# SOC range: floor (Min) vs ceiling (Max)
# ──────────────────────────────────────────────

class TestSocRange:

    def test_soc_floor_and_ceiling_decoupled(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80, "ev_target_soc_min": 50,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        # floor: (50-40)/100*40 = 4.0 ; ceiling: (80-40)/100*40 = 16.0
        assert _floor(coord, energy, vehicle_soc=40.0) == pytest.approx(4.0)
        assert _ceiling(coord, energy, vehicle_soc=40.0) == pytest.approx(16.0)

    def test_soc_floor_met_ceiling_open(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80, "ev_target_soc_min": 50,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        # SOC 55% > Min 50% → floor 0; ceiling (80-55)/100*40 = 10.0
        assert _floor(coord, energy, vehicle_soc=55.0) == 0.0
        assert _ceiling(coord, energy, vehicle_soc=55.0) == pytest.approx(10.0)

    def test_soc_min_clamped_to_max(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80, "ev_target_soc_min": 90,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        assert _floor(coord, energy, vehicle_soc=40.0) == pytest.approx(16.0)  # clamped to 80

    def test_soc_min_ignored_without_sensor_falls_back_to_kwh(self):
        """SOC mode with no vehicle_soc uses kWh target for both bounds."""
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80, "ev_target_soc_min": 50,
            "daily_ev_target": 10, "daily_ev_target_min": 4,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy(daily_ev=2.0)
        assert _floor(coord, energy, vehicle_soc=None) == pytest.approx(2.0)   # 4 - 2 (kWh Min)
        assert _ceiling(coord, energy, vehicle_soc=None) == pytest.approx(8.0)  # 10 - 2 (kWh Max)


# ──────────────────────────────────────────────
# Per-charger overrides and global inheritance
# ──────────────────────────────────────────────

class TestPerChargerRange:

    def test_per_charger_min_overrides_global(self):
        coord = _make_coordinator({
            "daily_ev_target": 50, "daily_ev_target_min": 5,
        })
        energy = _make_energy(daily_ev=0.0)
        cfg = {"id": "ev1", "daily_ev_target": 40, "daily_ev_target_min": 15}
        assert _floor(coord, energy, charger_cfg=cfg) == pytest.approx(15.0)
        assert _ceiling(coord, energy, charger_cfg=cfg) == pytest.approx(40.0)

    def test_per_charger_inherits_global_min_when_unset(self):
        coord = _make_coordinator({
            "daily_ev_target": 50, "daily_ev_target_min": 12,
        })
        energy = _make_energy(daily_ev=0.0)
        cfg = {"id": "ev1", "daily_ev_target": 40}  # no per-charger min
        assert _floor(coord, energy, charger_cfg=cfg) == pytest.approx(12.0)
        assert _ceiling(coord, energy, charger_cfg=cfg) == pytest.approx(40.0)

    def test_per_charger_no_min_anywhere_floor_follows_max(self):
        coord = _make_coordinator({"daily_ev_target": 50})
        energy = _make_energy(daily_ev=0.0)
        cfg = {"id": "ev1", "daily_ev_target": 40}
        assert _floor(coord, energy, charger_cfg=cfg) == pytest.approx(40.0)


# ──────────────────────────────────────────────
# _resolve_target unit behaviour
# ──────────────────────────────────────────────

class TestResolveTarget:

    def test_max_bound_returns_base_key(self):
        coord = _make_coordinator({"daily_ev_target": 22})
        assert coord._resolve_target({}, "daily_ev_target", "max", 10) == 22

    def test_max_bound_uses_default_when_unset(self):
        coord = _make_coordinator({})
        assert coord._resolve_target({}, "daily_ev_target", "max", 10) == 10

    def test_min_bound_falls_back_to_max_when_zero(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_min": 0})
        assert coord._resolve_target({}, "daily_ev_target", "min", 10) == 22

    def test_min_bound_returns_min_when_set(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_min": 8})
        assert coord._resolve_target({}, "daily_ev_target", "min", 10) == 8

    def test_min_bound_clamped_to_max(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_min": 99})
        assert coord._resolve_target({}, "daily_ev_target", "min", 10) == 22

    def test_cfg_takes_precedence_over_config(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_min": 8})
        cfg = {"daily_ev_target": 40, "daily_ev_target_min": 30}
        assert coord._resolve_target(cfg, "daily_ev_target", "min", 10) == 30
        assert coord._resolve_target(cfg, "daily_ev_target", "max", 10) == 40
