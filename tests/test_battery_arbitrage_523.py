"""#523 — battery → grid export arbitrage, owned by the scheduler.

Discharge-to-grid is the mirror of the BatteryChargeScheduler's
charge-on-cheap logic, so the decision lives ON the scheduler
(``evaluate_arbitrage``) and reuses its economic model
(roundtrip_efficiency + battery_cycle_cost). ``decide_battery`` is a pure
actuator of the scheduler's verdict; the Huawei adapter sells to grid.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

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


def test_integration_loaded_only_when_state_loaded():
    # The self-heal trigger: a brand integration counts as present only when
    # an entry is actually LOADED (not while it's still setting up after a
    # restart — that race left PROD on the Generic adapter).
    from custom_components.solar_energy_management.coordinator.battery_adapters import (
        _integration_loaded,
    )
    hass = MagicMock()
    hass.data = {}

    def _entry(state_value):
        e = MagicMock()
        e.state = MagicMock()
        e.state.value = state_value
        return e

    hass.config_entries.async_entries.return_value = [_entry("setup_in_progress")]
    assert _integration_loaded(hass, "huawei_solar") is False   # still loading
    hass.config_entries.async_entries.return_value = [_entry("loaded")]
    assert _integration_loaded(hass, "huawei_solar") is True     # ready
    hass.config_entries.async_entries.return_value = []
    assert _integration_loaded(hass, "huawei_solar") is False    # not installed


def test_adapter_for_detects_huawei_via_config_entries():
    # Modern huawei_solar uses runtime_data, not hass.data — adapter_for
    # must still detect it through loaded config entries (#523 real-hardware).
    from custom_components.solar_energy_management.coordinator.battery_adapters import (
        adapter_for, HuaweiBatteryAdapter,
    )
    hass = MagicMock()
    hass.data = {}  # legacy hass.data check must fail
    entry = MagicMock()
    entry.state = MagicMock()
    entry.state.value = "loaded"
    hass.config_entries.async_entries.return_value = [entry]
    assert isinstance(adapter_for(hass, {}), HuaweiBatteryAdapter)


def test_huawei_autodetects_battery_device_zero_config():
    # #523: with no inverter_device_id configured, the Huawei adapter
    # auto-detects the battery device (connected_energy_storage) from the
    # device registry, so forcible discharge works with zero manual config.
    hass = _hass()
    dev = MagicMock()
    dev.id = "batterydev123"
    dev.identifiers = {("huawei_solar", "BT2470369058/connected_energy_storage")}
    reg = MagicMock()
    reg.devices.values.return_value = [dev]
    with patch(
        "homeassistant.helpers.device_registry.async_get", return_value=reg,
    ):
        a = HuaweiBatteryAdapter(hass, {"battery_max_discharge_power": 4000})
    assert a._inverter_device_id == "batterydev123"
    assert a.supports_forced_discharge is True


@pytest.mark.asyncio
async def test_huawei_service_force_discharge_no_number_entity():
    # Real Huawei has NO forcible-discharge number entity — it uses the
    # huawei_solar.forcible_discharge_soc SERVICE (#523 hardware path).
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "inverter_device_id": "dev123",
        "battery_max_discharge_power": 4000,
    })
    assert a.supports_forced_discharge is True  # device_id, no number entity
    await a.command_force_discharge(3000, 30.0)  # power 3000, reserve 30%
    call = hass.services.async_call.await_args
    assert call.args[0] == "huawei_solar"
    assert call.args[1] == "forcible_discharge_soc"
    assert call.args[2]["device_id"] == "dev123"
    assert call.args[2]["power"] == 3000
    assert call.args[2]["target_soc"] == 30


@pytest.mark.asyncio
async def test_huawei_normal_after_forcible_stops_only_no_limit_write():
    # Anti-block (RienduPre's LUNA2000 locks on back-to-back Modbus writes):
    # exiting a forcible discharge must issue ONLY stop_forcible_charge and
    # NOT also write the discharge-limit register in the same cycle.
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "inverter_device_id": "dev123", "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 30.0)
    hass.services.async_call.reset_mock()
    await a.command_normal()
    calls = hass.services.async_call.await_args_list
    services = [(c.args[0], c.args[1]) for c in calls]
    assert ("huawei_solar", "stop_forcible_charge") in services
    # No number.set_value (discharge-limit register) in the SAME cycle.
    assert ("number", "set_value") not in services


@pytest.mark.asyncio
async def test_huawei_stop_retried_on_following_cycles():
    # Flaky Modbus can drop a single stop — the stop must be re-issued on the
    # next couple of NORMAL cycles so it self-heals (#523 real-hardware).
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "inverter_device_id": "dev123", "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 30.0)
    await a.command_normal()  # first stop (clears _forcible_discharging)
    hass.services.async_call.reset_mock()
    await a.command_normal()  # retry 1
    await a.command_normal()  # retry 2
    stops = [
        c for c in hass.services.async_call.await_args_list
        if c.args[1] == "stop_forcible_charge"
    ]
    assert len(stops) >= 2  # re-issued on the following cycles


@pytest.mark.asyncio
async def test_huawei_force_discharge_issued_once_not_rehammered():
    # Re-issuing forcible_discharge_soc every cycle blocks the inverter;
    # while already discharging at ~the same power it must be a no-op.
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "inverter_device_id": "dev123", "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 30.0)
    hass.services.async_call.reset_mock()
    await a.command_force_discharge(3000, 30.0)  # same power, next cycle
    hass.services.async_call.assert_not_awaited()


@pytest.mark.asyncio
async def test_huawei_service_normal_stops_forcible():
    hass = _hass()
    a = HuaweiBatteryAdapter(hass, {
        "inverter_device_id": "dev123", "battery_max_discharge_power": 4000,
    })
    await a.command_force_discharge(3000, 30.0)
    hass.services.async_call.reset_mock()
    await a.command_normal()  # mutual exclusion → must stop the forced discharge
    stopped = any(
        c.args[0] == "huawei_solar" and c.args[1] == "stop_forcible_charge"
        and c.args[2].get("device_id") == "dev123"
        for c in hass.services.async_call.await_args_list
    )
    assert stopped


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


# ── #523: AC-coupled bidirectional setpoint (Sessy) force-CHARGE ──────────


def _bidir(hass, **over):
    cfg = {
        "battery_force_discharge_control_entity": "number.sessy_1_power_setpoint",
        "battery_strategy_control_entity": "select.sessy_1_power_strategy",
        "battery_setpoint_bidirectional": True,
        "battery_max_charge_power": 2200,
        "battery_max_discharge_power": 1700,
    }
    cfg.update(over)
    return GenericBatteryAdapter(hass, cfg)


@pytest.mark.asyncio
async def test_bidirectional_supports_forced_charge_without_switch():
    # A Sessy has no charge switch — the bidirectional setpoint is enough.
    gen = _bidir(_hass())
    assert gen.supports_forced_charge is True


@pytest.mark.asyncio
async def test_bidirectional_force_charge_writes_negative_setpoint():
    hass = _hass()
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1500, duration_min=60)
    calls = {}
    for c in hass.services.async_call.await_args_list:
        calls[(c.args[0], c.args[1])] = c.args[2]
    # strategy → active (api) BEFORE the setpoint
    assert calls[("select", "select_option")]["option"] == "api"
    # charge = NEGATIVE power on the same setpoint entity
    sp = calls[("number", "set_value")]
    assert sp["entity_id"] == "number.sessy_1_power_setpoint"
    assert sp["value"] == -1500


@pytest.mark.asyncio
async def test_bidirectional_force_charge_clamps_to_max_charge():
    hass = _hass()
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=9000, duration_min=60)
    sp = [c.args[2] for c in hass.services.async_call.await_args_list
          if c.args[0] == "number"][-1]
    assert sp["value"] == -2200  # clamped to max charge


@pytest.mark.asyncio
async def test_bidirectional_normal_zeroes_setpoint_and_releases_strategy():
    hass = _hass()
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1500, duration_min=60)
    hass.services.async_call.reset_mock()
    await gen.command_normal()
    calls = {}
    for c in hass.services.async_call.await_args_list:
        calls[(c.args[0], c.args[1])] = c.args[2]
    assert calls[("number", "set_value")]["value"] == 0.0   # idle
    assert calls[("select", "select_option")]["option"] == "eco"  # self-consume


@pytest.mark.asyncio
async def test_force_charge_via_actuator_fires_for_bidirectional():
    hass = _hass()
    gen = _bidir(hass)
    await actuate_battery(BatteryDecision(
        battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
        target_soc=100.0, charge_power_w=1200,
    ), gen)
    sp = [c.args[2] for c in hass.services.async_call.await_args_list
          if c.args[0] == "number"][-1]
    assert sp["value"] == -1200  # charge actuated, not dropped


@pytest.mark.asyncio
async def test_non_bidirectional_force_charge_still_needs_switch():
    # Without the flag, a setpoint-only battery can't force-charge (no switch).
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.sessy_1_power_setpoint",
    })
    assert gen.supports_forced_charge is False


@pytest.mark.asyncio
async def test_strategy_restores_user_mode_not_eco():
    # #523: the user runs ``nom`` (zero-on-meter). When SEM force-charges
    # (→ api) and then returns to NORMAL, it must restore ``nom`` — NOT clobber
    # it with the ``eco`` fallback (real Sessy options are lowercase).
    hass = _hass()
    state = MagicMock()
    state.state = "nom"
    hass.states.get = MagicMock(return_value=state)
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1000, duration_min=60)
    # captured the prior mode and switched to api
    assert gen._restore_strategy == "nom"
    hass.services.async_call.reset_mock()
    await gen.command_normal()
    opt = [c.args[2]["option"] for c in hass.services.async_call.await_args_list
           if c.args[0] == "select"][-1]
    assert opt == "nom"          # restored, not "eco"
    assert gen._restore_strategy is None


@pytest.mark.asyncio
async def test_strategy_falls_back_to_eco_when_nothing_captured():
    # No readable prior strategy → release uses the configured idle fallback.
    hass = _hass()
    hass.states.get = MagicMock(return_value=None)
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1000, duration_min=60)
    assert gen._restore_strategy is None
    await gen.command_normal()
    opt = [c.args[2]["option"] for c in hass.services.async_call.await_args_list
           if c.args[0] == "select"][-1]
    assert opt == "eco"


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


@pytest.mark.asyncio
async def test_generic_sessy_strategy_gates_setpoint():
    # AC-coupled (Sessy): force_discharge must switch the power-strategy
    # select to the active value BEFORE writing the setpoint, and normal
    # must hand control back to the idle/self-consumption value (#523).
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.sessy_1_power_setpoint",
        "battery_strategy_control_entity": "select.sessy_1_power_strategy",
        "battery_strategy_active_value": "api",
        "battery_strategy_idle_value": "eco",
        "battery_max_discharge_power": 1700,
    })
    await gen.command_force_discharge(1700, 20.0)
    calls = [(c.args[0], c.args[1], c.args[2]) for c in hass.services.async_call.await_args_list]
    # strategy → api (select) then setpoint (number)
    assert ("select", "select_option", {"entity_id": "select.sessy_1_power_strategy", "option": "api"}) in calls
    assert any(c[0] == "number" and c[2].get("value") == 1700 for c in calls)

    hass.services.async_call.reset_mock()
    await gen.command_normal()
    calls = [(c.args[0], c.args[1], c.args[2].get("option")) for c in hass.services.async_call.await_args_list if c.args[0] == "select"]
    assert ("select", "select_option", "eco") in calls   # back to self-consumption


@pytest.mark.asyncio
async def test_generic_strategy_optional_no_entity():
    # No strategy entity → plain setpoint write, no select call (other generic
    # batteries without a mode select still work).
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": "number.batt_setpoint",
        "battery_max_discharge_power": 3000,
    })
    await gen.command_force_discharge(3000, 20.0)
    assert not any(c.args[0] == "select" for c in hass.services.async_call.await_args_list)
