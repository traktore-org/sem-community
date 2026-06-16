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


def test_enabled_override_runs_when_global_off():
    # #523 per-battery allow_arbitrage: global toggle off, but the override
    # lets the economic check run + fire (decide_battery then gates per unit).
    s = _scheduler(arbitrage_enabled=False)
    assert s.evaluate_arbitrage(80.0, 0.45, None).state is not SchedulerState.DISCHARGING_ARBITRAGE
    assert s.evaluate_arbitrage(
        80.0, 0.45, None, enabled_override=True,
    ).state is SchedulerState.DISCHARGING_ARBITRAGE


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
    # #523 per-battery gating: an ``auto`` battery actuates the shared
    # arbitrage verdict only when the global toggle is on — which the real
    # coordinator config always carries when it produced the verdict.
    return BatteryView(
        runtime=BatteryRuntime(battery_id="luna", last_known_soc=80.0),
        config={"battery_grid_arbitrage_enabled": True},
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
async def test_actuator_drops_when_no_entity():
    # No forcible-discharge entity → unsupported → dropped, no call.
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {})
    assert gen.supports_forced_discharge is False
    await actuate_battery(BatteryDecision(
        battery_id="b", intent=BatteryIntent.FORCE_DISCHARGE,
        discharge_power_w=3000, floor_soc=50.0,
    ), gen)
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_generic_adapter_actuates_with_entity():
    # #523: NON-Huawei batteries (Growatt/Sessy via the generic adapter)
    # can sell to grid too, as long as a discharge-power entity is wired.
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.sessy_setpoint",
        "battery_max_discharge_power": 3000,
    })
    assert gen.supports_forced_discharge is True
    await actuate_battery(BatteryDecision(
        battery_id="b", intent=BatteryIntent.FORCE_DISCHARGE,
        discharge_power_w=5000, floor_soc=50.0,  # clamps to 3000 max
    ), gen)
    args = hass.services.async_call.await_args.args
    assert args[0] == "number" and args[2]["entity_id"] == "number.sessy_setpoint"
    assert args[2]["value"] == 3000  # clamped to max discharge


_ALL_ADAPTERS = [
    ("huawei", "coordinator.battery_adapters.huawei", "HuaweiBatteryAdapter"),
    ("goodwe", "coordinator.battery_adapters.goodwe", "GoodWeBatteryAdapter"),
    ("generic", "coordinator.battery_adapters.generic", "GenericBatteryAdapter"),
]


@pytest.mark.parametrize("name,mod,cls", _ALL_ADAPTERS)
@pytest.mark.asyncio
async def test_all_brand_adapters_can_sell_to_grid(name, mod, cls):
    """#523: EVERY supported battery adapter sells to grid when a
    forcible-discharge entity is wired, and stops cleanly on NORMAL."""
    import importlib
    Adapter = getattr(importlib.import_module(
        f"custom_components.solar_energy_management.{mod}"), cls)
    hass = _hass()
    a = Adapter(hass, {
        "battery_force_discharge_control_entity": "number.sell_power",
        "battery_max_discharge_power": 4000,
    })
    assert a.supports_forced_discharge is True, f"{name} must support it"
    await a.command_force_discharge(3000, 50.0)
    assert any(
        c.args[2].get("entity_id") == "number.sell_power"
        and c.args[2].get("value") == 3000
        for c in hass.services.async_call.await_args_list
    ), f"{name} did not write the sell power"
    hass.services.async_call.reset_mock()
    await a.command_normal()  # any other mode must stop the sale
    assert any(
        c.args[2].get("entity_id") == "number.sell_power"
        and c.args[2].get("value") == 0.0
        for c in hass.services.async_call.await_args_list
    ), f"{name} did not zero the sell power on NORMAL"


@pytest.mark.asyncio
async def test_force_discharge_write_is_domain_aware():
    # A user may wire an input_number helper instead of a number entity;
    # the write must route to that entity's own domain (#523 hardware test).
    hass = _hass()
    a = GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "input_number.sim_force_discharge_power",
        "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 50.0)
    args = hass.services.async_call.await_args.args
    assert args[0] == "input_number" and args[1] == "set_value"
    assert args[2]["entity_id"] == "input_number.sim_force_discharge_power"
    assert args[2]["value"] == 3000


@pytest.mark.asyncio
async def test_generic_normal_zeroes_force_discharge():
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.sessy_setpoint",
        "battery_max_discharge_power": 3000,
    })
    await gen.command_force_discharge(2000, 50.0)
    hass.services.async_call.reset_mock()
    await gen.command_normal()
    wrote_zero = any(
        c.args[2].get("entity_id") == "number.sessy_setpoint"
        and c.args[2].get("value") == 0.0
        for c in hass.services.async_call.await_args_list
    )
    assert wrote_zero
