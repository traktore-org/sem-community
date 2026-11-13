"""#1081 Slice A — what a kWh of HEAT costs, not what a kWh of electricity
costs. A heat pump's COP (coefficient of performance) means one kWh of
electricity makes ``COP`` kWh of heat, so heat's real price is
``price / COP`` — cheaper on a mild day (COP 4) than a cold one (COP 2)
even at the same electricity price. Pure, hass-free, mirrors
``curtailment.py``'s own contract.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional


def heat_pump_price(own_tariff: Any, house_provider: Any,
                    now: datetime) -> Optional[float]:
    """The heat pump's own tariff at ``now``, else the house import rate;
    ``None`` when neither gives a real number."""
    if own_tariff is not None:
        price = own_tariff.price_at(now)
    elif house_provider is not None and hasattr(house_provider, "get_current_import_rate"):
        price = house_provider.get_current_import_rate()
    else:
        return None
    if isinstance(price, bool) or not isinstance(price, (int, float)):
        return None
    return float(price)


def cost_of_heat(price: Optional[float], cop: Optional[float]) -> Optional[float]:
    """``price / cop``, or ``None`` when either is missing or ``cop`` is
    not a real, positive number — never guess a cost from a broken input."""
    if price is None or cop is None:
        return None
    try:
        cop = float(cop)
    except (TypeError, ValueError):
        return None
    if cop <= 0:
        return None
    return float(price) / cop


#: (#1081) A COP curve has 2 or 3 points: outdoor °C → COP.
COP_CURVE_MIN_POINTS = 2
COP_CURVE_MAX_POINTS = 3


def parse_cop_curve(raw: Any) -> Optional[list]:
    """(#1081) A heat pump's COP curve as sorted ``[(outdoor °C, COP)]``.

    Accepts the stored text ``"-7:2.5, 2:3.2, 12:4.2"`` or a list of pairs.
    ``None`` for "no curve" (empty) AND for anything that is not 2–3 points
    with distinct temperatures and a COP above 0 — a curve that cannot be
    read is no curve, never a guess."""
    if raw is None:
        return None
    pairs: list = []
    try:
        if isinstance(raw, str):
            text = raw.strip()
            if not text:
                return None
            for part in text.replace(";", ",").split(","):
                part = part.strip()
                if not part:
                    continue
                t, c = part.split(":")
                pairs.append((float(t), float(c)))
        else:
            for item in raw:
                t, c = item
                pairs.append((float(t), float(c)))
    except (TypeError, ValueError):
        return None
    if not COP_CURVE_MIN_POINTS <= len(pairs) <= COP_CURVE_MAX_POINTS:
        return None
    if any(c <= 0 or c != c or t != t for t, c in pairs):
        return None
    pairs.sort()
    if len({t for t, _ in pairs}) != len(pairs):
        return None
    return pairs


def format_cop_curve(curve: Optional[list]) -> str:
    """(#1081) The stored text of a parsed curve; ``""`` for none."""
    if not curve:
        return ""
    return ", ".join(f"{t:g}:{c:g}" for t, c in curve)


def cop_at(curve: Optional[list], outdoor_c: Optional[float],
           flat_cop: Optional[float]) -> tuple:
    """(#1081) The COP for an outdoor temperature: ``(cop, source)``.

    With a curve and a reading: linear between the points, clamped at the
    ends — ``source`` ``"curve"``. Otherwise the flat COP the user set,
    ``source`` ``"flat"`` (today's behaviour, unchanged)."""
    if curve and outdoor_c is not None:
        try:
            t = float(outdoor_c)
        except (TypeError, ValueError):
            t = None
        if t is not None and t == t:
            if t <= curve[0][0]:
                return float(curve[0][1]), "curve"
            if t >= curve[-1][0]:
                return float(curve[-1][1]), "curve"
            for (t0, c0), (t1, c1) in zip(curve, curve[1:], strict=False):
                if t0 <= t <= t1:
                    return float(c0 + (c1 - c0) * (t - t0) / (t1 - t0)), "curve"
    return flat_cop, "flat"


#: (#1081) where a heat pump's COP comes from — the user's choice per unit.
#: ``""`` (never chosen) = the curve when one is set, else the flat COP:
#: exactly what SEM did before it could learn.
COP_SOURCES = ("flat", "curve", "learned")
#: a learned curve is used only from this many trusted points on
LEARNED_MIN_POINTS = 2


def learned_curve_of(device: Any) -> Optional[list]:
    """(#1081) The device's learned curve when the user chose it and it has
    enough points; else None."""
    if str(getattr(device, "cop_source", "") or "") != "learned":
        return None
    pts = getattr(device, "cop_learned", None) or []
    return list(pts) if len(pts) >= LEARNED_MIN_POINTS else None


def device_cop_at(device: Any, outdoor_c: Optional[float]) -> tuple:
    """(#1081) The COP of ``device`` at ``outdoor_c``: ``(cop, source)``.

    ``cop_source`` "flat" → the flat COP. "learned" → the learned curve
    inside the temperatures it has seen; outside them the user's curve if
    there is one (the learned ends are not stretched over a cold snap it
    never measured), else the learned end. Not enough learned points → as
    if "curve". "curve" or unset → the user's curve, else flat."""
    flat = getattr(device, "cop", None)
    choice = str(getattr(device, "cop_source", "") or "")
    if choice == "flat":
        return flat, "flat"
    curve = getattr(device, "cop_curve", None)
    learned = learned_curve_of(device)
    if learned and outdoor_c is not None:
        try:
            t = float(outdoor_c)
        except (TypeError, ValueError):
            t = None
        if t is not None and t == t:
            inside = learned[0][0] <= t <= learned[-1][0]
            if inside or not curve:
                cop, src = cop_at(learned, t, flat)
                return cop, ("learned" if src == "curve" else src)
    return cop_at(curve, outdoor_c, flat)


def device_has_cop_shape(device: Any) -> bool:
    """(#1081) True when the COP of ``device`` can change with the outdoor
    temperature (a curve it uses, or a learned one it chose)."""
    if str(getattr(device, "cop_source", "") or "") == "flat":
        return False
    return bool(getattr(device, "cop_curve", None) or learned_curve_of(device))
