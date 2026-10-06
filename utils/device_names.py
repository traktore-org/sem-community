"""The names SEM gives the devices it controls (#1053).

A heat pump or hot-water heater the user did not name got an English
literal ("Heat Pump", "Heat Pump 2", "Hot Water"), so a Dutch dashboard
read "Heat Pump — draait naar verwachting". The default now comes from the
shared translation file in the Home Assistant language. A name the user set
is theirs and always wins; the old English defaults stored in existing
configs count as "not named" and are translated too.
"""
from __future__ import annotations

import re
from typing import Any, Optional

from .translate import get_text

# kind -> (translation key, the English defaults older SEM wrote into configs)
_KINDS = {
    "heat_pump": ("device_heat_pump", ("heat pump",)),
    "hot_water": ("device_hot_water", ("hot water",)),
}
_ENGLISH = {"heat_pump": "Heat pump", "hot_water": "Hot water"}

# The stored defaults older SEM wrote, kept for rows that need a name before
# Home Assistant's language is known; device_display_name translates them.
HEAT_PUMP_DEFAULT = "Heat Pump"
HOT_WATER_DEFAULT = "Hot Water"


def _old_default(stored: str, kind: str) -> Optional[tuple]:
    """(matched, number) when ``stored`` is one of SEM's old English defaults,
    such as "Heat Pump" or "Heat Pump 2"."""
    for base in _KINDS[kind][1]:
        m = re.fullmatch(rf"{re.escape(base)}(?:\s+(\d+))?", stored.strip(),
                         flags=re.IGNORECASE)
        if m:
            return True, (int(m.group(1)) if m.group(1) else None)
    return None


def device_display_name(hass: Any, stored: Optional[str], kind: str,
                        number: Optional[int] = None) -> str:
    """The name to show for a SEM-controlled device of ``kind``."""
    if kind not in _KINDS:
        return str(stored or "")
    text = str(stored or "").strip()
    if text:
        hit = _old_default(text, kind)
        if hit is None:
            return text                      # the user's own name
        number = hit[1] if hit[1] is not None else number
    base = (get_text(hass, _KINDS[kind][0], _ENGLISH[kind])
            if getattr(hass, "config", None) is not None else _ENGLISH[kind])
    return f"{base} {number}" if number else base
