"""(#1381) Say so when the phase guard stops a charger SEM yields to.

The guard's stop goes out even when another party steers the charger (the
fuse comes first), but SEM does not switch that charger back on: it is not
SEM's to start. Until the charger owner can hand it back, the user is told:
one Repair naming the charger, and the charger state "stopped by the phase
guard" instead of a plan's "night charging active" at 0 W. Both clear when
the charger draws again (switched on by hand or by its own app) or the car
is unplugged. The Repair is persistent, so it also carries the fact over an
HA restart.
"""
from __future__ import annotations

import logging
from typing import Any

from ..consts.states import ChargingState

_LOGGER = logging.getLogger(__name__)

#: The meter may still show the draw a few cycles after the stop.
GRACE_S = 120
#: A charger drawing more than this charges again.
DRAWING_W = 500.0


def _ir():
    from homeassistant.helpers import issue_registry
    return issue_registry


def _issue_id(cid: str) -> str:
    return f"guard_stopped_{cid}"


def _book(coord: Any) -> dict:
    book = getattr(coord, "_guard_held", None)
    if not isinstance(book, dict):
        book = {}
        coord._guard_held = book
    return book


def _name(coord: Any, cid: str) -> str:
    dev = (getattr(coord, "_ev_devices", None) or {}).get(cid) \
        or getattr(coord, "_ev_device", None)
    return str(getattr(dev, "name", None) or cid)


def note_stop(coord: Any, cid: str, reason: str, *, now: float) -> None:
    """The guard's stop of a yielded charger went out this cycle."""
    book = _book(coord)
    if cid in book:
        return
    book[cid] = float(now)
    _LOGGER.warning("phase guard stopped %s (%s); SEM does not switch it back "
                    "on — another party steers it", cid, reason)
    try:
        ir = _ir()
        ir.async_create_issue(
            coord.hass, "solar_energy_management", _issue_id(cid),
            is_fixable=False, is_persistent=True,
            severity=ir.IssueSeverity.WARNING,
            translation_key="guard_stopped",
            translation_placeholders={"charger": _name(coord, cid)})
    except Exception as e:  # noqa: BLE001 — a missing Repair is no failure
        _LOGGER.debug("issue_registry.create (guard_stopped) failed: %s", e)


def held(coord: Any, cid: str) -> bool:
    """Is this charger off after the guard's stop? After a restart, the
    Repair still standing says so."""
    book = _book(coord)
    if cid in book:
        return True
    try:
        reg = _ir().async_get(coord.hass)
        if reg.async_get_issue("solar_energy_management", _issue_id(cid)):
            book[cid] = 0.0          # from before the restart: no grace
            return True
    except Exception:  # noqa: BLE001
        pass
    return False


def update(coord: Any, cid: str, power: Any, *, now: float) -> None:
    """Every cycle, per charger: clear once it charges again or the car left."""
    if not held(coord, cid):
        return
    since = _book(coord).get(cid, 0.0)
    drawing = float(getattr(power, "power_w", 0.0) or 0.0) > DRAWING_W
    gone = bool(getattr(power, "car_absent", False))
    if gone or (drawing and now - since > GRACE_S):
        _book(coord).pop(cid, None)
        try:
            _ir().async_delete_issue(coord.hass, "solar_energy_management",
                                     _issue_id(cid))
        except Exception:  # noqa: BLE001
            pass


def effective_state(coord: Any, cid: str, state: str) -> str:
    return ChargingState.PHASE_GUARD_STOPPED if held(coord, cid) else state


def fleet_state(coord: Any, state: str, *, any_drawing: bool) -> str:
    """No car draws and a charger sits stopped: the fleet text says so."""
    if any_drawing or not _book(coord):
        return state
    return ChargingState.PHASE_GUARD_STOPPED
