"""#1086 — SEM's tools for AI assistants (the ``llm.py`` platform).

Run through Home Assistant's own ``llm`` component, the way a
conversation agent asks for tools.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.components import llm as ha_llm
from homeassistant.helpers import issue_registry as ir
from homeassistant.helpers.llm import LLM_API_ASSIST, LLMContext, ToolInput
from homeassistant.setup import async_setup_component
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.solar_energy_management import llm as sem_llm
from custom_components.solar_energy_management.assist_intents import (
    EXPLAIN_HANDLERS, WRITE_HANDLERS, async_register_intents,
)
from custom_components.solar_energy_management.const import DOMAIN


def _ctx():
    return LLMContext(platform="test", context=None, language="en",
                      assistant="conversation", device_id=None)


def _coordinator(hass, **config):
    return SimpleNamespace(
        hass=hass, config=config, _observer_mode=True,
        _forecast_reader=SimpleNamespace(source="forecast_solar"),
        source_recommendation=MagicMock(return_value=None))


def _load(hass, coordinator):
    entry = MockConfigEntry(domain=DOMAIN, title="SEM")
    entry.add_to_hass(hass)
    entry.runtime_data = coordinator
    return entry


@pytest.fixture(autouse=True)
def _intents(hass):
    async_register_intents(hass)


def _names(tools):
    return {t.name for t in tools}


def test_other_api_gets_nothing(hass):
    _load(hass, _coordinator(hass))
    assert sem_llm.async_get_tools(hass, _ctx(), "some_other_api") is None


def test_sem_not_loaded_returns_none_without_raising(hass):
    assert sem_llm.async_get_tools(hass, _ctx(), LLM_API_ASSIST) is None


def test_assist_gets_explain_tools_and_setup_tool_but_no_write_tools(hass):
    _load(hass, _coordinator(hass))
    result = sem_llm.async_get_tools(hass, _ctx(), LLM_API_ASSIST)
    expected = {c.intent_type for c in EXPLAIN_HANDLERS} | {sem_llm.TOOL_SETUP_STATUS}
    assert _names(result.tools) == expected
    assert result.prompt and len(result.prompt.split()) <= 80


def test_write_tools_appear_only_with_the_switch_on(hass):
    _load(hass, _coordinator(hass, assist_write_intents_enabled=True))
    result = sem_llm.async_get_tools(hass, _ctx(), LLM_API_ASSIST)
    assert {c.intent_type for c in WRITE_HANDLERS} <= _names(result.tools)


def test_every_tool_has_a_short_plain_description(hass):
    _load(hass, _coordinator(hass, assist_write_intents_enabled=True))
    for tool in sem_llm.async_get_tools(hass, _ctx(), LLM_API_ASSIST).tools:
        assert tool.description and not tool.description.startswith("Execute")
        assert len(tool.description.split()) <= 25


async def test_setup_status_for_a_watch_only_install_without_charger(sem_real_hass):
    _load(sem_real_hass, _coordinator(sem_real_hass))
    sem_real_hass.config.language = "en"
    out = await sem_llm.SetupStatusTool().async_call(
        sem_real_hass, ToolInput(tool_name="x", tool_args={}), _ctx())
    assert out["watch_only"] is True
    assert "changes nothing" in out["watch_only_note"]
    assert out["chargers"] == {"count": 0, "names": []}
    assert out["battery_seen"] is False
    assert out["forecast_source"] == {"in_use": "forecast_solar"}
    assert out["tariff_configured"] is False
    assert out["open_repairs"] == []
    assert out["version"]


async def test_setup_status_reads_chargers_tariff_recommendation_and_repairs(sem_real_hass):
    coord = _coordinator(
        sem_real_hass, ev_chargers=[{"id": "a", "name": "Garage"}],
        electricity_import_rate=0.3)
    coord._observer_mode = False
    coord.source_recommendation.return_value = {"source": "open_meteo"}
    _load(sem_real_hass, coord)
    ir.async_create_issue(
        sem_real_hass, DOMAIN, "some_issue", is_fixable=False,
        severity=ir.IssueSeverity.WARNING, translation_key="some_issue")
    out = await sem_llm.build_setup_status(sem_real_hass, coord)
    assert out["watch_only"] is False
    assert out["chargers"] == {"count": 1, "names": ["Garage"]}
    assert out["tariff_configured"] is True
    assert out["forecast_source"]["recommended"] == "open_meteo"
    assert out["open_repairs"] == ["some_issue"]


async def test_setup_tool_without_sem_says_so(hass):
    out = await sem_llm.SetupStatusTool().async_call(
        hass, ToolInput(tool_name="x", tool_args={}), _ctx())
    assert "error" in out


async def test_ha_llm_component_discovers_the_platform(sem_real_hass):
    assert await async_setup_component(sem_real_hass, "llm", {})
    _load(sem_real_hass, _coordinator(sem_real_hass))
    sem_real_hass.config.components.add(DOMAIN)  # the platform is read once SEM is set up
    tools = await ha_llm.async_get_tools(sem_real_hass, _ctx(), LLM_API_ASSIST)
    assert sem_llm.TOOL_SETUP_STATUS in _names(tools.tools)
    assert "SEM" in (tools.prompt or "")
