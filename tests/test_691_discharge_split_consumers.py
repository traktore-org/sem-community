"""#691 — the LIMIT_DISCHARGE home split must divide by budget CONSUMERS.

Live report (onkelfu, SolarEdge, 2 configured batteries, one mode=off):
home ≈1 kW at night → the clamp wrote home/2 = 500 W to the ONE battery
SEM controls, and the grid imported the other half all evening.

Two defects, one class (the divisor answered "how many rows are
configured", execution asks "how many units receive this clamp"):

1. a ``mode=off`` battery is hands-off — ``decide_battery`` short-
   circuits to OFF before any command — yet it still sat in the divisor;
2. batteries sharing ONE discharge-limit control entity (SolarEdge's
   inverter-level Storage Discharge Limit; any install without
   per-battery ``battery_discharge_control_entities``) are a single
   actuation surface — one write governs the bank — yet each counted.

Plus the startup-restore gap the reporter surfaced: only the GLOBAL
discharge entity was restored to max after a restart, never the
per-battery ones.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.decide_battery import (
    effective_battery_count,
)
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    restore_discharge_limit_on_startup,
)


# ---------------------------------------------------------------------------
# effective_battery_count — the divisor
# ---------------------------------------------------------------------------

def _pbc(mode="auto", ent=None):
    cfg = {"battery_mode": mode}
    if ent is not None:
        cfg["battery_discharge_control_entity"] = ent
    return cfg


class TestEffectiveBatteryCount:
    def test_two_controlled_distinct_entities_keep_the_531_split(self):
        assert effective_battery_count(
            [_pbc(ent="number.b1_limit"), _pbc(ent="number.b2_limit")]
        ) == 2

    def test_an_off_battery_does_not_eat_a_share(self):
        """The #691 repro: 2 configured, 1 off → divisor 1, the
        controlled battery gets the FULL home budget."""
        assert effective_battery_count(
            [_pbc(ent="number.b1_limit"), _pbc(mode="off", ent="number.b2_limit")]
        ) == 1

    def test_shared_control_entity_is_one_consumer(self):
        """Both units fall back to the same global discharge-limit
        entity (SolarEdge single inverter-level control) — one write
        governs the bank, so together they are ONE consumer."""
        assert effective_battery_count(
            [_pbc(ent="number.se_storage_limit"), _pbc(ent="number.se_storage_limit")]
        ) == 1

    def test_no_entities_keep_todays_per_unit_split(self):
        """Unknown actuation surfaces (no discharge-limit entity at
        all) count individually — no behaviour change for installs
        without discharge control."""
        assert effective_battery_count([_pbc(), _pbc()]) == 2

    def test_mixed_fleet(self):
        """3 batteries: one off, two sharing one entity → 1."""
        assert effective_battery_count([
            _pbc(mode="off"),
            _pbc(ent="number.shared"),
            _pbc(ent="number.shared"),
        ]) == 1

    def test_mode_is_case_insensitive(self):
        assert effective_battery_count(
            [_pbc(mode="Off", ent="number.a"), _pbc(ent="number.b")]
        ) == 1

    def test_all_off_returns_at_least_one(self):
        """Divisor floor: never 0 (decide_battery divides by it)."""
        assert effective_battery_count([_pbc(mode="off"), _pbc(mode="off")]) == 1

    def test_empty_fleet_returns_one(self):
        assert effective_battery_count([]) == 1

    def test_the_reporters_arithmetic(self):
        """1 kW home, 2 configured, 1 off: the clamp must be the full
        1000 W, not the 500 W that left half the load on the meter."""
        n = effective_battery_count(
            [_pbc(ent="number.se_limit"), _pbc(mode="off")]
        )
        assert 1000.0 / n == 1000.0


# ---------------------------------------------------------------------------
# Coordinator wiring pin — the helper must actually feed FleetContext
# ---------------------------------------------------------------------------

def test_coordinator_wires_the_effective_count():
    """The pure helper is worthless if the coordinator still counts
    configured rows. Source pin: FleetContext.battery_count comes from
    ``effective_battery_count`` over the per-battery configs, and the
    old ``len(power.batteries)`` computation is gone."""
    src = (Path(__file__).resolve().parent.parent
           / "coordinator" / "coordinator.py").read_text()
    assert "effective_battery_count(" in src
    assert "battery_count=_eff_battery_count" in src
    assert 'battery_count=max(1, len(getattr(power, "batteries"' not in src


# ---------------------------------------------------------------------------
# Startup restore covers per-battery entities too
# ---------------------------------------------------------------------------

def _hass_with_limits(states: dict):
    hass = MagicMock()
    hass.states.get = lambda ent: (
        MagicMock(state=str(states[ent])) if ent in states else None
    )
    hass.services.async_call = AsyncMock()
    return hass


class TestStartupRestorePerBattery:
    @pytest.mark.asyncio
    async def test_per_battery_entities_are_restored(self):
        """A stale 500 W limit on a per-battery entity must be pushed
        back to max on startup — the old code only handled the global
        key."""
        hass = _hass_with_limits({
            "number.b1_limit": 500.0,
            "number.b2_limit": 4800.0,
        })
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entities": [
                "number.b1_limit", "number.b2_limit",
            ],
            "battery_max_discharge_power": 5000,
        })
        calls = hass.services.async_call.await_args_list
        restored = {c.args[2]["entity_id"]: c.args[2]["value"] for c in calls}
        assert restored == {
            "number.b1_limit": 5000,
            "number.b2_limit": 5000,
        }

    @pytest.mark.asyncio
    async def test_global_and_per_battery_deduplicated(self):
        """Global key + per-battery list naming the same entity → ONE
        restore write, not two."""
        hass = _hass_with_limits({"number.shared_limit": 300.0})
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entity": "number.shared_limit",
            "battery_discharge_control_entities": ["number.shared_limit"],
            "battery_max_discharge_power": 5000,
        })
        assert hass.services.async_call.await_count == 1

    @pytest.mark.asyncio
    async def test_at_max_entities_are_left_alone(self):
        hass = _hass_with_limits({"number.b1_limit": 5000.0})
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entities": ["number.b1_limit"],
            "battery_max_discharge_power": 5000,
        })
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_no_entities_configured_is_a_noop(self):
        hass = _hass_with_limits({})
        await restore_discharge_limit_on_startup(
            hass, {"battery_max_discharge_power": 5000},
        )
        hass.services.async_call.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_unavailable_entity_does_not_block_the_others(self):
        """One missing entity (integration still loading) must not stop
        the rest of the fleet from being restored."""
        hass = _hass_with_limits({"number.b2_limit": 100.0})
        await restore_discharge_limit_on_startup(hass, {
            "battery_discharge_control_entities": [
                "number.gone", "number.b2_limit",
            ],
            "battery_max_discharge_power": 5000,
        })
        calls = hass.services.async_call.await_args_list
        assert len(calls) == 1
        assert calls[0].args[2]["entity_id"] == "number.b2_limit"
