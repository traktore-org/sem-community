"""#1086 — SEM's tools for AI assistants (the ``llm.py`` platform).

Run through Home Assistant's own ``llm`` component, the way a
conversation agent asks for tools.
"""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qsl, unquote, urlsplit
from unittest.mock import MagicMock

import pytest
import yaml
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
    expected = {c.intent_type for c in EXPLAIN_HANDLERS} | {sem_llm.TOOL_SETUP_STATUS, sem_llm.TOOL_DRAFT_ISSUE}
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
        assert len(tool.description.split()) <= 55


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


async def test_setup_tool_never_raises_on_a_charger_that_is_not_a_dict(sem_real_hass):
    _load(sem_real_hass, _coordinator(sem_real_hass, ev_chargers=["not a dict"]))
    out = await sem_llm.SetupStatusTool().async_call(
        sem_real_hass, ToolInput(tool_name="x", tool_args={}), _ctx())
    assert out == {"error": "SEM status is not available yet."}


async def test_setup_tool_guards_a_battery_check_that_raises(sem_real_hass, monkeypatch):
    import custom_components.solar_energy_management.coordinator.coordinator as c
    monkeypatch.setattr(c, "battery_unseen", MagicMock(side_effect=RuntimeError("x")))
    _load(sem_real_hass, _coordinator(sem_real_hass))
    out = await sem_llm.SetupStatusTool().async_call(
        sem_real_hass, ToolInput(tool_name="x", tool_args={}), _ctx())
    assert out == {"error": "SEM status is not available yet."}


# ---- SemDraftIssue -------------------------------------------------------

SECRETS = ["sensor.my_secret_grid", "me@example.com", "192.168.7.44",
           "47.37691, 8.54169", "abcdef0123456789abcdef0123456789abcd",
           "sensor.somebody_power"]
TEXT = ("Charging stops. My grid is sensor.my_secret_grid, mail me@example.com, "
        "box 192.168.7.44, home 47.37691, 8.54169, key abcdef0123456789abcdef0123456789abcd "
        "and sensor.somebody_power")


class _FakeSystemLog:
    def __init__(self, records):
        self.records = SimpleNamespace(to_list=lambda: records)


def _rec(msg, level="ERROR", name="custom_components.solar_energy_management.x", ts=1.0):
    return {"name": name, "level": level, "message": [msg], "timestamp": ts}


async def _draft(hass, coord=None, **args):
    coord = coord or _coordinator(
        hass, grid_import_power_entity="sensor.my_secret_grid",
        ev_chargers=[{"id": "a", "name": "Anna car"}])
    _load(hass, coord)
    args.setdefault("what_happened", TEXT)
    return await sem_llm.DraftIssueTool().async_call(
        hass, ToolInput(tool_name="x", tool_args=args), _ctx())


async def test_draft_contains_no_secret_in_body_or_url(sem_real_hass):
    sem_real_hass.data["system_log"] = _FakeSystemLog([
        _rec("failed for sensor.my_secret_grid at 192.168.7.44 user me@example.com")])
    out = await _draft(sem_real_hass, expected="steady 192.168.7.44")
    for secret in SECRETS + ["Anna car", "Anna"]:
        assert secret not in out["body"], secret
        assert secret not in unquote(out["url"]), secret
    assert len(out["title"]) <= 60
    assert out["url"].startswith(
        "https://github.com/traktore-org/sem-community/issues/new?template=bug_report.yml")
    assert "Press Submit" in " ".join(out["next_steps"])


async def test_draft_url_fields_follow_the_template_order(sem_real_hass):
    out = await _draft(sem_real_hass)
    template = yaml.safe_load(
        (Path(__file__).resolve().parent.parent / ".github/ISSUE_TEMPLATE/bug_report.yml")
        .read_text())
    ids = [b["id"] for b in template["body"] if "id" in b]
    keys = [k for k, _ in parse_qsl(urlsplit(out["url"]).query)
            if k not in ("template", "title")]
    assert keys and set(keys) <= set(ids)
    assert keys == [i for i in ids if i in keys]
    headings = [l for l in out["body"].splitlines() if l.startswith("### ")]
    labels = {b["id"]: b["attributes"]["label"] for b in template["body"] if "id" in b}
    assert headings == [f"### {labels[i]}" for i in ids]


async def test_draft_url_stays_under_the_cap_with_long_logs(sem_real_hass):
    sem_real_hass.data["system_log"] = _FakeSystemLog(
        [_rec("x" * 600 + str(n), ts=float(n)) for n in range(200)])
    out = await _draft(sem_real_hass, what_happened="y" * 6000)
    assert len(out["url"]) <= 7500
    assert len([l for l in out["body"].splitlines() if " ERROR " in l]) <= 10
    assert all(len(l) <= 330 for l in out["body"].splitlines() if " ERROR " in l)


async def test_draft_keeps_only_sem_warnings_and_errors_newest_first(sem_real_hass):
    sem_real_hass.data["system_log"] = _FakeSystemLog([
        _rec("newest"), _rec("other", name="homeassistant.core"),
        _rec("info only", level="INFO"), _rec("older", level="WARNING")])
    body = (await _draft(sem_real_hass))["body"]
    assert body.index("newest") < body.index("older")
    assert "other" not in body.split("Relevant log entries")[1]
    assert "info only" not in body


async def test_draft_works_without_system_log(sem_real_hass):
    sem_real_hass.data.pop("system_log", None)
    out = await _draft(sem_real_hass)
    assert "no recent SEM log entries available" in out["body"]


async def test_draft_without_sem_or_with_bad_input_never_raises(sem_real_hass):
    tool = sem_llm.DraftIssueTool()
    no_sem = await tool.async_call(
        sem_real_hass, ToolInput(tool_name="x", tool_args={"what_happened": "a"}), _ctx())
    assert "error" in no_sem
    _load(sem_real_hass, _coordinator(sem_real_hass))
    bad = await tool.async_call(
        sem_real_hass, ToolInput(tool_name="x", tool_args={}), _ctx())
    assert "title" in bad or "error" in bad


async def test_draft_available_without_the_write_switch(sem_real_hass):
    _load(sem_real_hass, _coordinator(sem_real_hass))
    result = sem_llm.async_get_tools(sem_real_hass, _ctx(), LLM_API_ASSIST)
    assert sem_llm.TOOL_DRAFT_ISSUE in _names(result.tools)


async def test_draft_is_postable_by_an_ai_with_its_own_github_access(sem_real_hass):
    out = await _draft(sem_real_hass)
    assert out["repo"] == "traktore-org/sem-community"
    assert out["labels"] == ["bug"]
    assert out["body"].rstrip().endswith(
        "Prepared with SEM's report tool and checked by the reporter before posting.")
    assert "Show the draft to the user" in out["next_steps"][0]
    desc = sem_llm.DraftIssueTool.description
    assert "agrees" in desc and "url" in desc


async def test_draft_details_block_is_bounded(sem_real_hass):
    coord = _coordinator(sem_real_hass, ev_chargers=[{"id": "a"}])
    coord.source_recommendation.return_value = {"source": "z" * 5000}
    out = await _draft(sem_real_hass, coord)
    block = out["body"].split("<details>")[1].split("</details>")[0]
    assert len(block) <= 2000 + 200
    assert "<summary>Diagnostics extract</summary>" in out["body"]
