"""(#1346) A grid charge started by a SELECT, not a switch.

Some inverters have no switch for "charge the battery from the grid"; they
have a select with an option that means it ("Solar and mains" against
"Solar only"). The user names the select and the option that means a grid
charge. SEM starts the charge by setting that option and stops it by setting
the select back to what it showed before SEM changed it.

Asleep until BOTH settings are set. These helpers only read; the writes and
the record are the generic charge adapter's, through the same record the
switch uses (``charge_record``), so a restart mid-charge is recovered.

(#1377) A charge switch set BESIDE the pair is no longer the start: it is a
PERMIT, turned on with the charge and put back after it. A Powerwall charges
from the grid only with "allow grid charging" on, the reserve raised AND its
operating mode changed — three entities, one charge.
"""
from __future__ import annotations

from typing import Any, Optional

from ...utils.select_option import listed_option

SELECT_KEY = "battery_charge_select_entity"
OPTION_KEY = "battery_charge_select_option"
_NO_STATE = ("", "unknown", "unavailable")

#: (#1377) A select or permit that showed SEM's value and now reads the value
#: it had BEFORE SEM's write is not taken as the end at once: a cloud
#: integration can show the old values for minutes after a write that landed,
#: then SEM's again (a Tesla Powerwall, 23.11.2026: all three entities read
#: their old values at 20:05, mode and permit read SEM's again at 20:16, with
#: no write in between). The end counts once the old value has read this long
#: without a break; nothing is written meanwhile. Any OTHER value is a change
#: made since, and ends the charge at once.
AWAY_FOR_S = 15 * 60.0
#: (#1377) a select SEM wrote must show the option within this long before
#: the one re-send, and as long again before the start is given up: the hold
#: select's rule (``hold_select.SHOW_WITHIN_S``), for the same cloud selects
SHOW_WITHIN_S = 60.0


def select_setup(config: dict) -> Optional[tuple]:
    """``(select entity, charge option)`` when the select path is set up:
    both settings given. Else None."""
    config = config or {}
    entity = str(config.get(SELECT_KEY) or "").strip()
    option = str(config.get(OPTION_KEY) or "").strip()
    if not entity or not option:
        return None
    return entity, option


def permit_switch(config: dict) -> str:
    """(#1377) The switch that must be ON for the select's option to charge
    from the grid, or "". Only beside a select pair: alone it is the start."""
    if select_setup(config) is None:
        return ""
    return str((config or {}).get("battery_force_charge_switch") or "").strip()


def read_select(hass: Any, entity: str) -> tuple:
    """``(state, options)``. ``state`` is None when the select cannot be
    read (not loaded, unknown, unavailable): could-not-ask, never a guess."""
    try:
        st = hass.states.get(entity)
    except Exception:  # noqa: BLE001 — a read never costs a cycle
        return None, []
    state = getattr(st, "state", None)
    raw = getattr(st, "attributes", None) or {}
    options = raw.get("options") if hasattr(raw, "get") else None
    options = [str(o) for o in options] if isinstance(options, (list, tuple)) else []
    if not isinstance(state, str) or state in _NO_STATE:
        return None, options
    return state, options


def charge_option(hass: Any, entity: str, option: str) -> str:
    """The option as the select lists it (#1039); unchanged when unlisted."""
    return str(listed_option(hass, entity, option))
