"""#1426 — a charge that starts while the cloud still shows SEM's own values.

A battery setting changed through a cloud integration can show its old
value for minutes after a write. SEM stops a grid charge: it puts the mode
back to the user's ``self_consumption`` and turns "allow grid charging"
off. The cloud still shows ``autonomous`` and "on" — SEM's own charge
values. The next charge starts inside that time.

Before the fix the start read those as the user's: it saved ``autonomous``
as the mode to put back and took the permit "on" as the user's, so it never
turned it on (it was really off) and never off again. When the cloud showed
the real values, the mode read "not the old one", the charge ended at once
and the plan left the battery out for 24 h.

The rule pinned here: SEM remembers what it put back. For 15 minutes a
read of SEM's own charge value is SEM's, and the start counts from the
value SEM put back. A value that is neither is the user's.

Round 2 (25.11.2026): the memory no longer ends when the entity shows the
put-back. Tesla Fleet shows every write at once (its own state, before any
poll), so the next cycle always read the put-back and the memory was gone
before the poll that still showed SEM's values. The reserve number had the
same gap: its hold dropped SEM's values on that first read.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    charge_target,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

from .test_1377_cloud_read_lag import CYCLE_S, _cycles, _poll, clock  # noqa: F401
from .test_1377_powerwall_charge import (
    MODE, PERMIT, RESERVE, _adapter, _charge, _Hass, _stop, _Store,
)


@pytest.fixture
def wall(clock, monkeypatch):
    """(round 2) The reserve hold on the test's clock too: it keeps its
    own, read when it is made, so this runs before ``_adapter``."""
    fake = SimpleNamespace(monotonic=lambda: clock.t,
                           time=lambda: 1.7e9 + clock.t)
    monkeypatch.setattr(charge_target, "time", fake)
    return clock


def _idle():
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.NORMAL)


async def _idle_cycles(a, clock, seconds):
    """Cycles with no charge, as the coordinator runs them: the adopt step
    (which looks at SEM's records), then the decision."""
    for _ in range(int(seconds // CYCLE_S)):
        clock.t += CYCLE_S
        await a.async_adopt_running_charge()
        await actuate_battery(_idle(), a)


def _reserve_prior(hold):
    return json.loads(hold.raw)["entities"][RESERVE]["prior"]


def _three(hass):
    return hass.read(MODE), hass.read(PERMIT), hass.read(RESERVE)


async def _charge_then_stop(hass, rec, hold, clock):
    a = _adapter(hass, rec, hold)
    await actuate_battery(_charge(), a)
    await _cycles(a, clock, 120)
    await actuate_battery(_stop(), a)
    assert (hass.read(MODE), hass.read(PERMIT)) == ("self_consumption", "off")
    return a


def _cloud_still_shows_sem(hass):
    """The cloud has not yet shown SEM's put-back: SEM's charge values."""
    hass.put(MODE, "autonomous")
    hass.put(PERMIT, "on")


def _prior(rec, entity):
    return json.loads(rec.raw).get("prior", {}).get(entity)


class TestTheStartInsideTheWindow:
    async def test_the_user_values_are_the_ones_sem_put_back(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 120
        n = len(hass.calls)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "self_consumption", "not SEM's own mode"
        assert _prior(rec, PERMIT) == "off", "SEM turned the permit on"
        sent = [(c[1], c[2].get("option")) for c in hass.calls[n:]]
        assert ("turn_on", None) in sent, "the permit really is off"
        assert ("select_option", "autonomous") in sent

    async def test_the_real_values_showing_do_not_end_the_charge(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 120
        await actuate_battery(_charge(), a)
        # the cloud now shows SEM's put-back, then SEM's new charge values
        hass.put(MODE, "self_consumption")
        hass.put(PERMIT, "off")
        await _cycles(a, clock, 60)
        assert a.charge_refused is False, "the plan keeps the battery"
        hass.put(MODE, "autonomous")
        hass.put(PERMIT, "on")
        await _cycles(a, clock, 120)
        assert a.charge_refused is False
        await actuate_battery(_stop(), a)
        assert (hass.read(MODE), hass.read(PERMIT)) == ("self_consumption", "off")

    async def test_a_restart_inside_the_window_keeps_the_memory(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 120
        fresh = _adapter(hass, rec, hold)                  # HA restarts
        await actuate_battery(_charge(), fresh)
        assert _prior(rec, MODE) == "self_consumption"
        assert _prior(rec, PERMIT) == "off"


class TestWhatIsTheUsers:
    async def test_a_value_set_since_is_the_users(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        hass.put(MODE, "backup")                           # set by hand
        clock.t += 120
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "backup"

    async def test_after_the_window_sems_value_is_taken_as_shown(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        _cloud_still_shows_sem(hass)
        clock.t += 16 * 60                                 # past 15 minutes
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) != "self_consumption"

    async def test_the_put_back_shown_at_once_keeps_the_memory(self, clock):
        """(round 2) A cloud shows SEM's put-back at once; a poll a minute
        on can still show SEM's values. That read is SEM's."""
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await a.async_adopt_running_charge()  # the next cycle sees the put-back
        clock.t += 60
        _cloud_still_shows_sem(hass)                      # the poll
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "self_consumption"
        assert _prior(rec, PERMIT) == "off"


class TestTheTeslaOrder:
    """(round 2) What Tesla Fleet does after SEM's stop: the three
    put-backs show at once, cycles run, then a poll shows SEM's charge
    values again (the cloud has not caught up), then the real ones."""

    async def test_a_start_after_the_poll_keeps_all_three_settings(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        assert _three(hass) == ("self_consumption", "off", "0")
        await _idle_cycles(a, clock, 120)             # the put-backs show
        _poll(hass, "autonomous", "on", "100")        # SEM's values again
        await _idle_cycles(a, clock, 60)
        n = len(hass.calls)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "self_consumption", "not SEM's own mode"
        assert _prior(rec, PERMIT) == "off", "SEM turned the permit on"
        assert _reserve_prior(hold) == 0, "not SEM's own 100 %"
        sent = [(c[1], c[2].get("option")) for c in hass.calls[n:]]
        assert ("turn_on", None) in sent, "the permit really is off"
        # the cloud catches up, then shows SEM's new charge values
        _poll(hass, "self_consumption", "off", "0")
        await _cycles(a, clock, 60)
        _poll(hass, "autonomous", "on", "100")
        await _cycles(a, clock, 120)
        assert a.charge_refused is False, "the plan keeps the battery"
        await actuate_battery(_stop(), a)
        assert _three(hass) == ("self_consumption", "off", "0")

    async def test_nothing_is_sent_while_the_poll_shows_sems_values(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 60)
        _poll(hass, "autonomous", "on", "100")
        n = len(hass.calls)
        await _idle_cycles(a, clock, 12 * 60)
        assert hass.calls[n:] == [], "a read of SEM's value is no reason to write"

    async def test_a_restart_after_the_poll_keeps_the_reserve(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 120)
        _poll(hass, "autonomous", "on", "100")
        clock.t += 60
        fresh = _adapter(hass, rec, hold)                  # HA restarts
        await fresh.async_adopt_running_charge()
        await actuate_battery(_charge(), fresh)
        assert _reserve_prior(hold) == 0
        assert _prior(rec, MODE) == "self_consumption"
        assert _prior(rec, PERMIT) == "off"
        await _cycles(fresh, clock, 120)
        await actuate_battery(_stop(), fresh)
        assert hass.read(RESERVE) == "0"

    async def test_a_value_set_since_is_still_the_users(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 120)
        _poll(hass, "backup", "off", "30")                 # set by hand
        await _idle_cycles(a, clock, 60)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "backup"
        assert _reserve_prior(hold) == 30

    async def test_past_fifteen_minutes_the_memory_ends(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 16 * 60)
        _poll(hass, "autonomous", "on", "100")
        await _idle_cycles(a, clock, 30)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "autonomous"
        assert _reserve_prior(hold) == 100


class TestTheReserveMemory:
    """(round 2) ``ChargeTargetHold`` keeps SEM's values after the
    put-back reads back, for ``LANDED_KEEP_S``, and sends nothing."""

    def _hold(self, hass, store):
        hold = ChargeTargetHold(hass, store, configured=(RESERVE,))
        hold.now = [0.0]
        hold._clock = lambda: hold.now[0]
        hold._wall = lambda: 1.7e9 + hold.now[0]
        return hold

    async def _landed(self, hass, store):
        hold = self._hold(hass, store)
        assert await hold.write(RESERVE, 100)
        await hold.put_back(RESERVE)
        await hold.settle()                       # reads 0: put back
        return hold

    async def test_a_landed_put_back_has_nothing_left_to_put_back(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        assert hold.snapshot() == {}, "diagnostics: nothing to put back"
        row = json.loads(store.raw)["entities"][RESERVE]
        assert (row["held"], row["pending"], row["prior"]) == (False, False, 0)
        assert isinstance(row["landed_at"], float)

    async def test_the_memory_is_read_after_a_restart(self):
        hass, store = _Hass(reserve="0"), _Store()
        await self._landed(hass, store)
        hass.put(RESERVE, "100")                 # a poll: SEM's value
        fresh = self._hold(hass, store)
        fresh.now[0] = 120.0
        assert await fresh.write(RESERVE, 80)
        assert _reserve_prior(store) == 0

    async def test_a_damaged_time_is_no_memory(self):
        hass, store = _Hass(reserve="0"), _Store()
        await self._landed(hass, store)
        raw = json.loads(store.raw)
        raw["entities"][RESERVE]["landed_at"] = True
        store.raw = json.dumps(raw)
        hass.put(RESERVE, "100")
        fresh = self._hold(hass, store)
        fresh._wall = lambda: 100.0          # a True read as 1.0 would count
        assert await fresh.write(RESERVE, 80)
        assert _reserve_prior(store) == 100, "no memory: the read is taken"

    async def test_a_time_ahead_of_the_clock_is_no_memory(self):
        """The clock was set back after the put-back: the memory must not
        last as long as the clock was wrong."""
        hass, store = _Hass(reserve="0"), _Store()
        await self._landed(hass, store)
        hass.put(RESERVE, "100")                  # set by hand, days later
        fresh = self._hold(hass, store)
        fresh.now[0] = -7 * 24 * 3600.0           # the clock went back
        assert await fresh.write(RESERVE, 80)
        assert _reserve_prior(store) == 100

    async def test_a_put_back_time_ahead_of_the_clock_is_no_memory(self, clock):
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        clock.t -= 7 * 24 * 3600.0                # the clock went back
        _cloud_still_shows_sem(hass)              # set by hand
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "autonomous"

    async def test_past_the_time_settle_drops_it(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = ChargeTargetHold.LANDED_KEEP_S + 1
        await hold.settle()
        assert json.loads(store.raw)["entities"] == {}
