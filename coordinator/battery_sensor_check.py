"""(#1256) Which sensors and controls of the batteries SEM depends on are
missing, and which replacements fit.

The "no battery power sensor" Repair named one sensor. A battery whose power
sensor went also lost its SOC sensor or a control, and the user found out one
by one. This lists every battery entity SEM is wired to that is gone, and the
entities that could take its place, found by role (device class, unit,
domain) — never by brand.
"""
from __future__ import annotations

from typing import Any, Iterable, Mapping

from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN

from ..utils.own_entity import is_sem_entity
from .battery_controls import PER_BATTERY_ENTITY_LISTS

#: SEM config key → what the entity is. ``control`` stands for any entity SEM
#: writes to (or watches as a setting): a replacement must be of its domain.
_ROLE_OF_KEY: dict[str, str] = {
    "battery_power_sensor": "power",
    "battery_soc_sensor": "soc",
    "battery_soc_entity": "soc",
    "battery_charge_energy_sensor": "energy",
    "battery_discharge_energy_sensor": "energy",
    "battery_energy_discharged_sensor": "energy",
    "battery_cycles_sensor": "cycles",
    "battery_temperature_sensor": "temperature",
    "battery_target_soc_entity": "control",
    "battery_charge_end_soc_entity": "control",
    "battery_operating_mode_entity": "control",
    "battery_charge_power_limit_entity": "control",
    "battery_discharge_control_entity": "control",
    "battery_force_discharge_control_entity": "control",
    "battery_strategy_control_entity": "control",
    "battery_power_direction_entity": "control",
}
_ROLE_OF_LIST_KEY = {list_key: "control" for list_key, _ in PER_BATTERY_ENTITY_LISTS}
_CLASS_OF_ROLE = {"power": "power", "soc": "battery", "energy": "energy",
                  "temperature": "temperature"}
_UNITS_OF_ROLE = {"power": {"W", "kW", "MW"}, "soc": {"%"},
                  "energy": {"Wh", "kWh", "MWh"}}
MAX_CANDIDATES = 25


def entity_is_down(hass: Any, entity_id: str) -> bool:
    """No state, or one that carries no value."""
    state = hass.states.get(entity_id)
    return state is None or state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN)


def _add(found: dict, entity: Any, role: str, place: list) -> None:
    if isinstance(entity, str) and "." in entity:
        slot = found.setdefault(entity, {"entity": entity, "role": role, "places": []})
        slot["places"].append(place)


def _wired(merged: Mapping, ed: Any) -> dict[str, dict]:
    """Every battery entity SEM is wired to, with the places that name it."""
    found: dict[str, dict] = {}
    for key, role in _ROLE_OF_KEY.items():
        _add(found, merged.get(key), role, ["config", key, None])
    for key, role in _ROLE_OF_LIST_KEY.items():
        values = merged.get(key)
        for slot, entity in enumerate(values if isinstance(values, list) else []):
            _add(found, entity, role, ["config", key, slot])
    if ed is not None:
        for entity in list(getattr(ed, "battery_power_list", None) or []):
            _add(found, entity, "power", ["dashboard", None, None])
        for pair in getattr(ed, "battery_power_pairs", None) or []:
            for entity in pair:
                _add(found, entity, "power", ["dashboard", None, None])
        for entity in list(getattr(ed, "battery_soc_list", None) or []):
            _add(found, entity, "soc", ["dashboard", None, None])
        counters = getattr(ed, "battery_unit_counters", None)
        for pair in (counters.values() if isinstance(counters, dict) else []):
            for entity in pair:
                _add(found, entity, "energy", ["dashboard", None, None])
    return found


def battery_problems(hass: Any, merged: Mapping, ed: Any = None, *,
                     unsourced: str | None = None,
                     beside: bool = False) -> list[dict]:
    """The battery entities that are gone or unavailable, one row per entity.

    A row: ``entity``, ``role``, ``places`` (``[where, key, slot]``: the
    config key or list slot that names it, or the Energy Dashboard) and
    ``editable`` — SEM can re-point it when a config key names it.

    ``unsourced``: the Energy Dashboard counters that have no power sensor
    at all. Its row has an empty ``entity``. SEM's power pick stands for the
    whole battery, so it is offered only when no other battery is read
    (``beside``) and no pick is already one of the rows.
    """
    out = []
    for entity, row in _wired(merged, ed).items():
        if entity_is_down(hass, entity):
            row["editable"] = any(p[0] == "config" for p in row["places"])
            out.append(row)
    if unsourced and beside:
        out.insert(0, {"entity": "", "label": unsourced, "role": "power",
                       "places": [["dashboard", None, None]], "editable": False})
    elif unsourced and not any(
            ["config", "battery_power_sensor", None] in r["places"] for r in out):
        out.insert(0, {"entity": "", "label": unsourced, "role": "power",
                       "places": [["config", "battery_power_sensor", None]],
                       "editable": True})
    return out


def candidates(hass: Any, row: Mapping, *, taken: Iterable[str] = ()) -> list[str]:
    """Entities that fit this row's role, those that answer first.

    A power, SOC or energy sensor must carry that device class and unit; a
    control must be of the domain of the entity it replaces. Entities SEM
    already uses for a battery are left out.
    """
    role = row.get("role")
    domain = str(row.get("entity") or "").split(".", 1)[0] or "sensor"
    if role in _CLASS_OF_ROLE or role == "cycles":
        domain = "sensor"
    skip = set(taken) | {row.get("entity")}
    live, down = [], []
    for state in hass.states.async_all(domain):
        if state.entity_id in skip or is_sem_entity(hass, state.entity_id):
            continue
        attrs = state.attributes
        if role in _CLASS_OF_ROLE and attrs.get("device_class") != _CLASS_OF_ROLE[role]:
            continue
        units = _UNITS_OF_ROLE.get(role)
        if units and attrs.get("unit_of_measurement") not in units:
            continue
        (down if state.state in (STATE_UNAVAILABLE, STATE_UNKNOWN) else live
         ).append(state.entity_id)
    return sorted(live)[:MAX_CANDIDATES] or sorted(down)[:MAX_CANDIDATES]


def apply_replacements(merged: Mapping, replacements: Mapping[str, str],
                       rows: Iterable[Mapping]) -> dict:
    """The option changes that point each ``replacements`` old entity to its
    new one, in every config place that names it (a list place keeps its
    slot). Pure."""
    changes: dict = {}
    for row in rows:
        new = replacements.get(row["entity"])
        if not new:
            continue
        for where, key, slot in row["places"]:
            if where != "config":
                continue
            if slot is None:
                changes[key] = new
                continue
            values = changes.get(key)
            if values is None:
                stored = merged.get(key)
                values = list(stored) if isinstance(stored, list) else []
            while len(values) <= slot:
                values.append(None)
            values[slot] = new
            changes[key] = values
    return changes
