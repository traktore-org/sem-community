"""#523 — per-battery control modes (decide_battery + gating).

Five modes, all mapping to existing BatteryIntent values:
  auto / self_consumption / allow_arbitrage / force_charge / force_discharge

The pure decision (``decide_battery``) is the contract under test here;
the entities (select/number) and coordinator wiring are thin around it.
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

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


def test_force_discharge_respects_reserve_floor():
    # SOC at/under reserve → manual force_discharge must HOLD (NORMAL),
    # never drain below the backup reserve.
    below = decide_battery(_view(mode="force_discharge", soc=65.0, reserve=90))
    assert below.intent is BatteryIntent.NORMAL
    above = decide_battery(_view(mode="force_discharge", soc=65.0, reserve=40))
    assert above.intent is BatteryIntent.FORCE_DISCHARGE


def test_force_charge_mode():
    d = decide_battery(_view(mode="force_charge"))
    assert d.intent is BatteryIntent.FORCE_CHARGE
    assert d.target_soc == 100.0
    assert d.charge_power_w == 5000


def test_force_charge_power_falls_back_when_w_key_is_none():
    # #523: battery_max_charge_power_w present-as-None used to yield 0 W
    # (a .get(key, default) returns None when the key exists), so the
    # bidirectional setpoint charged at 0 W. Must fall through to
    # battery_max_charge_power, then the 5000 default.
    d = decide_battery(_view(mode="force_charge", cfg_extra={
        "battery_max_charge_power_w": None,
        "battery_max_charge_power": 2200,
    }))
    assert d.charge_power_w == 2200


def test_force_charge_power_defaults_when_both_keys_absent():
    d = decide_battery(_view(mode="force_charge", cfg_extra={
        "battery_max_charge_power_w": None,
        "battery_max_charge_power": None,
    }))
    assert d.charge_power_w == 5000.0


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
    # decide_battery layer ONLY — this asserts the pure decision permits an
    # allow_arbitrage battery to actuate a verdict even with the global toggle
    # off. It does NOT mean arbitrage runs in v1.7.3: the coordinator gate
    # (_any_allow_arb=False) never calls evaluate_arbitrage, so no verdict is
    # ever produced to actuate. Re-armed in v1.7.4 (ruflo L3).
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
    assert arbitrage_allowed_for_mode("off", True) is False  # off never sells


def test_allow_arbitrage_removed_from_selector_v173():
    # #533: automatic battery→grid arbitrage is deactivated for stable 1.7.3,
    # so the allow_arbitrage mode is no longer OFFERED — but its value is still
    # recognised so a stale config doesn't error (returns in 1.7.4).
    from custom_components.solar_energy_management.consts.battery_modes import (
        BATTERY_MODES,
    )
    assert "allow_arbitrage" not in BATTERY_MODES, "must not be selectable in 1.7.3"
    # the safe + manual modes stay
    for m in ("auto", "self_consumption", "force_charge", "force_discharge", "off"):
        assert m in BATTERY_MODES
    # value still classified (graceful handling + 1.7.4 restore)
    assert arbitrage_allowed_for_mode("allow_arbitrage", True) is True


# ── off mode: SEM hands-off (RienduPre request) ─────────────────────

def test_off_mode_returns_off_intent():
    d = decide_battery(_view(mode="off"))
    assert d.intent is BatteryIntent.OFF
    assert "hands-off" in d.reason


def test_off_mode_beats_scheduler_arbitrage_and_protection():
    # Highest precedence — even with an active arbitrage verdict AND the EV-night
    # protection conditions, off short-circuits to OFF (no command issued).
    d = decide_battery(_view(
        mode="off", sched=_arb_verdict(),
        ev_charging=True, charging_state="night_charging_active",
    ))
    assert d.intent is BatteryIntent.OFF


@pytest.mark.asyncio
async def test_command_off_missing_control_state_fails_closed_then_silent():
    # A missing control entity cannot be validated, so the first OFF handoff
    # must not issue a blind set_value. Subsequent cycles remain silent.
    from unittest.mock import AsyncMock, MagicMock
    from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
        GenericBatteryAdapter,
    )
    hass = MagicMock(); hass.services.async_call = AsyncMock()
    hass.states.get = MagicMock(return_value=None)
    gen = GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": "number.batt_limit",
        "battery_max_discharge_power": 4000,
    })
    gen._last_intent = BatteryIntent.FORCE_DISCHARGE  # was controlling
    await gen.command_off()
    assert gen.last_intent is BatteryIntent.OFF
    assert hass.services.async_call.await_count == 0
    hass.services.async_call.reset_mock()
    await gen.command_off()  # already off → silent
    assert hass.services.async_call.await_count == 0
