"""(#1083) Add simulated days up: per day, per day type, overall.

Pure. Every number here is modelled; the result says so at the top
(``"modelled": True``) so no reader can take it for a measurement.
``delta`` is simulated − recorded: below 0 the what-if would have cost less.
"""
from __future__ import annotations

from typing import Iterable, List

#: the day types the Simulation tab totals
SUMMARY_TAGS = ("sunny", "mixed", "grey", "car", "cheap")


def _blank() -> dict:
    return {"days": 0, "actual_cost": 0.0, "simulated_cost": 0.0,
            "delta": 0.0, "kwh_over_limit": 0.0, "indicative_days": 0}


def _add(total: dict, day) -> None:
    total["days"] += 1
    total["actual_cost"] += float(day.actual_cost)
    total["simulated_cost"] += float(day.simulated_cost)
    total["delta"] += float(day.delta)
    total["kwh_over_limit"] += float(day.kwh_over_limit)
    total["indicative_days"] += 1 if day.indicative else 0


def _rounded(total: dict) -> dict:
    return {k: (round(v, 2) if isinstance(v, float) else v)
            for k, v in total.items()}


def summarise(days: Iterable) -> dict:
    """``days`` are ``DayResult``s. Returns rows, per-tag and overall."""
    rows: List[dict] = []
    by_tag = {t: _blank() for t in SUMMARY_TAGS}
    overall = _blank()
    for day in days:
        rows.append({
            "date": day.date, "tags": list(day.tags),
            "actual_cost": round(float(day.actual_cost), 2),
            "simulated_cost": round(float(day.simulated_cost), 2),
            "delta": round(float(day.delta), 2),
            "kwh_over_limit": round(float(day.kwh_over_limit), 2),
            "indicative": bool(day.indicative),
            "indicative_reasons": list(day.indicative_reasons),
        })
        _add(overall, day)
        for tag in SUMMARY_TAGS:
            if tag in day.tags:
                _add(by_tag[tag], day)
    return {
        "modelled": True,
        "days": rows,
        "by_tag": {t: _rounded(v) for t, v in by_tag.items()},
        "overall": _rounded(overall),
    }
