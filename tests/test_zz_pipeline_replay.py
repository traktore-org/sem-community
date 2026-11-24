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
    links_on = sim["states"].get("switch.links_enable", "on") == "on"
    rechts_on = sim["states"].get("switch.rechts_enable", "on") == "on"
    links_a = 12.0 if links_on else 0.0       # Audi ~8.3 kW
    rechts_a = 6.0 if (rechts_on and 16.5 <= hh < 21.0) else 0.0
    heat_l3 = 8.0 if 16.71 <= hh < 16.76 else 0.0    # 16:43–16:45 peak
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
        "number.links_current": 16, "number.rechts_current": 16,
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
    cfg.update({
        "phase_guard_enabled": True, "phase_guard_enforcement_enabled": True,
        "phase_guard_topology": "grid_only", "phase_guard_phase_count": 3,
        "phase_guard_grid_limit_a": 23,
        "phase_guard_grid_l1_current_entity": "sensor.l1",
        "phase_guard_grid_l2_current_entity": "sensor.l2",
        "phase_guard_grid_l3_current_entity": "sensor.l3",
    })
    chargers = [
        _charger("links", power="sensor.links_power", mode="always_max",
                 external_control_mode="yield", priority=1),
        _charger("rechts", power="sensor.rechts_power", mode="always_max",
                 external_control_mode="yield", priority=2),
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

    with gzip.open(OUT, "wt", encoding="utf-8") as fh:
        json.dump(report, fh)
