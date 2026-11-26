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
import re
from datetime import datetime, timedelta
from typing import Optional

import voluptuous as vol
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, intent

from .const import DOMAIN
from .coordinator import SEMCoordinator
from .coordinator.plan_override import MAX_OVERRIDE_MINUTES
from .coordinator.units import finite_float
from .coordinator.decision_log import (
    KIND_BATTERY, KIND_CHARGER, DecisionLog, current)
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
# (#1431) four more: set the mode, charge until, the peak limit, savings
INTENT_SET_CHARGE_MODE = "SemSetChargeMode"
INTENT_CHARGE_NOW_UNTIL = "SemChargeNowUntil"
INTENT_SET_PEAK_LIMIT = "SemSetPeakLimit"
INTENT_SOLAR_SAVINGS = "SemSolarSavings"

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


def write_intents_enabled(coordinator: SEMCoordinator) -> bool:
    """The ONE gate for every write intent, here and in ``llm.py`` (#1086):
    the "Voice commands" switch. Off by default."""
    return bool(coordinator.config.get("assist_write_intents_enabled", False))


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
    # (#1086) the record while it still fits, else the live reason
    rec = current(kind, device_id, coordinator)
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
    # (#1086) the AI reads this to decide when to call the tool
    description = "Explain in one sentence why the solar battery is charging, discharging or idle right now."

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
    # (#1086) the AI reads this to decide when to call the tool
    description = "Explain why an EV charger is charging or not charging right now. Optional name picks the charger."
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
        chargers = coordinator.config.get("ev_chargers") or []
        if charger_id is None and chargers:
            # (#1379) a question, not a command: a name that fits no charger
            # ("my car") gets every charger's answer instead of a question back
            lines = [f"{c.get('name') or c.get('id')}: "
                     f"{_why_sentence(coordinator, KIND_CHARGER, c.get('id'))}"
                     for c in chargers if c.get("id")]
            response.async_set_speech(" ".join(lines) or _NO_ANSWER)
            return response
        if charger_id is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        response.async_set_speech(_why_sentence(coordinator, KIND_CHARGER, charger_id))
        return response


class TonightCostIntent(intent.IntentHandler):
    """"What will tonight cost?" — the stamped plan's own total, #638's
    number, never recomputed here."""

    intent_type = INTENT_TONIGHT_COST
    # (#1086) the AI reads this to decide when to call the tool
    description = "Say what tonight's planned EV and battery charging will cost."

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
    # (#1086) the AI reads this to decide when to call the tool
    description = "Say whether the current hour is a cheap time to charge the EV."

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
        sun = False
        for s in slot_rows:
            if isinstance(s, dict) and s.get("start") and s.get("end") \
                    and s["start"] <= now_iso < s["end"]:
                cheap = s.get("cheap")
                # (#1310) a sun slot is a good hour at any tariff; "cheap"
                # is the tariff's own word and stays false at its peak
                sun = s.get("sun") is True
                break
        if cheap is None:
            response.async_set_speech("I don't have a plan for right now.")
        elif sun:
            response.async_set_speech("Yes, the plan expects spare solar now.")
        elif cheap:
            response.async_set_speech("Yes, this is a cheap hour.")
        else:
            response.async_set_speech("No, this is not a cheap hour.")
        return response


class SetChargerTargetSocIntent(intent.IntentHandler):
    """"Charge the car to 80%" — the one write-intent, refused unless
    ``assist_write_intents_enabled`` is on (default off)."""

    intent_type = INTENT_SET_TARGET_SOC
    # (#1086) the AI reads this to decide when to call the tool
    description = "Set an EV charger's standing target charge level in percent. Optional name picks the charger."
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
        if not write_intents_enabled(coordinator):
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
    # (#1086) the AI reads this to decide when to call the tool
    description = "Skip EV charging tonight only. Tomorrow is normal. Optional name picks the charger."
    slot_schema = {vol.Optional("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not write_intents_enabled(coordinator):
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
    # (#1086) the AI reads this to decide when to call the tool
    description = "Charge the EV now at full power for a set time (default 1 hour), once."
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
        if not write_intents_enabled(coordinator):
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
        # (#1430) A voice "charge now" is the user's own Now (#1381 D31):
        # marked so, it runs an Off or paused charger for these minutes and
        # the charger is Off or paused again after. An unmarked force left
        # Off alone while the speech said "Charging now".
        coordinator.set_plan_override(charger_id, "force", minutes, user_now=True)
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(f"Charging now, for {minutes} minutes.")
        return response


class ClearPlanOverrideIntent(intent.IntentHandler):
    """(#1086 Part B) "Charge normally again" — ends a one-off override
    now, before its own time is up. The symmetric undo for the two
    intents above."""

    intent_type = INTENT_CLEAR_OVERRIDE
    # (#1086) the AI reads this to decide when to call the tool
    description = "End a skip or charge-now once early and return the charger to normal."
    slot_schema = {vol.Optional("name"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not write_intents_enabled(coordinator):
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


# ── (#1431) four more ───────────────────────────────────────────────────

#: Spoken / written mode names → the select's four options.
_MODE_WORDS = {
    "off": "off", "stop": "off",
    "sun": "sun", "solar": "sun", "sun only": "sun",
    "sun + tariff": "sun_tariff", "sun plus tariff": "sun_tariff",
    "sun and tariff": "sun_tariff", "sun tariff": "sun_tariff",
    "sun_tariff": "sun_tariff", "sun+tariff": "sun_tariff",
    "solar + tariff": "sun_tariff", "solar plus tariff": "sun_tariff",
    "solar and tariff": "sun_tariff", "tariff": "sun_tariff",
    "now": "now", "full power": "now", "charge now": "now",
    # the old six names said aloud: passed on as the stored strategy, so the
    # select's alias path keeps the battery switch exactly as that mode had it
    "solar only": "solar_only", "only solar": "solar_only",
    "solar plus battery": "solar_plus_battery", "solar and battery": "solar_plus_battery",
    "solar + battery": "solar_plus_battery",
    "solar plus cheapest hours": "solar_plus_cheap", "cheapest hours": "solar_plus_cheap",
    "solar + cheapest hours": "solar_plus_cheap",
    "min plus solar": "min_plus_solar", "min + solar": "min_plus_solar",
    "minimum plus solar": "min_plus_solar",
    "always max": "always_max", "always maximum": "always_max",
}
_MODE_LABEL = {"off": "Off", "sun": "Sun", "sun_tariff": "Sun + tariff", "now": "Now"}
_WATCH_ONLY = " SEM is in watch-only mode, so nothing is sent to the charger yet."
_PEAK_RANGE = (1.0, 80.0)


def _watch_only_note(coordinator: SEMCoordinator) -> str:
    """(#1431) A change in watch-only mode is stored but moves nothing."""
    return _WATCH_ONLY if getattr(coordinator, "_observer_mode", False) else ""
_FULL_WORDS = {"full", "until full", "the car is full", "100", "100%", "100 percent"}
_CLOCK = re.compile(
    r"^\s*(\d{1,2})(?:[:.h](\d{2}))?\s*(?:o'?\s*clock|uhr)?\s*(am|pm|a\.m\.|p\.m\.)?\s*$",
    re.IGNORECASE)
#: (#1431) the savings sensors per period, the ones the Insights screen reads
_SAVINGS = {
    "today": ("daily_savings", "daily_battery_savings"),
    "this month": ("monthly_savings", "monthly_battery_savings"),
    "this year": ("yearly_savings", "yearly_battery_savings"),
}
_PERIOD_WORDS = {
    "today": "today", "day": "today", "this day": "today",
    "month": "this month", "this month": "this month",
    "year": "this year", "this year": "this year",
}


def _charge_mode_select(hass: HomeAssistant, charger_id: str):
    """(#1431) The charger's charge-mode select ENTITY. A voice change goes
    through its own ``async_select_option`` — the one write path that holds
    the old-name aliases, the same-mode idempotency, the battery switch and
    the user's Now (#1381 S9/S11). ``select.select_option`` would refuse an
    old name such as ``always_max`` before the entity saw it."""
    component = hass.data.get("entity_components", {}).get("select")
    if component is None:
        return None
    return component.get_entity(f"select.sem_charger_{charger_id}_charge_mode")


def minutes_until_clock(text: str, now: datetime) -> Optional[int]:
    """(#1431) Minutes from ``now`` to the next ``text`` o'clock ("07:00",
    "7", "7 pm", "19.30"), 1..1440. ``None`` when it is not a clock time."""
    m = _CLOCK.match(str(text or ""))
    if not m:
        return None
    hour, minute = int(m.group(1)), int(m.group(2) or 0)
    half = (m.group(3) or "").lower().replace(".", "")
    if half == "pm" and hour < 12:
        hour += 12
    elif half == "am" and hour == 12:
        hour = 0
    if hour > 23 or minute > 59:
        return None
    end = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if end <= now:
        end += timedelta(days=1)
    minutes = int(round((end - now).total_seconds() / 60))
    return max(1, min(minutes, MAX_OVERRIDE_MINUTES))


def _which_charger_or_say(response, coordinator, name) -> Optional[str]:
    charger_id = _first_charger_id(coordinator, name, write=True)
    if charger_id is None:
        response.async_set_speech(
            "I don't know which charger you mean — say its name."
            if name or len(coordinator.config.get("ev_chargers") or []) > 1
            else _NO_ANSWER)
    return charger_id


class SetChargeModeIntent(intent.IntentHandler):
    """(#1431) "Set the charger to Sun + tariff" — through the select."""

    intent_type = INTENT_SET_CHARGE_MODE
    description = ("Set an EV charger's charge mode: Off, Sun, Sun + tariff "
                   "or Now. Optional name picks the charger.")
    slot_schema = {vol.Optional("name"): cv.string, vol.Required("mode"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not write_intents_enabled(coordinator):
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        mode = _MODE_WORDS.get(str(slots["mode"]["value"]).strip().lower())
        if mode is None:
            response.async_set_speech("Say Off, Sun, Sun + tariff or Now.")
            return response
        charger_id = _which_charger_or_say(
            response, coordinator, slots.get("name", {}).get("value"))
        if charger_id is None:
            return response
        entity = _charge_mode_select(intent_obj.hass, charger_id)
        if entity is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        await entity.async_select_option(mode)
        from .consts.ev_charge_modes import user_mode_of
        shown = mode if mode in _MODE_LABEL else user_mode_of(mode)
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(
            f"The charger is on {_MODE_LABEL.get(shown, shown)}." + _watch_only_note(coordinator))
        return response


class ChargeNowUntilIntent(intent.IntentHandler):
    """(#1431) "Charge until 7 o'clock" / "charge until full" — the user's
    own Now with its end, the same two paths the card's Now uses."""

    intent_type = INTENT_CHARGE_NOW_UNTIL
    description = ("Charge the EV now at full power until a clock time "
                   "(for example 07:00) or until the car is full ('full'). "
                   "Optional name picks the charger.")
    slot_schema = {vol.Optional("name"): cv.string, vol.Required("until"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not write_intents_enabled(coordinator):
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        until = str(slots["until"]["value"]).strip().lower()
        charger_id = _which_charger_or_say(
            response, coordinator, slots.get("name", {}).get("value"))
        if charger_id is None:
            return response
        if until in _FULL_WORDS:
            entity = _charge_mode_select(intent_obj.hass, charger_id)
            if entity is None:
                response.async_set_speech(_NO_ANSWER)
                return response
            # the untimed Now, "until full" (#1381 S11) — the select's alias
            await entity.async_select_option("always_max")
            response.response_type = intent.IntentResponseType.ACTION_DONE
            response.async_set_speech(
                "Charging now, until the car is full." + _watch_only_note(coordinator))
            return response
        from homeassistant.util import dt as dt_util
        minutes = minutes_until_clock(until, dt_util.now())
        if minutes is None:
            response.async_set_speech("Say a time, such as 7 o'clock, or say full.")
            return response
        coordinator.set_plan_override(
            charger_id, "force", minutes, user_now=True, fixed_end=True)
        end = (dt_util.now() + timedelta(minutes=minutes)).strftime("%H:%M")
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(f"Charging now, until {end}." + _watch_only_note(coordinator))
        return response


class SetPeakLimitIntent(intent.IntentHandler):
    """(#1431) "Set the peak limit to 3.5 kW" — the ``update_target_peak``
    action itself, so a voice change and an automation are one path."""

    intent_type = INTENT_SET_PEAK_LIMIT
    description = "Set SEM's grid peak limit in kW (1 to 80)."
    slot_schema = {vol.Required("kw"): vol.Coerce(float)}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        coordinator = _coordinator_for(intent_obj.hass)
        if coordinator is None:
            response.async_set_speech(_NO_ANSWER)
            return response
        if not write_intents_enabled(coordinator):
            response.async_set_speech(_WRITE_REFUSED)
            return response
        slots = self.async_validate_slots(intent_obj.slots)
        kw = round(float(slots["kw"]["value"]), 1)
        if not _PEAK_RANGE[0] <= kw <= _PEAK_RANGE[1]:
            response.async_set_speech("The peak limit must be between 1 and 80 kW.")
            return response
        from homeassistant.exceptions import ServiceNotFound
        try:
            await intent_obj.hass.services.async_call(
                DOMAIN, "update_target_peak", {"target_peak_limit": kw}, blocking=True)
        except ServiceNotFound:   # SEM half-started: say so, never a stack trace
            response.async_set_speech(_NO_ANSWER)
            return response
        response.response_type = intent.IntentResponseType.ACTION_DONE
        response.async_set_speech(f"The peak limit is now {kw:g} kW." + (
            " SEM is in watch-only mode, so it only plans with it."
            if getattr(coordinator, "_observer_mode", False) else ""))
        return response


class SolarSavingsIntent(intent.IntentHandler):
    """(#1431) "How much did solar save this month?" — the savings sensors
    the Insights screen shows: the sun's part plus the battery's."""

    intent_type = INTENT_SOLAR_SAVINGS
    description = ("Say how much solar and the home battery saved today, "
                   "this month or this year.")
    slot_schema = {vol.Optional("period"): cv.string}

    async def async_handle(self, intent_obj: intent.Intent) -> intent.IntentResponse:
        response = intent_obj.create_response()
        hass = intent_obj.hass
        slots = self.async_validate_slots(intent_obj.slots)
        word = str(slots.get("period", {}).get("value") or "today").strip().lower()
        period = _PERIOD_WORDS.get(word, "today")
        sun_key, batt_key = _SAVINGS[period]
        values, unit = [], ""
        for key in (sun_key, batt_key):
            state = hass.states.get(f"sensor.sem_{key}")
            try:
                values.append(finite_float(state.state))
                unit = unit or str(state.attributes.get("unit_of_measurement") or "")
            except (AttributeError, TypeError, ValueError):
                values.append(None)
        sun, batt = values
        if sun is None and batt is None:
            response.async_set_speech(f"There is no savings figure for {period} yet.")
            return response
        total = (sun or 0.0) + (batt or 0.0)
        unit = f" {unit}" if unit else ""
        text = f"Solar saved {total:.2f}{unit} {period}"
        if batt:
            text += f", {batt:.2f}{unit} of it through the battery"
        response.async_set_speech(text + ".")
        return response


EXPLAIN_HANDLERS = (
    WhyBatteryIntent, WhyChargerIntent, TonightCostIntent, GoodToChargeNowIntent,
    SolarSavingsIntent,
)
WRITE_HANDLERS = (
    SetChargerTargetSocIntent, SkipChargerTonightIntent,
    ForceChargeNowIntent, ClearPlanOverrideIntent,
    SetChargeModeIntent, ChargeNowUntilIntent, SetPeakLimitIntent,
)
_HANDLERS = EXPLAIN_HANDLERS + WRITE_HANDLERS


def async_register_intents(hass: HomeAssistant) -> None:
    """Register all of SEM's intent handlers. Idempotent — ``intent.
    async_register`` overwrites a same-named handler on a second call
    (a second config entry, a reload), it does not duplicate."""
    for handler_cls in _HANDLERS:
        intent.async_register(hass, handler_cls())
