"""#1086 Part A/B — Assist intents: SEM explains a decision, states
tonight's cost, says whether now is a cheap time to charge, and — opt-in
only — can set a charger's target SOC or hold a one-off override.

**Part B (time/suspend) was blocked on #1085 Part B** (``plan_override``)
and is unblocked now it exists. "Don't charge the car tonight" and
"charge the car now" wrap ``coordinator.set_plan_override`` — the SAME
one-off, self-expiring mechanism #1085 built, not
``set_charger_departure`` (the persistent weekly table #1085's own issue
exists to stop misusing for a one-night ask). Scoped down from the
plan's own example ("charge to 80% before 07:00"): ``plan_override``'s
``force`` action is CHARGE_MAX, the same unconditional command #580's
VPP import-boost already uses — it does not respect a target SOC, so a
voice command promising "to 80%" would overshoot. "Charge the car to
80%" (a STANDING preference, matching the dashboard slider) is
``SetChargerTargetSocIntent`` below; "charge the car now, for an hour"
(a ONE-OFF, self-expiring force) is the new ``ForceChargeNowIntent`` —
two different, honest asks, not one intent over-promising both.

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
from .coordinator.plan_override import MAX_OVERRIDE_MINUTES
from .coordinator.decision_log import KIND_BATTERY, KIND_CHARGER, DecisionLog
from .plain_reasons import DATA_KEY as PLAIN_REASONS_DATA_KEY, plain_sentence

_LOGGER = logging.getLogger(__name__)

INTENT_WHY_BATTERY = "SemWhyBattery"
INTENT_WHY_CHARGER = "SemWhyCharger"
INTENT_TONIGHT_COST = "SemTonightCost"
INTENT_GOOD_TO_CHARGE = "SemGoodToChargeNow"
INTENT_SET_TARGET_SOC = "SemSetChargerTargetSoc"
INTENT_SKIP_TONIGHT = "SemSkipChargerTonight"
INTENT_FORCE_CHARGE_NOW = "SemForceChargeNow"
INTENT_CLEAR_OVERRIDE = "SemClearPlanOverride"

_NO_ANSWER = "I don't have an answer for that right now."
_WRITE_REFUSED = ("Voice commands are read-only — turn on \"Voice commands\" "
                  "in SEM's settings to let me change anything.")
#: (#1086 Part B) a one-off that names no duration holds for this long.
_DEFAULT_OVERRIDE_MINUTES = 8 * 60


def _coordinator_for(hass: HomeAssistant) -> Optional[SEMCoordinator]:
    """The first loaded SEM entry's coordinator, same lookup
    ``decision_ws.py`` uses — SEM has no per-entry slot in a voice
    question, so "the" install is whichever one is actually running."""
    for entry in hass.config_entries.async_entries(DOMAIN):
        coordinator = getattr(entry, "runtime_data", None)
        if coordinator is not None:
            return coordinator
    return None


def _first_charger_id(coordinator: SEMCoordinator, name: Optional[str],
                      write: bool = False) -> Optional[str]:
    """``name`` matched against a configured charger's own name
    (case-insensitive substring). A name that fits none or several
    chargers → ``None``. No name → the first charger for a question; a
    change (``write``) needs a name once there is more than one charger,
    so a command never lands on a guessed car (#925)."""
    chargers = coordinator.config.get("ev_chargers") or []
    if not chargers:
        return None
    if write and not name and len(chargers) > 1:
        return None
    if name:
        needle = name.strip().lower()
        hits = [c for c in chargers
               if needle in str(c.get("name") or c.get("id") or "").lower()]
        return hits[0].get("id") if len(hits) == 1 else None
    return chargers[0].get("id")


def _entry_for(hass: HomeAssistant, coordinator: SEMCoordinator):
    """The config entry THIS coordinator's own runtime_data points at —
    needed by any write, since ``persist_per_charger_option`` takes the
    entry, not the coordinator alone."""
    return next((e for e in hass.config_entries.async_entries(DOMAIN)
                if getattr(e, "runtime_data", None) is coordinator), None)


def _minutes_until_departure(coordinator: SEMCoordinator, charger_id: str) -> int:
    """(#1086 Part B) "Tonight" for THIS charger — until its own next
    departure (weekday table or calendar, #1023/#1087), the same
    deadline the card and the night planner already show. Falls back to
    a plain default rather than refuse the whole intent on a bad read —
    a voice command is not the place to surface a stack trace."""
    try:
        from homeassistant.util import dt as dt_util
        from .coordinator.departure import departure_for
        charger_cfg = next(
            (c for c in (coordinator.config.get("ev_chargers") or [])
             if str(c.get("id")) == charger_id), {})
        now = dt_util.now()
        calendar_next = coordinator._calendar_departure_for(charger_id)
        departure = departure_for(charger_cfg, now, coordinator.config,
                                  calendar_next=calendar_next)
        minutes = int((departure - now).total_seconds() / 60)
        if minutes <= 0:
            return _DEFAULT_OVERRIDE_MINUTES
        return min(minutes, MAX_OVERRIDE_MINUTES)
    except Exception:  # noqa: BLE001 — a bad read is the default, not a crash
        return _DEFAULT_OVERRIDE_MINUTES


def _duration_words(minutes: int) -> str:
    if minutes < 60:
        return f"{minutes} minute{'s' if minutes != 1 else ''}"
    hours = round(minutes / 60)
    return f"{hours} hour{'s' if hours != 1 else ''}"


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
                "I don't know which charger you mean — say its name."
                if name or len(coordinator.config.get("ev_chargers") or []) > 1
                else _NO_ANSWER)
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
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots.get("name", {}).get("value")
        percent = slots["percent"]["value"]
        charger_id = _first_charger_id(coordinator, name, write=True)
        if charger_id is None:
            response.async_set_speech(
                "I don't know which charger you mean — say its name."
                if name or len(coordinator.config.get("ev_chargers") or []) > 1
                else _NO_ANSWER)
            return response
        entry = _entry_for(hass, coordinator)
        if entry is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        from . import persist_per_charger_option
        persist_per_charger_option(
            hass, entry, coordinator, charger_id, "ev_target_soc", float(percent))
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(f"Set the target to {percent} percent.")
        return response


class SkipChargerTonightIntent(intent.IntentHandler):
    """(#1086 Part B) "Don't charge the car tonight" — a one-off
    ``plan_override(action="skip")``, not the persistent weekly table:
    tomorrow's charging is untouched, the same thing #1085 itself was
    built to guarantee."""

    intent_type = INTENT_SKIP_TONIGHT
    slot_schema = {vol.Optional("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not bool(coordinator.config.get("assist_write_intents_enabled", False)):
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots.get("name", {}).get("value")
        charger_id = _first_charger_id(coordinator, name, write=True)
        if charger_id is None:
            response.async_set_speech(
                "I don't know which charger you mean — say its name."
                if name or len(coordinator.config.get("ev_chargers") or []) > 1
                else _NO_ANSWER)
            return response
        minutes = _minutes_until_departure(coordinator, charger_id)
        coordinator.set_plan_override(charger_id, "skip", minutes)
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(
            f"Stopped charging for the next {_duration_words(minutes)}.")
        return response


class ForceChargeNowIntent(intent.IntentHandler):
    """(#1086 Part B) "Charge the car now" — a one-off
    ``plan_override(action="force")``, the same unconditional CHARGE_MAX
    #580's VPP import-boost already uses. Does not target a specific
    SOC — see the module docstring for why "to 80%" is a different
    intent (``SetChargerTargetSocIntent``), not this one."""

    intent_type = INTENT_FORCE_CHARGE_NOW
    slot_schema = {
        vol.Optional("name"): cv.string,
        vol.Optional("minutes"): vol.All(vol.Coerce(int), vol.Range(min=1, max=24 * 60)),
    }

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not bool(coordinator.config.get("assist_write_intents_enabled", False)):
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots.get("name", {}).get("value")
        minutes = slots.get("minutes", {}).get("value") or 60
        charger_id = _first_charger_id(coordinator, name, write=True)
        if charger_id is None:
            response.async_set_speech(
                "I don't know which charger you mean — say its name."
                if name or len(coordinator.config.get("ev_chargers") or []) > 1
                else _NO_ANSWER)
            return response
        coordinator.set_plan_override(charger_id, "force", minutes)
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(f"Charging now, for {minutes} minutes.")
        return response


class ClearPlanOverrideIntent(intent.IntentHandler):
    """(#1086 Part B) "Charge normally again" — ends a one-off override
    now, before its own time is up. The symmetric undo for the two
    intents above."""

    intent_type = INTENT_CLEAR_OVERRIDE
    slot_schema = {vol.Optional("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not bool(coordinator.config.get("assist_write_intents_enabled", False)):
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        name = slots.get("name", {}).get("value")
        charger_id = _first_charger_id(coordinator, name, write=True)
        if charger_id is None:
            response.async_set_speech(
                "I don't know which charger you mean — say its name."
                if name or len(coordinator.config.get("ev_chargers") or []) > 1
                else _NO_ANSWER)
            return response
        coordinator.clear_plan_override(charger_id)
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech("Back to normal.")
        return response


_HANDLERS = (
    WhyBatteryIntent, WhyChargerIntent, TonightCostIntent,
    GoodToChargeNowIntent, SetChargerTargetSocIntent,
    SkipChargerTonightIntent, ForceChargeNowIntent, ClearPlanOverrideIntent,
)


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all of SEM's intent handlers. Idempotent — ``intent.
    async_register`` overwrites a same-named handler on a second call
    (a second config entry, a reload), it does not duplicate."""
    for handler_cls in _HANDLERS:
        intent.async_register(hass, handler_cls())
