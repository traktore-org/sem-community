"""(#1346) A grid charge started by a SELECT, not a switch.

Some inverters have no switch for "charge the battery from the grid"; they
have a select with an option that means it ("Solar and mains" against
"Solar only"). The user names the select and the option that means a grid
charge. SEM starts the charge by setting that option and stops it by setting
the select back to what it showed before SEM changed it.

Asleep until BOTH settings are set, and only where no charge switch is set
(a switch wins, as it always did). These helpers only read; the writes and
the record are the generic charge adapter's, through the same record the
switch uses (``charge_record``), so a restart mid-charge is recovered.
"""
from __future__ import annotations

from typing import Any, Optional

from ...utils.select_option import listed_option

SELECT_KEY = "battery_charge_select_entity"
OPTION_KEY = "battery_charge_select_option"
_NO_STATE = ("", "unknown", "unavailable")


def select_setup(config: dict) -> Optional[tuple]:
    """``(select entity, charge option)`` when the select path is set up:
    both settings given and no charge switch beside them. Else None."""
    config = config or {}
    entity = str(config.get(SELECT_KEY) or "").strip()
    option = str(config.get(OPTION_KEY) or "").strip()
    if not entity or not option or config.get("battery_force_charge_switch"):
        return None
    return entity, option


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
