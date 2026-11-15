"""(#1102) Every use case the reporter raised, as one acceptance list.

The reporter's boiler: a 3.2 kW element on a switch (SEM was told 2.5 kW),
a tank thermometer, "Solar only" with "Finish overnight from: Grid", Keep at
52 °C, Extra 4 °C, Run now past 36 °C, minimum run and pause 30 min, Solar
heating target 55 °C, Legionella 60 °C every 72 h, no battery, no car.

Each test is one thing they asked for or complained about, run through the
real engine (``SurplusController``) and the real tank (``HotWaterController``).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import patch

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.plan_verdict import PlanVerdict
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices import hot_water_controller as hwc
from custom_components.solar_energy_management.devices.base import DeviceControlMode
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)

SENSOR, SWITCH, DID = "sensor.tank", "switch.boiler", "hot_water"
BLOCK = PlanVerdict(in_block=True, comfort_in_block=True, reason="comfort block open")
#: what a real plan says once the block is over: hold, the window closed
CLOSED = PlanVerdict(hold=True, reason="joint energy plan: window closed")


def _boiler(temp, *, buy=True, stop=None):
    hass = _Hass()
    hass.set(SWITCH, "off")
    hass.set(SENSOR, str(temp), unit_of_measurement="°C")
    dev = HotWaterController(
        hass=hass, entity_id=SWITCH, temperature_entity_id=SENSOR,
        solar_target_temp=55.0, rated_power=2500.0, legionella_target_temp=60.0)
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity = SENSOR
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = 52.0, 4.0, 36.0
    dev.top_up_policy = "cheap_hours" if buy else "solar_only"
    dev.min_on_seconds = dev.min_off_seconds = 1800
    if stop is not None:
        dev.stop_entity, dev.stop_at = SENSOR, stop
    dev.withheld_commands = []
    dev._last_legionella_time = hwc.dt_util.now() - timedelta(hours=10)
    sc = SurplusController(hass)
    sc.register_device(dev)
    return hass, dev, sc


async def _cycle(sc, *, surplus=-400.0, price="normal", night=True, block=False, solar=0.0):
    await sc.update(
        surplus, price_level=price, is_night=night, battery_soc=None,
        battery_reserve_soc=10.0, daylight_remaining_s=0.0 if night else 7200.0,
        solar_w=solar,
        plan_windows=({DID: BLOCK} if block is True
                      else {DID: CLOSED} if block == "closed" else {}))


def _past_minimums(dev):
    long_ago = datetime.now() - timedelta(hours=1)
    dev._last_activated = long_ago
    dev._status.last_activated = long_ago
    dev._last_deactivated = long_ago


# ── 1. the original report ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_1_solar_only_stops_when_the_house_buys():
    """ "SEM keeps my boiler enabled after I started importing." """
    hass, dev, sc = _boiler(45.0, buy=False)
    await _cycle(sc, surplus=4000.0, night=False, solar=5000.0)
    assert dev.is_active
    _past_minimums(dev)
    for _ in range(12):                      # the sun is gone, the house buys
        await _cycle(sc, surplus=-2500.0, night=False, solar=600.0)
    assert not dev.is_active


# ── 2. "Keep at should be a target" ───────────────────────────────────────

@pytest.mark.asyncio
async def test_2_a_cheap_hour_heats_to_keep_at_not_to_the_blocks_end():
    """ "It does not heat the water at 52 °C but somehow 50 °C." The planned
    block is an estimate (2.5 kW told, 3.2 kW real): when it ends at 50 °C
    the run goes on to 52 °C while the hour is still cheap."""
    hass, dev, sc = _boiler(47.6)
    await _cycle(sc, price="cheap", block=True)
    assert dev.is_active
    hass.set(SENSOR, "50.1", unit_of_measurement="°C")
    _past_minimums(dev)
    for verdict in (False, "closed"):        # no opinion, or the plan's hold
        await _cycle(sc, price="cheap", block=verdict)   # the block is over
        assert dev.is_active, f"the run ended at the block's end ({verdict})"
    hass.set(SENSOR, "52.0", unit_of_measurement="°C")
    await _cycle(sc, price="cheap", block="closed")
    await _cycle(sc, price="cheap", block="closed")
    assert not dev.is_active                              # Keep at reached


@pytest.mark.asyncio
async def test_2b_it_never_runs_on_into_an_hour_that_is_not_cheap():
    hass, dev, sc = _boiler(47.6)
    await _cycle(sc, price="cheap", block=True)
    hass.set(SENSOR, "50.1", unit_of_measurement="°C")
    _past_minimums(dev)
    await _cycle(sc, price="normal", block="closed", night=False)
    await _cycle(sc, price="normal", block="closed", night=False)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_2c_no_cheap_run_starts_without_a_planned_block():
    hass, dev, sc = _boiler(47.6)
    await _cycle(sc, price="cheap", block=False)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_2d_solar_only_never_buys_for_keep_at():
    hass, dev, sc = _boiler(47.6, buy=False)
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active


# ── 3. the sun heats past Keep at, to Keep at + Extra ─────────────────────

@pytest.mark.asyncio
async def test_3_the_sun_heats_to_56_not_to_the_old_55_or_50():
    hass, dev, sc = _boiler(51.0)
    await _cycle(sc, surplus=4000.0, night=False, solar=5000.0)
    assert dev.is_active
    hass.set(SENSOR, "55.5", unit_of_measurement="°C")    # past the Solar target 55
    await _cycle(sc, surplus=4000.0, night=False, solar=5000.0)
    assert dev.is_active
    hass.set(SENSOR, "56.0", unit_of_measurement="°C")
    await _cycle(sc, surplus=4000.0, night=False, solar=5000.0)
    assert not dev.is_active


# ── 4. no daily run time needed; too cold heats at any price ──────────────

@pytest.mark.asyncio
async def test_4_too_cold_heats_at_once_on_any_tariff_up_to_keep_at():
    hass, dev, sc = _boiler(35.5)
    assert dev.has_runtime_deficit is False or dev.comfort_state == "forced"
    await _cycle(sc, price="expensive", night=False)
    assert dev.is_active
    hass.set(SENSOR, "45.0", unit_of_measurement="°C")
    _past_minimums(dev)
    await _cycle(sc, price="expensive", night=False)
    assert dev.is_active                                   # goes on to Keep at
    hass.set(SENSOR, "52.0", unit_of_measurement="°C")
    await _cycle(sc, price="expensive", night=False)
    await _cycle(sc, price="expensive", night=False)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_4b_a_band_tank_needs_no_daily_run_time():
    """ "Minimal runtime per day should not be required for hot water." """
    hass, dev, sc = _boiler(53.0)
    dev.daily_min_runtime_min = 60
    for _ in range(6):                      # warm tank, cheap hour, block open
        await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active


# ── 5. Legionella and their own stop at 53 °C ─────────────────────────────

@pytest.mark.asyncio
async def test_5_a_stop_below_the_legionella_target_never_heats_for_it():
    """ "The run never ended and switched the boiler on again, also on grid
    power." Now it does not start at all, and is not counted as done."""
    hass, dev, sc = _boiler(45.0, stop=53.0)
    dev._last_legionella_time = hwc.dt_util.now() - timedelta(hours=80)
    for _ in range(8):
        out = await dev.check_legionella_cycle(good_hour=False)
        await _cycle(sc)
    assert not dev.is_active and not hass.calls("turn_on", SWITCH)
    assert dev.legionella_blocked_by_stop is True
    assert (hwc.dt_util.now() - dev._last_legionella_time) > timedelta(hours=79)
    assert out is None or "started" not in out


@pytest.mark.asyncio
async def test_5b_without_a_stop_the_due_run_reaches_60_and_ends():
    hass, dev, sc = _boiler(50.0)
    dev._last_legionella_time = hwc.dt_util.now() - timedelta(hours=80)
    t0 = hwc.dt_util.now()

    async def at(minute, temp):
        hass.set(SENSOR, str(temp), unit_of_measurement="°C")
        with patch.object(hwc.dt_util, "now", return_value=t0 + timedelta(minutes=minute)):
            out = await dev.check_legionella_cycle(good_hour=False)
            await _cycle(sc)
        return out

    assert await at(0, 50.0) == "legionella_started"
    assert dev.is_active
    await at(60, 60.2)
    assert await at(60 + dev.legionella_hold_minutes + 1, 60.1) == "legionella_complete"
    await at(60 + dev.legionella_hold_minutes + 2, 60.0)
    assert not dev.is_active


# ── 6. "I often don't know why SEM schedules my boiler" ───────────────────

@pytest.mark.asyncio
async def test_6_every_start_and_stop_carries_a_reason():
    hass, dev, sc = _boiler(47.6)
    await _cycle(sc, price="cheap", block=True)
    hass.set(SENSOR, "52.0", unit_of_measurement="°C")
    _past_minimums(dev)
    await _cycle(sc, price="cheap", block=False)
    await _cycle(sc, price="cheap", block=False)
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    assert records and all(r.get("reason_code") for r in records), records
    assert records[0]["reason_code"] == RC.LOAD_COMFORT_GOAL


# ── 7. the Solar heating target moves in whole degrees ────────────────────

def test_7_the_solar_target_has_one_degree_steps():
    from custom_components.solar_energy_management import number as number_mod
    desc = next(d for d in number_mod.NUMBER_TYPES
                if d.key == "hot_water_solar_target")
    assert desc.native_step == 1


# ── 8. found by running the real planner (ruflo use-case round) ────────────

@pytest.mark.asyncio
async def test_8_a_bought_run_stops_at_keep_at_inside_its_minimum_run():
    """A 30 min minimum run carried a bought run 2–4 K past Keep at."""
    hass, dev, sc = _boiler(51.0)
    await _cycle(sc, price="cheap", block=True)
    assert dev.is_active and dev.can_deactivate() is False
    hass.set(SENSOR, "52.1", unit_of_measurement="°C")
    await _cycle(sc, price="cheap", block=True)
    assert not dev.is_active


def test_8b_a_tank_that_cools_after_the_plan_was_made_replans():
    """A shower at 22:30: the plan made at 14:00 had no block. The plan's
    signature now carries the Keep at goal, with no learned model needed."""
    from custom_components.solar_energy_management.coordinator.coordinator import (
        demand_signature_changed)
    from custom_components.solar_energy_management.tests.test_638_demand_replan import (
        _coord, _power)
    hass, dev, sc = _boiler(55.0)
    warm = _coord(devices=(dev,))._energy_plan_demand_signature(_power())
    hass.set(SENSOR, "47.0", unit_of_measurement="°C")
    cold = _coord(devices=(dev,))._energy_plan_demand_signature(_power())
    assert demand_signature_changed(warm, cold) is True
    hass.set(SENSOR, "46.0", unit_of_measurement="°C")       # cooling on: silence
    colder = _coord(devices=(dev,))._energy_plan_demand_signature(_power())
    assert demand_signature_changed(cold, colder) is False


def test_8c_the_boilers_own_thermostat_is_named():
    """SEM has it on, it draws nothing, the tank sits at 50 °C: the boiler's
    own thermostat stopped it. The card says so with the temperature."""
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry)
    hass, dev, sc = _boiler(50.0)
    dev.power_entity_id = "sensor.boiler_power"
    hass.set("sensor.boiler_power", "0", unit_of_measurement="W")
    t0 = hwc.dt_util.now()
    for minute in (0, 5, 11):
        with patch.object(hwc.dt_util, "now", return_value=t0 + timedelta(minutes=minute)), \
                patch.object(type(dev), "is_active", new=True):
            dev.check_heating_works()
    assert dev.own_thermostat_c == 50.0
    assert UnifiedDeviceRegistry._band_lines(dev)["own_thermostat_c"] == 50.0
    hass.set("sensor.boiler_power", "3200", unit_of_measurement="W")
    with patch.object(type(dev), "is_active", new=True):
        dev.check_heating_works()
    assert dev.own_thermostat_c is None                      # it heats again


@pytest.mark.asyncio
async def test_8d_a_run_for_keep_at_that_reaches_it_says_so():
    """A too-cold run that reached Keep at was logged "not enough spare sun"."""
    hass, dev, sc = _boiler(35.5)
    await _cycle(sc, price="normal", night=False)
    hass.set(SENSOR, "52.1", unit_of_measurement="°C")
    await _cycle(sc, price="normal", night=False)
    assert not dev.is_active
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    assert records[-1]["reason_code"] == RC.LOAD_AT_TARGET, records[-1]


# ── 9. a day with one price (weekend on a two-rate tariff, a flat tariff) ──

def _one_price_night(sun_hours=()):
    from custom_components.solar_energy_management.coordinator.energy_planner import (
        LedgerSlot, build_night_ledger)
    t0 = datetime(2026, 11, 14, 18, 0)            # a Saturday evening
    slots = []
    for h in range(14):                            # 18:00 → 08:00
        t = t0 + timedelta(hours=h)
        slots.append(LedgerSlot(
            start=t, end=t + timedelta(hours=1), price=0.6,
            level_cheap=False, tariff_cheap=True, home_w=0.0,
            solar_w=3000.0 if t.hour in sun_hours else 0.0))
    return t0, build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                  max_discharge_w=0.0, peak_limit_w=8000.0)


def _keep_at_demand(deadline, **kw):
    from custom_components.solar_energy_management.coordinator.energy_planner import Demand
    return Demand(id="comfort:hot_water", kind="comfort", energy_kwh=2.5,
                  max_power_w=2500.0, min_power_w=2500.0, deadline=deadline,
                  source="grid", needs_cheap_level=True, unpriced_ok=True, **kw)


def test_9_a_one_price_night_still_gets_its_keep_at_hour():
    """Saturday night: no hour is cheaper than another. Before, nothing was
    planned and the tank cooled to its too-cold limit."""
    from custom_components.solar_energy_management.coordinator.energy_planner import pack_night
    t0, ledger = _one_price_night()
    end = t0 + timedelta(hours=14)
    old = pack_night([_keep_at_demand(end)], ledger, peak_limit_w=8000.0)
    assert not old.allocations                            # the old answer
    plan = pack_night([_keep_at_demand(end, one_price_ok=True)], ledger,
                      peak_limit_w=8000.0)
    assert plan.allocations, plan.results
    assert sum(a.energy_kwh for a in plan.allocations) == pytest.approx(2.5, abs=0.05)


def test_9b_never_in_a_sun_hour_and_not_when_a_cheap_hour_exists():
    from custom_components.solar_energy_management.coordinator.energy_planner import pack_night
    t0, ledger = _one_price_night(sun_hours=(18, 19))
    end = t0 + timedelta(hours=14)
    plan = pack_night([_keep_at_demand(end, one_price_ok=True)], ledger,
                      peak_limit_w=8000.0)
    assert plan.allocations
    assert all(a.start.hour not in (18, 19) for a in plan.allocations)
    # a night that HAS a cheap hour keeps using only that
    for s in ledger:
        if s.start.hour == 2:
            s.level_cheap = True
    plan = pack_night([_keep_at_demand(end, one_price_ok=True)], ledger,
                      peak_limit_w=8000.0)
    assert {a.start.hour for a in plan.allocations} == {2}


@pytest.mark.asyncio
async def test_9c_on_a_one_price_day_the_run_also_heats_on_to_keep_at():
    hass, dev, sc = _boiler(47.6)
    await _cycle(sc, price="normal", block=True)          # one price: "normal"
    assert dev.is_active
    hass.set(SENSOR, "50.1", unit_of_measurement="°C")
    _past_minimums(dev)
    await _cycle(sc, price="normal", block="closed")
    assert dev.is_active
    # the price goes up: it stops
    await _cycle(sc, price="expensive", block="closed", night=False)
    await _cycle(sc, price="expensive", block="closed", night=False)
    assert not dev.is_active


@pytest.mark.asyncio
async def test_9d_a_run_started_cheap_stops_when_the_cheap_hours_end():
    hass, dev, sc = _boiler(47.6)
    await _cycle(sc, price="cheap", block=True)
    hass.set(SENSOR, "50.1", unit_of_measurement="°C")
    _past_minimums(dev)
    await _cycle(sc, price="normal", block="closed", night=False)   # 07:00, high tariff
    await _cycle(sc, price="normal", block="closed", night=False)
    assert not dev.is_active
