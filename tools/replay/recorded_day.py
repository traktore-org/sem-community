"""(#1083) One recorded day, anonymised, ready to replay.

A corpus day is one file, ``YYYY-MM-DD.json.gz``, written by the read-only
exporter (``~/bin/sem-export-days``) from SEM's OWN published entities. The
entity ids are already gone: every series is keyed by a ROLE name. That is
the whole anonymisation — the numbers of a house are not a name, and the
day's shape (when the sun came, when the car charged) is what replay needs.

File shape::

    {"date": "2026-10-13", "tz": "Europe/Zurich", "cycle_s": 10,
     "series": {"solar_power": [[epoch_s, 512.0], [epoch_s, null], ...], ...},
     "tags": {...} | null,
     "meta": {"source": "prod", "exported": "..."}}

A ``null`` value is a DARK reading (the entity was unavailable). It stays
dark through the resampling: an absent reading is not 0 W (#925) — that is
exactly what the shown-home hold (#1047, #1105) is about.

One day in memory at a time: :func:`load_day` reads one file;
:meth:`RecordedDay.cycles` is a generator.
"""
from __future__ import annotations

import gzip
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Sequence, Tuple

#: the roles a corpus day may carry → SEM entity key they were read from.
#: One list: the exporter writes these, the replay reads these.
ROLES: Dict[str, str] = {
    "solar_power": "solar_power",
    "grid_power": "grid_power",            # SEM: − import / + export
    "battery_power": "battery_power",      # SEM: − discharge / + charge
    "battery_soc": "battery_soc",
    "ev_power": "ev_power",
    "home_power": "home_consumption_power",  # what SEM SHOWED (comparison only)
    "daily_solar_kwh": "daily_solar_energy",
    "lifetime_solar_kwh": "lifetime_solar_yield_energy",
    "forecast_today_kwh": "forecast_today_kwh",
    "forecast_remaining_kwh": "forecast_remaining_today_kwh",
    "import_price": "tariff_current_import_rate",
}

#: roles that are power inputs of the balance; a dark one sets its flag
POWER_INPUTS = ("solar_power", "grid_power", "battery_power", "ev_power")


@dataclass
class Cycle:
    """One replay cycle: the last recorded value of every role at ``t``
    (``None`` = dark or nothing recorded yet)."""

    t: float                     # epoch seconds
    values: Dict[str, Optional[float]] = field(default_factory=dict)

    def get(self, role: str, default: Optional[float] = None) -> Optional[float]:
        v = self.values.get(role)
        return default if v is None else v

    def dark(self, role: str) -> bool:
        return self.values.get(role) is None


@dataclass
class RecordedDay:
    date: str
    tz: str
    cycle_s: int
    series: Dict[str, List[Tuple[float, Optional[float]]]]
    tags: Optional[Dict[str, Any]] = None
    meta: Dict[str, Any] = field(default_factory=dict)

    def bounds(self) -> Tuple[float, float]:
        """Local midnight to midnight, in epoch seconds."""
        from datetime import datetime, timedelta
        from zoneinfo import ZoneInfo
        d = datetime.fromisoformat(self.date).replace(tzinfo=ZoneInfo(self.tz))
        return d.timestamp(), (d + timedelta(days=1)).timestamp()

    def local_hour(self, t: float) -> float:
        from datetime import datetime
        from zoneinfo import ZoneInfo
        d = datetime.fromtimestamp(t, ZoneInfo(self.tz))
        return d.hour + d.minute / 60.0 + d.second / 3600.0

    def cycles(self, start_s: Optional[float] = None,
               end_s: Optional[float] = None,
               cycle_s: Optional[int] = None) -> Iterator[Cycle]:
        """Every ``cycle_s`` from ``start_s`` to ``end_s`` (default: the
        whole local day): sticky values, dark stays dark."""
        lo, hi = self.bounds()
        start = lo if start_s is None else max(lo, float(start_s))
        end = hi if end_s is None else min(hi, float(end_s))
        step = int(cycle_s or self.cycle_s)
        idx = {r: 0 for r in self.series}
        cur: Dict[str, Optional[float]] = {r: None for r in self.series}
        # values recorded before the window start are carried in
        t = start
        while t < end:
            for role, pts in self.series.items():
                i = idx[role]
                while i < len(pts) and pts[i][0] <= t:
                    cur[role] = pts[i][1]
                    i += 1
                idx[role] = i
            yield Cycle(t=t, values=dict(cur))
            t += step


def day_to_json(day: RecordedDay) -> Dict[str, Any]:
    return {"date": day.date, "tz": day.tz, "cycle_s": day.cycle_s,
            "series": {r: [[round(t, 1), v] for t, v in pts]
                       for r, pts in day.series.items()},
            "tags": day.tags, "meta": day.meta}


def save_day(day: RecordedDay, folder: Path) -> Path:
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{day.date}.json.gz"
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(day_to_json(day), fh, separators=(",", ":"))
    return path


def load_day(path: Path) -> RecordedDay:
    with gzip.open(path, "rt", encoding="utf-8") as fh:
        raw = json.load(fh)
    unknown = set(raw.get("series", {})) - set(ROLES)
    if unknown:
        raise ValueError(f"{path.name}: unknown roles {sorted(unknown)}")
    return RecordedDay(
        date=raw["date"], tz=raw.get("tz") or "UTC",
        cycle_s=int(raw.get("cycle_s") or 10),
        series={r: [(float(t), None if v is None else float(v)) for t, v in pts]
                for r, pts in raw["series"].items()},
        tags=raw.get("tags"), meta=raw.get("meta") or {})


def corpus_days(folder: Path, *, tags: Sequence[str] = (),
                include_gap: bool = False,
                dates: Sequence[str] = ()) -> List[Path]:
    """Day files of a corpus (and its ``pinned/`` subfolder), picked by tag.
    A ``gap`` day is skipped unless asked for — its data cannot be trusted.
    Reads only the small tag block, never a whole day, to choose."""
    paths = sorted(set(folder.glob("*.json.gz")) | set(folder.glob("pinned/*.json.gz")),
                   key=lambda p: p.name)
    out = []
    seen = set()
    for p in paths:
        date = p.name.split(".")[0]
        if date in seen or (dates and date not in dates):
            continue
        day_tags: List[str] = []
        try:
            with gzip.open(p, "rt", encoding="utf-8") as fh:
                day_tags = list(((json.load(fh).get("tags") or {}).get("tags")) or [])
        except (OSError, ValueError):
            continue
        if "gap" in day_tags and not include_gap and "gap" not in tags:
            continue
        if tags and not all(t in day_tags for t in tags):
            continue
        seen.add(date)
        out.append(p)
    return out


def from_history(date: str, tz: str, history: Dict[str, Sequence[Tuple[float, Any]]],
                 *, cycle_s: int = 10, tags: Optional[dict] = None,
                 meta: Optional[dict] = None) -> RecordedDay:
    """Build a day from ``{sem entity key: [(epoch_s, raw state), ...]}``.
    Entity keys become roles; anything not in ``ROLES`` is dropped, so no
    other entity can leak into a corpus file."""
    by_key = {v: k for k, v in ROLES.items()}
    series: Dict[str, List[Tuple[float, Optional[float]]]] = {}
    for key, pts in history.items():
        role = by_key.get(key)
        if role is None:
            continue
        out = []
        for t, raw in sorted(pts, key=lambda p: float(p[0])):
            try:
                v: Optional[float] = float(raw)
            except (TypeError, ValueError):
                v = None
            out.append((float(t), v))
        series[role] = out
    return RecordedDay(date=date, tz=tz, cycle_s=cycle_s, series=series,
                       tags=tags, meta=dict(meta or {}))
