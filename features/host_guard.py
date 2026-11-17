"""(#896) Does this switch look like it powers the network or Home Assistant?

Forum #30: shedding cut the circuit feeding the router and the HA host, SEM
died with it, and every shed circuit stayed off. A user can opt such a switch
in without noticing what it feeds. A name or area that says so makes it
"never switch off" by default; the user can allow it.

Words are matched as whole name parts ("ap" in ``switch.ap_attic``, not in
"map"), on generic device nouns only. Wrong guesses cost a protected load,
never a cut one.
"""
from __future__ import annotations

import re

# WHY a constant: one list for every reader (registry, load manager, tests).
# Generic nouns for what a home's network and HA host are called, in English
# and German; no brand names.
HOST_WORDS = (
    "router", "modem", "switch_netzwerk", "network", "netzwerk", "wifi",
    "wlan", "access_point", "ap", "nas", "server", "homeassistant",
    "home_assistant", "ha", "raspberry", "rpi", "nuc", "proxmox", "ups",
    "internet", "fritz",
)

WARNING = ("This looks like it powers your network or Home Assistant. "
           "SEM will never switch it off unless you allow it.")


def _norm(text: str) -> str:
    return "_" + re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_") + "_"


def looks_like_host(*texts: object) -> bool:
    """True when any text (entity id, name, area) holds a host/network word.
    An entity id's domain (``switch.``) is not part of its name."""
    parts = []
    for t in texts:
        if not t:
            continue
        s = str(t)
        parts.append(s.split(".", 1)[1] if re.match(r"^[a-z_]+\.", s) else s)
    return any(_has(_norm(p), w) for p in parts for w in HOST_WORDS)


def _has(norm: str, word: str) -> bool:
    # a long word also opens a longer one (fritz -> fritzbox, server ->
    # serverschrank); a short one ("ap", "ha", "nas") must stand alone
    if len(word) >= 5:
        return f"_{word}" in norm
    return re.search(rf"_{word}\d*_", norm) is not None   # rpi4, nas2


def area_name_of(hass, entity_id: str | None) -> str:
    """The area name of an entity (its own, else its device's); "" if none."""
    if not entity_id:
        return ""
    try:
        from homeassistant.helpers import area_registry as ar
        from homeassistant.helpers import device_registry as dr
        from homeassistant.helpers import entity_registry as er
        ent = er.async_get(hass).async_get(entity_id)
        if ent is None:
            return ""
        area_id = ent.area_id
        if not area_id and ent.device_id:
            dev = dr.async_get(hass).async_get(ent.device_id)
            area_id = dev.area_id if dev else None
        area = ar.async_get(hass).async_get_area(area_id) if area_id else None
        return area.name if area else ""
    except Exception:  # noqa: BLE001 — a guess aid; never costs a sync
        return ""
