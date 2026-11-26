"""#1429 — the memory of SEM's put-back ends on a read, not on a clock.

After a stop SEM puts the user's mode, permit and reserve back, and for a
while a read of SEM's own charge values is SEM's (#1426): a cloud read can
show them for minutes after the put-back. Before this fix that while was 15
minutes from the put-back, whatever the entity read. The 23.11 History of
the #1377 reporter shows the cloud's old copy from 5 to 16 minutes after a
write. Mirrored on a stop, the memory ended while SEM's values still showed,
and a start then saved SEM's mode, permit "on" and 100 % reserve as the
user's; its stop wrote them back as the user's values.

The rule pinned here is the start's (``_wait_while_away``): a value counts
once it has read 15 minutes with no read of the other. A read of the other
one starts the time again. A value that is neither is the user's at once.
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
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)

from .test_1377_cloud_read_lag import _cycles, _poll, clock  # noqa: F401
from .test_1377_powerwall_charge import (
    MODE, PERMIT, RESERVE, _adapter, _charge, _Hass, _stop, _Store,
)
from .test_1426_own_put_back import (
    _charge_then_stop, _idle, _idle_cycles, _prior, _reserve_prior, _three,
)

MIN = 60.0


@pytest.fixture
def wall(clock, monkeypatch):
    """The reserve hold on the test's clock too (it reads its clock when
    it is made, so this runs before ``_adapter``)."""
    fake = SimpleNamespace(monotonic=lambda: clock.t,
                           time=lambda: 1.7e9 + clock.t)
    monkeypatch.setattr(charge_target, "time", fake)
    return clock


def _sem_values(hass):
    _poll(hass, "autonomous", "on", "100")


def _users_values(hass):
    _poll(hass, "self_consumption", "off", "0")


async def _the_old_copy_from_five_minutes(hass, rec, hold, clock):
    """The stop, the put-backs shown at once, then from 5 min on a poll
    that shows SEM's charge values (the cloud's old copy)."""
    a = await _charge_then_stop(hass, rec, hold, clock)
    await _idle_cycles(a, clock, 5 * MIN)
    _sem_values(hass)
    return a


async def _yielded_cycles(a, clock, seconds):
    for _ in range(int(seconds // 10)):
        clock.t += 10
        await a.async_adopt_running_charge()
        await actuate_battery(_idle(), a, yielded=True)


class TestTheReportersLag:
    """The 23.11 lag shape, mirrored on a stop: the old copy shows from
    5 min and is still there 15 min after the put-back."""

    async def test_a_start_past_fifteen_minutes_keeps_the_users_values(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 10.5 * MIN)        # 15.5 min after the stop
        n = len(hass.calls)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "self_consumption", "not SEM's own mode"
        assert _prior(rec, PERMIT) == "off", "SEM turned the permit on"
        assert _reserve_prior(hold) == 0, "not SEM's own 100 %"
        sent = [(c[1], c[2].get("option")) for c in hass.calls[n:]]
        assert ("turn_on", None) in sent, "the permit really is off"

    async def test_that_charge_ends_with_the_users_values(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 10.5 * MIN)
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 2 * MIN)
        await actuate_battery(_stop(), a)
        assert _three(hass) == ("self_consumption", "off", "0")

    async def test_nothing_is_sent_while_the_old_copy_shows(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        n = len(hass.calls)
        await _idle_cycles(a, clock, 14 * MIN)
        assert hass.calls[n:] == [], "a read of SEM's value is no reason to write"

    async def test_a_restart_keeps_the_time(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 9 * MIN)           # 14 min after the stop
        fresh = _adapter(hass, rec, hold)               # HA restarts
        await _idle_cycles(fresh, clock, 2 * MIN)
        await actuate_battery(_charge(), fresh)
        assert _prior(rec, MODE) == "self_consumption"
        assert _prior(rec, PERMIT) == "off"
        assert _reserve_prior(hold) == 0


class TestTheTimeStartsAgain:
    async def test_the_put_back_shown_again_gets_its_own_fifteen_minutes(self, wall):
        """The cloud catches up at 16 min, then shows the old copy once
        more at 20 min: still SEM's."""
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 11 * MIN)
        _users_values(hass)                              # 16 min
        await _idle_cycles(a, clock, 4 * MIN)
        _sem_values(hass)                                # 20 min
        await _idle_cycles(a, clock, 1 * MIN)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "self_consumption"
        assert _prior(rec, PERMIT) == "off"
        assert _reserve_prior(hold) == 0

    async def test_the_put_back_for_fifteen_minutes_ends_the_memory(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 11 * MIN)
        _users_values(hass)                              # 16 min
        await _idle_cycles(a, clock, 16 * MIN)
        _poll(hass, "autonomous", "on", "100")           # set since
        await _idle_cycles(a, clock, 1 * MIN)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "autonomous"
        assert _reserve_prior(hold) == 100


class TestSEMsValueForFifteenMinutes:
    """No cloud read lags that long: SEM's value read 15 min without a
    break is the user's (set by hand, or the start's own bound)."""

    async def test_it_counts_as_the_users(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 16 * MIN)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "autonomous"
        assert _reserve_prior(hold) == 100

    async def test_a_value_set_since_is_the_users_at_once(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        await _idle_cycles(a, clock, 1 * MIN)
        _poll(hass, "backup", "off", "30")               # set by hand
        await _idle_cycles(a, clock, 1 * MIN)
        await actuate_battery(_charge(), a)
        assert _prior(rec, MODE) == "backup"
        assert _reserve_prior(hold) == 30


class TestTheRecord:
    async def test_the_record_keeps_what_shows_and_since_when(self):
        store = _Store()
        rec = ForcedChargeRecord(store)
        await rec.note_put_back(MODE, "autonomous", "self_consumption", 100.0)
        assert await rec.put_back_of(MODE) == (
            "autonomous", "self_consumption", 100.0, "self_consumption")
        await rec.put_back_shows(MODE, "autonomous", 400.0)
        again = ForcedChargeRecord(store)                # a restart
        assert await again.put_back_of(MODE) == (
            "autonomous", "self_consumption", 400.0, "autonomous")

    async def test_another_value_is_never_saved_as_shown(self):
        rec = ForcedChargeRecord(_Store())
        await rec.note_put_back(MODE, "autonomous", "self_consumption", 100.0)
        await rec.put_back_shows(MODE, "backup", 400.0)
        assert await rec.put_back_of(MODE) == (
            "autonomous", "self_consumption", 100.0, "self_consumption")

    async def test_a_record_from_before_shows_the_put_back(self):
        store = _Store()
        store.raw = json.dumps({"running": {}, "put_back": {
            MODE: ["autonomous", "self_consumption", 100.0]}})
        rec = ForcedChargeRecord(store)
        assert await rec.put_back_of(MODE) == (
            "autonomous", "self_consumption", 100.0, "self_consumption")

    async def test_a_damaged_shown_value_reads_as_the_put_back(self):
        store = _Store()
        store.raw = json.dumps({"running": {}, "put_back": {
            MODE: ["autonomous", "self_consumption", 100.0]},
            "put_back_shown": {MODE: "backup"}})
        rec = ForcedChargeRecord(store)
        assert (await rec.put_back_of(MODE))[3] == "self_consumption"

    async def test_the_rows_keep_their_old_shape(self):
        """A SEM from before reads rows of three, and drops any other: what
        shows goes beside them, so going back a version keeps the memory."""
        store = _Store()
        rec = ForcedChargeRecord(store)
        await rec.note_put_back(MODE, "autonomous", "self_consumption", 100.0)
        await rec.put_back_shows(MODE, "autonomous", 400.0)
        raw = json.loads(store.raw)
        assert raw["put_back"] == {MODE: ["autonomous", "self_consumption", 400.0]}
        assert raw["put_back_shown"] == {MODE: "autonomous"}


class TestTheReserveOnCyclesWithNoSettle:
    """The hold's ``settle`` sends put-backs, so it is skipped while the
    battery is yielded, in watch-only mode and on a charge cycle. The
    reserve's read is still taken every cycle, like the mode's."""

    async def test_a_yield_still_sees_the_old_copy(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        for _ in range(int(10.5 * MIN // 10)):
            clock.t += 10
            await a.async_adopt_running_charge()
            await actuate_battery(_idle(), a, yielded=True)
        await actuate_battery(_charge(), a)
        assert _reserve_prior(hold) == 0, "not SEM's own 100 %"

    async def test_a_value_set_by_hand_while_yielded_is_the_users(self, wall):
        """(review) Yielded from the stop on, so ``settle`` never runs: the
        user sets 30 at 2 min, then SEM's own 100 at 8 min. That 100 is
        theirs; the charge at 18 min must not put 0 back over it."""
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await _yielded_cycles(a, clock, 2 * MIN)
        hass.put(RESERVE, "30")
        await _yielded_cycles(a, clock, 6 * MIN)
        hass.put(RESERVE, "100")
        await _yielded_cycles(a, clock, 10 * MIN)
        await actuate_battery(_charge(), a)
        assert _reserve_prior(hold) == 100, "the user's own 100 %"

    async def test_sems_value_after_the_time_is_up_is_the_users(self, wall):
        """Yielded: the put-back shows for 16 min, then 100. The memory is
        over, so that 100 is the user's pick and does not start it again."""
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _charge_then_stop(hass, rec, hold, clock)
        await _yielded_cycles(a, clock, 16 * MIN)
        hass.put(RESERVE, "100")
        await _yielded_cycles(a, clock, 1 * MIN)
        await actuate_battery(_charge(), a)
        assert _reserve_prior(hold) == 100, "the user's own 100 %"

    async def test_watch_only_writes_nothing(self, wall):
        clock = wall
        hass, rec, hold = _Hass(reserve="0"), _Store(), _Store()
        a = await _the_old_copy_from_five_minutes(hass, rec, hold, clock)
        n = len(hass.calls)
        for _ in range(int(10.5 * MIN // 10)):
            clock.t += 10
            await a.async_adopt_running_charge(observer=True)
            await actuate_battery(_idle(), a, observer=True)
        assert hass.calls[n:] == []


class TestTheReserveHold:
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

    async def test_sems_value_read_late_keeps_the_memory(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")                  # the cloud's old copy
        await hold.settle()
        row = json.loads(store.raw)["entities"][RESERVE]
        assert row["landed_sem"] is True
        hold.now[0] = 15.5 * MIN
        await hold.settle()
        assert RESERVE in json.loads(store.raw)["entities"]
        assert await hold.write(RESERVE, 80)
        assert _reserve_prior(store) == 0

    async def test_sems_value_for_fifteen_minutes_is_dropped(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")
        await hold.settle()
        hold.now[0] = 20 * MIN + 1
        await hold.settle()
        assert json.loads(store.raw)["entities"] == {}

    async def test_a_restart_keeps_what_shows(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")
        await hold.settle()
        fresh = self._hold(hass, store)
        fresh.now[0] = 19 * MIN                   # 14 min of SEM's value
        assert await fresh.write(RESERVE, 80)
        assert _reserve_prior(store) == 0

    async def test_after_a_restart_sems_value_still_counts_at_fifteen(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")
        await hold.settle()
        late = self._hold(hass, store)
        late.now[0] = 21 * MIN                    # 16 min of SEM's value
        assert await late.write(RESERVE, 80)
        assert _reserve_prior(store) == 100

    async def test_a_restart_keeps_which_value_shows(self):
        """SEM's value shows from 5 min; after a restart the put-back shows
        at 18 min, and SEM's value once more at 22 min: still SEM's."""
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")
        await hold.settle()
        fresh = self._hold(hass, store)            # HA restarts
        fresh.now[0] = 18 * MIN
        hass.put(RESERVE, "0")
        await fresh.settle()
        fresh.now[0] = 22 * MIN
        hass.put(RESERVE, "100")
        assert await fresh.write(RESERVE, 80)
        assert _reserve_prior(store) == 0

    async def test_observe_sends_nothing_and_a_value_set_since_ends_it(self):
        """(review) A value set since ends the memory here too, as in
        ``settle``: kept, a later read of SEM's value would start the time
        again and take the user's own pick for SEM's."""
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        n = len(hass.calls)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")
        await hold.observe(RESERVE)
        assert json.loads(store.raw)["entities"][RESERVE]["landed_sem"] is True
        hass.put(RESERVE, "30")                   # set by hand
        await hold.observe(RESERVE)
        assert json.loads(store.raw)["entities"] == {}
        assert hass.calls[n:] == []

    async def test_observe_ends_a_memory_whose_time_is_up(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 15 * MIN + 1
        await hold.observe(RESERVE)
        assert json.loads(store.raw)["entities"] == {}

    async def test_the_put_back_read_again_starts_its_time_again(self):
        hass, store = _Hass(reserve="0"), _Store()
        hold = await self._landed(hass, store)
        hold.now[0] = 5 * MIN
        hass.put(RESERVE, "100")
        await hold.settle()
        hold.now[0] = 16 * MIN
        hass.put(RESERVE, "0")                    # the cloud caught up
        await hold.settle()
        row = json.loads(store.raw)["entities"][RESERVE]
        assert row.get("landed_sem") is None
        assert row["landed_at"] == 1.7e9 + 16 * MIN
