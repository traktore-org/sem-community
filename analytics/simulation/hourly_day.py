"""(#1083) One recorded day as 24 hours of kWh — the simulation's input.

Pure: no Home Assistant, no clock. The job reads the recorder's hourly
long-term statistics and hands the rows here; the replay tool builds the
same shape from its own recordings.

Flows come from SEM's own daily counters (``last_reset`` at midnight), so
an hour's ``change`` is the gross kWh of that hour. The recorder already
takes the midnight reset out of ``change``: a negative change is the
counter stepping back, not a reset. It is netted against the role's
earlier hours — latest first — then its later ones, so the day adds up to
the counter's own total and no flow goes negative. Earlier first because
that is what a step back undoes: PROD's car counter keeps yesterday's
total past midnight (the recorder books it as new energy at 00:00) and
drops it at 07:00; netting forward put that phantom charge at midnight
and took the real one out of the morning (#1083 accuracy). A row
that exists counts, even at 0 or with no change; only an absent row is a
missing hour. Measurements (SOC, prices, forecast) come from the hourly
``mean``.
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
#: today's solar forecast (SEM's ``forecast_today_kwh``) — the night plan's
FORECAST = "forecast"
MEAN_ROLES = (SOC, IMPORT_RATE, EXPORT_RATE, FORECAST)

ROLES = FLOW_ROLES + MEAN_ROLES

#: Every house has these. A role with no rows at all here means the
#: recorder had nothing — every hour is missing. The other flow roles may
#: be absent on purpose (no battery, no car) and then read as 0.
CORE_ROLES = (SOLAR, GRID_IMPORT, GRID_EXPORT, HOME)

#: a step back bigger than this (kWh) is no rounding fix: the day is
#: still netted, but marked indicative with the hour and size
STEP_BACK_NOTE_KWH = 0.5
#: an hour whose recorded house use and the balance of the other counters
#: (solar + import + discharge − car − export − charge) differ by more than
#: this (kWh) has a counter that jumped (PROD 24.04.2026: 144 kWh of solar
#: and 239 kWh of car in one hour). The day cannot be trusted.
COUNTERS_DISAGREE_KWH = 3.0
#: what the note of such a day starts with — the harness and the job
#: look for it
COUNTERS_DISAGREE = "the counters disagree"
#: the meters close each hour (``close_hours``); a day whose house and
#: solar counters had to move more than this (kWh) in total says so
CLOSE_NOTE_KWH = 5.0


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
    #: what the reading had to fix, said for the day's indicative marks
    notes: List[str] = field(default_factory=list)

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
        self.notes = [str(n) for n in (self.notes or [])]

    @property
    def gap(self) -> bool:
        return "gap" in self.tags

    @property
    def counters_disagree(self) -> bool:
        """An hour where a counter jumped (``COUNTERS_DISAGREE_KWH``)."""
        return any(n.startswith(COUNTERS_DISAGREE) for n in self.notes)

    def close_hours(self) -> float:
        """Make every hour close on the meters; returns the kWh moved.

        The grid meter and the battery counters say what the hour's net
        was (export + charge − import − discharge); SEM's house figure is
        that balance's residual anyway (``home = solar + import + discharge
        − car − export − charge``), and the day totals agree. Hour by hour
        they do not always: PROD's solar counter booked ~0.5 kWh an hour
        at night for weeks (July 2026) while the meters showed the pack
        covering the house, so a model fed the solar counter kept the pack
        full and sold the difference. Here the house takes the residual;
        where that is below 0 (a counter late by an hour) the solar takes
        the rest, so the hour's net is always the meters' own."""
        moved = 0.0
        for h in range(HOURS):
            rest = (self.solar[h] + self.grid_import[h]
                    + self.battery_discharge[h] - self.ev[h]
                    - self.grid_export[h] - self.battery_charge[h])
            if rest >= 0:
                moved += abs(rest - self.home[h])
                self.home[h] = rest
            else:
                moved += self.home[h] - rest
                self.home[h] = 0.0
                self.solar[h] -= rest
        if moved > CLOSE_NOTE_KWH:
            self.notes.append(
                f"the house and solar counters moved {moved:.1f} kWh to "
                "close on the meters")
        return moved

    def _check_balance(self) -> None:
        for h in range(HOURS):
            rest = (self.solar[h] + self.grid_import[h]
                    + self.battery_discharge[h] - self.ev[h]
                    - self.grid_export[h] - self.battery_charge[h])
            off = rest - self.home[h]
            if abs(off) > COUNTERS_DISAGREE_KWH:
                self.notes.append(
                    f"{COUNTERS_DISAGREE} at {h:02d}:00 by {abs(off):.1f} kWh "
                    "— a counter jumped")
                return

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
        notes: List[str] = []
        for role in FLOW_ROLES:
            rows = list(rows_by_role.get(role) or [])
            if not rows:
                if role in CORE_ROLES:
                    missing.update(range(HOURS))
                continue
            raw = _zeros()
            seen = set()
            for row in rows:
                hour = _hour_of(row.get("start"), day, tz)
                if hour is None:
                    continue
                seen.add(hour)      # the row is there: a value, even 0
                change = row.get("change")
                try:
                    raw[hour] += 0.0 if change is None else float(change)
                except (TypeError, ValueError):
                    pass
            missing.update(h for h in range(HOURS) if h not in seen)
            out[role] = _net_step_backs(raw)
            for hour, kwh in enumerate(raw):
                if kwh < -STEP_BACK_NOTE_KWH:
                    notes.append(f"{role} counter stepped back {-kwh:.2f} kWh "
                                 f"at {hour:02d}:00 — netted against the day")
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
        day_obj = cls(
            date=day.isoformat(), tags=list(tags),
            soc_pct=means[SOC], import_rate=means[IMPORT_RATE],
            export_rate=means[EXPORT_RATE], forecast_kwh=forecast,
            missing_hours=sorted(missing), notes=notes,
            **out,
        )
        if not missing:
            day_obj._check_balance()
            day_obj.close_hours()
        return day_obj


def _net_step_backs(raw: List[float]) -> List[float]:
    """Hourly kWh with no negative hour, adding up to ``sum(raw)`` (0 if
    that is below 0). A step back undoes what the counter counted before
    it: it is taken from the earlier hours, latest first; what is left
    from the later hours, earliest first."""
    out = [max(0.0, kwh) for kwh in raw]
    for hour, kwh in enumerate(raw):
        if kwh >= 0:
            continue
        debt = -kwh
        for back in range(hour - 1, -1, -1):
            if debt <= 0:
                break
            take = min(out[back], debt)
            out[back] -= take
            debt -= take
        for fwd in range(hour + 1, HOURS):
            if debt <= 0:
                break
            take = min(out[fwd], debt)
            out[fwd] -= take
            debt -= take
    return out


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
