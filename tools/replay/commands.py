"""(#1299) Replay the pure decisions over a recorded day.

``no_writes`` once counted service calls on a coordinator that never
decided anything, so it could not fail. This module runs SEM's REAL pure
deciders — ``decide_battery(view)`` and the charger's ``decide(view)`` —
every 10-s cycle from the recorded readings, and keeps the sequence of
what SEM WOULD have commanded. The gate compares that sequence between a
branch and its base.

Honest limits: the corpus holds readings, not the install's configuration.
The roster is built with SEM's defaults, one battery of 10 kWh and one
3-phase car in ``min_plus_solar`` mode that counts as plugged in while it
draws. A battery limit is kept in 100 W steps, so the roster lists
decisions, not every watt the house moved. It is a comparison of decisions from the same inputs, not a
prediction of what PROD sent that day.
"""
from __future__ import annotations

from typing import List, Optional, Tuple

from .recorded_day import RecordedDay

#: a car drawing more than this is "plugged in" for the replay
CAR_DRAW_W = 100.0
CHARGER_CFG = {"id": "car", "ev_min_current": 6, "ev_phases": 3,
               "ev_voltage": 230, "ev_max_current": 16}
BATTERY_KWH = 10.0
CAR_MODE = "min_plus_solar"
#: a discharge limit follows the house watt by watt; the roster keeps steps
LIMIT_STEP_W = 100.0


def _readings(c, daylight: Optional[Tuple[float, float]], hour: float):
    from custom_components.solar_energy_management.coordinator.types import PowerReadings
    ev_w = float(c.get("ev_power", 0.0) or 0.0)
    pr = PowerReadings(
        solar_power=float(c.get("solar_power", 0.0) or 0.0),
        grid_power=float(c.get("grid_power", 0.0) or 0.0),
        battery_power=float(c.get("battery_power", 0.0) or 0.0),
        ev_power=ev_w,
        battery_soc=float(c.get("battery_soc", 50.0) or 50.0),
        solar_power_unavailable=c.dark("solar_power"),
        grid_power_unavailable=c.dark("grid_power"),
        battery_power_all_unavailable=c.dark("battery_power"),
    )
    pr.ev_connected = pr.ev_charging = ev_w > CAR_DRAW_W
    pr.calculate_derived()
    return pr


def _charger_key(decision) -> tuple:
    return ("car", getattr(decision.intent, "name", str(decision.intent)),
            int(getattr(decision, "commanded_amps", 0) or 0))


def _battery_key(decision) -> tuple:
    return ("battery", getattr(decision.intent, "name", str(decision.intent)),
            _step(getattr(decision, "discharge_limit_w", 0.0)),
            _step(getattr(decision, "charge_power_w", 0.0)))


def _step(w) -> int:
    return int(round(float(w or 0.0) / LIMIT_STEP_W) * LIMIT_STEP_W)


def replay_commands(day: RecordedDay,
                    daylight: Optional[Tuple[float, float]]) -> List[list]:
    """``[[epoch_s, who, intent, value...], ...]`` — one row each time the
    decision for the car or the battery changes."""
    from custom_components.solar_energy_management.coordinator.build_view import (
        build_charger_view,
    )
    from custom_components.solar_energy_management.coordinator.charger_types import (
        BatteryRuntime, BatteryView, FleetCycleState,
    )
    from custom_components.solar_energy_management.coordinator.decide import decide
    from custom_components.solar_energy_management.coordinator.decide_battery import (
        decide_battery,
    )

    out: List[list] = []
    last = {"car": None, "battery": None}
    have = {r for r in ("solar_power", "grid_power", "battery_power") if day.series.get(r)}
    for c in day.cycles():
        if not any(c.values.get(r) is not None for r in have):
            continue
        hour = day.local_hour(c.t)
        pr = _readings(c, daylight, hour)
        is_night = daylight is None or not (daylight[0] <= hour <= daylight[1])
        raw = c.get("forecast_remaining_kwh")
        state = FleetCycleState(
            power=pr, config={}, is_night=is_night, tariff_level=None,
            forecast_remaining_kwh=float(raw or 0.0))
        view = build_charger_view(
            state, charger_id="car", charger_cfg=CHARGER_CFG,
            mode=CAR_MODE, daily_ev_kwh=0.0)
        car = _charger_key(decide(view))
        soc = c.get("battery_soc")
        bw = c.get("battery_power")
        bview = BatteryView(
            runtime=BatteryRuntime(
                battery_id="b1", name="b1", capacity_kwh=BATTERY_KWH,
                last_known_soc=float(soc if soc is not None else 0.0),
                last_known_w=float(bw if bw is not None else 0.0),
                soc_read=soc is not None, power_read=bw is not None),
            config={}, fleet=view.fleet, charging_state="idle",
            ev_charging=bool(pr.ev_charging), ev_connected=bool(pr.ev_connected),
            home_consumption_w=float(pr.home_consumption_power or 0.0))
        battery = _battery_key(decide_battery(bview))
        for who, key in (("car", car), ("battery", battery)):
            if key != last[who]:
                last[who] = key
                out.append([round(c.t), *key])
    return out
