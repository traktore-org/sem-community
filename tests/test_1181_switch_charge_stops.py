"""#1181 — Off or an unload left a switch grid charge running.

GoodWe and the generic switch setup start a grid charge by setting the work
mode or turning a switch on. Only the stop turns it back. Three paths never
sent it:

* Battery mode Off during a grid charge: ``command_off`` ran
  ``command_normal``, and that left the switch on;
* SEM disabled or removed during a grid charge: the unload release also ran
  only ``command_normal``;
* a restart during a grid charge, with night charging turned off before the
  next run: the new adapter did not know SEM had started it.

The pack then charged from the grid with nothing watching it, and the charge
target SEM wrote stayed (#1180). The fix: the hand-back stops a charge SEM
started, and a record per entry keeps "SEM turned this on" across a restart.
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.base import (
    async_release_batteries_on_unload,
    unload_release_reason,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_record import (
    ForcedChargeRecord,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    ChargeCommandStatus,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.goodwe import (
    GoodWeBatteryAdapter,
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
    forced_ops,
)

TARGET = "number.soc_upper_limit"
SWITCH = "switch.force_charge"
MODE = "select.work_mode"
STRATEGY = "select.power_strategy"
SALE = "number.sale_power"
LIMIT = "number.battery_max_discharge"


class _Hass:
    """States the test sets; every call recorded, and each write lands."""

    def __init__(self):
        self._states = {
            TARGET: SimpleNamespace(state="100", attributes={}),
            SWITCH: SimpleNamespace(state="off", attributes={}),
            MODE: SimpleNamespace(state="General", attributes={}),
            STRATEGY: SimpleNamespace(state="nom", attributes={}),
            SALE: SimpleNamespace(state="0", attributes={
                "unit_of_measurement": "W", "min": -5000, "max": 5000}),
            LIMIT: SimpleNamespace(state="5000", attributes={
                "unit_of_measurement": "W", "min": 0, "max": 5000}),
        }
        self.calls: list[tuple] = []
        self.raise_on = None
        #: called with each call before it lands — a test can look around
        self.spy = None
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def set(self, entity_id, value):
        old = self._states.get(entity_id)
        self._states[entity_id] = SimpleNamespace(
            state=str(value), attributes=getattr(old, "attributes", {}))

    def read(self, entity_id):
        return self._states[entity_id].state

    async def _call(self, domain, service, data, **kw):
        if self.spy is not None:
            self.spy(domain, service, dict(data))
        if self.raise_on == (domain, service):
            raise RuntimeError("bus timeout")
        self.calls.append((domain, service, dict(data)))
        ent = data.get("entity_id")
        if getattr(self._states.get(ent), "state", None) == "unavailable":
            return                  # HA drops it without a word
        if service == "turn_on":
            self.set(ent, "on")
        elif service == "turn_off":
            self.set(ent, "off")
        elif service == "select_option":
            self.set(ent, data["option"])
        elif service == "set_value":
            self.set(ent, data["value"])

    def sent(self, service, entity_id):
        return [c for c in self.calls
                if c[1] == service and c[2].get("entity_id") == entity_id]


class _Store:
    """The record as Home Assistant keeps it: through JSON."""

    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


class _Life:
    """One lifetime of SEM: a record and a hold on the entry's two stores."""

    def __init__(self, hass, record_store, hold_store):
        self.hass = hass
        self.record = ForcedChargeRecord(record_store)
        self.hold = ChargeTargetHold(hass, hold_store, configured=(TARGET,))

    def generic(self, battery_id="b1", **extra):
        return GenericBatteryAdapter(self.hass, {
            "battery_force_charge_switch": SWITCH,
            "battery_target_soc_entity": TARGET,
            "charge_target_hold": self.hold,
            "forced_charge_record": self.record,
            "battery_id": battery_id, **extra})

    def goodwe(self, battery_id="b1", **extra):
        return GoodWeBatteryAdapter(self.hass, {
            "inverter_work_mode_entity": MODE,
            "battery_target_soc_entity": TARGET,
            "charge_target_hold": self.hold,
            "forced_charge_record": self.record,
            "battery_id": battery_id, **extra})


def _life(hass=None):
    hass = hass or _Hass()
    return _Life(hass, _Store(), _Store())


def _restart(life):
    """An HA restart: the entry is not unloaded, the stores stay."""
    return _Life(life.hass, life.record._store, life.hold._store)


_KINDS = {"generic": (lambda life, **kw: life.generic(**kw), SWITCH, "on", "off"),
          "goodwe": (lambda life, **kw: life.goodwe(**kw), MODE, "Eco Charge", "General")}
_RAISE = {SWITCH: ("switch", "turn_off"), MODE: ("select", "select_option")}


def _on_disk(life):
    return json.loads(life.record._store.raw)["running"]


def _charge_decision(soc=60.0):
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=soc, charge_power_w=3000.0, duration_min=60)


def _decision(intent):
    return BatteryDecision(battery_id="b1", intent=intent)


def _view(adapter, *, mode="auto", sched=None, gate=None):
    """No car, no sun: with no scheduler the decision is NORMAL."""
    charge, discharge = forced_ops(adapter)
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=55.0),
        config={"battery_mode": mode, "battery_max_discharge_power": 5000.0},
        fleet=FleetContext(solar_w=0.0, home_w=400.0, battery_soc=55.0,
                           battery_count=1, buffer_soc=30.0,
                           battery_assist_min_surplus_w=1200.0),
        charging_state="idle", ev_charging=False, ev_connected=False,
        home_consumption_w=400.0, scheduler_decision=sched, plan_gate=gate,
        sem_forced_charge=charge, sem_forced_discharge=discharge,
        sem_stop_misses=0)


async def _cycle(adapter, **view):
    decision = decide_battery(_view(adapter, **view))
    await actuate_battery(decision, adapter)
    return decision


def _unloading(adapter, observer=False):
    return SimpleNamespace(_observer_mode=observer, _battery_adapters={"b1": adapter})


@pytest.mark.asyncio
class TestOffStopsTheCharge:

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_off_sets_the_actuator_back_and_the_target(self, kind):
        make, actuator, on, off = _KINDS[kind]
        life = _life()
        adapter = make(life)
        await actuate_battery(_charge_decision(), adapter)
        assert life.hass.read(actuator) == on
        assert life.hass.read(TARGET) == "60"

        decision = await _cycle(adapter, mode="off")
        assert decision.intent is BatteryIntent.OFF
        assert life.hass.read(actuator) == off
        assert life.hass.read(TARGET) == "100"
        assert adapter.last_intent is BatteryIntent.OFF
        assert adapter._sem_forced_charge is False
        assert _on_disk(life) == {}

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_back_to_auto_sends_no_second_stop(self, kind):
        make, actuator, _, _ = _KINDS[kind]
        life = _life()
        adapter = make(life)
        await actuate_battery(_charge_decision(), adapter)
        await _cycle(adapter, mode="off")
        stops = len(life.hass.calls)
        decision = await _cycle(adapter)
        assert decision.intent is BatteryIntent.NORMAL
        assert [c for c in life.hass.calls[stops:]
                if c[2].get("entity_id") == actuator] == []

    async def test_a_pack_with_a_strategy_select_turns_the_switch_off(self):
        life = _life()
        adapter = life.generic(battery_strategy_control_entity=STRATEGY)
        await actuate_battery(_charge_decision(), adapter)
        await _cycle(adapter, mode="off")
        assert life.hass.read(SWITCH) == "off"
        assert life.hass.read(STRATEGY) == "idle"
        assert life.hass.read(TARGET) == "100"
        assert adapter.last_intent is BatteryIntent.OFF

    @pytest.mark.parametrize("kind,strategy", [
        ("generic", False), ("generic", True), ("goodwe", False)])
    async def test_a_stop_that_fails_records_no_off_and_is_tried_again(
            self, kind, strategy):
        make, actuator, on, off = _KINDS[kind]
        life = _life()
        extra = {"battery_strategy_control_entity": STRATEGY} if strategy else {}
        adapter = make(life, **extra)
        await actuate_battery(_charge_decision(), adapter)
        life.hass.raise_on = _RAISE[actuator]
        await _cycle(adapter, mode="off")
        assert adapter.last_intent is not BatteryIntent.OFF
        assert "stop_forced_charge failed" in adapter.last_error
        assert life.hass.read(actuator) == on
        assert _on_disk(life) == {actuator: ["b1"]}     # kept until it lands
        life.hass.raise_on = None
        await _cycle(adapter, mode="off")
        assert life.hass.read(actuator) == off
        assert adapter.last_intent is BatteryIntent.OFF
        assert adapter.last_error is None
        assert _on_disk(life) == {}

    @pytest.mark.parametrize("kind,strategy", [
        ("generic", False), ("generic", True), ("goodwe", False)])
    async def test_a_stop_that_fails_still_hands_the_limit_back(self, kind, strategy):
        """Review HIGH: the failed stop returned before the zero and the
        limit, so a 0 W hold stayed under Off."""
        make, actuator, _, _ = _KINDS[kind]
        life = _life()
        extra = {"battery_discharge_control_entity": LIMIT,
                 "battery_max_discharge_power": 5000}
        if strategy:
            extra["battery_strategy_control_entity"] = STRATEGY
        adapter = make(life, **extra)
        await adapter.command_limit_discharge(0.0)
        assert float(life.hass.read(LIMIT)) == 0.0
        await actuate_battery(_charge_decision(), adapter)
        life.hass.raise_on = _RAISE[actuator]
        await _cycle(adapter, mode="off")
        assert float(life.hass.read(LIMIT)) == 5000.0
        assert adapter.last_intent is not BatteryIntent.OFF

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_off_leaves_a_charge_sem_did_not_start(self, kind):
        """The twin: the user's own switch or mode is not SEM's to stop."""
        make, actuator, on, _ = _KINDS[kind]
        life = _life()
        life.hass.set(actuator, on)
        adapter = make(life)
        await _cycle(adapter, mode="off")
        assert life.hass.read(actuator) == on
        assert life.hass.sent("turn_off", actuator) == []
        assert life.hass.sent("select_option", actuator) == []


@pytest.mark.asyncio
class TestUnloadStopsTheCharge:

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_unload_sets_the_actuator_back_and_the_target(self, kind):
        make, actuator, _, off = _KINDS[kind]
        life = _life()
        adapter = make(life)
        await actuate_battery(_charge_decision(), adapter)
        outcome = await async_release_batteries_on_unload(_unloading(adapter))
        assert outcome["b1"].startswith("released")
        assert life.hass.read(actuator) == off
        assert life.hass.read(TARGET) == "100"

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_an_unload_whose_stop_fails_says_so_and_still_lifts_the_limit(self, kind):
        make, actuator, on, _ = _KINDS[kind]
        life = _life()
        adapter = make(life, battery_discharge_control_entity=LIMIT,
                       battery_max_discharge_power=5000)
        await adapter.command_limit_discharge(0.0)
        await actuate_battery(_charge_decision(), adapter)
        life.hass.raise_on = _RAISE[actuator]
        outcome = await async_release_batteries_on_unload(_unloading(adapter))
        assert outcome["b1"].startswith("release incomplete")
        assert "stop_forced_charge failed" in outcome["b1"]
        assert float(life.hass.read(LIMIT)) == 5000.0

    async def test_observer_unload_sends_nothing(self):
        life = _life()
        adapter = life.generic()
        await actuate_battery(_charge_decision(), adapter)
        calls = len(life.hass.calls)
        await async_release_batteries_on_unload(_unloading(adapter, observer=True))
        assert life.hass.calls[calls:] == []

    async def test_a_sale_stop_whose_charge_stop_fails_keeps_the_error(self):
        life = _life()
        adapter = life.generic(battery_force_discharge_control_entity=SALE)
        await actuate_battery(_charge_decision(), adapter)
        life.hass.raise_on = ("switch", "turn_off")
        await adapter.command_stop_force_discharge()
        assert adapter.last_intent is BatteryIntent.STOP_FORCE_DISCHARGE
        assert "stop_forced_charge failed" in adapter.last_error
        assert adapter._sem_forced_charge is True        # stopped next cycle

    async def test_a_sale_whose_lifetime_wrote_no_limit_is_stopped(self):
        """Sibling: the release keyed on a limit SEM wrote, and a lifetime
        whose first command was a sale wrote none — the sale went on."""
        life = _life()
        adapter = life.generic(battery_force_discharge_control_entity=SALE)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.FORCE_DISCHARGE,
            discharge_power_w=3000.0, floor_soc=20.0), adapter)
        assert life.hass.read(SALE) == "3000.0"
        assert adapter.last_discharge_limit_w == -1.0
        await async_release_batteries_on_unload(_unloading(adapter))
        assert float(life.hass.read(SALE)) == 0.0

class TestTheUnloadReasons:

    def test_the_reasons_read_the_forced_flags_and_the_setpoint(self):
        def _a(**kw):
            base = dict(_forcible_charging=False, _forcible_discharging=False,
                        _charge_adapter=None, _last_discharge_limit_w=-1.0)
            return SimpleNamespace(**{**base, **kw})
        assert unload_release_reason(_a(_sem_forced_discharge=True), False)
        assert unload_release_reason(_a(_sem_forced_charge=True), False)
        assert unload_release_reason(_a(_last_force_discharge_w=-2200.0), False)
        # the twins: nothing of SEM's in force
        assert unload_release_reason(_a(_sem_forced_charge=False), False) is None
        assert unload_release_reason(_a(_last_force_discharge_w=0.0), False) is None
        assert unload_release_reason(_a(_last_force_discharge_w=None), False) is None
        assert unload_release_reason(_a(_sem_forced_charge=True), True) is None


@pytest.mark.asyncio
class TestARestartMidCharge:

    async def _charged_then_restarted(self, kind):
        make, actuator, on, off = _KINDS[kind]
        first = _life()
        await actuate_battery(_charge_decision(), make(first))
        assert first.hass.read(actuator) == on
        second = _restart(first)
        adapter = make(second)
        await adapter.async_adopt_running_charge()
        return second, adapter, actuator, off

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_night_charging_off_the_next_decision_stops_it(self, kind):
        life, adapter, actuator, off = await self._charged_then_restarted(kind)
        decision = await _cycle(adapter)             # no scheduler
        assert decision.intent is BatteryIntent.STOP_FORCE_CHARGE
        assert life.hass.read(actuator) == off
        assert life.hass.read(TARGET) == "100"
        assert _on_disk(life) == {}
        assert adapter._sem_forced_charge is False

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_an_actuator_that_reads_no_charge_is_not_adopted(self, kind):
        """The charge ended while SEM was down (or the user ended it): the
        name goes, and nothing is sent."""
        make, actuator, on, off = _KINDS[kind]
        first = _life()
        await actuate_battery(_charge_decision(), make(first))
        first.hass.set(actuator, off)
        second = _restart(first)
        adapter = make(second)
        await adapter.async_adopt_running_charge()
        assert forced_ops(adapter) == (None, None)
        assert _on_disk(second) == {}
        first.hass.set(actuator, on)                 # the user's, later
        await adapter.async_adopt_running_charge()
        await _cycle(adapter)
        assert first.hass.read(actuator) == on

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_an_actuator_not_loaded_yet_is_asked_again(self, kind):
        """A stop sent to an entity HA has not loaded yet is dropped
        without a word — and the name with it. So wait until it reads."""
        make, actuator, on, off = _KINDS[kind]
        first = _life()
        await actuate_battery(_charge_decision(), make(first))
        first.hass.set(actuator, "unavailable")
        adapter = make(_restart(first))
        await adapter.async_adopt_running_charge()
        assert forced_ops(adapter) == (None, None)
        assert _on_disk(first) == {actuator: ["b1"]}
        first.hass.set(actuator, on)
        await adapter.async_adopt_running_charge()
        assert forced_ops(adapter) == (True, None)
        await _cycle(adapter)
        assert first.hass.read(actuator) == off

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_off_before_the_actuator_loads_still_stops_it_once_it_reads(self, kind):
        """Review round 2, HIGH: Off recorded on the cycle the actuator
        could not be read stayed silent after the charge was adopted."""
        make, actuator, on, off = _KINDS[kind]
        first = _life()
        await actuate_battery(_charge_decision(), make(first))
        first.hass.set(actuator, "unavailable")
        adapter = make(_restart(first))
        await _cycle(adapter, mode="off")
        assert adapter.last_intent is BatteryIntent.OFF
        first.hass.set(actuator, on)
        for _ in range(3):
            await adapter.async_adopt_running_charge()
            await _cycle(adapter, mode="off")
        assert first.hass.read(actuator) == off
        assert first.hass.read(TARGET) == "100"
        assert _on_disk(first) == {}

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_a_stop_sent_before_the_actuator_loads_keeps_the_name(self, kind):
        """Review round 2, MEDIUM: the night scheduler's stop to an entity
        HA had not loaded "landed", the name went, and the charge ran on."""
        make, actuator, on, off = _KINDS[kind]
        first = _life()
        await actuate_battery(_charge_decision(), make(first))
        first.hass.set(actuator, "unavailable")
        adapter = make(_restart(first))
        idle = SimpleNamespace(state="idle", from_arbitrage=False)
        await adapter.async_adopt_running_charge()
        decision = await _cycle(adapter, sched=idle)
        assert decision.intent is BatteryIntent.STOP_FORCE_CHARGE
        assert _on_disk(first) == {actuator: ["b1"]}
        first.hass.set(actuator, on)
        await adapter.async_adopt_running_charge()
        decision = await _cycle(adapter, sched=idle)
        assert decision.intent is BatteryIntent.STOP_FORCE_CHARGE
        assert first.hass.read(actuator) == off
        assert _on_disk(first) == {}

    async def test_a_pack_in_off_leaves_the_charge_another_pack_started(self):
        """Review LOW: the switch key is not per battery, so both packs
        name the same switch. b2 in Off must not stop b1's charge."""
        first = _life()
        await actuate_battery(_charge_decision(), first.generic("b1"))
        second = _restart(first)
        b2 = second.generic("b2")
        await b2.async_adopt_running_charge()
        assert forced_ops(b2) == (None, None)
        await _cycle(b2, mode="off")
        assert first.hass.read(SWITCH) == "on"
        b1 = second.generic("b1")
        await b1.async_adopt_running_charge()
        assert forced_ops(b1) == (True, None)

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_off_after_the_restart_stops_it(self, kind):
        life, adapter, actuator, off = await self._charged_then_restarted(kind)
        await _cycle(adapter, mode="off")
        assert life.hass.read(actuator) == off
        assert life.hass.read(TARGET) == "100"

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_an_unload_after_the_restart_stops_it(self, kind):
        life, adapter, actuator, off = await self._charged_then_restarted(kind)
        await async_release_batteries_on_unload(_unloading(adapter))
        assert life.hass.read(actuator) == off
        assert life.hass.read(TARGET) == "100"

    async def test_the_adoption_itself_writes_nothing(self):
        first = _life()
        await actuate_battery(_charge_decision(), first.generic())
        calls = len(first.hass.calls)
        adapter = _restart(first).generic()
        await adapter.async_adopt_running_charge()
        assert first.hass.calls[calls:] == []
        assert forced_ops(adapter) == (True, None)

    async def test_the_plan_still_wanting_it_keeps_it(self):
        life, adapter, _, _ = await self._charged_then_restarted("generic")
        sched = SimpleNamespace(state="scheduled", charge_power_w=3000.0,
                                target_soc=60.0, duration_min=60, price_forced=False)
        gate = SimpleNamespace(covered=True, in_block=True, block_power_w=3000.0)
        decision = await _cycle(adapter, sched=sched, gate=gate)
        assert decision.intent is BatteryIntent.FORCE_CHARGE
        assert life.hass.read(SWITCH) == "on"
        assert life.hass.sent("turn_off", SWITCH) == []

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_a_switch_the_user_turned_on_is_left_alone(self, kind):
        """The twin: no record, so no lifetime of SEM's turned it on."""
        make, actuator, on, _ = _KINDS[kind]
        life = _life()
        life.hass.set(actuator, on)
        adapter = make(life)
        await adapter.async_adopt_running_charge()
        assert forced_ops(adapter) == (None, None)
        await _cycle(adapter)
        await _cycle(adapter, mode="off")
        await async_release_batteries_on_unload(_unloading(adapter))
        assert life.hass.read(actuator) == on

    async def test_a_charge_stopped_before_the_restart_is_not_adopted(self):
        first = _life()
        adapter = first.generic()
        await actuate_battery(_charge_decision(), adapter)
        await actuate_battery(_decision(BatteryIntent.STOP_FORCE_CHARGE), adapter)
        first.hass.set(SWITCH, "on")                 # the user's, later
        again = _restart(first).generic()
        await again.async_adopt_running_charge()
        assert again._charge_adapter.is_active is False
        await _cycle(again)
        assert first.hass.read(SWITCH) == "on"


@pytest.mark.asyncio
class TestTheRecord:

    async def test_the_name_is_saved_before_the_switch_goes_on(self):
        life = _life()
        seen = []

        def _spy(domain, service, data):
            if service == "turn_on":
                seen.append(json.loads(life.record._store.raw or "{}"))
        life.hass.spy = _spy
        await actuate_battery(_charge_decision(), life.generic())
        assert seen == [{"running": {SWITCH: ["b1"]}}]

    @pytest.mark.parametrize("kind", list(_KINDS))
    async def test_no_record_no_start(self, kind):
        class _Full(_Store):
            async def async_save(self, data):
                raise OSError("disk full")
        make, actuator, on, _ = _KINDS[kind]
        hass = _Hass()
        life = _Life(hass, _Full(), _Store())
        adapter = make(life)
        await actuate_battery(_charge_decision(), adapter)
        assert hass.read(actuator) != on
        assert hass.read(TARGET) == "100"
        assert adapter.last_intent is not BatteryIntent.FORCE_CHARGE
        assert adapter._sem_forced_charge is not True
        status = await adapter._charge_adapter.start_forced_charge(
            SimpleNamespace(target_soc=60.0, max_power_w=3000, duration_minutes=60))
        assert status.status is ChargeCommandStatus.FAILED
        assert life.record.snapshot() == {}

    @pytest.mark.parametrize("raw", ['{"running": "switch.force_charge"}',
                                     '["switch.force_charge"]',
                                     '{"running": ["switch.force_charge"]}',
                                     '{"running": {"switch.force_charge": "b1"}}',
                                     '{"running": {"switch.force_charge": [1]}}'])
    async def test_a_damaged_record_adopts_nothing_and_the_next_start_writes_over(self, raw):
        life = _life()
        life.record._store.raw = raw
        life.hass.set(SWITCH, "on")
        adapter = life.generic()
        await adapter.async_adopt_running_charge()
        assert forced_ops(adapter) == (None, None)
        await actuate_battery(_charge_decision(), adapter)
        assert _on_disk(life) == {SWITCH: ["b1"]}

    async def test_an_unreadable_record_adopts_nothing(self):
        class _Broken(_Store):
            async def async_load(self):
                raise ValueError("corrupt")
        hass = _Hass()
        hass.set(SWITCH, "on")
        adapter = _Life(hass, _Broken(), _Store()).generic()
        await adapter.async_adopt_running_charge()
        assert forced_ops(adapter) == (None, None)

    async def test_a_failed_start_whose_switch_went_on_keeps_the_name(self):
        """The write may have landed anyway: the next lifetime stops it."""
        life = _life()

        def _lands_then_raises(domain, service, data):
            if service == "turn_on":
                life.hass.set(SWITCH, "on")
        life.hass.spy = _lands_then_raises
        life.hass.raise_on = ("switch", "turn_on")
        await actuate_battery(_charge_decision(), life.generic())
        assert _on_disk(life) == {SWITCH: ["b1"]}

    async def test_a_failed_start_whose_switch_stayed_off_drops_the_name(self):
        """Review MEDIUM: kept, it named a switch the user turned on later
        as SEM's to stop after a restart."""
        life = _life()
        life.hass.raise_on = ("switch", "turn_on")
        await actuate_battery(_charge_decision(), life.generic())
        assert _on_disk(life) == {}

    async def test_two_packs_on_one_mode_select_share_one_name(self):
        life = _life()
        a, b = life.goodwe("b1"), life.goodwe("b2")
        await actuate_battery(_charge_decision(), a)
        await actuate_battery(_charge_decision(), b)
        assert _on_disk(life) == {MODE: ["b1", "b2"]}
        await actuate_battery(_decision(BatteryIntent.STOP_FORCE_CHARGE), a)
        assert _on_disk(life) == {}

    async def test_saves_only_when_something_changes(self):
        class _Counting(_Store):
            saves = 0

            async def async_save(self, data):
                _Counting.saves += 1
                await super().async_save(data)
        hass = _Hass()
        adapter = _Life(hass, _Counting(), _Store()).generic()
        for _ in range(20):
            await actuate_battery(_charge_decision(), adapter)
        assert _Counting.saves == 1


class _FakeStore:
    made: list = []

    def __init__(self, hass, version, key):
        self.key = key
        _FakeStore.made.append(key)


class TestCoordinatorWiring:

    def _coordinator(self, entry_id="entry-1"):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator(MagicMock(), {})
        coord.hass = MagicMock()
        coord.config_entry = SimpleNamespace(entry_id=entry_id)
        return coord

    def test_every_battery_gets_the_one_record_of_the_entry(self):
        _FakeStore.made = []
        with patch("homeassistant.helpers.storage.Store", _FakeStore):
            coord = self._coordinator()
            a = coord._battery_adapter_context("b1", 0, 2)["forced_charge_record"]
            b = coord._battery_adapter_context("b2", 1, 2)["forced_charge_record"]
        assert isinstance(a, ForcedChargeRecord) and a is b
        assert a._store.key == "sem.forced_charge.entry-1"
        assert "sem.forced_charge.entry-1" in _FakeStore.made

    def test_no_entry_no_store(self):
        coord = self._coordinator(entry_id="")
        assert coord._battery_adapter_context("b1")["forced_charge_record"]._store is None

    def test_the_adapters_take_the_injected_record(self):
        record = ForcedChargeRecord()
        for cls in (GenericBatteryAdapter, GoodWeBatteryAdapter):
            assert cls(MagicMock(), {"forced_charge_record": record}
                       )._charge_adapter.charge_record is record

    def test_the_record_goes_on_removal(self):
        from custom_components.solar_energy_management import cleanup
        assert "sem.forced_charge.e1" in cleanup.per_entry_store_keys("e1")

    def test_every_battery_decision_adopts_first_even_in_observer(self):
        """The pipeline asks every adapter — built, rebuilt or cached —
        before ``forced_ops`` reads its flags, and never only outside
        observer mode: adoption reads, the decision then sends nothing."""
        src = (Path(__file__).resolve().parent.parent
               / "coordinator" / "coordinator.py").read_text(encoding="utf-8")
        tree = ast.parse(src)
        parent = {c: p for p in ast.walk(tree) for c in ast.iter_child_nodes(p)}

        def _calls(node, name):
            return [n for n in ast.walk(node) if isinstance(n, ast.Call)
                    and getattr(n.func, "attr", getattr(n.func, "id", "")) == name]

        fns = [f for f in ast.walk(tree) if isinstance(f, ast.AsyncFunctionDef)
               and any(a.args and getattr(a.args[0], "id", "") == "adapter"
                       for a in _calls(f, "forced_ops"))]
        assert len(fns) == 1, "the battery pipeline was not found"
        reads = [c for c in _calls(fns[0], "forced_ops")]
        adopts = _calls(fns[0], "async_adopt_running_charge")
        assert adopts, "the pipeline never adopts a running charge"
        assert min(a.lineno for a in adopts) < min(r.lineno for r in reads)
        for call in adopts:
            node = call
            while node in parent:
                node = parent[node]
                if isinstance(node, ast.If):
                    assert "_observer_mode" not in ast.unparse(node.test), (
                        "adoption must run in observer mode too")
                if isinstance(node, (ast.For, ast.AsyncFor)):
                    break
            assert isinstance(node, (ast.For, ast.AsyncFor)), (
                "adoption must run once per battery, inside the battery loop")
