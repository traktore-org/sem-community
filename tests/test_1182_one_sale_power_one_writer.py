"""#1182 — two batteries on one sale power entity cancelled the sale.

Two batteries can share one sale power entity
(``battery_force_discharge_control_entity``, one register for the whole
inverter). Battery A sold and wrote 3000 W. Battery B was NORMAL in the same
cycle and wrote 0 W into the same entity (every mode zeroes it, #523). A's
own record still said 3000 W, so A never wrote again: A showed a sale while
the entity read 0 W. The sale was also split by the number of discharge
limit entities, so two batteries on one sale entity each got half.

Pinned here through the real ``_run_battery_pipeline`` and real adapters on
one fake HA:

* the sale stays, in either fleet order, with one write; the sibling's
  record is the entity's; the sale ends with one 0 W write;
* a battery that stops beside a seller does not stop the other's sale; two
  sellers write once; a writer whose command writes nothing gives the
  entity to the next battery, so a stop still goes out (#757, #978);
* Huawei on a number: a sibling's stop and its retries leave the sale;
* own entities each write their own (the twin); observer writes nothing;
  the mark is gone after the cycle, after a command that raises, and for an
  unload during a cycle;
* the sale split counts sale surfaces, not limit entities;
* one structural check: only ``_write_force_discharge`` writes the sale
  power entity, so the hold-back there covers every writer.
"""
from __future__ import annotations

import ast
import textwrap
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    async_release_batteries_on_unload,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.deye import (
    DeyeBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.huawei import (
    HuaweiBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_shared_limit import (
    setpoint_entity,
    setpoint_wish_of,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    sale_surface_count,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)

ROOT = Path(__file__).resolve().parents[1]
LIMIT = "number.battery_1_max_discharge"
LIMIT2 = "number.battery_2_max_discharge"
SETPOINT = "number.inverter_sale_power"
SETPOINT2 = "number.battery_2_sale_power"
STRATEGY = "select.battery_1_strategy"
MAX_W = 5000.0


class _Hass:
    """Numbers that take what is written to them; every call is kept."""

    def __init__(self):
        self.calls: list = []
        self._states = {e: self._num(MAX_W) for e in (LIMIT, LIMIT2)}
        for e in (SETPOINT, SETPOINT2):
            self._states[e] = self._num(0.0)
        # never switches: a sale behind it waits for ever (#978)
        self._states[STRATEGY] = SimpleNamespace(
            state="nom", attributes={"options": ["nom", "api"]})
        self.states = SimpleNamespace(get=self._states.get,
                                      async_all=lambda *a, **k: [])
        self.services = SimpleNamespace(async_call=self._call)
        self.data = {}

    @staticmethod
    def _num(w):
        return SimpleNamespace(state=str(w), attributes={
            "unit_of_measurement": "W", "min": -MAX_W, "max": MAX_W})

    async def _call(self, domain, service, data=None, **kw):
        data = dict(data or {})
        self.calls.append((domain, service, data))
        ent = data.get("entity_id")
        if service == "set_value" and ent in self._states:
            self._states[ent] = self._num(float(data["value"]))

    def value(self, ent) -> float:
        return float(self._states[ent].state)

    def writes_to(self, ent) -> list:
        return [c[2]["value"] for c in self.calls
                if c[1] == "set_value" and c[2].get("entity_id") == ent]


def _battery(hass, limit=LIMIT, sale=SETPOINT, **extra):
    cfg = {"battery_discharge_control_entity": limit,
           "battery_force_discharge_control_entity": sale,
           "battery_max_discharge_power": MAX_W,
           "battery_max_charge_power": MAX_W, **extra}
    return GenericBatteryAdapter(hass, cfg)


def _huawei(hass, limit):
    """Huawei with the sale power on a number (no device id)."""
    a = HuaweiBatteryAdapter(hass, {
        "battery_discharge_control_entity": limit,
        "battery_force_discharge_control_entity": SETPOINT,
        "battery_max_discharge_power": MAX_W})
    a._inverter_device_id = ""
    a._startup_orphan_checked = True
    return a


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


def _power(ids):
    return SimpleNamespace(
        inputs_degraded=False,
        batteries={b: BatteryPower(battery_id=b, power_w=0.0, soc_pct=60.0,
                                   power_read=True) for b in ids},
        battery_soc=60.0, battery_power=0.0, battery_soc_known=True,
        battery_soc_unavailable=False, battery_power_unavailable=False,
        battery_power_read=True)


def _d(bid, intent, **kw):
    return BatteryDecision(battery_id=bid, intent=intent, reason="test", **kw)


def _sale(bid, w=3000.0):
    return _d(bid, BatteryIntent.FORCE_DISCHARGE, discharge_power_w=w,
              floor_soc=20.0)


def _normal(bid):
    return _d(bid, BatteryIntent.NORMAL)


def _stop_sale(bid):
    return _d(bid, BatteryIntent.STOP_FORCE_DISCHARGE)


def _stop_charge(bid):
    return _d(bid, BatteryIntent.STOP_FORCE_CHARGE)


def _charge(bid):
    return _d(bid, BatteryIntent.FORCE_CHARGE, target_soc=100.0,
              charge_power_w=2000.0, duration_min=60)


async def _cycle(monkeypatch, stub, wants: dict, views=None):
    """One cycle of the real pipeline; ``wants`` is each battery's decision,
    in fleet order."""
    from custom_components.solar_energy_management.coordinator import (
        decide_battery as db,
    )

    def _decide(view):
        if views is not None:
            views.append(view)
        return wants[view.runtime.battery_id]

    monkeypatch.setattr(db, "decide_battery", _decide)
    await SEMCoordinator._run_battery_pipeline(
        stub, _power(list(wants)), SimpleNamespace(), "idle")


# ─────────────────────────────────────────────────────────────────
# 1. The reported case: a sale beside NORMAL on one sale entity
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestASaleBesideNormalStays:
    @pytest.mark.parametrize("order", [("b1", "b2"), ("b2", "b1")])
    async def test_the_sale_stays_in_either_order(self, monkeypatch, order):
        hass = _Hass()
        ads = {"b1": _battery(hass, LIMIT), "b2": _battery(hass, LIMIT2)}
        stub = _stub(hass, {b: ads[b] for b in order})
        for _ in range(3):
            await _cycle(monkeypatch, stub, {
                b: _sale(b) if b == "b1" else _normal(b) for b in order})
            assert hass.value(SETPOINT) == 3000.0, "the sibling's 0 W cancelled the sale"
        assert hass.writes_to(SETPOINT) == [3000.0], "one write, no fight"
        assert ads["b2"]._last_force_discharge_w == 3000.0, "b2's record is the entity's"
        assert ads["b1"]._sale_sent is True
        assert stub._last_battery_decisions["b2"]["sale_power_written_by"] == "b1"
        assert "sale_power_written_by" not in stub._last_battery_decisions["b1"]

    async def test_the_sale_ends_with_one_zero(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass, LIMIT), "b2": _battery(hass, LIMIT2)})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")})
        assert hass.value(SETPOINT) == 0.0
        assert hass.writes_to(SETPOINT) == [3000.0, 0.0]

    async def test_a_new_sale_power_goes_out(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass, LIMIT), "b2": _battery(hass, LIMIT2)})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1", 1500.0), "b2": _normal("b2")})
        assert hass.value(SETPOINT) == 1500.0
        assert hass.writes_to(SETPOINT) == [3000.0, 1500.0]


# ─────────────────────────────────────────────────────────────────
# 2. Which battery writes
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestWhichBatteryWrites:
    async def test_a_stop_beside_a_seller_leaves_its_sale(self, monkeypatch):
        """b1 reached its floor; b2 still sells on the same entity."""
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _sale("b2")})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _stop_sale("b1"), "b2": _sale("b2")})
            assert hass.value(SETPOINT) == 3000.0
        assert hass.writes_to(SETPOINT) == [3000.0]
        assert b1.last_intent is BatteryIntent.STOP_FORCE_DISCHARGE
        assert b2._sale_sent is True

    async def test_two_sellers_write_once(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        for _ in range(2):
            await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _sale("b2")})
        assert hass.writes_to(SETPOINT) == [3000.0]
        assert b1._sale_sent and b2._sale_sent
        assert b1.last_intent is b2.last_intent is BatteryIntent.FORCE_DISCHARGE

    async def test_a_held_sale_did_not_go_out_when_the_writer_failed(
            self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})

        async def _refuse(domain, service, data=None, **kw):
            raise RuntimeError("modbus")
        hass.services.async_call = _refuse
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _sale("b2")})
        assert b1._sale_sent is False
        assert b2._sale_sent is False, "b2's sale rode on b1's write"

    async def test_a_writer_that_writes_nothing_still_lets_the_stop_out(
            self, monkeypatch):
        """b1's charge stop is already stopped (#757) and sends nothing; it
        is first in line. b2 stops its sale: the 0 W must still go out."""
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _stop_charge("b1"), "b2": _sale("b2")})
        assert hass.value(SETPOINT) == 3000.0
        assert b1.last_intent is BatteryIntent.STOP_FORCE_CHARGE
        await _cycle(monkeypatch, stub, {"b1": _stop_charge("b1"), "b2": _stop_sale("b2")})
        assert hass.value(SETPOINT) == 0.0, "the sale was never stopped"
        assert hass.writes_to(SETPOINT) == [3000.0, 0.0]
        assert b1._last_force_discharge_w == 0.0
        assert stub._last_battery_decisions["b1"]["sale_power_written_by"] == "b2"

    async def test_a_refused_writer_still_lets_the_stop_out(self, monkeypatch):
        """Review: b1 is first in line but its writes are refused (#840,
        between probes). b2 ends its sale: its 0 W goes out."""
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _sale("b2")})
        assert hass.value(SETPOINT) == 3000.0
        b1._force_discharge_failures = b1.FORCE_DISCHARGE_FAILURE_LIMIT
        b1._force_discharge_retry_after = float("inf")
        await _cycle(monkeypatch, stub, {"b1": _stop_sale("b1"), "b2": _stop_sale("b2")})
        assert hass.value(SETPOINT) == 0.0, "the sale ran on"
        assert b2.last_intent is BatteryIntent.STOP_FORCE_DISCHARGE
        assert stub._last_battery_decisions["b1"]["sale_power_written_by"] == "b2"

    async def test_the_next_in_line_is_tried_until_one_lands(self, monkeypatch):
        hass = _Hass()
        b1 = _battery(hass, LIMIT, battery_setpoint_bidirectional=True)
        b2, b3 = _battery(hass, LIMIT2), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2, "b3": b3})
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2"),
                                         "b3": _sale("b3")})
        assert hass.value(SETPOINT) == 3000.0
        for ad in (b1, b3):                     # refused, between probes
            ad._force_discharge_failures = ad.FORCE_DISCHARGE_FAILURE_LIMIT
            ad._force_discharge_retry_after = float("inf")
        await _cycle(monkeypatch, stub, {"b1": _charge("b1"), "b2": _normal("b2"),
                                         "b3": _stop_sale("b3")})
        assert hass.value(SETPOINT) == 0.0, "b1 and b3 were refused; b2's 0 W lands"

    async def test_a_sale_waiting_for_its_select_gives_the_entity_on(
            self, monkeypatch):
        """b1's sale waits for a strategy select that never switches (#978):
        it writes nothing, so b2's 0 W goes out and b1 has not sold."""
        hass = _Hass()
        await hass._call("number", "set_value", {"entity_id": SETPOINT, "value": 2000.0})
        b1 = _battery(hass, LIMIT, battery_strategy_control_entity=STRATEGY,
                      battery_strategy_active_value="api")
        b2 = _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        assert hass.value(SETPOINT) == 0.0
        assert b1._sale_sent is False

    async def test_a_sale_beats_a_setpoint_charge(self, monkeypatch):
        hass = _Hass()
        b1 = _battery(hass, LIMIT, battery_setpoint_bidirectional=True)
        b2 = _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _charge("b1"), "b2": _normal("b2")})
        assert hass.value(SETPOINT) == -2000.0, "the charge beats a 0 W"
        await _cycle(monkeypatch, stub, {"b1": _charge("b1"), "b2": _sale("b2")})
        assert hass.value(SETPOINT) == 3000.0
        assert hass.writes_to(SETPOINT) == [-2000.0, 3000.0]


# ─────────────────────────────────────────────────────────────────
# 3. Huawei with the sale power on a number
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestHuaweiOnANumber:
    async def test_a_siblings_stop_and_its_retries_leave_the_sale(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _huawei(hass, LIMIT), _huawei(hass, LIMIT)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _sale("b2")})
        assert hass.value(SETPOINT) == 3000.0
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _stop_sale("b2")})
        assert b2._sent_stop is False, "no stop went out, so no quiet cycle"
        for _ in range(3):                      # the stop's two retries
            await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
            assert hass.value(SETPOINT) == 3000.0
        assert hass.writes_to(SETPOINT) == [3000.0]
        assert b2._forcible_discharging is False

    async def test_the_battery_ending_its_sale_writes_the_stop(
            self, monkeypatch):
        """Review: b1 is first in fleet order but has no sale to end; b2
        does. b2's stop goes out with its own command, so the shared limit's
        writer gets its quiet cycle: no limit write next to the stop
        (#1178). Before, the stop went out late, right after a limit
        write, which the LUNA2000 does not take."""
        hass = _Hass()
        await hass._call("number", "set_value", {"entity_id": LIMIT, "value": 1000.0})
        b1, b2 = _huawei(hass, LIMIT), _huawei(hass, LIMIT)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _sale("b2")})
        assert hass.value(SETPOINT) == 3000.0
        start = len(hass.calls)
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")})
        sent = [c[2]["entity_id"] for c in hass.calls[start:]]
        assert sent == [SETPOINT], "the stop alone: no limit write around it"
        assert hass.value(SETPOINT) == 0.0
        assert stub._last_battery_decisions["b1"]["sale_power_written_by"] == "b2"
        assert b1._last_force_discharge_w == 0.0

    async def test_a_late_stop_is_still_a_stop(self, monkeypatch):
        """b1 owes a stop too but its write is refused; b2's held stop goes
        out after the commands and still counts as a stop."""
        hass = _Hass()
        b1, b2 = _huawei(hass, LIMIT), _huawei(hass, LIMIT)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _sale("b2")})
        b1._force_discharge_failures = b1.FORCE_DISCHARGE_FAILURE_LIMIT
        b1._force_discharge_retry_after = float("inf")
        await _cycle(monkeypatch, stub, {"b1": _stop_sale("b1"), "b2": _stop_sale("b2")})
        assert hass.value(SETPOINT) == 0.0
        assert b2._sent_stop is True, "a stop sent late is still a stop"

def test_a_device_or_a_select_writes_no_sale_number():
    hass = _Hass()
    a = HuaweiBatteryAdapter(hass, {
        "battery_force_discharge_control_entity": SETPOINT,
        "inverter_device_id": "luna"})
    assert setpoint_entity(a) == ""
    assert a.sale_surface() == "huawei_solar device luna"
    assert setpoint_entity(_huawei(hass, LIMIT)) == SETPOINT
    deye = DeyeBatteryAdapter.__new__(DeyeBatteryAdapter)
    deye._force_discharge_entity = SETPOINT
    deye._system_work_mode_entity = "select.work_mode"
    assert setpoint_entity(deye) == ""
    assert deye.sale_surface() == "select.work_mode"


# ─────────────────────────────────────────────────────────────────
# 4. The twin, observer, and the mark
# ─────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestTwinAndMark:
    async def test_own_entities_each_write_their_own(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2, SETPOINT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        assert hass.writes_to(SETPOINT) == [3000.0]
        assert hass.writes_to(SETPOINT2) == [0.0]
        assert "sale_power_written_by" not in stub._last_battery_decisions["b2"]

    async def test_observer_writes_nothing(self, monkeypatch):
        hass = _Hass()
        stub = _stub(hass, {"b1": _battery(hass, LIMIT), "b2": _battery(hass, LIMIT2)},
                     observer=True)
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        assert hass.calls == []

    async def test_the_mark_is_gone_after_the_cycle(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        assert b1._setpoint_writer is None and b2._setpoint_writer is None

    async def test_a_command_that_fails_still_clears_the_mark(self, monkeypatch):
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        stub = _stub(hass, {"b1": b1, "b2": b2})
        b1.command_force_discharge = AsyncMock(side_effect=RuntimeError("modbus"))
        with pytest.raises(RuntimeError):
            await _cycle(monkeypatch, stub, {"b1": _sale("b1"), "b2": _normal("b2")})
        assert b2._setpoint_writer is None

    async def test_an_unload_during_a_cycle_still_zeroes(self):
        hass = _Hass()
        b1, b2 = _battery(hass, LIMIT), _battery(hass, LIMIT2)
        await hass._call("number", "set_value", {"entity_id": SETPOINT, "value": 3000.0})
        b2._last_force_discharge_w = 3000.0
        b2._last_discharge_limit_w = MAX_W
        b2._setpoint_writer = "b1"
        stub = _stub(hass, {"b1": b1, "b2": b2})
        stub._observer_mode = False
        await async_release_batteries_on_unload(stub)
        assert hass.value(SETPOINT) == 0.0


# ─────────────────────────────────────────────────────────────────
# 5. The rule alone
# ─────────────────────────────────────────────────────────────────

class TestTheRule:
    def test_ranks(self):
        hass = _Hass()
        ad = _battery(hass)
        assert setpoint_wish_of(_sale("b1"), ad)[0] == 0
        assert setpoint_wish_of(_normal("b1"), ad)[0] == 2
        assert setpoint_wish_of(_charge("b1"), ad)[0] == 2, "a switch charge writes 0 W"
        bidi = _battery(hass, battery_setpoint_bidirectional=True)
        assert setpoint_wish_of(_charge("b1"), bidi)[0] == 1

    def test_writes_none(self):
        hass = _Hass()
        ad = _battery(hass)
        ad._force_discharge_failures = ad.FORCE_DISCHARGE_FAILURE_LIMIT
        assert setpoint_wish_of(_sale("b1"), ad) is None, "the actuator drops it"
        off = _battery(hass)
        off._last_intent = BatteryIntent.OFF
        assert setpoint_wish_of(_d("b1", BatteryIntent.OFF), off) is None
        blind = _battery(hass)
        blind._last_intent = BatteryIntent.NORMAL
        hold = _d("b1", BatteryIntent.LIMIT_DISCHARGE, discharge_limit_w=0.0)
        assert setpoint_wish_of(hold, blind, inputs_degraded=True) is None


# ─────────────────────────────────────────────────────────────────
# 6. The sale split counts sale surfaces
# ─────────────────────────────────────────────────────────────────

def _pbc(limit=None, sale=None, mode="auto"):
    out = {"battery_mode": mode}
    if limit:
        out["battery_discharge_control_entity"] = limit
    if sale:
        out["battery_force_discharge_control_entity"] = sale
    return out


class TestSaleSurfaceCount:
    def test_one_sale_entity_two_limits_is_one(self):
        assert sale_surface_count([(_pbc(LIMIT, SETPOINT), None),
                                   (_pbc(LIMIT2, SETPOINT), None)]) == 1

    def test_two_sale_entities_one_limit_is_two(self):
        assert sale_surface_count([(_pbc(LIMIT, SETPOINT), None),
                                   (_pbc(LIMIT, SETPOINT2), None)]) == 2

    def test_without_a_sale_entity_the_limit_counts_as_before(self):
        assert sale_surface_count([(_pbc(LIMIT), None), (_pbc(LIMIT), None)]) == 1
        assert sale_surface_count([(_pbc(LIMIT), None), (_pbc(LIMIT2), None)]) == 2
        assert sale_surface_count([(_pbc(), None), (_pbc(), None)]) == 2

    def test_a_built_adapter_answers_for_itself(self):
        hass = _Hass()
        seller = _battery(hass, LIMIT)
        cannot = _battery(hass, LIMIT2, "")
        assert sale_surface_count([(_pbc(LIMIT, SETPOINT), seller),
                                   (_pbc(LIMIT2), cannot)]) == 1
        withdrawn = _battery(hass, LIMIT2, SETPOINT2)
        withdrawn._force_discharge_failures = withdrawn.FORCE_DISCHARGE_FAILURE_LIMIT
        assert sale_surface_count([(_pbc(LIMIT, SETPOINT), seller),
                                   (_pbc(LIMIT2, SETPOINT2), withdrawn)]) == 1
        h1 = HuaweiBatteryAdapter(hass, {"inverter_device_id": "luna"})
        h2 = HuaweiBatteryAdapter(hass, {"inverter_device_id": "luna"})
        assert sale_surface_count([(_pbc(LIMIT), h1), (_pbc(LIMIT2), h2)]) == 1

    def test_off_and_nobody(self):
        assert sale_surface_count([(_pbc(LIMIT, SETPOINT), None),
                                   (_pbc(LIMIT2, SETPOINT2, mode="off"), None)]) == 1
        assert sale_surface_count([]) == 1


@pytest.mark.asyncio
class TestTheSplitInThePipeline:
    @pytest.mark.parametrize("limits, sales, share", [
        ((LIMIT, LIMIT2), (SETPOINT, SETPOINT), 4000.0),   # one sale entity: whole
        ((LIMIT, LIMIT), (SETPOINT, SETPOINT2), 2000.0),   # two sale entities: half
    ])
    async def test_the_share(self, monkeypatch, limits, sales, share):
        from custom_components.solar_energy_management.coordinator import (
            energy_plan_actuation as epa,
        )
        hass = _Hass()
        cfgs = [_pbc(limits[i], sales[i]) for i in range(2)]
        stub = _stub(hass, {f"b{i + 1}": _battery(hass, limits[i], sales[i])
                            for i in range(2)})
        stub._per_battery_config = lambda i, n: cfgs[i]
        stub._energy_plan_actuation = True
        monkeypatch.setattr(epa, "arbitrage_sell_gate", lambda *a, **k: (True, 4000.0))
        views: list = []
        await _cycle(monkeypatch, stub, {"b1": _normal("b1"), "b2": _normal("b2")},
                     views=views)
        assert [v.arbitrage_sell for v in views] == [(True, share)] * 2


# ─────────────────────────────────────────────────────────────────
# 7. Structure: one door to the sale power entity
# ─────────────────────────────────────────────────────────────────

_DOOR = "_write_force_discharge"


def _writers_of_the_sale_entity(src: str) -> list:
    """Functions that send a service call naming ``_force_discharge_entity``."""
    found = []
    for node in ast.walk(ast.parse(src)):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for call in ast.walk(node):
            if (isinstance(call, ast.Call)
                    and isinstance(call.func, ast.Attribute)
                    and call.func.attr == "async_call"
                    and any(isinstance(n, ast.Attribute)
                            and n.attr == "_force_discharge_entity"
                            for a in call.args for n in ast.walk(a))):
                found.append(node.name)
    return found


def test_only_the_door_writes_the_sale_power_entity():
    """The hold-back sits in ``_write_force_discharge``: a second writer of
    the entity would bring the fight back unseen."""
    seen = []
    for path in sorted((ROOT / "coordinator" / "battery_adapters").glob("*.py")):
        for name in _writers_of_the_sale_entity(path.read_text()):
            seen.append((path.name, name))
    assert seen == [("base.py", _DOOR)], seen


def test_the_door_check_bites():
    sneaky = textwrap.dedent("""
        class X:
            async def sneaky(self):
                await self._hass.services.async_call(
                    "number", "set_value",
                    {"entity_id": self._force_discharge_entity, "value": 0})
    """)
    assert _writers_of_the_sale_entity(sneaky) == ["sneaky"]


def test_both_sale_splits_count_sale_surfaces():
    """The arbitrage sale and the forecast spend are shared out the same
    way; the pipeline test drives the first, this pins the second."""
    src = (ROOT / "coordinator" / "coordinator.py").read_text()
    fn = next(n for n in ast.walk(ast.parse(src))
              if isinstance(n, ast.AsyncFunctionDef)
              and n.name == "_run_battery_pipeline")
    splits = {}
    for node in ast.walk(fn):
        if (isinstance(node, ast.Assign) and len(node.targets) == 1
                and isinstance(node.targets[0], ast.Name)
                and node.targets[0].id in ("_arb_sell", "_fsell")):
            splits[node.targets[0].id] = {
                n.id for n in ast.walk(node.value) if isinstance(n, ast.Name)}
    assert set(splits) == {"_arb_sell", "_fsell"}
    for name, names in splits.items():
        assert "_sale_count" in names and "_eff_battery_count" not in names, name
