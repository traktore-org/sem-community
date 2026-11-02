"""#1179 — the discharge limit still moved while the pack was empty.

PROD, 30.10 and 01.11.2026: the pack sat at 20 % (its inverter's own end of
discharge) and 0 W all evening. Under the car clamp the limit still moved
15–17 times: 1000 → 3000 → 1000 → 2500 → 750 → 1000 → 750 … Each move is a
write to the inverter, and none of them does anything: a pack at its floor
sends nothing, whatever the limit.

SEM does not know that floor (it is the inverter's own setting; SEM's
reserve may be another number). The fix learns it from the pack: a limit of
at least one step in force, the pack idle (its own power within 100 W) and
the home buying at least one step from the grid with no sun, for
``DISCHARGE_LIMIT_FLOOR_CYCLES`` cycles in a row. From then on the limit does
not rise; it still falls by its own rule. The pack moving, its level moving
two points, or no such limit in force starts the count again.

Pinned here:

* the reading (``decide_battery.pack_reading``) — every condition, and that
  ``decide_battery`` carries it on its decision;
* the actuator on a real adapter: the PROD evening writes nothing after the
  first clamp, and was many writes before (the same cycles, no reading);
  a fall still goes out; each way the count starts again;
* packs on one limit entity are judged as one;
* the real pipeline hands each battery its own level and power flags and
  the cycle's grid and sun, and the whole chain holds the rise.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    DISCHARGE_LIMIT_FLOOR_CYCLES,
    DISCHARGE_LIMIT_LOWER_DWELL_CYCLES,
    PACK_FLOOR_SOC_DRIFT,
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_shared_limit import (
    packs_judged_together,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryPower,
    BatteryRuntime,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    MANUAL_CHARGE_STALL_W,
    MANUAL_SALE_STALL_SUN_W,
    PACK_FLOOR_IMPORT_W,
    decide_battery,
    pack_reading,
)
from custom_components.solar_energy_management.coordinator.install_modules import (
    Module, Presence,
)

LIMIT = "number.battery_max_discharge"
LIMIT2 = "number.battery_2_max_discharge"
MAX_W = 5000.0
N = DISCHARGE_LIMIT_FLOOR_CYCLES


class _Hass:
    """Numbers that take what is written to them; every write is kept."""

    def __init__(self):
        self.writes: list = []
        self._states = {e: self._num(MAX_W) for e in (LIMIT, LIMIT2)}
        self.states = SimpleNamespace(get=self._states.get,
                                      async_all=lambda *a, **k: [])
        self.services = SimpleNamespace(async_call=self._call)

    @staticmethod
    def _num(w):
        return SimpleNamespace(state=str(w), attributes={
            "unit_of_measurement": "W", "min": 0, "max": MAX_W})

    async def _call(self, domain, service, data=None, **kw):
        data = dict(data or {})
        ent = data.get("entity_id")
        if service == "set_value" and ent in self._states:
            self.writes.append((ent, float(data["value"])))
            self._states[ent] = self._num(float(data["value"]))

    def values(self, ent=LIMIT) -> list:
        return [w for e, w in self.writes if e == ent]


def _adapter(hass=None, entity=LIMIT):
    hass = hass or _Hass()
    return hass, GenericBatteryAdapter(hass, {
        "battery_discharge_control_entity": entity,
        "battery_max_discharge_power": MAX_W})


def _clamp(w, *, idle_soc=None, moves=False, follows=False, bid="b1"):
    """A clamp at ``w``. PROD's rises were targets (the cars' share, a meter
    at its limit), so ``follows_load`` is off unless asked."""
    return BatteryDecision(
        battery_id=bid, intent=BatteryIntent.LIMIT_DISCHARGE,
        discharge_limit_w=w, reason="ev plugged in → house",
        follows_load=follows, pack_idle_soc=idle_soc, pack_moves=moves)


async def _run(adapter, houses, **kw):
    for h in houses:
        await actuate_battery(_clamp(h, **kw), adapter)


async def _at_floor(house_w=1000.0, soc=20.0):
    """A clamp in force at ``house_w`` whose pack has shown its floor."""
    hass, a = _adapter()
    await _run(a, [house_w] * (N + 1), idle_soc=soc)
    assert a._pack_floor == (soc, N)
    hass.writes.clear()
    return hass, a


# ─── 1. the reading ─────────────────────────────────────────────────────────

def _view(*, w=0.0, soc=20.0, power_read=True, soc_read=True,
          site=(900.0, 0.0)):
    return SimpleNamespace(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc,
                               last_known_w=w, soc_read=soc_read,
                               power_read=power_read),
        grid_and_sun=site)


class TestTheReading:
    def test_the_prod_evening_is_idle(self):
        assert pack_reading(_view()) == (20.0, False)

    @pytest.mark.parametrize("w", [MANUAL_CHARGE_STALL_W + 1, -(MANUAL_CHARGE_STALL_W + 1)])
    def test_a_pack_that_sends_or_takes_moves(self, w):
        assert pack_reading(_view(w=w)) == (None, True)

    @pytest.mark.parametrize("w", [MANUAL_CHARGE_STALL_W, -MANUAL_CHARGE_STALL_W, 40.0])
    def test_a_trickle_is_idle(self, w):
        assert pack_reading(_view(w=w)) == (20.0, False)

    def test_a_power_that_is_no_reading_says_nothing(self):
        assert pack_reading(_view(power_read=False)) == (None, False)
        assert pack_reading(_view(w=3000.0, power_read=False)) == (None, False)
        assert pack_reading(_view(w=float("nan"))) == (None, False)

    def test_a_level_that_is_no_reading_is_not_idle(self):
        assert pack_reading(_view(soc_read=False)) == (None, False)

    def test_no_measured_grid_is_not_idle(self):
        assert pack_reading(_view(site=None)) == (None, False)

    def test_a_home_that_buys_too_little_is_not_idle(self):
        assert pack_reading(_view(site=(PACK_FLOOR_IMPORT_W - 1, 0.0))) == (None, False)
        assert pack_reading(_view(site=(PACK_FLOOR_IMPORT_W, 0.0))) == (20.0, False)

    def test_sun_is_not_idle(self):
        """A hybrid inverter full with sun has no room for the pack."""
        assert pack_reading(_view(site=(900.0, MANUAL_SALE_STALL_SUN_W + 1))) == (None, False)

    def test_a_runtime_built_without_flags_reads_nothing(self):
        rt = BatteryRuntime(battery_id="b1", last_known_soc=20.0)
        assert (rt.soc_read, rt.power_read) == (False, False)
        assert pack_reading(SimpleNamespace(runtime=rt, grid_and_sun=(900.0, 0.0))) == (None, False)

    def test_decide_battery_carries_it(self, monkeypatch):
        from custom_components.solar_energy_management.coordinator import (
            decide_battery as db,
        )
        monkeypatch.setattr(db, "_decide_battery", lambda v: _clamp(1000.0))
        view = SimpleNamespace(**vars(_view()), sem_forced_charge=None,
                               sem_forced_discharge=None, sem_stop_misses=0)
        d = decide_battery(view)
        assert (d.pack_idle_soc, d.pack_moves) == (20.0, False)
        assert d == _clamp(1000.0), "a reading is not part of what to do"


# ─── 2. the actuator ────────────────────────────────────────────────────────

#: The house of PROD's 01.11 evening under the car clamp, one value a
#: cycle: 1000, the cars' share at 3000, 1000, 2500, 750, and a hover
#: across the 750 W step. The pack read 20 % and 0 W throughout.
_PROD = ([846.0] * 8 + [3000.0] * 9 + [919.0] * 90 + [2500.0] * 9
         + [700.0] * 8 + [733.0, 760.0] * 25 + [624.0] * 10 + [763.0] * 20
         + [568.0] * 10 + [750.0] * 30)


@pytest.mark.asyncio
class TestTheEmptyPack:
    async def test_the_prod_evening_writes_the_first_clamp_and_one_fall(self):
        """No rise at all; the house's one real fall (568 W) still lands."""
        hass, a = _adapter()
        await _run(a, _PROD, idle_soc=20.0)
        assert hass.values() == [1000.0, 750.0], hass.values()

    async def test_before_the_fix_the_same_evening_moved_the_limit(self):
        """The same cycles with no reading: pins that the test above is the
        bug."""
        hass, a = _adapter()
        await _run(a, _PROD)
        assert len(hass.values()) >= 6, hass.values()

    async def test_a_house_rise_waits_too(self):
        hass, a = await _at_floor(1000.0)
        await _run(a, [2600.0] * 60, idle_soc=20.0, follows=True)
        assert hass.writes == []

    async def test_a_fall_still_goes_out(self):
        """The fall keeps the pack out of the car once it can send again."""
        hass, a = await _at_floor(2500.0)
        await _run(a, [700.0] * DISCHARGE_LIMIT_LOWER_DWELL_CYCLES, idle_soc=20.0)
        assert hass.values() == [750.0]
        await _run(a, [2500.0] * 20, idle_soc=20.0)
        assert hass.values() == [750.0], "and does not rise back"

    async def test_before_the_count_is_full_a_rise_goes_out(self):
        """The first clamp is written from no limit, so it counts no cycle:
        the rise is the count's last cycle but one."""
        hass, a = _adapter()
        await _run(a, [1000.0] * (N - 1), idle_soc=20.0)
        await _run(a, [3000.0], idle_soc=20.0)
        assert hass.values() == [1000.0, 3000.0]
        assert a._pack_floor == (20.0, N - 1)

    async def test_the_pack_moving_ends_it(self):
        hass, a = await _at_floor(1000.0)
        await _run(a, [3000.0], moves=True)
        assert hass.values() == [3000.0]
        assert a._pack_floor is None

    async def test_a_cycle_with_no_reading_keeps_it(self):
        hass, a = await _at_floor(1000.0)
        await _run(a, [3000.0] * 5)
        assert hass.writes == []

    async def test_a_level_that_moves_starts_the_count_again(self):
        hass, a = await _at_floor(1000.0, soc=20.0)
        await _run(a, [3000.0], idle_soc=20.0 + PACK_FLOOR_SOC_DRIFT)
        assert hass.values() == [3000.0]
        assert a._pack_floor == (20.0 + PACK_FLOOR_SOC_DRIFT, 1)

    async def test_a_one_point_flicker_keeps_it(self):
        """PROD's level reads 20 then 19 at its floor."""
        hass, a = await _at_floor(1000.0, soc=20.0)
        await _run(a, [3000.0] * 5, idle_soc=19.0)
        await _run(a, [3000.0] * 5, idle_soc=20.0)
        assert hass.writes == []

    async def test_a_limit_under_one_step_teaches_nothing(self):
        """The 0 W hold: the pack sends nothing because SEM says so."""
        hass, a = _adapter()
        await _run(a, [0.0] * (N + 3), idle_soc=20.0)
        assert getattr(a, "_pack_floor", None) is None
        await _run(a, [1000.0], idle_soc=20.0)
        assert hass.values() == [0.0, 1000.0]

    async def test_the_first_clamp_after_normal_goes_out(self):
        hass, a = await _at_floor(1000.0)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.NORMAL, reason="car gone"), a)
        assert a._pack_floor is None
        await _run(a, [3000.0], idle_soc=20.0)
        assert hass.values() == [MAX_W, 3000.0]

    async def test_observer_and_yield_forget_it(self):
        for kw in ({"observer": True}, {"yielded": True}):
            _hass, a = await _at_floor(1000.0)
            await actuate_battery(_clamp(1000.0, idle_soc=20.0), a, **kw)
            assert a._pack_floor is None, kw

    async def test_the_log_says_it_once_each_way(self, caplog):
        import logging
        caplog.set_level(logging.INFO)
        hass, a = _adapter()
        await _run(a, [1000.0] * (N + 10), idle_soc=20.0)
        await _run(a, [1000.0] * 3, moves=True)
        said = [r.getMessage() for r in caplog.records if "#1179" in r.getMessage()]
        assert len(said) == 2, said
        assert "sends nothing at 20%" in said[0]


# ─── 3. packs on one limit entity ───────────────────────────────────────────

def _rows(*pairs, entities=(LIMIT, LIMIT)):
    hass = _Hass()
    out = []
    for i, ((soc, moves), ent) in enumerate(zip(pairs, entities, strict=True)):
        _, ad = _adapter(hass, ent)
        out.append((f"b{i + 1}", ad, _clamp(1000.0, idle_soc=soc, moves=moves,
                                             bid=f"b{i + 1}")))
    return out


class TestPacksOnOneEntity:
    def test_one_resting_beside_one_sending_is_no_floor(self):
        out = packs_judged_together(_rows((20.0, False), (None, True)))
        assert [(d.pack_idle_soc, d.pack_moves) for _, _, d in out] == [
            (None, True), (None, True)]

    def test_one_unread_beside_one_idle_is_no_floor(self):
        out = packs_judged_together(_rows((20.0, False), (None, False)))
        assert [(d.pack_idle_soc, d.pack_moves) for _, _, d in out] == [
            (None, False), (None, False)]

    def test_both_idle_stay_idle(self):
        out = packs_judged_together(_rows((20.0, False), (21.0, False)))
        assert [d.pack_idle_soc for _, _, d in out] == [20.0, 21.0]

    def test_own_entities_are_judged_alone(self):
        rows = _rows((20.0, False), (None, True), entities=(LIMIT, LIMIT2))
        assert packs_judged_together(rows) == rows
        assert [(d.pack_idle_soc, d.pack_moves) for _, _, d in rows] == [
            (20.0, False), (None, True)]


# ─── 4. the real pipeline ───────────────────────────────────────────────────

def _stub(hass, adapters):
    stub = MagicMock()
    stub.hass = hass
    stub.setup_presence = {m: Presence.PRESENT for m in Module}
    stub._observer_mode = False
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


def _power(batteries, *, import_w=900.0, sun_w=0.0, **fleet):
    base = dict(
        inputs_degraded=False, dark_inputs=(), home_residual_clamped_w=0.0,
        grid_import_power=import_w, solar_power=sun_w,
        batteries=batteries, battery_soc=20.0, battery_power=0.0,
        battery_soc_known=True, battery_soc_unavailable=False,
        battery_power_unavailable=False, battery_power_read=True)
    base.update(fleet)
    return SimpleNamespace(**base)


def _bp(bid, *, w=0.0, soc=20.0, read=True):
    return BatteryPower(battery_id=bid, power_w=w, soc_pct=soc, power_read=read)


@pytest.mark.asyncio
class TestThePipeline:
    async def _views(self, monkeypatch, power):
        from custom_components.solar_energy_management.coordinator import (
            decide_battery as db,
        )
        seen = []

        def _decide(view):
            seen.append(view)
            return BatteryDecision(battery_id=view.runtime.battery_id,
                                   intent=BatteryIntent.NORMAL, reason="x")

        monkeypatch.setattr(db, "decide_battery", _decide)
        hass = _Hass()
        await SEMCoordinator._run_battery_pipeline(
            _stub(hass, {}), power, SimpleNamespace(), "idle")
        return seen

    async def test_each_battery_gets_its_own_flags_and_the_site(self, monkeypatch):
        seen = await self._views(monkeypatch, _power({
            "b1": _bp("b1"), "b2": _bp("b2", soc=None, read=False)}))
        assert [(v.runtime.soc_read, v.runtime.power_read) for v in seen] == [
            (True, True), (False, False)]
        assert [v.grid_and_sun for v in seen] == [(900.0, 0.0)] * 2

    async def test_one_battery_keeps_the_fleet_flags(self, monkeypatch):
        seen = await self._views(monkeypatch, _power(
            {}, battery_soc_unavailable=True))
        assert (seen[0].runtime.soc_read, seen[0].runtime.power_read) == (False, True)

    async def test_a_grid_that_is_no_measurement_is_no_site(self, monkeypatch):
        seen = await self._views(monkeypatch, _power(
            {"b1": _bp("b1")}, home_residual_clamped_w=300.0))
        assert seen[0].grid_and_sun is None

    async def test_the_whole_chain_holds_the_rise(self, monkeypatch):
        """Real pipeline, real ``decide_battery`` wrapper, real adapter: the
        clamp asks for 3000 W after the pack showed its floor."""
        from custom_components.solar_energy_management.coordinator import (
            decide_battery as db,
        )
        hass = _Hass()
        _, ad = _adapter(hass)
        stub = _stub(hass, {"b1": ad})
        house = {"w": 1000.0}
        monkeypatch.setattr(db, "_decide_battery",
                            lambda view: _clamp(house["w"]))
        for _ in range(N + 1):
            await SEMCoordinator._run_battery_pipeline(
                stub, _power({"b1": _bp("b1")}), SimpleNamespace(), "idle")
        house["w"] = 3000.0
        for _ in range(5):
            await SEMCoordinator._run_battery_pipeline(
                stub, _power({"b1": _bp("b1")}), SimpleNamespace(), "idle")
        assert hass.values() == [1000.0]
        # the pack sends again: the rise goes out at once
        await SEMCoordinator._run_battery_pipeline(
            stub, _power({"b1": _bp("b1", w=800.0)}), SimpleNamespace(), "idle")
        assert hass.values() == [1000.0, 3000.0]
