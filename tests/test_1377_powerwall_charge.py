"""#1377 — a Tesla Powerwall charged from the grid through three entities.

The reporter's own automation, tested on the real battery: set the backup
reserve to the target, turn "allow grid charging" on, set the operating mode
to ``autonomous``, and afterwards put all three back. SEM does it with its
existing settings and no brand code:

* ``battery_charge_select_entity`` / ``_option`` = the operating mode / autonomous
* ``battery_target_soc_entity`` = the backup reserve (a number, put back by the hold)
* ``battery_force_charge_switch`` = "allow grid charging", now a PERMIT beside
  the select pair (it used to win and start alone)

The fixture is Powerwall-shaped: option names, a step-1 reserve number and a
switch, whose state every write changes.
"""
from __future__ import annotations

import pytest

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
from custom_components.solar_energy_management.coordinator.battery_adapters.charge_target import (
    ChargeTargetHold,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    GenericChargeAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)

MODE = "select.myhome_mode_de_fonctionnement"
PERMIT = "switch.myhome_autoriser_la_recharge_depuis_le_reseau"
RESERVE = "number.myhome_reserve_de_secours"
SOC = "sensor.myhome_pourcentage_charge"
OPTIONS = ["autonomous", "backup", "self_consumption"]


@pytest.fixture(autouse=True)
def _no_cloud_wait(monkeypatch):
    """(#1377) the waits for a cloud read are pinned in
    test_1377_cloud_read_lag.py; here every read counts at once"""
    monkeypatch.setattr(GenericChargeAdapter, "SHOW_WITHIN_S", 0.0)
    monkeypatch.setattr(GenericChargeAdapter, "AWAY_FOR_S", 0.0)


class _Hass:
    """A Powerwall: every write lands and changes the entity's state."""

    def __init__(self, mode="self_consumption", permit="off", reserve="20"):
        self._states = {
            MODE: SimpleNamespace(state=mode, attributes={"options": OPTIONS}),
            PERMIT: SimpleNamespace(state=permit, attributes={}),
            RESERVE: SimpleNamespace(state=reserve, attributes={"step": 1}),
            SOC: SimpleNamespace(state="35", attributes={}),
        }
        self.calls: list[tuple] = []
        self.refuse_mode = False
        self.refuse_permit = False
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def put(self, eid, value):
        old = self._states[eid]
        self._states[eid] = SimpleNamespace(state=value,
                                            attributes=old.attributes)

    def read(self, eid):
        return self._states[eid].state

    async def _call(self, domain, service, data, **kw):
        self.calls.append((domain, service, dict(data)))
        eid = data["entity_id"]
        if service == "select_option" and not self.refuse_mode:
            self.put(eid, data["option"])
        elif service in ("turn_on", "turn_off") and not (
                self.refuse_permit and service == "turn_on"):
            self.put(eid, service[5:])
        elif service == "set_value":
            self.put(eid, str(data["value"]))

    def writes(self, domain=None):
        return [c for c in self.calls if domain is None or c[0] == domain]


class _Store:
    def __init__(self):
        self.raw = None

    async def async_load(self):
        return None if self.raw is None else json.loads(self.raw)

    async def async_save(self, data):
        self.raw = json.dumps(data)


def _adapter(hass, record_store, hold_store=None, **extra):
    cfg = {
        "battery_charge_select_entity": MODE,
        "battery_charge_select_option": "autonomous",
        "battery_force_charge_switch": PERMIT,
        "battery_target_soc_entity": RESERVE,
        "battery_soc_entity": SOC,
        "forced_charge_record": ForcedChargeRecord(record_store),
        "charge_target_hold": ChargeTargetHold(
            hass, hold_store, configured=(RESERVE,)),
        "battery_id": "b1", **extra}
    return GenericBatteryAdapter(hass, cfg)


def _charge(soc=100.0):
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=soc, charge_power_w=5000.0,
                           duration_min=240)


def _stop():
    return BatteryDecision(battery_id="b1",
                           intent=BatteryIntent.STOP_FORCE_CHARGE)


def _shape(hass):
    return [(c[0], c[1], c[2].get("option") or c[2].get("value")
             or c[2]["entity_id"]) for c in hass.calls]


class TestConfigurationAlone:
    def test_the_reporters_entities_make_a_charge_command(self):
        a = _adapter(_Hass(), _Store())
        assert a.supports_forced_charge is True
        assert a.charge_command_configured is True

    def test_without_the_pair_the_switch_is_still_the_start(self):
        a = GenericBatteryAdapter(_Hass(), {
            "battery_force_charge_switch": PERMIT,
            "battery_target_soc_entity": RESERVE, "battery_id": "b1"})
        assert a.supports_forced_charge is True
        assert a._charge_adapter.charge_actuator() == PERMIT


class TestStartAndStop:
    async def test_one_start_writes_the_three_entities_once(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_charge(), a)             # a second cycle
        assert _shape(hass) == [("number", "set_value", 100),
                                ("switch", "turn_on", PERMIT),
                                ("select", "select_option", "autonomous")]

    async def test_the_stop_puts_all_three_back(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.read(MODE) == "self_consumption"
        assert hass.read(PERMIT) == "off"
        assert float(hass.read(RESERVE)) == 20
        n = len(hass.calls)
        await actuate_battery(_stop(), a)               # nothing more
        assert len(hass.calls) == n

    async def test_the_old_values_are_on_disk_before_the_first_write(self):
        hass, rec, hold = _Hass(), _Store(), _Store()
        seen = []
        orig = hass._call

        async def spy(domain, service, data, **kw):
            seen.append((service, rec.raw, hold.raw))
            await orig(domain, service, data, **kw)
        hass.services.async_call = spy
        await actuate_battery(_charge(), _adapter(hass, rec, hold))
        for _service, rec_raw, hold_raw in seen:
            saved = json.loads(rec_raw)
            assert saved["prior"][MODE] == "self_consumption"
            assert saved["prior"][PERMIT] == "off"
            assert json.loads(hold_raw)["entities"][RESERVE]["prior"] == 20

    async def test_a_permit_already_on_is_the_users_and_stays_on(self):
        hass = _Hass(permit="on")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.writes("switch") == []
        assert hass.read(PERMIT) == "on"

    async def test_a_permit_turned_off_by_hand_is_not_written_over(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        hass.put(PERMIT, "off")
        n = len(hass.writes("switch"))
        await actuate_battery(_stop(), a)
        # never turned on again; (#1377) "off" goes out once, in case SEM's
        # own "on" is still on its way in the cloud
        assert [c[1] for c in hass.writes("switch")[n:]] == ["turn_off"]
        assert hass.read(PERMIT) == "off"

    async def test_a_mode_chosen_by_hand_is_left_alone(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        hass.put(MODE, "backup")
        await actuate_battery(_stop(), a)
        assert hass.read(MODE) == "backup"
        assert hass.read(PERMIT) == "off"


class TestRefusals:
    async def test_an_unreadable_permit_writes_nothing(self):
        hass = _Hass(permit="unavailable")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        assert hass.calls == []
        assert "unavailable" in a.last_error

    async def test_a_mode_that_refuses_is_tried_twice_and_the_permit_goes_back(self):
        hass = _Hass()
        hass.refuse_mode = True
        a = _adapter(hass, _Store(), _Store())
        for _ in range(10):
            await actuate_battery(_charge(), a)
        options = [c[2]["option"] for c in hass.writes("select")]
        # bounded, said; (#1377) then the old mode once
        assert options == ["autonomous", "autonomous", "self_consumption"]
        assert a.charge_refused is True
        assert hass.read(PERMIT) == "off"               # the permit is not left on

    async def test_a_failed_permit_write_releases_the_reserve(self):
        hass = _Hass()
        orig = hass._call

        async def boom(domain, service, data, **kw):
            if domain == "switch":
                raise RuntimeError("cloud timeout")
            await orig(domain, service, data, **kw)
        hass.services.async_call = boom
        hold = _Store()
        a = _adapter(hass, _Store(), hold)
        await actuate_battery(_charge(), a)
        assert hass.writes("select") == []
        assert json.loads(hold.raw)["entities"][RESERVE]["pending"] is True


class TestRestartAndUnload:
    async def test_a_restart_mid_charge_puts_all_three_back(self):
        hass, rec, hold = _Hass(), _Store(), _Store()
        await actuate_battery(_charge(), _adapter(hass, rec, hold))
        fresh = _adapter(hass, rec, hold)               # a new lifetime
        await fresh.async_adopt_running_charge()
        await actuate_battery(_stop(), fresh)
        assert hass.read(MODE) == "self_consumption"
        assert hass.read(PERMIT) == "off"
        assert float(hass.read(RESERVE)) == 20

    async def test_the_unload_abort_puts_the_mode_and_the_permit_back(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await async_release_batteries_on_unload(
            SimpleNamespace(_observer_mode=False, _battery_adapters={"b1": a}))
        assert hass.read(MODE) == "self_consumption"
        assert hass.read(PERMIT) == "off"

    async def test_settings_cleared_before_the_restart_still_restores(self):
        hass, rec = _Hass(), _Store()
        await actuate_battery(_charge(), _adapter(hass, rec, _Store()))
        bare = GenericBatteryAdapter(hass, {
            "forced_charge_record": ForcedChargeRecord(rec),
            "battery_id": "b1"})
        await bare.async_adopt_running_charge()
        assert hass.read(MODE) == "self_consumption"
        assert hass.read(PERMIT) == "off"

    async def test_the_permit_is_not_an_orphan_while_the_charge_is_set_up(self):
        hass, rec, hold = _Hass(), _Store(), _Store()
        await actuate_battery(_charge(), _adapter(hass, rec, hold))
        n = len(hass.calls)
        await _adapter(hass, rec, hold).async_adopt_running_charge()
        assert len(hass.calls) == n and hass.read(PERMIT) == "on"


class TestObserver:
    async def test_observer_sends_and_saves_nothing(self):
        hass, rec = _Hass(), _Store()
        seen = []
        controller = SimpleNamespace(
            publish_observer_decision=lambda **kw: seen.append(kw))
        await actuate_battery(_charge(), _adapter(hass, rec, _Store()),
                              observer=True, controller=controller)
        assert hass.calls == [] and rec.raw is None
        assert seen and seen[0]["action"] == "force_charge"

    async def test_observer_keeps_the_record_after_a_restart(self):
        hass, rec, hold = _Hass(), _Store(), _Store()
        await actuate_battery(_charge(), _adapter(hass, rec, hold))
        bare = GenericBatteryAdapter(hass, {
            "forced_charge_record": ForcedChargeRecord(rec),
            "battery_id": "b1"})
        n = len(hass.calls)
        await bare.async_adopt_running_charge(observer=True)
        assert len(hass.calls) == n and hass.read(PERMIT) == "on"


class TestReview:
    async def test_an_unreadable_permit_at_the_stop_never_holds_the_reserve(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        hass.put(PERMIT, "unavailable")
        await actuate_battery(_stop(), a)
        assert float(hass.read(RESERVE)) == 20           # not held at 100
        assert hass.read(MODE) == "self_consumption"
        assert "unavailable" in a.last_error
        hass.put(PERMIT, "on")                           # it answers again
        await actuate_battery(_stop(), a)                # the stop is retried
        assert hass.read(PERMIT) == "off"

    async def test_an_unreadable_mode_at_the_stop_still_restores_the_reserve(self):
        hass = _Hass()
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        hass.put(MODE, "unavailable")
        await actuate_battery(_stop(), a)
        assert float(hass.read(RESERVE)) == 20
        assert hass.read(PERMIT) == "off"

    async def test_a_permit_that_ignores_turn_on_is_bounded_said_and_undone(self):
        hass = _Hass()
        hass.refuse_permit = True
        a = _adapter(hass, _Store(), _Store())
        for _ in range(10):
            await actuate_battery(_charge(), a)
        # the start + one try, then (#1377) "off" once
        assert [c[1] for c in hass.writes("switch")] == [
            "turn_on", "turn_on", "turn_off"]
        assert hass.read(MODE) == "self_consumption"     # given up, put back
        assert float(hass.read(RESERVE)) == 20
        assert a.charge_refused is True
        assert "did not turn on" in a.last_error
        assert a.last_intent is not BatteryIntent.FORCE_CHARGE

    async def test_a_slow_permit_is_given_a_minute_not_two_cycles(self):
        """(#1377 review 2) a cloud switch that shows "on" after 30 s is a
        charge, not a refusal: no give-up within ~60 s, one re-send."""
        hass = _Hass()
        hass.refuse_permit = True
        a = _adapter(hass, _Store(), _Store())
        for _ in range(4):                               # ~40 s of "off"
            await actuate_battery(_charge(), a)
        assert a.charge_refused is False
        assert hass.read(MODE) == "autonomous"
        assert len(hass.writes("switch")) == 2           # the start + one re-send
        hass.refuse_permit = False
        hass.put(PERMIT, "on")                           # it shows on, late
        for _ in range(5):
            await actuate_battery(_charge(), a)
        assert a.charge_refused is False and a.last_intent is BatteryIntent.FORCE_CHARGE
        assert len(hass.writes("switch")) == 2

    async def test_a_crash_before_the_select_write_puts_the_permit_back(self):
        hass, rec, hold = _Hass(), _Store(), _Store()
        await actuate_battery(_charge(), _adapter(hass, rec, hold))
        hass.put(MODE, "self_consumption")       # the select write never came
        fresh = _adapter(hass, rec, hold)
        await fresh.async_adopt_running_charge(observer=True)
        assert hass.read(PERMIT) == "on"                 # observer: nothing sent
        await fresh.async_adopt_running_charge()
        assert hass.read(PERMIT) == "off"


class TestTheModeAlreadyShowsTheOption:
    """(#1377, beta.20) The operating mode already read "autonomous" when the
    charge began — time-based control, or a mode left from a test. SEM saw
    "the select already shows the charge option", wrote neither the reserve
    nor the permit, and still reported charging: "commanded force_charge,
    not observed", 0 W."""

    async def test_the_reserve_and_the_permit_are_still_set(self):
        hass = _Hass(mode="autonomous")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        assert float(hass.read(RESERVE)) == 100
        assert hass.read(PERMIT) == "on"
        assert hass.writes("select") == [], "the mode is already right"

    async def test_once_per_charge_not_every_cycle(self):
        hass = _Hass(mode="autonomous")
        a = _adapter(hass, _Store(), _Store())
        for _ in range(3):
            await actuate_battery(_charge(), a)
        assert _shape(hass) == [("number", "set_value", 100),
                                ("switch", "turn_on", PERMIT)]

    async def test_the_stop_puts_back_only_what_sem_changed(self):
        hass = _Hass(mode="autonomous")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert float(hass.read(RESERVE)) == 20
        assert hass.read(PERMIT) == "off"
        assert hass.read(MODE) == "autonomous", "the mode was the user's"
        assert hass.writes("select") == []

    async def test_a_permit_already_on_stays_the_users(self):
        hass = _Hass(mode="autonomous", permit="on")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await actuate_battery(_stop(), a)
        assert hass.writes("switch") == []
        assert hass.read(PERMIT) == "on"
        assert float(hass.read(RESERVE)) == 20

    async def test_a_permit_that_ignores_turn_on_is_given_up_not_rewritten(self):
        hass = _Hass(mode="autonomous")
        hass.refuse_permit = True
        a = _adapter(hass, _Store(), _Store())
        for _ in range(12):
            await actuate_battery(_charge(), a)
        turn_ons = [c for c in hass.writes("switch") if c[1] == "turn_on"]
        assert len(turn_ons) == 2, "the start and one retry, then no more"
        assert float(hass.read(RESERVE)) == 20, "the reserve went back"
        assert a.last_error and "did not turn on" in a.last_error

    async def test_without_a_permit_or_target_nothing_changes(self):
        # a select-only setup (another brand): the option alone is the
        # charge, so a select already on it is joined as before, unwritten
        hass = _Hass(mode="autonomous")
        a = GenericBatteryAdapter(hass, {
            "battery_charge_select_entity": MODE,
            "battery_charge_select_option": "autonomous",
            "forced_charge_record": ForcedChargeRecord(_Store()),
            "battery_id": "b1"})
        await actuate_battery(_charge(), a)
        assert hass.calls == []

    async def test_observer_sends_nothing_here_either(self):
        hass = _Hass(mode="autonomous")
        controller = SimpleNamespace(publish_observer_decision=lambda **kw: None)
        await actuate_battery(_charge(), _adapter(hass, _Store(), _Store()),
                              observer=True, controller=controller)
        assert hass.calls == []


class TestTheDiagnosticsShowTheChargePath:
    async def test_the_three_entities_and_what_sem_did(self):
        from custom_components.solar_energy_management.coordinator.battery_diag import (
            battery_actuation_diag,
        )
        hass = _Hass(mode="autonomous")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        coord = SimpleNamespace(_battery_adapters={"b1": a})
        path = battery_actuation_diag(hass, coord)["b1"]["charge_path"]
        assert path["select"] == {"entity": MODE, "reads": "autonomous",
                                  "option": "autonomous"}
        assert path["switch"] == {"entity": PERMIT, "reads": "on", "role": "permit"}
        assert path["target"]["entity"] == RESERVE
        assert float(path["target"]["reads"]) == 100
        assert path["active"] is True
        assert path["last"].startswith("start: charging")


class TestTheJoinedChargeEndsCleanly:
    """(#1377 review) Every way a joined charge ends puts back the reserve
    and the permit, and never writes the mode."""

    async def test_a_restart_mid_charge_puts_the_permit_and_reserve_back(self):
        hass, rec, hold = _Hass(mode="autonomous"), _Store(), _Store()
        await actuate_battery(_charge(), _adapter(hass, rec, hold))
        fresh = _adapter(hass, rec, hold)               # a new lifetime
        await fresh.async_adopt_running_charge()
        await actuate_battery(_stop(), fresh)
        assert hass.read(PERMIT) == "off"
        assert float(hass.read(RESERVE)) == 20
        assert hass.read(MODE) == "autonomous"
        assert hass.writes("select") == []

    async def test_the_unload_abort_puts_the_permit_back(self):
        hass = _Hass(mode="autonomous")
        a = _adapter(hass, _Store(), _Store())
        await actuate_battery(_charge(), a)
        await async_release_batteries_on_unload(
            SimpleNamespace(_observer_mode=False, _battery_adapters={"b1": a}))
        assert hass.read(PERMIT) == "off"
        assert hass.read(MODE) == "autonomous"
        assert hass.writes("select") == []

    async def test_a_mode_changed_by_hand_ends_the_charge_and_is_not_forced_back(self):
        hass, hold = _Hass(mode="autonomous"), _Store()
        a = _adapter(hass, _Store(), hold)
        await actuate_battery(_charge(), a)
        hass.put(MODE, "self_consumption")              # the user's choice
        await actuate_battery(_charge(), a)
        assert hass.writes("select") == []
        assert hass.read(PERMIT) == "off"
        # the reserve is released: it goes back on the next cycle without
        # a charge (the hold's own rule, #1180)
        assert json.loads(hold.raw)["entities"][RESERVE]["pending"] is True

    async def test_two_packs_on_one_mode_the_first_stop_keeps_the_permit(self):
        # one record and one hold for the whole install, as the coordinator
        # hands them to every adapter
        hass = _Hass(mode="autonomous")
        shared = {"forced_charge_record": ForcedChargeRecord(_Store()),
                  "charge_target_hold": ChargeTargetHold(
                      hass, _Store(), configured=(RESERVE,))}
        a = _adapter(hass, _Store(), _Store(), **shared)
        b = _adapter(hass, _Store(), _Store(), battery_id="b2", **shared)
        await actuate_battery(_charge(), a)
        await actuate_battery(BatteryDecision(
            battery_id="b2", intent=BatteryIntent.FORCE_CHARGE, target_soc=100.0,
            charge_power_w=5000.0, duration_min=240), b)
        await actuate_battery(_stop(), a)
        assert hass.read(PERMIT) == "on", "b2 still charges"
        await actuate_battery(BatteryDecision(
            battery_id="b2", intent=BatteryIntent.STOP_FORCE_CHARGE), b)
        assert hass.read(PERMIT) == "off"
        assert hass.writes("select") == []
