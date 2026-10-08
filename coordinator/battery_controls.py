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
runs once in ``async_setup_entry``, before any platform builds an entity, and
its answer is held on the coordinator. The platforms build their controls
from it and the runtime reads the store of the controls that were built.
"""
from __future__ import annotations

import logging
import re
from typing import Any

from homeassistant.helpers import entity_registry as er

_LOGGER = logging.getLogger(__name__)

_BATTERY_SLUG_RE = re.compile(r"^sensor\.sem_battery_(b\d+)_power$")


def discover_battery_control_slugs(coordinator: Any) -> tuple[str, ...]:
    """Short per-battery slugs (``b1`` …) for multi-battery installs.

    Primary source is the Energy Dashboard ``battery_power_list`` order
    (same as the per-battery sensors in ``sensor.py``). But that depends
    on ``_energy_dashboard_config`` being populated at platform-setup
    time, which can lag the first refresh — so we FALL BACK to the
    persisted per-battery power sensors in the entity registry
    (``sensor.sem_battery_b<N>_power``). The registry survives restarts,
    so once a multi-battery install has its sensors the control entities
    are created deterministically on every boot. Empty on single-battery
    installs (no per-battery control entities created).
    """
    sr = getattr(coordinator, "_sensor_reader", None)
    ed = getattr(sr, "_energy_dashboard_config", None) if sr is not None else None
    batt_list = list(getattr(ed, "battery_power_list", []) or []) if ed is not None else []
    if len(batt_list) > 1:
        return tuple(f"b{i + 1}" for i in range(len(batt_list)))

    # Fallback: discover from the persisted per-battery power sensors.
    try:
        reg = er.async_get(coordinator.hass)
        slugs = sorted({
            m.group(1)
            for ent in reg.entities.values()
            if (m := _BATTERY_SLUG_RE.match(ent.entity_id))
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

    Before the capture (the first refresh runs before the platforms) the live
    battery count stands in for it."""
    slugs = captured_battery_control_slugs(coordinator)
    if slugs is not None:
        return len(slugs) > 1
    return count > 1
