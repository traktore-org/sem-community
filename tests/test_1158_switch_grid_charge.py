"""#1158 — grid charging on an inverter that has no program groups.

A hybrid inverter read through a stick-logger integration offers a
grid-charge switch, the level a grid charge stops at, and a discharge limit
in PERCENT of its rating. SEM had the adapter for exactly that shape (a
switch plus a target, a number for the limit) and could not use it:

* the integration names its entities in device profiles (one YAML file per
  device family), which the roster crawler never read — so no role was
  offered and nothing was bound;
* the discharge limit is in percent, and every power write refused a unit
  that is not W or kW.

The fix has no brand code. The crawler reads device profiles; the role
lexicon knows three more words; the one power-write path converts watts to
percent of "Maximum battery discharge power". The reporter's profile is the
fixture below, as the integration registers it.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management import hardware_detection as hd
from custom_components.solar_energy_management.consts import role_lexicon as lex
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.battery_adapters import (
    adapter_for,
)
from custom_components.solar_energy_management.coordinator.battery_adapters.generic import (
    GenericBatteryAdapter,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryDecision,
    BatteryIntent,
)
from custom_components.solar_energy_management.coordinator.power_control import (
    entity_max_watts,
    is_percent_control,
    prepare_power_setpoint,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
DOMAIN = "solarman"                     # the fixture's integration

# The control part of the reporter's stock hybrid profile, in the profile
# format: every item has a name and a platform.
PROFILE = """
info:
  manufacturer: Example
parameters:
  - group: Battery
    items:
      - name: "Battery"
        class: "battery"
        uom: "%"
        registers: [3066]
      - name: "Battery Discharging Power"
        platform: number
        uom: "%"
        registers: [3078]
        range: {min: 1, max: 100}
      - name: "Battery Charging Power"
        platform: number
        uom: "%"
        registers: [3079]
        range: {min: 1, max: 100}
      - name: "Battery Grid Max Charge"
        platform: number
        uom: "%"
        registers: [3260]
        range: {min: 20, max: 100}
      - name: "Battery Grid Charging"
        platform: switch
        registers: [3314]
      - name: "Battery Grid Charging Start"
        platform: time
        registers: [3317]
      - name: "Battery Grid Charging End"
        platform: time
        registers: [3318]
      - name: Work Mode
        platform: "select"
        registers: [3044]
        lookup:
          - {key: 0x0000, value: "Self Use"}
          - {key: 0x0001, value: "Time of Use"}
          - {key: 0x0002, value: "Battery Priority"}
"""

SWITCH = "switch.inverter_battery_grid_charging"
TARGET = "number.inverter_battery_grid_max_charge"
LIMIT = "number.inverter_battery_discharging_power"


def _crawler():
    spec = importlib.util.spec_from_file_location(
        "crawl_integration_roster_1158",
        ROOT / "scripts" / "crawl_integration_roster.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = mod
    try:
        spec.loader.exec_module(mod)
    finally:
        sys.modules.pop(spec.name, None)
    return mod


def _roster():
    spec = importlib.util.spec_from_file_location(
        "integration_roster_1158", ROOT / "consts" / "integration_roster.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ───────────────────────── the crawler reads profiles ─────────────────────

@pytest.mark.unit
class TestTheCrawlerReadsDeviceProfiles:
    def test_a_profile_declares_its_controls_by_the_slug_of_their_name(self):
        vocab = _crawler().mine_profile(PROFILE)
        assert set(vocab["switch"]) == {"battery_grid_charging"}
        assert set(vocab["number"]) == {
            "battery_discharging_power", "battery_charging_power",
            "battery_grid_max_charge"}
        assert set(vocab["time"]) == {
            "battery_grid_charging_start", "battery_grid_charging_end"}

    def test_a_selects_lookup_values_are_its_options(self):
        vocab = _crawler().mine_profile(PROFILE)
        assert vocab["select"]["work_mode"]["options"] == (
            "Self Use", "Time of Use", "Battery Priority")

    def test_a_profiles_readings_are_not_read(self):
        """Thirty device families share one domain: pooling their sensors
        would offer one family's meter to another's owner."""
        vocab = _crawler().mine_profile(PROFILE)
        assert "sensor" not in vocab
        assert "battery" not in {k for keys in vocab.values() for k in keys}

    @pytest.mark.parametrize("text", [
        "", "{", "- a\n- b", "parameters: 7",
        "parameters:\n  - items: 3\n  - 4\n  - items: [5, {platform: switch}]",
    ])
    def test_a_broken_profile_is_nothing_not_a_crash(self, text):
        assert _crawler().mine_profile(text) == {}

    def test_the_folder_is_only_asked_for_when_no_control_is_declared(self):
        wants = _crawler()._wants_profiles
        assert wants({}) and wants({"sensor": {"x": {}}, "service": {"y": {}}})
        assert not wants({"number": {"x": {}}})
        assert not wants({"switch": {"x": {}}})

    def test_two_repos_one_domain_the_downloaded_one_wins(self):
        """The roster read an abandoned repo's vocabulary: it had more
        stars, and the successor has all the downloads."""
        crawler = _crawler()
        old = {"domain": "stick", "full_name": "old/stick",
               "description": "solar inverter", "stargazers_count": 700}
        new = {"domain": "stick", "full_name": "new/stick",
               "description": "solar inverter", "stargazers_count": 500,
               "downloads": 50000}
        for order in ((old, new), (new, old)):
            rows = crawler.candidate_rows(
                {"hacs": {str(i): e for i, e in enumerate(order)}})
            assert rows["stick"]["repo"] == "new/stick"

    def test_stars_still_decide_between_two_that_nobody_downloads(self):
        crawler = _crawler()
        a = {"domain": "stick", "full_name": "a/stick",
             "description": "solar inverter", "stargazers_count": 5}
        b = {"domain": "stick", "full_name": "b/stick",
             "description": "solar inverter", "stargazers_count": 9}
        rows = crawler.candidate_rows({"hacs": {"1": a, "2": b}})
        assert rows["stick"]["repo"] == "b/stick"

    def test_the_profile_gives_the_three_roles_through_the_lexicon(self):
        crawler = _crawler()
        roles = crawler.roles_from_vocabulary(
            crawler.mine_profile(PROFILE), lex, "energy", DOMAIN)
        assert roles["battery_force_charge"]["keys"] == ("battery_grid_charging",)
        assert roles["battery_target_soc"]["keys"] == ("battery_grid_max_charge",)
        assert roles["battery_discharge_limit"]["keys"] == (
            "battery_discharging_power",)
        # the work mode is a policy selector: named, never written (#845)
        assert "battery_strategy" in lex.OBSERVE_ONLY_ROLES
        assert roles["battery_strategy"]["keys"] == ("work_mode",)
        # the charge limit stays in watts: no percent path writes it
        assert "battery_charge_limit" not in roles


# ───────────────────────── the committed roster ───────────────────────────

@pytest.mark.unit
class TestTheRosterOffersIt:
    def test_the_three_roles_are_in_the_shipped_roster(self):
        vocab = _roster().ROLE_VOCAB[DOMAIN]
        assert "battery_grid_charging" in vocab["battery_force_charge"]["keys"]
        assert "battery_grid_max_charge" in vocab["battery_target_soc"]["keys"]
        assert "battery_discharging_power" in (
            vocab["battery_discharge_limit"]["keys"])

    def test_a_permission_switch_of_the_same_name_is_not_a_force_charge(self):
        """Elsewhere ``battery_grid_charging`` says the battery MAY charge
        from the grid. Turning it on starts nothing."""
        assert lex.role_for("switch", "battery_grid_charging", DOMAIN) == (
            "battery_force_charge")
        assert lex.role_for("switch", "battery_grid_charging", "fronius") is None
        assert lex.role_for("switch", "battery_grid_charging") is None
        roster = _roster()
        for domain, roles in roster.ROLE_VOCAB.items():
            if domain == DOMAIN:
                continue
            keys = roles.get("battery_force_charge", {}).get("keys", ())
            assert "battery_grid_charging" not in keys, domain

    @pytest.mark.parametrize("key", [
        "battery_generator_charging", "battery_grid_charging_current",
        "battery_grid_charging_start", "battery_grid_charging_start_voltage"])
    def test_its_neighbours_are_not_the_switch(self, key):
        for platform in ("switch", "number"):
            assert lex.role_for(platform, key, DOMAIN) != "battery_force_charge"

    def test_a_reading_of_the_same_name_is_not_a_limit(self):
        assert lex.role_for("sensor", "battery_discharging_power", DOMAIN) != (
            "battery_discharge_limit")


# ───────────────────────── the install: registry → config ─────────────────

def _ent(entity_id, key):
    """An entity as the fixture integration registers it: the translation
    key is the slug of the profile name, the unique id ends in the key and
    the platform."""
    platform = entity_id.split(".", 1)[0]
    return SimpleNamespace(
        entity_id=entity_id, platform=DOMAIN, device_id="inv1",
        translation_key=key, unique_id=f"01hx_{key}_{platform}",
        original_device_class=None, disabled_by=None, config_entry_id="e1")


FIXTURE_ENTITIES = [
    _ent(SWITCH, "battery_grid_charging"),
    _ent(TARGET, "battery_grid_max_charge"),
    _ent(LIMIT, "battery_discharging_power"),
    _ent("number.inverter_battery_charging_power", "battery_charging_power"),
    _ent("select.inverter_work_mode", "work_mode"),
    _ent("time.inverter_battery_grid_charging_start",
         "battery_grid_charging_start"),
]


class _Hass:
    """The fixture inverter: states the test sets, every call recorded, and
    each write lands the way the register takes it."""

    def __init__(self):
        self._states = {
            SWITCH: SimpleNamespace(state="off", attributes={}),
            TARGET: SimpleNamespace(state="100", attributes={
                "unit_of_measurement": "%", "min": 20, "max": 100, "step": 1}),
            LIMIT: SimpleNamespace(state="100", attributes={
                "unit_of_measurement": "%", "min": 1, "max": 100, "step": 1}),
        }
        self.calls: list = []
        self.states = SimpleNamespace(get=self._states.get)
        self.services = SimpleNamespace(async_call=self._call)

    def read(self, entity_id):
        return self._states[entity_id].state

    def set(self, entity_id, value):
        old = self._states[entity_id]
        self._states[entity_id] = SimpleNamespace(
            state=str(value), attributes=old.attributes)

    async def _call(self, domain, service, data, **kw):
        self.calls.append((domain, service, dict(data)))
        ent = data.get("entity_id")
        if service == "turn_on":
            self.set(ent, "on")
        elif service == "turn_off":
            self.set(ent, "off")
        elif service == "set_value":
            self.set(ent, data["value"])

    def sent(self, service, entity_id):
        return [c[2] for c in self.calls
                if c[1] == service and c[2].get("entity_id") == entity_id]


def _proposals(hass):
    return hd.propose_roles_from_roster(
        FIXTURE_ENTITIES, DOMAIN, state_of=hass.states.get)


def _accepted_config(hass, **extra):
    """What one click per proposal writes: each role's own option key."""
    config = {"battery_max_discharge_power": 10000.0, "battery_id": "b1"}
    for prop in _proposals(hass).values():
        if prop.get("action") == "set_option":
            config[prop["config_key"]] = prop["entity"]
    config.update(extra)
    return config


@pytest.mark.unit
class TestTheInstallIsOfferedItsThreeControls:
    def test_each_role_finds_its_entity_with_a_button(self):
        props = _proposals(_Hass())
        want = {"battery_force_charge": (SWITCH, "battery_force_charge_switch"),
                "battery_target_soc": (TARGET, "battery_target_soc_entity"),
                "battery_discharge_limit": (
                    LIMIT, "battery_discharge_control_entity")}
        for role, (entity, key) in want.items():
            assert props[role]["entity"] == entity, role
            assert props[role]["action"] == "set_option", props[role]
            assert props[role]["config_key"] == key

    def test_a_percent_limit_gets_a_button_and_an_ampere_one_does_not(self):
        hass = _Hass()
        hass._states[LIMIT] = SimpleNamespace(state="30", attributes={
            "unit_of_measurement": "A", "min": 0, "max": 100})
        prop = _proposals(hass)["battery_discharge_limit"]
        assert prop["action"] == "unit_mismatch" and prop["unit_seen"] == "A"

    def test_the_work_mode_is_named_and_has_no_button(self):
        prop = _proposals(_Hass())["battery_strategy"]
        assert prop["entity"] == "select.inverter_work_mode"
        assert prop["action"] != "set_option"

    def test_nothing_is_offered_to_an_install_without_the_switch(self):
        """Inert: no entity of that role, no proposal, no option written."""
        ents = [e for e in FIXTURE_ENTITIES if e.entity_id != SWITCH]
        props = hd.propose_roles_from_roster(ents, DOMAIN,
                                             state_of=_Hass().states.get)
        assert "battery_force_charge" not in props
        assert not GenericBatteryAdapter(
            _Hass(), {"battery_target_soc_entity": TARGET}
        ).supports_forced_charge


# ───────────────────────── the pipeline: config → writes ──────────────────

def _adapter(hass, **extra):
    adapter = adapter_for(hass, _accepted_config(hass, **extra))
    adapter._WRITE_GRACE_S = 0.0          # judge the read-back at once
    return adapter


def _charge(soc=80.0):
    return BatteryDecision(battery_id="b1", intent=BatteryIntent.FORCE_CHARGE,
                           target_soc=soc, charge_power_w=3000.0,
                           duration_min=60)


def _limit(watts):
    return BatteryDecision(battery_id="b1",
                           intent=BatteryIntent.LIMIT_DISCHARGE,
                           discharge_limit_w=watts)


@pytest.mark.asyncio
class TestTheGenericAdapterDrivesIt:
    async def test_the_bound_roles_make_a_battery_sem_can_force_charge(self):
        adapter = _adapter(_Hass())
        assert isinstance(adapter, GenericBatteryAdapter)
        assert adapter.supports_forced_charge

    async def test_a_forced_charge_sets_the_level_and_turns_the_switch_on(self):
        hass = _Hass()
        adapter = _adapter(hass)
        await actuate_battery(_charge(80.0), adapter)
        assert hass.read(SWITCH) == "on"
        assert float(hass.read(TARGET)) == 80.0
        assert adapter.last_intent is BatteryIntent.FORCE_CHARGE

    async def test_the_stop_turns_it_off_and_puts_the_level_back(self):
        hass = _Hass()
        adapter = _adapter(hass)
        await actuate_battery(_charge(80.0), adapter)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.STOP_FORCE_CHARGE), adapter)
        assert hass.read(SWITCH) == "off"
        assert float(hass.read(TARGET)) == 100.0
        assert len(hass.sent("turn_on", SWITCH)) == 1
        assert len(hass.sent("turn_off", SWITCH)) == 1

    async def test_observer_mode_withholds_every_write(self):
        hass = _Hass()
        adapter = _adapter(hass)
        for decision in (_charge(), _limit(0.0)):
            await actuate_battery(decision, adapter, observer=True)
        assert hass.calls == []
        assert hass.read(SWITCH) == "off" and hass.read(LIMIT) == "100"

    async def test_watts_go_out_as_percent_of_the_maximum_power(self):
        hass = _Hass()
        adapter = _adapter(hass)                       # 100 % = 10 000 W
        await actuate_battery(_limit(2500.0), adapter)
        assert hass.sent("set_value", LIMIT) == [
            {"entity_id": LIMIT, "value": 25.0}]
        assert adapter.last_discharge_limit_w == 2500.0

    async def test_no_discharge_is_the_least_the_register_can_say(self):
        """The register starts at 1 %. A refused 0 would leave the old limit
        in force — the car would run on the pack."""
        hass = _Hass()
        adapter = _adapter(hass)
        await actuate_battery(_limit(0.0), adapter)
        assert hass.sent("set_value", LIMIT) == [
            {"entity_id": LIMIT, "value": 1.0}]
        assert adapter.last_error is None

    async def test_a_percent_is_never_rounded_up(self):
        hass = _Hass()
        adapter = _adapter(hass)
        # the adapter itself: the actuator steps a limit before it gets here
        await adapter.command_limit_discharge(2590.0)    # 25.9 %
        assert hass.sent("set_value", LIMIT)[-1]["value"] == 25.0

    async def test_the_read_back_is_judged_in_percent(self):
        """Judged as watts, 1 % read as 1 W of a 100 W ask: three strikes
        and a Repair for a write that landed."""
        hass = _Hass()
        adapter = _adapter(hass)
        await actuate_battery(_limit(0.0), adapter)
        assert adapter.verify_pending_write() is True
        assert adapter.write_not_taken_strikes == 0
        await actuate_battery(_limit(2500.0), adapter)
        assert adapter.verify_pending_write() is True

    async def test_a_write_the_register_did_not_take_is_still_a_miss(self):
        hass = _Hass()
        adapter = _adapter(hass)
        await actuate_battery(_limit(2500.0), adapter)
        hass.set(LIMIT, 100)                           # the inverter put it back
        assert adapter.verify_pending_write() is False
        assert "25 %" in adapter.last_unverified_wanted

    async def test_the_same_limit_is_not_written_twice(self):
        hass = _Hass()
        adapter = _adapter(hass)
        for _ in range(4):
            await actuate_battery(_limit(2500.0), adapter)
        assert len(hass.sent("set_value", LIMIT)) == 1

    async def test_normal_gives_the_whole_pack_back(self):
        hass = _Hass()
        adapter = _adapter(hass)
        await actuate_battery(_limit(0.0), adapter)
        await actuate_battery(BatteryDecision(
            battery_id="b1", intent=BatteryIntent.NORMAL), adapter)
        assert float(hass.read(LIMIT)) == 100.0

    async def test_without_a_maximum_power_nothing_is_written_and_it_says_so(self):
        hass = _Hass()
        config = _accepted_config(hass)
        config.pop("battery_max_discharge_power")
        adapter = adapter_for(hass, config)
        await actuate_battery(_limit(0.0), adapter)
        assert hass.sent("set_value", LIMIT) == []
        assert adapter.last_error == adapter.NO_PERCENT_BASE_ERROR
        assert adapter.last_discharge_limit_w == -1.0
        # …and the gap is only an error while a limit is asked for
        adapter._clear_no_limit_error()
        assert adapter.last_error is None


# ───────────────────────── the one power-write path ───────────────────────

def _number(state, unit, **attrs):
    hass = _Hass()
    hass._states["number.x"] = SimpleNamespace(
        state=str(state), attributes={"unit_of_measurement": unit, **attrs})
    return hass


@pytest.mark.unit
class TestPercentIsAPowerUnitOnlyWithABase:
    def test_three_states(self):
        hass = _number(100, "%", min=1, max=100)
        assert is_percent_control(hass, "number.x")
        assert prepare_power_setpoint(hass, "number.x", 500.0) is None
        prepared = prepare_power_setpoint(hass, "number.x", 500.0,
                                          percent_of_w=5000.0)
        assert (prepared.value, prepared.scale_to_watts) == (10.0, 50.0)

    @pytest.mark.parametrize("base", [0, -1, None, "x", float("nan")])
    def test_a_base_that_is_no_power_is_no_base(self, base):
        hass = _number(100, "%", min=1, max=100)
        assert prepare_power_setpoint(hass, "number.x", 500.0,
                                      percent_of_w=base) is None

    def test_a_watt_control_is_untouched_by_a_base(self):
        hass = _number(5000, "W", min=0, max=5000)
        assert not is_percent_control(hass, "number.x")
        assert prepare_power_setpoint(
            hass, "number.x", 1234.0, percent_of_w=9000.0).value == 1234.0
        # …and still refuses what is outside its own range
        assert prepare_power_setpoint(hass, "number.x", 6000.0) is None

    def test_an_ampere_control_stays_refused(self):
        hass = _number(30, "A", min=0, max=100)
        assert prepare_power_setpoint(hass, "number.x", 500.0,
                                      percent_of_w=5000.0) is None

    def test_the_ceiling_of_a_percent_control_is_its_base(self):
        hass = _number(100, "%", min=1, max=100)
        assert entity_max_watts(hass, "number.x") is None
        assert entity_max_watts(hass, "number.x", percent_of_w=8000.0) == 8000.0

    def test_more_than_the_pack_has_is_all_of_it(self):
        hass = _number(40, "%", min=1, max=100)
        assert prepare_power_setpoint(hass, "number.x", 99999.0,
                                      percent_of_w=5000.0).value == 100.0
