"""#1422 — the phase guard's stop reaches a charger whose power sensor is dark.

Found while fixing #1420. With a phase over its limit the guard stops the
chargers. The reconciler sends nothing to a charger that is already stopped,
and it decided "stopped" from the status sensor, else the power. A dark
power sensor reads 0.0 W after the median, so a charging box with no status
sensor looked stopped: two chargers SEM steers, L1 over its limit, the
charging one's power sensor "unavailable" — six cycles, no write.

Now the reading says when it is no reading (``ChargerPower.power_known``,
from the reader's per-charger flags), and the reconciler calls a charger
"blind" when no power and no status answers. A stop that must go out goes
out once per blind spell; a stop SEM only prefers is not sent blind. A blind
cycle is no "stopped" evidence for the failsafe recogniser, the "stop is
not taking" count or the #627 Repair either.
"""
from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_reconciler import (
    STOP_REASSERT_DWELL_S,
    ActionKind,
    ChargerReconciler,
    DesiredState,
    ObservedState,
    observe,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerPower,
)

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
    """A charger SEM steers, with no status sensor."""
    return {"id": cid, "name": cid, "ev_min_current": 6, "ev_max_current": 16,
            "ev_phases": 3, "ev_voltage": 230,
            "ev_current_control_entity": f"number.{cid}_current",
            "ev_connected_sensor": f"binary_sensor.{cid}_connected",
            "ev_power_sensor": f"sensor.{cid}_power",
            "ev_charging_power_sensor": f"sensor.{cid}_power",
            "charge_mode": "always_max",
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


def _rig():
    rig = CycleRig(config=dict(WIRED),
                   chargers=[_charger("links", 1), _charger("rechts", 2)])
    for cid in ("links", "rechts"):
        rig.coord._ev_devices[cid].start_stop_entity = f"switch.{cid}_enable"
    _fresh(rig)
    return rig


def _values(*, links_a, house_a, links_power):
    """Links draws ``links_a`` on all three phases; its power sensor shows
    ``links_power``. Rechts has a car and draws nothing (a live 0 W)."""
    l = {p: house_a + links_a for p in ("l1", "l2", "l3")}
    return {
        "sensor.solar": 0.0, "sensor.batt": 0.0, "sensor.soc": 40.0,
        "sensor.grid": -(sum(l.values()) * 230),
        "sensor.ev": links_a * 3 * 230,
        "sensor.links_power": links_power,
        "sensor.rechts_power": 0.0,
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


def _stops(rig, cid):
    return [c for c in rig.calls
            if c[:2] == ("switch", "turn_off")
            and (c[2] or {}).get("entity_id") == f"switch.{cid}_enable"]


T0 = datetime(2026, 11, 25, 4, 10, tzinfo=timezone.utc).timestamp()


async def _run(rig, freezer, *, quiet, over, cycles):
    """Quiet until the guard lets the chargers run (its start-up hold is
    three cycles), then ``cycles`` over the limit."""
    t = T0
    for _ in range(5):
        await _cycle(rig, freezer, t, quiet)
        t += 10
    before = len(rig.calls)
    for _ in range(cycles):
        await _cycle(rig, freezer, t, over)
        t += 10
    return before, t


# ── The issue's case, through the real cycle ──────────────────────────


@pytest.mark.asyncio
async def test_the_dark_charging_box_gets_the_guard_stop_once(freezer):
    """Links charges 14 A with its power sensor "unavailable"; L1 goes to
    24 A > 23 A. Before: six cycles, no write. Now: one stop goes out, and
    no more while Links stays dark. Rechts (a live 0 W) gets none."""
    rig = _rig()
    quiet = _values(links_a=14.0, house_a=1.0, links_power="unavailable")
    over = _values(links_a=14.0, house_a=10.0, links_power="unavailable")
    before, _ = await _run(rig, freezer, quiet=quiet, over=over, cycles=6)
    assert rig.coord._charger_reconcilers["links"]._last_desired == "OFF"
    stops = [c for c in rig.calls[before:] if c in _stops(rig, "links")]
    assert len(stops) == 1, rig.calls[before:]
    assert _stops(rig, "rechts") == []
    # the power reading carried "no number" through the cycle
    rec = rig.coord._charger_reconcilers["links"]
    assert rec._blind_stop_sent is True


@pytest.mark.asyncio
async def test_a_live_0_w_box_gets_no_guard_stop(freezer):
    """The control: the same overload with Links' sensor live at 0 W (a box
    that really stopped) sends Links nothing — the spam fix stands."""
    rig = _rig()
    quiet = _values(links_a=0.0, house_a=21.0, links_power=0.0)
    over = _values(links_a=0.0, house_a=24.0, links_power=0.0)
    before, _ = await _run(rig, freezer, quiet=quiet, over=over, cycles=6)
    assert _stops(rig, "links") == []
    assert _stops(rig, "rechts") == []


@pytest.mark.asyncio
async def test_a_new_blind_spell_gets_one_more_stop(freezer):
    """A reading ends the spell: dark, then live (still charging, the
    usual re-assert), then dark again — the new spell gets its own one."""
    rig = _rig()
    quiet = _values(links_a=14.0, house_a=1.0, links_power="unavailable")
    over_dark = _values(links_a=14.0, house_a=10.0, links_power="unavailable")
    before, t = await _run(rig, freezer, quiet=quiet, over=over_dark, cycles=3)
    assert len([c for c in rig.calls[before:]
                if c in _stops(rig, "links")]) == 1
    rec = rig.coord._charger_reconcilers["links"]
    # a live 0 W: the box stopped; the spell is over
    over_live = _values(links_a=0.0, house_a=24.0, links_power=0.0)
    for _ in range(3):
        await _cycle(rig, freezer, t, over_live)
        t += 10
    assert rec._blind_stop_sent is False
    mid = len(rig.calls)
    t += STOP_REASSERT_DWELL_S
    for _ in range(3):
        await _cycle(rig, freezer, t, over_dark)
        t += 10
    assert len([c for c in rig.calls[mid:]
                if c in _stops(rig, "links")]) == 1, rig.calls[mid:]


# ── The reader carries "no number" ────────────────────────────────────


@pytest.mark.asyncio
async def test_the_reader_marks_each_chargers_own_read(freezer):
    rig = _rig()
    vals = _values(links_a=14.0, house_a=7.0, links_power="unavailable")
    await _cycle(rig, freezer, T0, vals)
    power = rig.coord._sensor_reader.read_power()
    assert power.ev_power_per_charger_read == {"links": False, "rechts": True}
    assert power.ev_power_per_charger["links"] == 0.0


def test_charger_power_known_follows_the_watts_it_goes_with():
    from types import SimpleNamespace

    from custom_components.solar_energy_management.coordinator.ev_availability import (
        charger_power_known,
    )
    per = SimpleNamespace(ev_power_per_charger={"a": 0.0, "b": 0.0},
                          ev_power_per_charger_read={"a": False, "b": True},
                          ev_power_fleet_read=True)
    assert charger_power_known("a", per) is False
    assert charger_power_known("b", per) is True
    # a charger with no own entry reads the fleet sensor — and its answer
    fleet = SimpleNamespace(ev_power_per_charger={}, ev_power_fleet_read=False)
    assert charger_power_known("a", fleet) is False
    # unsaid is today's meaning
    assert charger_power_known("a", SimpleNamespace()) is True
    assert ChargerPower(charger_id="a").power_known is True


# ── The reconciler's blind row ────────────────────────────────────────


def _blind(**kw):
    base = dict(charging=False, setpoint_a=0, self_charging=False,
                power_w=0.0, draw_known=False)
    base.update(kw)
    return ObservedState(**base)


def _seen(**kw):
    return _blind(draw_known=True, **kw)


def _kinds(actions):
    return [a.kind for a in actions]


def test_a_demand_stop_goes_out_once_per_blind_spell():
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    t = 1000.0
    assert _kinds(r.reconcile(DesiredState.OFF, 0, _blind(), t)) == [ActionKind.DISABLE]
    for i in range(1, 20):
        assert _kinds(r.reconcile(
            DesiredState.OFF, 0, _blind(), t + i * 70)) == [ActionKind.NONE]
    # a reading ends the spell; the next spell gets one stop
    t += 2000
    assert _kinds(r.reconcile(DesiredState.OFF, 0, _seen(), t)) == [ActionKind.NONE]
    assert _kinds(r.reconcile(
        DesiredState.OFF, 0, _blind(), t + 70)) == [ActionKind.DISABLE]


def test_a_stop_sem_only_prefers_is_not_sent_blind():
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    for i in range(10):
        assert _kinds(r.reconcile(
            DesiredState.IDLE, 0, _blind(), 1000.0 + i * 70)) == [ActionKind.NONE]


def test_a_peak_emergency_idle_is_a_demand():
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    assert _kinds(r.reconcile(DesiredState.IDLE, 0, _blind(), 1000.0,
                              safety_stop=True)) == [ActionKind.DISABLE]
    assert _kinds(r.reconcile(DesiredState.IDLE, 0, _blind(), 1100.0,
                              safety_stop=True)) == [ActionKind.NONE]


def test_a_cycle_that_asks_no_stop_ends_the_spell():
    """Guard releases (CHARGE), trips again, still dark: one more stop."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    assert _kinds(r.reconcile(DesiredState.OFF, 0, _blind(), 1000.0)) == [ActionKind.DISABLE]
    r.reconcile(DesiredState.CHARGE, 16, _blind(), 1100.0)
    assert ActionKind.DISABLE in _kinds(
        r.reconcile(DesiredState.OFF, 0, _blind(), 1200.0))


def test_the_spell_waits_out_the_dwell_of_a_stop_just_sent():
    """A stop went out while the box still read drawing; it went dark the
    next cycle. The blind stop waits for the dwell, then goes once."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    drawing = _seen(charging=True, power_w=9000.0)
    assert _kinds(r.reconcile(DesiredState.OFF, 0, drawing, 1000.0)) == [ActionKind.DISABLE]
    assert _kinds(r.reconcile(DesiredState.OFF, 0, _blind(), 1010.0)) == [ActionKind.NONE]
    assert _kinds(r.reconcile(
        DesiredState.OFF, 0, _blind(), 1000.0 + STOP_REASSERT_DWELL_S)) == [ActionKind.DISABLE]
    assert _kinds(r.reconcile(
        DesiredState.OFF, 0, _blind(), 1200.0)) == [ActionKind.NONE]


def test_nothing_sent_is_not_the_spells_stop():
    """Observer mode / a yield withholds the write: the one stop is still owed."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    assert ActionKind.DISABLE in _kinds(
        r.reconcile(DesiredState.OFF, 0, _blind(), 1000.0, sending=False))
    assert r._blind_stop_sent is False
    assert ActionKind.DISABLE in _kinds(
        r.reconcile(DesiredState.OFF, 0, _blind(), 1010.0, sending=True))
    assert r._blind_stop_sent is True


def test_no_mechanism_or_a_locked_switch_sends_nothing_blind():
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    assert _kinds(r.reconcile(DesiredState.OFF, 0, _blind(stop_controllable=False),
                              1000.0)) == [ActionKind.NONE]
    r = ChargerReconciler(charger_id="b", heartbeat_s=30.0)
    assert _kinds(r.reconcile(DesiredState.OFF, 0, _blind(enable_controllable=False),
                              1000.0)) == [ActionKind.NONE]


def test_a_draw_seen_is_not_blind():
    """The median still holds the draw for a cycle: the drawing row runs."""
    o = _blind(charging=True, power_w=9000.0)
    assert o.blind is False
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    assert _kinds(r.reconcile(DesiredState.OFF, 0, o, 1000.0)) == [ActionKind.DISABLE]
    assert r._blind_stop_sent is False


def test_entering_off_stops_a_blind_charger_once():
    """Mode Off: one stop for whatever may be charging — a box SEM cannot
    see too. Then nothing (#898)."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    r.reconcile(DesiredState.IDLE, 0, _seen(), 900.0)     # not Off before
    assert _kinds(r.reconcile(DesiredState.RELEASED, 0, _blind(), 1000.0)) == [ActionKind.DISABLE]
    for i in range(1, 6):
        assert ActionKind.DISABLE not in _kinds(
            r.reconcile(DesiredState.RELEASED, 0, _blind(), 1000.0 + i * 70))


def test_a_restart_already_in_off_sends_nothing_blind():
    """The latch starts set (#898): a restart in Off with a dark sensor
    sends no stop."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    assert ActionKind.DISABLE not in _kinds(
        r.reconcile(DesiredState.RELEASED, 0, _blind(), 1000.0))


def test_a_blind_cycle_is_no_settle():
    """Stopped is a reading. A blind cycle neither settles the wind-down
    nor counts as the failsafe settle, nor retires a failsafe Repair."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    r.reconcile(DesiredState.CHARGE, 16, _seen(charging=True, power_w=9000.0), 900.0)
    r.reconcile(DesiredState.OFF, 0, _seen(charging=True, power_w=9000.0), 1000.0)
    assert r._failsafe_settled_since_disable is False
    r.reconcile(DesiredState.OFF, 0, _blind(), 1010.0)
    assert r._failsafe_settled_since_disable is False
    assert r._idle_settled is False
    # the recovery that retires a failsafe Repair waits for a reading too
    r._failsafe_reported = True
    r._failsafe_interval_s = 100.0
    acts = r.reconcile(DesiredState.OFF, 0, _blind(), 1000.0 + 500.0)
    assert ActionKind.CLEAR_FAILSAFE_SUSPECTED not in _kinds(acts)
    assert r._failsafe_reported is True
    last = r._last_disable_issued_at          # the blind spell's one stop
    acts = r.reconcile(DesiredState.OFF, 0, _blind(), last + 300.0)
    assert ActionKind.CLEAR_FAILSAFE_SUSPECTED not in _kinds(acts)
    acts = r.reconcile(DesiredState.OFF, 0, _seen(), last + 310.0)
    assert ActionKind.CLEAR_FAILSAFE_SUSPECTED in _kinds(acts)


def test_hands_off_learns_no_gap_while_blind():
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    r._released_stop_at = 1000.0
    assert r._observe_self_reenable(_blind(), 1100.0) == []
    assert r._failsafe_settled_since_disable is False


# ── observe(): status answers, power does not ─────────────────────────


def _adapter(status):
    a = MagicMock()
    a.actual_charging = MagicMock(return_value=bool(status))
    a.is_self_charging = MagicMock(return_value=False)
    a.status_answer = MagicMock(return_value=status)
    a.enable_state = MagicMock(return_value=(None, True))
    a.resume_pressable = MagicMock(return_value=False)
    a._device = MagicMock(_current_setpoint=0, contactor_surface=False)
    a._device.can_stop_charging = MagicMock(return_value=True)
    return a


def test_observe_a_dark_read_with_no_status_is_blind():
    p = ChargerPower(charger_id="a", power_w=0.0, connected=True,
                     power_known=False)
    assert observe(_adapter(None), p).blind is True
    # a status that answers is a reading — either way
    assert observe(_adapter(False), p).blind is False
    assert observe(_adapter(True), p).draw_known is True
    # a live read is a reading
    live = ChargerPower(charger_id="a", power_w=0.0, connected=True)
    assert observe(_adapter(None), live).blind is False


def test_observe_without_a_status_method_is_blind_on_a_dark_read():
    a = _adapter(None)
    del a.status_answer
    p = ChargerPower(charger_id="a", power_w=0.0, power_known=False)
    assert observe(a, p).blind is True


def test_the_generic_adapter_answers_from_its_status():
    from custom_components.solar_energy_management.coordinator.charger_adapters.generic import (
        GenericAdapter,
    )
    from custom_components.solar_energy_management.coordinator.charger_adapters.keba import (
        KebaAdapter,
    )
    ad = GenericAdapter.__new__(GenericAdapter)
    for raw, want in (("charging", True), ("", None)):
        ad._status_raw = (lambda r=raw: r)
        assert ad.status_answer() is want
    ka = KebaAdapter.__new__(KebaAdapter)
    assert ka.status_answer() is None


# ── apply: a failed send is no stop ───────────────────────────────────


@pytest.mark.asyncio
async def test_a_stop_that_failed_to_leave_is_sent_again_at_the_dwell():
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision, ChargerIntent,
    )
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    adapter = _adapter(None)
    adapter.command_disable = AsyncMock(side_effect=RuntimeError("cloud down"))
    adapter._device.observer_mode = False
    adapter._device.external_yield = False
    adapter._device.phase_guard_override = False
    p = ChargerPower(charger_id="a", power_w=0.0, connected=True,
                     power_known=False)
    d = ChargerDecision(charger_id="a", mode="always_max",
                        intent=ChargerIntent.DISABLE, reason="phase guard")
    with pytest.raises(RuntimeError):
        await r.reconcile_and_apply(d, adapter, p, 1000.0)
    assert r._blind_stop_sent is False
    adapter.command_disable = AsyncMock()
    await r.reconcile_and_apply(d, adapter, p, 1010.0)      # inside the dwell
    adapter.command_disable.assert_not_awaited()
    await r.reconcile_and_apply(d, adapter, p, 1000.0 + STOP_REASSERT_DWELL_S)
    adapter.command_disable.assert_awaited_once()
    assert r._blind_stop_sent is True


@pytest.mark.asyncio
async def test_a_blind_cycle_keeps_the_stop_count_and_its_repair():
    """The "stop is not taking" count and the #627 Repair clear on a
    reading that says stopped, not on a dark one."""
    r = ChargerReconciler(charger_id="a", heartbeat_s=30.0)
    r._stop_commanded_while_drawing = 5
    r._clear_stop_unenforceable = MagicMock()
    adapter = _adapter(None)
    adapter.command_disable = AsyncMock()
    from custom_components.solar_energy_management.coordinator.charger_types import (
        ChargerDecision, ChargerIntent,
    )
    d = ChargerDecision(charger_id="a", mode="always_max",
                        intent=ChargerIntent.IDLE, reason="no surplus")
    dark = ChargerPower(charger_id="a", power_w=0.0, connected=True,
                        power_known=False)
    await r.reconcile_and_apply(d, adapter, dark, 1000.0)
    assert r._stop_commanded_while_drawing == 5
    r._clear_stop_unenforceable.assert_not_called()
    live = ChargerPower(charger_id="a", power_w=0.0, connected=True)
    await r.reconcile_and_apply(d, adapter, live, 1010.0)
    assert r._stop_commanded_while_drawing == 0
    r._clear_stop_unenforceable.assert_called_once()
