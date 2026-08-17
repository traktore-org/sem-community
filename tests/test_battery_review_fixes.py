"""Regression tests for the pre-1.7.3 battery-subsystem review fixes.

Covers the BLOCKER/HIGH findings from the ruflo-core review:
- B1: adapters built ``ChargeCommand`` with wrong kwarg names
  (``charge_power_w`` / ``duration_min`` vs the dataclass's
  ``max_power_w`` / ``duration_minutes``) → TypeError → every forced charge
  silently failed. Plus ``SchedulerDecision`` carried no ``charge_power_w``,
  so a scheduled charge would issue 0 W.
- H3: ``NightChargeSchedule`` had no ``is_active_now`` so
  ``decide_battery._now_in_window`` defaulted to True whenever slots existed,
  force-charging at evaluation time instead of inside the cheapest slot.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    ChargeCommand,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    SchedulerDecision,
    SchedulerState,
)


# ── B1: forced charge builds a VALID ChargeCommand on every adapter ──────

def _hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.data = {}  # huawei_solar NOT loaded → orphan check is skipped
    return h


@pytest.mark.asyncio
@pytest.mark.parametrize("mod,cls,cfg", [
    ("huawei", "HuaweiBatteryAdapter", {"inverter_device_id": "dev1"}),
    ("goodwe", "GoodWeBatteryAdapter", {}),
    ("generic", "GenericBatteryAdapter", {
        "battery_force_charge_switch": "switch.fc",
        "battery_target_soc_entity": "number.soc",
    }),
])
async def test_force_charge_builds_valid_charge_command(mod, cls, cfg):
    import importlib
    Adapter = getattr(importlib.import_module(
        f"custom_components.solar_energy_management.coordinator.battery_adapters.{mod}"), cls)
    a = Adapter(_hass(), cfg)
    a._charge_adapter.start_forced_charge = AsyncMock()
    # The exact call decide_battery → actuate_battery makes for FORCE_CHARGE.
    await a.command_force_charge(target_soc=100.0, charge_power_w=5000, duration_min=240)
    a._charge_adapter.start_forced_charge.assert_awaited_once()
    cmd = a._charge_adapter.start_forced_charge.await_args.args[0]
    assert isinstance(cmd, ChargeCommand)
    assert cmd.target_soc == 100.0
    assert cmd.max_power_w == 5000          # was charge_power_w → TypeError
    assert cmd.duration_minutes == 240      # was duration_min → TypeError


# ── B1 part 2: a SCHEDULED decision carries a real charge power ──────────

def test_scheduler_decision_has_charge_power_field():
    d = SchedulerDecision(state=SchedulerState.SCHEDULED, charge_power_w=4400.0)
    assert d.charge_power_w == 4400.0
    # decide_battery reads it via getattr; default must be 0.0 not missing
    assert SchedulerDecision(state=SchedulerState.IDLE).charge_power_w == 0.0


# ── H3: is_active_now respects the real slot boundaries ─────────────────
