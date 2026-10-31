"""#1180 — a grid charge left the pack's charge limit lowered.

GoodWe and the generic switch setup wrote SEM's charge target (60 %) into
the ``battery_target_soc_entity`` number when a grid charge started. On
many inverters that number is the pack's standing upper limit. The stop
turned the switch or the mode back and never wrote the old value back, so
the pack stopped at 60 % on sunny days too, until someone set it by hand.

The fix is charge pacing's rule (#949): save the value before the first
write, put it back on the stop, and keep the saved value across a restart.
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    ChargeCommand,
    ChargeCommandStatus,
    GenericChargeAdapter,
    GoodWeChargeAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

TARGET = "number.soc_upper_limit"
SWITCH = "switch.force_charge"
MODE = "select.work_mode"


class _Hass:
    """States the test sets; every call recorded. A number ``takes`` a
    write (its state moves) unless it is told to lag or is unavailable."""

    def __init__(self, target="100"):
        self._states = {TARGET: SimpleNamespace(state=target, attributes={})}
        self.calls: list[tuple] = []
        self.lag = False
        #: non-blocking writes wait in ``queued`` until ``flush()``
        self.delay = False
        self.queued: list[tuple] = []
        self.raise_on = None
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def set(self, entity_id, value):
        self._states[entity_id] = SimpleNamespace(state=str(value), attributes={})

    def read(self, entity_id):
        return self._states[entity_id].state

    async def _call(self, domain, service, data, **kw):
        if self.raise_on == (domain, service):
            raise RuntimeError("bus timeout")
        self.calls.append((domain, service, dict(data)))
        if service == "set_value" and self.delay and not kw.get("blocking"):
            self.queued.append(dict(data))
            return
        self._take(data)

    def _take(self, data):
        ent = data.get("entity_id")
        if (not self.lag and ent in self._states
                and self._states[ent].state not in ("unavailable", "unknown")
                and "value" in data):
            self.set(ent, data["value"])

    def flush(self):
        for data in self.queued:
            self._take(data)
        self.queued = []

    def target_writes(self, entity_id=TARGET):
        return [c[2]["value"] for c in self.calls
                if c[1] == "set_value" and c[2]["entity_id"] == entity_id]


class _Store:
    """The record as Home Assistant keeps it: through JSON."""

    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


def _generic(hass, hold=None):
    cfg = {"battery_force_charge_switch": SWITCH,
           "battery_target_soc_entity": TARGET}
    if hold is not None:
        cfg["charge_target_hold"] = hold
    return GenericChargeAdapter(hass, cfg)


def _goodwe(hass, hold=None):
    cfg = {"inverter_work_mode_entity": MODE,
           "battery_target_soc_entity": TARGET}
    if hold is not None:
        cfg["charge_target_hold"] = hold
    return GoodWeChargeAdapter(hass, cfg)


def _hold(hass, store=None, configured=(TARGET,)):
    """A hold on a clock the test moves: ``hold.now[0]``."""
    hold = ChargeTargetHold(hass, store, configured=configured)
    hold.now = [0.0]
    hold._clock = lambda: hold.now[0]
    return hold


async def _charge(adapter, soc=60.0):
    return await adapter.start_forced_charge(ChargeCommand(target_soc=soc, max_power_w=3000))


@pytest.mark.asyncio
class TestTheStopPutsTheValueBack:

    @pytest.mark.parametrize("make,off", [
        (_generic, ("switch", "turn_off", {"entity_id": SWITCH})),
        (_goodwe, ("select", "select_option", {"entity_id": MODE, "option": "General"})),
    ])
    async def test_reporter_night_60_then_back_to_100(self, make, off):
        hass = _Hass("100")
        adapter = make(hass)
        await _charge(adapter)
        assert hass.read(TARGET) == "60"
        status = await adapter.stop_forced_charge()
        assert status.status is ChargeCommandStatus.IDLE
        assert hass.read(TARGET) == "100"
        # the switch or mode first: a higher target while still forced
        # would charge on from the grid
        assert hass.calls.index(off) < len(hass.calls) - 1
        assert hass.calls[-1] == ("number", "set_value",
                                  {"entity_id": TARGET, "value": 100})

    async def test_every_cycle_rewrites_but_the_first_value_is_kept(self):
        hass = _Hass("100")
        adapter = _generic(hass)
        for soc in (60.0, 60.0, 70.0, 70.0):
            await _charge(adapter, soc)
        await adapter.stop_forced_charge()
        assert hass.target_writes() == [60, 60, 70, 70, 100]

    async def test_the_put_back_goes_out_even_when_the_read_says_it_is_there(self):
        """A short charge: SEM's 60 never read back before the stop. The
        number still reads 100 — the read from BEFORE the write."""
        hass = _Hass("100")
        hass.lag = True
        adapter = _generic(hass)
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert hass.target_writes() == [60, 100]

    async def test_a_stop_with_nothing_held_writes_no_target(self):
        hass = _Hass("100")
        adapter = _generic(hass)
        await adapter.stop_forced_charge()
        assert hass.target_writes() == []
        assert hass.calls == [("switch", "turn_off", {"entity_id": SWITCH})]

    async def test_no_target_configured_writes_none(self):
        hass = _Hass("100")
        adapter = GenericChargeAdapter(hass, {"battery_force_charge_switch": SWITCH})
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert hass.target_writes() == []


@pytest.mark.asyncio
class TestAcrossARestart:

    async def test_restart_mid_charge_puts_back_the_users_value(self):
        """An HA restart never unloads the entry: the number keeps SEM's
        60 and a new lifetime that saved it would keep 60 for good."""
        hass, store = _Hass("100"), _Store()
        first = _generic(hass, ChargeTargetHold(hass, store, configured=(TARGET,)))
        await _charge(first)
        assert hass.read(TARGET) == "60"
        # new lifetime: fresh objects, the same record on disk
        second = _generic(hass, ChargeTargetHold(hass, store, configured=(TARGET,)))
        await _charge(second)                       # still in the block
        await second.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_restart_then_the_boot_stop(self):
        hass, store = _Hass("100"), _Store()
        await _charge(_generic(hass, ChargeTargetHold(hass, store, configured=(TARGET,))))
        second = _generic(hass, ChargeTargetHold(hass, store, configured=(TARGET,)))
        await second.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_the_record_is_written_before_the_number(self):
        hass, store = _Hass("100"), _Store()
        seen = []
        real = hass._call

        async def spy(domain, service, data, **kw):
            if service == "set_value":
                seen.append(json.loads(store.raw))
            await real(domain, service, data, **kw)
        hass.services.async_call = spy
        await _charge(_generic(hass, ChargeTargetHold(hass, store, configured=(TARGET,))))
        assert seen[0]["entities"][TARGET] == {
            "prior": 100.0, "sent": [60.0], "held": True, "pending": False}

    async def test_without_the_record_the_bug_comes_back(self):
        """Vacuity check: a hold with NO store saves SEM's own 60 after the
        restart. The record is what makes the test above pass."""
        hass = _Hass("100")
        await _charge(_generic(hass, ChargeTargetHold(hass, None, configured=(TARGET,))))
        second = _generic(hass, ChargeTargetHold(hass, None, configured=(TARGET,)))
        await _charge(second)
        await second.stop_forced_charge()
        assert hass.read(TARGET) == "60"

    @pytest.mark.parametrize("raw", [
        {"entities": {TARGET: "junk"}}, {"entities": ["junk"]}, ["junk"]])
    async def test_a_damaged_record_means_no_target_write(self, raw):
        """It may have held SEM's 60: the number cannot be trusted."""
        hass, store = _Hass("60"), _Store()
        store.raw = json.dumps(raw)
        adapter = _generic(hass, _hold(hass, store))
        status = await _charge(adapter, 70.0)
        assert status.status is ChargeCommandStatus.CHARGING
        assert hass.target_writes() == []

    async def test_an_empty_record_is_no_record(self):
        hass, store = _Hass("100"), _Store()
        store.raw = json.dumps({"entities": {}})
        adapter = _generic(hass, _hold(hass, store))
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert hass.target_writes() == [60, 100]

    async def test_a_value_the_user_set_while_sem_was_down_is_kept(self):
        """Review 2: held at the restart, the user moved it meanwhile."""
        hass, store = _Hass("100"), _Store()
        await _charge(_generic(hass, _hold(hass, store)))
        hass.set(TARGET, "90")                      # set by hand, SEM down
        second = _generic(hass, _hold(hass, store))
        await _charge(second)
        await second.stop_forced_charge()
        assert hass.read(TARGET) == "90"

    async def test_a_target_setting_that_moved_gets_its_value_back(self):
        """The user repointed the target while SEM's 60 sat on the old one."""
        hass, store = _Hass("100"), _Store()
        await _charge(_generic(hass, ChargeTargetHold(hass, store, configured=(TARGET,))))
        assert hass.read(TARGET) == "60"
        hold = _hold(hass, store, configured=("number.other",))
        await hold.settle()
        assert hass.read(TARGET) == "100"


@pytest.mark.asyncio
class TestNeverWriteWhatCannotBePutBack:

    @pytest.mark.parametrize("state", ["unavailable", "unknown", "abc"])
    async def test_unreadable_number_is_not_written_the_charge_goes_on(self, state):
        hass = _Hass(state)
        adapter = _generic(hass)
        status = await _charge(adapter)
        assert status.status is ChargeCommandStatus.CHARGING
        assert ("switch", "turn_on", {"entity_id": SWITCH}) in hass.calls
        assert hass.target_writes() == []
        # it becomes readable: the next cycle saves it and writes
        hass.set(TARGET, "100")
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert hass.target_writes() == [60, 100]

    async def test_missing_number_is_not_written(self):
        hass = _Hass("100")
        adapter = GenericChargeAdapter(hass, {
            "battery_force_charge_switch": SWITCH,
            "battery_target_soc_entity": "number.gone"})
        await _charge(adapter)
        assert hass.target_writes("number.gone") == []


@pytest.mark.asyncio
class TestThePutBackLands:
    """A put-back is done when a read shows it, not when it is sent."""

    async def test_unavailable_at_the_stop_goes_once_it_can_be_read(self):
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        await _charge(adapter)
        hass.set(TARGET, "unavailable")
        status = await adapter.stop_forced_charge()
        # the stop itself landed: it is not sent again for the target
        assert status.status is ChargeCommandStatus.IDLE
        assert hass.target_writes() == [60]
        assert hold.snapshot()[TARGET]["pending"] is True
        await hold.settle()                         # still unreadable
        assert hass.target_writes() == [60]
        hass.set(TARGET, "60")
        await hold.settle()                         # never sent: goes at once
        assert hass.target_writes() == [60, 100]
        await hold.settle()                         # reads 100: done
        assert hold.snapshot() == {}
        await hold.settle()
        assert hass.target_writes() == [60, 100]

    async def test_a_raising_put_back_is_sent_again(self):
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        await _charge(adapter)
        hass.raise_on = ("number", "set_value")
        status = await adapter.stop_forced_charge()
        assert status.status is ChargeCommandStatus.IDLE
        assert hold.snapshot()[TARGET]["pending"] is True
        hass.raise_on = None
        hold.now[0] = ChargeTargetHold.RETRY_S - 1
        await hold.settle()
        assert hass.read(TARGET) == "60"
        hold.now[0] = ChargeTargetHold.RETRY_S
        await hold.settle()
        assert hass.read(TARGET) == "100"

    async def test_the_put_back_is_sent_blocking(self):
        """Non-blocking, a refused write is only in HA's log."""
        hass = _Hass("100")
        seen = []
        real = hass._call

        async def spy(domain, service, data, **kw):
            seen.append((data.get("value"), kw.get("blocking")))
            await real(domain, service, data, **kw)
        hass.services.async_call = spy
        adapter = _generic(hass)
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert (100, True) in seen

    async def test_a_dropped_put_back_is_sent_again_then_said(self, caplog):
        """The number never takes it (a GoodWe UDP write lost). Sent
        again ``MAX_TRIES`` times, ``RETRY_S`` apart, then a warning."""
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        await _charge(adapter)
        hass.lag = True                             # writes go, never read
        await adapter.stop_forced_charge()
        for i in range(1, 6):
            hold.now[0] = i * ChargeTargetHold.RETRY_S
            await hold.settle()
        assert hass.target_writes() == [60] + [100] * ChargeTargetHold.MAX_TRIES
        assert "set it back by hand" in caplog.text

    async def test_a_new_charge_takes_a_pending_number_over(self):
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        await _charge(adapter)
        hass.set(TARGET, "unavailable")
        await adapter.stop_forced_charge()
        hass.set(TARGET, "60")
        await _charge(adapter, 70.0)               # the next block
        snap = hold.snapshot()[TARGET]
        assert (snap["saved"], snap["held"], snap["pending"]) == (100.0, True, False)
        await adapter.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_a_failed_start_gives_the_value_back_after_the_block(self):
        """The switch call raised after the target went out. No charge, so
        no stop will come: the value goes back on the next cycle without a
        forced charge — not during the block, where it would flip."""
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        hass.raise_on = ("switch", "turn_on")
        status = await _charge(adapter)
        assert status.status is ChargeCommandStatus.FAILED
        assert hass.read(TARGET) == "60"
        assert hold.snapshot()[TARGET]["pending"] is True
        await _charge(adapter)                      # the block retries
        assert hass.target_writes() == [60, 60]
        hass.raise_on = None
        await hold.settle()                         # out of the block: waits
        assert hass.read(TARGET) == "60"
        hold.now[0] = ChargeTargetHold.RETRY_S
        await hold.settle()
        assert hass.read(TARGET) == "100"

    async def test_a_read_from_before_the_write_does_not_end_a_failed_start(self):
        """Review 2, MEDIUM: the target write is non-blocking. Right after a
        failed start the number still reads 100 — from before SEM's 60
        lands. That read must not end it: SEM's 60 would then stay, and the
        next start would save it as the user's."""
        hass = _Hass("100")
        hass.delay = True
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        hass.raise_on = ("switch", "turn_on")
        await _charge(adapter)
        hass.raise_on = None
        await hold.settle()                         # reads 100: not proof
        hass.flush()                                # SEM's 60 lands
        hold.now[0] = ChargeTargetHold.RETRY_S
        await hold.settle()                         # sent once, blocking
        await hold.settle()                         # reads 100: landed
        assert hass.read(TARGET) == "100"
        assert hold.snapshot() == {}

    async def test_a_failing_pack_and_a_normal_pack_do_not_flip_the_number(self):
        """Review 2: b1's switch fails all block, b2 runs NORMAL beside it.
        b2's cycle must not put the value back between b1's retries."""
        hass = _Hass("100")
        hold = _hold(hass)
        b1 = _generic(hass, hold)
        hass.raise_on = ("switch", "turn_on")
        for i in range(10):
            hold.now[0] = i * 10.0
            await _charge(b1)
            await hold.settle()                     # b2's NORMAL cycle
        assert hass.target_writes() == [60] * 10


@pytest.mark.asyncio
class TestOwnEcho:

    async def test_a_number_still_showing_sems_value_is_not_the_users(self):
        """Stop, then a new start before the integration read the number
        back: it still shows SEM's 60 (class 95)."""
        hass = _Hass("100")
        adapter = _generic(hass)
        await _charge(adapter)
        hass.lag = True
        await adapter.stop_forced_charge()          # 100 sent, still reads 60
        assert hass.read(TARGET) == "60"
        hass.lag = False
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_every_value_sem_wrote_is_its_own_not_only_the_last(self):
        """Review, HIGH: the target rose 60 → 70 in one charge. A restart
        before the number read back the put-back: it still shows 60."""
        hass, store = _Hass("100"), _Store()
        first = _generic(hass, _hold(hass, store))
        await _charge(first, 60.0)
        await _charge(first, 70.0)
        hass.lag = True
        await first.stop_forced_charge()
        hass.set(TARGET, "60")                      # an old read
        hass.lag = False
        second = _generic(hass, _hold(hass, store))
        await _charge(second, 50.0)
        await second.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_two_packs_asking_two_values(self):
        hass = _Hass("90")                          # the user's limit
        hold = _hold(hass)
        b1, b2 = _generic(hass, hold), _generic(hass, hold)
        await _charge(b1, 100.0)                    # a manual Force charge
        await _charge(b2, 60.0)                     # the plan
        hass.lag = True
        await b1.stop_forced_charge()
        await b2.stop_forced_charge()
        hass.set(TARGET, "100")
        hass.lag = False
        await _charge(b2, 60.0)                     # reads b1's 100: SEM's
        await b2.stop_forced_charge()
        assert hass.read(TARGET) == "90"

    async def test_an_inverter_that_rounds_sems_value_still_shows_sems(self):
        hass = _Hass("100")
        hass._states[TARGET].attributes = {"step": 5}
        adapter = _generic(hass)
        await _charge(adapter, 62.0)
        hass.set(TARGET, "60")                      # the inverter's step
        hass._states[TARGET].attributes = {"step": 5}
        hass.lag = True
        await adapter.stop_forced_charge()
        hass.lag = False
        await _charge(adapter, 62.0)
        await adapter.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_a_value_the_user_changed_is_saved(self):
        hass = _Hass("100")
        adapter = _generic(hass)
        await _charge(adapter)
        await adapter.stop_forced_charge()
        hass.set(TARGET, "90")                      # the user's new limit
        await _charge(adapter)
        await adapter.stop_forced_charge()
        assert hass.read(TARGET) == "90"

    async def test_once_the_put_back_landed_sems_old_value_is_the_users(self):
        """Review, MEDIUM: SEM charged to 80. Days later the user sets 80
        on purpose. That is their value now, not SEM's echo."""
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        await _charge(adapter, 80.0)
        await adapter.stop_forced_charge()
        await hold.settle()                         # reads 100: landed
        hass.set(TARGET, "80")                      # the user's choice
        await _charge(adapter, 60.0)
        await adapter.stop_forced_charge()
        assert hass.read(TARGET) == "80"

    async def test_a_user_value_while_pending_ends_it(self):
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = _generic(hass, hold)
        await _charge(adapter)
        hass.lag = True
        await adapter.stop_forced_charge()
        hass.set(TARGET, "95")                      # set by hand meanwhile
        hold.now[0] = 10 * ChargeTargetHold.RETRY_S
        await hold.settle()
        assert hass.read(TARGET) == "95"
        assert hold.snapshot() == {}


@pytest.mark.asyncio
class TestTwoPacksOneNumber:

    async def test_the_second_pack_does_not_save_the_first_ones_60(self):
        """No per-battery target list: two packs behind one inverter write
        the same number. One hold for the entry, keyed by the number."""
        hass = _Hass("100")
        hold = _hold(hass)
        b1, b2 = _generic(hass, hold), _generic(hass, hold)
        await _charge(b1)
        await _charge(b2)                           # reads b1's 60
        await b1.stop_forced_charge()
        await b2.stop_forced_charge()
        assert hass.read(TARGET) == "100"

    async def test_one_hold_per_pack_would_leave_60(self):
        """Vacuity check for the test above."""
        hass = _Hass("100")
        b1, b2 = _generic(hass), _generic(hass)
        await _charge(b1)
        await _charge(b2)
        await b1.stop_forced_charge()
        await b2.stop_forced_charge()
        assert hass.read(TARGET) == "60"


@pytest.mark.asyncio
class TestTheRecordFailsClosed:

    async def test_a_record_that_cannot_be_read_means_no_target_write(self):
        class _Broken(_Store):
            async def async_load(self):
                raise ValueError("corrupt")
        hass = _Hass("60")                          # maybe SEM's own
        adapter = _generic(hass, _hold(hass, _Broken()))
        status = await _charge(adapter, 70.0)
        assert status.status is ChargeCommandStatus.CHARGING
        assert hass.target_writes() == []

    async def test_a_record_that_cannot_be_saved_means_no_target_write(self):
        class _Full(_Store):
            async def async_save(self, data):
                raise OSError("disk full")
        hass = _Hass("100")
        hold = _hold(hass, _Full())
        adapter = _generic(hass, hold)
        await _charge(adapter)
        assert hass.target_writes() == []
        assert hold.snapshot() == {}

    @pytest.mark.parametrize("stop_first", [True, False])
    async def test_a_record_with_a_lost_value_writes_nothing_over_sems_own(
            self, stop_first):
        hass, store = _Hass("60"), _Store()
        store.raw = json.dumps({"entities": {TARGET: {
            "prior": None, "sent": [60], "held": True, "pending": False}}})
        hold = _hold(hass, store)
        adapter = _generic(hass, hold)
        if stop_first:
            await adapter.stop_forced_charge()      # nothing known to put back
            await hold.settle()
        await _charge(adapter, 70.0)
        assert hass.target_writes() == []

    async def test_saves_only_when_something_new_happens(self):
        """Review, MEDIUM: two packs asking 100 and 60 saved the record on
        every cycle, all night."""
        class _Counting(_Store):
            saves = 0

            async def async_save(self, data):
                _Counting.saves += 1
                await super().async_save(data)
        hass = _Hass("100")
        hold = _hold(hass, _Counting())
        b1, b2 = _generic(hass, hold), _generic(hass, hold)
        for _ in range(50):
            await _charge(b1, 100.0)
            await _charge(b2, 60.0)
        assert _Counting.saves == 2                 # the save, then 60 joins


@pytest.mark.asyncio
class TestTheCycleSettlesAPutBack:

    def _adapter(self, hass, hold):
        return GenericBatteryAdapter(hass, {
            "battery_force_charge_switch": SWITCH,
            "battery_target_soc_entity": TARGET,
            "charge_target_hold": hold,
        })

    async def _pending(self):
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = self._adapter(hass, hold)
        await adapter._charge_adapter.start_forced_charge(
            ChargeCommand(target_soc=60.0, max_power_w=3000))
        hass.set(TARGET, "unavailable")
        await adapter._charge_adapter.stop_forced_charge()
        hass.set(TARGET, "60")
        return hass, hold, adapter

    @pytest.mark.parametrize("intent", [
        BatteryIntent.NORMAL, BatteryIntent.STOP_FORCE_CHARGE, BatteryIntent.OFF,
        BatteryIntent.LIMIT_DISCHARGE])
    async def test_a_cycle_without_a_charge_puts_it_back(self, intent):
        hass, hold, adapter = await self._pending()
        await actuate_battery(BatteryDecision(battery_id="b1", intent=intent,
                                              discharge_limit_w=1000.0), adapter)
        assert hass.read(TARGET) == "100"

    async def test_observer_writes_nothing(self):
        hass, hold, adapter = await self._pending()
        await actuate_battery(BatteryDecision(battery_id="b1", intent=BatteryIntent.NORMAL),
                              adapter, observer=True)
        assert hass.read(TARGET) == "60"

    async def test_a_charge_cycle_takes_the_number_over_instead(self):
        hass, hold, adapter = await self._pending()
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_CHARGE, target_soc=60.0,
            charge_power_w=3000.0, duration_min=60), adapter)
        assert hass.target_writes() == [60, 60]
        assert hold.snapshot()[TARGET]["held"] is True

    async def test_the_stop_cycle_turns_the_switch_off_before_the_value_goes(self):
        hass = _Hass("100")
        hold = _hold(hass)
        adapter = self._adapter(hass, hold)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_CHARGE, target_soc=60.0,
            charge_power_w=3000.0, duration_min=60), adapter)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.STOP_FORCE_CHARGE), adapter)
        off = hass.calls.index(("switch", "turn_off", {"entity_id": SWITCH}))
        back = hass.calls.index(("number", "set_value",
                                 {"entity_id": TARGET, "value": 100}))
        assert off < back
        assert hass.read(TARGET) == "100"

    async def test_no_switch_no_put_back_of_another_adapters_value(self):
        """Review, LOW: a GoodWe install on the generic fallback at boot.
        Its stop with no switch must not hand the value back while the
        GoodWe charge may still run."""
        hass, store = _Hass("100"), _Store()
        await _charge(_goodwe(hass, _hold(hass, store)))
        fallback = GenericChargeAdapter(hass, {
            "battery_target_soc_entity": TARGET,
            "charge_target_hold": _hold(hass, store)})
        await fallback.stop_forced_charge()
        assert hass.read(TARGET) == "60"


class _FakeStore:
    made: list = []

    def __init__(self, hass, version, key):
        self.key = key
        _FakeStore.made.append(key)


class TestCoordinatorWiring:

    def _coordinator(self, config, entry_id="entry-1"):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator(MagicMock(), config)
        coord.hass = MagicMock()
        coord.config_entry = SimpleNamespace(entry_id=entry_id)
        return coord

    def test_every_battery_gets_the_one_hold_of_the_entry(self):
        _FakeStore.made = []
        with patch("homeassistant.helpers.storage.Store", _FakeStore):
            coord = self._coordinator({"battery_target_soc_entity": TARGET})
            a = coord._battery_adapter_context("b1", 0, 2)["charge_target_hold"]
            b = coord._battery_adapter_context("b2", 1, 2)["charge_target_hold"]
        assert isinstance(a, ChargeTargetHold) and a is b
        assert a._store.key == "sem.charge_target.entry-1"
        assert a._configured == {TARGET}
        # one hold for both (#1181 adds the record's own store beside it)
        assert _FakeStore.made.count("sem.charge_target.entry-1") == 1

    def test_no_entry_no_record(self):
        coord = self._coordinator({}, entry_id="")
        assert coord._battery_adapter_context("b1")["charge_target_hold"]._store is None

    def test_the_adapters_take_the_injected_hold(self):
        hold = ChargeTargetHold(MagicMock())
        for make in (_generic, _goodwe):
            assert make(MagicMock(), hold).target_hold is hold

    def test_every_battery_adapter_is_built_from_the_context(self):
        """The self-heal rebuild used the bare per-battery config, so an
        upgraded adapter had no record: a restart then saved SEM's 60."""
        import ast
        from pathlib import Path
        src = (Path(__file__).resolve().parent.parent
               / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        bad, found = [], 0
        for n in ast.walk(ast.parse(src)):
            if (isinstance(n, ast.Call) and getattr(n.func, "id", "") == "adapter_for"
                    and len(n.args) == 2):
                arg = n.args[1]
                ok = (isinstance(arg, ast.Name) and arg.id == "_pbc") or (
                    isinstance(arg, ast.Call)
                    and getattr(arg.func, "attr", "") == "_battery_adapter_context")
                found += 1
                if not ok:
                    bad.append(n.lineno)
        assert found >= 2, "the battery adapter builds were not found"
        assert not bad, f"battery adapter built without its context at {bad}"

    def test_the_record_goes_on_removal(self):
        from custom_components.solar_energy_management import cleanup
        assert "sem.charge_target.e1" in cleanup.per_entry_store_keys("e1")
