"""#1431 — four more voice/AI commands: set the charge mode, charge until,
set the peak limit, and ask what solar saved.

Unit level, through the real ``intent.async_handle`` dispatch Assist uses.
The changes go through the code paths the card and the services use: the
charge-mode select's own ``async_select_option`` (aliases, idempotency, the
battery switch and the user's Now live there), ``set_plan_override(
user_now=True, fixed_end=True)`` for "until a time", and the
``update_target_peak`` action. The end-to-end proof against a loaded SEM is
``test_1431_voice_commands_real_ha.py``.

Every spoken answer is pinned as an exact string (at most two short
sentences, plain words, no codes or entity ids).
"""
from __future__ import annotations

from datetime import datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.core import ServiceCall
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management import assist_intents
from custom_components.solar_energy_management.assist_intents import (
    EXPLAIN_HANDLERS,
    INTENT_CHARGE_NOW_UNTIL,
    INTENT_SET_CHARGE_MODE,
    INTENT_SET_PEAK_LIMIT,
    INTENT_SOLAR_SAVINGS,
    WRITE_HANDLERS,
    async_register_intents,
    minutes_until_clock,
)
from custom_components.solar_energy_management.const import DOMAIN

REFUSED = ("Voice commands are read-only — turn on \"Voice commands\" in SEM's "
           "settings to let me change anything.")
WHICH = "I don't know which charger you mean — say its name."
WATCH = " SEM is in watch-only mode, so nothing is sent to the charger yet."


def _coordinator(hass, observer=False, **config):
    coord = SimpleNamespace()
    coord.hass = hass
    coord.config = config
    coord._observer_mode = observer
    coord.set_plan_override = MagicMock()
    coord.clear_plan_override = MagicMock()
    return coord


def _add(hass, coordinator):
    entry = MockConfigEntry(domain=DOMAIN, title="SEM")
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    return entry


class _FakeSelect:
    def __init__(self):
        self.picked = []

    async def async_select_option(self, option):
        self.picked.append(option)


@pytest.fixture(autouse=True)
def _register(hass):
    async_register_intents(hass)


@pytest.fixture
def select(monkeypatch):
    fake = _FakeSelect()
    fake.chargers = []

    def _lookup(hass, charger_id):
        fake.chargers.append(charger_id)
        return fake
    monkeypatch.setattr(assist_intents, "_charge_mode_select", _lookup)
    return fake


@pytest.fixture
def peak_calls(hass):
    calls: list[ServiceCall] = []

    async def _svc(call):
        calls.append(call)
    hass.services.async_register(DOMAIN, "update_target_peak", _svc)
    return calls


def _speech(r):
    return r.speech["plain"]["speech"]


def _sentences(text):
    """Sentence ends are a stop followed by a space or the end ("1.20" is not)."""
    import re
    return [s for s in re.split(r"[.!?](?:\s+|$)", text) if s.strip()]


ONE = {"ev_chargers": [{"id": "keba", "name": "Garage"}]}
TWO = {"ev_chargers": [{"id": "left", "name": "Audi"}, {"id": "right", "name": "Mini"}]}
ON = {"assist_write_intents_enabled": True}


def test_the_new_commands_reach_ai_assistants_too():
    """``llm.py`` builds its tools from these two tuples."""
    assert assist_intents.SolarSavingsIntent in EXPLAIN_HANDLERS
    for cls in (assist_intents.SetChargeModeIntent,
                assist_intents.ChargeNowUntilIntent,
                assist_intents.SetPeakLimitIntent):
        assert cls in WRITE_HANDLERS


# ── 1. set the charge mode ──────────────────────────────────────────────

@pytest.mark.parametrize("said, picked, answer", [
    ("off", "off", "The charger is on Off."),
    ("Sun", "sun", "The charger is on Sun."),
    ("sun + tariff", "sun_tariff", "The charger is on Sun + tariff."),
    ("Sun plus tariff", "sun_tariff", "The charger is on Sun + tariff."),
    ("now", "now", "The charger is on Now."),
    # the old names said aloud reach the select as the stored strategy, so
    # its alias path keeps the battery switch as that mode had it
    ("solar only", "solar_only", "The charger is on Sun."),
    ("Solar plus battery", "solar_plus_battery", "The charger is on Sun."),
    ("min plus solar", "min_plus_solar", "The charger is on Sun + tariff."),
    ("cheapest hours", "solar_plus_cheap", "The charger is on Sun + tariff."),
    ("always max", "always_max", "The charger is on Now."),
])
async def test_set_mode_said_aloud(hass, select, said, picked, answer):
    _add(hass, _coordinator(hass, **ON, **ONE))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": said}})
    assert select.picked == [picked]
    assert select.chargers == ["keba"]
    assert _speech(r) == answer


async def test_set_mode_refused_while_voice_commands_are_off(hass, select):
    _add(hass, _coordinator(hass, **ONE))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "sun"}})
    assert _speech(r) == REFUSED
    assert select.picked == []


async def test_set_mode_unknown_mode_declines(hass, select):
    _add(hass, _coordinator(hass, **ON, **ONE))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "turbo"}})
    assert select.picked == []
    assert _speech(r) == "Say Off, Sun, Sun + tariff or Now."


async def test_set_mode_with_two_chargers_needs_a_name(hass, select):
    _add(hass, _coordinator(hass, **ON, **TWO))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "off"}})
    assert select.picked == []
    assert _speech(r) == WHICH


async def test_set_mode_the_name_picks_the_right_charger(hass, select):
    _add(hass, _coordinator(hass, **ON, **TWO))
    await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                              {"mode": {"value": "sun"}, "name": {"value": "mini"}})
    assert select.chargers == ["right"] and select.picked == ["sun"]


async def test_set_mode_unknown_name_declines(hass, select):
    _add(hass, _coordinator(hass, **ON, **TWO))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "sun"}, "name": {"value": "tesla"}})
    assert select.picked == [] and _speech(r) == WHICH


async def test_set_mode_in_watch_only_says_nothing_is_sent(hass, select):
    _add(hass, _coordinator(hass, observer=True, **ON, **ONE))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "now"}})
    assert select.picked == ["now"]
    assert _speech(r) == "The charger is on Now." + WATCH
    assert len(_sentences(_speech(r))) == 2


async def test_set_mode_without_the_select_entity_answers_honestly(hass, monkeypatch):
    monkeypatch.setattr(assist_intents, "_charge_mode_select", lambda h, c: None)
    _add(hass, _coordinator(hass, **ON, **ONE))
    r = await intent.async_handle(hass, "t", INTENT_SET_CHARGE_MODE,
                                  {"mode": {"value": "sun"}})
    assert _speech(r) == "I don't have an answer for that right now."


# ── 2. charge until ─────────────────────────────────────────────────────

async def test_charge_until_a_time_is_the_users_now_with_a_fixed_end(hass):
    coord = _coordinator(hass, **ON, **ONE)
    _add(hass, coord)
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": "07:00"}})
    args, kwargs = coord.set_plan_override.call_args
    assert args[0] == "keba" and args[1] == "force"
    assert 1 <= args[2] <= 24 * 60
    assert kwargs == {"user_now": True, "fixed_end": True}
    assert _speech(r) == "Charging now, until 07:00."


async def test_charge_until_full_picks_now_until_full(hass, select):
    coord = _coordinator(hass, **ON, **ONE)
    _add(hass, coord)
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": "until full"}})
    assert select.picked == ["always_max"]
    coord.set_plan_override.assert_not_called()
    assert _speech(r) == "Charging now, until the car is full."


@pytest.mark.parametrize("said", ["soon", "25 o'clock", "7:75", "", "tomorrow"])
async def test_charge_until_something_that_is_not_a_time_declines(hass, said):
    coord = _coordinator(hass, **ON, **ONE)
    _add(hass, coord)
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": said}})
    coord.set_plan_override.assert_not_called()
    assert _speech(r) == "Say a time, such as 7 o'clock, or say full."


async def test_charge_until_refused_while_voice_commands_are_off(hass):
    coord = _coordinator(hass, **ONE)
    _add(hass, coord)
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": "07:00"}})
    coord.set_plan_override.assert_not_called()
    assert _speech(r) == REFUSED


async def test_charge_until_with_two_chargers_needs_a_name(hass):
    coord = _coordinator(hass, **ON, **TWO)
    _add(hass, coord)
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": "07:00"}})
    coord.set_plan_override.assert_not_called()
    assert _speech(r) == WHICH


async def test_charge_until_in_watch_only_says_nothing_is_sent(hass):
    coord = _coordinator(hass, observer=True, **ON, **ONE)
    _add(hass, coord)
    r = await intent.async_handle(hass, "t", INTENT_CHARGE_NOW_UNTIL,
                                  {"until": {"value": "07:00"}})
    assert _speech(r) == "Charging now, until 07:00." + WATCH


def test_minutes_until_a_clock_time():
    now = datetime(2026, 11, 25, 21, 30)
    assert minutes_until_clock("23:00", now) == 90
    assert minutes_until_clock("7", now) == 9 * 60 + 30          # tomorrow 07:00
    assert minutes_until_clock("7 o'clock", now) == 9 * 60 + 30
    assert minutes_until_clock("7 pm", now) == 21 * 60 + 30       # 19:00 tomorrow
    assert minutes_until_clock("12 am", now) == 2 * 60 + 30       # midnight
    assert minutes_until_clock("19.30", now) == 22 * 60
    # a time already past today is tomorrow's; "now" itself is a full day
    assert minutes_until_clock("21:00", now) == 23 * 60 + 30
    assert minutes_until_clock("21:30", now) == 24 * 60
    for bad in ("25:00", "7:75", "soon", "", None):
        assert minutes_until_clock(bad, now) is None


# ── 3. peak limit ───────────────────────────────────────────────────────

async def test_peak_limit_goes_through_the_update_target_peak_action(hass, peak_calls):
    _add(hass, _coordinator(hass, **ON))
    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": "3.5"}})
    assert [c.data for c in peak_calls] == [{"target_peak_limit": 3.5}]
    assert _speech(r) == "The peak limit is now 3.5 kW."


@pytest.mark.parametrize("kw", [0.5, 200, -3])
async def test_peak_limit_out_of_range_is_refused_in_words(hass, peak_calls, kw):
    _add(hass, _coordinator(hass, **ON))
    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": kw}})
    assert peak_calls == []
    assert _speech(r) == "The peak limit must be between 1 and 80 kW."


async def test_peak_limit_refused_while_voice_commands_are_off(hass, peak_calls):
    _add(hass, _coordinator(hass))
    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": 3.5}})
    assert peak_calls == [] and _speech(r) == REFUSED


async def test_peak_limit_in_watch_only_says_it_only_plans(hass, peak_calls):
    _add(hass, _coordinator(hass, observer=True, **ON))
    r = await intent.async_handle(hass, "t", INTENT_SET_PEAK_LIMIT,
                                  {"kw": {"value": 6}})
    assert _speech(r) == ("The peak limit is now 6 kW. SEM is in watch-only "
                          "mode, so it only plans with it.")


# ── 4. savings ──────────────────────────────────────────────────────────

async def test_savings_this_month_adds_the_battery_part(hass):
    _add(hass, _coordinator(hass))
    hass.states.async_set("sensor.sem_monthly_savings", "42.5",
                          {"unit_of_measurement": "CHF"})
    hass.states.async_set("sensor.sem_monthly_battery_savings", "7.5",
                          {"unit_of_measurement": "CHF"})
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS,
                                  {"period": {"value": "this month"}})
    assert _speech(r) == ("Solar saved 50.00 CHF this month, 7.50 CHF of it "
                          "through the battery.")


async def test_savings_in_another_currency(hass):
    _add(hass, _coordinator(hass))
    hass.states.async_set("sensor.sem_yearly_savings", "1234.5",
                          {"unit_of_measurement": "SEK"})
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS,
                                  {"period": {"value": "year"}})
    assert _speech(r) == "Solar saved 1234.50 SEK this year."


@pytest.mark.parametrize("state", ["unknown", "unavailable", "abc"])
async def test_savings_without_a_value_says_so(hass, state):
    _add(hass, _coordinator(hass))
    hass.states.async_set("sensor.sem_daily_savings", state)
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS, {})
    assert _speech(r) == "There is no savings figure for today yet."


async def test_savings_without_the_sensor_at_all(hass):
    _add(hass, _coordinator(hass))
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS,
                                  {"period": {"value": "this month"}})
    assert _speech(r) == "There is no savings figure for this month yet."


async def test_savings_defaults_to_today_and_needs_no_switch(hass):
    _add(hass, _coordinator(hass))          # Voice commands off: a question
    hass.states.async_set("sensor.sem_daily_savings", "1.2",
                          {"unit_of_measurement": "EUR"})
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS, {})
    assert _speech(r) == "Solar saved 1.20 EUR today."


async def test_savings_an_unknown_period_means_today(hass):
    _add(hass, _coordinator(hass))
    hass.states.async_set("sensor.sem_daily_savings", "2")
    r = await intent.async_handle(hass, "t", INTENT_SOLAR_SAVINGS,
                                  {"period": {"value": "last week"}})
    assert _speech(r) == "Solar saved 2.00 today."


def test_every_new_answer_is_short_and_plain():
    """At most two short sentences, no entity ids or internal codes."""
    answers = [
        "The charger is on Sun + tariff." + WATCH,
        "Charging now, until 07:00." + WATCH,
        "Charging now, until the car is full.",
        "Say a time, such as 7 o'clock, or say full.",
        "Say Off, Sun, Sun + tariff or Now.",
        "The peak limit is now 3.5 kW.",
        "The peak limit must be between 1 and 80 kW.",
        "Solar saved 50.00 CHF this month, 7.50 CHF of it through the battery.",
        "There is no savings figure for today yet.",
    ]
    for a in answers:
        assert len(_sentences(a)) <= 2, a
        assert "sensor." not in a and "select." not in a and "_" not in a, a
        for s in _sentences(a):
            assert len(s.split()) <= 16, a
