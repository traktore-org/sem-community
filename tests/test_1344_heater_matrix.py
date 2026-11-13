"""#1344 — what every heater does in every situation, as ONE table.

The hot-water area produced one issue per rule: each rule was tested alone,
on one device class, and the #1335 audit checked WHERE loads are switched
(one seam), not WHAT a heater does. This file runs the real
``SurplusController`` — layers 1, 2 and 3, no mocked decision — for every
combination of

    device class   every class that carries the comfort band (discovered)
    grid setting   solar_only · cheap_hours · battery
    tank state     too cold · below the start line · inside the start gap ·
                   at Keep at · above Keep at + Extra · no reading ·
                   under your own stop · at your own stop · too cold but
                   past your own stop
    situation      night with its planned hour open · night with no plan ·
                   day with spare sun · day with too little sun · peak shed ·
                   Mode Off · watch-only (observer)
    away           the house is away, or not

and compares the outcome with ``_spec``, one small function written from
docs/USER_GUIDE.md, "Keep at, Extra from surplus, Run now past":

    own stop → Legionella → too cold → Keep at in its planned hour, if the
    grid is allowed → sun up to Keep at + Extra → nothing; and while away
    only the too-cold limit heats, back above the limit and no further.

A second table runs the Legionella run of every class that has one.

A new class that gains the band enters the matrix by itself; without a
factory here the first test fails and names it.
"""
from __future__ import annotations

import itertools
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.plan_verdict import PlanVerdict
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.devices import (  # noqa: F401 — import = discovery
    heat_pump_controller, hot_water_controller, power_setpoint,
)
from custom_components.solar_energy_management.devices.base import (
    BandedCurrentLoad, ClimateDevice, ComfortBandMixin, DeviceControlMode,
    SwitchDevice,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)
from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
)
from custom_components.solar_energy_management.devices.power_setpoint import (
    PowerSetpointDevice,
)
from custom_components.solar_energy_management.features.load_management import (
    LoadManagementState,
)

TANK = "sensor.tank"
DID = "heater"
KEEP, EXTRA, LIMIT = 50.0, 5.0, 36.0          # start line 49, ceiling 55
CYCLES = 30

GRID = ("solar_only", "cheap_hours", "battery")
#: tank state -> (reading in °C, the user's own stop temperature or None)
TANKS = {
    "too_cold": (34.0, None), "below_start": (45.0, None), "in_gap": (49.5, None),
    "at_keep": (50.0, None), "above_ceiling": (56.0, None), "no_reading": (None, None),
    # "Stop when": the first rung. Under it the ladder runs as usual; at or
    # above it nothing starts and a run ends, whatever else says go.
    "under_own_stop": (52.0, 53.0), "at_own_stop": (53.5, 53.0),
    "too_cold_past_own_stop": (34.0, 30.0),
}
SITUATIONS = ("night_block", "night_no_block", "day_sun", "day_little_sun",
              "peak_shed", "mode_off", "observer",
              # (#1349) "Finish overnight from: Battery": the house battery
              # above its reserve, and at it
              "night_battery_ok", "night_battery_low")
AWAY = (False, True)


class _Hass:
    """A state table and the few services these devices call."""

    def __init__(self):
        self._states: dict = {}
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
        self.states = MagicMock()
        self.states.get = self._states.get
        self.states.is_state = lambda eid, v: (
            eid in self._states and self._states[eid].state == v)
        self.services = MagicMock()
        self.services.has_service = lambda *_a, **_k: True
        self.services.async_call = AsyncMock(side_effect=self._call)
        self.data = {}

    def set(self, entity_id, state, **attributes):
        old = self._states.get(entity_id)
        attrs = dict(getattr(old, "attributes", {}) or {})
        attrs.update(attributes)
        self._states[entity_id] = SimpleNamespace(
            entity_id=entity_id, state=str(state), attributes=attrs)

    async def _call(self, domain, service, data=None, **_kw):
        data = data or {}
        eid = data.get("entity_id")
        if not eid:
            return
        if service == "turn_on":
            self.set(eid, "heat" if eid.startswith("climate.") else "on")
        elif service == "turn_off":
            self.set(eid, "off")
        elif service == "set_value":
            self.set(eid, data.get("value"))
        elif service == "set_hvac_mode":
            self.set(eid, data.get("hvac_mode"))
        elif service == "set_temperature":
            self.set(eid, self._states[eid].state,
                     temperature=data.get("temperature"))

    def writes(self):
        return [c.args[:3] for c in self.services.async_call.await_args_list]


def _switch(hass):
    hass.set("switch.heater", "off")
    return SwitchDevice(hass, DID, "Heater", rated_power=3000.0,
                        entity_id="switch.heater")


def _climate(hass):
    hass.set("climate.heater", "off", hvac_modes=["off", "heat"])
    return ClimateDevice(hass, DID, "Heater", rated_power=3000.0,
                         entity_id="climate.heater", hvac_mode="heat")


def _hot_water(hass):
    hass.set("switch.heater", "off")
    return HotWaterController(hass=hass, device_id=DID, name="Heater",
                              rated_power=3000.0, entity_id="switch.heater",
                              temperature_entity_id=TANK, solar_target_temp=70.0)


def _heat_pump(hass):
    hass.set("switch.relay1", "off")
    hass.set("switch.relay2", "off")
    return HeatPumpController(hass=hass, device_id=DID, name="Heater",
                              rated_power=3000.0, min_power_threshold=3000.0,
                              relay1_entity_id="switch.relay1",
                              relay2_entity_id="switch.relay2",
                              min_power_change_interval=0.0)


def _watts(hass):
    hass.set("number.heater", "0", unit_of_measurement="W", min=0, max=3000, step=1)
    return PowerSetpointDevice(hass, DID, "Heater", rated_power=3000.0,
                               entity_id="number.heater")


def _amps(hass):
    hass.set("number.heater", "0", unit_of_measurement="A", min=0, max=13, step=1)
    return BandedCurrentLoad(hass=hass, device_id=DID, name="Heater",
                             min_current=6.0, max_current=13.0, phases=1,
                             voltage=230.0, current_entity_id="number.heater")


FACTORIES = {
    SwitchDevice: _switch, ClimateDevice: _climate,
    HotWaterController: _hot_water, HeatPumpController: _heat_pump,
    PowerSetpointDevice: _watts, BandedCurrentLoad: _amps,
}


def _banded_classes():
    seen, todo = [], list(ComfortBandMixin.__subclasses__())
    while todo:
        cls = todo.pop()
        if cls not in seen:
            seen.append(cls)
            todo.extend(cls.__subclasses__())
    return [c for c in seen
            if c.__module__.startswith("custom_components.solar_energy_management.devices")]


def test_every_class_with_the_band_is_in_the_matrix():
    missing = [c.__name__ for c in _banded_classes() if c not in FACTORIES]
    assert not missing, (
        f"{missing} carry the comfort band but have no factory in "
        "tests/test_1344_heater_matrix.py — add one, so the matrix runs them")


#: (the guide, "no reading") A tank whose OWN temperature sensor is set up
#: but silent is not heated blind. Every other class without a reading has no
#: band at all and runs as a plain load.
REFUSES_BLIND = {HotWaterController}


def _build(cls, grid, tank, situation, away=False):
    hass = _Hass()
    dev = FACTORIES[cls](hass)
    reading, own_stop = TANKS[tank]
    hass.set(TANK, "unavailable" if reading is None else reading,
             unit_of_measurement="°C")
    dev.control_mode = (DeviceControlMode.OFF if situation == "mode_off"
                        else DeviceControlMode.SURPLUS)
    dev.comfort_entity = TANK
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = KEEP, EXTRA, LIMIT
    if own_stop is not None:
        dev.stop_entity, dev.stop_at = TANK, own_stop
    dev.top_up_policy = "cheap_hours" if grid == "cheap_hours" else "solar_only"
    dev.battery_eligible_overnight = grid == "battery"
    # nothing hides a flap: no minimum run, pause or start delay
    for attr in ("min_on_seconds", "min_off_seconds", "min_on_time",
                 "min_off_time", "activation_delay_seconds",
                 "min_power_change_interval", "_min_power_change_interval"):
        if hasattr(dev, attr):
            setattr(dev, attr, 0)
    # the one stamp the coordinator makes on every device with the band
    dev.vacation = bool(away)
    sc = SurplusController(hass, regulation_offset=0)
    sc.register_device(dev)
    return hass, sc, dev


def _inputs(situation):
    block = {DID: PlanVerdict(in_block=True, comfort_in_block=True,
                              reason="planned block")}
    night = dict(available_power_w=0.0, price_level="normal", is_night=True,
                 solar_w=0.0, plan_windows=block)
    if situation == "night_no_block":
        return {**night, "plan_windows": {}}
    if situation == "night_battery_ok":
        return {**night, "plan_windows": {}, "battery_soc": 80.0,
                "battery_reserve_soc": 20.0}
    if situation == "night_battery_low":
        return {**night, "plan_windows": {}, "battery_soc": 20.0,
                "battery_reserve_soc": 20.0}
    if situation == "day_sun":
        return dict(available_power_w=6000.0, price_level="normal",
                    is_night=False, solar_w=8000.0, plan_windows={},
                    daylight_remaining_s=4 * 3600.0)
    if situation == "day_little_sun":
        return dict(available_power_w=300.0, price_level="normal",
                    is_night=False, solar_w=800.0, plan_windows={},
                    daylight_remaining_s=4 * 3600.0)
    if situation == "peak_shed":
        return {**night, "peak_state": LoadManagementState.EMERGENCY}
    if situation == "observer":
        return {**night, "observer": True}
    return night            # night_block, mode_off


def _spec(cls, grid, tank, situation, away):
    """(on, family) per the User Guide. family: floor · floor_away · goal ·
    sun · none. Written from the guide alone — it asks the device nothing."""
    off = (False, "none")
    reading, own_stop = TANKS[tank]
    if situation == "mode_off":
        return off                      # SEM does not drive it
    if situation == "peak_shed":
        return off                      # a shed outranks every run
    if own_stop is not None and reading is not None and reading >= own_stop:
        return off                      # your own stop is the first rung
    if away:
        # no Keep at run, no banking: only the too-cold limit heats
        return (True, "floor_away") if tank == "too_cold" else off
    sun = situation == "day_sun"
    if reading is None:
        # no reading: the band does nothing — no planned run, no too-cold
        # run. The load runs as a plain load on spare sun, unless its own
        # sensor is the silent one (it is not heated blind).
        return (True, "sun") if sun and cls not in REFUSES_BLIND else off
    if reading <= LIMIT:
        return (True, "floor")          # at once, on any tariff
    if reading >= KEEP + EXTRA:
        return off
    if (reading <= KEEP - 1.0 and grid == "cheap_hours"
            and situation in ("night_block", "observer")):
        return (True, "goal")           # bought, in its planned hour
    if (reading <= KEEP - 1.0 and grid == "battery"
            and situation == "night_battery_ok"):
        return (True, "goal_battery")   # at night, from the house battery
    if sun:
        return (True, "sun")            # up to Keep at + Extra
    return off


def _family(code, source):
    if code == RC.LOAD_COMFORT_FLOOR:
        return "floor"
    if code == RC.LOAD_COMFORT_FLOOR_AWAY:
        return "floor_away"
    if code == RC.LOAD_COMFORT_GOAL:
        return "goal"
    if code == RC.LOAD_COMFORT_GOAL_BATTERY:
        return "goal_battery"
    if code == RC.LOAD_LEGIONELLA:
        return "legionella"
    return "sun" if source in ("solar", "tier1_battery") or code in (
        "solar", "tier1_battery") else "other"


def _where(cls, grid, tank, situation, away):
    reading, own_stop = TANKS.get(tank, (tank, None))
    return (f"{cls.__name__} · grid {grid} · tank {tank} ({reading} °C"
            f"{'' if own_stop is None else f', own stop {own_stop} °C'}) · "
            f"{situation} · {'away' if away else 'at home'}")


def _check(hass, sc, dev, where, situation, want_on, want_family, grid):
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    # a watt or ampere load's record reads "on 3000 W"
    starts = [r for r in records if str(r["new"]).startswith("on")]
    stops = [r for r in records if str(r["new"]).startswith("off")]

    if situation == "observer":
        assert not hass.writes(), f"{where}: wrote {hass.writes()[:2]} while only watching"
        assert not dev.is_active, f"{where}: believed running while only watching"
        return

    assert len(starts) <= 1 and len(stops) <= 1, (
        f"{where}: flapped — {len(starts)} starts, {len(stops)} stops in "
        f"{CYCLES} cycles: {[(r['new'], r['reason_code']) for r in records][:6]}")
    assert dev.is_active is want_on, (
        f"{where}: expected {'on' if want_on else 'off'} ({want_family}), is "
        f"{'on' if dev.is_active else 'off'}; decisions "
        f"{[(r['new'], r['reason_code']) for r in records][:4]}")
    if not want_on:
        assert not starts, f"{where}: was started ({starts[0]['reason_code']}) and stopped again"
        return
    got = _family(starts[0]["reason_code"], starts[0].get("source"))
    assert got == want_family, (
        f"{where}: expected a {want_family} run, got {got} "
        f"(code {starts[0]['reason_code']})")
    if got == "goal_battery":
        assert grid == "battery", f"{where}: took the house battery without the user's word"
    elif grid != "cheap_hours" and got not in ("floor", "floor_away", "sun", "legionella"):
        pytest.fail(f"{where}: bought power without the grid allowed ({got})")


CELLS = [
    pytest.param(cls, grid, tank, situation, away,
                 id=f"{cls.__name__}-{grid}-{tank}-{situation}-{'away' if away else 'home'}")
    for cls, grid, tank, situation, away in itertools.product(
        FACTORIES, GRID, TANKS, SITUATIONS, AWAY)
]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls, grid, tank, situation, away", CELLS)
async def test_a_heater_does_what_the_guide_says(cls, grid, tank, situation, away):
    hass, sc, dev = _build(cls, grid, tank, situation, away)
    where = _where(cls, grid, tank, situation, away)
    want_on, want_family = _spec(cls, grid, tank, situation, away)
    kw = _inputs(situation)
    power = kw.pop("available_power_w")
    for _ in range(CYCLES):
        await sc.update(power, **kw)
    _check(hass, sc, dev, where, situation, want_on, want_family, grid)


# ── away: the too-cold run heats back above the limit, and no further ─────

@pytest.mark.asyncio
@pytest.mark.parametrize("cls", list(FACTORIES), ids=lambda c: c.__name__)
async def test_away_the_too_cold_run_ends_just_above_the_limit(cls):
    """Limit 36, start gap 1: it starts at or under 36, runs on at 36.5 and
    stops at 37 — it is not taken on to Keep at 50, and 36.5 does not start it."""
    hass, sc, dev = _build(cls, "cheap_hours", "too_cold", "night_block", away=True)
    kw = _inputs("night_block")
    power = kw.pop("available_power_w")
    await _run(sc, 5, power, **kw)
    assert dev.is_active, f"{cls.__name__}: too cold while away must heat"
    hass.set(TANK, 36.5, unit_of_measurement="°C")
    await _run(sc, 5, power, **kw)
    assert dev.is_active, f"{cls.__name__}: stopped inside the gap above the limit"
    hass.set(TANK, 37.2, unit_of_measurement="°C")
    await _run(sc, 5, power, **kw)
    assert not dev.is_active, f"{cls.__name__}: heated on past the limit while away"
    hass.set(TANK, 36.5, unit_of_measurement="°C")
    await _run(sc, 5, power, **kw)
    assert not dev.is_active, f"{cls.__name__}: restarted inside the gap"
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    assert [r["reason_code"] for r in records if str(r["new"]).startswith("on")] == [
        RC.LOAD_COMFORT_FLOOR_AWAY]
    assert len([r for r in records if str(r["new"]).startswith("off")]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", list(FACTORIES), ids=lambda c: c.__name__)
async def test_going_away_ends_a_keep_at_run_and_the_plan_is_asked_nothing(cls):
    hass, sc, dev = _build(cls, "cheap_hours", "below_start", "night_block")
    kw = _inputs("night_block")
    power = kw.pop("available_power_w")
    await _run(sc, 5, power, **kw)
    assert dev.is_active
    assert dev.comfort_plan_demand(None, goal=True) is not None
    dev.vacation = True
    await _run(sc, 5, power, **kw)
    assert not dev.is_active, f"{cls.__name__}: kept heating to Keep at while away"
    assert dev.comfort_plan_demand(None, goal=True) is None
    assert dev.comfort_state == "disengaged" and dev.away_pauses() is True


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", [c for c in FACTORIES if c.away_needs_band],
                         ids=lambda c: c.__name__)
async def test_away_leaves_a_load_without_a_band_alone(cls):
    """A load SEM found is a heater only once its band is set up."""
    hass, sc, dev = _build(cls, "solar_only", "below_start", "day_sun", away=True)
    dev.comfort_target = dev.comfort_limit = dev.comfort_offset = 0.0
    kw = _inputs("day_sun")
    await _run(sc, 5, kw.pop("available_power_w"), **kw)
    assert dev.away_pauses() is False
    assert dev.is_active, f"{cls.__name__}: a plain load was paused by away"


# ── Legionella: every class that has the run ──────────────────────────────

LEGIONELLA_CLASSES = [c for c in FACTORIES if hasattr(c, "check_legionella_cycle")]
LEGIONELLA_CASES = {
    # case -> (reading, own stop)
    "due_below_target": (45.0, None),
    "due_own_stop_already_met": (54.0, 53.0),
    "due_no_reading": (None, None),
}
LEGIONELLA_SITUATIONS = ("night_no_block", "day_sun", "peak_shed", "mode_off", "observer")


def test_a_class_with_a_legionella_run_is_in_its_table():
    assert LEGIONELLA_CLASSES, "no class with a Legionella run was found"


def _legionella_spec(cls, case, situation, away):
    """The run outranks the band and needs no sun; it heats to its OWN
    target. A shed, Mode Off and away (paused, #594) stop it from starting;
    your own stop under its target ends it (#1102); no reading, no run."""
    off = (False, "none")
    reading, own_stop = LEGIONELLA_CASES[case]
    if situation in ("mode_off", "peak_shed"):
        return off
    if own_stop is not None and reading >= own_stop:
        return off
    if reading is None:
        return off                      # no run, and not heated blind
    if away:
        return off                      # paused; 45 °C is not too cold
    return (True, "legionella")


@pytest.mark.asyncio
@pytest.mark.parametrize("cls, grid, case, situation, away", [
    pytest.param(c, g, k, s, a, id=f"{c.__name__}-{g}-{k}-{s}-{'away' if a else 'home'}")
    for c, g, k, s, a in itertools.product(
        LEGIONELLA_CLASSES, GRID, LEGIONELLA_CASES, LEGIONELLA_SITUATIONS, AWAY)
])
async def test_a_legionella_run_does_what_the_guide_says(cls, grid, case, situation, away):
    hass, sc, dev = _build(cls, grid, "below_start", situation, away)
    reading, own_stop = LEGIONELLA_CASES[case]
    hass.set(TANK, "unavailable" if reading is None else reading,
             unit_of_measurement="°C")
    if own_stop is not None:
        dev.stop_entity, dev.stop_at = TANK, own_stop
    where = (f"{cls.__name__} · grid {grid} · Legionella {case} · {situation} · "
             f"{'away' if away else 'at home'}")
    want_on, want_family = _legionella_spec(cls, case, situation, away)
    kw = _inputs(situation)
    power = kw.pop("available_power_w")
    for _ in range(CYCLES):
        await dev.check_legionella_cycle()      # as the coordinator does
        await sc.update(power, **kw)
    _check(hass, sc, dev, where, situation, want_on, want_family, grid)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", LEGIONELLA_CLASSES, ids=lambda c: c.__name__)
async def test_a_legionella_run_heats_to_its_own_target_and_ends_once(cls):
    hass, sc, dev = _build(cls, "solar_only", "below_start", "night_no_block")
    kw = _inputs("night_no_block")
    power = kw.pop("available_power_w")

    async def cycles(n):
        for _ in range(n):
            await dev.check_legionella_cycle()
            await sc.update(power, **kw)

    await cycles(5)
    assert dev.is_active
    # past Keep at + Extra and still on: it runs to ITS target, not the band's
    hass.set(TANK, 58.0, unit_of_measurement="°C")
    await cycles(5)
    assert dev.is_active, "the band's ceiling ended the Legionella run"
    hass.set(TANK, dev.legionella_target_temp + 0.5, unit_of_measurement="°C")
    await cycles(2)
    assert dev.is_active, "it must hold at its target, not stop on reaching it"
    # the hold is over (its length comes from the target temperature)
    dev._legionella_hold_start -= timedelta(hours=2)
    await cycles(5)
    assert not dev.is_active
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    assert [r["reason_code"] for r in records] == [
        RC.LOAD_LEGIONELLA, RC.LOAD_LEGIONELLA_END], records


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", LEGIONELLA_CLASSES, ids=lambda c: c.__name__)
async def test_your_own_stop_under_the_target_ends_a_legionella_run_once(cls):
    """(#1102) It cannot finish: it ends, and does not start again when the
    tank cools under the stop."""
    hass, sc, dev = _build(cls, "solar_only", "below_start", "night_no_block")
    dev.stop_entity, dev.stop_at = TANK, 53.0
    kw = _inputs("night_no_block")
    power = kw.pop("available_power_w")

    async def cycles(n):
        for _ in range(n):
            await dev.check_legionella_cycle()
            await sc.update(power, **kw)

    await cycles(5)
    assert dev.is_active
    hass.set(TANK, 53.5, unit_of_measurement="°C")
    await cycles(5)
    assert not dev.is_active
    hass.set(TANK, 52.0, unit_of_measurement="°C")
    await cycles(10)
    assert not dev.is_active, "the run started again under your stop"
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    assert len([r for r in records if str(r["new"]).startswith("on")]) == 1


# ── the watt and ampere loads, beyond on and off ──────────────────────────

async def _run(sc, n, power, **kw):
    for _ in range(n):
        await sc.update(power, **kw)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls, entity, full", [
    (PowerSetpointDevice, "number.heater", 3000.0),
    (BandedCurrentLoad, "number.heater", 13.0),
])
async def test_a_too_cold_run_asks_for_the_full_setpoint(cls, entity, full):
    hass, sc, dev = _build(cls, "solar_only", "too_cold", "night_no_block")
    kw = _inputs("night_no_block")
    await _run(sc, 5, kw.pop("available_power_w"), **kw)
    assert dev.is_active
    assert float(hass.states.get(entity).state) == full


@pytest.mark.asyncio
@pytest.mark.parametrize("cls, sun_w, full", [
    (PowerSetpointDevice, 1500.0, 3000.0),
    (BandedCurrentLoad, 1700.0, 13.0),
])
async def test_a_heater_on_little_sun_goes_to_full_when_it_gets_too_cold(cls, sun_w, full):
    """It followed the sun below its full power; the tank fell under Run now
    past. The too-cold run is not left at the sun's setpoint."""
    hass, sc, dev = _build(cls, "solar_only", "at_keep", "day_sun")
    dev.min_power_threshold = 1000.0
    day = dict(price_level="normal", is_night=False, solar_w=3000.0,
               plan_windows={}, daylight_remaining_s=4 * 3600.0)
    await _run(sc, 20, sun_w, **day)
    assert dev.is_active and float(hass.states.get("number.heater").state) < full
    hass.set(TANK, 34.0, unit_of_measurement="°C")
    await _run(sc, 5, 0.0, **{**day, "solar_w": 0.0, "is_night": True})
    assert dev.is_active
    assert float(hass.states.get("number.heater").state) == full


@pytest.mark.asyncio
async def test_a_watt_heater_in_its_planned_hour_runs_at_full_and_stops_at_keep_at():
    hass, sc, dev = _build(PowerSetpointDevice, "cheap_hours", "below_start", "night_block")
    kw = _inputs("night_block")
    power = kw.pop("available_power_w")
    await _run(sc, 10, power, **kw)
    assert dev.is_active and float(hass.states.get("number.heater").state) == 3000.0
    hass.set(TANK, 50.2, unit_of_measurement="°C")
    await _run(sc, 5, power, **kw)
    assert not dev.is_active and float(hass.states.get("number.heater").state) == 0.0
    writes = [w for w in hass.writes() if w[1] == "set_value"]
    assert len(writes) == 2, f"one start and one stop, not {len(writes)} writes"


def test_a_charger_never_gains_the_band():
    """Only the registry's LOAD path builds the banded ampere class."""
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    assert not issubclass(CurrentControlDevice, ComfortBandMixin)
    from .ast_contracts import call_sites
    sites = {path for path, _line, _kw in call_sites("BandedCurrentLoad")}
    assert sites == {"features/device_registry.py"}, sites


def test_the_stored_band_reaches_a_watt_and_an_ampere_load_at_registration():
    """(#1344) The registry stored the fields and never put them on the live
    object on this path."""
    from custom_components.solar_energy_management.features.device_registry import (
        UnifiedDeviceRegistry,
    )
    for unit, ceiling, cls in (("W", 9000, PowerSetpointDevice), ("A", 16, BandedCurrentLoad)):
        reg = UnifiedDeviceRegistry.__new__(UnifiedDeviceRegistry)
        reg._built_from_store = {}
        hass = MagicMock()
        st = MagicMock()
        st.state = "0"
        st.attributes = {"unit_of_measurement": unit, "min": 0, "max": ceiling, "step": 1}
        hass.states.get.return_value = st
        reg.hass = hass
        reg._surplus_controller = MagicMock()
        reg._load_manager = None
        reg._initial_rated_power = MagicMock(return_value=3000.0)
        reg._device_goals = {"rod": {"comfort_entity": TANK, "comfort_target": 50,
                                      "comfort_offset": 5, "comfort_limit": 36}}
        # …and neither were the user's Mode and "Requires" link
        reg._service_registrations = {}
        reg._control_mode_overrides = {"rod": "surplus"}
        reg._dependency_overrides = {"rod": ["pump"]}
        device = MagicMock()
        device.device_id, device.name, device.priority = "rod", "Heating rod", 1
        device.power_sensor = None
        reg._register_current_control(
            device, {"type": "current", "entity": "number.rod",
                     "min_value": 0, "max_value": ceiling})
        live = reg._surplus_controller.register_device.call_args[0][0]
        assert isinstance(live, cls), (unit, type(live))
        assert (live.comfort_entity, live.comfort_target, live.comfort_limit) == (TANK, 50.0, 36.0)
        assert live.control_mode is DeviceControlMode.SURPLUS, (
            f"{cls.__name__}: rebuilt with {live.control_mode}, not the user's mode")
        assert live.depends_on == ["pump"]


def test_a_watt_heater_with_no_measured_rating_runs_a_heater_rung_at_its_entity_maximum():
    """(#1344, found on a real instance) No power sensor → the 1 kW rating is
    a placeholder. A 3 kW rod under its too-cold limit was sent 1 kW."""
    hass = _Hass()
    hass.set("number.heater", "0", unit_of_measurement="W", min=0, max=3000, step=1)
    unmeasured = PowerSetpointDevice(hass, DID, "Heater", rated_power=0.0,
                                     entity_id="number.heater")
    assert unmeasured.rated_power_measured is False
    assert unmeasured.heater_full_w() == 3000.0
    measured = PowerSetpointDevice(hass, DID, "Heater", rated_power=2000.0,
                                   entity_id="number.heater")
    assert measured.heater_full_w() == 2000.0


# ── (#1349) cooling: the same ladder, mirrored ───────────────────────────
# Keep at 24, sun may cool down to 22, never warmer than 27; a planned run
# starts at 25 (the start gap above Keep at).

C_KEEP, C_EXTRA, C_LIMIT = 24.0, 2.0, 27.0
C_ROOMS = {
    "too_warm": 28.0, "above_start": 26.0, "in_gap": 24.5, "at_keep": 24.0,
    "below_floor": 21.5, "no_reading": None,
}


def _cooler(hass):
    hass.set("climate.heater", "off", hvac_modes=["off", "cool"])
    return ClimateDevice(hass, DID, "Cooler", rated_power=3000.0,
                         entity_id="climate.heater", hvac_mode="cool")


def _build_cool(grid, room, situation, away=False):
    hass = _Hass()
    dev = _cooler(hass)
    reading = C_ROOMS[room]
    hass.set(TANK, "unavailable" if reading is None else reading,
             unit_of_measurement="°C")
    dev.control_mode = (DeviceControlMode.OFF if situation == "mode_off"
                        else DeviceControlMode.SURPLUS)
    dev.comfort_entity = TANK
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = C_KEEP, C_EXTRA, C_LIMIT
    dev.top_up_policy = "cheap_hours" if grid == "cheap_hours" else "solar_only"
    dev.battery_eligible_overnight = grid == "battery"
    for attr in ("min_on_seconds", "min_off_seconds", "min_on_time",
                 "min_off_time", "activation_delay_seconds"):
        if hasattr(dev, attr):
            setattr(dev, attr, 0)
    dev.vacation = bool(away)
    sc = SurplusController(hass, regulation_offset=0)
    sc.register_device(dev)
    return hass, sc, dev


def _spec_cool(grid, room, situation, away):
    """The heater's spec with every comparison turned round."""
    off = (False, "none")
    reading = C_ROOMS[room]
    if situation in ("mode_off", "peak_shed"):
        return off
    if away:
        return (True, "floor_away") if room == "too_warm" else off
    sun = situation == "day_sun"
    if reading is None:
        return (True, "sun") if sun else off
    if reading >= C_LIMIT:
        return (True, "floor")          # too warm: at once, on any tariff
    if reading <= C_KEEP - C_EXTRA:
        return off                      # cooled as far as the sun may take it
    if (reading >= C_KEEP + 1.0 and grid == "cheap_hours"
            and situation in ("night_block", "observer")):
        return (True, "goal")
    if (reading >= C_KEEP + 1.0 and grid == "battery"
            and situation == "night_battery_ok"):
        return (True, "goal_battery")
    if sun:
        return (True, "sun")
    return off


COOL_CELLS = [
    pytest.param(grid, room, situation, away,
                 id=f"cool-{grid}-{room}-{situation}-{'away' if away else 'home'}")
    for grid, room, situation, away in itertools.product(
        GRID, C_ROOMS, SITUATIONS, AWAY)
]


@pytest.mark.asyncio
@pytest.mark.parametrize("grid, room, situation, away", COOL_CELLS)
async def test_a_cooler_does_the_same_mirrored(grid, room, situation, away):
    hass, sc, dev = _build_cool(grid, room, situation, away)
    where = (f"ClimateDevice cooling · grid {grid} · room {room} "
             f"({C_ROOMS[room]} °C) · {situation} · {'away' if away else 'at home'}")
    want_on, want_family = _spec_cool(grid, room, situation, away)
    kw = _inputs(situation)
    power = kw.pop("available_power_w")
    for _ in range(CYCLES):
        await sc.update(power, **kw)
    _check(hass, sc, dev, where, situation, want_on, want_family, grid)


@pytest.mark.asyncio
@pytest.mark.parametrize("cls", list(FACTORIES), ids=lambda c: c.__name__)
async def test_the_battery_run_ends_at_the_reserve_and_buys_nothing(cls):
    """(#1349) It heats from the house battery while the battery is above its
    reserve; at the reserve it stops and waits — it is not turned into a
    bought run, and it says why."""
    hass, sc, dev = _build(cls, "battery", "below_start", "night_battery_ok")
    kw = _inputs("night_battery_ok")
    power = kw.pop("available_power_w")
    for _ in range(5):
        await sc.update(power, **kw)
    assert dev.is_active, f"{cls.__name__}: not heating from the battery"
    kw["battery_soc"] = 20.0                       # down to its reserve
    for _ in range(10):
        await sc.update(power, **kw)
    assert not dev.is_active, f"{cls.__name__}: kept heating at the reserve"
    records = [r for r in sc.decision_log.records() if r["device_id"] == DID]
    starts = [r for r in records if str(r["new"]).startswith("on")]
    assert [r["reason_code"] for r in starts] == [RC.LOAD_COMFORT_GOAL_BATTERY]
    intent = sc.intent_for(DID) if hasattr(sc, "intent_for") else None
    if intent is not None:
        assert intent.get("code") == RC.LOAD_BATTERY_RESERVE


@pytest.mark.asyncio
async def test_the_battery_run_goes_on_to_keep_at_and_stops_there():
    hass, sc, dev = _build(SwitchDevice, "battery", "below_start", "night_battery_ok")
    kw = _inputs("night_battery_ok")
    power = kw.pop("available_power_w")
    for _ in range(3):
        await sc.update(power, **kw)
    assert dev.is_active
    hass.set(TANK, 49.6, unit_of_measurement="°C")   # inside the start gap: goes on
    for _ in range(3):
        await sc.update(power, **kw)
    assert dev.is_active
    hass.set(TANK, 50.2, unit_of_measurement="°C")   # Keep at reached
    for _ in range(3):
        await sc.update(power, **kw)
    assert not dev.is_active


# ── (#705/#1349) a unit that rides its own setpoint ──────────────────────
# Typed Keep 50 / limit 36 / extra 5 with the thermostat at 48: the band is
# 48 / 34 / up to 53, and a planned run starts at 47. Cooling: typed 24 / 27 /
# 2 with the thermostat at 25 gives 25 / 28 / down to 23, start at 26.

ANCHORED = [
    # (hvac, setpoint, reading, situation, on, family)
    ("heat", 48.0, 47.5, "night_block", False, "none"),     # inside the EFFECTIVE gap
    ("heat", 48.0, 49.5, "night_block", False, "none"),     # under the typed 50, over the unit's 48
    ("heat", 48.0, 46.5, "night_block", True, "goal"),
    ("heat", 48.0, 35.0, "night_no_block", False, "none"),  # under the typed limit 36, over the unit's 34
    ("heat", 48.0, 33.5, "night_no_block", True, "floor"),
    ("heat", 48.0, 52.0, "day_sun", True, "sun"),           # the sun goes to 48 + 5
    ("heat", 48.0, 53.5, "day_sun", False, "none"),
    ("cool", 25.0, 25.5, "night_block", False, "none"),
    ("cool", 25.0, 24.5, "night_block", False, "none"),     # over the typed 24, under the unit's 25
    ("cool", 25.0, 26.5, "night_block", True, "goal"),
    ("cool", 25.0, 27.5, "night_no_block", False, "none"),  # over the typed limit 27, under the unit's 28
    ("cool", 25.0, 28.5, "night_no_block", True, "floor"),
    ("cool", 25.0, 23.5, "day_sun", True, "sun"),           # the sun goes down to 25 − 2
    ("cool", 25.0, 22.5, "day_sun", False, "none"),
]


@pytest.mark.asyncio
@pytest.mark.parametrize("hvac, setpoint, reading, situation, want_on, want_family", ANCHORED,
                         ids=[f"{h}-{r}-{s}" for h, _sp, r, s, _o, _f in ANCHORED])
async def test_a_unit_that_rides_its_own_setpoint_follows_that_setpoint(
        hvac, setpoint, reading, situation, want_on, want_family):
    hass = _Hass()
    hass.set("climate.heater", "off", hvac_modes=["off", hvac], temperature=setpoint)
    dev = ClimateDevice(hass, DID, "Unit", rated_power=3000.0,
                        entity_id="climate.heater", hvac_mode=hvac)
    hass.set(TANK, reading, unit_of_measurement="°C")
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity = TANK
    if hvac == "heat":
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = KEEP, EXTRA, LIMIT
    else:
        dev.comfort_target, dev.comfort_offset, dev.comfort_limit = C_KEEP, C_EXTRA, C_LIMIT
    dev.top_up_policy = "cheap_hours"
    for attr in ("min_on_seconds", "min_off_seconds", "min_on_time",
                 "min_off_time", "activation_delay_seconds"):
        if hasattr(dev, attr):
            setattr(dev, attr, 0)
    sc = SurplusController(hass, regulation_offset=0)
    sc.register_device(dev)
    kw = _inputs(situation)
    power = kw.pop("available_power_w")
    for _ in range(CYCLES):
        await sc.update(power, **kw)
        # the unit's own setpoint is the anchor: SEM's writes must not move it
        hass.set("climate.heater", hass.states.get("climate.heater").state,
                 hvac_modes=["off", hvac], temperature=setpoint)
    where = f"anchored {hvac} unit at {setpoint} °C · reading {reading} °C · {situation}"
    _check(hass, sc, dev, where, situation, want_on, want_family, "cheap_hours")
