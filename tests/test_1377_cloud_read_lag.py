"""#1377 — a cloud read that shows the old values for minutes ends no charge.

The reporter's History, 23.11.2026 (Tesla Powerwall through Tesla Fleet,
which polls the site every 60 s and shows a write at once):

* 20:00:05 SEM set the reserve to 100, "allow grid charging" on, the mode
  to ``autonomous``;
* 20:05:06 one poll showed all three old values, in the same millisecond
  (a poll, not a write: SEM writes the reserve first and waits for it);
* 20:16:06 the next change, again one poll: mode ``autonomous`` and the
  permit on — SEM's values, with no write from anyone in between.

SEM read the 20:05 poll as "the mode went back by itself", gave the charge
up at once, put the reserve back to 0 five minutes later and dropped its
record of the mode and the permit. At 21:30 the pack sat in ``autonomous``
with grid charging on and the reserve at 0 %: no charge, and not the
user's settings either. A forum report of the same integration: the
settings "revert to their prior values and then change to the desired
values over an hour later".

The rules pinned here (``AWAY_FOR_S``, ``SHOW_WITHIN_S``):

* a select or permit that showed SEM's value and reads the value it had
  BEFORE SEM's write ends the charge only once it has read so for 15
  minutes; a read of SEM's value again goes on; nothing is written while
  it waits. Any other value is a change made since and ends it at once;
* a charge that ends while the select or permit reads its old value sends
  that value once: SEM's own write may still be on its way;
* a select SEM wrote has 60 s to show it, then one re-send, then 60 s more.

The same rules hold for the hold select (#1362).
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    force_charge,
    hold_select,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_select import (
    AWAY_FOR_S,
    SHOW_WITHIN_S,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    GenericChargeAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.hold_select import (
    SelectHold,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
)

from .test_1362_hold_by_select import (
    MODE as HOLD_MODE, SBU, SOLAR, UTILITY, _adapter as _hold_adapter,
    _Hass as _HoldHass, _limit,
)
from .test_1377_powerwall_charge import (
    MODE, PERMIT, RESERVE, _adapter, _charge, _Hass, _stop, _Store,
)

CYCLE_S = 10.0


class _Clock:
    """One clock for the charge path, the hold select and the reserve hold."""

    def __init__(self, monkeypatch):
        self.t = 1000.0
        fake = SimpleNamespace(monotonic=lambda: self.t, time=lambda: 1.7e9 + self.t)
        monkeypatch.setattr(force_charge, "time", fake)
        monkeypatch.setattr(hold_select, "time", fake)


@pytest.fixture
def clock(monkeypatch):
    # the real numbers, whatever another module's fixture left
    monkeypatch.setattr(GenericChargeAdapter, "AWAY_FOR_S", AWAY_FOR_S)
    monkeypatch.setattr(GenericChargeAdapter, "SHOW_WITHIN_S", SHOW_WITHIN_S)
    monkeypatch.setattr(SelectHold, "AWAY_FOR_S", AWAY_FOR_S)
    monkeypatch.setattr(SelectHold, "SHOW_WITHIN_S", SHOW_WITHIN_S)
    monkeypatch.setattr(SelectHold, "MIN_HOLD_S", 0.0)
    return _Clock(monkeypatch)


def _poll(hass, mode, permit, reserve):
    """One Tesla Fleet poll: all three change at once, nothing is written."""
    hass.put(MODE, mode)
    hass.put(PERMIT, permit)
    hass.put(RESERVE, reserve)


async def _cycles(a, clock, seconds, decision=None):
    for _ in range(int(seconds // CYCLE_S)):
        clock.t += CYCLE_S
        await actuate_battery(decision or _charge(), a)


class TestTheReportersEvening:
    async def test_the_old_values_for_eleven_minutes_end_no_charge(self, clock):
        hass, hold = _Hass(reserve="0"), _Store()
        a = _adapter(hass, _Store(), hold)
        await actuate_battery(_charge(), a)                       # 20:00:05
        assert (hass.read(MODE), hass.read(PERMIT), hass.read(RESERVE)) == (
            "autonomous", "on", "100")
        await _cycles(a, clock, 300)                              # to 20:05
        n = len(hass.calls)
        _poll(hass, "self_consumption", "off", "0")               # 20:05:06
        await _cycles(a, clock, 11 * 60)                          # to 20:16
        assert hass.calls[n:] == [], "nothing written while the cloud lags"
        assert a.charge_refused is False, "the plan keeps the charge"
        assert a.last_intent is BatteryIntent.FORCE_CHARGE
        assert json.loads(hold.raw)["entities"][RESERVE]["held"] is True
        _poll(hass, "autonomous", "on", "100")                    # 20:16:06
        await _cycles(a, clock, 30 * 60)
        assert hass.calls[n:] == []
        assert a.charge_refused is False
        assert a.last_intent is BatteryIntent.FORCE_CHARGE
        assert a.last_error is None
        await actuate_battery(_stop(), a)                         # the block ends
        assert (hass.read(MODE), hass.read(PERMIT), hass.read(RESERVE)) == (
            "self_consumption", "off", "0")

    async def test_a_poll_that_shows_on_again_starts_the_wait_again(self, clock):
        hass = _Hass(reserve="0")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 60)
        for _ in range(3):                    # 10 min old, 1 min SEM's, ×3
            _poll(hass, "self_consumption", "off", "0")
            await _cycles(a, clock, 10 * 60)
            _poll(hass, "autonomous", "on", "100")
            await _cycles(a, clock, 60)
        assert a.charge_refused is False
        assert a.last_intent is BatteryIntent.FORCE_CHARGE


class TestTheWaitEnds:
    async def test_the_old_values_past_fifteen_minutes_end_the_charge(self, clock):
        hass, hold = _Hass(reserve="0"), _Store()
        a = _adapter(hass, _Store(), hold)
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 60)
        n = len(hass.calls)
        _poll(hass, "self_consumption", "off", "0")
        await _cycles(a, clock, AWAY_FOR_S - 30)
        assert a.charge_refused is False and hass.calls[n:] == []
        await _cycles(a, clock, 60)
        assert a.charge_refused is True
        assert "by itself" in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE
        # the old mode and "off" go out ONCE: SEM's own writes may still be
        # on their way and would land later with no one to put them back
        sent = [(c[1], c[2].get("option")) for c in hass.calls[n:]]
        assert sent == [("select_option", "self_consumption"),
                        ("turn_off", None)]
        assert json.loads(hold.raw)["entities"][RESERVE]["pending"] is True
        await _cycles(a, clock, 30 * 60)
        assert len(hass.calls) == n + 2, "once, not every cycle"

    async def test_a_value_set_since_ends_the_charge_at_once(self, clock):
        hass = _Hass(reserve="0")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 60)
        n = len(hass.writes("select"))
        hass.put(MODE, "backup")                  # the user's own choice
        await _cycles(a, clock, CYCLE_S)
        assert a.charge_refused is True and "by itself" in a.last_error
        assert len(hass.writes("select")) == n, "a hand choice is never written over"
        assert hass.read(MODE) == "backup"
        assert hass.read(PERMIT) == "off"

    async def test_a_hand_change_to_the_old_mode_waits_then_ends(self, clock):
        """The cost of the wait: the old mode set by hand is the cloud's old
        value too. SEM writes nothing for 15 minutes, then ends the charge."""
        hass = _Hass(reserve="0")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 60)
        n = len(hass.writes("select"))
        hass.put(MODE, "self_consumption")
        await _cycles(a, clock, AWAY_FOR_S + 30)
        assert a.charge_refused is True
        assert [c[2]["option"] for c in hass.writes("select")[n:]] == [
            "self_consumption"]                   # its own value, once
        assert hass.read(MODE) == "self_consumption"


class TestThePermit:
    """The mode already showed ``autonomous`` (the join): only the reserve
    and the permit are SEM's, and the permit is what a poll turns back."""

    async def test_a_permit_shown_on_then_off_for_minutes_is_not_given_up(self, clock):
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 60)                # it reads on: it took
        n = len(hass.calls)
        hass.put(PERMIT, "off")
        await _cycles(a, clock, 10 * 60)
        assert hass.calls[n:] == [], "no re-send while the cloud lags"
        assert a.charge_refused is False
        hass.put(PERMIT, "on")
        await _cycles(a, clock, 60)
        assert a.charge_refused is False
        assert a.last_intent is BatteryIntent.FORCE_CHARGE

    async def test_a_permit_off_past_the_wait_ends_the_charge(self, clock):
        hass = _Hass(mode="autonomous", reserve="0")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 60)
        n = len(hass.calls)
        hass.put(PERMIT, "off")
        await _cycles(a, clock, AWAY_FOR_S + 30)
        assert a.charge_refused is True
        assert "went back to off by itself" in a.last_error
        assert float(hass.read(RESERVE)) == 0, "the reserve went back"
        assert hass.writes("select") == [], "the mode was the user's"
        assert [c[1] for c in hass.writes("switch")[0:]].count("turn_on") == 1
        assert ("switch", "turn_off", {"entity_id": PERMIT}) in hass.calls[n:]

    async def test_a_permit_that_never_shows_on_keeps_its_minute(self, clock):
        hass = _Hass(mode="autonomous", reserve="0")
        hass.refuse_permit = True
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 90)
        assert a.charge_refused is True
        assert "did not turn on" in a.last_error


class TestTheSelectGetsAMinuteToShowIt:
    async def test_a_select_that_shows_the_write_late_gets_one_write(self, clock):
        hass = _Hass(reserve="0")
        hass.refuse_mode = True                   # not shown until the next poll
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 50)
        hass.put(MODE, "autonomous")              # the poll shows it
        await _cycles(a, clock, 60)
        assert len(hass.writes("select")) == 1
        assert a.charge_refused is False
        assert a.last_intent is BatteryIntent.FORCE_CHARGE

    async def test_a_select_that_never_shows_it_is_sent_twice_a_minute_apart(self, clock):
        hass = _Hass(reserve="0")
        hass.refuse_mode = True
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await _cycles(a, clock, 50)
        assert len(hass.writes("select")) == 1, "no re-send within the minute"
        await _cycles(a, clock, 20)
        assert len(hass.writes("select")) == 2, "the one re-send"
        assert a.charge_refused is False
        await _cycles(a, clock, 60)
        assert a.charge_refused is True and "did not take" in a.last_error
        assert [c[2]["option"] for c in hass.writes("select")] == [
            "autonomous", "autonomous", "self_consumption"]
        assert hass.read(PERMIT) == "off"


# ── the hold select (#1362): the same two rules ─────────────────────────
class TestTheHoldSelect:
    async def test_the_old_option_for_minutes_keeps_the_hold(self, clock):
        hass = _HoldHass()
        a = _hold_adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await _cycles(a, clock, 60, _limit(0.0))      # shown: SEM's hold
        hass.put(HOLD_MODE, SBU)                      # a poll shows the old one
        await _cycles(a, clock, 10 * 60, _limit(0.0))
        assert hass.writes() == [UTILITY], "nothing written while it lags"
        assert a.hold_active is True
        hass.put(HOLD_MODE, UTILITY)
        await _cycles(a, clock, 60, _limit(0.0))
        assert hass.writes() == [UTILITY] and a.hold_active is True
        assert not (a.last_error and "by itself" in a.last_error)

    async def test_past_the_wait_it_ends_and_the_old_option_goes_out_once(self, clock):
        hass = _HoldHass()
        a = _hold_adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await _cycles(a, clock, 60, _limit(0.0))
        hass.put(HOLD_MODE, SBU)
        await _cycles(a, clock, AWAY_FOR_S + 30, _limit(0.0))
        assert "by itself" in a.last_error
        assert hass.writes() == [UTILITY, SBU]

    async def test_another_option_ends_it_at_once_and_is_left(self, clock):
        hass = _HoldHass()
        a = _hold_adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await _cycles(a, clock, 60, _limit(0.0))
        hass.put(HOLD_MODE, SOLAR)                    # set by hand
        await _cycles(a, clock, CYCLE_S, _limit(0.0))
        assert "by itself" in a.last_error
        assert hass.writes() == [UTILITY]
        assert hass.read(HOLD_MODE) == SOLAR
