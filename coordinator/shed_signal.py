"""(#1021) The grid operator's "reduce load" signal (§14a EnWG, ripple control).

One optional relay entity, ``on`` = active. While active, ``cap_kw`` is the
grid-import limit the operator allows (Germany). Anything unreadable on the
relay = NOT active, and the state says why: the operator's own relay is the
hard stop; SEM's part is to stay under it, never to lock a house out of its
grid on a broken wire. An unreadable CAP falls back to 4.2 kW, the legal
per-device floor — never to "no cap".

Pure: no Home Assistant import, the caller hands in ``get_state``.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

# §14a EnWG: the operator may never dim a device below 4.2 kW.
LEGAL_FLOOR_KW = 4.2

_ON = ("on", "true")
_OFF = ("off", "false")


@dataclass(frozen=True)
class ShedSignal:
    """What the relay says this cycle."""

    active: bool
    source: Optional[str]
    state: str                  # none | on | off | unavailable | unknown
    cap_kw: Optional[float]     # set only while active


INERT = ShedSignal(False, None, "none", None)


def _positive(value: Any) -> Optional[float]:
    if isinstance(value, bool):
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    return v if v > 0 else None


def _cap(limit: Any, get_state: Callable[[str], Any]) -> float:
    """The cap in kW: a number, a numeric string, or a sensor entity id."""
    v = _positive(limit)
    if v is not None:
        return v
    if isinstance(limit, str) and "." in limit:
        try:
            v = _positive(getattr(get_state(limit), "state", None))
        except Exception:  # noqa: BLE001 — an unreadable cap is the floor
            v = None
        if v is not None:
            return v
    return LEGAL_FLOOR_KW


def read_shed_signal(entity_id: Optional[str], limit: Any,
                     get_state: Callable[[str], Any]) -> ShedSignal:
    """Read the relay and its cap. Never raises."""
    if not entity_id:
        return INERT
    try:
        raw = str(getattr(get_state(entity_id), "state", "unknown")
                  or "unknown").lower()
    except Exception:  # noqa: BLE001 — a reader that cannot ask is off
        raw = "unknown"
    if raw in _ON:
        return ShedSignal(True, entity_id, "on", _cap(limit, get_state))
    if raw in _OFF:
        return ShedSignal(False, entity_id, "off", None)
    return ShedSignal(False, entity_id,
                      raw if raw == "unavailable" else "unknown", None)
