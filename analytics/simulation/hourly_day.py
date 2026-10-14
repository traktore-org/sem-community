"""(#1083) One recorded day as 24 hours of kWh — the simulation's input.

Pure: no Home Assistant, no clock. The job reads the recorder's hourly
long-term statistics and hands the rows here; the replay tool builds the
same shape from its own recordings.

Flows come from SEM's own TOTAL counters (midnight reset), so an hour's
``change`` is the gross kWh of that hour. A negative change is a counter
reset: that hour counts 0 and is marked missing — never a negative flow.
Measurements (SOC, prices, forecast) come from the hourly ``mean``.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date as _date, datetime, tzinfo
from typing import Any, Dict, Iterable, List, Mapping, Optional

HOURS = 24

#: flow roles — gross kWh per hour, from a TOTAL counter's ``change``
SOLAR = "solar"
GRID_IMPORT = "grid_import"
GRID_EXPORT = "grid_export"
BATTERY_CHARGE = "battery_charge"
BATTERY_DISCHARGE = "battery_discharge"
EV = "ev"
HOME = "home"
FLOW_ROLES = (SOLAR, GRID_IMPORT, GRID_EXPORT, BATTERY_CHARGE,
              BATTERY_DISCHARGE, EV, HOME)

#: measurement roles — the hour's ``mean``
SOC = "soc"
IMPORT_RATE = "import_rate"
EXPORT_RATE = "export_rate"
FORECAST = "forecast"
MEAN_ROLES = (SOC, IMPORT_RATE, EXPORT_RATE, FORECAST)

ROLES = FLOW_ROLES + MEAN_ROLES

#: Every house has these. A role with no rows at all here means the
#: recorder had nothing — every hour is missing. The other flow roles may
#: be absent on purpose (no battery, no car) and then read as 0.
CORE_ROLES = (SOLAR, GRID_IMPORT, GRID_EXPORT, HOME)


def _zeros() -> List[float]:
    return [0.0] * HOURS


def _nones() -> List[Optional[float]]:
    return [None] * HOURS


@dataclass
class HourlyDay:
    """24 hours of one day. kWh per flow, mean SOC % and prices per hour."""

    date: str
    tags: List[str] = field(default_factory=list)
    solar: List[float] = field(default_factory=_zeros)
    grid_import: List[float] = field(default_factory=_zeros)
    grid_export: List[float] = field(default_factory=_zeros)
    battery_charge: List[float] = field(default_factory=_zeros)
    battery_discharge: List[float] = field(default_factory=_zeros)
    ev: List[float] = field(default_factory=_zeros)
    home: List[float] = field(default_factory=_zeros)
    soc_pct: List[Optional[float]] = field(default_factory=_nones)
    #: None = not recorded; the caller's flat rate stands in
    import_rate: List[Optional[float]] = field(default_factory=_nones)
    export_rate: List[Optional[float]] = field(default_factory=_nones)
    forecast_kwh: Optional[float] = None
    missing_hours: List[int] = field(default_factory=list)

    def __post_init__(self) -> None:
        for role in FLOW_ROLES:
            vals = list(getattr(self, role))
            if len(vals) != HOURS:
                raise ValueError(f"{role}: {len(vals)} hours, need {HOURS}")
            setattr(self, role, [float(v or 0.0) for v in vals])
        for name in ("soc_pct", "import_rate", "export_rate"):
            vals = list(getattr(self, name))
            if len(vals) != HOURS:
                raise ValueError(f"{name}: {len(vals)} hours, need {HOURS}")
            setattr(self, name, [None if v is None else float(v) for v in vals])
        self.tags = [str(t) for t in (self.tags or [])]
        self.missing_hours = sorted({int(h) for h in self.missing_hours})

    @property
    def gap(self) -> bool:
        return "gap" in self.tags

    def flows(self, hour: int) -> Dict[str, float]:
        """The seven flows of one hour, in kWh."""
        return {role: getattr(self, role)[hour] for role in FLOW_ROLES}

    def total(self, role: str) -> float:
        return float(sum(getattr(self, role)))

    def first_soc(self) -> Optional[float]:
        return next((s for s in self.soc_pct if s is not None), None)

    @classmethod
    def from_statistics(
        cls,
        rows_by_role: Mapping[str, Iterable[Mapping[str, Any]]],
        *,
        date: Any,
        tags: Iterable[str] = (),
        tz: Optional[tzinfo] = None,
    ) -> "HourlyDay":
        """Build a day from a recorder hourly-statistics read.

        ``rows_by_role`` maps a role name (``ROLES``) to that entity's rows:
        ``{"start": datetime | ISO text | epoch seconds, "change": kWh}`` for
        a flow, ``{"start": …, "mean": value}`` for a measurement. ``tz`` is
        the house's time zone; a row's hour is its local hour. Epoch
        seconds need ``tz`` (ValueError without it — never read as UTC). A row of
        another day is ignored. Two rows on one hour (the autumn clock
        change) add up for a flow; the later mean wins for a measurement.
        """
        day = _as_date(date)
        out: Dict[str, Any] = {role: _zeros() for role in FLOW_ROLES}
        means: Dict[str, List[Optional[float]]] = {
            role: _nones() for role in MEAN_ROLES}
        missing = set()
        for role in FLOW_ROLES:
            rows = list(rows_by_role.get(role) or [])
            if not rows:
                if role in CORE_ROLES:
                    missing.update(range(HOURS))
                continue
            seen = set()
            for row in rows:
                hour = _hour_of(row.get("start"), day, tz)
                if hour is None:
                    continue
                change = row.get("change")
                try:
                    change = None if change is None else float(change)
                except (TypeError, ValueError):
                    change = None
                if change is None or change < 0:
                    # A reset or a hole: 0 for the hour, and say so.
                    missing.add(hour)
                    seen.add(hour)
                    continue
                out[role][hour] += change
                seen.add(hour)
            missing.update(h for h in range(HOURS) if h not in seen)
        for role in MEAN_ROLES:
            for row in rows_by_role.get(role) or []:
                hour = _hour_of(row.get("start"), day, tz)
                if hour is None:
                    continue
                mean = row.get("mean")
                try:
                    means[role][hour] = None if mean is None else float(mean)
                except (TypeError, ValueError):
                    means[role][hour] = None
        forecast = next((v for v in means[FORECAST] if v is not None), None)
        return cls(
            date=day.isoformat(), tags=list(tags),
            soc_pct=means[SOC], import_rate=means[IMPORT_RATE],
            export_rate=means[EXPORT_RATE], forecast_kwh=forecast,
            missing_hours=sorted(missing),
            **out,
        )


def _as_date(value: Any) -> _date:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, _date):
        return value
    return _date.fromisoformat(str(value))


def _hour_of(start: Any, day: _date, tz: Optional[tzinfo]) -> Optional[int]:
    """The local hour a statistics row starts in, or None (another day)."""
    if start is None:
        return None
    if isinstance(start, (int, float)):
        if tz is None:
            raise ValueError("an epoch start needs the house's time zone")
        dt = datetime.fromtimestamp(float(start), tz)
    elif isinstance(start, datetime):
        dt = start
    else:
        try:
            dt = datetime.fromisoformat(str(start))
        except ValueError:
            return None
    if tz is not None and dt.tzinfo is not None:
        dt = dt.astimezone(tz)
    if dt.date() != day:
        return None
    return dt.hour
