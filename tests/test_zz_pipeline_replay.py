"""(#1381, charger owner) Pipeline replay: the REAL coordinator cycle over
recorded days, every service call it makes, compared between two trees.

``tools/replay`` runs only the pure deciders (``decide``, ``decide_battery``)
and compares (intent, amps). It never reaches the stability/yield step, the
phase guard, ``actuate``, the reconciler, the one hardware seam ``send``, the
command ledger or the hand-back — so it cannot show that a change there is
neutral (owner review, S2–S5).

This file drives ``SEMCoordinator._async_update_data`` (``CycleRig``: real
coordinator, real charger devices, real adapters and reconcilers) cycle by
cycle on a simulated clock, from:

* the PROD corpus days (``~/sem-replay-corpus``), one charger SEM steers;
* a synthetic day from the #1381 timeline: two chargers another party
  steers ("SEM yields"), the phase guard enforcing at 23 A, an overload on
  L3 at 16:43, a quiet evening.

It writes every ``(time, domain, service, data)`` the cycle sent to
``$PIPELINE_REPLAY_OUT``. It is skipped unless that variable is set; the
driver (``~/claude-jobs/pipeline-replay.sh``) copies this file into a base
tree, runs both, and compares.

Kept to the coordinator API both trees share, on purpose.
"""
from __future__ import annotations

import gzip
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import pytest

OUT = os.environ.get("PIPELINE_REPLAY_OUT")
DAYS = [p for p in os.environ.get("PIPELINE_REPLAY_DAYS", "").split(",") if p]
STEP_S = int(os.environ.get("PIPELINE_REPLAY_STEP_S", "60"))

pytestmark = pytest.mark.skipif(not OUT, reason="pipeline replay runs only on request")

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 10.0,
    "battery_reserve_soc": 20,
}


def _charger(cid, *, power, mode="min_plus_solar", **over):
    c = {"id": cid, "name": cid, "ev_min_current": 6, "ev_max_current": 16,
         "ev_phases": 3, "ev_voltage": 230,
         "ev_current_control_entity": f"number.{cid}_current",
         "ev_connected_sensor": f"binary_sensor.{cid}_connected",
         "ev_power_sensor": power, "charge_mode": mode,
         "ev_target_type": "kwh", "daily_ev_target": 10}
    c.update(over)
    return c


def _rows(rig, t, seen):
    out = []
    calls = rig.calls
    for domain, service, data in calls[seen:]:
        out.append([round(t), domain, service,
                    json.dumps(data, sort_keys=True, default=str)])
    return out, len(calls)


async def _run(rig, steps, set_states, freezer_move):
    """``steps``: [(epoch_s, {entity: value})]."""
    rows, seen = [], 0
    for t, values in steps:
        freezer_move(t)
        set_states(rig, values, t)
        try:
            await rig.coord._async_update_data()
        except Exception as e:  # noqa: BLE001 — a failed cycle is a row too
            rows.append([round(t), "cycle", "failed", type(e).__name__])
        new, seen = _rows(rig, t, seen)
        rows.extend(new)
    return rows


def _set_states(rig, values, t):
    from homeassistant.util import dt as dt_util
    for eid, val in values.items():
        state, attrs = (val if isinstance(val, tuple) else (val, {}))
        rig.hass.states.set(eid, (state, attrs))
    # every reading is fresh this cycle (the guard reads last_reported):
    # one wrapper, installed once, reading the simulated clock
    store = rig.hass.states
    if not getattr(store, "_fresh_installed", False):
        orig = store.get

        def _fresh(entity_id, _orig=orig):
            st = _orig(entity_id)
            if st is not None:
                now = dt_util.utcnow()
                st.last_reported = now
                st.last_updated = now
            return st

        store.get = _fresh
        store._fresh_installed = True


# ── the PROD corpus ──────────────────────────────────────────────────────

def _corpus_steps(path):
    from custom_components.solar_energy_management.tools.replay.recorded_day import (
        load_day,
    )
    day = load_day(Path(path))
    steps, last = [], None
    for c in day.cycles():
        if last is not None and c.t - last < STEP_S:
            continue
        last = c.t
        ev = float(c.get("ev_power", 0.0) or 0.0)
        values = {
            "sensor.solar": c.get("solar_power", 0.0) or 0.0,
            "sensor.grid": c.get("grid_power", 0.0) or 0.0,
            "sensor.batt": c.get("battery_power", 0.0) or 0.0,
            "sensor.soc": c.get("battery_soc", 50.0) or 50.0,
            "sensor.ev": ev,
            "binary_sensor.car_connected": "on" if ev > 100 else "off",
            "number.car_current": 16,
        }
        steps.append((c.t, values))
    return steps


# ── the #1381 day: two yielded chargers, the guard, an overload ─────────

def _overload_steps():
    day0 = datetime(2026, 11, 23, 15, 0, tzinfo=timezone.utc).timestamp()
    steps = []
    for i in range(0, 12 * 3600, 30):
        t = day0 + i
        hh = (t - day0) / 3600 + 16.0          # local-ish label, 16:00 →
        steps.append((t, {"_hour": hh}))
    return steps


def _overload_values(rig, values, t, sim):
    """A little physics: a charger whose enable switch is on and whose car is
    plugged draws its current on all three phases."""
    hh = values.pop("_hour")
    links_on = (sim["states"].get("switch.links_enable", "on") == "on"
                and float(sim["states"].get("number.links_current", 12)) >= 6)
    rechts_on = (sim["states"].get("switch.rechts_enable", "on") == "on"
                 and float(sim["states"].get("number.rechts_current", 6)) >= 6)
    links_a = 12.0 if links_on else 0.0       # Audi ~8.3 kW
    rechts_a = 6.0 if (rechts_on and 16.5 <= hh < 21.0) else 0.0
    heat_l3 = 8.0 if 16.71 <= hh < 16.73 else 0.0    # 16:43 peak, ~1 min
    base = {"l1": 2.0, "l2": 3.0, "l3": 2.0}
    l = {p: base[p] + links_a + rechts_a for p in base}
    l["l3"] += heat_l3
    ev_w = (links_a + rechts_a) * 3 * 230
    vals = {
        "sensor.solar": 0.0, "sensor.batt": 0.0, "sensor.soc": 40.0,
        "sensor.grid": -(sum(l.values()) * 230),
        "sensor.ev": ev_w,
        "sensor.links_power": links_a * 3 * 230,
        "sensor.rechts_power": rechts_a * 3 * 230,
        "binary_sensor.links_connected": "on",
        "binary_sensor.rechts_connected": "on",
        "sensor.l1": (round(l["l1"], 1), {"unit_of_measurement": "A"}),
        "sensor.l2": (round(l["l2"], 1), {"unit_of_measurement": "A"}),
        "sensor.l3": (round(l["l3"], 1), {"unit_of_measurement": "A"}),
        "switch.links_enable": sim["states"].get("switch.links_enable", "on"),
        "switch.rechts_enable": sim["states"].get("switch.rechts_enable", "on"),
        # the other party set these currents (12 A and 6 A)
        "number.links_current": sim["states"].get("number.links_current", 12),
        "number.rechts_current": sim["states"].get("number.rechts_current", 6),
    }
    _set_states(rig, vals, t)


# ── the runs ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_pipeline_replay(freezer):
    from .cycle_rig import CycleRig
    report = {}
    for path in DAYS:
        rig = CycleRig(config=dict(WIRED),
                       chargers=[_charger("car", power="sensor.ev")])
        steps = _corpus_steps(path)
        if not steps:
            continue

        def _move(t):
            freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))

        report[Path(path).name] = await _run(rig, steps, _set_states, _move)

    # the synthetic #1381 day
    cfg = dict(WIRED)
    # the install's EV sensor is the sum of both chargers
    cfg["ev_power_sensor"] = "sensor.ev"
    cfg.update({
        "phase_guard_enabled": True, "phase_guard_enforcement_enabled": True,
        "phase_guard_topology": "grid_only", "phase_guard_phase_count": 3,
        "phase_guard_grid_limit_a": 23,
        "phase_guard_grid_l1_current_entity": "sensor.l1",
        "phase_guard_grid_l2_current_entity": "sensor.l2",
        "phase_guard_grid_l3_current_entity": "sensor.l3",
    })
    # each charger reads its OWN power (the per-charger key the card writes)
    chargers = [
        _charger("links", power="sensor.links_power", mode="always_max",
                 external_control_mode="yield", priority=1,
                 ev_charging_power_sensor="sensor.links_power"),
        _charger("rechts", power="sensor.rechts_power", mode="always_max",
                 external_control_mode="yield", priority=2,
                 ev_charging_power_sensor="sensor.rechts_power"),
    ]
    rig = CycleRig(config=cfg, chargers=chargers)
    for cid in ("links", "rechts"):
        rig.coord._ev_devices[cid].start_stop_entity = f"switch.{cid}_enable"
    sim = {"states": {}}
    real_call = rig.hass.services.async_call.side_effect

    async def _call(domain, service, data, *a, **k):
        ent = (data or {}).get("entity_id")
        if domain == "switch" and ent:
            sim["states"][ent] = "on" if service == "turn_on" else "off"
        elif domain == "number" and ent and "value" in (data or {}):
            sim["states"][ent] = data["value"]
        if real_call:
            return await real_call(domain, service, data, *a, **k)
        return None

    rig.hass.services.async_call.side_effect = _call

    def _move(t):
        freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))

    def _set(rig_, values, t):
        _overload_values(rig_, dict(values), t, sim)

    report["synthetic-1381-overload"] = await _run(
        rig, _overload_steps(), _set, _move)
    if os.environ.get("PIPELINE_REPLAY_DEBUG"):
        report["_drawing_at_hand_back"] = getattr(rig.coord, "_hand_back_facts", None)

    # the same day on the legacy single-charger path (no fleet list)
    cfg1 = dict(cfg)
    cfg1["ev_chargers"] = [_charger(
        "ev_charger", power="sensor.links_power", mode="always_max",
        external_control_mode="yield",
        ev_charging_power_sensor="sensor.links_power")]
    cfg1["ev_power_sensor"] = "sensor.links_power"
    rig1 = CycleRig(config=cfg1, chargers=[])
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    dev1 = CurrentControlDevice(
        rig1.hass, device_id="ev_charger", name="ev_charger", priority=1,
        min_current=6.0, max_current=16.0, phases=3, voltage=230.0,
        entity_id=None, power_entity_id="sensor.links_power",
        current_entity_id="number.links_current", charger_service=None,
        charger_service_entity_id=None)
    dev1.start_stop_entity = "switch.links_enable"
    rig1.coord._ev_devices = {}
    rig1.coord._ev_device = dev1
    sim1 = {"states": {}}   # the second box is plain house load here

    async def _call1(domain, service, data, *a, **k):
        ent = (data or {}).get("entity_id")
        if domain == "switch" and ent:
            sim1["states"][ent] = "on" if service == "turn_on" else "off"
        elif domain == "number" and ent and "value" in (data or {}):
            sim1["states"][ent] = data["value"]
        return None

    rig1.hass.services.async_call.side_effect = _call1

    def _set1(rig_, values, t):
        _overload_values(rig_, dict(values), t, sim1)

    report["synthetic-1381-single-charger"] = await _run(
        rig1, _overload_steps(), _set1, _move)
    if os.environ.get("PIPELINE_REPLAY_DEBUG"):
        report["_single_debug"] = {
            "trail": json.loads(json.dumps(getattr(rig1.coord, "_owner_trail", None), default=str)),
            "yield": rig1.coord.external_yielding("charger:ev_charger"),
            "ev_device": bool(rig1.coord._ev_device),
            "ev_devices": list((rig1.coord._ev_devices or {}).keys()),
            "guard": (getattr(rig1.coord, "_phase_guard_snapshot", None) or {}).get("mode"),
            "stops": json.loads(json.dumps(getattr(rig1.coord, "_guard_stops", None), default=str)),
        }
    if os.environ.get("PIPELINE_REPLAY_DEBUG"):
        report["_debug"] = {
            "stops": json.loads(json.dumps(getattr(rig.coord, "_guard_stops", None), default=str)),
            "why": getattr(rig.coord, "_guard_hand_back_why", None),
            "facts": getattr(rig.coord, "_hand_back_facts", None),
            "snapshot_mode": (getattr(rig.coord, "_phase_guard_snapshot", None) or {}).get("mode"),
            "ledger": [e for e in getattr(rig.coord._ev_devices["links"], "command_ledger", [])][-6:],
        }

    # ── (#1381 D28) the mode layer, Now and the thin-sun rule ────────────
    # Kept to the API both trees share: stored strategy keys and the plain
    # ``set_plan_override`` (the base tree has neither the four modes nor the
    # user's Now marker). Expected differences are stated in the report.
    report.update(await _mode_and_now_days(freezer))

    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(report, fh)


def _sun_day_steps(day, start_h=6.0, end_h=20.0, step=60):
    t0 = datetime(2026, 6, day, 0, 0, tzinfo=timezone.utc).timestamp()
    return [(t0 + h * 3600, {"_hour": h})
            for h in [start_h + i * step / 3600
                      for i in range(int((end_h - start_h) * 3600 / step))]]


def _sun_values(hh, *, thin=False, plugged=True):
    """A June day: a clear bell (peak 6 kW at 13:00), or thin sun (1.5 kW
    flat from 9 to 17 h). 400 W house, no battery power."""
    import math
    if thin:
        solar = 1500.0 if 9.0 <= hh < 17.0 else 0.0
    else:
        solar = max(0.0, 6000.0 * math.sin(math.pi * (hh - 6.0) / 14.0)) if 6 <= hh <= 20 else 0.0
    return {"sensor.solar": solar, "sensor.batt": 0.0, "sensor.soc": 100.0,
            "sensor.grid": solar - 400.0, "sensor.ev": 0.0,   # SEM sign: + export
            "binary_sensor.car_connected": "on" if plugged else "off",
            "number.car_current": 16}


async def _mode_and_now_days(freezer):
    from .cycle_rig import CycleRig
    out = {}

    def _move(t):
        freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))

    # 1. A mode change mid-day: Sun + tariff with help (min_plus_solar) until
    #    noon, then Sun without help (solar_only). Expected: identical — the
    #    stored strategies are the same in both trees.
    rig = CycleRig(config=dict(WIRED), chargers=[_charger(
        "car", power="sensor.ev", mode="min_plus_solar",
        ev_connected_sensor="binary_sensor.car_connected",
        ev_current_control_entity="number.car_current")])

    def _set_mode_day(rig_, values, t):
        hh = values["_hour"]
        if hh >= 12.0:
            for c in rig_.coord.config.get("ev_chargers") or []:
                c["charge_mode"] = "solar_only"
        _set_states(rig_, _sun_values(hh), t)

    _dbg = []
    if os.environ.get("PIPELINE_REPLAY_DEBUG"):
        from custom_components.solar_energy_management.coordinator import decide as _cm
        _orig = _cm.decide

        def _wrap(view, _o=_orig):
            d = _o(view)
            _dbg.append([view.fleet.is_night, view.power.connected, view.mode,
                         d.intent.value, d.commanded_amps, d.reason[:80]])
            return d
        _cm.decide = _wrap
    out["synthetic-mode-change"] = await _run(
        rig, _sun_day_steps(10), _set_mode_day, _move)
    if _dbg:
        from custom_components.solar_energy_management.coordinator import decide as _cm
        _cm.decide = _orig
        out["_mode_decisions"] = _dbg[::60]
    if os.environ.get("PIPELINE_REPLAY_DEBUG"):
        out["_mode_debug"] = json.loads(json.dumps({
            "state": getattr(rig.coord, "_owner_trail", None),
            "data": {k: v for k, v in (getattr(rig.coord, "data", None) or {}).items()
                     if "charg" in str(k) or "strategy" in str(k)},
        }, default=str))

    # 2. Now: a 2-hour force at 08:00 (the plan card's Charge now), the car
    #    unplugged at 09:00 and plugged again at 09:30. Expected difference:
    #    the branch ends Now on the unplug (D22), so after 09:30 it charges
    #    from the sun only; the base keeps full power until 10:00.
    rig = CycleRig(config=dict(WIRED), chargers=[_charger(
        "car", power="sensor.ev", mode="solar_plus_battery",
        ev_connected_sensor="binary_sensor.car_connected",
        ev_current_control_entity="number.car_current")])
    armed = {"done": False}

    def _set_now_day(rig_, values, t):
        hh = values["_hour"]
        if hh >= 8.0 and not armed["done"]:
            armed["done"] = True
            rig_.coord.set_plan_override("car", "force", 120)
        _set_states(rig_, _sun_values(hh, plugged=not (9.0 <= hh < 9.5)), t)

    out["synthetic-now-unplug"] = await _run(
        rig, _sun_day_steps(11, 7.5, 11.0), _set_now_day, _move)

    # 3. Thin sun on one price (import 0.30, export 0.075), no battery,
    #    Sun + tariff without help (solar_plus_cheap). Expected difference:
    #    the base tree has no thin-sun rule (#1411 lives on this branch), so
    #    only the branch may charge at the minimum in thin sun, and only
    #    inside a thin-sun block of the plan.
    cfg = dict(WIRED)
    cfg.update({"electricity_import_rate": 0.30, "electricity_export_rate": 0.075})
    rig = CycleRig(config=cfg, chargers=[_charger(
        "car", power="sensor.ev", mode="solar_plus_cheap",
        ev_connected_sensor="binary_sensor.car_connected",
        ev_current_control_entity="number.car_current")])

    def _set_thin_day(rig_, values, t):
        _set_states(rig_, _sun_values(values["_hour"], thin=True), t)

    out["synthetic-thin-sun"] = await _run(
        rig, _sun_day_steps(12), _set_thin_day, _move)
    return out
