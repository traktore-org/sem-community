"""Which battery mode / reserve controls an install has (#523, #1071).

A battery's mode and reserve are stored twice: the scalar ``battery_mode`` /
``battery_reserve_soc`` keys (written by the ONE global
``select.sem_battery_mode`` / ``number.sem_battery_reserve_soc``) and the
idx-aligned ``battery_modes`` / ``battery_reserve_socs`` lists (written by the
per-battery ``select.sem_battery_b<N>_mode`` / ``number…_reserve_soc``).

Only one of the two has a control on screen, so only one may drive the
battery. #1071: the select/number platforms picked the store by the battery
slugs found at setup, while ``_per_battery_config`` picked it by "is a list
slot set?". A one-battery install that kept a ``battery_modes`` list (.175:
``['auto', 'auto']``) showed the global select, and every write to it was
shadowed by the list — the select read ``force_charge``, SEM ran ``auto``.

The fix is one decision with one owner: ``discover_battery_control_slugs``
runs once in ``async_setup_entry``, before the first refresh and before any
platform builds an entity, and its answer is held on the coordinator. The
platforms build their controls from it and the runtime reads the store of the
controls that were built.

An UNSET reserve is the value its number shows, ``DEFAULT_BATTERY_RESERVE_SOC``
— the runtime used 0 % while the number showed 20 % (``reserve_soc_of``).
"""
from __future__ import annotations

import logging
import re
from collections.abc import Mapping
from typing import Any

from homeassistant.helpers import entity_registry as er

from ..ha_energy_reader import battery_units

_LOGGER = logging.getLogger(__name__)

#: (#523, #1195) The per-battery lists: slot N of each is battery bN's, and
#: ``_per_battery_config`` lays slot N over the key beside it. The entity
#: lists first (shown only while more than one battery runs, #1089), then
#: mode and reserve (shown by the per-battery controls, #1071).
PER_BATTERY_ENTITY_LISTS: tuple[tuple[str, str], ...] = (
    ("battery_force_discharge_entities", "battery_force_discharge_control_entity"),
    ("battery_discharge_control_entities", "battery_discharge_control_entity"),
    ("battery_strategy_entities", "battery_strategy_control_entity"),
    # (#1166) each pack's own end-of-charge level (read only)
    ("battery_charge_end_soc_entities", "battery_charge_end_soc_entity"),
)
PER_BATTERY_SETTING_LISTS: tuple[tuple[str, str], ...] = (
    ("battery_modes", "battery_mode"),
    ("battery_reserve_socs", "battery_reserve_soc"),
)
PER_BATTERY_LIST_KEYS: tuple[str, ...] = tuple(
    key for key, _ in PER_BATTERY_ENTITY_LISTS + PER_BATTERY_SETTING_LISTS)
#: (#1195) Which battery each slot of those lists belongs to: its entry in
#: ``battery_units`` (the combined power sensor, or a pair's charge sensor).
BATTERY_SLOT_UNITS_KEY = "battery_slot_units"

_BATTERY_SLUG_RE = re.compile(r"^sensor\.sem_battery_(b\d+)_power$")
# (#1171) the same sensor by its unique id (a renamed entity keeps it), and
# the per-battery Mode select (``<entry_id>_battery_<bid>_mode``)
_BATTERY_SENSOR_UID_RE = re.compile(r"^sem_battery_(b\d+)_power$")
_BATTERY_SELECT_UID_RE = re.compile(r"_battery_(b\d+)_mode$")


def discover_battery_control_slugs(coordinator: Any) -> tuple[str, ...]:
    """Short per-battery slugs (``b1`` …) for multi-battery installs.

    Primary source is the Energy Dashboard's batteries, combined sensors and
    two-sensor pairs (``battery_units``, #1171; the same list as the
    per-battery sensors in ``sensor.py``). But that depends
    on ``_energy_dashboard_config`` being populated at capture time, which
    a cold start (#274) can miss — so we FALL BACK to the
    persisted per-battery power sensors in the entity registry
    (``sensor.sem_battery_b<N>_power``). The registry survives restarts,
    so once a multi-battery install has its sensors the control entities
    are created deterministically on every boot. Empty on single-battery
    installs (no per-battery control entities created).

    (#1171) The per-battery Mode selects count too, and a sensor is known
    by its unique id as well. A cold start builds the per-battery sensors
    from the Energy Dashboard, so one that misses it sweeps them; the
    selects stay. Without them a second such start fell back to the one
    shared select, and the next normal start's handover
    (``adopt_shared_battery_settings``) wrote the shared mode over every
    battery's own.
    """
    sr = getattr(coordinator, "_sensor_reader", None)
    ed = getattr(sr, "_energy_dashboard_config", None) if sr is not None else None
    batt_list = battery_units(ed)
    if len(batt_list) > 1:
        return tuple(f"b{i + 1}" for i in range(len(batt_list)))

    # Fallback: discover from the persisted per-battery power sensors —
    # this entry's own (#1071 review: a second SEM entry's batteries are not
    # this install's).
    entry_id = getattr(getattr(coordinator, "config_entry", None), "entry_id", None)
    from ..const import DOMAIN

    def _slug(ent) -> str | None:
        m = _BATTERY_SLUG_RE.match(ent.entity_id)
        if m:
            return m.group(1)
        if ent.platform != DOMAIN or not isinstance(ent.unique_id, str):
            return None
        if ent.domain == "sensor":
            m = _BATTERY_SENSOR_UID_RE.match(ent.unique_id)
        elif (ent.domain == "select" and isinstance(entry_id, str)
              and ent.unique_id.startswith(f"{entry_id}_")):
            m = _BATTERY_SELECT_UID_RE.search(ent.unique_id)
        return m.group(1) if m else None

    try:
        reg = er.async_get(coordinator.hass)
        slugs = sorted({
            slug
            for ent in reg.entities.values()
            if (not isinstance(entry_id, str)
                or ent.config_entry_id == entry_id)
            and (slug := _slug(ent))
        })
        _LOGGER.debug("battery slugs (registry fallback): %s", slugs)
        return tuple(slugs) if len(slugs) > 1 else ()
    except Exception as exc:  # noqa: BLE001 — discovery must never break setup
        _LOGGER.debug("battery slug discovery failed: %s", exc)
        return ()


def captured_battery_control_slugs(coordinator: Any) -> tuple[str, ...] | None:
    """The slugs ``async_setup_entry`` captured, or None before the capture.

    Asks for a tuple on purpose: a test double that answers every attribute
    (``MagicMock``) has not captured anything."""
    slugs = getattr(coordinator, "battery_control_slugs", None)
    return slugs if isinstance(slugs, tuple) else None


def has_per_battery_controls(coordinator: Any, count: int) -> bool:
    """True → the per-battery lists drive each battery; False → the scalar
    keys drive every battery.

    ``async_setup_entry`` captures before the first refresh; the live battery
    count stands in only where nothing was captured (test doubles)."""
    slugs = captured_battery_control_slugs(coordinator)
    if slugs is not None:
        return len(slugs) > 1
    return count > 1


def adopt_shared_battery_settings(hass: Any, entry: Any, coordinator: Any,
                                  slugs: tuple[str, ...]) -> bool:
    """(#1171) The first start with one Mode select per battery, after the one
    shared select: each battery starts on what the shared select drove.

    A home moves to per-battery controls when it gains a second battery, or
    when an update first counts its two-sensor batteries (#1171). Under the
    shared select the ``battery_modes`` / ``battery_reserve_socs`` slots were
    not read. Empty, they run Auto at the default reserve, so a shared Off
    (SEM hands off) would become Auto with no one asking; a list left from an
    older layout would drive again (#531). So the shared mode and reserve are
    copied into every slot, once. The move is read from the registry, which
    still holds the shared select and no per-battery one: the platforms have
    not built or swept anything yet. True when the slots were written.
    """
    if len(slugs) < 2:
        return False
    from ..const import DOMAIN
    entry_id = entry.entry_id
    try:
        reg = er.async_get(hass)
        shared = reg.async_get_entity_id("select", DOMAIN, f"{entry_id}_battery_mode")
        own = any(
            reg.async_get_entity_id("select", DOMAIN, f"{entry_id}_battery_{bid}_mode")
            for bid in slugs)
    except Exception as exc:  # noqa: BLE001 — never break setup
        _LOGGER.debug("battery control handover check failed: %s", exc)
        return False
    if not shared or own:
        return False
    merged = {**(entry.data or {}), **(entry.options or {})}
    mode = merged.get("battery_mode") or None
    reserve = merged.get("battery_reserve_soc")
    new_options = {
        **(entry.options or {}),
        "battery_modes": [mode] * len(slugs),
        "battery_reserve_socs": [reserve] * len(slugs),
    }
    if isinstance(getattr(coordinator, "config", None), dict):
        # only these two: the coordinator's copy of the rest is its own
        coordinator.config.update({k: new_options[k] for k in (
            "battery_modes", "battery_reserve_socs")})
    hass.config_entries.async_update_entry(entry, options=new_options)
    _LOGGER.warning(
        "Battery controls: one Mode select and one reserve per battery now "
        "(%s). Each battery starts on the shared mode %s and reserve %s. %s "
        "and the shared reserve number go away; automations that set them "
        "need the per-battery ones.",
        ", ".join(slugs), mode or "auto",
        "default" if reserve is None else reserve, shared)
    return True


def _strip_unset_tail(slots: list) -> list:
    """A slot past the end of a list is unset, the same as ``None``."""
    out = list(slots)
    while out and out[-1] is None:
        out.pop()
    return out


def _old_slot_of(record: list, units: list) -> list[int | None]:
    """For each battery of ``units``, its slot in ``record`` (None: new).
    A sensor named twice takes its slots in turn."""
    unclaimed = list(range(len(record)))
    old_slot_of: list[int | None] = []
    for unit in units:
        j = next((k for k in unclaimed if record[k] == unit), None)
        if j is not None:
            unclaimed.remove(j)
        old_slot_of.append(j)
    return old_slot_of


def _battery_order(value: Any) -> list[str] | None:
    """A ``battery_slot_units`` record, or None for none or a damaged one."""
    if (isinstance(value, (list, tuple)) and value
            and all(isinstance(u, str) and u for u in value)):
        return list(value)
    return None


def slot_today(slot: int, read_units: Any, saved: Mapping) -> int | None:
    """(#1204) Where the battery at ``slot`` of the order a writer read is now.

    A writer that holds a per-battery list (the Config card, an open
    Configure dialog, a Mode select) holds it in the battery order it read,
    ``read_units`` — the ``battery_slot_units`` of that moment. The
    alignment may have moved every slot since. With no order on either side
    (none read, or none saved) the slot is taken as it stands, as the
    alignment does with no record. None: that battery is gone, or the writer
    had no battery at that place.
    """
    read = _battery_order(read_units)
    now = _battery_order(saved.get(BATTERY_SLOT_UNITS_KEY))
    if read is None or now is None or read == now:
        return slot
    if not 0 <= slot < len(read):
        return None
    return next((i for i, j in enumerate(_old_slot_of(read, now)) if j == slot),
                None)


def put_battery_slot(saved: Mapping, key: str, slot: int, value: Any,
                     read_units: Any) -> list:
    """(#1204) The saved list ``key`` with one battery's slot set.

    ``slot`` is the battery's place in the order the writer read
    (``slot_today``). Every other slot stays as saved, so a copy read
    before another writer changed a slot does not put the old value back.
    Raises ``LookupError`` when that battery is gone: its place now belongs
    to another battery."""
    target = slot_today(slot, read_units, saved)
    if target is None:
        raise LookupError(key)
    stored = saved.get(key)
    lst = list(stored) if isinstance(stored, list) else []
    while len(lst) <= target:
        lst.append(None)
    lst[target] = value
    return lst


def lists_in_current_order(written: Mapping, read_units: Any,
                           saved: Mapping) -> dict:
    """(#1204) Whole per-battery lists a writer read in one order, put in
    today's order.

    Each battery takes the writer's value from its place in the order the
    writer read. A battery the writer never saw keeps its saved value; the
    slot of a battery that is gone is dropped. Lists already in today's
    order (or with no order to follow) come back as they are. Only the keys
    of ``PER_BATTERY_LIST_KEYS`` that hold a list are returned.
    """
    lists = {k: v for k, v in written.items()
             if k in PER_BATTERY_LIST_KEYS and isinstance(v, list)}
    read = _battery_order(read_units)
    now = _battery_order(saved.get(BATTERY_SLOT_UNITS_KEY))
    if read is None or now is None or read == now:
        return lists
    sources = _old_slot_of(read, now)
    out: dict = {}
    for key, lst in lists.items():
        stored = saved.get(key)
        stored = stored if isinstance(stored, list) else []
        out[key] = _strip_unset_tail([
            (lst[j] if j < len(lst) else None) if j is not None
            else (stored[i] if i < len(stored) else None)
            for i, j in enumerate(sources)])
    return out


#: (#1204) No home has this many batteries; a larger slot is a damaged edit.
_MAX_BATTERY_SLOTS = 64


def battery_slot_edits(options: Mapping, saved: Mapping) -> dict:
    """(#1204) ``set_option`` options with each one-battery edit made whole.

    The Config card sends a per-battery list as one battery's edit:
    ``{"slot": N, "value": …, "battery_slot_units": [the order it read]}``.
    It becomes the saved list with that battery's slot set
    (``put_battery_slot``). A whole list (a script) is today's order and
    passes as it is. Raises ``ValueError`` on a damaged edit and
    ``LookupError`` when the battery is gone.
    """
    out = dict(options)
    for key in PER_BATTERY_LIST_KEYS:
        edit = options.get(key)
        if not isinstance(edit, Mapping):
            continue
        slot = edit.get("slot")
        value = edit.get("value")
        if (not isinstance(slot, int) or isinstance(slot, bool)
                or not 0 <= slot < _MAX_BATTERY_SLOTS or isinstance(value, bool)
                or not (value is None or isinstance(value, (str, int, float)))):
            raise ValueError(key)
        out[key] = put_battery_slot(saved, key, slot, value if value != "" else None,
                                    edit.get(BATTERY_SLOT_UNITS_KEY))
    return out


def _has_record(saved: Mapping) -> bool:
    record = saved.get(BATTERY_SLOT_UNITS_KEY)
    return isinstance(record, list) and all(isinstance(u, str) for u in record)


def _slots_stand_in(saved: Mapping, units: list, before: Any) -> list | None:
    """The battery order the saved slots are in: the record, else (#1226)
    ``before`` where it differs from ``units``, else None (as they stand)."""
    if _has_record(saved):
        return saved[BATTERY_SLOT_UNITS_KEY]
    if (isinstance(before, (list, tuple))
            and all(isinstance(u, str) and u for u in before)
            and list(before) != units):
        return list(before)
    return None


def realign_battery_slots(saved: Any, units: Any,
                          before: Any = None) -> tuple[dict, bool] | None:
    """(#1195) The per-battery lists put in the order of ``units``.

    Slot N of each list is battery bN's, and bN is the N-th entry of
    ``battery_units``: combined sensors first, then two-sensor pairs, each in
    Energy Dashboard order. A battery added or removed there moves the
    batteries after it, so a slot kept by its number went to another
    battery: a combined battery added to a home of two pairs became b1 and
    took the first pair's discharge entity.

    ``battery_slot_units`` says which battery each slot is for. Each battery
    takes its own slot back at its new number; a new battery starts unset; a
    removed battery's slots go. With no record yet the slots are taken as
    they stand, and a slot past the last battery is no battery's: left from
    an older, longer list, it drove the next battery added.

    (#1226) ``before``: the batteries in the order the saved slots were
    written for, used only while there is no record. A build before #1226
    counted a power sensor SEM found itself only when no battery had its
    own, so a battery found now beside others is not in it and starts unset,
    instead of taking the slot of the battery it pushed back.

    Returns ``(changes, moved)`` — the option keys to write, and whether the
    battery list is another than the one recorded — or None when the lists
    already are in this order. Pure. An empty ``units`` (no battery read
    yet) changes nothing.
    """
    if not isinstance(units, (list, tuple)) or not units:
        return None
    if not all(isinstance(u, str) and u for u in units):
        return None     # a gap would move every later battery: no answer
    units = list(units)
    first = not _has_record(saved)
    record = _slots_stand_in(saved, units, before)
    if record == units:
        return None
    if record is None:
        old_slot_of = list(range(len(units)))
    else:
        old_slot_of = _old_slot_of(record, units)
    changes: dict = {BATTERY_SLOT_UNITS_KEY: list(units)}
    for key in PER_BATTERY_LIST_KEYS:
        old = saved.get(key)
        if not isinstance(old, list):
            continue
        new = _strip_unset_tail([
            old[j] if j is not None and j < len(old) else None
            for j in old_slot_of])
        if new != _strip_unset_tail(old):
            changes[key] = new
    return changes, not first


def align_battery_slots(hass: Any, entry: Any, coordinator: Any, units: Any,
                        *, running: bool, before: Any = None) -> bool:
    """(#1195) Keep each battery's saved settings with that battery.

    Runs on every Energy Dashboard read: at setup, before the controls are
    captured and before the first command, and when the user edits the
    dashboard (#923). ``running`` says the platforms are built. Each
    battery's adapter holds its control entities from when it was built, and
    each select and number its slot number, so a battery list that changed
    while SEM runs reloads the entry once. A first record alone moves no
    slot and does not reload. Until the reload the battery pipeline sends
    nothing (``_battery_reload_pending``). True when the options were
    written.
    """
    options = getattr(entry, "options", None)
    data = getattr(entry, "data", None)
    if not isinstance(options, Mapping):
        return False
    merged = {**(data if isinstance(data, Mapping) else {}), **options}
    plan = realign_battery_slots(merged, units, before)
    if plan is None:
        return False
    changes, moved = plan
    new_options = {**options, **changes}
    if isinstance(getattr(coordinator, "config", None), dict):
        coordinator.config.update(changes)
    if running and not moved:
        # the options listener must not reload for a record alone
        coordinator._skip_options_reload = dict(new_options)
    if not running and getattr(coordinator, "_battery_controls_built", False) is not True:
        # (#1204) the controls are built after this, from the new places
        coordinator.battery_control_units = tuple(changes[BATTERY_SLOT_UNITS_KEY])
    elif not moved and not isinstance(
            getattr(coordinator, "battery_control_units", None), tuple):
        # (#1204) built with no record, the controls hold the places the
        # slots stood in until now (no reload follows a first record)
        coordinator.battery_control_units = tuple(
            _slots_stand_in(merged, list(units), before) or units)
    limits = "battery_discharge_control_entities"
    old_limits, new_limits = merged.get(limits), changes.get(limits, merged.get(limits))
    if not running and isinstance(old_limits, list):
        # a removed battery's cap is lifted at start (the unload lifts it
        # when SEM runs): ``restore_discharge_limit_on_startup``
        kept = new_limits if isinstance(new_limits, list) else []
        dropped = [e for e in old_limits if isinstance(e, str) and e and e not in kept]
        if dropped:
            coordinator._dropped_battery_limit_entities = dropped
    written = hass.config_entries.async_update_entry(entry, options=new_options)
    if running and moved and written:
        # until the reload, the battery pipeline sends nothing: the adapters
        # still hold the old places' entities
        coordinator._battery_reload_pending = True
    if moved:
        old_units = merged.get(BATTERY_SLOT_UNITS_KEY) or []
        new_units = [u for u in changes[BATTERY_SLOT_UNITS_KEY] if u not in old_units]
        _LOGGER.warning(
            "The batteries in the Energy Dashboard changed (%s → %s). Each "
            "battery keeps its own SEM settings at its new number%s%s.",
            ", ".join(old_units), ", ".join(changes[BATTERY_SLOT_UNITS_KEY]),
            "; new, starting on Auto with no entities of their own: "
            + ", ".join(new_units) if new_units else "",
            "; reloading to rebuild the battery controls" if running else "")
    return True
