"""(#1381 D19) Old charge-mode names in the user's automations and scripts.

The charge-mode select now offers the four modes (sun, sun_tariff, now, off).
Home Assistant checks ``select.select_option`` against the select's options
before SEM sees the call, so an automation or script that still picks one of
the six old names (``solar_only`` …) fails with "not a valid option", and a
state trigger or condition on an old name never matches again. SEM's own
``set_option`` service keeps accepting the old names.

This module finds those uses — read-only, in the configs Home Assistant has
loaded — and keeps ONE Repair that names each automation or script and the
name to use now. The Repair goes away by itself once nothing uses an old
name.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any, Iterable, List, Mapping, Tuple

from ..consts.ev_charge_modes import EV_CHARGE_MODES, USER_MODES, user_mode_of

_LOGGER = logging.getLogger(__name__)

ISSUE_ID = "old_charge_mode_names"
_SELECT_RE = re.compile(r"^select\.sem_charger_.*charge_mode$")
#: The six stored names that are not also one of the four new ones.
OLD_NAMES = frozenset(n for n in EV_CHARGE_MODES if n not in USER_MODES)
_VALUE_KEYS = ("option", "state", "to", "from")
#: (#1381 D32) A SEM charge-mode select named anywhere in a config's text:
#: whole, or built from pieces in a template ("select.sem_charger_" … "charge_mode")
_SELECT_TEXT_RE = re.compile(r"select\.sem_charger_[A-Za-z0-9_{} .~|'\"]*charge_mode")
_OLD_WORD_RE = re.compile(
    r"(?<![A-Za-z0-9_])(" + "|".join(sorted(OLD_NAMES, key=len, reverse=True))
    + r")(?![A-Za-z0-9_])")


def _mentions_select(text: str) -> bool:
    if _SELECT_TEXT_RE.search(text):
        return True
    return "select.sem_charger_" in text and "charge_mode" in text


def _entities(node: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for holder in (node, node.get("target"), node.get("data")):
        if not isinstance(holder, Mapping):
            continue
        ent = holder.get("entity_id")
        if isinstance(ent, str):
            out.append(ent)
        elif isinstance(ent, (list, tuple)):
            out.extend(e for e in ent if isinstance(e, str))
    return out


def _values(node: Mapping[str, Any]) -> List[str]:
    out: List[str] = []
    for holder in (node, node.get("data")):
        if not isinstance(holder, Mapping):
            continue
        for key in _VALUE_KEYS:
            v = holder.get(key)
            if isinstance(v, str):
                out.append(v)
            elif isinstance(v, (list, tuple)):
                out.extend(x for x in v if isinstance(x, str))
    return out


def _walk(node: Any) -> Iterable[Mapping[str, Any]]:
    if isinstance(node, Mapping):
        yield node
        for v in node.values():
            yield from _walk(v)
    elif isinstance(node, (list, tuple)):
        for v in node:
            yield from _walk(v)


def find_old_mode_uses(kind: str, configs: Iterable[Any]) -> List[Tuple[str, str, str]]:
    """``(name, old, new)`` for every automation or script config that sets
    or tests a SEM charge-mode select with an old name. ``kind`` names the
    source (only for logging). SEM's own ``set_option`` is not reported: it
    takes the old names."""
    found: List[Tuple[str, str, str]] = []
    for cfg in configs:
        if not isinstance(cfg, Mapping):
            continue
        name = str(cfg.get("alias") or cfg.get("id") or kind)
        seen = set()
        for node in _walk(cfg):
            if not any(_SELECT_RE.match(e) for e in _entities(node)):
                continue
            for v in _values(node):
                if v in OLD_NAMES and v not in seen:
                    seen.add(v)
                    found.append((name, v, user_mode_of(v)))
        # (#1381 D32) …and the whole config as text: a template condition,
        # an option or entity held in a variable, data_template, a comma
        # string of entities, blueprint inputs. A config that names a SEM
        # charge-mode select AND an old mode name anywhere is reported.
        # Judged per step (an action, condition or trigger), so another
        # select's old-looking option in the same automation is not blamed.
        held = _text({k: cfg.get(k) for k in
                      ("variables", "__blueprint_inputs", "use_blueprint")})
        held_names_select = _mentions_select(held)
        words = []
        if held_names_select and not any(
                isinstance(n, Mapping) and any(k in n for k in _STEP_KEYS)
                for n in _walk(cfg)):
            words.append(held)          # a blueprint: its inputs are all there is
        for node in _walk(cfg):
            if not any(k in node for k in _STEP_KEYS):
                continue
            t = _text(node)
            here = _mentions_select(t)
            templated = "{{" in t
            if here or (templated and held_names_select):
                words.append(t)
            if here and templated:
                words.append(held)
        for t in words:
            for m in _OLD_WORD_RE.finditer(t):
                v = m.group(1)
                if v not in seen:
                    seen.add(v)
                    found.append((name, v, user_mode_of(v)))
    return found


#: keys that make a mapping one step of an automation or script
_STEP_KEYS = ("action", "service", "condition", "trigger", "platform",
              "value_template")


def _text(obj: Any) -> str:
    try:
        return json.dumps(obj, default=str, ensure_ascii=False)
    except (TypeError, ValueError):
        return str(obj)


def _loaded_configs(hass: Any, domain: str) -> List[Any]:
    """The configs Home Assistant has loaded for ``domain`` (automation or
    script), read from its entities' ``raw_config``. Empty when unreadable."""
    try:
        comp = hass.data.get(domain)
        entities = getattr(comp, "entities", None) or ()
        out = []
        for e in entities:
            raw = getattr(e, "raw_config", None)
            # (#1381 D32) a blueprint automation keeps its inputs apart
            bp = getattr(e, "raw_blueprint_inputs", None)
            if isinstance(raw, Mapping) and isinstance(bp, Mapping):
                raw = {**raw, "__blueprint_inputs": bp}
            out.append(raw)
        return out
    except Exception:  # noqa: BLE001 — unreadable is "nothing found"
        return []


def check_old_mode_uses(hass: Any) -> List[Tuple[str, str, str]]:
    """Scan, then raise or clear the one Repair. Returns what it found."""
    found = (find_old_mode_uses("automation", _loaded_configs(hass, "automation"))
             + find_old_mode_uses("script", _loaded_configs(hass, "script")))
    try:
        from homeassistant.helpers import issue_registry as ir
        from ..const import DOMAIN
        if found:
            lines = "; ".join(f"{n}: {old} → {new}" for n, old, new in found[:20])
            ir.async_create_issue(
                hass, domain=DOMAIN, issue_id=ISSUE_ID,
                is_fixable=False, is_persistent=False,
                severity=ir.IssueSeverity.WARNING,
                translation_key=ISSUE_ID,
                translation_placeholders={"uses": lines},
            )
            _LOGGER.warning("Old charge mode names in use: %s", lines)
        else:
            ir.async_delete_issue(hass, DOMAIN, ISSUE_ID)
    except Exception as e:  # noqa: BLE001 — a Repair never breaks startup
        _LOGGER.debug("old mode names Repair failed: %s", e)
    return found
