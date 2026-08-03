"""Tests for the inverter + battery per-device primary architecture.

Group C of the arch follow-up. Pins the new contracts:

- Runtime types are immutable / sane (I13, I14)
- Per-device flow conservation (I15, I16) — deferred to flow_calculator
  refactor in a follow-on commit
- Single-device fallback works (I17)
- BatteryIntent gating logic (I18, I19)
- Adapter idempotency / discharge limit hysteresis (I20)
- Decision sanity bounds (I21, I22)
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    DeyeBatteryAdapter,
    GenericBatteryAdapter,
    GoodWeBatteryAdapter,
    HuaweiBatteryAdapter,
    adapter_for,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryFlows,
    BatteryIntent,
    BatteryPower,
    BatteryRuntime,
    BatteryView,
    FleetContext,
    InverterFlows,
    InverterPower,
    InverterRuntime,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────

def _runtime(battery_id="batt1", **kw):
    return BatteryRuntime(battery_id=battery_id, **kw)


def _view(*, runtime=None, charging_state="idle", ev_charging=False,
          ev_connected=None, home_w=500.0, scheduler_decision=None,
          config=None, fleet=None, grid_funded_w=0.0):
    return BatteryView(
        runtime=runtime or _runtime(),
        config=config or {},
        fleet=fleet or FleetContext(),
        charging_state=charging_state,
        ev_charging=ev_charging,
        # Default ev_connected to ev_charging when not given: a drawing
        # car is by definition plugged in. Tests that exercise the
        # "plugged but idle" case pass ev_connected explicitly.
        ev_connected=ev_charging if ev_connected is None else ev_connected,
        home_consumption_w=home_w,
        scheduler_decision=scheduler_decision,
        grid_funded_load_w=grid_funded_w,
    )


def _sched(state, **kw):
    """Build a synthetic SchedulerDecision-shaped object."""
    m = MagicMock()
    m.state = MagicMock(value=state)
    # Faithful to the real dataclass default (#533): a bare MagicMock would
    # make getattr(m, "from_arbitrage") a truthy auto-attr, wrongly routing the
    # night-charge stop to STOP_FORCE_DISCHARGE. Default False; kwargs override.
    m.from_arbitrage = False
    for k, v in kw.items():
        setattr(m, k, v)
    return m


# ─────────────────────────────────────────────────────────────────
# I13 — InverterRuntime / BatteryRuntime shape
# ─────────────────────────────────────────────────────────────────

class TestRuntimeTypes:
    def test_inverter_runtime_defaults(self):
        rt = InverterRuntime(inverter_id="sun2000")
        assert rt.inverter_id == "sun2000"
        assert rt.daily_kwh == 0.0
        assert rt.available is True

    def test_battery_runtime_defaults(self):
        rt = BatteryRuntime(battery_id="luna")
        assert rt.battery_id == "luna"
        assert rt.daily_charge_kwh == 0.0
        assert rt.daily_discharge_kwh == 0.0
        assert rt.capacity_kwh == 0.0
        assert rt.available is True


# ─────────────────────────────────────────────────────────────────
# I15 / I16 — Per-device flow types
# ─────────────────────────────────────────────────────────────────

class TestFlowTypes:
    def test_inverter_flows_frozen(self):
        from dataclasses import FrozenInstanceError
        f = InverterFlows(inverter_id="sun2000", solar_to_home=2000.0)
        with pytest.raises(FrozenInstanceError):
            f.solar_to_home = 0.0  # type: ignore[misc]

    def test_battery_flows_frozen(self):
        from dataclasses import FrozenInstanceError
        f = BatteryFlows(battery_id="luna", battery_to_home=1500.0)
        with pytest.raises(FrozenInstanceError):
            f.battery_to_home = 0.0  # type: ignore[misc]


# ─────────────────────────────────────────────────────────────────
# I18 — LIMIT_DISCHARGE gate
# ─────────────────────────────────────────────────────────────────

class TestI18LimitDischargeGate:
    """LIMIT_DISCHARGE only fires during NIGHT_CHARGING_ACTIVE + EV charging."""

    def test_night_charging_active_with_ev_charging_limits(self):
        d = decide_battery(_view(
            charging_state="night_charging_active",
            ev_charging=True, home_w=1500.0,
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 1500.0

    def test_night_charging_active_without_ev_does_not_limit(self):
        d = decide_battery(_view(
            charging_state="night_charging_active",
            ev_charging=False,
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_solar_charging_with_ev_and_surplus_does_not_limit(self):
        # Real solar surplus ≥ gate (3500 W) AND SoC ≥ buffer → battery
        # free to assist the EV; the unified clamp does not fire.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=True, home_w=500.0,
            fleet=FleetContext(solar_w=4000.0, home_w=500.0,
                               battery_soc=80.0, buffer_soc=70.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_below_buffer_limits_even_with_surplus(self):
        # PROD 2026-06-26: SoC below the buffer floor but surplus ≥ gate.
        # The battery must NOT feed the car below the self-consumption
        # reserve, in any zone — clamp via the buffer arm.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=True, home_w=600.0,
            fleet=FleetContext(solar_w=2000.0, home_w=600.0,   # surplus 1400 ≥ gate
                               battery_soc=83.0, buffer_soc=85.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 600.0
        assert "buffer" in d.reason

    def test_at_buffer_with_surplus_does_not_limit(self):
        # Exactly at the buffer (SoC == buffer) → in the assist band → free.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=True, home_w=600.0,
            fleet=FleetContext(solar_w=2000.0, home_w=600.0,
                               battery_soc=85.0, buffer_soc=85.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_solar_charging_with_ev_below_gate_limits(self):
        # Solar surplus below the gate (cloudy day) → the unified clamp
        # protects the battery in ANY mode, no opt-in flag needed.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=True, home_w=800.0,
            fleet=FleetContext(solar_w=300.0, home_w=800.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 800.0

    def test_protection_disabled_never_limits(self):
        d = decide_battery(_view(
            charging_state="night_charging_active",
            ev_charging=True,
            config={"battery_discharge_protection_enabled": False},
        ))
        assert d.intent is BatteryIntent.NORMAL


class TestGridFundedLoadClamp:
    """(#620) "Finish overnight from: Grid" must be GRID-fed. Observed live
    (PROD 2026-07-22): with no clamp the inverter's self-consumption covered
    the cheap-hours load from the battery — Battery and Grid picker choices
    were physically identical. While grid-funded loads run, discharge is
    capped at home − grid_funded so the grid feeds exactly those loads."""

    def test_grid_funded_load_limits_without_ev(self):
        # Night, no EV plugged: a 600 W cheap-hours load runs. home=1250
        # (includes the load) → limit 650: battery serves the rest of the
        # house, grid imports the load's 600 W.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=False,
            home_w=1250.0, grid_funded_w=600.0,
            fleet=FleetContext(solar_w=0.0, home_w=1250.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 650.0
        assert "grid" in d.reason.lower()

    def test_ev_clamp_also_excludes_grid_funded_load(self):
        # EV plugged at night (surplus 0 < gate) AND a 600 W cheap-hours
        # load running: the EV clamp fires and must subtract the load too.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=True,
            home_w=1250.0, grid_funded_w=600.0,
            fleet=FleetContext(solar_w=0.0, home_w=1250.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 650.0
        assert "grid-funded" in d.reason

    def test_no_grid_funded_load_no_extra_clamp(self):
        # Nothing on cheap-hours → the new branch is inert; battery free.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=False,
            home_w=1250.0, grid_funded_w=0.0,
            fleet=FleetContext(solar_w=0.0, home_w=1250.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_grid_funded_respects_protection_disable(self):
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=False,
            home_w=1250.0, grid_funded_w=600.0,
            fleet=FleetContext(solar_w=0.0, home_w=1250.0),
            config={"battery_discharge_protection_enabled": False},
        ))
        assert d.intent is BatteryIntent.NORMAL

    def test_grid_funded_larger_than_home_clamps_to_zero(self):
        # Defensive: load draw exceeding measured home (sensor skew) must
        # floor at 0, never a negative limit.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=False,
            home_w=500.0, grid_funded_w=800.0,
            fleet=FleetContext(solar_w=0.0, home_w=500.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 0.0

    def test_plugged_but_not_drawing_still_limits(self):
        # The coupling fix: a bursty car (Renault Zoe) is plugged in
        # (ev_connected) but momentarily NOT drawing (ev_charging=False)
        # between pulses. The clamp MUST still hold — otherwise the
        # battery discharges freely in the gap and feeds the next pull
        # (PROD 2026-06-24, 93→41 % overnight). Surplus 0 < gate.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=True, home_w=800.0,
            fleet=FleetContext(solar_w=0.0, home_w=800.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == 800.0

    def test_unplugged_and_not_drawing_does_not_limit(self):
        # No car plugged in at all → the protection does not fire even
        # in a low-surplus state; the battery is free to discharge for
        # the house as normal.
        d = decide_battery(_view(
            charging_state="solar_charging_active",
            ev_charging=False, ev_connected=False, home_w=800.0,
            fleet=FleetContext(solar_w=0.0, home_w=800.0),
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.NORMAL


# ─────────────────────────────────────────────────────────────────
# I19 — FORCE_CHARGE only when scheduler says SCHEDULED
# ─────────────────────────────────────────────────────────────────

class TestI19ForceChargeGate:
    def test_scheduled_in_window_force_charges(self):
        sched = _sched("scheduled", target_soc=90.0, charge_power_w=3000.0,
                       duration_min=120)
        # No schedule means in_window defaults True (back-compat path).
        d = decide_battery(_view(scheduler_decision=sched))
        assert d.intent is BatteryIntent.FORCE_CHARGE
        assert d.target_soc == 90.0
        assert d.charge_power_w == 3000.0
        assert d.duration_min == 120

    def test_target_reached_stops_force_charge(self):
        sched = _sched("target_reached")
        d = decide_battery(_view(scheduler_decision=sched))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    def test_not_needed_stops(self):
        sched = _sched("not_needed")
        d = decide_battery(_view(scheduler_decision=sched))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    def test_not_profitable_stops(self):
        sched = _sched("not_profitable")
        d = decide_battery(_view(scheduler_decision=sched))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    def test_idle_state_stops(self):
        sched = _sched("idle")
        d = decide_battery(_view(scheduler_decision=sched))
        assert d.intent is BatteryIntent.STOP_FORCE_CHARGE

    def test_no_scheduler_decision_normal(self):
        d = decide_battery(_view(scheduler_decision=None))
        assert d.intent is BatteryIntent.NORMAL


# ─────────────────────────────────────────────────────────────────
# Precedence — FORCE_CHARGE > LIMIT_DISCHARGE > NORMAL
# ─────────────────────────────────────────────────────────────────

class TestPrecedence:
    def test_force_charge_beats_limit_discharge(self):
        """Scheduler says force-charge AND it's night + EV charging.
        Force-charge wins."""
        sched = _sched("scheduled", target_soc=80.0, charge_power_w=2000.0)
        d = decide_battery(_view(
            scheduler_decision=sched,
            charging_state="night_charging_active",
            ev_charging=True,
            config={"battery_discharge_protection_enabled": True},
        ))
        assert d.intent is BatteryIntent.FORCE_CHARGE


# ─────────────────────────────────────────────────────────────────
# I21 / I22 — Decision sanity bounds
# ─────────────────────────────────────────────────────────────────

class TestDecisionBounds:
    def test_discharge_limit_non_negative(self):
        """Even with bogus negative home consumption, the
        clamp produces ≥ 0."""
        d = decide_battery(_view(
            charging_state="night_charging_active",
            ev_charging=True, home_w=-500.0,
            config={"battery_discharge_protection_enabled": True},
        ))
        if d.intent is BatteryIntent.LIMIT_DISCHARGE:
            assert d.discharge_limit_w >= 0.0


# ─────────────────────────────────────────────────────────────────
# I20 — Adapter idempotency / discharge limit hysteresis
# ─────────────────────────────────────────────────────────────────

class TestI20AdapterHysteresis:
    """Adapter de-dups consecutive same-value LIMIT_DISCHARGE calls
    so HA isn't spammed with duplicate writes."""

    @pytest.mark.asyncio
    async def test_huawei_hysteresis_skips_small_change(self):
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        cfg = {
            "battery_discharge_control_entity": "number.batt_max_discharge",
            "battery_max_discharge_power": 5000,
        }
        a = HuaweiBatteryAdapter(hass, cfg)
        # First call applies
        await a.command_limit_discharge(2000.0)
        assert hass.services.async_call.await_count == 1
        # Second call with same value (within 100W hysteresis) — no service call
        await a.command_limit_discharge(2050.0)
        assert hass.services.async_call.await_count == 1
        # Third call beyond 100W — service called again
        await a.command_limit_discharge(2200.0)
        assert hass.services.async_call.await_count == 2


# ─────────────────────────────────────────────────────────────────
# Actuate dispatch — every intent → exactly one adapter method
# ─────────────────────────────────────────────────────────────────

class TestActuateDispatch:
    def _adapter(self, supports_forced=True):
        a = MagicMock()
        a.command_normal = AsyncMock()
        a.command_limit_discharge = AsyncMock()
        a.command_force_charge = AsyncMock()
        a.command_stop_force_charge = AsyncMock()
        a.supports_forced_charge = supports_forced
        return a

    @pytest.mark.asyncio
    async def test_normal_calls_command_normal(self):
        a = self._adapter()
        d = BatteryDecision(battery_id="b1", intent=BatteryIntent.NORMAL)
        await actuate_battery(d, a)
        a.command_normal.assert_awaited_once()
        a.command_limit_discharge.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_limit_discharge_calls_with_watts(self):
        a = self._adapter()
        d = BatteryDecision(
            battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
            discharge_limit_w=1500.0,
        )
        await actuate_battery(d, a)
        a.command_limit_discharge.assert_awaited_once_with(1500.0)

    @pytest.mark.asyncio
    async def test_force_charge_calls_with_args(self):
        a = self._adapter()
        d = BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
            target_soc=90.0, charge_power_w=3000.0, duration_min=120,
        )
        await actuate_battery(d, a)
        a.command_force_charge.assert_awaited_once_with(90.0, 3000.0, 120)

    @pytest.mark.asyncio
    async def test_stop_force_charge_calls(self):
        a = self._adapter()
        d = BatteryDecision(
            battery_id="b1", intent=BatteryIntent.STOP_FORCE_CHARGE,
        )
        await actuate_battery(d, a)
        a.command_stop_force_charge.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_force_charge_skipped_when_unsupported(self):
        a = self._adapter(supports_forced=False)
        d = BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
            target_soc=90.0, charge_power_w=3000.0,
        )
        await actuate_battery(d, a)
        a.command_force_charge.assert_not_awaited()


# ─────────────────────────────────────────────────────────────────
# Adapter factory
# ─────────────────────────────────────────────────────────────────

class TestEnergyTotalsViews:
    """EnergyTotals daily_*_view @property accessors compute from
    per-device dicts when populated, fall back to legacy fields
    otherwise."""

    def test_daily_solar_view_empty_dict_falls_back(self):
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        e = EnergyTotals(daily_solar=15.0)
        assert e.daily_solar_view == 15.0

    def test_daily_solar_view_sums_inverters(self):
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        e = EnergyTotals(daily_solar=0.0)
        e.per_inverter["a"] = InverterRuntime(inverter_id="a", daily_kwh=8.0)
        e.per_inverter["b"] = InverterRuntime(inverter_id="b", daily_kwh=5.5)
        assert e.daily_solar_view == pytest.approx(13.5)

    def test_daily_battery_charge_view_sums(self):
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        e = EnergyTotals(daily_battery_charge=0.0)
        e.per_battery["a"] = BatteryRuntime(battery_id="a", daily_charge_kwh=4.0)
        e.per_battery["b"] = BatteryRuntime(battery_id="b", daily_charge_kwh=2.5)
        assert e.daily_battery_charge_view == pytest.approx(6.5)

    def test_daily_battery_discharge_view_sums(self):
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        e = EnergyTotals()
        e.per_battery["a"] = BatteryRuntime(battery_id="a", daily_discharge_kwh=3.0)
        e.per_battery["b"] = BatteryRuntime(battery_id="b", daily_discharge_kwh=1.2)
        assert e.daily_battery_discharge_view == pytest.approx(4.2)

    def test_views_invariant_legacy_field_matches_when_consistent(self):
        """When sensor_reader populates BOTH legacy field + dict
        consistently, the view equals the field. Pinned so a future
        refactor can't drift them."""
        from custom_components.solar_energy_management.coordinator.types import (
            EnergyTotals,
        )
        e = EnergyTotals(daily_solar=20.0)
        e.per_inverter["a"] = InverterRuntime(inverter_id="a", daily_kwh=12.0)
        e.per_inverter["b"] = InverterRuntime(inverter_id="b", daily_kwh=8.0)
        assert e.daily_solar_view == e.daily_solar == 20.0


class TestAdapterFactory:
    def test_explicit_deye(self):
        hass = MagicMock()
        a = adapter_for(hass, {"battery_charge_platform": "deye"})
        assert isinstance(a, DeyeBatteryAdapter)

    def test_explicit_huawei(self):
        hass = MagicMock()
        a = adapter_for(hass, {"battery_charge_platform": "huawei"})
        assert isinstance(a, HuaweiBatteryAdapter)

    def test_explicit_goodwe(self):
        hass = MagicMock()
        a = adapter_for(hass, {"battery_charge_platform": "goodwe"})
        assert isinstance(a, GoodWeBatteryAdapter)

    def test_explicit_generic(self):
        hass = MagicMock()
        a = adapter_for(hass, {"battery_charge_platform": "generic"})
        assert isinstance(a, GenericBatteryAdapter)

    def test_auto_no_brand_falls_back_to_generic(self):
        hass = MagicMock()
        hass.data = {}
        a = adapter_for(hass, {})
        assert isinstance(a, GenericBatteryAdapter)
