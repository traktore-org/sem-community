"""#1420 — the phase guard's override reaches only a yielded charger that draws.

The reporter's morning of 25.11 (2.3.0-beta.27): two Wallboxes another party
steers ("SEM yields"). Laadpaal Links charged at 14 A; L1 read 24 A against a
23 A limit. The log said the guard was "stopping" both chargers — also
Laadpaal Rechts, which drew nothing.

The guard's reason to override the yield was the phase alone, so the whole
reconciler ran for the idle box too, every cycle the phase stayed over, and
any row it picked went out through the yield gate: an unplug in that time
switched the box off ("park off"), a stop the hand-back drops as "car gone".
The log line claimed a stop before anything was sent. Stopping a charger
that draws nothing takes no current off the phase.

Now the guard also asks the charger: one every reading shows idle gets no
override. A dark or missing reading is not idle; a charger that just started
(raw draw, the smoothed value still 0) or whose status says charging keeps
its stop. The log says what went out.

The real coordinator cycle (``CycleRig``), real devices, adapters and send
seam.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from .cycle_rig import CycleRig

LIMIT_A = 23

WIRED = {
    "solar_production_sensor": "sensor.solar",
    "grid_power_sensor": "sensor.grid",
    "battery_power_sensor": "sensor.batt",
    "battery_soc_sensor": "sensor.soc",
    "ev_power_sensor": "sensor.ev",
    "battery_capacity_kwh": 10.0,
    "battery_reserve_soc": 20,
    "phase_guard_enabled": True, "phase_guard_enforcement_enabled": True,
    "phase_guard_topology": "grid_only", "phase_guard_phase_count": 3,
    "phase_guard_grid_limit_a": LIMIT_A,
    "phase_guard_grid_l1_current_entity": "sensor.l1",
    "phase_guard_grid_l2_current_entity": "sensor.l2",
    "phase_guard_grid_l3_current_entity": "sensor.l3",
}


def _charger(cid, priority):
    return {"id": cid, "name": cid, "ev_min_current": 6, "ev_max_current": 16,
            "ev_phases": 3, "ev_voltage": 230,
            "ev_current_control_entity": f"number.{cid}_current",
            "ev_connected_sensor": f"binary_sensor.{cid}_connected",
            "ev_power_sensor": f"sensor.{cid}_power",
            "ev_charging_power_sensor": f"sensor.{cid}_power",
            "charge_mode": "always_max", "external_control_mode": "yield",
            "priority": priority, "ev_target_type": "kwh",
            "daily_ev_target": 10}


def _fresh(rig):
    """Every reading is fresh (the guard reads ``last_reported``)."""
    from homeassistant.util import dt as dt_util
    store = rig.hass.states
    orig = store.get

    def _get(entity_id, _orig=orig):
        st = _orig(entity_id)
        if st is not None:
            now = dt_util.utcnow()
            st.last_reported = now
            st.last_updated = now
        return st

    store.get = _get


def _rig(cids=("links", "rechts")):
    rig = CycleRig(config=dict(WIRED),
                   chargers=[_charger(c, i + 1) for i, c in enumerate(cids)])
    for cid in cids:
        rig.coord._ev_devices[cid].start_stop_entity = f"switch.{cid}_enable"
    _fresh(rig)
    return rig


def _values(*, links_a, rechts_w, house_a=10.0, rechts_power=None):
    """``links_a`` on all three phases; ``rechts_w`` is what Rechts draws;
    ``rechts_power`` overrides the state its power sensor shows."""
    rechts_a = rechts_w / (3 * 230)
    l = {p: house_a + links_a + rechts_a for p in ("l1", "l2", "l3")}
    shown = rechts_w if rechts_power is None else rechts_power
    return {
        "sensor.solar": 0.0, "sensor.batt": 0.0, "sensor.soc": 40.0,
        "sensor.grid": -(sum(l.values()) * 230),
        "sensor.ev": links_a * 3 * 230 + rechts_w,
        "sensor.links_power": links_a * 3 * 230,
        "sensor.rechts_power": shown,
        "binary_sensor.links_connected": "on",
        "binary_sensor.rechts_connected": "on",
        "switch.links_enable": "on", "switch.rechts_enable": "on",
        "number.links_current": 14, "number.rechts_current": 14,
        "sensor.l1": (round(l["l1"], 1), {"unit_of_measurement": "A"}),
        "sensor.l2": (round(l["l2"], 1), {"unit_of_measurement": "A"}),
        "sensor.l3": (round(l["l3"], 1), {"unit_of_measurement": "A"}),
    }


async def _cycle(rig, freezer, t, values):
    freezer.move_to(datetime.fromtimestamp(t, tz=timezone.utc))
    for eid, val in values.items():
        rig.hass.states.set(eid, val)
    await rig.coord._async_update_data()


def _touched(rig, cid):
    """Every service call that named one of this charger's entities."""
    return [c for c in rig.calls
            if cid in str((c[2] or {}).get("entity_id", ""))]


T0 = datetime(2026, 11, 25, 4, 10, tzinfo=timezone.utc).timestamp()


async def _quiet_then_over(rig, freezer, *, over, quiet=None, cycles=3):
    """Three quiet cycles under the limit, then ``cycles`` over it."""
    quiet = quiet or _values(links_a=0.0, rechts_w=0.0)
    t = T0
    for _ in range(3):
        await _cycle(rig, freezer, t, quiet)
        t += 10
    assert rig.calls == [], "nothing is sent to yielded chargers under the limit"
    for _ in range(cycles):
        await _cycle(rig, freezer, t, over)
        t += 10


@pytest.mark.asyncio
async def test_the_morning_of_25_november(freezer, caplog):
    """Links draws 14 A, L1 at 24 A > 23 A: Links is stopped, Rechts —
    idle, 0 W — gets nothing, and no line says it was stopped."""
    import logging
    caplog.set_level(logging.INFO)
    rig = _rig()
    quiet = _values(links_a=14.0, rechts_w=0.0, house_a=7.0)
    over = _values(links_a=14.0, rechts_w=0.0, house_a=10.0)
    await _quiet_then_over(rig, freezer, quiet=quiet, over=over)
    assert ("switch", "turn_off", {"entity_id": "switch.links_enable"}) in rig.calls
    assert _touched(rig, "rechts") == []
    assert "rechts" not in (getattr(rig.coord, "_guard_stops", None) or {})
    text = caplog.text
    assert "rechts draws nothing" in text
    assert "overrides yield" in text and "links" in text
    for line in text.splitlines():
        if "overrides yield" in line or "phase guard stopped" in line:
            assert "rechts" not in line, line


@pytest.mark.asyncio
async def test_the_idle_charger_never_runs_the_reconciler(freezer, monkeypatch):
    """The override let the whole reconciler run for the idle box, every
    cycle the phase stayed over. Whatever row it picked went out through
    the yield gate — a stop, a failsafe, the "car left" park-off. It now
    runs only for the charger that draws."""
    from custom_components.solar_energy_management.coordinator import (
        charger_reconciler as cr,
    )
    ran = []
    orig = cr.ChargerReconciler.reconcile_and_apply

    async def _spy(self, decision, adapter, power, now):
        ran.append(self.charger_id)
        return await orig(self, decision, adapter, power, now)

    monkeypatch.setattr(cr.ChargerReconciler, "reconcile_and_apply", _spy)
    rig = _rig()
    quiet = _values(links_a=14.0, rechts_w=0.0, house_a=7.0)
    over = _values(links_a=14.0, rechts_w=0.0, house_a=10.0)
    await _quiet_then_over(rig, freezer, quiet=quiet, over=over, cycles=6)
    assert "links" in ran, "the drawing charger must still be stopped"
    assert "rechts" not in ran


@pytest.mark.asyncio
async def test_a_status_that_says_charging_is_stopped(freezer):
    """A cloud charger's power lags its status by a minute or more: power
    0 W, status "Charging". It draws; the stop goes out."""
    rig = _rig()
    rig.coord._ev_devices["rechts"].charging_status_entity = "sensor.rechts_status"
    quiet = _values(links_a=14.0, rechts_w=0.0, house_a=7.0)
    quiet["sensor.rechts_status"] = "Ready"
    over = _values(links_a=14.0, rechts_w=0.0, house_a=10.0)
    over["sensor.rechts_status"] = "Charging"
    await _quiet_then_over(rig, freezer, quiet=quiet, over=over)
    assert ("switch", "turn_off", {"entity_id": "switch.rechts_enable"}) in rig.calls


@pytest.mark.asyncio
async def test_an_idle_status_and_0_w_are_idle(freezer):
    """The same charger with its status "Ready" and 0 W: nothing is sent."""
    rig = _rig()
    rig.coord._ev_devices["rechts"].charging_status_entity = "sensor.rechts_status"
    quiet = _values(links_a=14.0, rechts_w=0.0, house_a=7.0)
    quiet["sensor.rechts_status"] = "Ready"
    over = _values(links_a=14.0, rechts_w=0.0, house_a=10.0)
    over["sensor.rechts_status"] = "Ready"
    await _quiet_then_over(rig, freezer, quiet=quiet, over=over)
    assert ("switch", "turn_off", {"entity_id": "switch.links_enable"}) in rig.calls
    assert _touched(rig, "rechts") == []


@pytest.mark.asyncio
async def test_house_load_over_the_limit_stops_no_idle_charger(freezer):
    """No car draws; the house alone puts L1 over. No charger is stopped:
    stopping one takes no current off the phase."""
    rig = _rig()
    over = _values(links_a=0.0, rechts_w=0.0, house_a=26.0)
    await _quiet_then_over(rig, freezer, over=over)
    assert _touched(rig, "links") == []
    assert _touched(rig, "rechts") == []
    assert not (getattr(rig.coord, "_guard_stops", None) or {})


@pytest.mark.asyncio
async def test_the_single_charger_path_asks_the_charger_too(freezer, monkeypatch):
    """The legacy single-charger branch (no fleet list) uses the same rule:
    an idle yielded charger over a house overload gets nothing, and its
    reconciler does not run; once it draws, it is stopped."""
    from custom_components.solar_energy_management.coordinator import (
        charger_reconciler as cr,
    )
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    ran = []
    orig = cr.ChargerReconciler.reconcile_and_apply

    async def _spy(self, decision, adapter, power, now):
        ran.append(self.charger_id)
        return await orig(self, decision, adapter, power, now)

    monkeypatch.setattr(cr.ChargerReconciler, "reconcile_and_apply", _spy)
    cfg = dict(WIRED)
    cfg["ev_chargers"] = [dict(_charger("ev_charger", 1),
                               ev_power_sensor="sensor.links_power",
                               ev_charging_power_sensor="sensor.links_power")]
    cfg["ev_power_sensor"] = "sensor.links_power"
    rig = CycleRig(config=cfg, chargers=[])
    dev = CurrentControlDevice(
        rig.hass, device_id="ev_charger", name="ev_charger", priority=1,
        min_current=6.0, max_current=16.0, phases=3, voltage=230.0,
        entity_id=None, power_entity_id="sensor.links_power",
        current_entity_id="number.links_current", charger_service=None,
        charger_service_entity_id=None)
    dev.start_stop_entity = "switch.links_enable"
    rig.coord._ev_devices = {}
    rig.coord._ev_device = dev
    _fresh(rig)
    over = _values(links_a=0.0, rechts_w=0.0, house_a=26.0)
    await _quiet_then_over(rig, freezer, over=over)
    assert _touched(rig, "links") == [], "an idle charger is not stopped"
    assert ran == [], "an idle yielded charger runs no reconciler"
    t = T0 + 600
    for _ in range(3):
        await _cycle(rig, freezer, t, _values(links_a=14.0, rechts_w=0.0,
                                              house_a=10.0))
        t += 10
    assert ("switch", "turn_off", {"entity_id": "switch.links_enable"}) in rig.calls


# ── the check itself: every reading must say "nothing" ───────────────────

def _check_rig(raw="0", *, unit="W", status=None, smoothed=0.0, charging=False):
    from types import SimpleNamespace
    from custom_components.solar_energy_management.coordinator.charger_adapters import (
        adapter_for,
    )
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerPower,
    )
    rig = _rig(("rechts",))
    dev = rig.coord._ev_devices["rechts"]
    if raw is not None:
        rig.hass.states.set("sensor.rechts_power",
                            (raw, {"unit_of_measurement": unit}))
    if status is not None:
        dev.charging_status_entity = "sensor.rechts_status"
        rig.hass.states.set("sensor.rechts_status", status)
    power = ChargerPower(charger_id="rechts", power_w=smoothed,
                         connected=True, charging=charging)
    return adapter_for(dev), power, SimpleNamespace


def _idle(**kw):
    from custom_components.solar_energy_management.coordinator.active_phase_guard import (
        charger_draws_nothing,
    )
    adapter, power, _ = _check_rig(**kw)
    return charger_draws_nothing(adapter, power)


def test_every_reading_idle_is_idle():
    assert _idle() is True
    assert _idle(raw="0.0", unit="kW") is True
    assert _idle(status="Ready") is True


def test_a_dark_or_missing_own_sensor_is_not_idle():
    assert _idle(raw="unavailable") is False
    assert _idle(raw="unknown") is False
    assert _idle(raw="nan") is False
    assert _idle(raw=None) is False          # no state at all


def test_the_raw_draw_counts_while_the_smoothed_one_lags():
    assert _idle(raw="4140") is False
    assert _idle(raw="4.1", unit="kW") is False
    assert _idle(raw="-4140") is False       # a sign SEM did not expect


def test_a_flag_or_status_that_says_charging_is_not_idle():
    assert _idle(charging=True) is False
    assert _idle(status="Charging") is False
    assert _idle(smoothed=4140.0) is False


def test_no_device_sensor_or_a_mock_adapter_is_not_idle():
    from types import SimpleNamespace
    from unittest.mock import MagicMock
    from custom_components.solar_energy_management.coordinator.active_phase_guard import (
        charger_draws_nothing,
    )
    adapter, power, _ = _check_rig()
    adapter._device.power_entity_id = None
    assert charger_draws_nothing(adapter, power) is False
    assert charger_draws_nothing(MagicMock(), power) is False
    assert charger_draws_nothing(adapter, SimpleNamespace()) is False


def test_the_coordinator_must_name_the_charger():
    """The coordinator's entry takes the charger and its yield as required
    keywords; a caller that leaves them out fails at once. (The method
    called without them keeps the stop: ``test_1381_phase_guard_yield``.)"""
    import inspect
    from custom_components.solar_energy_management.coordinator import active_phase_guard as apg
    params = inspect.signature(apg.yield_override_reason).parameters
    for name in ("adapter", "power", "yielded"):
        assert params[name].kind is inspect.Parameter.KEYWORD_ONLY
        assert params[name].default is inspect.Parameter.empty


def test_a_charger_sem_steers_is_not_asked():
    """No override is needed for a charger SEM steers: its own stop goes
    out as always. The entry answers "" for it, and says nothing."""
    from types import SimpleNamespace
    from custom_components.solar_energy_management.coordinator import active_phase_guard as apg
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision,
        ChargerIntent,
    )
    adapter, power, _ = _check_rig(raw="9000", smoothed=9000.0, charging=True)
    row = {"current_a": 24.0, "limit_a": 23.0, "margin_a": -1.0,
           "safe": False, "data_fresh": True, "reason": "over_limit"}
    guard = apg.ActivePhaseGuard()
    guard.update({"topology": "grid_only", "phase_count": 3, "safe": False,
                  "data_fresh": True, "stop_reason": "",
                  "grid": {"l1": row, "l2": dict(row), "l3": dict(row)},
                  "inverter": {}},
                 {"phase_guard_enabled": True,
                  "phase_guard_enforcement_enabled": True})
    coord = SimpleNamespace(_active_phase_guard=guard)
    decision = guard.filter_decision(ChargerDecision(
        charger_id="rechts", mode="pv", intent=ChargerIntent.CHARGE_AT_AMPS,
        commanded_amps=16, budget_w=11000.0, reason="x"))
    assert apg.yield_override_reason(coord, decision, adapter=adapter,
                                     power=power, yielded=True) \
        == "phase L1 at 24.0 A > 23.0 A"
    assert apg.yield_override_reason(coord, decision, adapter=adapter,
                                     power=power, yielded=False) == ""


@pytest.mark.asyncio
async def test_an_unplug_during_the_overload_does_not_park_the_box_off():
    """The one write the old override could send to an idle yielded box.
    Rechts has a car but draws nothing while L2 is over; the car leaves
    while L2 stays over. With the reconciler run for it, the "car left" row
    switched the box off through the yield gate — owed, but dropped by the
    hand-back as "car gone", so the other party's next session could not
    start. Real guard, reconciler, adapter and send seam."""
    from custom_components.solar_energy_management.coordinator.active_phase_guard import (
        ActivePhaseGuard,
    )
    from custom_components.solar_energy_management.coordinator.actuate import actuate
    from custom_components.solar_energy_management.coordinator.charger_adapters import (
        adapter_for,
    )
    from custom_components.solar_energy_management.coordinator.charger_reconciler import (
        PARK_ON_DISCONNECT_CYCLES,
        ChargerReconciler,
    )
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision,
        ChargerIntent,
        ChargerPower,
    )
    from custom_components.solar_energy_management.devices.base import (
        CurrentControlDevice,
    )
    from .cycle_rig import make_hass

    def _reading(current):
        row = {"current_a": current, "limit_a": 23.0, "margin_a": 23.0 - current,
               "safe": current <= 23.0, "data_fresh": True,
               "reason": "over_limit" if current > 23.0 else None}
        calm = dict(row, current_a=10.0, margin_a=13.0, safe=True, reason=None)
        return {"topology": "grid_only", "phase_count": 3,
                "safe": current <= 23.0, "data_fresh": True, "stop_reason": "",
                "grid": {"l1": calm, "l2": row, "l3": dict(calm)},
                "inverter": {}}

    guard = ActivePhaseGuard()
    guard.update(_reading(24.0), {"phase_guard_enabled": True,
                                  "phase_guard_enforcement_enabled": True})
    hass = make_hass({"sensor.rechts_power": "0",
                      "switch.rechts_enable": "on"})
    dev = CurrentControlDevice(
        hass, device_id="rechts", name="rechts", priority=2,
        min_current=6.0, max_current=16.0, phases=3, voltage=230.0,
        entity_id=None, power_entity_id="sensor.rechts_power",
        current_entity_id="number.rechts_current", charger_service=None,
        charger_service_entity_id=None)
    dev.start_stop_entity = "switch.rechts_enable"
    adapter = adapter_for(dev)
    rec = ChargerReconciler(charger_id="rechts", heartbeat_s=5.0)
    rec._seen_connected = True          # it had a car before the overload
    for _ in range(PARK_ON_DISCONNECT_CYCLES + 2):
        decision = guard.filter_decision(ChargerDecision(
            charger_id="rechts", mode="pv", intent=ChargerIntent.IDLE,
            commanded_amps=0, budget_w=0.0, reason="yields"))
        assert decision.intent is ChargerIntent.DISABLE
        power = ChargerPower(charger_id="rechts", power_w=0.0,
                             connected=False, charging=False)
        reason = guard.yield_override_reason(decision, adapter=adapter,
                                             power=power)
        await actuate(decision, adapter, power, rec, yielded=True,
                      phase_override=reason)
    hass.services.async_call.assert_not_called()
    assert not [e for e in dev.command_ledger if e.get("owed")]
