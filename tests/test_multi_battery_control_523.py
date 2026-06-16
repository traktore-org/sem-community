"""#523 multi-battery control — per-battery control entities.

RienduPre runs 2 batteries; SEM sensed both but controlled with single
global entities, so only one could sell to grid. ``_per_battery_config``
overlays per-battery control entities (force-discharge / discharge-limit)
from list keys, indexed like the Energy-Dashboard battery_power_list.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _cfg(coordinator_config):
    """Call the unbound method with a minimal fake self (uses only
    ``self.config``)."""
    fake = SimpleNamespace(config=coordinator_config)
    return SEMCoordinator._per_battery_config(fake, _cfg.idx)


_cfg.idx = 0


def _per(config, idx):
    fake = SimpleNamespace(config=config)
    return SEMCoordinator._per_battery_config(fake, idx)


def test_no_lists_falls_back_to_global():
    cfg = {
        "battery_force_discharge_control_entity": "number.global_sell",
        "battery_discharge_control_entity": "number.global_limit",
    }
    # No list keys → the same config object is returned (no overlay).
    assert _per(cfg, 0) is cfg
    assert _per(cfg, 1) is cfg


def test_per_battery_force_discharge_entities():
    cfg = {
        "battery_force_discharge_entities": ["number.b1_sell", "number.b2_sell"],
        "battery_force_discharge_control_entity": "number.global_sell",
    }
    assert _per(cfg, 0)["battery_force_discharge_control_entity"] == "number.b1_sell"
    assert _per(cfg, 1)["battery_force_discharge_control_entity"] == "number.b2_sell"


def test_per_battery_discharge_limit_entities():
    cfg = {
        "battery_discharge_control_entities": ["number.b1_limit", "number.b2_limit"],
    }
    assert _per(cfg, 0)["battery_discharge_control_entity"] == "number.b1_limit"
    assert _per(cfg, 1)["battery_discharge_control_entity"] == "number.b2_limit"


def test_missing_or_empty_list_entry_falls_back():
    cfg = {
        "battery_force_discharge_entities": ["number.b1_sell", ""],  # b2 empty
        "battery_force_discharge_control_entity": "number.global_sell",
    }
    # b2 (empty entry) keeps the global entity; b1 gets its own.
    assert _per(cfg, 0)["battery_force_discharge_control_entity"] == "number.b1_sell"
    assert _per(cfg, 1)["battery_force_discharge_control_entity"] == "number.global_sell"
    # idx beyond the list → global
    assert _per(cfg, 5)["battery_force_discharge_control_entity"] == "number.global_sell"


def test_global_config_not_mutated():
    cfg = {
        "battery_force_discharge_entities": ["number.b1_sell"],
        "battery_force_discharge_control_entity": "number.global_sell",
    }
    _per(cfg, 0)
    # The overlay must be a copy — the shared global config is untouched.
    assert cfg["battery_force_discharge_control_entity"] == "number.global_sell"


def test_per_battery_mode_and_reserve_overlay():
    # #523 Increment 2: mode + reserve lists overlay to single keys.
    cfg = {
        "battery_modes": ["self_consumption", "allow_arbitrage"],
        "battery_reserve_socs": [30, 45],
    }
    assert _per(cfg, 0)["battery_mode"] == "self_consumption"
    assert _per(cfg, 0)["battery_reserve_soc"] == 30
    assert _per(cfg, 1)["battery_mode"] == "allow_arbitrage"
    assert _per(cfg, 1)["battery_reserve_soc"] == 45


def test_per_battery_mode_absent_falls_back():
    cfg = {"battery_modes": ["force_charge"]}  # only b1 set
    assert _per(cfg, 0)["battery_mode"] == "force_charge"
    # b2 beyond the list → no battery_mode key (decide_battery defaults to auto)
    assert "battery_mode" not in _per(cfg, 1)
