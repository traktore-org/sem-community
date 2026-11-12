"""#1334 — a comfort block turned a load on and off when Grid was Off.

The old comfort-banking pass started a load from the grid in its planned
comfort block; the next cycle the force-expiry pass stopped it as
"cheap-hours disabled by user" ("Finish overnight via: Off"), and one
minimum pause later the banking pass started it again. On "Grid" the same
happened when a planned sun hour turned cloudy and the price was not cheap.

Since #1335 one rule decides the start and the stop: layer 1's banking
clause. With the grid allowed for the load ("Finish overnight via: Grid")
it runs while the plan's comfort block is open and the tank is below Keep
at, and stops once: at Keep at, or when the block closes. With the grid
not allowed, solar only is solar only (#1102): the block buys nothing, so
there is nothing to switch on and off.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.plan_verdict import (
    PlanVerdict,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices.base import (
    DeviceControlMode,
    SwitchDevice,
)
from custom_components.solar_energy_management.tests.test_1062_hot_water_fields import (
    _Hass,
)

TANK = "sensor.tank"
BLOCK = {"boiler": PlanVerdict(in_block=True, comfort_in_block=True,
                               reason="planned block")}


def _boiler(hass, policy):
    hass.set("switch.boiler", "off")
    hass.set(TANK, "45", unit_of_measurement="°C")
    dev = SwitchDevice(hass, "boiler", "Boiler", rated_power=3000.0,
                       entity_id="switch.boiler")
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity, dev.comfort_target = TANK, 50.0
    dev.comfort_offset, dev.comfort_limit = 5.0, 36.0
    dev.top_up_policy = policy
    # no anti-cycle help: a stop/start pair would show at once
    dev.min_on_seconds = dev.min_off_seconds = 0
    dev.min_on_time = dev.min_off_time = 0
    sc = SurplusController(hass)
    sc.register_device(dev)
    return sc, dev


async def _block(sc, n, *, price, solar_w=0.0, plan=BLOCK):
    for _ in range(n):
        await sc.update(0.0, price_level=price, plan_windows=plan,
                        is_night=solar_w <= 0, solar_w=solar_w)


@pytest.mark.asyncio
@pytest.mark.parametrize("policy, price, solar_w", [
    ("cheap_hours", "normal", 0.0),     # Finish overnight via: Grid
    ("cheap_hours", "expensive", 0.0),
    ("cheap_hours", "normal", 400.0),   # Grid, a planned sun hour gone cloudy
])
async def test_1334_a_full_comfort_block_runs_without_cycling(policy, price, solar_w):
    hass = _Hass()
    sc, dev = _boiler(hass, policy)

    await _block(sc, 60, price=price, solar_w=solar_w)       # the whole block
    assert dev.is_active
    assert len(hass.calls("turn_on")) == 1, "started more than once"
    assert not hass.calls("turn_off"), "stopped inside its block"
    start = [r for r in sc.decision_log.records() if r["device_id"] == "boiler"]
    assert [(r["new"], r["reason_code"]) for r in start] == [
        ("on", RC.LOAD_COMFORT_GOAL)]

    hass.set(TANK, "50.5", unit_of_measurement="°C")         # Keep at reached
    await _block(sc, 20, price=price, solar_w=solar_w)
    assert not dev.is_active
    assert len(hass.calls("turn_off")) == 1 and len(hass.calls("turn_on")) == 1


@pytest.mark.asyncio
async def test_1334_the_block_closing_ends_it_once():
    hass = _Hass()
    sc, dev = _boiler(hass, "cheap_hours")
    await _block(sc, 10, price="normal")
    assert dev.is_active
    await _block(sc, 20, price="normal", plan={})            # block over
    assert not dev.is_active
    assert len(hass.calls("turn_off")) == 1 and len(hass.calls("turn_on")) == 1


@pytest.mark.asyncio
async def test_1334_without_a_block_grid_off_never_buys():
    """The other side of the rule: no comfort block, no sun — a willing
    band with "Finish overnight via: Off" stays off."""
    hass = _Hass()
    sc, dev = _boiler(hass, "solar_only")
    await _block(sc, 20, price="cheap", plan={})
    assert not dev.is_active and not hass.calls("turn_on")


@pytest.mark.asyncio
@pytest.mark.parametrize("price", ["cheap", "normal", "expensive"])
async def test_1334_grid_off_buys_nothing_in_a_comfort_block(price):
    """Solar only is solar only (#1102): with "Finish overnight via: Off" a
    comfort block starts nothing from the grid — and so switches nothing."""
    hass = _Hass()
    sc, dev = _boiler(hass, "solar_only")
    await _block(sc, 60, price=price)
    assert not dev.is_active
    assert not hass.calls("turn_on") and not hass.calls("turn_off")


@pytest.mark.asyncio
async def test_1334_grid_off_still_heats_on_sun_and_when_too_cold():
    hass = _Hass()
    sc, dev = _boiler(hass, "solar_only")
    await sc.update(4000.0, price_level="normal", plan_windows=BLOCK,
                    is_night=False, solar_w=5000.0)
    assert dev.is_active, "spare sun heats a solar-only tank"
    hass2 = _Hass()
    sc2, dev2 = _boiler(hass2, "solar_only")
    hass2.set(TANK, "34", unit_of_measurement="°C")       # under Run now past 36
    await _block(sc2, 3, price="expensive", plan={})
    assert dev2.is_active, "the too-cold limit heats at once, whatever the mode"
