"""(#1430) A voice "charge now" is the user's own Now.

Since the four charge modes (#1381 D31), only the user's own Now may run a
charger that stands in Off or a pause. The Assist intent asked for a plain
``force`` without saying it was the user's, so on an Off charger nothing
happened while the speech said "Charging now". The intent now marks the
request as the user's, through the same coordinator entry point the mode
select uses, and the mode rule then lets it through for its minutes only.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers import intent
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management.assist_intents import (
    INTENT_FORCE_CHARGE_NOW,
    async_register_intents,
)
from custom_components.solar_energy_management.const import DOMAIN
from custom_components.solar_energy_management.coordinator import plan_override as po
from custom_components.solar_energy_management.coordinator.decision_log import DecisionLog


def _coordinator(hass):
    coord = SimpleNamespace()
    coord.hass = hass
    coord.config = {"ev_chargers": [{"id": "c1", "name": "Carport"}],
                    "assist_write_intents_enabled": True}
    coord.decision_log = DecisionLog()
    coord._battery_adapters = {}
    coord._energy_plan_shadow = None
    coord.set_plan_override = MagicMock()
    coord.clear_plan_override = MagicMock()
    coord._calendar_departure_for = MagicMock(return_value=None)
    return coord


@pytest.fixture(autouse=True)
def _register(hass):
    async_register_intents(hass)


async def test_voice_charge_now_is_marked_as_the_users_own_now(hass):
    coord = _coordinator(hass)
    entry = MockConfigEntry(domain=DOMAIN, title="SEM")
    entry.add_to_hass(hass)
    entry.runtime_data = coord
    await intent.async_handle(
        hass, "test", INTENT_FORCE_CHARGE_NOW, {"minutes": {"value": 45}})
    coord.set_plan_override.assert_called_once()
    args, kwargs = coord.set_plan_override.call_args
    assert args == ("c1", "force", 45)
    assert kwargs.get("user_now") is True


def test_a_users_now_runs_an_off_charger_for_its_minutes_then_off_again():
    now = datetime(2026, 11, 25, 20, 0, tzinfo=timezone.utc)
    marked = po.set_override({}, "c1", "force", now + timedelta(minutes=45), now,
                             user_now=True)
    plain = po.set_override({}, "c1", "force", now + timedelta(minutes=45), now)
    # the voice request, marked as the user's: an Off charger charges
    assert po.charger_mode_for(marked, "c1", "off", now) == "always_max"
    # an unmarked force (a plan or an automation) leaves Off alone
    assert po.charger_mode_for(plain, "c1", "off", now) == "off"
    # after its minutes the charger is Off again
    later = now + timedelta(minutes=46)
    assert po.charger_mode_for(marked, "c1", "off", later) == "off"


# ── Real Home Assistant path: the coordinator's own set_plan_override ──
#
# The owner asked for the AI commands to be tested end to end, not against a
# mock: the intent runs through ``intent.async_handle`` (and through the LLM
# API's tool) on a real ``hass``, and the override it leaves behind is the
# one SEMCoordinator.set_plan_override stores — then the mode rule decides.

import types

from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, ToolInput
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management import llm as sem_llm
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)


def _real_override_coordinator(hass):
    """A coordinator whose set/clear plan override are SEM's real methods."""
    coord = SimpleNamespace(
        hass=hass,
        config={"ev_chargers": [{"id": "c1", "name": "Carport",
                                 "charge_mode": "off"}],
                "assist_write_intents_enabled": True},
        decision_log=DecisionLog(), _battery_adapters={},
        _energy_plan_shadow=None, _plan_overrides={}, _storage=None,
        _known_battery_ids=set(), _battery_ids_read=True,
        _observer_mode=True,
        _forecast_reader=SimpleNamespace(source="forecast_solar"),
        source_recommendation=MagicMock(return_value=None),
        _calendar_departure_for=MagicMock(return_value=None))
    coord.set_plan_override = types.MethodType(SEMCoordinator.set_plan_override, coord)
    coord.clear_plan_override = types.MethodType(SEMCoordinator.clear_plan_override, coord)
    return coord


def _load(hass, coord):
    entry = MockConfigEntry(domain=DOMAIN, title="SEM")
    entry.add_to_hass(hass)
    entry.runtime_data = coord
    return entry


def _assert_users_now_runs_off_charger_then_off(coord, minutes):
    rec = coord._plan_overrides["c1"]
    assert rec.action == "force"
    assert rec.user_now is True
    # set while the car is not yet seen: it waits for the car (#1381 D30)
    assert rec.started is False and rec.minutes == minutes
    # the car is in: Now starts and ends `minutes` later
    plug_in = dt_util.utcnow()
    started = po.end_now_on_unplug(coord._plan_overrides, "c1", False, plug_in)
    srec = started["c1"]
    assert srec.started is True
    assert srec.expires_at == plug_in.astimezone(timezone.utc) + timedelta(minutes=minutes)
    # the standing mode is Off: the user's Now runs it at full power …
    during = plug_in + timedelta(minutes=minutes - 1)
    assert po.charger_mode_for(started, "c1", "off", during) == "always_max"
    # … and after its minutes the charger is Off again
    after = plug_in + timedelta(minutes=minutes, seconds=1)
    assert po.charger_mode_for(started, "c1", "off", after) == "off"
    # an unplug while it runs ends it at once: the next car does not inherit it
    unplugged = po.end_now_on_unplug(started, "c1", True, during)
    assert "c1" not in unplugged
    assert po.charger_mode_for(unplugged, "c1", "off", during) == "off"


async def test_voice_charge_now_on_an_off_charger_real_hass(hass):
    coord = _real_override_coordinator(hass)
    _load(hass, coord)
    response = await intent.async_handle(
        hass, "test", INTENT_FORCE_CHARGE_NOW,
        {"name": {"value": "Carport"}, "minutes": {"value": 45}})
    assert response.response_type == intent.IntentResponseType.ACTION_DONE
    assert response.speech["plain"]["speech"] == "Charging now, for 45 minutes."
    _assert_users_now_runs_off_charger_then_off(coord, 45)


async def test_ai_charge_now_tool_on_an_off_charger_real_hass(hass):
    coord = _real_override_coordinator(hass)
    _load(hass, coord)
    ctx = LLMContext(platform="test", context=None, language="en",
                     assistant="conversation", device_id=None)
    api = sem_llm.async_get_tools(hass, ctx, LLM_API_ASSIST)
    name = sem_llm.TOOL_PREFIX + INTENT_FORCE_CHARGE_NOW
    tool = next(t for t in api.tools if t.name == name)
    result = await tool.async_call(
        hass, ToolInput(tool_name=name, tool_args={"minutes": 30}), ctx)
    data = getattr(result, "data", result)
    assert "Charging now, for 30 minutes." in str(data)
    _assert_users_now_runs_off_charger_then_off(coord, 30)


async def test_ai_charge_now_tool_is_absent_while_write_commands_are_off(hass):
    coord = _real_override_coordinator(hass)
    coord.config["assist_write_intents_enabled"] = False
    _load(hass, coord)
    ctx = LLMContext(platform="test", context=None, language="en",
                     assistant="conversation", device_id=None)
    api = sem_llm.async_get_tools(hass, ctx, LLM_API_ASSIST)
    assert sem_llm.TOOL_PREFIX + INTENT_FORCE_CHARGE_NOW not in {t.name for t in api.tools}
    assert coord._plan_overrides == {}


async def test_every_sem_ai_tool_reaches_its_intent_real_hass(hass):
    """(#1430) Each intent-backed AI tool must find its intent. On HA
    2026.8–2026.10 the prefixed tool name was used as the intent type, so
    every call failed with "Unknown intent"."""
    coord = _real_override_coordinator(hass)
    _load(hass, coord)
    ctx = LLMContext(platform="test", context=None, language="en",
                     assistant="conversation", device_id=None)
    api = sem_llm.async_get_tools(hass, ctx, LLM_API_ASSIST)
    intent_tools = [t for t in api.tools if isinstance(t, sem_llm.SemIntentTool)]
    assert len(intent_tools) >= 8
    # each tool gets what its intent needs; an empty call is enough to show
    # the intent is found (a missing required slot is its own, later error)
    args = {sem_llm.TOOL_PREFIX + "SemSetChargerTargetSoc": {"percent": 80},
            # (#1431) the four newer commands' required slots
            sem_llm.TOOL_PREFIX + "SemSetChargeMode": {"mode": "sun"},
            sem_llm.TOOL_PREFIX + "SemChargeNowUntil": {"until": "07:00"},
            sem_llm.TOOL_PREFIX + "SemSetPeakLimit": {"kw": 5}}
    for tool in intent_tools:
        try:
            result = await tool.async_call(
                hass, ToolInput(tool_name=tool.name,
                                tool_args=args.get(tool.name, {})), ctx)
        except intent.UnknownIntent:  # the #1430 floor bug
            pytest.fail(f"{tool.name} does not reach its intent")
        data = getattr(result, "data", result)
        assert "Unknown intent" not in str(data), tool.name
