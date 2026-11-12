"""#1344 — what every heater does in every situation, as ONE table.

The hot-water area produced one issue per rule: each rule was tested alone,
on one device class, and the #1335 audit checked WHERE loads are switched
(one seam), not WHAT a heater does. This file runs the real
``SurplusController`` — layers 1, 2 and 3, no mocked decision — for every
combination of

    device class   every class that carries the comfort band (discovered)
    grid setting   solar_only · cheap_hours · battery
    tank state     too cold · below the start line · inside the start gap ·
                   at Keep at · above Keep at + Extra · no reading
    situation      night with its planned hour open · night with no plan ·
                   day with spare sun · day with too little sun · peak shed ·
                   away · Mode Off · watch-only (observer)

and compares the outcome with ``_spec``, one small function written from
docs/USER_GUIDE.md, "Keep at, Extra from surplus, Run now past":

    own stop → Legionella → too cold → Keep at in its planned hour, if the
    grid is allowed → sun up to Keep at + Extra → nothing.

A new class that gains the band enters the matrix by itself; without a
factory here the first test fails and names it.
"""
from __future__ import annotations

import itertools
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
CYCLES = 60

GRID = ("solar_only", "cheap_hours", "battery")
TANKS = {
    "too_cold": 34.0, "below_start": 45.0, "in_gap": 49.5,
    "at_keep": 50.0, "above_ceiling": 56.0, "no_reading": None,
}
SITUATIONS = ("night_block", "night_no_block", "day_sun", "day_little_sun",
              "peak_shed", "away", "mode_off", "observer")


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


def _build(cls, grid, tank, situation):
    hass = _Hass()
    dev = FACTORIES[cls](hass)
    reading = TANKS[tank]
    hass.set(TANK, "unavailable" if reading is None else reading,
             unit_of_measurement="°C")
    dev.control_mode = (DeviceControlMode.OFF if situation == "mode_off"
                        else DeviceControlMode.SURPLUS)
    dev.comfort_entity = TANK
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = KEEP, EXTRA, LIMIT
    dev.top_up_policy = "cheap_hours" if grid == "cheap_hours" else "solar_only"
    dev.battery_eligible_overnight = grid == "battery"
    # nothing hides a flap: no minimum run, pause or start delay
    for attr in ("min_on_seconds", "min_off_seconds", "min_on_time",
                 "min_off_time", "activation_delay_seconds",
                 "min_power_change_interval", "_min_power_change_interval"):
        if hasattr(dev, attr):
            setattr(dev, attr, 0)
    away = situation == "away" and hasattr(dev, "vacation")
    if away:
        dev.vacation = True
    sc = SurplusController(hass, regulation_offset=0)
    sc.register_device(dev)
    return hass, sc, dev, away


def _inputs(situation):
    block = {DID: PlanVerdict(in_block=True, comfort_in_block=True,
                              reason="planned block")}
    night = dict(available_power_w=0.0, price_level="normal", is_night=True,
                 solar_w=0.0, plan_windows=block)
    if situation == "night_no_block":
        return {**night, "plan_windows": {}}
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
    return night            # night_block, away, mode_off


def _spec(grid, tank, situation, *, away, refuses_blind):
    """(on, family) per the User Guide. family: floor · goal · sun · none."""
    off = (False, "none")
    if situation == "mode_off":
        return off                      # SEM does not drive it
    if situation == "peak_shed":
        return off                      # a shed outranks every run
    if away:
        return off                      # no comfort heating while away
    if situation == "away":
        situation = "night_block"       # a load SEM is not told about away
    sun = situation == "day_sun"
    if tank == "no_reading":
        # no reading is no band: a plain load on spare sun — unless the
        # device refuses to heat blind
        return (True, "sun") if sun and not refuses_blind else off
    if tank == "too_cold":
        return (True, "floor")          # at once, on any tariff
    if tank == "above_ceiling":
        return off
    if (tank == "below_start" and grid == "cheap_hours"
            and situation in ("night_block", "observer")):
        return (True, "goal")           # bought, in its planned hour
    if sun:
        return (True, "sun")            # up to Keep at + Extra
    return off


def _family(code, source):
    if code == RC.LOAD_COMFORT_FLOOR:
        return "floor"
    if code == RC.LOAD_COMFORT_GOAL:
        return "goal"
    return "sun" if source in ("solar", "tier1_battery") or code in (
        "solar", "tier1_battery") else "other"


CELLS = [
    pytest.param(cls, grid, tank, situation,
                 id=f"{cls.__name__}-{grid}-{tank}-{situation}")
    for cls, grid, tank, situation in itertools.product(
        FACTORIES, GRID, TANKS, SITUATIONS)
]


@pytest.mark.asyncio
@pytest.mark.parametrize("cls, grid, tank, situation", CELLS)
async def test_a_heater_does_what_the_guide_says(cls, grid, tank, situation):
    hass, sc, dev, away = _build(cls, grid, tank, situation)
    where = (f"{cls.__name__} · grid {grid} · tank {tank} "
             f"({TANKS[tank]} °C) · {situation}")
    refuses_blind = getattr(dev, "start_refusal", None) == "sensor"
    want_on, want_family = _spec(grid, tank, situation,
                                 away=away, refuses_blind=refuses_blind)
    kw = _inputs(situation)
    power = kw.pop("available_power_w")
    for _ in range(CYCLES):
        await sc.update(power, **kw)

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
    if grid != "cheap_hours" and got not in ("floor", "sun"):
        pytest.fail(f"{where}: bought power without the grid allowed ({got})")


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
    hass, sc, dev, _ = _build(cls, "solar_only", "too_cold", "night_no_block")
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
    hass, sc, dev, _ = _build(cls, "solar_only", "at_keep", "day_sun")
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
    hass, sc, dev, _ = _build(PowerSetpointDevice, "cheap_hours", "below_start", "night_block")
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
        device = MagicMock()
        device.device_id, device.name, device.priority = "rod", "Heating rod", 1
        device.power_sensor = None
        reg._register_current_control(
            device, {"type": "current", "entity": "number.rod",
                     "min_value": 0, "max_value": ceiling})
        live = reg._surplus_controller.register_device.call_args[0][0]
        assert isinstance(live, cls), (unit, type(live))
        assert (live.comfort_entity, live.comfort_target, live.comfort_limit) == (TANK, 50.0, 36.0)
