"""(#1369) Replay the hot water tank's decision over a recorded day.

SEM's REAL ``HotWaterController`` is built with no Home Assistant behind
it and asked the question the load engine asks every cycle,
``compute_load_intent``, from the recorded tank temperature, the surplus
the recorded grid shows and the recorded price. What it WOULD command
(on / off, with the reason code) is kept, one row per change, and compared
between a branch and its base like the car's and the battery's.

Honest limits: the tank's temperature is the RECORDED one, so a different
decision does not warm or cool it — the replay judges decisions, not heat.
The corpus holds no tank settings, so the band is fixed (below). Legionella
is not replayed: its last-run time is not recorded, so no run is ever due.
OFFLINE and READ-ONLY: no service is ever called.

(#1369) The owner's install has no tank, so a day with no recorded tank
temperature SIMULATES one (``SIM_*``, below) and feeds the controller the
simulated water, closed loop: its on/off heats the model. Base and branch
share the model, so the comparison is of decisions under ONE physics; the
physics itself is a plain estimate, not a measurement.
"""
from __future__ import annotations

import time as _time
from contextlib import ExitStack
from datetime import datetime as _datetime
from datetime import timedelta
from types import SimpleNamespace
from typing import List, Optional, Tuple
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

from .recorded_day import RecordedDay

SWITCH = "switch.replay_tank"
SENSOR = "sensor.replay_tank_temp"
#: the settings the replay uses (the corpus holds none): a 3.2 kW element,
#: Keep at 52 °C, Extra 4 °C, too cold below 36 °C, Solar Heating Target 50
RATED_W = 3200.0
KEEP_AT_C, EXTRA_C, TOO_COLD_C, SOLAR_TARGET_C = 52.0, 4.0, 36.0, 50.0
#: the simulated tank (#1369): 300 L, ~0.35 kWh/K, the element at RATED_W,
#: ~1.5 K/day lost toward a 20 C room when at Keep at, two draws of cold water
SIM_CAPACITY_WH_PER_K = 350.0
SIM_ROOM_C, SIM_COLD_C, SIM_VOLUME_L = 20.0, 15.0, 300.0
SIM_LOSS_PER_S = 1.5 / (86400.0 * (KEEP_AT_C - SIM_ROOM_C))   # K/s per K above room
SIM_DRAWS = ((7.0, 40.0), (20.0, 60.0))                       # (local hour, litres)
SIM_START_C = KEEP_AT_C - 2.0
MODE_RECORDED, MODE_SIMULATED = "recorded", "simulated"
#: the sanity check allows this long to react (min run / rest times)
GRACE_S = 20 * 60
#: a price this far under the day's top counts as cheap
CHEAP_BELOW = 0.9


class _Hass:
    """A state table and a service counter — nothing else."""

    def __init__(self):
        self._states: dict = {}
        self.config = SimpleNamespace(units=SimpleNamespace(temperature_unit="°C"))
        self.states = MagicMock()
        self.states.get = self._states.get
        self.states.is_state = lambda e, v: e in self._states and self._states[e].state == v
        self.services = MagicMock()
        self.services.async_call = AsyncMock()
        self.data: dict = {}

    def set(self, entity_id, state, **attributes):
        self._states[entity_id] = SimpleNamespace(
            entity_id=entity_id, state=str(state), attributes=attributes)


class _Clock:
    def __init__(self, tz: str):
        self.t = 0.0
        self.zi = ZoneInfo(tz)

    def aware(self):
        return _datetime.fromtimestamp(self.t, self.zi)

    def naive(self):
        return self.aware().replace(tzinfo=None)


def _dt_class(clock: _Clock):
    """``datetime`` whose ``now()`` is the day's clock, never the wall's (#1369)."""
    class _Meta(type(_datetime)):
        def __instancecheck__(cls, obj):
            return isinstance(obj, _datetime)

    class _Dt(_datetime, metaclass=_Meta):
        @classmethod
        def now(cls, tz=None):
            return clock.aware() if tz is not None else clock.naive()
    return _Dt


def _tank(hass):
    from custom_components.solar_energy_management.devices.base import DeviceControlMode
    from custom_components.solar_energy_management.devices.hot_water_controller import (
        HotWaterController,
    )
    dev = HotWaterController(
        hass=hass, entity_id=SWITCH, temperature_entity_id=SENSOR,
        solar_target_temp=SOLAR_TARGET_C, rated_power=RATED_W,
        legionella_target_temp=60.0)
    dev.control_mode = DeviceControlMode.SURPLUS
    dev.comfort_entity = SENSOR
    dev.comfort_target, dev.comfort_offset, dev.comfort_limit = KEEP_AT_C, EXTRA_C, TOO_COLD_C
    dev.withheld_commands = []
    return dev


def _believe(dev, hass, on: bool, clock: _Clock) -> None:
    """Make the controller believe what the replay last commanded."""
    from custom_components.solar_energy_management.devices.base import DeviceState
    now = clock.naive()
    dev._status.state = DeviceState.ACTIVE if on else DeviceState.IDLE
    dev._status.current_consumption_w = RATED_W if on else 0.0
    dev._sem_owned = dev._sem_commanded = dev._commanded_claim = on
    if on:
        dev._last_activated = dev._status.last_activated = now
    else:
        dev._last_deactivated = now
    hass.set(SWITCH, "on" if on else "off")


def _cheap(price: Optional[float], top: Optional[float]) -> bool:
    return price is not None and top is not None and top > 0 and price < CHEAP_BELOW * top


def sim_step(temp: float, on: bool, dt_s: float) -> float:
    """(#1369) One step of the model: heat in, minus the standing loss."""
    heat = (RATED_W * dt_s / 3600.0 if on else 0.0) / SIM_CAPACITY_WH_PER_K
    loss = SIM_LOSS_PER_S * (temp - SIM_ROOM_C) * dt_s
    return temp + heat - loss


def sim_draw(temp: float, litres: float) -> float:
    """Cold water mixed in for a draw of ``litres``."""
    return temp - (litres / SIM_VOLUME_L) * (temp - SIM_COLD_C)


def _fault(kind: str, since: float, temp: float, limit: float) -> dict:
    return {"kind": kind, "t": round(since), "temp_c": round(temp, 1), "limit_c": limit}


def replay_tank(day: RecordedDay, daylight: Optional[Tuple[float, float]]
                ) -> Optional[Tuple[List[list], List[dict], str]]:
    """``(rows, faults, mode)``. Mode ``recorded`` feeds the controller the
    day's own tank temperature, ``simulated`` the model above (#1369). Rows: ``[epoch_s, "tank", "on"|"off", code]``, one
    per change. Faults: the replayed tank ran ``over_top`` or stayed off
    ``too_cold`` for longer than ``GRACE_S`` against the RECORDED water
    temperature. None when there is nothing to replay (no tank recorded and
    no grid reading to simulate on)."""
    recorded = bool(day.series.get("tank_temp"))
    if not recorded and not day.series.get("grid_power"):
        return None
    from custom_components.solar_energy_management.coordinator import surplus_controller as sc
    from custom_components.solar_energy_management.devices import base
    from homeassistant.util import dt as dt_util

    clock, hass = _Clock(day.tz), _Hass()
    prices = [v for _, v in day.series.get("import_price", []) if v is not None]
    top_price = max(prices) if prices else None
    out: List[list] = []
    faults: List[dict] = []
    bad = {"over_top": None, "too_cold": None}
    flagged: set = set()
    with ExitStack() as stack:
        dt_cls = _dt_class(clock)
        stack.enter_context(patch.object(dt_util, "now", lambda *a, **k: clock.aware()))
        stack.enter_context(patch.object(base, "datetime", dt_cls))
        stack.enter_context(patch.object(sc, "datetime", dt_cls))
        stack.enter_context(patch.object(base, "time", SimpleNamespace(
            monotonic=lambda: clock.t, time=lambda: clock.t, sleep=_time.sleep)))
        clock.t = day.bounds()[0]
        hass.set(SWITCH, "off")
        dev = _tank(hass)
        dev._last_legionella_time = clock.aware() - timedelta(hours=1)  # never due
        dev._last_deactivated = clock.naive() - timedelta(days=1)
        last = None
        sim, prev_t, drawn, on_now = SIM_START_C, None, set(), False
        for c in day.cycles():
            clock.t = c.t
            hour = day.local_hour(c.t)
            if recorded:
                temp = c.get("tank_temp")
            else:
                if prev_t is not None:
                    sim = sim_step(sim, on_now, c.t - prev_t)
                for h, litres in SIM_DRAWS:
                    if hour >= h and h not in drawn:
                        drawn.add(h)
                        sim = sim_draw(sim, litres)
                prev_t, temp = c.t, sim
            if temp is None:
                hass.set(SENSOR, "unavailable")
            else:
                hass.set(SENSOR, f"{temp}", unit_of_measurement="°C")
            night = daylight is None or not (daylight[0] <= hour <= daylight[1])
            left = None if night or daylight is None else (daylight[1] - hour) * 3600.0
            intent = sc.compute_load_intent(
                dev, remaining_surplus_w=max(0.0, c.get("grid_power", 0.0) or 0.0),
                price_is_cheap=_cheap(c.get("import_price"), top_price),
                is_night=night, daylight_remaining_s=left)
            row = ("on" if intent.on else "off", str(intent.code or intent.source or ""))
            if bool(intent.on) != bool(dev.is_active):
                _believe(dev, hass, bool(intent.on), clock)
            on_now = bool(dev.is_active)
            if row != last:
                last = row
                out.append([round(c.t), "tank", *row])
            top = dev.band_top_c(peek=True) or (KEEP_AT_C + EXTRA_C)
            for kind, bad_now, lim in (
                    ("over_top", temp is not None and temp >= top and intent.on, top),
                    ("too_cold", temp is not None and temp < TOO_COLD_C and not intent.on,
                     TOO_COLD_C)):
                if not bad_now:
                    bad[kind] = None
                    continue
                since = bad[kind] = bad[kind] if bad[kind] is not None else c.t
                if c.t - since >= GRACE_S and (kind, since) not in flagged:
                    flagged.add((kind, since))
                    faults.append(_fault(kind, since, temp, lim))
    return out, faults, MODE_RECORDED if recorded else MODE_SIMULATED
