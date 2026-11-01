"""#1256 — a battery's settings rejoin it, and the Repair can fix its sensors.

Remove a battery's power sensor and the "no power sensor" Repair came, naming
that one sensor. Its SEM settings (reserve SOC, mode, discharge entities) were
dropped with its place in the battery list, so a sensor that came back was a
new battery with nothing set. Now:

* a removed battery's slot values are parked by its unit and given back when
  the unit returns (``realign_battery_slots``);
* the battery Repair lists every battery sensor and control that is gone
  (``battery_sensor_check``) and is fixable: its flow picks a replacement for
  each one SEM can re-point, and the battery's settings follow its sensor.
"""
from __future__ import annotations

import importlib.util
from unittest.mock import patch

import pytest
from homeassistant.helpers import issue_registry as ir

from custom_components.solar_energy_management import repairs
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator import (
    repair_issues as ri,
)
from custom_components.solar_energy_management.coordinator.battery_controls import (
    BATTERY_SLOT_UNITS_KEY, PARKED_SETTINGS_KEY, realign_battery_slots,
    rename_battery_unit,
)
from custom_components.solar_energy_management.coordinator.battery_sensor_check import (
    apply_replacements, battery_problems, candidates,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.ha_energy_reader import (
    EnergyDashboardConfig,
)

_HAS_PHACC = importlib.util.find_spec("pytest_homeassistant_custom_component") is not None
real_ha = pytest.mark.skipif(
    not _HAS_PHACC,
    reason="pytest-homeassistant-custom-component not installed; CI runs these",
)

A, B = "sensor.pack_a_power", "sensor.pack_b_power"
MONO = "time.monotonic"
WAIT = ri.UNAVAILABLE_REPAIR_THRESHOLD_S
COUNTER = "sensor.battery_charge_total"


# ── a returning battery gets its settings back ─────────────────────────────

def _two_batteries():
    return {
        BATTERY_SLOT_UNITS_KEY: [A, B],
        "battery_modes": ["force_discharge", "off"],
        "battery_reserve_socs": [30, 0],
        "battery_discharge_control_entities": ["number.a_limit", "number.b_limit"],
    }


def _apply(saved, changes):
    return {**saved, **changes}


def test_a_removed_battery_is_parked_and_comes_back_with_its_settings():
    saved = _two_batteries()
    changes, moved = realign_battery_slots(saved, [B])
    assert moved is True
    assert changes["battery_reserve_socs"] == [0] or changes["battery_reserve_socs"] == []
    assert changes[PARKED_SETTINGS_KEY][A] == {
        "battery_modes": "force_discharge",
        "battery_reserve_socs": 30,
        "battery_discharge_control_entities": "number.a_limit",
    }
    gone = _apply(saved, changes)

    # the sensor comes back — as b2 again, with everything it had
    changes, _ = realign_battery_slots(gone, [B, A])
    back = _apply(gone, changes)
    assert back[BATTERY_SLOT_UNITS_KEY] == [B, A]
    assert back["battery_modes"] == ["off", "force_discharge"]
    assert back["battery_reserve_socs"] == [0, 30]
    assert back["battery_discharge_control_entities"] == [
        "number.b_limit", "number.a_limit"]
    assert A not in back[PARKED_SETTINGS_KEY]


def test_a_returning_battery_may_come_back_first():
    gone = _apply(_two_batteries(), realign_battery_slots(_two_batteries(), [B])[0])
    changes, _ = realign_battery_slots(gone, [A, B])
    back = _apply(gone, changes)
    assert back["battery_reserve_socs"] == [30, 0]
    assert back["battery_modes"] == ["force_discharge", "off"]


def test_a_battery_never_seen_before_still_starts_unset():
    gone = _apply(_two_batteries(), realign_battery_slots(_two_batteries(), [B])[0])
    changes, _ = realign_battery_slots(gone, [B, "sensor.other_power"])
    new = _apply(gone, changes)
    assert new["battery_reserve_socs"] == [0]
    assert new["battery_modes"] == ["off"]
    assert A in new[PARKED_SETTINGS_KEY], "A is still waiting for its own sensor"


def test_only_the_newest_batteries_stay_parked():
    saved = {BATTERY_SLOT_UNITS_KEY: [f"sensor.p{i}" for i in range(12)],
             "battery_reserve_socs": list(range(10, 22))}
    changes, _ = realign_battery_slots(saved, ["sensor.p11"])
    parked = changes[PARKED_SETTINGS_KEY]
    assert len(parked) == 8
    assert "sensor.p10" in parked and "sensor.p0" not in parked


def test_a_battery_with_nothing_set_is_not_parked():
    saved = {BATTERY_SLOT_UNITS_KEY: [A, B], "battery_reserve_socs": [None, 40]}
    changes, _ = realign_battery_slots(saved, [B])
    assert PARKED_SETTINGS_KEY not in changes


def test_a_replacement_carries_the_old_units_settings():
    saved = {**_two_batteries(), PARKED_SETTINGS_KEY: {"sensor.gone": {
        "battery_reserve_socs": 45}}}
    # still a battery of the record: the record follows it
    assert rename_battery_unit(saved, A, "sensor.pack_a_new")[
        BATTERY_SLOT_UNITS_KEY] == ["sensor.pack_a_new", B]
    # parked: the values wait for the new unit
    changes = rename_battery_unit(saved, "sensor.gone", "sensor.new")
    assert changes[PARKED_SETTINGS_KEY] == {"sensor.new": {"battery_reserve_socs": 45}}
    # a battery that never had a power sensor: the one parked battery
    changes = rename_battery_unit(saved, "", "sensor.new")
    assert list(changes[PARKED_SETTINGS_KEY]) == ["sensor.new"]
    # two parked and no name: no guess
    two = {PARKED_SETTINGS_KEY: {"sensor.x": {"battery_modes": "off"},
                                 "sensor.y": {"battery_modes": "auto"}}}
    assert rename_battery_unit(two, "", "sensor.new") == {}
    # and the swap finishes the job through the same alignment
    renamed = _apply(saved, rename_battery_unit(saved, "sensor.gone", "sensor.new"))
    changes, _ = realign_battery_slots(renamed, [A, B, "sensor.new"])
    assert _apply(renamed, changes)["battery_reserve_socs"] == [30, 0, 45]


# ── the check names every battery entity that is gone ─────────────────────

def _wired_config():
    return {
        "battery_power_sensor": "sensor.old_power",
        "battery_soc_sensor": "sensor.old_soc",
        "battery_charge_energy_sensor": "sensor.old_charged",
        "battery_discharge_control_entities": ["number.old_limit", "number.live_limit"],
    }


def _states(hass):
    hass.states.async_set("number.live_limit", "50")
    hass.states.async_set("sensor.live_power", "-400", {
        "unit_of_measurement": "W", "device_class": "power"})
    hass.states.async_set("sensor.live_soc", "55", {
        "unit_of_measurement": "%", "device_class": "battery"})
    hass.states.async_set("sensor.live_kwh", "9", {
        "unit_of_measurement": "kWh", "device_class": "energy"})
    hass.states.async_set("number.live_other", "5")
    hass.states.async_set("sensor.room_temp", "21", {
        "unit_of_measurement": "°C", "device_class": "temperature"})


async def test_the_check_lists_every_battery_entity_that_is_gone(hass):
    _states(hass)
    rows = battery_problems(hass, _wired_config())
    assert {r["entity"]: r["role"] for r in rows} == {
        "sensor.old_power": "power", "sensor.old_soc": "soc",
        "sensor.old_charged": "energy", "number.old_limit": "control"}
    assert all(r["editable"] for r in rows)
    limit = next(r for r in rows if r["entity"] == "number.old_limit")
    assert limit["places"] == [["config", "battery_discharge_control_entities", 0]]


async def test_an_unavailable_entity_is_gone_too(hass):
    _states(hass)
    hass.states.async_set("sensor.old_soc", "unavailable")
    rows = battery_problems(hass, {"battery_soc_sensor": "sensor.old_soc"})
    assert [r["entity"] for r in rows] == ["sensor.old_soc"]


async def test_the_dashboard_sensors_are_listed_but_not_ours_to_change(hass):
    _states(hass)
    ed = EnergyDashboardConfig(
        battery_power_list=["sensor.dash_power"], battery_soc_list=["sensor.dash_soc"],
        battery_unit_counters={"sensor.dash_power": ("sensor.dash_in", "sensor.dash_out")})
    rows = battery_problems(hass, {}, ed)
    assert {r["entity"] for r in rows} == {
        "sensor.dash_power", "sensor.dash_soc", "sensor.dash_in", "sensor.dash_out"}
    assert not any(r["editable"] for r in rows)


async def test_candidates_are_of_the_role_not_a_brand(hass):
    _states(hass)
    row = lambda entity, role: {"entity": entity, "role": role}  # noqa: E731
    assert candidates(hass, row("sensor.old_power", "power")) == ["sensor.live_power"]
    assert candidates(hass, row("sensor.old_soc", "soc")) == ["sensor.live_soc"]
    assert candidates(hass, row("sensor.old_charged", "energy")) == ["sensor.live_kwh"]
    # a control is replaced by one of its own domain, one already used is left out
    assert candidates(hass, row("number.old_limit", "control"),
                      taken=["number.live_limit"]) == ["number.live_other"]


def test_a_replacement_keeps_its_list_slot():
    rows = [{"entity": "number.old_limit", "role": "control", "places": [
        ["config", "battery_discharge_control_entities", 1]]},
        {"entity": "sensor.old_soc", "role": "soc", "places": [
            ["config", "battery_soc_sensor", None]]}]
    merged = {"battery_discharge_control_entities": ["number.a", "number.old_limit"]}
    assert apply_replacements(
        merged, {"number.old_limit": "number.new", "sensor.old_soc": "sensor.new_soc"},
        rows) == {"battery_discharge_control_entities": ["number.a", "number.new"],
                  "battery_soc_sensor": "sensor.new_soc"}


# ── the Repair, end to end ─────────────────────────────────────────────────

def _entry(hass, **options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=DOMAIN, data={}, options=options)
    entry.add_to_hass(hass)
    return entry


def _battery_without_power() -> EnergyDashboardConfig:
    return EnergyDashboardConfig(
        battery_charge_energy=COUNTER, battery_discharge_energy="sensor.battery_out",
        has_battery=True)


def _raise(hass, ed):
    hass.states.async_set(COUNTER, "100", {"unit_of_measurement": "kWh"})
    r = SensorReader(hass, {})
    r._sign_vote_warmup = 0
    r.set_energy_dashboard_config(ed)
    for t in (0.0, WAIT + 10):
        with patch(MONO, return_value=t):
            r.read_power()
            r.report_unsourced_power(waiting=False)
    return ir.async_get(hass).async_get_issue(DOMAIN, "power_sensor_not_found_battery")


@real_ha
async def test_the_battery_repair_lists_the_other_missing_sensors_and_is_fixable(hass):
    _states(hass)
    _entry(hass, **_wired_config())
    issue = _raise(hass, _battery_without_power())

    assert issue is not None
    assert issue.is_fixable is True
    assert issue.translation_key == "power_sensor_not_found_fixable"
    listed = issue.translation_placeholders["missing"]
    for gone in ("sensor.old_power", "sensor.old_soc", "sensor.old_charged",
                 "number.old_limit"):
        assert gone in listed
    assert "number.live_limit" not in listed


async def test_a_battery_beside_others_keeps_the_dashboard_only_text(hass):
    """Only the dashboard can add the unit's power sensor, so with nothing
    else of ours to fix the Repair stays a notice."""
    _states(hass)
    rows = battery_problems(hass, {}, None, unsourced=COUNTER, beside=True)
    assert [r["editable"] for r in rows] == [False]
    ri.raise_power_sensor_not_found(
        hass, "battery", energy_entity=COUNTER, beside=True, rows=rows)
    issue = ir.async_get(hass).async_get_issue(DOMAIN, "power_sensor_not_found_battery")
    assert issue.is_fixable is False
    assert issue.translation_key == "power_sensor_not_found_unit"


@real_ha
async def test_the_flow_repoints_the_config_and_the_settings_follow(hass):
    _states(hass)
    entry = _entry(
        hass, **_wired_config(),
        **{BATTERY_SLOT_UNITS_KEY: ["sensor.old_power"],
           "battery_reserve_socs": [35], "battery_modes": ["force_discharge"]})
    issue = _raise(hass, _battery_without_power())
    flow = await repairs.async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass

    answers = {"sensor.old_power": "sensor.live_power", "sensor.old_soc": "sensor.live_soc",
               "sensor.old_charged": "sensor.live_kwh",
               "number.old_limit": "number.live_other"}
    result = await flow.async_step_init()
    asked = []
    while result["type"] == "form":
        assert result["step_id"] == "pick"
        old = result["description_placeholders"]["old"]
        asked.append(old)
        # only entities of the role are on offer
        allowed = result["data_schema"].schema["replacement"].config["include_entities"]
        assert answers.get(old, "x") in allowed
        result = await flow.async_step_pick({"replacement": answers.get(old)})
    assert result["type"] == "create_entry"
    assert set(asked) >= set(answers)

    opts = entry.options
    assert opts["battery_power_sensor"] == "sensor.live_power"
    assert opts["battery_soc_sensor"] == "sensor.live_soc"
    assert opts["battery_charge_energy_sensor"] == "sensor.live_kwh"
    assert opts["battery_discharge_control_entities"] == [
        "number.live_other", "number.live_limit"]
    # the battery is the same battery under its new sensor
    assert opts[BATTERY_SLOT_UNITS_KEY] == ["sensor.live_power"]
    assert opts["battery_reserve_socs"] == [35]
    assert opts["battery_modes"] == ["force_discharge"]


@real_ha
async def test_the_flow_hands_parked_settings_to_the_new_power_sensor(hass):
    """Battery A lost its sensor while B read: its settings are parked. The
    user names A's replacement; the next alignment gives them to it."""
    _states(hass)
    parked = {"sensor.pack_a_old": {"battery_reserve_socs": 30,
                                    "battery_modes": "force_discharge"}}
    entry = _entry(hass, **{BATTERY_SLOT_UNITS_KEY: [B], "battery_reserve_socs": [0],
                            PARKED_SETTINGS_KEY: parked})
    issue = _raise(hass, _battery_without_power())
    assert issue.is_fixable is True
    flow = await repairs.async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass

    result = await flow.async_step_init()
    assert result["description_placeholders"]["old"] == COUNTER
    result = await flow.async_step_pick({"replacement": "sensor.live_power"})
    assert result["type"] == "create_entry"
    assert entry.options["battery_power_sensor"] == "sensor.live_power"
    assert list(entry.options[PARKED_SETTINGS_KEY]) == ["sensor.live_power"]

    changes, _ = realign_battery_slots(dict(entry.options), [B, "sensor.live_power"])
    after = _apply(dict(entry.options), changes)
    assert after["battery_reserve_socs"] == [0, 30]
    assert after["battery_modes"] == [None, "force_discharge"]


@real_ha
async def test_a_flow_with_nothing_picked_changes_nothing(hass):
    _states(hass)
    entry = _entry(hass, **_wired_config())
    before = dict(entry.options)
    issue = _raise(hass, _battery_without_power())
    flow = await repairs.async_create_fix_flow(hass, issue.issue_id, issue.data)
    flow.hass = hass
    result = await flow.async_step_init()
    while result["type"] == "form":
        result = await flow.async_step_pick({})
    assert result["type"] == "abort" and result["reason"] == "nothing_chosen"
    assert dict(entry.options) == before


@real_ha
async def test_the_other_fixable_repairs_keep_their_copy_flow(hass):
    flow = await repairs.async_create_fix_flow(
        hass, "charger_actuation_failed_x", {"placeholders": {}})
    assert isinstance(flow, repairs.SEMContextCopyFlow)
