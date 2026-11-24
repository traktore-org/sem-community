"""#1381 part 3 — SEM hands back a yielded charger it stopped for the phase guard.

The reporter's night of 23→24.11: two chargers steered by another party, L3 at
28 A against a 23 A limit at 16:43, the guard switched both enable switches off
within a second, the guard was armed again at 16:47:53 — and nothing switched
either back on. At 02:00 the car was at 12 % with an 08:00 deadline, and SEM's
state read "night charging active" at 0 W.

Real send seam and real guard snapshots; the coordinator is a small namespace
with the attributes the module reads.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator import guard_hand_back as ghb
from custom_components.solar_energy_management.coordinator.actuate import actuate
from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerIntent,
)
from custom_components.solar_energy_management.consts.states import (
    ChargingState,
    get_status_message,
)
from custom_components.solar_energy_management.devices.base import ControllableDevice

T0 = 1_795_000_000.0          # an epoch; times below are offsets in seconds
LINKS, RECHTS = "laadpaal_links", "laadpaal_rechts"
SW = {LINKS: "switch.links_charging_enable", RECHTS: "switch.rechts_charging_enable"}


# ── fakes ────────────────────────────────────────────────────────────────

class _States:
    def __init__(self, init):
        self.values = dict(init)

    def get(self, entity):
        if entity not in self.values:
            return None
        return SimpleNamespace(state=self.values[entity])


def _hass(states):
    hass = MagicMock()
    hass.states = states

    async def _call(domain, service, data, blocking=True):
        ent = data.get("entity_id")
        if service == "turn_off":
            states.values[ent] = "off"
        elif service == "turn_on":
            states.values[ent] = "on"
        hass.calls.append((domain, service, ent))

    hass.calls = []
    hass.services.async_call = AsyncMock(side_effect=_call)
    return hass


def _device(cid, hass):
    class _Dev(ControllableDevice):
        async def activate(self, w):
            return 0.0

        async def deactivate(self):
            return None

        async def adjust_power(self, w):
            return 0.0

    dev = _Dev.__new__(_Dev)
    dev.hass = hass
    dev.device_id, dev.name = cid, cid
    dev.observer_mode = False
    dev.external_yield = False
    return dev


def _snapshot(mode, margins):
    """A guard runtime snapshot: grid lane only, margin per phase."""
    return {"mode": mode, "topology": "grid_only", "phase_count": 3,
            "grid": {p: {"margin_a": m, "current_a": 23.0 - m, "limit_a": 23.0}
                     for p, m in margins.items()},
            "inverter": {}}


ARMED_TIGHT = _snapshot("enforcing_armed", {"l1": 9.0, "l2": 11.0, "l3": 9.0})
ARMED_ROOMY = _snapshot("enforcing_armed", {"l1": 17.0, "l2": 18.0, "l3": 18.0})
RECOVERY = _snapshot("enforcing_recovery", {"l1": 17.0, "l2": 18.0, "l3": 18.0})


def _coord(hass, devices, *, observer=False):
    prio = {LINKS: 1, RECHTS: 2}
    c = SimpleNamespace(
        hass=hass, _ev_devices=devices, _ev_device=None,
        _observer_mode=observer, _phase_guard_snapshot={},
        _ev_priority_for=lambda cid: prio.get(cid, 9))
    return c


def _power(watts, *, absent=False):
    return SimpleNamespace(power_w=watts, car_absent=absent)


def _adapter(dev, phases=3):
    return SimpleNamespace(_device=dev, phases=phases, voltage=230,
                           min_current_a=6)


async def _guard_stop(coord, cid, watts, now):
    """One cycle of the guard's stop for a yielded charger: the real actuate
    and send seam, a reconciler stub that switches the enable off."""
    dev = coord._ev_devices[cid]
    decision = ChargerDecision(charger_id=cid, mode="pv",
                               intent=ChargerIntent.DISABLE, commanded_amps=0,
                               budget_w=0.0, reason="phase guard")

    async def _reconcile(*_a, **_k):
        await dev.send("switch", "turn_off", {"entity_id": SW[cid]}, why="guard")

    rec = SimpleNamespace(reconcile_and_apply=_reconcile)
    reason = "phase L3 at 28.0 A > 23.0 A"
    await actuate(decision, _adapter(dev), _power(watts), rec,
                  yielded=True, phase_override=reason)
    ghb.note_facts(coord, cid, _power(0.0), yielded=True)
    return ghb.note_guard_stop(coord, cid, _adapter(dev), _power(watts), reason,
                               now=now)


def _two_chargers(observer=False):
    states = _States({SW[LINKS]: "on", SW[RECHTS]: "on"})
    hass = _hass(states)
    devs = {LINKS: _device(LINKS, hass), RECHTS: _device(RECHTS, hass)}
    return _coord(hass, devs, observer=observer), states, hass


async def _tick(coord, now, snapshot, *, yielded=True):
    coord._phase_guard_snapshot = snapshot
    facts = getattr(coord, "_hand_back_facts", None)
    if not isinstance(facts, dict):
        facts = coord._hand_back_facts = {}
    for cid in coord._ev_devices:
        facts.setdefault(cid, {"car_absent": False, "priority": 9}).update(
            yielded=yielded)
    return await ghb.run_step(coord, now=now)


# ── the inverse of a stop ────────────────────────────────────────────────

def test_a_switch_turned_off_is_turned_back_on():
    inv = ghb.inverse_of({"domain": "switch", "service": "turn_off",
                          "data": {"entity_id": "switch.x"}, "prior": "on"})
    assert inv["service"] == "turn_on" and inv["left"] == "off"


def test_a_switch_that_was_already_off_needs_nothing():
    assert ghb.inverse_of({"domain": "switch", "service": "turn_off",
                           "data": {"entity_id": "switch.x"},
                           "prior": "off"}) == {"noop": True}


def test_an_unknown_prior_is_never_guessed():
    assert ghb.inverse_of({"domain": "switch", "service": "turn_off",
                           "data": {"entity_id": "switch.x"},
                           "prior": "unavailable"}) is None


def test_a_number_and_a_select_go_back_to_their_values():
    num = ghb.inverse_of({"domain": "number", "service": "set_value",
                          "data": {"entity_id": "number.a", "value": 0},
                          "prior": "14"})
    assert num["data"]["value"] == 14.0 and num["left"] == 0.0
    sel = ghb.inverse_of({"domain": "select", "service": "select_option",
                          "data": {"entity_id": "select.m", "option": "stop"},
                          "prior": "smart"})
    assert sel["data"]["option"] == "smart"


def test_a_brand_service_cannot_be_undone_and_is_not_guessed():
    rec = ghb.build_record(
        [{"domain": "wallbox_x", "service": "pause", "data": {"entity_id": "x.y"},
          "prior": "charging"}],
        now=T0, reason="r", draw_w=7000, phases=3, voltage=230, min_current_a=6)
    assert rec["undoable"] is False


def test_the_failsafe_steers_nothing_and_is_skipped():
    rec = ghb.build_record(
        [{"domain": "keba", "service": "set_failsafe", "data": {}, "prior": None},
         {"domain": "switch", "service": "turn_off",
          "data": {"entity_id": "switch.x"}, "prior": "on"}],
        now=T0, reason="r", draw_w=10400, phases=3, voltage=230, min_current_a=6)
    assert rec["undoable"] is True and len(rec["restores"]) == 1
    assert rec["draw_a"] == pytest.approx(15.07, abs=0.01)


def test_a_stop_that_changed_nothing_leaves_no_record():
    assert ghb.build_record(
        [{"domain": "switch", "service": "turn_off",
          "data": {"entity_id": "switch.x"}, "prior": "off"}],
        now=T0, reason="r", draw_w=0, phases=3, voltage=230,
        min_current_a=6) is None


# ── when the guard lets it back ──────────────────────────────────────────

def test_not_while_the_guard_recovers():
    ok, why = ghb.guard_allows(RECOVERY, 6.0)
    assert ok is False and why == "enforcing_recovery"


def test_not_while_a_phase_lacks_room_for_the_draw():
    ok, why = ghb.guard_allows(ARMED_TIGHT, 13.9)
    assert ok is False and why.startswith("l1")


def test_armed_with_room_for_draw_plus_margin():
    assert ghb.guard_allows(ARMED_ROOMY, 13.9)[0] is True


def test_an_enforcing_guard_without_a_full_reading_blocks():
    ok, why = ghb.guard_allows({"mode": "enforcing_armed", "grid": {}}, 6.0)
    assert ok is False


def test_a_guard_that_is_off_does_not_block():
    assert ghb.guard_allows({"mode": "disabled"}, 6.0)[0] is True


# ── the send seam ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_seam_records_the_stop_and_its_prior_state():
    coord, states, hass = _two_chargers()
    assert await _guard_stop(coord, LINKS, 10400, T0) is True
    assert states.values[SW[LINKS]] == "off"
    rec = coord._guard_stops[LINKS]
    assert rec["restores"][0]["service"] == "turn_on"
    assert coord._ev_devices[LINKS].take_owed() == []


@pytest.mark.asyncio
async def test_a_normal_yielded_write_still_stays_withheld():
    coord, states, hass = _two_chargers()
    dev = coord._ev_devices[LINKS]
    dev.external_yield = True
    assert await dev.send("switch", "turn_on", {"entity_id": SW[LINKS]}) is False
    assert hass.calls == []


# ── the reporter's night ─────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_the_night_of_23_to_24_november():
    coord, states, hass = _two_chargers()
    # 16:43: Rechts (Mini) at 6.7 kW, Links (Audi) at 10.3 kW; the guard
    # stops both.
    await _guard_stop(coord, RECHTS, 6700, T0)
    await _guard_stop(coord, LINKS, 10300, T0 + 60)
    hass.calls.clear()
    assert states.values == {SW[LINKS]: "off", SW[RECHTS]: "off"}
    assert ghb.effective_state(coord, LINKS, ChargingState.NIGHT_CHARGING_ACTIVE) \
        == ChargingState.PHASE_GUARD_STOPPED
    assert ghb.fleet_state(coord, ChargingState.NIGHT_CHARGING_ACTIVE) \
        == ChargingState.PHASE_GUARD_STOPPED

    # 16:45: recovery hold — nothing.
    await _tick(coord, T0 + 180, RECOVERY)
    # 16:48: armed, but the evening load leaves too little room on L1/L3.
    await _tick(coord, T0 + 300, ARMED_TIGHT)
    assert hass.calls == []

    # 20:15: HA restarts — the records survive in the store.
    blob = ghb.to_store(coord)
    fresh = _coord(hass, coord._ev_devices)
    ghb.from_store(fresh, blob)
    for cid in (LINKS, RECHTS):
        ghb.note_facts(fresh, cid, _power(0.0), yielded=True)
    coord = fresh

    # 21:30: room on every phase — Links first (priority 1), alone.
    await _tick(coord, T0 + 5 * 3600, ARMED_ROOMY)
    assert hass.calls == [("switch", "turn_on", SW[LINKS])]
    assert states.values[SW[LINKS]] == "on"
    assert ghb.effective_state(coord, LINKS, "x") == "x"

    # 60 s later: Rechts waits — the meter does not show Links' draw yet,
    # so Links' expected current is held for it on every phase (review F5).
    await _tick(coord, T0 + 5 * 3600 + 60, ARMED_ROOMY)
    assert hass.calls == [("switch", "turn_on", SW[LINKS])]
    assert "free <" in coord._guard_hand_back_why[RECHTS]
    # 2.5 minutes on: still no draw from Links — Rechts still waits.
    await _tick(coord, T0 + 5 * 3600 + 150, ARMED_ROOMY)
    assert hass.calls == [("switch", "turn_on", SW[LINKS])]

    # The Audi draws; the meter still has room for the Mini: Rechts comes back.
    coord._hand_back_facts[LINKS]["drawing"] = True
    await _tick(coord, T0 + 5 * 3600 + 180, ARMED_ROOMY)
    assert hass.calls[-1] == ("switch", "turn_on", SW[RECHTS])

    # After the watch window both records are gone; no repeat sends.
    await _tick(coord, T0 + 6 * 3600, ARMED_ROOMY)
    assert coord._guard_stops == {}
    assert len(hass.calls) == 2


@pytest.mark.asyncio
async def test_an_overload_that_comes_back_backs_off_and_then_gives_up():
    coord, states, hass = _two_chargers()
    now = T0
    await _guard_stop(coord, LINKS, 10300, now)
    created = []
    with patch("homeassistant.helpers.issue_registry.async_create_issue",
               side_effect=lambda *a, **k: created.append(k.get("issue_id"))):
        waits = []
        for attempt in range(ghb.MAX_FAILURES):
            now += 3600
            await _tick(coord, now, ARMED_ROOMY)
            assert states.values[SW[LINKS]] == "on", attempt
            # the car pulls the phase over again within minutes
            now += 120
            await _guard_stop(coord, LINKS, 10300, now)
            rec = coord._guard_stops[LINKS]
            assert rec["failures"] == attempt + 1
            if attempt + 1 < ghb.MAX_FAILURES:
                waits.append(rec["next_try_at"] - now)
                hass.calls.clear()
                await _tick(coord, now + waits[-1] - 1, ARMED_ROOMY)
                assert hass.calls == []          # still backing off
        assert waits == [600, 1200, 2400]     # 10, 20, 40 min, then a Repair
        assert coord._guard_stops[LINKS]["left_off"] is True
        hass.calls.clear()
        await _tick(coord, now + 86400, ARMED_ROOMY)
        assert hass.calls == []                  # SEM no longer tries
    assert created == [f"guard_left_off_{LINKS}"]


@pytest.mark.asyncio
async def test_the_other_party_restarts_it_itself():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    hass.calls.clear()
    states.values[SW[LINKS]] = "on"      # the other party switched it on
    await _tick(coord, T0 + 3600, ARMED_ROOMY)
    assert hass.calls == []
    assert LINKS not in coord._guard_stops


@pytest.mark.asyncio
async def test_an_unplugged_car_ends_the_record():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    hass.calls.clear()
    coord._hand_back_facts[LINKS]["car_absent"] = True
    coord._phase_guard_snapshot = ARMED_ROOMY
    await ghb.run_step(coord, now=T0 + 3600)
    assert hass.calls == [] and LINKS not in coord._guard_stops


@pytest.mark.asyncio
async def test_sem_steering_it_again_ends_the_record():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    hass.calls.clear()
    await _tick(coord, T0 + 3600, ARMED_ROOMY, yielded=False)
    assert hass.calls == [] and LINKS not in coord._guard_stops


@pytest.mark.asyncio
async def test_a_charger_sem_controls_gets_no_record():
    coord, states, hass = _two_chargers()
    dev = coord._ev_devices[LINKS]
    # not yielded: the stop goes through the reconciler as always
    await dev.send("switch", "turn_off", {"entity_id": SW[LINKS]})
    assert ghb.note_guard_stop(coord, LINKS, _adapter(dev), _power(10300),
                               "r", now=T0) is False
    assert getattr(coord, "_guard_stops", {}) == {}


@pytest.mark.asyncio
async def test_observer_mode_withholds_the_hand_back_and_shows_it():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    hass.calls.clear()
    coord._observer_mode = True
    coord._ev_devices[LINKS].observer_mode = True
    coord._ev_devices[LINKS].external_yield = True
    await _tick(coord, T0 + 3600, ARMED_ROOMY)
    assert hass.calls == []
    withheld = coord._ev_devices[LINKS].withheld_commands
    assert withheld[-1]["service"] == "switch.turn_on"
    # shown again at most every 10 minutes, and the record stays
    await _tick(coord, T0 + 3600 + 60, ARMED_ROOMY)
    assert len(coord._ev_devices[LINKS].withheld_commands) == 1
    assert LINKS in coord._guard_stops


@pytest.mark.asyncio
async def test_a_removed_charger_ends_its_record():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    hass.calls.clear()
    del coord._ev_devices[LINKS]
    await _tick(coord, T0 + 3600, ARMED_ROOMY)
    assert hass.calls == [] and LINKS not in coord._guard_stops


def test_the_state_has_a_text():
    assert "phase guard" in get_status_message(ChargingState.PHASE_GUARD_STOPPED)


@pytest.mark.asyncio
async def test_a_drawing_charger_keeps_the_fleet_text():
    coord, states, hass = _two_chargers()
    await _guard_stop(coord, LINKS, 10300, T0)
    coord._hand_back_facts[RECHTS] = {"drawing": True}
    assert ghb.fleet_state(coord, "night_charging_active") == "night_charging_active"


def test_the_coordinator_wires_every_step():
    """Both charger paths record the stop and run the hand-back through the
    owner; the state, the fleet text, the store and the restore all call in.
    Read from the syntax tree: calls, not spelling."""
    import ast
    import pathlib
    tree = ast.parse((pathlib.Path(__file__).resolve().parent.parent
                      / "coordinator" / "coordinator.py").read_text())
    names = [n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert names.count("after_charger_cycle") == 2
    assert names.count("fleet_step") == 2
    for fn in ("effective_state", "fleet_state", "to_store", "from_store"):
        assert fn in names, fn
