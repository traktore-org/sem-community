"""#1178 — two batteries on one discharge limit entity undid each other.

Two batteries behind one inverter often share its one discharge limit. SEM
decides each battery on its own, and each adapter kept its own record of the
limit it wrote. Battery A held 0 W (it may not feed the car); battery B was
NORMAL in the same cycle and wrote the max into the same entity. A's record
still said 0 W, so A never wrote again: the pack fed the car, and the
discharge limit sensor showed 0 W.

Pinned here through the real ``_run_battery_pipeline`` and real adapters on
one fake HA:

* the hold stays, in either fleet order, with one write and no false
  "not kept" verdict; the sensor shows what the entity holds;
* the lowest limit wins; a sale lifts it (#533) and the hold comes back on
  the first cycle after the sale; Off beside a hold hands nothing back;
* batteries on their own entities each write their own (the twin);
  observer writes nothing; the mark is gone after the cycle, so the unload
  hand-back still writes;
* the rule alone, and two structural checks: every adapter method that
  writes the limit entity asks ``_limit_not_mine`` first, and the pipeline
  sends its commands through the one-writer dispatch.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    active_discharge_limit,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    async_release_batteries_on_unload,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.goodwe import (
    GoodWeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_shared_limit import (
    shared_groups,
    wish_of,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)

ROOT = Path(__file__).resolve().parents[1]
LIMIT = "number.battery_max_discharge"
STRATEGY = "select.battery_2_strategy"
LIMIT2 = "number.battery_2_max_discharge"
SETPOINT = "number.battery_2_sale_power"
MAX_W = 5000.0


class _Hass:
    """Numbers that take what is written to them; every call is kept."""

    def __init__(self, deaf=()):
        self.calls: list = []
        self.deaf = set(deaf)
        self._states = {e: self._num(MAX_W if e != SETPOINT else 0.0)
                        for e in (LIMIT, LIMIT2, SETPOINT)}
        # never switches: a sale behind it waits for ever (#978)
        self._states[STRATEGY] = SimpleNamespace(
            state="nom", attributes={"options": ["nom", "api"]})
        self.states = SimpleNamespace(get=self._states.get,
                                      async_all=lambda *a, **k: [])
        self.services = SimpleNamespace(async_call=self._call)

    @staticmethod
    def _num(w):
        return SimpleNamespace(state=str(w), attributes={
            "unit_of_measurement": "W", "min": 0, "max": MAX_W})

    async def _call(self, domain, service, data=None, **kw):
        data = dict(data or {})
        self.calls.append((domain, service, data))
        ent = data.get("entity_id")
        if service == "set_value" and ent in self._states and ent not in self.deaf:
            self._states[ent] = self._num(float(data["value"]))

    def value(self, ent) -> float:
        return float(self._states[ent].state)

    def writes_to(self, ent) -> list:
        return [c[2]["value"] for c in self.calls
                if c[1] == "set_value" and c[2].get("entity_id") == ent]


def _battery(hass, entity=LIMIT, *, sells=False):
    cfg = {"battery_discharge_control_entity": entity,
           "battery_max_discharge_power": MAX_W}
    if sells:
        cfg["battery_force_discharge_control_entity"] = SETPOINT
    return GenericBatteryAdapter(hass, cfg)


def _stub(hass, adapters, *, observer=False):
    """The coordinator around the pipeline. Only the battery loop is real."""
    stub = MagicMock()
    stub.hass = hass
    stub.setup_presence = {m: Presence.PRESENT for m in Module}
    stub._observer_mode = observer
    stub._battery_charge_scheduler.enabled = False
    stub.config = {}
    stub._vpp_apply_battery_override = lambda pbc: {}
    stub._battery_adapters = dict(adapters)
    stub._last_battery_decisions = {}
    stub._apply_export_decision = AsyncMock()
    stub._finish_manual_battery_modes = lambda *a, **k: None
    stub._arbitrage_enabled = lambda n: False
    stub._energy_plan_actuation = False
    stub._cycle_fleet_state = None
    stub.external_yielding = lambda key: False
    return stub


def _power(ids, degraded=False):
    return SimpleNamespace(
        inputs_degraded=degraded,
        batteries={b: BatteryPower(battery_id=b, power_w=0.0, soc_pct=60.0,
                                   power_read=True) for b in ids},
        battery_soc=60.0, battery_power=0.0, battery_soc_known=True,
        battery_soc_unavailable=False, battery_power_unavailable=False,
        battery_power_read=True)


def _hold(bid, w=0.0):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.LIMIT_DISCHARGE,
                           discharge_limit_w=w, reason="may not feed the car")


def _normal(bid):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.NORMAL,
                           reason="default discharge")


def _sale(bid):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.FORCE_DISCHARGE,
                           discharge_power_w=3000.0, floor_soc=20.0,
                           reason="manual sell")


def _off(bid):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.OFF, reason="off")


def _charge(bid):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=100.0, charge_power_w=3000.0,
                           duration_min=60, reason="charge")


async def _cycle(monkeypatch, stub, wants: dict, *, degraded=False):
    """One cycle of the real pipeline; ``wants`` is each battery's decision,
    in fleet order."""
    from custom_components.solar_energy_management.coordinator import (
        decide_battery as db,
    )
    asked = []

    def _decide(view):
        bid = view.runtime.battery_id
        asked.append(bid)
        return wants[bid]

    monkeypatch.setattr(db, "decide_battery", _decide)
    await SEMCoordinator._run_battery_pipeline(
        stub, _power(list(wants), degraded), SimpleNamespace(), "idle")
    assert asked == list(wants), "the pipeline decided every battery"


def _sensor(stub):
    return active_discharge_limit(stub._battery_adapters)


# ─────────────────────────────────────────────────────────────────
# 1. The reported case: a hold beside NORMAL on one entity
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAHoldBesideNormalStays:
    @pytest.mark.parametrize("order", [("b1", "b2"), ("b2", "b1")])
    async def test_the_hold_stays_in_either_order(self, monkeypatch, order):
        hass = _Hass()
        ads = {b: _battery(hass) for b in order}
        stub = _stub(hass, ads)
        for _ in range(3):
            await _cycle(monkeypatch, stub, {
                order[0]: _hold(order[0]) if order[0] == "b1" else _normal(order[0]),
                order[1]: _hold(order[1]) if order[1] == "b1" else _normal(order[1]),
            })
            assert hass.value(LIMIT) == 0.0, "the sibling's NORMAL wrote the max"
            assert _sensor(stub) == 0.0
        assert hass.writes_to(LIMIT) == [0.0], "one write, no fight"
        assert ads["b1"].last_discharge_limit_w == 0.0
        assert ads["b2"].last_discharge_limit_w == 0.0, "b2's record is the entity's"
        assert stub._last_battery_decisions["b2"]["limit_written_by"] == "b1"
        assert "limit_written_by" not in stub._last_battery_decisions["b1"]

    async def test_the_kept_hold_is_judged_kept(self, monkeypatch):
        """#915: before, b1's 0 W read back as b2's max — a false 'not kept'
        strike every cycle on a working entity."""
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        t = [1000.0]
        with patch("time.monotonic", side_effect=lambda: t[0]):
            for _ in range(4):
                await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
                t[0] += 10.0
                for ad in (b1, b2):
                    ad.verify_pending_write()
        assert b1.last_verified_entity == LIMIT, "the write was judged"
        assert b1.write_not_taken_strikes == 0
        assert b2.write_not_taken_strikes == 0

    async def test_a_write_the_next_writer_replaced_is_not_judged(self, monkeypatch):
        """b1's 0 W is still waiting to be judged when b2's sale lifts the
        limit: the entity now holds b2's value, so b1 is not told its write
        was not kept."""
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass, sells=True)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        t = [1000.0]
        with patch("time.monotonic", side_effect=lambda: t[0]):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
            t[0] += 2.0                                 # inside the grace
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _sale("b2")})
            t[0] += 10.0
            assert b1.verify_pending_write() is None, "b1 has nothing to judge"
            assert b2.verify_pending_write() is True
        assert b1.write_not_taken_strikes == 0

    async def test_a_write_still_held_is_judged_by_its_next_writer(self, monkeypatch):
        """The writer moves from b1 to b2 and the value stays, so b2 sends
        nothing: b1's unjudged write is b2's to judge. On an entity that
        keeps nothing, that is how the miss is still seen (#915, #1138)."""
        hass = _Hass(deaf={LIMIT})
        b1, b2 = _battery(hass), _battery(hass)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        t = [1000.0]
        with patch("time.monotonic", side_effect=lambda: t[0]):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
            t[0] += 2.0
            await _cycle(monkeypatch, stub, {"b1": _hold("b1", 300.0),
                                             "b2": _hold("b2", 0.0)})
            assert hass.writes_to(LIMIT) == [0.0], "b2 holds the same value"
            t[0] += 10.0
            assert b1.verify_pending_write() is None
            assert b2.verify_pending_write() is False, "the miss is seen"
        assert b2.write_not_taken_strikes == 1
        await _cycle(monkeypatch, stub, {"b1": _hold("b1", 300.0),
                                         "b2": _hold("b2", 0.0)})
        assert hass.writes_to(LIMIT) == [0.0, 0.0], "sent once more (#1138)"

    async def test_the_hold_ends_when_its_battery_lets_go(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")})
        assert hass.value(LIMIT) == MAX_W
        assert hass.writes_to(LIMIT) == [0.0, MAX_W]
        assert _sensor(stub) is None


# ─────────────────────────────────────────────────────────────────
# 2. Which battery writes
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestWhichBatteryWrites:
    async def test_the_lowest_limit_wins_and_the_next_lands_at_once(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1", 1000.0),
                                             "b2": _hold("b2", 0.0)})
            assert hass.value(LIMIT) == 0.0
        await _cycle(monkeypatch, stub, {"b1": _hold("b1", 1000.0),
                                         "b2": _normal("b2")})
        assert hass.value(LIMIT) == 1000.0, "b1's own limit lands on the first cycle"
        assert hass.writes_to(LIMIT) == [0.0, 1000.0]

    async def test_a_sale_lifts_the_hold_and_the_hold_comes_back_at_once(
            self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass, sells=True)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        assert hass.value(LIMIT) == 0.0
        for _ in range(3):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _sale("b2")})
            assert hass.value(LIMIT) == MAX_W, "a sale beats the car limit (#533)"
            assert _sensor(stub) is None, "no limit in force while it sells"
        assert hass.value(SETPOINT) == 3000.0, "the sale went out"
        assert hass.writes_to(LIMIT) == [0.0, MAX_W], "lifted once"
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        assert hass.value(LIMIT) == 0.0, "no 6-cycle dwell after the sale"
        assert _sensor(stub) == 0.0

    async def test_off_beside_a_hold_hands_nothing_back(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _off("b2")})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _off("b2")})
        assert hass.writes_to(LIMIT) == [0.0]
        assert stub._battery_adapters["b2"].last_intent is BatteryIntent.OFF

    async def test_a_charge_beside_a_hold(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _charge("b1"), "b2": _hold("b2")})
        assert hass.writes_to(LIMIT) == [0.0]


# ─────────────────────────────────────────────────────────────────
# 3. What stays as it was
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestWhatStays:
    async def test_own_entities_each_write_their_own(self, monkeypatch):
        """The twin: nothing is shared, so nothing is held back."""
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass, LIMIT), "b2": _battery(hass, LIMIT2)})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1", 0.0),
                                         "b2": _hold("b2", 1000.0)})
        assert (hass.value(LIMIT), hass.value(LIMIT2)) == (0.0, 1000.0)
        assert "limit_written_by" not in stub._last_battery_decisions["b2"]

    async def test_observer_writes_nothing(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)}, observer=True)
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        assert hass.calls == []

    async def test_the_mark_is_gone_after_the_cycle(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        assert b1._limit_writer is None and b2._limit_writer is None
        stub._observer_mode = False
        await async_release_batteries_on_unload(stub)
        assert hass.value(LIMIT) == MAX_W, "the unload hand-back still writes"

    async def test_a_shared_limit_is_no_longer_called_a_fight(self, caplog):
        """The setup warning said two batteries on one entity "will fight".
        For the discharge limit that is no longer true, nor for the sale
        power (#1182); for a strategy select it still is."""
        stub = MagicMock()
        stub._battery_control_entity_owner = None
        for bid in ("b1", "b2"):
            SEMCoordinator._warn_battery_entity_collision(stub, bid, {
                "battery_discharge_control_entity": LIMIT,
                "battery_force_discharge_control_entity": SETPOINT,
                "battery_strategy_control_entity": STRATEGY})
        fights = [r.getMessage() for r in caplog.records
                  if "collision" in r.getMessage()]
        assert len(fights) == 1 and STRATEGY in fights[0]

    async def test_an_unload_during_a_cycle_still_hands_back(self):
        """A cycle still running has b2 marked; the unload's hand-back is
        b2's own and goes out."""
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass)
        await hass._call("number", "set_value", {"entity_id": LIMIT, "value": 0.0})
        b2._last_discharge_limit_w = 0.0
        b2._limit_writer = "b1"
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await async_release_batteries_on_unload(stub)
        assert hass.value(LIMIT) == MAX_W

    async def test_a_command_that_fails_still_clears_the_mark(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        b1.command_limit_discharge = AsyncMock(side_effect=RuntimeError("modbus"))
        with pytest.raises(RuntimeError):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
        assert b2._limit_writer is None


# ─────────────────────────────────────────────────────────────────
# 3b. A battery counts by what its command will really write
# ─────────────────────────────────────────────────────────────────

def _huawei(hass, *, id_in_config=True):
    """``id_in_config=False`` is production's shape: the device id is found
    by the battery adapter and never reaches its charge adapter's config."""
    cfg = {"battery_discharge_control_entity": LIMIT,
           "battery_max_discharge_power": MAX_W}
    if id_in_config:
        cfg["inverter_device_id"] = "luna"
    a = HuaweiBatteryAdapter(hass, cfg)
    a._inverter_device_id = "luna"
    a._startup_orphan_checked = True
    return a


def _calls_of(hass, start):
    return hass.calls[start:]


@pytest.mark.asyncio
class TestWhatTheCommandWillWrite:
    @pytest.mark.parametrize("why", ["no sale entity", "sale withdrawn",
                                     "strategy never switches"])
    async def test_a_sale_that_cannot_go_out_leaves_the_hold(self, monkeypatch, why):
        hass = _Hass()
        b1 = _battery(hass)
        if why == "no sale entity":
            b2 = _battery(hass)
        elif why == "sale withdrawn":
            b2 = _battery(hass, sells=True)
            b2._force_discharge_failures = b2.FORCE_DISCHARGE_FAILURE_LIMIT
        else:
            b2 = GenericBatteryAdapter(hass, {
                "battery_discharge_control_entity": LIMIT,
                "battery_force_discharge_control_entity": SETPOINT,
                "battery_strategy_control_entity": STRATEGY,
                "battery_strategy_active_value": "api",
                "battery_max_discharge_power": MAX_W})
        stub = _stub(hass, {"b1": b1, "b2": b2})
        for _ in range(3):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _sale("b2")})
            assert hass.value(LIMIT) == 0.0, "the hold lands"
            assert _sensor(stub) == 0.0
        assert hass.writes_to(LIMIT) == [0.0]
        assert hass.value(SETPOINT) == 0.0, "nothing was sold"

    async def test_two_offs_hand_the_limit_back(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)})
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _hold("b2")})
        await _cycle(monkeypatch, stub, {"b1": _off("b1"), "b2": _hold("b2")})
        assert hass.value(LIMIT) == 0.0, "b2 still holds"
        await _cycle(monkeypatch, stub, {"b1": _off("b1"), "b2": _off("b2")})
        assert hass.value(LIMIT) == MAX_W, "hands-off leaves no limit of SEM's"
        assert hass.writes_to(LIMIT) == [0.0, MAX_W]

    async def test_a_missed_hold_is_sent_again_by_the_next_writer(self, monkeypatch):
        """#1138: b1's 0 W was not kept and owes one more send. The hold
        moves to b2 with the same value, so b2 sends it."""
        hass = _Hass(deaf={LIMIT})
        b1, b2 = _battery(hass), _battery(hass)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        t = [1000.0]
        with patch("time.monotonic", side_effect=lambda: t[0]):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _normal("b2")})
            t[0] += 10.0
            assert b1.verify_pending_write() is False
            assert b1._limit_resend_due is True
            await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _hold("b2")})
        assert hass.writes_to(LIMIT) == [0.0, 0.0], "sent once more"

    async def test_a_blind_cycle_moves_nothing(self, monkeypatch):
        """#818: b2's hold may not flip to NORMAL on a cycle that cannot
        see, and b1's NORMAL may not write the max past it."""
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass), "b2": _battery(hass)})
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _hold("b2")})
        assert hass.value(LIMIT) == 0.0
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")},
                     degraded=True)
        assert hass.writes_to(LIMIT) == [0.0], "no flip on a blind cycle"
        assert _sensor(stub) == 0.0
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")})
        assert hass.writes_to(LIMIT) == [0.0, MAX_W], "it lets go once it can see"

    @pytest.mark.parametrize("order", [("b1", "b2"), ("b2", "b1")])
    async def test_no_limit_write_right_after_a_stop(self, monkeypatch, order):
        """Two packs on one inverter. b2's sale ends: its stop goes out,
        and b1's hold is not written in the same cycle — the inverter
        takes one write per cycle after a stop."""
        hass = _Hass()
        ads = {"b1": _huawei(hass), "b2": _huawei(hass)}
        stub = _stub(hass, {b: ads[b] for b in order})

        def _wants(b2_sells):
            w = {"b1": _hold("b1"), "b2": _sale("b2") if b2_sells else _normal("b2")}
            return {b: w[b] for b in order}

        for _ in range(2):              # the hold stands before the sale
            await _cycle(monkeypatch, stub, _wants(False))
        assert hass.value(LIMIT) == 0.0
        for _ in range(3):
            await _cycle(monkeypatch, stub, _wants(True))
        assert hass.value(LIMIT) == MAX_W, "the sale lifted it"
        assert ads["b2"]._forcible_discharging is True
        landed = None
        for i in range(6):
            start = len(hass.calls)
            await _cycle(monkeypatch, stub, _wants(False))
            calls = _calls_of(hass, start)
            stops = [c for c in calls if c[1] == "stop_forcible_charge"]
            limits = [c for c in calls if c[2].get("entity_id") == LIMIT]
            assert not (stops and limits), f"cycle {i}: a write right after a stop"
            if limits and landed is None:
                landed = i
        assert landed is not None and landed <= 3, \
            "the hold lands once it is quiet, with no dwell after it"
        assert hass.value(LIMIT) == 0.0

    async def test_a_charge_stop_that_sends_nothing_leaves_no_quiet_cycle(
            self, monkeypatch):
        """The charge adapter has no device id of its own, so its stop
        sends nothing: the hold beside it lands that cycle."""
        hass = _Hass()
        b1, b2 = _huawei(hass), _huawei(hass, id_in_config=False)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        stop = BatteryDecision(battery_id="b2",
                               intent=BatteryIntent.STOP_FORCE_CHARGE, reason="stop")
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": stop})
        assert [c for c in hass.calls if c[1] == "stop_forcible_charge"] == []
        assert hass.value(LIMIT) == 0.0

    async def test_a_sale_that_stops_going_out_gives_the_hold_back(self, monkeypatch):
        """b2 sold, then its sale was withdrawn after refusals (#840). Its
        last command still reads as a sale; the hold must land anyway."""
        hass = _Hass()
        b1, b2 = _battery(hass), _battery(hass, sells=True)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _sale("b2")})
        assert hass.value(SETPOINT) == 3000.0 and hass.value(LIMIT) == MAX_W
        b2._force_discharge_failures = b2.FORCE_DISCHARGE_FAILURE_LIMIT
        await _cycle(monkeypatch, stub, {"b1": _hold("b1"), "b2": _sale("b2")})
        assert b2.last_intent is BatteryIntent.FORCE_DISCHARGE, "the stale intent"
        assert hass.value(LIMIT) == 0.0, "the hold lands"


# ─────────────────────────────────────────────────────────────────
# 4. The rule alone
# ─────────────────────────────────────────────────────────────────

def limit_writers(rows) -> dict:
    """``{battery_id: writer_id}`` for every battery another one writes for,
    as ``actuate_batteries`` reads ``shared_groups``."""
    return {bid: ranked[0] for members, ranked in shared_groups(rows)
            for bid in members if ranked and bid != ranked[0]}


class TestTheRule:
    def _rows(self, *pairs, entity=LIMIT):
        return [(d.battery_id, entity, wish_of(d)) for d in pairs]

    def test_alone_on_an_entity_writes_its_own(self):
        assert limit_writers(self._rows(_hold("b1"))) == {}
        assert limit_writers([("b1", LIMIT, wish_of(_hold("b1"))),
                              ("b2", LIMIT2, wish_of(_normal("b2")))]) == {}

    def test_no_entity_is_not_shared(self):
        assert limit_writers(self._rows(_hold("b1"), _normal("b2"), entity="")) == {}

    def test_a_sale_beats_a_limit(self):
        assert limit_writers(self._rows(_hold("b1"), _sale("b2"))) == {"b1": "b2"}

    def test_the_lowest_limit_beats_normal(self):
        rows = self._rows(_normal("b1"), _hold("b2", 800.0), _hold("b3", 300.0))
        assert limit_writers(rows) == {"b1": "b3", "b2": "b3"}

    def test_normal_beats_off_and_a_tie_goes_to_fleet_order(self):
        assert limit_writers(self._rows(_off("b1"), _normal("b2"))) == {"b1": "b2"}
        assert limit_writers(self._rows(_hold("b1"), _hold("b2"))) == {"b2": "b1"}

    def test_a_charge_never_writes_for_the_others(self):
        assert limit_writers(self._rows(_charge("b1"), _normal("b2"))) == {"b1": "b2"}
        assert limit_writers(self._rows(_charge("b1"), _charge("b2"))) == {}


# ─────────────────────────────────────────────────────────────────
# 5. Every brand asks; the pipeline uses the one-writer dispatch
# ─────────────────────────────────────────────────────────────────

_WRITERS = {"async_write_power_setpoint", "async_write_power_setpoint_verbose",
            "async_call"}


def _writes_limit_entity(fn: ast.AST) -> bool:
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        name = getattr(node.func, "attr", None) or getattr(node.func, "id", None)
        if name not in _WRITERS:
            continue
        for arg in ast.walk(node):
            if (isinstance(arg, ast.Attribute)
                    and arg.attr == "_discharge_control_entity"):
                return True
    return False


def _asks(fn: ast.AST) -> bool:
    return any(isinstance(n, ast.Call)
               and getattr(n.func, "attr", None) == "_limit_not_mine"
               for n in ast.walk(fn))


def _unguarded(tree: ast.AST) -> list:
    return [fn.name for fn in ast.walk(tree)
            if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
            and _writes_limit_entity(fn) and not _asks(fn)]


class TestEveryWriterAsks:
    def test_every_adapter_method_that_writes_the_limit_asks_first(self):
        found = 0
        for path in sorted((ROOT / "coordinator" / "battery_adapters").glob("*.py")):
            tree = ast.parse(path.read_text())
            found += sum(1 for fn in ast.walk(tree)
                         if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef))
                         and _writes_limit_entity(fn))
            assert _unguarded(tree) == [], f"{path.name} writes the limit unasked"
        assert found >= 3, "generic, GoodWe and Huawei each write the limit"

    def test_the_check_bites(self):
        tree = ast.parse(textwrap.dedent("""
            async def _apply_discharge_limit(self, watts):
                await async_write_power_setpoint(
                    self._hass, self._discharge_control_entity, watts)
        """))
        assert _unguarded(tree) == ["_apply_discharge_limit"]

    @pytest.mark.parametrize("cls", [GenericBatteryAdapter, GoodWeBatteryAdapter,
                                     HuaweiBatteryAdapter])
    def test_each_brand_sends_nothing_while_another_writes(self, cls):
        import asyncio
        hass = _Hass()
        a = cls(hass, {"battery_discharge_control_entity": LIMIT,
                       "battery_max_discharge_power": MAX_W})
        a._limit_writer = "b1"
        asyncio.run(a._apply_discharge_limit(0.0))
        assert hass.writes_to(LIMIT) == []

    def test_the_pipeline_sends_through_the_one_writer_dispatch(self):
        tree = ast.parse((ROOT / "coordinator" / "coordinator.py").read_text())
        fn = next(n for n in ast.walk(tree)
                  if isinstance(n, ast.AsyncFunctionDef)
                  and n.name == "_run_battery_pipeline")
        def _sends(node):
            return any(isinstance(n, ast.Call)
                       and getattr(n.func, "id", None) == "actuate_battery"
                       for n in ast.walk(node))

        senders = {n.name for n in ast.walk(fn)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                   and n is not fn and _sends(n)}
        handed = {a.id for n in ast.walk(fn) if isinstance(n, ast.Call)
                  and getattr(n.func, "id", None) == "actuate_batteries"
                  for a in n.args if isinstance(a, ast.Name)}
        assert senders and senders <= handed, \
            "every battery command goes through actuate_batteries"

        def _outside_senders(node):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if (isinstance(child, ast.Call)
                        and getattr(child.func, "id", None) == "actuate_battery"):
                    yield child
                yield from _outside_senders(child)

        assert list(_outside_senders(fn)) == [], \
            "a command sent past the one-writer rule"
