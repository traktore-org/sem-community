"""#1362 — a battery HELD through a select, for a dearer hour.

@matekogon, two batteries behind one inverter, controlled only through the
DESS Monitor integration: a MODE select (SBU / Solar / Utility; Utility runs
the loads from the grid and the battery rests) and a charge-source select.
There is no discharge-limit number, so SEM could not keep the pack for the
expensive hours. Two settings, the select and its hold option; with either
unset nothing changes. SEM holds only for a 0 W decision (a select cannot cap
at 500 W), keeps the option the select showed BEFORE the write, and puts it
back on normal, on Off, on unload and after a restart. A choice made by hand
is left alone.
"""
from __future__ import annotations

import json
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    hold_select,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    async_release_batteries_on_unload,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.hold_select import (
    SelectHold,
    hold_setup,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.price_view import PriceView
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    sink_verdicts,
)
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)

MODE = "select.dess_output_mode"
SOURCE = "select.dess_charge_source"
SBU, SOLAR, UTILITY = "SBU", "Solar", "Utility"
MODES = [SBU, SOLAR, UTILITY]
MAINS, SOLAR_ONLY = "Solar and mains", "Solar only"
SOURCES = [SOLAR_ONLY, MAINS]


class _Hass:
    """The DESS Monitor shape: two selects, each write lands, every call kept."""

    def __init__(self, mode=SBU, source=SOLAR_ONLY):
        self._states = {
            MODE: SimpleNamespace(state=mode, attributes={"options": list(MODES)}),
            SOURCE: SimpleNamespace(state=source, attributes={"options": list(SOURCES)}),
        }
        self.calls: list[tuple] = []
        self.raise_on = False
        self.refuse = False          # the call succeeds, the select stays
        self.on_write = None         # a hook run at the moment of a write
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def put(self, entity, value, options=None):
        old = self._states[entity]
        self._states[entity] = SimpleNamespace(
            state=value, attributes={"options": options if options is not None
                                     else old.attributes["options"]})

    def read(self, entity=MODE):
        return self._states[entity].state

    async def _call(self, domain, service, data, **kw):
        if self.raise_on:
            raise RuntimeError("bus timeout")
        if self.on_write:
            self.on_write(data)
        self.calls.append((domain, service, dict(data)))
        if service == "select_option" and not self.refuse:
            self.put(data["entity_id"], data["option"])

    def writes(self, entity=None):
        return [c[2]["option"] for c in self.calls if c[1] == "select_option"
                and (entity is None or c[2]["entity_id"] == entity)]


class _Store:
    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


@pytest.fixture(autouse=True)
def _no_dwell(monkeypatch):
    monkeypatch.setattr(SelectHold, "MIN_HOLD_S", 0.0)
    monkeypatch.setattr(SelectHold, "SHOW_WITHIN_S", 0.0)


def _adapter(hass, store=None, bid="b1", charge=False, **extra):
    cfg = {"battery_hold_select_entity": MODE,
           "battery_hold_select_option": UTILITY,
           "battery_hold_record": ForcedChargeRecord(store or _Store()),
           "battery_id": bid, **extra}
    if charge:
        cfg.update({"battery_charge_select_entity": SOURCE,
                    "battery_charge_select_option": MAINS,
                    "forced_charge_record": ForcedChargeRecord(_Store())})
    return GenericBatteryAdapter(hass, cfg)


def _limit(watts, bid="b1"):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.LIMIT_DISCHARGE,
                           discharge_limit_w=watts)


def _normal(bid="b1"):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.NORMAL)


def _charge(bid="b1"):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=80.0, charge_power_w=3000.0, duration_min=60)


# ── asleep ──────────────────────────────────────────────────────────────
class TestAsleep:
    def test_the_setup_needs_both_and_never_the_charge_select(self):
        assert hold_setup({}) is None
        assert hold_setup({"battery_hold_select_entity": MODE}) is None
        assert hold_setup({"battery_hold_select_option": UTILITY}) is None
        assert hold_setup({"battery_hold_select_entity": MODE,
                           "battery_hold_select_option": UTILITY}) == (MODE, UTILITY)
        # one entity, two meanings: the charge select is never the hold select
        assert hold_setup({"battery_hold_select_entity": SOURCE,
                           "battery_hold_select_option": UTILITY,
                           "battery_charge_select_entity": SOURCE}) is None

    async def test_without_the_pair_a_zero_limit_writes_nothing_and_says_so(self):
        hass = _Hass()
        a = GenericBatteryAdapter(hass, {"battery_id": "b1"})
        await actuate_battery(_limit(0.0), a)
        assert hass.calls == []
        assert a.last_error == a.NO_DISCHARGE_LIMIT_ERROR

    async def test_a_discharge_limit_number_keeps_its_own_path(self):
        hass = _Hass()
        a = _adapter(hass, battery_discharge_control_entity="number.limit")
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == []


# ── hold ────────────────────────────────────────────────────────────────
class TestHold:
    async def test_zero_watts_sets_the_hold_option_once(self):
        hass = _Hass()
        a = _adapter(hass)
        for _ in range(3):
            await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY]
        assert a.last_intent is BatteryIntent.LIMIT_DISCHARGE
        assert a.last_discharge_limit_w == 0.0 and a.last_error is None
        assert a.hold_active is True

    async def test_the_prior_option_is_on_disk_before_the_write(self):
        hass, store = _Hass(), _Store()
        seen = []
        hass.on_write = lambda d: seen.append(store.raw)
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        assert seen and '"SBU"' in seen[0] and MODE in seen[0]

    async def test_no_write_goes_out_when_the_record_cannot_be_saved(self):
        class _Bad(_Store):
            async def async_save(self, data):
                raise OSError("disk full")
        hass = _Hass()
        a = _adapter(hass, _Bad())
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == []
        assert "record" in a.last_error

    async def test_a_partial_limit_is_not_a_hold_and_is_said(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(500.0), a)
        assert hass.writes() == []
        assert a.last_error == a.NO_PARTIAL_HOLD_ERROR
        assert a.last_discharge_limit_w == -1.0       # no cap is in force

    async def test_a_partial_limit_releases_a_hold(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_limit(750.0), a)
        assert hass.writes() == [UTILITY, SBU]
        assert a.last_discharge_limit_w == -1.0 and a.hold_active is False

    async def test_a_select_already_showing_the_option_is_the_users_and_never_put_back(self):
        hass = _Hass(mode=UTILITY)
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_normal(), a)
        assert hass.writes() == [] and hass.read() == UTILITY

    async def test_a_select_that_does_not_list_the_option_is_not_written(self):
        hass = _Hass()
        a = _adapter(hass, battery_hold_select_option="Grid first")
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == []
        assert "does not list" in a.last_error

    async def test_an_unavailable_select_is_not_written(self):
        hass = _Hass(mode="unavailable")
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == []
        assert "unavailable" in a.last_error

    async def test_a_select_that_ignores_the_write_gets_two_tries_then_is_refused(self):
        hass = _Hass()
        hass.refuse = True
        a = _adapter(hass)
        for _ in range(6):
            await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY, UTILITY]
        assert "did not show" in a.last_error and "refused" in a.last_error
        assert a.hold_refused is True and a.hold_active is False

    async def test_a_select_the_inverter_flips_back_is_not_fought(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_limit(0.0), a)    # the next read sees it held
        hass.put(MODE, SBU)                      # the inverter's own logic
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY]
        assert "by itself" in a.last_error

    async def test_a_failed_write_leaves_no_name_in_the_record(self):
        hass, store = _Hass(), _Store()
        hass.raise_on = True
        a = _adapter(hass, store)
        await actuate_battery(_limit(0.0), a)
        assert "write failed" in a.last_error
        assert json.loads(store.raw)["running"] == {}

    async def test_observer_mode_sends_nothing_and_records_nothing(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_limit(0.0), a, observer=True)
        assert hass.calls == [] and store.raw is None


# ── release ─────────────────────────────────────────────────────────────
class TestRelease:
    async def test_normal_puts_back_what_the_select_showed_before(self):
        hass = _Hass(mode=SOLAR)                 # not SBU: the prior is the user's own
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_normal(), a)
        await actuate_battery(_normal(), a)
        assert hass.writes() == [UTILITY, SOLAR]
        assert a.last_intent is BatteryIntent.NORMAL and a.hold_active is False

    async def test_a_change_by_hand_since_is_left_alone(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        hass.put(MODE, SOLAR)                    # the user chose another mode
        await actuate_battery(_normal(), a)
        assert hass.writes() == [UTILITY] and hass.read() == SOLAR
        await actuate_battery(_limit(0.0), a)    # the name is gone: a fresh hold
        assert hass.writes() == [UTILITY, UTILITY]

    async def test_a_put_back_that_cannot_be_read_stays_and_is_asked_again(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        hass.put(MODE, "unavailable")
        await actuate_battery(_normal(), a)
        assert a.hold_active is True and "unavailable" in a.last_error
        assert a.last_intent is not BatteryIntent.NORMAL
        hass.put(MODE, UTILITY)
        await actuate_battery(_normal(), a)
        assert hass.read() == SBU and a.last_intent is BatteryIntent.NORMAL
        assert a.last_error is None

    async def test_a_prior_the_select_no_longer_lists_is_said_not_guessed(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        hass.put(MODE, UTILITY, options=[SOLAR, UTILITY])
        await actuate_battery(_normal(), a)
        assert hass.writes() == [UTILITY] and "no longer lists" in a.last_error

    async def test_off_puts_it_back(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.OFF), a)
        assert hass.read() == SBU

    async def test_unload_puts_it_back_through_the_hand_back(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        coord = SimpleNamespace(_battery_adapters={"b1": a}, _observer_mode=False)
        await async_release_batteries_on_unload(coord)
        assert hass.read() == SBU

    async def test_a_partial_limit_releases_after_the_dwell_in_the_test_shape(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_limit(500.0), a)
        assert hass.writes() == [UTILITY, SBU]


# ── the numbers: minimum hold, write limit, verification ───────────────
class _Clock:
    def __init__(self, monkeypatch):
        self.t = 1000.0
        monkeypatch.setattr(hold_select.time, "monotonic", lambda: self.t)

    def __iadd__(self, s):
        self.t += s
        return self


@pytest.fixture
def real_numbers(monkeypatch):
    monkeypatch.setattr(SelectHold, "MIN_HOLD_S", hold_select.MIN_HOLD_S)
    monkeypatch.setattr(SelectHold, "SHOW_WITHIN_S", hold_select.SHOW_WITHIN_S)
    return _Clock(monkeypatch)


def _watched(watts, bid="b1"):
    return BatteryDecision(battery_id=bid, intent=BatteryIntent.LIMIT_DISCHARGE,
                           discharge_limit_w=0.0, pack_w=watts)


class TestMinimumHold:
    async def test_flapping_decisions_write_nothing_for_thirty_minutes(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        for step, d in ((60, _normal()), (60, _limit(500.0)), (60, _limit(0.0)),
                        (1500, _normal()), (100, _limit(500.0))):
            clock += step
            await actuate_battery(d, a)
        assert hass.writes() == [UTILITY]            # 1780 s in: still held
        clock += 30
        await actuate_battery(_normal(), a)
        assert hass.writes() == [UTILITY, SBU]
        await actuate_battery(_limit(0.0), a)        # a hold right after waits too
        assert hass.writes() == [UTILITY, SBU]
        clock += 1801
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY, SBU, UTILITY]

    async def test_off_and_unload_never_wait(self, real_numbers):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.OFF), a)
        assert hass.read() == SBU
        hass2 = _Hass()
        b = _adapter(hass2)
        await actuate_battery(_limit(0.0), b)
        coord = SimpleNamespace(_battery_adapters={"b1": b}, _observer_mode=False)
        await async_release_batteries_on_unload(coord)
        assert hass2.read() == SBU


class TestWriteLimitPerDay:
    async def test_the_thirteenth_write_of_the_day_is_not_sent(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        for _ in range(6):                          # 6 holds + 6 releases = 12
            await actuate_battery(_limit(0.0), a)
            await actuate_battery(_normal(), a)
        assert len(hass.writes()) == 12
        await actuate_battery(_limit(0.0), a)
        assert len(hass.writes()) == 12 and hass.read() == SBU
        assert "12 writes" in a.last_error

    async def test_the_count_is_on_disk_and_starts_again_at_the_day_roll(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        for _ in range(6):
            await actuate_battery(_limit(0.0), a)
            await actuate_battery(_normal(), a)
        b = _adapter(hass, store)                   # a restart: same disk
        await actuate_battery(_limit(0.0), b)
        assert len(hass.writes()) == 12
        tomorrow = dt_util.now().replace(day=dt_util.now().day % 27 + 1, month=1)
        with patch.object(dt_util, "now", return_value=tomorrow):
            await actuate_battery(_limit(0.0), b)
        assert len(hass.writes()) == 13 and hass.read() == UTILITY

    async def test_a_put_back_is_never_held_back_by_the_limit(self):
        hass = _Hass()
        a = _adapter(hass)
        for _ in range(6):
            await actuate_battery(_limit(0.0), a)
            await actuate_battery(_normal(), a)
        hass.put(MODE, UTILITY)                     # held by someone: SEM's record is gone
        rec = a._hold.record
        await rec.started(MODE, "b1", prior=SBU, option=UTILITY)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.OFF), a)
        assert hass.read() == SBU


class TestVerified:
    async def test_a_hold_the_battery_ignores_is_refused_after_five_minutes(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        a = _adapter(hass)
        await actuate_battery(_watched(-900.0), a)
        for step in (10, 120, 160):                 # 290 s of discharge: not yet
            clock += step
            await actuate_battery(_watched(-900.0), a)
        assert hass.read() == UTILITY and a.hold_refused is False
        clock += 20                                 # past 300 s
        await actuate_battery(_watched(-900.0), a)
        assert hass.read() == SBU                   # the prior is back
        assert a.hold_refused is True and a.hold_active is False
        assert "still gives 900 W" in a.last_error
        n = len(hass.writes())
        for _ in range(5):
            clock += 3000
            await actuate_battery(_watched(-900.0), a)
        assert len(hass.writes()) == n              # no new attempt
        assert a.last_discharge_limit_w == -1.0

    async def test_the_refusal_lasts_a_day_and_survives_a_restart(self, real_numbers):
        clock, hass, store = real_numbers, _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_watched(-900.0), a)
        clock += 10
        await actuate_battery(_watched(-900.0), a)
        clock += 400
        await actuate_battery(_watched(-900.0), a)
        assert a.hold_refused is True
        b = _adapter(hass, store)                   # restart
        clock += 4000
        await actuate_battery(_watched(0.0), b)
        assert b.hold_refused is True and hass.read() == SBU
        rec = b._hold.record
        rec._refused[MODE] -= 86401                 # a day and a second on
        await actuate_battery(_watched(0.0), b)
        assert b.hold_refused is False and hass.read() == UTILITY

    async def test_a_battery_that_stops_giving_is_never_refused(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        a = _adapter(hass)
        await actuate_battery(_watched(-900.0), a)
        for watts in (-900.0, -50.0, -900.0, -30.0, -900.0, -20.0):
            clock += 250
            await actuate_battery(_watched(watts), a)
        assert a.hold_refused is False and hass.read() == UTILITY

    async def test_no_reading_neither_refuses_nor_clears_the_count(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        a = _adapter(hass)
        await actuate_battery(_watched(-900.0), a)
        clock += 10
        await actuate_battery(_watched(-900.0), a)
        clock += 400
        await actuate_battery(_watched(None), a)
        assert a.hold_refused is False

    async def test_either_battery_behind_the_shared_select_can_refuse_it(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        rec = ForcedChargeRecord(_Store())
        a = _adapter(hass, bid="b1", battery_hold_record=rec)
        b = _adapter(hass, bid="b2", battery_hold_record=rec)
        await actuate_battery(_watched(0.0, "b1"), a)
        await actuate_battery(_watched(0.0, "b2"), b)
        for _ in range(3):
            clock += 150
            await actuate_battery(_watched(0.0, "b1"), a)        # idle
            await actuate_battery(_watched(-800.0, "b2"), b)     # still giving
        assert b.hold_refused is True and hass.read() == UTILITY  # a still owns it
        clock += 10
        await actuate_battery(_watched(0.0, "b1"), a)
        assert a.hold_refused is True and hass.read() == SBU

    async def test_a_slow_select_gets_one_resend_then_is_refused(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        hass.refuse = True
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        clock += 30
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY]            # waiting, not writing
        clock += 40
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY, UTILITY]   # the one re-send
        clock += 30
        await actuate_battery(_limit(0.0), a)
        assert a.hold_refused is False
        clock += 40
        await actuate_battery(_limit(0.0), a)
        assert a.hold_refused is True and len(hass.writes()) == 2
        assert "did not show" in a.last_error

    async def test_a_slow_select_that_shows_in_time_is_held(self, real_numbers):
        clock, hass = real_numbers, _Hass()
        hass.refuse = True
        a = _adapter(hass)
        await actuate_battery(_limit(0.0), a)
        clock += 40
        hass.put(MODE, UTILITY)                      # the cloud caught up
        await actuate_battery(_limit(0.0), a)
        assert hass.writes() == [UTILITY] and a.hold_active is True
        assert a.last_error is None


# ── restart ─────────────────────────────────────────────────────────────
class TestRestart:
    async def test_the_next_lifetime_adopts_the_hold_and_releases_it(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        b = _adapter(hass, store)                # HA restarted: a new adapter
        assert b.hold_active is False
        await b.async_adopt_running_charge()
        assert b.hold_active is True
        await actuate_battery(_normal(), b)
        assert hass.read() == SBU

    async def test_an_unload_before_the_first_decision_still_releases(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        b = _adapter(hass, store)
        await b.async_adopt_running_charge()
        coord = SimpleNamespace(_battery_adapters={"b1": b}, _observer_mode=False)
        await async_release_batteries_on_unload(coord)
        assert hass.read() == SBU

    async def test_a_hold_the_select_no_longer_shows_is_dropped_not_written(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        hass.put(MODE, SOLAR)
        b = _adapter(hass, store)
        await b.async_adopt_running_charge()
        assert b.hold_active is False and hass.writes() == [UTILITY]

    async def test_settings_cleared_after_a_hold_puts_the_select_back_once(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        b = _adapter(hass, store, battery_hold_select_entity="",
                     battery_hold_select_option="")
        await b.async_adopt_running_charge()
        await b.async_adopt_running_charge()
        assert hass.writes() == [UTILITY, SBU]

    async def test_orphan_in_observer_mode_sends_nothing_and_keeps_the_record(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        b = _adapter(hass, store, battery_hold_select_entity="",
                     battery_hold_select_option="")
        await b.async_adopt_running_charge(observer=True)
        assert hass.writes() == [UTILITY] and hass.read() == UTILITY
        await b.async_adopt_running_charge(observer=False)
        assert hass.read() == SBU

    async def test_an_old_record_is_dropped_and_the_select_left(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_limit(0.0), _adapter(hass, store))
        raw = json.loads(store.raw)
        raw["since"] = {MODE: 1.0}               # 1970
        store.raw = json.dumps(raw)
        b = _adapter(hass, store, battery_hold_select_entity="",
                     battery_hold_select_option="")
        await b.async_adopt_running_charge()
        assert hass.writes() == [UTILITY] and hass.read() == UTILITY


# ── two batteries, one select ───────────────────────────────────────────
class TestTwoBatteriesOneInverter:
    async def test_the_select_goes_back_with_the_last_owner(self):
        hass, store = _Hass(), _Store()
        rec = ForcedChargeRecord(store)
        a = _adapter(hass, bid="b1", battery_hold_record=rec)
        b = _adapter(hass, bid="b2", battery_hold_record=rec)
        await actuate_battery(_limit(0.0, "b1"), a)
        await actuate_battery(_limit(0.0, "b2"), b)
        assert hass.writes() == [UTILITY]            # one write for the pair
        await actuate_battery(_normal("b1"), a)
        assert hass.read() == UTILITY                # b2 still holds
        await actuate_battery(_normal("b2"), b)
        assert hass.writes() == [UTILITY, SBU]

    async def test_a_pack_that_never_held_does_not_release_anothers_hold(self):
        hass = _Hass()
        rec = ForcedChargeRecord(_Store())
        a = _adapter(hass, bid="b1", battery_hold_record=rec)
        b = _adapter(hass, bid="b2", battery_hold_record=rec)
        await actuate_battery(_limit(0.0, "b1"), a)
        await actuate_battery(_normal("b2"), b)
        assert hass.read() == UTILITY


# ── beside the grid charge ──────────────────────────────────────────────
class TestBesideTheGridCharge:
    async def test_two_selects_two_records_each_restored_on_its_own(self):
        hass = _Hass()
        a = _adapter(hass, charge=True)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_charge(), a)
        assert hass.read(MODE) == UTILITY and hass.read(SOURCE) == MAINS
        # the two records never name each other's select
        assert set(a._hold.record.snapshot()) == {MODE}
        assert set(a._charge_adapter.charge_record.snapshot()) == {SOURCE}
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.STOP_FORCE_CHARGE), a)
        assert hass.read(SOURCE) == SOLAR_ONLY and hass.read(MODE) == UTILITY
        await actuate_battery(_normal(), a)
        assert hass.read(MODE) == SBU

    async def test_a_hold_that_cannot_be_put_back_never_blocks_the_charge_stop(self):
        hass = _Hass()
        a = _adapter(hass, charge=True)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_charge(), a)
        hass.put(MODE, "unavailable")
        await actuate_battery(_normal(), a)
        assert hass.read(SOURCE) == SOLAR_ONLY       # the charge select is back
        assert a.hold_active is True                 # the hold waits and is said
        assert "unavailable" in a.last_error

    async def test_a_charge_that_cannot_be_stopped_never_blocks_the_hold_release(self):
        hass = _Hass()
        a = _adapter(hass, charge=True)
        await actuate_battery(_limit(0.0), a)
        await actuate_battery(_charge(), a)
        hass.put(SOURCE, "unavailable")
        await actuate_battery(_normal(), a)
        assert hass.read(MODE) == SBU                # the hold is back


# ── does SEM decide a hold on G12w? ─────────────────────────────────────
PEAK, OFF = 1.25, 0.6387
WORKDAYS = [0, 1, 2, 3, 4]


def _g12w():
    return CalendarTariffProvider(
        None, peak_rate=PEAK, off_peak_rate=OFF, export_rate=0.0,
        rules=[{"days": WORKDAYS, "start": "06:00", "end": "13:00", "tariff": "ht"},
               {"days": WORKDAYS, "start": "15:00", "end": "22:00", "tariff": "ht"}])


def _at(day, hour, minute=0):
    """2026-11-16 is a Monday; 21 is a Saturday."""
    return datetime(2026, 11, day, hour, minute,
                    tzinfo=dt_util.get_default_time_zone())


def _cycle_decision(provider, moment, soc=60.0, sink=True):
    """The coordinator's own chain for one cycle: the compared level, the sink
    verdicts, then ``decide_battery`` for a pack at ``soc`` %."""
    with patch.object(dt_util, "now", return_value=moment):
        level = PriceView(provider).compared_level()
        level = getattr(level, "value", level)
        if not isinstance(level, str):
            from custom_components.solar_energy_management.coordinator.price_signal import (
                absence_word,
            )
            level = absence_word(provider)
        verdicts = sink_verdicts(
            now=moment, tariff_level=level, upcoming=None, export_rate=None,
            export_rate_known=False, export_guard_enabled=False,
            house_sink_enabled=sink, morning_window_enabled=False, departure=None,
            morning_hours=2.0, forecast_refills_pack=False, pacing_horizon_end=None)
    view = BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 4000, "battery_mode": "auto"},
        fleet=FleetContext(), charging_state="idle", ev_charging=False,
        ev_connected=False, home_consumption_w=800.0, scheduler_decision=None,
        sink_verdicts=verdicts)
    return decide_battery(view)


class TestG12wNightAndMorning:
    """A weekday at 22:00, pack at 60 %, tomorrow's peak 06-13 at 1.25: the
    pack is held through the cheap night and released at 06:00. The house
    sink switch must be on; it is off by default."""

    async def _run(self, hass, a, provider, moments, sink=True):
        trace = []
        for m in moments:
            d = _cycle_decision(provider, m, sink=sink)
            await actuate_battery(d, a)
            trace.append((m.strftime("%a %H:%M"), d.intent, hass.read()))
        return trace

    async def test_a_weekday_night_is_held_and_released_at_six(self):
        hass = _Hass()
        a = _adapter(hass, charge=True)
        night = [_at(16, 22, 0), _at(16, 23, 30), _at(17, 0, 30), _at(17, 3, 0),
                 _at(17, 5, 59), _at(17, 6, 0), _at(17, 9, 0)]
        trace = await self._run(hass, a, _g12w(), night)
        modes = {when: mode for when, _i, mode in trace}
        assert modes["Mon 22:00"] == UTILITY and modes["Tue 05:59"] == UTILITY
        assert modes["Tue 06:00"] == SBU and modes["Tue 09:00"] == SBU
        assert hass.writes(MODE) == [UTILITY, SBU]          # two writes, no more
        assert hass.writes(SOURCE) == []                    # the charge select is untouched

    async def test_the_midday_off_peak_window_is_held_for_the_afternoon_peak(self):
        hass = _Hass()
        a = _adapter(hass)
        trace = await self._run(hass, a, _g12w(), [
            _at(17, 12, 55), _at(17, 13, 0), _at(17, 14, 59), _at(17, 15, 0)])
        assert [m for *_x, m in trace] == [SBU, UTILITY, UTILITY, SBU]

    async def test_a_weekend_day_is_never_held(self):
        hass = _Hass()
        a = _adapter(hass)
        trace = await self._run(hass, a, _g12w(), [
            _at(21, 8, 0), _at(21, 14, 0), _at(21, 23, 0), _at(22, 3, 0)])
        assert all(i is BatteryIntent.NORMAL for _w, i, _m in trace)
        assert hass.writes() == []

    async def test_with_the_house_sink_off_nothing_is_ever_held(self):
        hass = _Hass()
        a = _adapter(hass)
        await self._run(hass, a, _g12w(), [_at(16, 22, 0), _at(17, 3, 0)], sink=False)
        assert hass.writes() == []

    async def test_a_calendar_without_a_peak_has_nothing_to_wait_for(self):
        flat = CalendarTariffProvider(None, peak_rate=OFF, off_peak_rate=OFF,
                                      export_rate=0.0, rules=[])
        hass = _Hass()
        a = _adapter(hass)
        await self._run(hass, a, flat, [_at(16, 22, 0), _at(17, 3, 0)])
        assert hass.writes() == []
