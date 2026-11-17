"""(#1086) SEM's tools for AI assistants in Home Assistant.

Home Assistant's ``llm`` integration asks every integration's ``llm.py``
platform for tools. Tools given for the Assist API reach every
conversation agent that has Assist on (OpenAI, Anthropic, Google, Ollama
...) and the MCP Server. No sentence file is needed.

Nothing here writes. The four change-tools exist only while the "Voice
commands" switch is on (``write_intents_enabled``, the same gate the
handlers check themselves). Several SEM entries: like the intents, the
first loaded entry answers (``_coordinator_for``).
"""
from __future__ import annotations

from typing import Any

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import intent, issue_registry as ir
from homeassistant.helpers.llm import (
    LLM_API_ASSIST, IntentTool, LLMContext, Tool, ToolInput,
)
from homeassistant.loader import async_get_integration
from homeassistant.helpers.translation import async_get_translations

from .assist_intents import (
    EXPLAIN_HANDLERS, WRITE_HANDLERS, _coordinator_for, write_intents_enabled,
)
from .const import DOMAIN

TOOL_SETUP_STATUS = "SemSetupStatus"

PROMPT = (
    "SEM (Solar Energy Management) steers solar, battery and EV charging. "
    "A new SEM install starts in watch-only mode: it changes nothing until "
    "its owner turns that off. For questions about SEM, its decisions, "
    "costs or setup, use the Sem tools."
)


def _handlers_by_type(hass: HomeAssistant) -> dict[str, intent.IntentHandler]:
    return {h.intent_type: h for h in intent.async_get(hass)}


def _tools_for(hass: HomeAssistant, classes: tuple) -> list[Tool]:
    """IntentTools for the handlers SEM registered; a missing one is skipped."""
    registered = _handlers_by_type(hass)
    return [IntentTool(c.intent_type, registered[c.intent_type])
            for c in classes if c.intent_type in registered]


def _open_issues(hass: HomeAssistant) -> list[ir.IssueEntry]:
    reg = ir.async_get(hass)
    return [i for i in reg.issues.values()
            if i.domain == DOMAIN and not i.dismissed_version]


async def _issue_titles(hass: HomeAssistant) -> list[str]:
    issues = _open_issues(hass)
    if not issues:
        return []
    texts = await async_get_translations(
        hass, hass.config.language, "issues", [DOMAIN])
    prefix = f"component.{DOMAIN}.issues."
    return [texts.get(f"{prefix}{i.translation_key}.title") or i.issue_id
            for i in issues]


def _forecast_part(coordinator: Any) -> dict[str, Any]:
    reader = getattr(coordinator, "_forecast_reader", None)
    out: dict[str, Any] = {"in_use": getattr(reader, "source", None)}
    try:
        rec = coordinator.source_recommendation()
    except Exception:  # noqa: BLE001 — advice is optional
        rec = None
    if rec:
        out["recommended"] = rec.get("source")
    return out


def _tariff_configured(config: dict) -> bool:
    """A dynamic or calendar tariff, or a price the owner typed in."""
    if config.get("tariff_mode", "static") != "static":
        return True
    return config.get("electricity_import_rate") is not None


async def build_setup_status(hass: HomeAssistant, coordinator: Any) -> dict:
    """Small summary of how SEM is set up. Reads only; derives nothing."""
    from .coordinator.coordinator import battery_unseen

    watch_only = bool(getattr(coordinator, "_observer_mode", False))
    chargers = coordinator.config.get("ev_chargers") or []
    integration = await async_get_integration(hass, DOMAIN)
    return {
        "version": str(integration.version),
        "watch_only": watch_only,
        "watch_only_note": (
            "SEM only watches and changes nothing." if watch_only
            else "SEM is controlling the hardware."),
        "chargers": {
            "count": len(chargers),
            "names": [str(c.get("name") or c.get("id")) for c in chargers],
        },
        "battery_seen": not battery_unseen(coordinator),
        "forecast_source": _forecast_part(coordinator),
        "tariff_configured": _tariff_configured(coordinator.config),
        "open_repairs": await _issue_titles(hass),
    }


class SetupStatusTool(Tool):
    """Read-only: how SEM is set up."""

    name = TOOL_SETUP_STATUS
    description = (
        "Summarise how SEM is set up: watch-only mode, chargers, battery, "
        "forecast source, tariff, open repairs and version. Read-only."
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> dict:
        coordinator = _coordinator_for(hass)
        if coordinator is None:
            return {"error": "SEM is not running."}
        return await build_setup_status(hass, coordinator)


@callback
def async_get_tools(
    hass: HomeAssistant, llm_context: LLMContext, api_id: str
) -> LLMTools | None:
    """SEM's tools for the Assist API; ``None`` for any other API or while
    SEM is not loaded."""
    if api_id != LLM_API_ASSIST:
        return None
    coordinator = _coordinator_for(hass)
    if coordinator is None:
        return None
    tools = _tools_for(hass, EXPLAIN_HANDLERS)
    tools.append(SetupStatusTool())
    if write_intents_enabled(coordinator):
        tools += _tools_for(hass, WRITE_HANDLERS)
    return LLMTools(tools=tools, prompt=PROMPT)
