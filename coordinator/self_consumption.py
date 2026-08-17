"""#755 pillar 2 — self-consumption, predicted.

The planner has always optimised money through slot price. Keeping your own
solar was never an objective; it fell out of pricing surplus hours at zero,
which made the sun win every comparison by fiat. Two consequences: the plan
could not say how much of tomorrow's solar it expected to keep, and a night
hour genuinely cheaper than the feed-in tariff could never win.

Pricing a surplus slot at the export rate (``day_ledger.build_day_slots``)
fixes the objective. This module answers the other half — what the resulting
schedule is expected to DO to the split — so the morning can compare it
against what the night recorder measured.

Pure: values in, values out. No clock, no I/O, no Home Assistant.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, Optional


@dataclass
class SelfConsumption:
    """The expected fate of a horizon's solar."""

    solar_kwh: float = 0.0
    self_consumed_kwh: float = 0.0
    exported_kwh: float = 0.0
    # Solar that WOULD have been exported and is consumed only because a
    # planned block sits in that slot. The number that answers "what did
    # planning buy me" — the rest of the keeping is the house being awake.
    from_plan_kwh: float = 0.0

    @property
    def share(self) -> Optional[float]:
        """Kept over produced. ``None`` when there was no solar at all —
        a midwinter night kept 0 of 0, which is not a failure and must not
        be reported as 0 %."""
        if self.solar_kwh <= 0:
            return None
        return self.self_consumed_kwh / self.solar_kwh

    def as_dict(self) -> Dict[str, Any]:
        return {
            "solar_kwh": round(self.solar_kwh, 2),
            "self_consumed_kwh": round(self.self_consumed_kwh, 2),
            "exported_kwh": round(self.exported_kwh, 2),
            "from_plan_kwh": round(self.from_plan_kwh, 2),
            "share": None if self.share is None else round(self.share, 3),
        }


def _parse(value) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except ValueError:
            return None
    return None


def _overlap_hours(a0: datetime, a1: datetime,
                   b0: Optional[datetime], b1: Optional[datetime]) -> float:
    if b0 is None or b1 is None:
        return 0.0
    lo, hi = max(a0, b0), min(a1, b1)
    if hi <= lo:
        return 0.0
    return (hi - lo).total_seconds() / 3600.0


def predict_self_consumption(slots, blocks) -> SelfConsumption:
    """The expected split over ``slots``, given the packed ``blocks``.

    ``blocks`` are the stamped plan's allocation rows (``start``/``end``
    ISO strings, ``power_w``) — a block spanning several slots contributes
    to each one pro rata, so a 90-minute block over an hourly grid is not
    counted twice.

    The house is served first: it is drawing anyway, and its share of the
    sun is not the plan's doing. Only what is left over can be exported,
    and only THAT is what a block competes for. Draw beyond the sun comes
    off the grid and is never counted as self-consumption — inventing solar
    here would be the estimate-teaching-the-model bug in a new costume.
    """
    out = SelfConsumption()
    for slot in slots or []:
        hours = getattr(slot, "hours", 0.0)
        if hours <= 0:
            continue
        solar = float(getattr(slot, "solar_w", 0.0) or 0.0) * hours / 1000.0
        if solar <= 0:
            continue
        house = float(getattr(slot, "home_gross_w", 0.0) or 0.0) \
            * hours / 1000.0
        by_house = min(solar, house)
        spare = solar - by_house

        planned = 0.0
        for b in blocks or []:
            p = float((b or {}).get("power_w") or 0.0)
            if p <= 0:
                continue
            planned += p * _overlap_hours(
                slot.start, slot.end,
                _parse((b or {}).get("start")),
                _parse((b or {}).get("end"))) / 1000.0

        by_plan = min(spare, planned)
        out.solar_kwh += solar
        out.self_consumed_kwh += by_house + by_plan
        out.exported_kwh += spare - by_plan
        out.from_plan_kwh += by_plan
    return out
