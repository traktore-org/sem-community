"""#1362 — a battery hold must never become a grid charge.

@matekogon, 26.11.2026: "House as a battery sink" held the battery 13:00–15:00
by setting the output mode select to "Utility". The charge-source select read
"Solar and mains", and in "Utility" his inverter then charged the battery
from the grid — SEM's "keep the pack" was a grid charge.

While a hold by select runs, the charge-source select (when one is set) shows
an option without the grid: the one solar-only option, written for the hold
and put back after it. With no option surely without the grid, SEM does not
hold and a Repair asks the user. A grid charge (the hold asked FOR a charge)
keeps writing the charge option as before.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.consts.role_lexicon import (
    hold_charge_source,
)
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
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

MODE = "select.inv_output_source_priority"
SOURCE = "select.inv_charger_source_priority"
SBU, SOLAR_FIRST, UTILITY = "SBU", "Solar first", "Utility"
MODES = [UTILITY, SOLAR_FIRST, SBU]
SRC_SOLAR_FIRST, MAINS, ONLY_SOLAR = "Solar first", "Solar and mains", "Only solar"
SOURCES = [SRC_SOLAR_FIRST, MAINS, ONLY_SOLAR]


class _Hass:
    """Two selects; a write lands; every call kept. ``charges_from_grid``
    is the inverter's own rule: hold mode + a mains charge source."""

    def __init__(self, mode=SBU, source=MAINS, sources=None):
        self._states = {
            MODE: SimpleNamespace(state=mode, attributes={"options": list(MODES)}),
            SOURCE: SimpleNamespace(state=source, attributes={
                "options": list(sources if sources is not None else SOURCES)}),
        }
        self.calls: list[tuple] = []
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def put(self, entity, value):
        old = self._states[entity]
        self._states[entity] = SimpleNamespace(state=value, attributes=old.attributes)

    def read(self, entity):
        return self._states[entity].state

    def charges_from_grid(self) -> bool:
        return self.read(MODE) == UTILITY and self.read(SOURCE) == MAINS

    async def _call(self, domain, service, data, **kw):
        self.calls.append((domain, service, dict(data)))
        if service == "select_option":
            self.put(data["entity_id"], data["option"])

    def writes(self, entity=None):
        return [(c[2]["entity_id"], c[2]["option"]) for c in self.calls
                if c[1] == "select_option"
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
    monkeypatch.setattr(SelectHold, "AWAY_FOR_S", 0.0)


def _adapter(hass, store=None, charge=True):
    cfg = {"battery_hold_select_entity": MODE,
           "battery_hold_select_option": UTILITY,
           "battery_hold_record": ForcedChargeRecord(store or _Store()),
           "battery_id": "b1"}
    if charge:
        cfg.update({"battery_charge_select_entity": SOURCE,
                    "battery_charge_select_option": MAINS,
                    "forced_charge_record": ForcedChargeRecord(_Store())})
    return GenericBatteryAdapter(hass, cfg)


def _hold():
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.LIMIT_DISCHARGE,
                           discharge_limit_w=0.0)


def _normal():
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.NORMAL)


def _charge():
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=80.0, charge_power_w=3000.0, duration_min=60)


# ── the one rule (lexicon) ───────────────────────────────────────────────
class TestRule:
    def test_the_solar_only_option_is_chosen(self):
        assert hold_charge_source(SOURCES, MAINS, MAINS) == ("set", ONLY_SOLAR)

    def test_it_is_kept_when_it_already_shows(self):
        assert hold_charge_source(SOURCES, ONLY_SOLAR, MAINS) == ("keep", None)

    def test_an_option_without_grid_words_is_kept_when_no_solar_only_exists(self):
        assert hold_charge_source(["Solar first", "Solar and utility"],
                                  "Solar first", "Solar and utility") == ("keep", None)

    def test_no_option_surely_without_the_grid_is_none(self):
        assert hold_charge_source(["Utility first", "Solar and utility"],
                                  "Solar and utility", "Solar and utility") == ("none", None)

    def test_inverter_abbreviations(self):
        assert hold_charge_source(["CSO", "SNU", "OSO"], "SNU", "SNU") == ("set", "OSO")


# ── the bug ──────────────────────────────────────────────────────────────
class TestHoldTakesNoGrid:
    async def test_the_reported_case_holds_without_a_grid_charge(self):
        """26.11: mode SBU, source "Solar and mains" — the hold must not
        charge from the grid."""
        hass = _Hass(mode=SBU, source=MAINS)
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        assert hass.read(MODE) == UTILITY
        assert hass.read(SOURCE) == ONLY_SOLAR
        assert not hass.charges_from_grid()
        # the source goes first: never "Utility" with a mains source
        assert hass.writes()[0] == (SOURCE, ONLY_SOLAR)

    async def test_the_hold_end_puts_both_back_mode_first(self):
        hass = _Hass(mode=SBU, source=MAINS)
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        await actuate_battery(_normal(), a)
        assert hass.read(MODE) == SBU and hass.read(SOURCE) == MAINS
        assert hass.writes()[-2:] == [(MODE, SBU), (SOURCE, MAINS)]

    async def test_a_source_without_the_grid_is_not_written(self):
        hass = _Hass(mode=SBU, source=ONLY_SOLAR)
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        await actuate_battery(_normal(), a)
        assert hass.writes(SOURCE) == []

    async def test_a_change_by_hand_during_the_hold_is_left_alone(self):
        hass = _Hass(mode=SBU, source=MAINS)
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        hass.put(SOURCE, SRC_SOLAR_FIRST)              # the user's choice
        await actuate_battery(_normal(), a)
        assert hass.read(SOURCE) == SRC_SOLAR_FIRST

    async def test_no_option_without_the_grid_means_no_hold(self):
        sources = ["Utility first", "Solar and mains"]
        hass = _Hass(mode=SBU, source=MAINS, sources=sources)
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        assert hass.writes() == []
        assert hass.read(MODE) == SBU
        assert "not held" in (a.last_error or "")

    async def test_an_unreadable_source_means_no_hold(self):
        hass = _Hass(mode=SBU, source="unavailable")
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        assert hass.writes() == [] and hass.read(MODE) == SBU

    async def test_without_a_charge_select_the_hold_is_as_before(self):
        hass = _Hass(mode=SBU, source=MAINS)
        a = _adapter(hass, charge=False)
        await actuate_battery(_hold(), a)
        assert hass.writes() == [(MODE, UTILITY)]


class TestCharge:
    async def test_a_grid_charge_still_sets_the_charge_option(self):
        hass = _Hass(mode=SBU, source=ONLY_SOLAR)
        a = _adapter(hass)
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert hass.read(MODE) == UTILITY and hass.read(SOURCE) == MAINS

    async def test_a_charge_after_a_hold_starts_from_the_users_source(self):
        """Hold (source → solar only), then a grid charge: the guard gives
        the source back first, so the charge's own record keeps the user's
        value and puts THAT back after the charge."""
        hass = _Hass(mode=SBU, source=SRC_SOLAR_FIRST)
        a = _adapter(hass)
        await actuate_battery(_hold(), a)
        assert hass.read(SOURCE) == ONLY_SOLAR
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert hass.read(SOURCE) == MAINS
        for _ in range(3):
            await actuate_battery(_normal(), a)
        assert hass.read(SOURCE) == SRC_SOLAR_FIRST and hass.read(MODE) == SBU


class TestRestart:
    async def test_a_restart_mid_hold_keeps_and_later_puts_back_both(self):
        store = _Store()
        hass = _Hass(mode=SBU, source=MAINS)
        await actuate_battery(_hold(), _adapter(hass, store))
        b = _adapter(hass, store)                      # the next lifetime
        await b.async_adopt_hold()
        await actuate_battery(_normal(), b)
        assert hass.read(MODE) == SBU and hass.read(SOURCE) == MAINS

    async def test_observer_mode_writes_nothing(self):
        hass = _Hass(mode=SBU, source=MAINS)
        a = _adapter(hass)
        await actuate_battery(_hold(), a, observer=True)
        assert hass.writes() == []
