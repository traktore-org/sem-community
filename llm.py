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

import logging
from typing import Any

import voluptuous as vol

from homeassistant.components.llm import LLMTools
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import config_validation as cv, intent
from homeassistant.helpers.llm import (
    LLM_API_ASSIST, IntentTool, LLMContext, Tool, ToolInput,
)
from homeassistant.loader import async_get_integration

try:  # HA 2026.11+: tools return a ToolResult (#1389); the 2026.8 floor has none
    from homeassistant.helpers.llm import ToolResult
except ImportError:  # pragma: no cover - exercised on the floor venv only
    ToolResult = None  # type: ignore[assignment,misc]

from .assist_intents import (
    EXPLAIN_HANDLERS, WRITE_HANDLERS, _coordinator_for, write_intents_enabled,
)
from .const import DOMAIN
from .setup_status import issue_titles, setup_facts

# (#1389) HA wants every tool name to start with the integration domain.
TOOL_PREFIX = f"{DOMAIN}__"
TOOL_SETUP_STATUS = f"{TOOL_PREFIX}SemSetupStatus"
TOOL_DRAFT_ISSUE = f"{TOOL_PREFIX}SemDraftIssue"
_LOGGER = logging.getLogger(__name__)
_NOT_READY = {"error": "SEM status is not available yet."}
_logged_failure = False


def _note_failure(what: str) -> None:
    """Debug-log a tool failure once; a half-started SEM would repeat it."""
    global _logged_failure
    if not _logged_failure:
        _logged_failure = True
        _LOGGER.debug("(#1086) %s failed", what, exc_info=True)

PROMPT = (
    "SEM (Solar Energy Management) steers solar, battery and EV charging. "
    "A new SEM install starts in watch-only mode: it changes nothing until "
    "its owner turns that off. For questions about SEM, its decisions, "
    "costs or setup, use the Sem tools."
)


def _result(data: dict) -> Any:
    """A ToolResult where HA has one, else the plain dict (2026.8 floor)."""
    return data if ToolResult is None else ToolResult(data=data)


def _handlers_by_type(hass: HomeAssistant) -> dict[str, intent.IntentHandler]:
    return {h.intent_type: h for h in intent.async_get(hass)}


class _SemIntentTool(IntentTool):
    """(#1431) An intent tool whose NAME carries SEM's prefix (#1389) but
    whose call reaches the intent by its own type.

    HA 2026.10+ keeps the two apart (``IntentTool.intent_type``). The
    2026.8 floor's ``IntentTool`` calls ``intent.async_handle`` with
    ``intent_type=self.name`` — the prefixed name — so every SEM tool an AI
    agent called there answered "Unknown intent". Where the base class
    already keeps ``intent_type`` it is used as is.
    """

    def __init__(self, name: str, handler: intent.IntentHandler) -> None:
        super().__init__(name, handler)
        self._sem_intent_type = handler.intent_type
        self._base_keeps_type = vars(self).get("intent_type") == handler.intent_type

    async def async_call(self, hass: HomeAssistant, tool_input: ToolInput,
                         llm_context: LLMContext) -> Any:
        if self._base_keeps_type:
            return await super().async_call(hass, tool_input, llm_context)
        slots = {key: {"value": val} for key, val in tool_input.tool_args.items()
                 if val not in (None, "")}
        response = await intent.async_handle(
            hass=hass, platform=llm_context.platform,
            intent_type=self._sem_intent_type, slots=slots, text_input=None,
            context=llm_context.context, language=llm_context.language,
            assistant=llm_context.assistant, device_id=llm_context.device_id)
        from homeassistant.helpers.llm import IntentResponseDict
        return _result(IntentResponseDict(response))


def _tools_for(hass: HomeAssistant, classes: tuple) -> list[Tool]:
    """IntentTools for the handlers SEM registered; a missing one is skipped."""
    registered = _handlers_by_type(hass)
    tools = [_SemIntentTool(TOOL_PREFIX + c.intent_type, registered[c.intent_type])
             for c in classes if c.intent_type in registered]
    for tool in tools:
        tool.integration = DOMAIN  # (#1389) the floor's IntentTool has no kwarg
    return tools


async def build_setup_status(hass: HomeAssistant, coordinator: Any) -> dict:
    """Small summary of how SEM is set up. Reads only; derives nothing.

    (#1379) The facts come from ``setup_status.setup_facts``, the same
    reading the dashboard's first-run checklist is built from.
    """
    from .coordinator.coordinator import battery_unseen

    facts = setup_facts(hass, coordinator)
    chargers = facts["chargers"]
    watch_only = facts["watch_only"]
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
        "forecast_source": facts["forecast_source"],
        "tariff_configured": facts["tariff_configured"],
        "open_repairs": await issue_titles(hass, facts["issues"]),
        # (#1362) set or not, where, and the selects to choose from
        "battery_grid_charge": facts["battery_grid_charge"],
    }


class SetupStatusTool(Tool):
    """Read-only: how SEM is set up."""

    name = TOOL_SETUP_STATUS
    integration = DOMAIN
    description = (
        "Summarise how SEM is set up: watch-only mode, chargers, battery, "
        "grid charge of the battery (set or not; if not, the selects on the "
        "battery's device and their options, to tell the user which to pick), "
        "forecast source, tariff, open repairs and version. Read-only."
    )

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> Any:
        coordinator = _coordinator_for(hass)
        if coordinator is None:
            return _result({"error": "SEM is not running."})
        try:
            return _result(await build_setup_status(hass, coordinator))
        except Exception:  # noqa: BLE001 — a half-started SEM must not raise into the AI
            _note_failure("SemSetupStatus")
            return _result(dict(_NOT_READY))


class DraftIssueTool(Tool):
    """Read-only: prepares a bug report for a person to post."""

    name = TOOL_DRAFT_ISSUE
    integration = DOMAIN
    description = (
        "Use when the user reports a problem with SEM and wants to tell its "
        "developers. Only prepares a draft; SEM posts nothing. Show the draft "
        "to the user and post it (repo, labels, title, body) only after the "
        "user agrees. If you cannot post, give the user the url."
    )
    parameters = vol.Schema({
        vol.Required("what_happened"): cv.string,
        vol.Optional("expected"): cv.string,
    })

    async def async_call(
        self, hass: HomeAssistant, tool_input: ToolInput, llm_context: LLMContext
    ) -> Any:
        coordinator = _coordinator_for(hass)
        if coordinator is None:
            return _result({"error": "SEM is not running."})
        try:
            from .issue_draft import build_draft
            args = tool_input.tool_args
            status = await build_setup_status(hass, coordinator)
            return _result(build_draft(
                hass, coordinator.config, status,
                str(args.get("what_happened") or ""), str(args.get("expected") or "")))
        except Exception:  # noqa: BLE001 — never raise into the AI
            _note_failure("SemDraftIssue")
            return _result({"error": "Could not prepare a draft."})


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
    tools += [SetupStatusTool(), DraftIssueTool()]
    if write_intents_enabled(coordinator):
        tools += _tools_for(hass, WRITE_HANDLERS)
    return LLMTools(tools=tools, prompt=PROMPT)
