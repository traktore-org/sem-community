"""#523 — battery → grid export arbitrage, owned by the scheduler.

Discharge-to-grid is the mirror of the BatteryChargeScheduler's
charge-on-cheap logic, so the decision lives ON the scheduler
(``evaluate_arbitrage``) and reuses its economic model
(roundtrip_efficiency + battery_cycle_cost). ``decide_battery`` is a pure
actuator of the scheduler's verdict; the Huawei adapter sells to grid.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
    SchedulerState,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)


def _scheduler(**over):
    base = dict(
        arbitrage_enabled=True,
        arbitrage_min_export_price=0.20,
        arbitrage_reserve_soc=50.0,
        max_discharge_power_w=4000.0,
        roundtrip_efficiency=0.90,
        battery_cycle_cost=0.0,
    )
    base.update(over)
    return BatteryChargeScheduler(MagicMock(), MagicMock(), SchedulerConfig(**base))


# ── scheduler owns the decision (reusing its economics) ─────────────

def test_disabled_no_fire():
    s = _scheduler(arbitrage_enabled=False)
    d = s.evaluate_arbitrage(80.0, 0.45, None)
    assert d.state is not SchedulerState.DISCHARGING_ARBITRAGE


def test_fires_on_high_export_above_reserve():
    s = _scheduler()
    d = s.evaluate_arbitrage(80.0, 0.45, None)
    assert d.state is SchedulerState.DISCHARGING_ARBITRAGE
    assert d.discharge_power_w == 4000.0
    assert d.floor_soc == 50.0


def test_export_below_floor_no_fire():
    s = _scheduler()
    assert s.evaluate_arbitrage(80.0, 0.10, None).state is SchedulerState.NOT_PROFITABLE


def test_soc_at_reserve_no_fire():
    s = _scheduler()
    assert s.evaluate_arbitrage(50.0, 0.45, None).state is SchedulerState.NOT_NEEDED


def test_not_profitable_vs_forecast_no_fire():
    # export 0.21 clears the floor, but recharge break-even is
    # 0.30/0.9 = 0.333 → unprofitable.
    s = _scheduler()
    assert s.evaluate_arbitrage(80.0, 0.21, 0.30).state is SchedulerState.NOT_PROFITABLE


def test_profitable_vs_forecast_fires():
    s = _scheduler()
    assert s.evaluate_arbitrage(80.0, 0.45, 0.20).state is SchedulerState.DISCHARGING_ARBITRAGE


def test_cycle_cost_raises_breakeven():
    # With a 0.05/kWh cycle cost, break-even = 0.20/0.9 + 0.10 = 0.322;
    # export 0.30 no longer clears it.
    s = _scheduler(battery_cycle_cost=0.05)
    assert s.evaluate_arbitrage(80.0, 0.30, 0.20).state is SchedulerState.NOT_PROFITABLE


# ── decide_battery is a pure actuator of the scheduler verdict ──────

def _view(sched):
    return BatteryView(
        runtime=BatteryRuntime(battery_id="luna"),
        config={},
        fleet=FleetContext(),
        charging_state="idle",
        ev_charging=False,
        home_consumption_w=500.0,
        scheduler_decision=sched,
    )


def test_decide_battery_actuates_arbitrage_verdict():
    s = _scheduler()
    arb = s.evaluate_arbitrage(80.0, 0.45, None)
    d = decide_battery(_view(arb))
    assert d.intent is BatteryIntent.FORCE_DISCHARGE
    assert d.discharge_power_w == 4000.0
    assert d.floor_soc == 50.0


# ── adapter / actuator ──────────────────────────────────────────────

def _hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    return h


def test_huawei_supports_discharge_only_with_entity():
    assert HuaweiBatteryAdapter(_hass(), {}).supports_forced_discharge is False
    assert HuaweiBatteryAdapter(_hass(), {
        "battery_force_discharge_control_entity": "number.luna_forcible_discharge",
    }).supports_forced_discharge is True


@pytest.mark.asyncio
async def test_huawei_force_discharge_writes_entity():
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.luna_forcible_discharge",
        "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 50.0)
    args = hass.services.async_call.await_args.args
    assert args[0] == "number" and args[1] == "set_value"
    assert args[2]["value"] == 3000
    assert a.last_intent is BatteryIntent.FORCE_DISCHARGE


@pytest.mark.asyncio
async def test_huawei_normal_zeroes_force_discharge():
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.luna_forcible_discharge",
        "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 50.0)
    hass.services.async_call.reset_mock()
    await a.command_normal()
    wrote_zero = any(
        c.args[2].get("entity_id") == "number.luna_forcible_discharge"
        and c.args[2].get("value") == 0.0
        for c in hass.services.async_call.await_args_list
    )
    assert wrote_zero


@pytest.mark.asyncio
async def test_actuator_drops_when_unsupported():
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {})
    assert gen.supports_forced_discharge is False
    await actuate_battery(BatteryDecision(
        battery_id="b", intent=BatteryIntent.FORCE_DISCHARGE,
        discharge_power_w=3000, floor_soc=50.0,
    ), gen)
    hass.services.async_call.assert_not_awaited()
