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
    SchedulerDecision,
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
    d = s.evaluate_arbitrage(80.0, 0.45, 0.20)
    assert d.state is SchedulerState.DISCHARGING_ARBITRAGE
    assert d.discharge_power_w == 4000.0
    assert d.floor_soc == 50.0


def test_enabled_override_runs_when_global_off():
    # #523 per-battery allow_arbitrage: global toggle off, but the override
    # lets the economic check run + fire (decide_battery then gates per unit).
    s = _scheduler(arbitrage_enabled=False)
    assert s.evaluate_arbitrage(80.0, 0.45, 0.20).state is not SchedulerState.DISCHARGING_ARBITRAGE
    assert s.evaluate_arbitrage(
        80.0, 0.45, 0.20, enabled_override=True,
    ).state is SchedulerState.DISCHARGING_ARBITRAGE


def test_no_import_forecast_does_not_fire():
    # #523: with no upcoming-import forecast we can't prove profitability, so
    # arbitrage must NOT sell on the export floor alone (was too eager).
    s = _scheduler()
    assert s.evaluate_arbitrage(80.0, 0.45, None).state is SchedulerState.NOT_PROFITABLE


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
    arb = s.evaluate_arbitrage(80.0, 0.45, 0.20)
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
async def test_bidirectional_normal_zeroes_setpoint_and_self_consumes():
    hass = _hass()
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1500, duration_min=60)
    hass.services.async_call.reset_mock()
    await gen.command_normal()
    calls = {}
    for c in hass.services.async_call.await_args_list:
        calls[(c.args[0], c.args[1])] = c.args[2]
    assert calls[("number", "set_value")]["value"] == 0.0   # setpoint idle
    # #523 (Rien beta.42): NORMAL = self-consumption strategy ``nom``, not ``eco``.
    assert calls[("select", "select_option")]["option"] == "nom"


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
async def test_normal_sets_self_consume_after_force_charge():
    # #523 (Rien beta.42): after a force-charge (→ api), NORMAL returns the
    # Sessy to self-consumption ``nom`` — never the old ``eco`` (which doesn't
    # self-consume), and regardless of what the prior strategy was.
    hass = _hass()
    state = MagicMock()
    state.state = "nom"
    hass.states.get = MagicMock(return_value=state)
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1000, duration_min=60)
    hass.services.async_call.reset_mock()
    await gen.command_normal()
    opt = [c.args[2]["option"] for c in hass.services.async_call.await_args_list
           if c.args[0] == "select"][-1]
    assert opt == "nom"


@pytest.mark.asyncio
async def test_normal_always_sets_nom_not_eco():
    # NORMAL deterministically sets the self-consume strategy ``nom`` — there
    # is no ``eco`` fallback any more (#523 Rien: eco left the battery idle).
    hass = _hass()
    hass.states.get = MagicMock(return_value=None)
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1000, duration_min=60)
    await gen.command_normal()
    opt = [c.args[2]["option"] for c in hass.services.async_call.await_args_list
           if c.args[0] == "select"][-1]
    assert opt == "nom"


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
    assert ("select", "select_option", "nom") in calls   # back to self-consumption


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


# ── #523: setpoint write clamped to the control entity's range ───────────

def _hass_with_range(entity, lo, hi):
    """hass whose states.get returns a number state with min/max attrs."""
    h = _hass()
    st = MagicMock()
    st.attributes = {"min": lo, "max": hi}
    h.states.get = MagicMock(return_value=st)
    return h


@pytest.mark.asyncio
async def test_charge_setpoint_clamped_to_entity_min():
    # RienduPre: fleet battery_max_charge_power_w=4400 → -4400 written to a
    # single Sessy whose setpoint min is -2200; HA rejects out-of-range, so it
    # must be clamped to -2200 (charge at the unit max), not left at 0.
    hass = _hass_with_range("number.sessy_1_power_setpoint", -2200, 1700)
    gen = _bidir(hass, battery_max_charge_power=5000)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=4400, duration_min=60)
    sp = [c.args[2] for c in hass.services.async_call.await_args_list
          if c.args[0] == "number"][-1]
    assert sp["value"] == -2200


@pytest.mark.asyncio
async def test_discharge_setpoint_clamped_to_entity_max():
    hass = _hass_with_range("number.sessy_1_power_setpoint", -2200, 1700)
    gen = _bidir(hass, battery_max_discharge_power=5000)
    await gen.command_force_discharge(5000, 50.0)
    sp = [c.args[2] for c in hass.services.async_call.await_args_list
          if c.args[0] == "number"][-1]
    assert sp["value"] == 1700


@pytest.mark.asyncio
async def test_setpoint_within_range_not_clamped():
    hass = _hass_with_range("number.sessy_1_power_setpoint", -2200, 1700)
    gen = _bidir(hass, battery_max_charge_power=1500)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1500, duration_min=60)
    sp = [c.args[2] for c in hass.services.async_call.await_args_list
          if c.args[0] == "number"][-1]
    assert sp["value"] == -1500


@pytest.mark.asyncio
async def test_normal_sets_self_consume_strategy():
    # #523 (Rien beta.42): Self-consumption / Auto must put the Sessy in the
    # self-consume strategy ``nom`` (zero-on-meter) — the old behaviour left it
    # in ``eco`` (Rien: "doesn't charge or discharge"), so NORMAL now sets nom.
    hass = _hass()
    gen = _bidir(hass)
    await gen.command_normal()
    opt = [c.args[2]["option"] for c in hass.services.async_call.await_args_list
           if c.args[0] == "select"][-1]
    assert opt == "nom"


@pytest.mark.asyncio
async def test_force_charge_then_release_restores_then_idle_leaves_alone():
    # After a force_charge→release cycle, a subsequent self-consumption cycle
    # must not re-touch the strategy (control was already handed back).
    hass = _hass()
    state = MagicMock(); state.state = "nom"
    hass.states.get = MagicMock(return_value=state)
    gen = _bidir(hass)
    await gen.command_force_charge(target_soc=100.0, charge_power_w=1000, duration_min=60)
    await gen.command_normal()              # restores nom, took_control → False
    hass.services.async_call.reset_mock()
    await gen.command_normal()              # second idle cycle — leave alone
    selects = [c for c in hass.services.async_call.await_args_list
               if c.args[0] == "select"]
    assert selects == []


# ═══════════════════════════════════════════════════════════════════════
# #531 — holistic review batch (charge-first, break-even, reserve safety,
# mode-bleed, fleet-split, stranded strategy, mixed-brand, robustness).
# ═══════════════════════════════════════════════════════════════════════

# ── #3: SOC unavailable → never sell blind (reserve safety) ──────────────

def _mode_view(mode, soc, *, sched=None, reserve=None):
    cfg = {"battery_mode": mode, "battery_grid_arbitrage_enabled": True}
    if reserve is not None:
        cfg["battery_reserve_soc"] = reserve
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b", last_known_soc=soc),
        config=cfg,
        fleet=FleetContext(),
        charging_state="idle",
        ev_charging=False,
        home_consumption_w=400.0,
        scheduler_decision=sched,
    )


def test_force_discharge_holds_when_soc_unavailable():
    # #531: a setpoint battery (Sessy) has no hardware reserve-stop, so an
    # unavailable SOC must HOLD, not drain blind past the backup reserve.
    d = decide_battery(_mode_view("force_discharge", None, reserve=20.0))
    assert d.intent is BatteryIntent.NORMAL
    assert "unavailable" in d.reason


def test_force_discharge_sells_when_soc_above_reserve():
    d = decide_battery(_mode_view("force_discharge", 80.0, reserve=20.0))
    assert d.intent is BatteryIntent.FORCE_DISCHARGE


def test_arbitrage_holds_when_soc_unavailable():
    # #531: same guard on the scheduler-driven arbitrage verdict path.
    s = _scheduler()
    arb = s.evaluate_arbitrage(80.0, 0.45, 0.20)
    v = _mode_view("auto", None, sched=arb)
    d = decide_battery(v)
    assert d.intent is not BatteryIntent.FORCE_DISCHARGE


# ── #5: LIMIT_DISCHARGE splits the home budget across the fleet ──────────

def _limit_view(battery_count, home_w):
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b", last_known_soc=80.0),
        config={"battery_discharge_protection_enabled": True},
        fleet=FleetContext(battery_count=battery_count),
        charging_state="night_charging_active",
        ev_charging=True,
        home_consumption_w=home_w,
    )


def test_limit_discharge_single_battery_full_home():
    d = decide_battery(_limit_view(1, 1000.0))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == 1000.0


def test_limit_discharge_two_batteries_split_home():
    # #531: two batteries each told the FULL home load over-inject 2× and
    # leak the surplus to the EV — each must get home / N.
    d = decide_battery(_limit_view(2, 1000.0))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == 500.0
    assert "home/2" in d.reason


# ── Unified solar-gate clamp: protect the battery in ANY EV mode ─────────
# The discharge clamp no longer keys on a night/solar charging-state
# string — it fires whenever the EV is drawing and the pure solar surplus
# (solar − home) is below ``battery_assist_min_surplus_w``. One knob,
# every mode (incl. always_max) and every time of day. Gate = 0 lets the
# battery support the EV everywhere (the user opt-in path).

def _gate_view(*, solar_w, home_w, gate_w=1200.0, ev_charging=True,
               charging_state="solar_charging_active", battery_count=1,
               battery_soc=90.0, buffer_soc=70.0):
    # battery_soc >= buffer_soc by default so these tests isolate the SURPLUS
    # gate arm of the clamp. Below the buffer the clamp also fires regardless
    # of surplus (the self-consumption floor) — a separate protection covered
    # in test_inverter_battery_arch.py.
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b", last_known_soc=80.0),
        config={"battery_discharge_protection_enabled": True},
        fleet=FleetContext(
            battery_count=battery_count,
            solar_w=solar_w, home_w=home_w,
            battery_soc=battery_soc, buffer_soc=buffer_soc,
            battery_assist_min_surplus_w=gate_w,
        ),
        charging_state=charging_state,
        ev_charging=ev_charging,
        home_consumption_w=home_w,
    )


def test_gate_clamps_any_mode_when_surplus_below_gate():
    # No night state at all (e.g. always_max midday with cloud) — surplus
    # 200 < 1200 gate → clamp the battery to home, EV draws from grid.
    d = decide_battery(_gate_view(solar_w=700, home_w=500,
                                  charging_state="charging"))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == 500.0


def test_gate_allows_discharge_when_surplus_above_gate():
    # Surplus 2000 ≥ 1200 gate → no clamp; battery free to assist the EV.
    d = decide_battery(_gate_view(solar_w=2500, home_w=500))
    assert d.intent is not BatteryIntent.LIMIT_DISCHARGE


def test_gate_zero_allows_overnight_battery_support():
    # Gate = 0, no solar, EV charging, SoC above the buffer → NOT clamped
    # (surplus 0 clears a 0 threshold). The user opt-in: battery supports
    # the EV overnight, but only while above the self-consumption floor.
    d = decide_battery(_gate_view(solar_w=0, home_w=600, gate_w=0.0,
                                  battery_soc=90.0, buffer_soc=70.0,
                                  charging_state="night_charging_active"))
    assert d.intent is not BatteryIntent.LIMIT_DISCHARGE


def test_gate_zero_still_honours_buffer_floor():
    # Gate = 0 bypasses the SURPLUS arm, but the buffer SoC floor is a HARD
    # constraint: below the buffer the battery is still clamped even with
    # gate=0 (reviewer #536 follow-up). SoC 65 < buffer 70 → LIMIT_DISCHARGE.
    d = decide_battery(_gate_view(solar_w=0, home_w=600, gate_w=0.0,
                                  battery_soc=65.0, buffer_soc=70.0,
                                  charging_state="night_charging_active"))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert "buffer" in d.reason


def test_gate_default_protects_overnight():
    # Default gate (1200), no solar overnight, EV charging → clamp (the
    # original night-protection behavior, now expressed via the gate).
    d = decide_battery(_gate_view(solar_w=0, home_w=600,
                                  charging_state="night_charging_active"))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == 600.0


def test_gate_no_clamp_when_ev_not_charging():
    # EV not drawing → no clamp regardless of surplus.
    d = decide_battery(_gate_view(solar_w=0, home_w=600, ev_charging=False))
    assert d.intent is not BatteryIntent.LIMIT_DISCHARGE


# ── #2: effective import floor (raw-spot → all-in) ──────────────────────

def test_effective_import_floor_scales_raw_up_to_all_in():
    from custom_components.solar_energy_management.tariff.tariff_provider import (
        DynamicTariffProvider,
    )
    p = DynamicTariffProvider.__new__(DynamicTariffProvider)
    # state all-in (0.30) vs current raw curve slot (0.10) → factor 3.0.
    p.get_current_import_rate = lambda: 0.30
    p._cached_price_for = lambda when: 0.10
    assert p.effective_import_floor(0.05) == pytest.approx(0.15)  # 0.05 * 3.0


def test_effective_import_floor_noop_when_curve_matches_state():
    from custom_components.solar_energy_management.tariff.tariff_provider import (
        DynamicTariffProvider,
    )
    p = DynamicTariffProvider.__new__(DynamicTariffProvider)
    p.get_current_import_rate = lambda: 0.20
    p._cached_price_for = lambda when: 0.20   # all-in provider (Tibber): equal
    assert p.effective_import_floor(0.12) == pytest.approx(0.12)


def test_effective_import_floor_never_scales_down():
    from custom_components.solar_energy_management.tariff.tariff_provider import (
        DynamicTariffProvider,
    )
    p = DynamicTariffProvider.__new__(DynamicTariffProvider)
    p.get_current_import_rate = lambda: 0.10
    p._cached_price_for = lambda when: 0.20   # factor 0.5 → keep raw min
    assert p.effective_import_floor(0.12) == pytest.approx(0.12)


# ── #6: adopt a stranded API strategy across a reload ────────────────────

@pytest.mark.asyncio
async def test_adopts_stranded_api_strategy_at_construction():
    # SEM reloaded mid-episode: the strategy is already 'api'. The next NORMAL
    # must move it OFF api to the self-consume strategy ``nom`` — not leave the
    # battery stranded in API forever.
    hass = _hass()
    state = MagicMock(); state.state = "api"
    hass.states.get = MagicMock(return_value=state)
    gen = _bidir(hass)
    assert gen._took_control is True
    await gen.command_normal()
    opt = [c.args[2]["option"] for c in hass.services.async_call.await_args_list
           if c.args[0] == "select"][-1]
    assert opt == "nom"          # self-consume, not stranded in api


@pytest.mark.asyncio
async def test_no_adoption_when_strategy_is_user_mode():
    hass = _hass()
    state = MagicMock(); state.state = "nom"
    hass.states.get = MagicMock(return_value=state)
    gen = _bidir(hass)
    assert gen._took_control is False


@pytest.mark.asyncio
async def test_off_mode_idles_sessy_strategy():
    # #523 (Rien beta.42): Off must IDLE the Sessy (idle power strategy +
    # setpoint 0) — not leave it self-consuming or stuck in eco.
    hass = _hass()
    gen = _bidir(hass)
    await gen.command_off()
    calls = {(c.args[0], c.args[1]): c.args[2]
             for c in hass.services.async_call.await_args_list}
    assert calls[("select", "select_option")]["option"] == "idle"
    assert calls[("number", "set_value")]["value"] == 0.0
    assert gen.last_intent is BatteryIntent.OFF


@pytest.mark.asyncio
async def test_off_mode_without_strategy_entity_defers_to_base():
    # A non-AC-coupled generic battery (no strategy select) has no native idle
    # → base one-time hands-off (no select call, no crash).
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "number.lim",
        "battery_max_discharge_power": 3000,
    })
    gen._last_intent = BatteryIntent.NORMAL
    await gen.command_off()
    assert gen.last_intent is BatteryIntent.OFF
    assert not [c for c in hass.services.async_call.await_args_list
                if c.args[0] == "select"]


# ── #7: mixed-brand — AC-coupled battery stays Generic ──────────────────

def test_adapter_for_keeps_sessy_generic_in_huawei_fleet():
    # A Sessy b2 (strategy select) in a Huawei fleet must NOT be promoted to
    # the Huawei adapter just because huawei_solar is loaded for b1.
    from custom_components.solar_energy_management.coordinator.battery_adapters import (
        adapter_for, GenericBatteryAdapter,
    )
    hass = _hass()
    entry = MagicMock(); entry.state = MagicMock(); entry.state.value = "loaded"
    hass.data = {}
    hass.config_entries.async_entries.return_value = [entry]  # huawei loaded
    cfg = {
        "battery_strategy_control_entity": "select.sessy_2_power_strategy",
        "battery_force_discharge_control_entity": "number.sessy_2_power_setpoint",
        "battery_setpoint_bidirectional": True,
    }
    assert isinstance(adapter_for(hass, cfg), GenericBatteryAdapter)


# ── robustness: domain-aware discharge limit + clamp warning ────────────

@pytest.mark.asyncio
async def test_discharge_limit_uses_input_number_domain():
    hass = _hass()
    gen = GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "input_number.batt_limit",
        "battery_max_discharge_power": 3000,
    })
    await gen._apply_discharge_limit(1500.0)
    call = hass.services.async_call.await_args
    assert call.args[0] == "input_number" and call.args[1] == "set_value"


@pytest.mark.asyncio
async def test_setpoint_clamp_emits_warning(caplog):
    import logging
    hass = _hass_with_range("number.sessy_1_power_setpoint", -2200, 1700)
    gen = _bidir(hass, battery_max_discharge_power=5000)
    with caplog.at_level(logging.WARNING):
        await gen.command_force_discharge(5000, 50.0)
    assert any("clamped" in r.message for r in caplog.records)


# ── #533 hardening: export cap, from_arbitrage flag, clean stop ────────

def test_export_cap_limits_sell_power():
    # #533: cap the sell power so arbitrage can't create a billed grid peak.
    s = _scheduler(max_discharge_power_w=4000.0, arbitrage_max_export_w=2500.0)
    d = s.evaluate_arbitrage(80.0, 0.45, 0.20)
    assert d.state is SchedulerState.DISCHARGING_ARBITRAGE
    assert d.discharge_power_w == 2500.0  # capped from 4000


def test_export_cap_zero_means_uncapped():
    s = _scheduler(max_discharge_power_w=4000.0, arbitrage_max_export_w=0.0)
    d = s.evaluate_arbitrage(80.0, 0.45, 0.20)
    assert d.discharge_power_w == 4000.0  # full discharge


def test_from_config_export_cap_defaults_to_export_limit():
    cfg = SchedulerConfig.from_config({
        "battery_grid_arbitrage_enabled": True,
        "max_export_power": 3000.0,  # no explicit arbitrage cap → inherits this
    })
    assert cfg.arbitrage_max_export_w == 3000.0


def test_all_verdicts_marked_from_arbitrage():
    # #533: every evaluate_arbitrage verdict carries from_arbitrage=True so the
    # stop routes to STOP_FORCE_DISCHARGE.
    s = _scheduler()
    for d in (
        s.evaluate_arbitrage(80.0, 0.45, 0.20),     # firing
        s.evaluate_arbitrage(50.0, 0.45, None),     # not_needed (reserve)
        s.evaluate_arbitrage(80.0, 0.10, None),     # not_profitable (floor)
        s.evaluate_arbitrage(80.0, 0.45, None),     # not_profitable (no forecast)
        s.evaluate_arbitrage(80.0, 0.21, 0.30),     # not_profitable (break-even)
    ):
        assert d.from_arbitrage is True
    # disabled path too
    assert _scheduler(arbitrage_enabled=False).evaluate_arbitrage(
        80.0, 0.45, 0.20).from_arbitrage is True


def test_decide_battery_arbitrage_stop_emits_stop_force_discharge():
    # #533: an arbitrage non-firing verdict (was selling, now unprofitable)
    # must STOP_FORCE_DISCHARGE — not STOP_FORCE_CHARGE (the Huawei coincidence).
    s = _scheduler()
    stop = s.evaluate_arbitrage(80.0, 0.21, 0.30)  # not_profitable, from_arbitrage
    assert stop.state is SchedulerState.NOT_PROFITABLE
    d = decide_battery(_view(stop))
    assert d.intent is BatteryIntent.STOP_FORCE_DISCHARGE
    # NOT_NEEDED (SOC at/below reserve) is the other arbitrage stop state — it
    # also carries from_arbitrage=True and must route the same way, else a
    # battery that dropped to its reserve while selling would keep force-
    # discharging (ruflo L2).
    at_reserve = s.evaluate_arbitrage(45.0, 0.45, 0.20)  # SOC 45 ≤ reserve 50
    assert at_reserve.state is SchedulerState.NOT_NEEDED
    assert decide_battery(_view(at_reserve)).intent is \
        BatteryIntent.STOP_FORCE_DISCHARGE


def test_decide_battery_night_stop_still_emits_stop_force_charge():
    # A night-charge non-firing verdict (from_arbitrage=False) keeps the
    # original STOP_FORCE_CHARGE behaviour.
    night = SchedulerDecision(
        state=SchedulerState.NOT_NEEDED, from_arbitrage=False,
        reason="already at target",
    )
    d = decide_battery(_view(night))
    assert d.intent is BatteryIntent.STOP_FORCE_CHARGE


def test_arbitrage_off_by_default_stays_deactivated():
    # #533: hardened but NOT activated. A default config (no arbitrage keys)
    # leaves it disabled, and a disabled scheduler never fires.
    cfg = SchedulerConfig.from_config({})
    assert cfg.arbitrage_enabled is False
    s = BatteryChargeScheduler(MagicMock(), MagicMock(), cfg)
    assert s.evaluate_arbitrage(80.0, 0.45, 0.20).state is not \
        SchedulerState.DISCHARGING_ARBITRAGE
