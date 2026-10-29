"""#1086 Part A — Assist intents: SEM explains a decision, states tonight's
cost, says whether now is a cheap time to charge, and — opt-in only — can
set a charger's target SOC.

**Explain-intents are always on; the one write-intent needs
``assist_write_intents_enabled``** (default off, ``persisted_flags.py``).
Each explain-intent reads data SEM already computed — the decision log
(#1174/#1084) and the stamped energy plan (#638/#1085 Part A) — no new
reasoning, matching the issue's own "nearly free" framing.

**Delivery, scoped down from the original plan:** registering these
``IntentHandler``s does NOT make Assist understand English sentences by
itself — that needs a ``custom_sentences/<lang>/*.yaml`` file in Home
Assistant's OWN config directory, and ALL such files across EVERY
integration are merged into ONE dict and compiled together
(``homeassistant/components/conversation/default_agent.py``,
``_load_intents``). A hassil-schema error in SEM's file could therefore
break Assist sentence compilation for the WHOLE house, not just SEM —
a materially bigger blast radius than anything else on this branch.
SEM does not write that file for the user; ``docs/USER_GUIDE.md`` ships
the sentences to copy in by hand, the same one-time step any other
custom-sentence addition needs. The intents below are simply unreachable
by voice until that file exists — inert, not broken, the same "complete
or inert" bar the rest of this branch holds to.
"""
from __future__ import annotations

import logging
from typing import Optional

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, intent

from .const import DOMAIN
from .coordinator import SEMCoordinator
from .coordinator.decision_log import KIND_BATTERY, KIND_CHARGER, DecisionLog
from .plain_reasons import DATA_KEY as PLAIN_REASONS_DATA_KEY, plain_sentence

_LOGGER = logging.getLogger(__name__)

INTENT_WHY_BATTERY = "SemWhyBattery"
INTENT_WHY_CHARGER = "SemWhyCharger"
INTENT_TONIGHT_COST = "SemTonightCost"
INTENT_GOOD_TO_CHARGE = "SemGoodToChargeNow"
INTENT_SET_TARGET_SOC = "SemSetChargerTargetSoc"

_NO_ANSWER = "I don't have an answer for that right now."


def _coordinator_for(hass: HomeAssistant) -> Optional[SEMCoordinator]:
    """The first loaded SEM entry's coordinator, same lookup
    ``decision_ws.py`` uses — SEM has no per-entry slot in a voice
    question, so "the" install is whichever one is actually running."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            return coordinator
    return None


def _first_charger_id(coordinator: SEMCoordinator, name: Optional[str]) -> Optional[str]:
    """``name`` matched against a configured charger's own name
    (case-insensitive substring); omitted or ambiguous → the first
    configured charger, a stable default, never a guess at WHICH one
    the question meant (#925)."""
    chargers = coordinator.config.get("ev_chargers") or []
    if not chargers:
        return None
    if name:
        needle = name.strip().lower()
        hits = [c for c in chargers
               if needle in str(c.get("name") or c.get("id") or "").lower()]
        if len(hits) == 1:
            return hits[0].get("id")
        if not hits:
            return None
    return chargers[0].get("id")


def _why_sentence(coordinator: SEMCoordinator, kind: str, device_id: str) -> str:
    log = getattr(coordinator, "decision_log", None)
    if not isinstance(log, DecisionLog) or not device_id:
        return _NO_ANSWER
    rec = log.last(kind, device_id)
    if rec is None:
        return _NO_ANSWER
    catalogue = coordinator.hass.data.get(PLAIN_REASONS_DATA_KEY, {})
    lang = getattr(coordinator.hass.config, "language", "en")
    sentence = plain_sentence(catalogue, str(rec.get("reason_code") or ""),
                              rec.get("params"), lang)
    return sentence or str(rec.get("text") or "").strip() or _NO_ANSWER


class WhyBatteryIntent(intent.IntentHandler):
    """"Why is the battery doing that?" — the battery's last decision,
    in the same plain sentence the logbook already shows."""

    intent_type = INTENT_WHY_BATTERY

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        # (99% case) the sole battery; a multi-battery fleet answers for
        # the first one — naming one is a Part B+ question, not this one.
        battery_id = next(iter(getattr(coordinator, "_battery_adapters", None) or ()), "primary")
        response.async_set_speech(_why_sentence(coordinator, KIND_BATTERY, battery_id))
        return response


class WhyChargerIntent(intent.IntentHandler):
    """"Why is the car charging/not charging?" — the named (or first)
    charger's last decision."""

    intent_type = INTENT_WHY_CHARGER
    slot_schema = {vol.Optional("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots.get("name", {}).get("value")
        charger_id = _first_charger_id(coordinator, name)
        if charger_id is None:
            response.async_set_speech(
                "I don't know which charger you mean." if name else _NO_ANSWER)
            return response
        response.async_set_speech(_why_sentence(coordinator, KIND_CHARGER, charger_id))
        return response


class TonightCostIntent(intent.IntentHandler):
    """"What will tonight cost?" — the stamped plan's own total, #638's
    number, never recomputed here."""

    intent_type = INTENT_TONIGHT_COST

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        coordinator = _coordinator_for(intent_obj.hass)
        plan = getattr(coordinator, "_energy_plan_shadow", None) if coordinator else None
        cost = plan.get("total_cost") if isinstance(plan, dict) else None
        if cost is None:
            response.async_set_speech(
                "I don't have tonight's plan yet.")
            return response
        response.async_set_speech(f"Tonight's plan costs about {cost:.2f}.")
        return response


class GoodToChargeNowIntent(intent.IntentHandler):
    """"Is now a good time to charge?" — the current slot's own cheap
    flag from the stamped plan; falls back to "I don't know" rather
    than invent a verdict the plan didn't already make (#925)."""

    intent_type = INTENT_GOOD_TO_CHARGE

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        response.response_type = intent.IntentResponseType.QUERY_ANSWER
        coordinator = _coordinator_for(intent_obj.hass)
        plan = getattr(coordinator, "_energy_plan_shadow", None) if coordinator else None
        slot_rows = plan.get("slots") if isinstance(plan, dict) else None
        if not isinstance(slot_rows, list):
            response.async_set_speech("I don't have a plan for right now.")
            return response
        from homeassistant.util import dt as dt_util
        now_iso = dt_util.now().isoformat()
        cheap = None
        for s in slot_rows:
            if isinstance(s, dict) and s.get("start") and s.get("end") \
                    and s["start"] <= now_iso < s["end"]:
                cheap = s.get("cheap")
                break
        if cheap is None:
            response.async_set_speech("I don't have a plan for right now.")
        elif cheap:
            response.async_set_speech("Yes, this is a cheap hour.")
        else:
            response.async_set_speech("No, this is not a cheap hour.")
        return response


class SetChargerTargetSocIntent(intent.IntentHandler):
    """"Charge the car to 80%" — the one write-intent, refused unless
    ``assist_write_intents_enabled`` is on (default off)."""

    intent_type = INTENT_SET_TARGET_SOC
    slot_schema = {
        vol.Optional("name"): cv.string,
        vol.Required("percent"): vol.All(vol.Coerce(int), vol.Range(min=0, max=100)),
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        hass = intent_obj.hass
        coordinator = _coordinator_for(hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not bool(coordinator.config.get("assist_write_intents_enabled", False)):
            response.async_set_speech(
                "Voice commands are read-only — turn on \"Voice commands\" "
                "in SEM's settings to let me change anything.")
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots.get("name", {}).get("value")
        percent = slots["percent"]["value"]
        charger_id = _first_charger_id(coordinator, name)
        if charger_id is None:
            response.async_set_speech(
                "I don't know which charger you mean." if name else _NO_ANSWER)
            return response
        entry = next((e for e in hass.config_entries.async_entries(DOMAIN)
                     if getattr(e, "runtime_data", None) is coordinator), None)
        if entry is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        from . import persist_per_charger_option
        persist_per_charger_option(
            hass, entry, coordinator, charger_id, "ev_target_soc", float(percent))
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(f"Set the target to {percent} percent.")
        return response


_HANDLERS = (
    WhyBatteryIntent, WhyChargerIntent, TonightCostIntent,
    GoodToChargeNowIntent, SetChargerTargetSocIntent,
)


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all of SEM's intent handlers. Idempotent — ``intent.
    async_register`` overwrites a same-named handler on a second call
    (a second config entry, a reload), it does not duplicate."""
    for handler_cls in _HANDLERS:
        intent.async_register(hass, handler_cls())
