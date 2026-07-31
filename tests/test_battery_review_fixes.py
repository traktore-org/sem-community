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

from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    ChargeCommand,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    NightChargeSchedule,
    SchedulerDecision,
    SchedulerState,
    TimeSlot,
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

def _slot(start_offset_h, dur_h, batt_w=4000.0):
    now = dt_util.now()
    start = now + timedelta(hours=start_offset_h)
    return TimeSlot(start=start, end=start + timedelta(hours=dur_h),
                    battery_power_w=batt_w)


def test_is_active_now_true_inside_slot():
    sch = NightChargeSchedule(slots=[_slot(-0.5, 1.0)])  # started 30m ago, 1h long
    assert sch.is_active_now() is True


def test_is_active_now_false_before_slot():
    # #532 review H3: a slot 2h in the future must NOT count as "now" — this is
    # the premature-force-charge bug (charged at 21:00 for a 23:00 slot).
    sch = NightChargeSchedule(slots=[_slot(2.0, 1.0)])
    assert sch.is_active_now() is False


def test_is_active_now_false_after_slot():
    sch = NightChargeSchedule(slots=[_slot(-3.0, 1.0)])  # ended 2h ago
    assert sch.is_active_now() is False


def test_is_active_now_true_when_no_slots():
    # No per-slot detail → legacy "charge whenever scheduled" behaviour.
    assert NightChargeSchedule(slots=[]).is_active_now() is True


def test_decide_battery_now_in_window_uses_is_active_now():
    # End-to-end: a SCHEDULED decision with a future-only slot must NOT
    # force-charge yet.
    from custom_components.solar_energy_management.coordinator.decide_battery import (
        _now_in_window,
    )
    view = MagicMock()
    view.scheduler_decision = SchedulerDecision(
        state=SchedulerState.SCHEDULED,
        schedule=NightChargeSchedule(slots=[_slot(2.0, 1.0)]),  # 2h out
    )
    assert _now_in_window(view) is False
    view.scheduler_decision.schedule = NightChargeSchedule(slots=[_slot(-0.2, 1.0)])
    assert _now_in_window(view) is True


# ── Deye safety: adapter writes remain power-unit aware ──────────────────

@pytest.mark.asyncio
async def test_generic_adapter_rejects_ampere_discharge_entity():
    from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
        GenericBatteryAdapter,
    )

    hass = _hass()
    state = MagicMock()
    state.state = "185"
    state.attributes = {"unit_of_measurement": "A", "min": 0, "max": 350}
    hass.states.get = MagicMock(return_value=state)
    adapter = GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": (
            "number.inverter_battery_max_discharging_current"
        ),
        "battery_max_discharge_power": 12000,
    })

    await adapter.command_normal()

    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_adapter_scales_watts_for_kw_entity():
    from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
        GenericBatteryAdapter,
    )

    hass = _hass()
    state = MagicMock()
    state.state = "1.2"
    state.attributes = {"unit_of_measurement": "kW", "min": 0, "max": 12}
    hass.states.get = MagicMock(return_value=state)
    adapter = GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "number.battery_discharge_power",
        "battery_max_discharge_power": 5000,
    })

    await adapter.command_normal()

    hass.services.async_call.assert_awaited_once()
    assert hass.services.async_call.await_args.args[2]["value"] == 5.0
