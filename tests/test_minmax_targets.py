"""Tests for Min/Max EV charge-target range (#245, Phase 1 of #239).

Mapping (per design review on #245): the EXISTING single-value key
(daily_ev_target / ev_target_soc) is the FLOOR (Min) — the grid-guaranteed
amount night charging tops up to. A NEW optional `{key}_max` is the solar
CEILING (Max): surplus may continue past Min up to Max.

This keeps night charging identical to pre-#245 with no migration:
- bound="min" (floor) -> existing key, drives night/grid top-up.
- bound="max" (ceiling) -> {key}_max, defaults to floor when unset, clamped >= floor;
  drives the ev_limit_surplus stop.
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
    """With no *_max keys, floor == ceiling == old single-target behaviour."""

    def test_kwh_default_bound_is_ceiling(self):
        coord = _make_coordinator({"daily_ev_target": 10})
        energy = _make_energy(daily_ev=3.0)
        # Default bound="max"; with no _max it falls back to the single target.
        assert coord._calculate_remaining_need(energy) == pytest.approx(7.0)

    def test_kwh_ceiling_follows_floor_when_no_max(self):
        coord = _make_coordinator({"daily_ev_target": 10})
        energy = _make_energy(daily_ev=3.0)
        assert _floor(coord, energy) == pytest.approx(7.0)
        assert _ceiling(coord, energy) == pytest.approx(7.0)

    def test_soc_ceiling_follows_floor_when_no_max(self):
        coord = _make_coordinator({
            "ev_target_type": "soc", "ev_target_soc": 80,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        assert _floor(coord, energy, vehicle_soc=60.0) == pytest.approx(8.0)
        assert _ceiling(coord, energy, vehicle_soc=60.0) == pytest.approx(8.0)

    def test_night_floor_is_the_existing_target(self):
        """The existing target is the night floor — night behaviour is unchanged."""
        coord = _make_coordinator({"daily_ev_target": 8})
        energy = _make_energy(daily_ev=5.6)
        # Night tops up the existing target (8): 8 - 5.6 = 2.4 remaining.
        assert _floor(coord, energy) == pytest.approx(2.4)


# ──────────────────────────────────────────────
# kWh range: floor (Min = existing) vs ceiling (Max = new _max)
# ──────────────────────────────────────────────

class TestKwhRange:

    def test_floor_and_ceiling_decoupled(self):
        coord = _make_coordinator({
            "daily_ev_target": 20, "daily_ev_target_max": 50,
        })
        energy = _make_energy(daily_ev=0.0)
        assert _floor(coord, energy) == pytest.approx(20.0)
        assert _ceiling(coord, energy) == pytest.approx(50.0)

    def test_remaining_subtracts_delivered_for_both_bounds(self):
        coord = _make_coordinator({
            "daily_ev_target": 20, "daily_ev_target_max": 50,
        })
        energy = _make_energy(daily_ev=5.0)
        assert _floor(coord, energy) == pytest.approx(15.0)   # 20 - 5
        assert _ceiling(coord, energy) == pytest.approx(45.0)  # 50 - 5

    def test_floor_satisfied_while_ceiling_open(self):
        """Daily > Min but < Max: night floor met (0), surplus still has room."""
        coord = _make_coordinator({
            "daily_ev_target": 20, "daily_ev_target_max": 50,
        })
        energy = _make_energy(daily_ev=25.0)
        assert _floor(coord, energy) == 0.0           # already above Min → no night charge
        assert _ceiling(coord, energy) == pytest.approx(25.0)  # surplus may add up to 25 more

    def test_max_clamped_to_min(self):
        """Misconfigured Max < Min is clamped up to Min."""
        coord = _make_coordinator({
            "daily_ev_target": 30, "daily_ev_target_max": 10,
        })
        energy = _make_energy(daily_ev=0.0)
        assert _floor(coord, energy) == pytest.approx(30.0)
        assert _ceiling(coord, energy) == pytest.approx(30.0)


# ──────────────────────────────────────────────
# SOC range: floor (Min = existing) vs ceiling (Max = new _max)
# ──────────────────────────────────────────────

class TestSocRange:

    def test_soc_floor_and_ceiling_decoupled(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 50, "ev_target_soc_max": 80,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        # floor: (50-40)/100*40 = 4.0 ; ceiling: (80-40)/100*40 = 16.0
        assert _floor(coord, energy, vehicle_soc=40.0) == pytest.approx(4.0)
        assert _ceiling(coord, energy, vehicle_soc=40.0) == pytest.approx(16.0)

    def test_soc_floor_met_ceiling_open(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 50, "ev_target_soc_max": 80,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        # SOC 55% > Min 50% → floor 0; ceiling (80-55)/100*40 = 10.0
        assert _floor(coord, energy, vehicle_soc=55.0) == 0.0
        assert _ceiling(coord, energy, vehicle_soc=55.0) == pytest.approx(10.0)

    def test_soc_max_clamped_to_min(self):
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 80, "ev_target_soc_max": 50,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy()
        # ceiling clamped up to 80 → (80-40)/100*40 = 16.0
        assert _ceiling(coord, energy, vehicle_soc=40.0) == pytest.approx(16.0)

    def test_soc_max_ignored_without_sensor_falls_back_to_kwh(self):
        """SOC mode with no vehicle_soc uses kWh targets for both bounds."""
        coord = _make_coordinator({
            "ev_target_type": "soc",
            "ev_target_soc": 50, "ev_target_soc_max": 80,
            "daily_ev_target": 4, "daily_ev_target_max": 10,
            "ev_battery_capacity_kwh": 40,
        })
        energy = _make_energy(daily_ev=2.0)
        assert _floor(coord, energy, vehicle_soc=None) == pytest.approx(2.0)   # 4 - 2 (kWh floor)
        assert _ceiling(coord, energy, vehicle_soc=None) == pytest.approx(8.0)  # 10 - 2 (kWh ceiling)


# ──────────────────────────────────────────────
# Per-charger overrides and global inheritance
# ──────────────────────────────────────────────

class TestPerChargerRange:

    def test_per_charger_max_overrides_global(self):
        coord = _make_coordinator({
            "daily_ev_target": 20, "daily_ev_target_max": 50,
        })
        energy = _make_energy(daily_ev=0.0)
        cfg = {"id": "ev1", "daily_ev_target": 15, "daily_ev_target_max": 40}
        assert _floor(coord, energy, charger_cfg=cfg) == pytest.approx(15.0)
        assert _ceiling(coord, energy, charger_cfg=cfg) == pytest.approx(40.0)

    def test_per_charger_inherits_global_max_when_unset(self):
        coord = _make_coordinator({
            "daily_ev_target": 20, "daily_ev_target_max": 50,
        })
        energy = _make_energy(daily_ev=0.0)
        cfg = {"id": "ev1", "daily_ev_target": 15}  # no per-charger max
        assert _floor(coord, energy, charger_cfg=cfg) == pytest.approx(15.0)
        assert _ceiling(coord, energy, charger_cfg=cfg) == pytest.approx(50.0)

    def test_per_charger_no_max_anywhere_ceiling_follows_floor(self):
        coord = _make_coordinator({"daily_ev_target": 20})
        energy = _make_energy(daily_ev=0.0)
        cfg = {"id": "ev1", "daily_ev_target": 40}
        assert _floor(coord, energy, charger_cfg=cfg) == pytest.approx(40.0)
        assert _ceiling(coord, energy, charger_cfg=cfg) == pytest.approx(40.0)


# ──────────────────────────────────────────────
# _resolve_target unit behaviour
# ──────────────────────────────────────────────

class TestResolveTarget:

    def test_min_bound_returns_base_key(self):
        coord = _make_coordinator({"daily_ev_target": 22})
        assert coord._resolve_target({}, "daily_ev_target", "min", 10) == 22

    def test_min_bound_uses_default_when_unset(self):
        coord = _make_coordinator({})
        assert coord._resolve_target({}, "daily_ev_target", "min", 10) == 10

    def test_max_bound_returns_max_key(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_max": 50})
        assert coord._resolve_target({}, "daily_ev_target", "max", 10) == 50

    def test_max_bound_falls_back_to_floor_when_unset(self):
        coord = _make_coordinator({"daily_ev_target": 22})
        assert coord._resolve_target({}, "daily_ev_target", "max", 10) == 22

    def test_max_bound_clamped_up_to_min(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_max": 5})
        assert coord._resolve_target({}, "daily_ev_target", "max", 10) == 22

    def test_cfg_takes_precedence_over_config(self):
        coord = _make_coordinator({"daily_ev_target": 22, "daily_ev_target_max": 50})
        cfg = {"daily_ev_target": 40, "daily_ev_target_max": 60}
        assert coord._resolve_target(cfg, "daily_ev_target", "min", 10) == 40
        assert coord._resolve_target(cfg, "daily_ev_target", "max", 10) == 60
