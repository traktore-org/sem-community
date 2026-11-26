"""#1431 — the four new voice commands against a LOADED SEM (real HA).

Each command is called the way Assist calls it (``intent.async_handle``)
and the way an AI agent calls it (Home Assistant's LLM API tool call), and
both the spoken answer and the resulting state are checked: the charge-mode
select, the plan override (user's Now, its end), the stored peak limit — and
that a refused command changes nothing.
"""
from __future__ import annotations

from datetime import timedelta

from homeassistant.helpers import intent
from homeassistant.helpers import llm as llm_helper
from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, ToolInput
from homeassistant.setup import async_setup_component
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.assist_intents import (
    INTENT_CHARGE_NOW_UNTIL,
    INTENT_SET_CHARGE_MODE,
    INTENT_SET_PEAK_LIMIT,
    INTENT_SOLAR_SAVINGS,
)
from custom_components.solar_energy_management.const import DOMAIN

SELECT = "select.sem_charger_ev_charger_charge_mode"
CID = "ev_charger"
WATCH = " SEM is in watch-only mode, so nothing is sent to the charger yet."
PEAK_WATCH = " SEM is in watch-only mode, so it only plans with it."
REFUSED = ("Voice commands are read-only — turn on \"Voice commands\" in SEM's "
           "settings to let me change anything.")


async def _load(hass, entry, voice_on=True, observer=None):
    """A new install starts watch-only, so every answer says so; ``observer=
    False`` is an install whose owner turned watch-only off."""
    entry.add_to_hass(hass)
    data = dict(entry.data)
    if voice_on:
        data["assist_write_intents_enabled"] = True
    if observer is not None:
        data["observer_mode"] = observer
    hass.config_entries.async_update_entry(entry, data=data)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _speech(r):
    return r.speech["plain"]["speech"]


def _override(coord):
    return (getattr(coord, "_plan_overrides", None) or {}).get(CID)


def _stored_mode(coord):
    return next(c for c in coord.config["ev_chargers"] if c.get("id") == CID)["charge_mode"]


async def test_set_mode_changes_the_select_and_the_stored_strategy(
        sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    coord = await _load(hass, sem_config_entry)
    assert hass.states.get(SELECT).state == "sun_tariff"   # min_plus_solar shows so

    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "sun"}})
    await hass.async_block_till_done()
    assert _speech(r) == "The charger is on Sun." + WATCH
    assert hass.states.get(SELECT).state == "sun"
    # battery help was on (min_plus_solar) → Sun with the battery = solar_plus_battery
    assert _stored_mode(coord) == "solar_plus_battery"

    # saying the mode it already has changes nothing (#1381 D21)
    await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                              {"mode": {"value": "Sun"}})
    await hass.async_block_till_done()
    assert _stored_mode(coord) == "solar_plus_battery"

    # an old name said aloud lands on its own strategy
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "solar only"}})
    await hass.async_block_till_done()
    assert _stored_mode(coord) == "solar_only"
    assert hass.states.get(SELECT).state == "sun"
    assert _speech(r) == "The charger is on Sun." + WATCH


async def test_now_on_an_off_charger_is_the_users_now(sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    coord = await _load(hass, sem_config_entry)
    await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                              {"mode": {"value": "off"}})
    await hass.async_block_till_done()
    assert hass.states.get(SELECT).state == "off"

    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "now"}})
    await hass.async_block_till_done()
    rec = _override(coord)
    assert rec is not None and rec.action == "force" and rec.user_now is True
    assert hass.states.get(SELECT).state == "now"
    assert _speech(r) == "The charger is on Now." + WATCH
    assert _stored_mode(coord) == "off"      # Off stays Off after Now ends (#1381 D20)


async def test_charge_until_a_time_and_until_full(sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    coord = await _load(hass, sem_config_entry)
    target = (dt_util.now() + timedelta(hours=3)).strftime("%H:%M")
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": target}})
    await hass.async_block_till_done()
    rec = _override(coord)
    assert rec is not None and rec.action == "force"
    assert rec.user_now is True and rec.fixed_end is True
    left = (rec.expires_at - dt_util.now()).total_seconds() / 60
    assert 170 <= left <= 181
    assert _speech(r) == f"Charging now, until {target}." + WATCH

    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": "full"}})
    await hass.async_block_till_done()
    assert _stored_mode(coord) == "always_max"
    assert hass.states.get(SELECT).state == "now"
    assert _speech(r) == "Charging now, until the car is full." + WATCH


async def test_peak_limit_is_stored(sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    coord = await _load(hass, sem_config_entry)
    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": 3.5}})
    await hass.async_block_till_done()
    assert float(coord.config["target_peak_limit"]) == 3.5
    assert _speech(r) == "The peak limit is now 3.5 kW." + PEAK_WATCH

    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": 200}})
    assert float(coord.config["target_peak_limit"]) == 3.5
    assert _speech(r) == "The peak limit must be between 1 and 80 kW."


async def test_with_watch_only_off_the_answers_are_one_sentence(
        sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    coord = await _load(hass, sem_config_entry, observer=False)
    assert coord._observer_mode is False
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "sun"}})
    assert _speech(r) == "The charger is on Sun."
    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": 5}})
    assert _speech(r) == "The peak limit is now 5 kW."


async def test_refused_commands_change_nothing(sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    coord = await _load(hass, sem_config_entry, voice_on=False)
    before_mode, before_peak = _stored_mode(coord), coord.config.get("target_peak_limit")
    for intent_type, slots in (
            (INTENT_SET_CHARGE_MODE, {"mode": {"value": "off"}}),
            (INTENT_CHARGE_NOW_UNTIL, {"until": {"value": "07:00"}}),
            (INTENT_SET_PEAK_LIMIT, {"kw": {"value": 2}})):
        r = await intent.async_handle(hass, "t", intent_type, slots)
        assert _speech(r) == REFUSED
    await hass.async_block_till_done()
    assert _stored_mode(coord) == before_mode
    assert coord.config.get("target_peak_limit") == before_peak
    assert _override(coord) is None


async def test_savings_reads_sems_own_sensor(sem_real_hass, sem_config_entry):
    hass = sem_real_hass
    await _load(hass, sem_config_entry, voice_on=False)
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS,
                                  {"period": {"value": "today"}})
    speech = _speech(r)
    state = hass.states.get("sensor.sem_daily_savings")
    assert state is not None
    if state.state in ("unknown", "unavailable"):
        assert speech == "There is no savings figure for today yet."
    else:
        assert speech.startswith("Solar saved ") and speech.endswith(" today.")
        assert f"{float(state.state):.2f}" in speech or "through the battery" in speech


def _ctx():
    return LLMContext(platform="test", context=None, language="en",
                      assistant="conversation", device_id=None)


async def test_an_ai_agent_calls_the_new_tools(sem_real_hass, sem_config_entry):
    """The tool call an AI agent makes through Home Assistant's LLM API."""
    hass = sem_real_hass
    assert await async_setup_component(hass, "llm", {})
    coord = await _load(hass, sem_config_entry)
    api = await llm_helper.async_get_api(hass, LLM_API_ASSIST, _ctx())
    names = {t.name for t in api.tools}
    for it in (INTENT_SET_CHARGE_MODE, INTENT_CHARGE_NOW_UNTIL,
               INTENT_SET_PEAK_LIMIT, INTENT_SOLAR_SAVINGS):
        assert f"{DOMAIN}__{it}" in names

    tools = {t.name: t for t in api.tools}

    async def _call(it, args):
        name = f"{DOMAIN}__{it}"
        # the tool object the API hands an agent (api.async_call_tool adds
        # only HA's own argument parsing, which needs hassil at runtime)
        out = await tools[name].async_call(hass, ToolInput(tool_name=name, tool_args=args), _ctx())
        await hass.async_block_till_done()
        return getattr(out, "data", out)

    out = await _call(INTENT_SET_PEAK_LIMIT, {"kw": 4.2})
    assert float(coord.config["target_peak_limit"]) == 4.2
    assert "4.2 kW" in str(out)

    out = await _call(INTENT_SET_CHARGE_MODE, {"mode": "sun_tariff"})
    assert hass.states.get(SELECT).state == "sun_tariff"
    assert "Sun + tariff" in str(out)

    out = await _call(INTENT_CHARGE_NOW_UNTIL, {"until": "full"})
    assert _stored_mode(coord) == "always_max"

    out = await _call(INTENT_SOLAR_SAVINGS, {"period": "this year"})
    assert "this year" in str(out)

    # an older tool too: on the HA 2026.8 floor every SEM tool used to answer
    # "Unknown intent", because HA called the intent by the prefixed tool name
    out = await _call("SemWhyBattery", {})
    assert "Unknown intent" not in str(out) and str(out)
