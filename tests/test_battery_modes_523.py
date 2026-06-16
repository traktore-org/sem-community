"""#523 — per-battery control modes (decide_battery + gating).

Five modes, all mapping to existing BatteryIntent values:
  auto / self_consumption / allow_arbitrage / force_charge / force_discharge

The pure decision (``decide_battery``) is the contract under test here;
the entities (select/number) and coordinator wiring are thin around it.
"""
from __future__ import annotations

from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.consts.battery_modes import (
    arbitrage_allowed_for_mode,
)


def _view(*, mode="auto", reserve=None, soc=80.0, sched=None, cfg_extra=None,
          ev_charging=False, charging_state="idle"):
    cfg = {"battery_max_discharge_power": 4000, "battery_max_charge_power_w": 5000}
    if mode is not None:
        cfg["battery_mode"] = mode
    if reserve is not None:
        cfg["battery_reserve_soc"] = reserve
    if cfg_extra:
        cfg.update(cfg_extra)
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config=cfg,
        fleet=FleetContext(),
        charging_state=charging_state,
        ev_charging=ev_charging,
        home_consumption_w=500.0,
        scheduler_decision=sched,
    )


def _arb_verdict(power=4000.0, floor=10.0):
    return SimpleNamespace(
        state=SimpleNamespace(value="discharging_arbitrage"),
        discharge_power_w=power, floor_soc=floor,
        reason="export arbitrage", should_charge=False,
    )


# ── manual modes override everything ────────────────────────────────

def test_force_discharge_mode():
    d = decide_battery(_view(mode="force_discharge", reserve=30))
    assert d.intent is BatteryIntent.FORCE_DISCHARGE
    assert d.discharge_power_w == 4000
    assert d.floor_soc == 30


def test_force_charge_mode():
    d = decide_battery(_view(mode="force_charge"))
    assert d.intent is BatteryIntent.FORCE_CHARGE
    assert d.target_soc == 100.0
    assert d.charge_power_w == 5000


def test_force_discharge_overrides_scheduler_charge():
    # Even if the scheduler wants to charge, manual force_discharge wins.
    sched = SimpleNamespace(
        state=SimpleNamespace(value="scheduled"), should_charge=True,
        target_soc=90, schedule=None,
    )
    d = decide_battery(_view(mode="force_discharge", sched=sched))
    assert d.intent is BatteryIntent.FORCE_DISCHARGE


# ── auto = today's behaviour (no override) ──────────────────────────

def test_auto_no_scheduler_is_normal():
    d = decide_battery(_view(mode="auto", sched=None))
    assert d.intent is BatteryIntent.NORMAL


def test_auto_missing_mode_key_is_normal():
    # No battery_mode key at all (single-battery / untouched) → NORMAL.
    d = decide_battery(_view(mode=None, sched=None))
    assert d.intent is BatteryIntent.NORMAL


# ── arbitrage verdict gated per battery ─────────────────────────────

def test_self_consumption_suppresses_arbitrage():
    # Shared DISCHARGING_ARBITRAGE verdict + global arbitrage ON, but this
    # battery is self_consumption → it must NOT sell.
    d = decide_battery(_view(
        mode="self_consumption", sched=_arb_verdict(),
        cfg_extra={"battery_grid_arbitrage_enabled": True},
    ))
    assert d.intent is BatteryIntent.NORMAL


def test_allow_arbitrage_sells_even_with_global_off():
    d = decide_battery(_view(
        mode="allow_arbitrage", sched=_arb_verdict(),
        cfg_extra={"battery_grid_arbitrage_enabled": False},
    ))
    assert d.intent is BatteryIntent.FORCE_DISCHARGE


def test_auto_sells_only_when_global_on():
    on = decide_battery(_view(
        mode="auto", sched=_arb_verdict(),
        cfg_extra={"battery_grid_arbitrage_enabled": True},
    ))
    off = decide_battery(_view(
        mode="auto", sched=_arb_verdict(),
        cfg_extra={"battery_grid_arbitrage_enabled": False},
    ))
    assert on.intent is BatteryIntent.FORCE_DISCHARGE
    assert off.intent is BatteryIntent.NORMAL


def test_arbitrage_respects_per_battery_reserve():
    # SOC 25% with reserve 30% → at/under floor → don't sell.
    d = decide_battery(_view(
        mode="allow_arbitrage", soc=25.0, reserve=30,
        sched=_arb_verdict(),
        cfg_extra={"battery_grid_arbitrage_enabled": True},
    ))
    assert d.intent is BatteryIntent.NORMAL


def test_arbitrage_floor_uses_per_battery_reserve_value():
    d = decide_battery(_view(
        mode="allow_arbitrage", soc=80.0, reserve=40,
        sched=_arb_verdict(floor=10.0),
        cfg_extra={"battery_grid_arbitrage_enabled": True},
    ))
    assert d.intent is BatteryIntent.FORCE_DISCHARGE
    assert d.floor_soc == 40  # per-battery reserve wins over verdict's 10


# ── the gating helper ───────────────────────────────────────────────

def test_arbitrage_allowed_helper():
    assert arbitrage_allowed_for_mode("self_consumption", True) is False
    assert arbitrage_allowed_for_mode("allow_arbitrage", False) is True
    assert arbitrage_allowed_for_mode("auto", True) is True
    assert arbitrage_allowed_for_mode("auto", False) is False
    assert arbitrage_allowed_for_mode(None, True) is True
