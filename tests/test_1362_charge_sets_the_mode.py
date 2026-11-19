"""#1362 — a grid charge also sets the mode select.

@matekogon, 19.11: the inverter charges from the grid only when the MODE
select is "Utility" (at night; "SOLAR" by day) AND the charge-source select
is "Solar and mains". In SBU nothing charges. SEM set only the charge source,
so a planned charge did nothing. With a hold select set (the mode, option
"Utility"), a grid charge now holds too: the same record, checks and
put-back as a hold. The next normal cycle releases it; a hold still wanted
keeps it.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
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
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

MODE = "select.inverter_output_mode"
SOURCE = "select.inverter_charge_source"
UTILITY, SOLAR, SBU = "Utility", "SOLAR", "SBU"
MAINS, SOLAR_ONLY = "Solar and mains", "Solar only"


class _Hass:
    """Two selects; every write lands unless refused; every call kept."""

    def __init__(self, mode=SBU, source=SOLAR_ONLY):
        self._states = {
            MODE: SimpleNamespace(state=mode, attributes={"options": [UTILITY, SOLAR, SBU]}),
            SOURCE: SimpleNamespace(state=source, attributes={"options": [SOLAR_ONLY, MAINS]}),
        }
        self.calls: list[tuple] = []
        self.refuse: set = set()
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def put(self, entity, value):
        old = self._states[entity]
        self._states[entity] = SimpleNamespace(state=value, attributes=old.attributes)

    def read(self, entity):
        return self._states[entity].state

    async def _call(self, domain, service, data, **kw):
        self.calls.append((domain, service, dict(data)))
        if service == "select_option" and data["entity_id"] not in self.refuse:
            self.put(data["entity_id"], data["option"])

    def writes(self, entity):
        return [c[2]["option"] for c in self.calls
                if c[1] == "select_option" and c[2]["entity_id"] == entity]


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


def _adapter(hass, hold_store=None, charge_store=None, hold=True, bid="b1"):
    cfg = {"battery_charge_select_entity": SOURCE,
           "battery_charge_select_option": MAINS,
           "forced_charge_record": ForcedChargeRecord(charge_store or _Store()),
           "battery_id": bid}
    if hold:
        cfg.update({"battery_hold_select_entity": MODE,
                    "battery_hold_select_option": UTILITY,
                    "battery_hold_record": ForcedChargeRecord(hold_store or _Store())})
    return GenericBatteryAdapter(hass, cfg)


def _d(intent, **kw):
    return BatteryDecision(battery_id="b1", intent=intent, **kw)


CHARGE = dict(target_soc=90.0, charge_power_w=3000.0, duration_min=120)


async def _charge(a):
    await actuate_battery(_d(BatteryIntent.FORCE_CHARGE, **CHARGE), a)


async def _stop(a):
    await actuate_battery(_d(BatteryIntent.STOP_FORCE_CHARGE), a)


async def _normal(a):
    await actuate_battery(_d(BatteryIntent.NORMAL), a)


class TestTheChargeSetsTheMode:
    async def test_a_charge_sets_both_and_both_go_back(self):
        hass = _Hass()
        a = _adapter(hass)
        await _charge(a)
        assert hass.read(MODE) == UTILITY and hass.read(SOURCE) == MAINS
        await _stop(a)
        await _normal(a)
        assert hass.read(MODE) == SBU and hass.read(SOURCE) == SOLAR_ONLY

    async def test_each_cycle_of_a_charge_writes_nothing_more(self):
        hass = _Hass()
        a = _adapter(hass)
        for _ in range(4):
            await _charge(a)
        assert hass.writes(MODE) == [UTILITY]
        assert hass.writes(SOURCE) == [MAINS]

    async def test_the_mode_already_utility_is_not_written_and_stays(self):
        hass = _Hass(mode=UTILITY)
        a = _adapter(hass)
        await _charge(a)
        await _stop(a)
        await _normal(a)
        assert hass.writes(MODE) == []
        assert hass.read(MODE) == UTILITY, "the user's mode is left as it was"

    async def test_a_mode_changed_by_hand_is_not_forced_back(self):
        hass = _Hass()
        a = _adapter(hass)
        await _charge(a)
        await _charge(a)                            # SEM sees its option land
        hass.put(MODE, SOLAR)                       # then the user's choice
        for _ in range(3):
            await _charge(a)
        assert hass.writes(MODE) == [UTILITY]
        await _stop(a)
        await _normal(a)
        assert hass.read(MODE) == SOLAR

    async def test_a_mode_that_does_not_take_the_option_is_bounded(self):
        hass = _Hass()
        hass.refuse.add(MODE)
        a = _adapter(hass)
        for _ in range(6):
            await _charge(a)
        assert len(hass.writes(MODE)) == 2           # the write and one re-send
        assert hass.read(SOURCE) == MAINS            # the charge still goes out
        assert a.last_error and "hold" in a.last_error.lower()


class TestEveryEndPutsTheModeBack:
    async def test_a_restart_mid_charge_puts_the_mode_back(self):
        hass, hold_store, charge_store = _Hass(), _Store(), _Store()
        await _charge(_adapter(hass, hold_store, charge_store))
        fresh = _adapter(hass, hold_store, charge_store)       # a new lifetime
        await fresh.async_adopt_running_charge()
        await _stop(fresh)
        await _normal(fresh)
        assert hass.read(MODE) == SBU and hass.read(SOURCE) == SOLAR_ONLY

    async def test_the_unload_puts_the_mode_back(self):
        hass = _Hass()
        a = _adapter(hass)
        await _charge(a)
        await async_release_batteries_on_unload(
            SimpleNamespace(_observer_mode=False, _battery_adapters={"b1": a}))
        assert hass.read(MODE) == SBU and hass.read(SOURCE) == SOLAR_ONLY

    async def test_observer_sends_nothing(self):
        hass = _Hass()
        controller = SimpleNamespace(publish_observer_decision=lambda **kw: None)
        await actuate_battery(_d(BatteryIntent.FORCE_CHARGE, **CHARGE), _adapter(hass),
                              observer=True, controller=controller)
        assert hass.calls == []


class TestTheHoldAndTheChargeShareTheMode:
    async def test_a_hold_then_a_charge_then_the_hold_again(self):
        hass = _Hass()
        a = _adapter(hass)
        await actuate_battery(_d(BatteryIntent.LIMIT_DISCHARGE, discharge_limit_w=0.0), a)
        assert hass.read(MODE) == UTILITY
        await _charge(a)
        await _stop(a)
        await actuate_battery(_d(BatteryIntent.LIMIT_DISCHARGE, discharge_limit_w=0.0), a)
        assert hass.read(MODE) == UTILITY, "the hold keeps the mode after the charge"
        assert hass.writes(MODE) == [UTILITY], "one write for the hold and the charge"
        await _normal(a)
        assert hass.read(MODE) == SBU

    async def test_without_a_hold_select_the_mode_is_never_touched(self):
        hass = _Hass()
        a = _adapter(hass, hold=False)
        await _charge(a)
        await _stop(a)
        await _normal(a)
        assert hass.writes(MODE) == []
        assert hass.writes(SOURCE) == [MAINS, SOLAR_ONLY]
