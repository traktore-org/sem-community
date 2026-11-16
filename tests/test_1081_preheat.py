"""(#1081) Pre-heat: "Also in the cheapest-heat hours".

With the tick ON (and the load may buy) a planned cheap block heats on to
the TOP (Keep at + Extra) instead of stopping at Keep at. With the tick OFF
every decision is what it was: the first tests run the same fixtures with the
key absent, False and (where it cannot count) True, and compare.
"""
from __future__ import annotations

from collections import deque
from datetime import datetime, timedelta
from unittest.mock import PropertyMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    compute_load_intent,
)
from custom_components.solar_energy_management.devices.base import (
    ClimateDevice,
    DeviceControlMode,
)
from custom_components.solar_energy_management.tests.test_1102_use_cases import (
    BLOCK,
    CLOSED,
    SENSOR,
    _boiler,
    _cycle,
    _past_minimums,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import _Hass

NOW = datetime(2026, 11, 16, 22, 0)


def _learned(dev, rate=3.0):
    """A heating rate of ``rate`` K/h, learned from an hour of running."""
    dev._comfort_on_samples = deque(
        (NOW - timedelta(minutes=60 - m), 40.0 + rate * m / 60)
        for m in range(0, 61, 10))
    dev._comfort_off_samples = deque()


def _tank(temp, *, preheat=None, **kw):
    hass, dev, sc = _boiler(temp, **kw)
    if preheat is not None:
        dev.preheat = preheat
    return hass, dev, sc


def _ask(dev):
    return dev.comfort_plan_demand(NOW, goal=True)


# ── tick OFF: identical ───────────────────────────────────────────────────

@pytest.mark.parametrize("temp", [47.0, 50.5, 52.5, 54.0, 56.5])
def test_off_the_demand_is_the_same_with_and_without_the_key(temp):
    _h, plain, _s = _tank(temp)
    _h, off, _s = _tank(temp, preheat=False)
    _learned(plain), _learned(off)
    assert plain.preheat is False
    assert _ask(plain) == _ask(off)
    _h, bare, _s = _tank(temp)                      # no learned rate either
    _h, bare_off, _s = _tank(temp, preheat=False)
    assert _ask(bare) == _ask(bare_off)


@pytest.mark.asyncio
@pytest.mark.parametrize("path", [
    [("cheap", True, 47.6), ("cheap", True, 52.1)],
    [("cheap", True, 47.6), ("cheap", "closed", 50.1), ("normal", "closed", 50.1)],
    [("cheap", True, 47.6), ("cheap", True, 52.5), ("cheap", True, 55.0)],
])
async def test_off_the_run_and_the_stop_are_the_same(path):
    """Same fixture, key absent vs False: the same decision at every step."""
    seen = []
    for preheat in (None, False):
        hass, dev, sc = _tank(path[0][2], preheat=preheat)
        trace = []
        for price, block, temp in path:
            hass.set(SENSOR, str(temp), unit_of_measurement="°C")
            _past_minimums(dev)
            await _cycle(sc, price=price, block=block, night=(block is True))
            trace.append((dev.is_active,
                          [r["reason_code"] for r in sc.decision_log.records()]))
        seen.append(trace)
    assert seen[0] == seen[1]


@pytest.mark.asyncio
async def test_off_a_run_still_stops_at_keep_at():
    hass, dev, sc = _tank(47.6)
    await _cycle(sc, price="cheap", block=True)
    assert dev.is_active
    hass.set(SENSOR, "52.1", unit_of_measurement="°C")
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active
    rec = sc.decision_log.records()[-1]
    assert rec["reason_code"] == RC.LOAD_AT_TARGET
    assert "keep-at" in rec["text"]


# ── tick ON: the plan ─────────────────────────────────────────────────────

def test_on_the_demand_grows_to_the_top():
    _h, off, _s = _tank(47.0)
    _h, on, _s = _tank(47.0, preheat=True)
    _learned(off), _learned(on)
    # 3 K/h at 2.5 kW: 5 K to Keep at, 9 K to the top (52 + 4 = 56)
    assert _ask(off)["energy_kwh"] == pytest.approx(5 / 3 * 2.5, rel=0.05)
    assert _ask(on)["energy_kwh"] == pytest.approx(9 / 3 * 2.5, rel=0.05)
    assert _ask(on)["deadline"] is None and _ask(off)["deadline"] is None


def test_on_a_tank_never_asks_above_its_legionella_cap():
    _h, on, _s = _tank(47.0, preheat=True)
    on.legionella_target_temp = 54.0              # the top 56 is capped to 54
    _learned(on)
    assert _ask(on)["energy_kwh"] == pytest.approx(7 / 3 * 2.5, rel=0.05)
    assert on.comfort_preheat_top_c() == 54.0


def test_on_a_cap_below_keep_at_never_shrinks_the_ask():
    _h, off, _s = _tank(47.0)
    _h, on, _s = _tank(47.0, preheat=True)
    on.legionella_target_temp = 50.0              # under Keep at (52)
    _learned(off), _learned(on)
    assert _ask(on) == _ask(off)


def test_on_without_a_learned_rate_the_ask_is_what_it_is_today():
    _h, off, _s = _tank(47.0)
    _h, on, _s = _tank(47.0, preheat=True)
    assert _ask(on) == _ask(off) and _ask(on) is not None


def test_on_the_start_rule_is_unchanged():
    """A tank between Keep at and the top is not started by the tick."""
    _h, on, _s = _tank(53.0, preheat=True)
    _learned(on, 3.0)
    assert _ask(on) is None
    _h, hot, _s = _tank(51.5, preheat=True)       # inside the start gap
    _learned(hot)
    assert _ask(hot) is None


def test_on_but_may_not_buy_nothing_changes():
    _h, off, _s = _tank(47.0, buy=False)
    _h, on, _s = _tank(47.0, preheat=True, buy=False)
    _learned(off), _learned(on)
    assert on.comfort_preheat_on() is False
    assert _ask(on) == _ask(off) is None


def test_the_replan_signature_differs_when_the_tick_flips():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        demand_signature_changed)
    from custom_components.solar_energy_management.tests.test_638_demand_replan import (
        _coord, _power)
    _h, dev, _s = _tank(47.0)
    off = _coord(devices=(dev,))._energy_plan_demand_signature(_power())
    dev.preheat = True
    on = _coord(devices=(dev,))._energy_plan_demand_signature(_power())
    assert demand_signature_changed(off, on) is True
    assert ("comfort", dev.device_id, "goal-preheat") in on
    assert ("comfort", dev.device_id, "goal") in off
    dev.preheat = False
    assert _coord(devices=(dev,))._energy_plan_demand_signature(_power()) == off


def test_a_normal_hour_is_never_used_even_for_the_bigger_ask():
    """The ask grows, the hours rule does not: only the cheap-level hour
    carries it, whatever the other hours cost."""
    from custom_components.solar_energy_management.coordinator.energy_planner import (
        Demand, LedgerSlot, build_night_ledger, pack_night)
    t0 = datetime(2026, 11, 14, 18, 0)
    slots = []
    for h in range(14):
        t = t0 + timedelta(hours=h)
        cheap = t.hour == 2
        slots.append(LedgerSlot(
            start=t, end=t + timedelta(hours=1), price=0.2 if cheap else 0.3,
            level_cheap=cheap, tariff_cheap=cheap, home_w=0.0, solar_w=0.0))
    ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                max_discharge_w=0.0, peak_limit_w=8000.0)
    for kwh in (2.5, 7.5):
        plan = pack_night([Demand(
            id="comfort:hot_water", kind="comfort", energy_kwh=kwh,
            max_power_w=2500.0, min_power_w=2500.0, deadline=t0 + timedelta(hours=14),
            source="grid", needs_cheap_level=True, unpriced_ok=True)],
            ledger, peak_limit_w=8000.0)
        assert {a.start.hour for a in plan.allocations} == {2}


# ── tick ON: layer 1 ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_on_a_run_goes_past_keep_at_and_stops_at_the_top():
    hass, dev, sc = _tank(47.6, preheat=True)
    await _cycle(sc, price="cheap", block=True)
    assert dev.is_active
    for temp in (52.1, 54.0, 55.9):
        hass.set(SENSOR, str(temp), unit_of_measurement="°C")
        _past_minimums(dev)
        await _cycle(sc, price="cheap", block=True)
        assert dev.is_active, temp
    hass.set(SENSOR, "56.0", unit_of_measurement="°C")
    assert dev.comfort_state == "banked"
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active
    rec = sc.decision_log.records()[-1]
    # banked at the top: the band's own stop speaks first
    assert rec["reason_code"] in (RC.LOAD_STOP_CONDITION, RC.LOAD_AT_TARGET)


@pytest.mark.asyncio
async def test_on_the_top_stops_it_at_once_inside_the_minimum_run():
    hass, dev, sc = _tank(47.6, preheat=True)
    await _cycle(sc, price="cheap", block=True)
    assert dev.can_deactivate() is False
    hass.set(SENSOR, "56.2", unit_of_measurement="°C")
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_on_it_stops_when_the_block_ended_and_the_price_rose():
    hass, dev, sc = _tank(47.6, preheat=True)
    await _cycle(sc, price="cheap", block=True)
    hass.set(SENSOR, "53.0", unit_of_measurement="°C")
    _past_minimums(dev)
    await _cycle(sc, price="cheap", block="closed")          # still cheap: on
    assert dev.is_active
    await _cycle(sc, price="normal", block="closed", night=False)
    await _cycle(sc, price="normal", block="closed", night=False)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_on_a_sun_run_is_not_turned_into_a_bought_one():
    hass, dev, sc = _tank(53.0, preheat=True)
    await _cycle(sc, surplus=4000.0, night=False, solar=5000.0)
    assert dev.is_active
    hass.set(SENSOR, "54.0", unit_of_measurement="°C")
    _past_minimums(dev)
    for _ in range(3):                         # the sun is gone, a block is open
        await _cycle(sc, surplus=-2500.0, price="cheap", night=False, solar=0.0,
                     block=True)
    assert not dev.is_active                   # a fresh start needs Keep at


def _intent(dev, **kw):
    args = dict(remaining_surplus_w=-400.0, price_is_cheap=True, plan=BLOCK)
    args.update(kw)
    return compute_load_intent(dev, **args)


@pytest.mark.asyncio
async def test_on_the_stops_that_outrank_the_run():
    hass, dev, sc = _tank(47.6, preheat=True)
    await _cycle(sc, price="cheap", block=True)
    hass.set(SENSOR, "54.0", unit_of_measurement="°C")
    assert _intent(dev).on is True and _intent(dev).code == RC.LOAD_COMFORT_GOAL
    # peak shed
    shed = _intent(dev, is_shed_target=True)
    assert shed.on is False and shed.code == RC.LOAD_PEAK_SHED
    # a peak limit that is near freezes STARTS only: the run is not cut by it
    assert _intent(dev, peak_freeze=True).on is True
    # mode Off
    dev.control_mode = DeviceControlMode.OFF
    assert _intent(dev).on is False
    dev.control_mode = DeviceControlMode.SURPLUS
    # away: the band is disengaged, the pre-heat has nothing to run on
    dev.vacation = True
    assert _intent(dev).code != RC.LOAD_COMFORT_GOAL
    dev.vacation = False
    # the operator's relay: no write either way
    with patch.object(type(dev), "locked_by_operator",
                      new_callable=PropertyMock, return_value=True):
        assert _intent(dev).code != RC.LOAD_COMFORT_GOAL


@pytest.mark.asyncio
async def test_on_the_users_own_stop_below_the_top_ends_it():
    hass, dev, sc = _tank(47.6, preheat=True, stop=54.0)
    await _cycle(sc, price="cheap", block=True)
    assert dev.is_active
    hass.set(SENSOR, "54.2", unit_of_measurement="°C")
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_on_but_may_not_buy_the_run_never_starts():
    hass, dev, sc = _tank(47.6, preheat=True, buy=False)
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active
    assert dev.comfort_preheat_open() is False


# ── tick ON: what is left out ─────────────────────────────────────────────

@pytest.mark.asyncio
async def test_a_unit_that_rides_its_own_setpoint_is_left_out():
    hass, dev, sc = _tank(47.6, preheat=True)
    dev._comfort_anchor_c = lambda: 50.0
    assert dev.comfort_preheat_supported() is False
    assert dev.comfort_preheat_on() is False
    await _cycle(sc, price="cheap", block=True)
    assert dev.is_active
    hass.set(SENSOR, "52.6", unit_of_measurement="°C")   # anchored: Keep at is 50
    _past_minimums(dev)
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active                             # stops as today


def test_a_climate_unit_and_a_heat_pump_with_a_climate_entity_are_left_out():
    from custom_components.solar_energy_management.devices.heat_pump_controller import (
        HeatPumpController)
    assert ClimateDevice.comfort_preheat_supported(object()) is False
    contacts = HeatPumpController(hass=_Hass(), climate_entity_id=None)
    assert contacts.comfort_preheat_supported() is True
    riding = HeatPumpController(hass=_Hass(), climate_entity_id="climate.pump")
    assert riding.comfort_preheat_supported() is False


def test_a_cooling_band_is_left_out():
    _h, dev, _s = _tank(47.0, preheat=True)
    dev._comfort_direction = lambda: "cool"
    assert dev.comfort_preheat_supported() is False


# ── the goal and the payload ──────────────────────────────────────────────

def test_the_goal_is_stored_validated_and_published():
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry, _goal_bool)
    assert "preheat" in UnifiedDeviceRegistry.GOAL_PROPERTIES
    _h, dev, _s = _tank(47.0, preheat=True)
    block = UnifiedDeviceRegistry._comfort_payload(dev)["comfort"]
    assert block["preheat"] is True and block["preheat_ok"] is True
    assert block["max_c"] == 56.0
    dev._comfort_anchor_c = lambda: 50.0
    block = UnifiedDeviceRegistry._comfort_payload(dev)["comfort"]
    assert block["preheat_ok"] is False and block["anchored"] is True
    assert _goal_bool("False") is False and _goal_bool("true") is True


def test_the_service_takes_the_key_as_a_bool_string():
    import pathlib
    root = pathlib.Path(__file__).resolve().parent.parent
    src = (root / "__init__.py").read_text()
    assert src.count('"preheat"') >= 3
    assert "preheat" in (root / "services.yaml").read_text()


@pytest.mark.asyncio
async def test_the_goal_reaches_the_device():
    from custom_components.solar_energy_management.tests.test_1081_cop_curve import (
        _registry_with_pump)
    reg, hp = _registry_with_pump()
    assert hp.preheat is False                  # a new load: off
    await reg.async_update_device_goal("heat_pump", "preheat", "True")
    assert hp.preheat is True
    hp.preheat = False
    reg._apply_goals(hp)                        # a restart applies the stored goal
    assert hp.preheat is True
    await reg.async_update_device_goal("heat_pump", "preheat", "False")
    assert hp.preheat is False
