"""(#1081) The Diagnose view of heat cost: per slot, what a kWh of heat costs
and whether the plan chose that slot for the device. Read-only: nothing
here decides anything, and no decision reads what it publishes. Pure,
hass-free like ``heat_cost``."""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Optional

from .heat_cost import cost_of_heat

#: rows kept per device (chosen slots first, then the cheapest heat): keeps
#: 2 devices x a 96-slot day well inside the recorder's attribute budget
MAX_ROWS_PER_DEVICE = 24

REASON_HEAT = "cheapest_heat"
REASON_GOAL = "comfort_goal"
REASON_PREHEAT = "preheat"
REASON_LOAD = "load"


def _num(value: Any, digits: int) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return round(float(value), digits) if value == value else None


def _cop_of(cop_at: Optional[Callable], start) -> Optional[float]:
    if cop_at is None:
        return None
    try:
        cop = cop_at(start)
    except Exception:  # noqa: BLE001 — no COP, no heat price
        return None
    return float(cop) if _num(cop, 3) is not None and cop > 0 else None


def chosen_slots(allocations: Iterable[Any], slots: List[Any],
                 reason_of: Callable[[Any, Any], str]) -> Dict[Any, str]:
    """``{slot start: reason}`` for the slots a device's allocations cover.
    ``reason_of(allocation, slot)`` names why."""
    out: Dict[Any, str] = {}
    for a in allocations:
        for s in slots:
            if s.start < a.end and a.start < s.end:
                out[s.start] = reason_of(a, s)
    return out


def device_rows(slots: List[Any], cop_at: Optional[Callable],
                chosen: Dict[Any, str]) -> List[list]:
    """``[[start, price, cop, heat_price, cheap, reason], ...]`` in time
    order: every chosen slot, then the cheapest heat among the rest, capped."""
    cand = []
    for s in slots:
        price = _num(s.price, 4)
        if price is None:
            continue
        cop = _cop_of(cop_at, s.start)
        heat = cost_of_heat(price, cop) if cop is not None else None
        cand.append((s, price, cop, heat))
    cand.sort(key=lambda c: (c[0].start not in chosen,
                             c[3] if c[3] is not None else c[1]))
    keep = sorted(cand[:MAX_ROWS_PER_DEVICE], key=lambda c: c[0].start)
    return [[s.start.isoformat(timespec="minutes"), price,
             _num(cop, 1), _num(heat, 3), 1 if s.tariff_cheap else 0,
             chosen.get(s.start)] for s, price, cop, heat in keep]


def build_heat_cost(slots: List[Any], entries: Iterable[Dict[str, Any]]
                    ) -> Dict[str, List[list]]:
    """``{device_id: rows}`` for the entries given; ``{}`` when none."""
    out: Dict[str, List[list]] = {}
    for e in entries:
        rows = device_rows(slots, e.get("cop_at"), e.get("chosen") or {})
        if rows:
            out[str(e["id"])] = rows
    return out
