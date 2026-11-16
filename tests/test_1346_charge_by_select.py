"""#1346 — a grid charge started by a select, stopped by putting it back.

An inverter with no charge switch, but a select ("Solar and mains" against
"Solar only"). Two settings, the select and its charge option; with either
unset nothing changes. The option the select showed before SEM changed it is
kept in the same record the switch path uses, so the stop, an abort and a
restart mid-charge all put it back, and a choice made by hand is left alone.
"""
from __future__ import annotations

import json
from types import SimpleNamespace

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
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

from .test_1367_plan_only_sendable_charge import _battery_row, _plan

SELECT = "select.charge_source"
CHARGE = "Solar and mains"
SOLAR = "Solar only"
OPTIONS = [SOLAR, CHARGE, "Utility first"]
SWITCH = "switch.force_charge"


class _Hass:
    """A select that lists options; each write lands, every call recorded."""

    def __init__(self, state=SOLAR):
        self._states = {SELECT: SimpleNamespace(
            state=state, attributes={"options": list(OPTIONS)})}
        self.calls: list[tuple] = []
        self.raise_on = False
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def set(self, value, options=None):
        old = self._states[SELECT]
        self._states[SELECT] = SimpleNamespace(
            state=value, attributes={"options": options if options is not None
                                     else old.attributes["options"]})

    def read(self):
        return self._states[SELECT].state

    async def _call(self, domain, service, data, **kw):
        if self.raise_on:
            raise RuntimeError("bus timeout")
        self.calls.append((domain, service, dict(data)))
        if service == "select_option":
            self.set(data["option"])

    def writes(self):
        return [c for c in self.calls if c[1] == "select_option"]


class _Store:
    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


def _adapter(hass, store, **extra):
    cfg = {"battery_charge_select_entity": SELECT,
           "battery_charge_select_option": CHARGE,
           "forced_charge_record": ForcedChargeRecord(store),
           "battery_id": "b1", **extra}
    return GenericBatteryAdapter(hass, cfg)


def _charge(soc=60.0):
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=soc, charge_power_w=3000.0, duration_min=60)


def _stop():
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.STOP_FORCE_CHARGE)


# ── asleep ──────────────────────────────────────────────────────────────
class TestAsleep:
    def test_nothing_configured_is_as_before(self):
        a = GenericBatteryAdapter(_Hass(), {"battery_id": "b1"})
        assert a.supports_forced_charge is False
        assert a.charge_command_configured is False

    def test_either_setting_alone_wakes_nothing(self):
        for cfg in ({"battery_charge_select_entity": SELECT},
                    {"battery_charge_select_option": CHARGE}):
            a = GenericBatteryAdapter(_Hass(), {"battery_id": "b1", **cfg})
            assert a.supports_forced_charge is False

    async def test_a_switch_setup_is_untouched_by_the_select_keys(self):
        hass = _Hass()
        hass._states[SWITCH] = SimpleNamespace(state="off", attributes={})
        a = _adapter(hass, _Store(), battery_force_charge_switch=SWITCH,
                     battery_target_soc_entity="number.t")
        await actuate_battery(_charge(), a)
        assert [c[:2] for c in hass.calls] == [("switch", "turn_on")]
        assert hass.writes() == []

    async def test_no_target_entity_is_needed_for_the_select_path(self):
        assert _adapter(_Hass(), _Store()).supports_forced_charge is True


# ── start ───────────────────────────────────────────────────────────────
class TestStart:
    async def test_writes_the_charge_option_once_and_a_second_start_nothing(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_charge(), a)
        assert hass.writes() == [("select", "select_option",
                                  {"entity_id": SELECT, "option": CHARGE})]
        assert a.last_intent is BatteryIntent.FORCE_CHARGE

    async def test_the_prior_option_is_on_disk_before_the_write(self):
        hass, store = _Hass(), _Store()
        seen = []
        orig = hass._call

        async def spy(domain, service, data, **kw):
            seen.append(json.loads(store.raw))
            await orig(domain, service, data, **kw)
        hass.services = SimpleNamespace(async_call=spy)
        await actuate_battery(_charge(), _adapter(hass, store))
        assert seen[0]["prior"] == {SELECT: SOLAR}

    async def test_an_option_the_select_does_not_list_writes_nothing(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), battery_charge_select_option="Grid only")
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert "does not list" in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_an_unavailable_select_cannot_start(self):
        for state in ("unavailable", "unknown"):
            hass = _Hass(state)
            a = _adapter(hass, _Store())
            await actuate_battery(_charge(), a)
            assert hass.calls == []
            assert "unavailable" in a.last_error
            assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_a_failed_write_drops_the_name_and_says_so(self):
        hass, store = _Hass(), _Store()
        hass.raise_on = True
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        assert "start failed" in a.last_error
        assert json.loads(store.raw).get("running", {}) == {}

    async def test_a_record_that_cannot_be_saved_means_no_start(self):
        hass, store = _Hass(), _Store()

        async def boom(data):
            raise OSError("disk")
        store.async_save = boom
        await actuate_battery(_charge(), _adapter(hass, store))
        assert hass.calls == []

    async def test_a_select_already_on_the_option_is_not_taken_over(self):
        hass, store = _Hass(CHARGE), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.calls == []             # nothing written, nothing put back
        assert store.raw is None


# ── stop ────────────────────────────────────────────────────────────────
class TestStop:
    async def test_the_stop_restores_what_the_select_showed(self):
        hass = _Hass("Utility first")
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.read() == "Utility first"
        assert [w[2]["option"] for w in hass.writes()] == [CHARGE, "Utility first"]

    async def test_a_second_stop_writes_nothing(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        n = len(hass.calls)
        await actuate_battery(_stop(), a)
        assert len(hass.calls) == n

    async def test_a_hand_change_during_the_charge_is_not_written_over(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        hass.set("Utility first")           # the user chose by hand
        n = len(hass.calls)
        await actuate_battery(_stop(), a)
        assert len(hass.calls) == n and hass.read() == "Utility first"
        assert json.loads(store.raw).get("running", {}) == {}   # name dropped

    async def test_an_unreadable_select_is_retried_not_forgotten(self):
        hass, store = _Hass(), _Store()
        a = _adapter(hass, store)
        await actuate_battery(_charge(), a)
        hass.set("unavailable")
        await actuate_battery(_stop(), a)
        assert "unavailable" in a.last_error
        assert a.last_intent is BatteryIntent.FORCE_CHARGE      # not "stopped"
        hass.set(CHARGE)
        await actuate_battery(_stop(), a)
        assert hass.read() == SOLAR

    async def test_the_unload_abort_puts_it_back(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await async_release_batteries_on_unload(
            SimpleNamespace(_observer_mode=False, _battery_adapters={"b1": a}))
        assert hass.read() == SOLAR

    async def test_off_puts_it_back(self):
        hass = _Hass()
        a = _adapter(hass, _Store())
        await actuate_battery(_charge(), a)
        await a.command_normal()
        assert hass.read() == SOLAR


# ── restart ─────────────────────────────────────────────────────────────
class TestRestart:
    async def test_the_prior_survives_a_restart_and_the_stop_restores_it(self):
        hass, store = _Hass("Utility first"), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        fresh = _adapter(hass, store)       # a new lifetime, same store
        await fresh.async_adopt_running_charge()
        await actuate_battery(_stop(), fresh)
        assert hass.read() == "Utility first"

    async def test_a_hand_change_before_the_restart_is_not_fought(self):
        hass, store = _Hass(), _Store()
        await actuate_battery(_charge(), _adapter(hass, store))
        hass.set("Utility first")
        fresh = _adapter(hass, store)
        await fresh.async_adopt_running_charge()
        n = len(hass.calls)
        await actuate_battery(_stop(), fresh)
        assert len(hass.calls) == n and hass.read() == "Utility first"

    async def test_an_old_record_without_a_prior_still_loads(self):
        store = _Store()
        store.raw = json.dumps({"running": {SWITCH: ["b1"]}})
        rec = ForcedChargeRecord(store)
        assert await rec.running(SWITCH, "b1") is True
        assert await rec.prior_of(SWITCH) is None


# ── observer ────────────────────────────────────────────────────────────
class TestObserver:
    async def test_observer_sends_nothing_and_records_the_would(self):
        hass, store = _Hass(), _Store()
        seen = []
        controller = SimpleNamespace(
            publish_observer_decision=lambda **kw: seen.append(kw))
        await actuate_battery(_charge(), _adapter(hass, store),
                              observer=True, controller=controller)
        assert hass.calls == [] and store.raw is None
        assert seen and seen[0]["action"] == "force_charge"


# ── the plan ────────────────────────────────────────────────────────────
class TestPlan:
    def test_the_plan_keeps_the_charge_when_the_select_is_set(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": _adapter(_Hass(), _Store())})
        assert _battery_row(plan) is not None
        assert not [r for r in plan["not_scheduled"] if r["id"] == "battery"]

    def test_the_plan_still_marks_no_charge_control_without_it(self, monkeypatch):
        plan = _plan(monkeypatch, {"b1": GenericBatteryAdapter(_Hass(), {})})
        assert _battery_row(plan) is None
        assert {"id": "battery", "why": "no_charge_control",
                "label": None} in plan["not_scheduled"]
