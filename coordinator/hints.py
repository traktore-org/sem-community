"""(#1019) Hints — short sentences when something is off, and a weekly note.

Five categories behind one select, ``hints`` (off / weekly / all), off
until a person picks otherwise. The engine is pure: it gets facts, returns hints, keeps a
small state the coordinator persists. Every hint carries an event key
and fires once per key — a restart with the stored state repeats
nothing.

Time is SEM's own day/night clock. ``facts.night`` is what
``time_manager.is_night_mode()`` says, and the engine acts on its EDGES:
night start (grid use, the weekly note on a Sunday) and morning (the
night's load). No wall-clock hour is read here, so the compressed-sun
simulation drives it exactly like a real day.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Mapping, Optional, Tuple

HINT_CATEGORIES = (
    "silent_input",
    "night_load",
    "grid_rise",
    "cheap_now",
    "weekly_summary",
)

#: (#1019) the one select, ``hints``: off / weekly (the Sunday note only)
#: / all (all five categories). Default off.
HINT_MODES = ("off", "weekly", "all")
DEFAULT_HINT_MODE = "off"


def enabled_categories(mode) -> dict:
    """Which categories the ``hints`` option turns on. Anything unknown
    reads as off."""
    if mode == "all":
        return {c: True for c in HINT_CATEGORIES}
    if mode == "weekly":
        return {c: c == "weekly_summary" for c in HINT_CATEGORIES}
    return {c: False for c in HINT_CATEGORIES}

#: an input dark this long is "silent" (the Repair threshold, 15 min)
SILENT_INPUT_S = 900
#: the night's mean home power against the median of past nights
NIGHT_LOAD_FACTOR = 1.5
NIGHT_LOAD_MIN_W = 300
#: today's grid import against the median of past days …
GRID_RISE_FACTOR = 1.5
GRID_RISE_MIN_KWH = 1.0
#: … while today's solar is this close to its median
GRID_RISE_SOLAR_BAND = 0.25
#: past nights / days needed before a comparison is made
MIN_HISTORY = 3
#: what the engine keeps
KEEP_NIGHTS = 14
KEEP_DAYS = 14


@dataclass
class HintFacts:
    """What one evaluation sees. The coordinator builds it every cycle."""
    now: datetime
    night: bool
    enabled: Mapping[str, bool]
    home_w: float = 0.0
    daily_solar_kwh: float = 0.0
    daily_import_kwh: float = 0.0
    daily_home_kwh: float = 0.0
    daily_ev_kwh: float = 0.0
    daily_cost: float = 0.0
    #: (#1088) CO2 avoided today, kg (None = not known)
    daily_co2_kg: Optional[float] = None
    self_use_pct: float = 0.0
    currency: str = ""
    #: entity_id -> (display name, seconds dark)
    dark_inputs: Mapping[str, Tuple[str, float]] = field(default_factory=dict)
    price_cheap: bool = False
    dynamic_tariff: bool = False
    #: names of chargers with a car plugged in and not charging
    idle_plugged_cars: Tuple[str, ...] = ()


@dataclass(frozen=True)
class Hint:
    category: str
    key: str
    text_key: str
    params: Dict[str, Any]


def _median(values: List[float]) -> Optional[float]:
    return statistics.median(values) if values else None


class HintEngine:
    def __init__(self, state: Optional[Mapping[str, Any]] = None) -> None:
        self.sent: Dict[str, str] = {}
        self.silent_open: Dict[str, Tuple[str, str]] = {}   # entity -> (key, name)
        self.night_means: List[float] = []
        self.night_sum_w = 0.0
        self.night_count = 0
        self.daily_totals: List[Dict[str, Any]] = []
        self.today: Optional[Dict[str, Any]] = None
        self.last_night: Optional[bool] = None
        self.cheap_since: Optional[str] = None
        if state:
            self._restore(state)

    # ── persistence ─────────────────────────────────────────────────
    def _restore(self, state: Mapping[str, Any]) -> None:
        try:
            sent = state.get("sent") or {}
            silent = state.get("silent_open") or {}
            means = state.get("night_means") or []
            totals = state.get("daily_totals") or []
            if not all(isinstance(x, (dict, list)) for x in (sent, silent, means, totals)):
                raise TypeError
            self.sent = {str(k): str(v) for k, v in dict(sent).items()}
            self.silent_open = {str(k): (str(v[0]), str(v[1]))
                                for k, v in dict(silent).items()}
            self.night_means = [float(x) for x in list(means)][-KEEP_NIGHTS:]
            self.daily_totals = [dict(x) for x in list(totals) if isinstance(x, dict)][-KEEP_DAYS:]
            self.night_sum_w = float(state.get("night_sum_w") or 0.0)
            self.night_count = int(state.get("night_count") or 0)
            today = state.get("today")
            self.today = dict(today) if isinstance(today, dict) else None
            ln = state.get("last_night")
            self.last_night = ln if isinstance(ln, bool) else None
            cs = state.get("cheap_since")
            self.cheap_since = str(cs) if cs else None
        except (TypeError, ValueError, AttributeError, IndexError):
            self.__init__()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "sent": dict(self.sent),
            "silent_open": {k: list(v) for k, v in self.silent_open.items()},
            "night_means": list(self.night_means),
            "night_sum_w": self.night_sum_w,
            "night_count": self.night_count,
            "daily_totals": [dict(x) for x in self.daily_totals],
            "today": dict(self.today) if self.today else None,
            "last_night": self.last_night,
            "cheap_since": self.cheap_since,
        }

    # ── the evaluation ──────────────────────────────────────────────
    def evaluate(self, facts: HintFacts) -> List[Hint]:
        out: List[Hint] = []
        self._roll_day(facts)

        was_night = self.last_night
        self.last_night = bool(facts.night)
        if facts.night:
            self.night_sum_w += float(facts.home_w or 0.0)
            self.night_count += 1

        if was_night is False and facts.night:
            # night start
            self._grid_rise(facts, out)
            self._weekly(facts, out)
            self.night_sum_w = 0.0
            self.night_count = 0
        elif was_night is True and not facts.night:
            # morning
            self._night_load(facts, out)
            self.night_sum_w = 0.0
            self.night_count = 0

        self._silent_input(facts, out)
        self._cheap_now(facts, out)
        return out

    def _fire(self, out: List[Hint], category: str, key: str, text_key: str,
              params: Dict[str, Any], slot: str = "") -> None:
        name = f"{category}:{slot}"
        if self.sent.get(name) == key:
            return
        self.sent[name] = key
        out.append(Hint(category, key, text_key, params))

    # ── the day ledger (rolls on the DATE, so the weekly note can add days)
    def _roll_day(self, facts: HintFacts) -> None:
        today = facts.now.date().isoformat()
        if self.today and self.today.get("date") != today:
            self.daily_totals.append(self.today)
            self.daily_totals = self.daily_totals[-KEEP_DAYS:]
            self.today = None
        self.today = {
            "date": today,
            "solar": float(facts.daily_solar_kwh or 0.0),
            "import": float(facts.daily_import_kwh or 0.0),
            "home": float(facts.daily_home_kwh or 0.0),
            "ev": float(facts.daily_ev_kwh or 0.0),
            "cost": float(facts.daily_cost or 0.0),
            "self_use": float(facts.self_use_pct or 0.0),
            # (#1088) None on days stored before, or when SEM had no number
            "co2": None if facts.daily_co2_kg is None else float(facts.daily_co2_kg),
        }

    # ── categories ──────────────────────────────────────────────────
    def _night_load(self, facts: HintFacts, out: List[Hint]) -> None:
        mean = self.night_sum_w / self.night_count if self.night_count else None
        if mean is None:
            return
        usual = _median(self.night_means) if len(self.night_means) >= MIN_HISTORY else None
        self.night_means = (self.night_means + [mean])[-KEEP_NIGHTS:]
        if not facts.enabled.get("night_load") or usual is None:
            return
        if mean >= NIGHT_LOAD_MIN_W and mean > NIGHT_LOAD_FACTOR * usual:
            self._fire(out, "night_load", facts.now.date().isoformat(),
                       "hint_msg_night_load",
                       {"watts": int(round(mean)), "usual": int(round(usual))})

    def _grid_rise(self, facts: HintFacts, out: List[Hint]) -> None:
        if not facts.enabled.get("grid_rise") or self.today is None:
            return
        past = self.daily_totals[-7:]
        if len(past) < MIN_HISTORY:
            return
        usual_import = _median([d["import"] for d in past])
        usual_solar = _median([d["solar"] for d in past])
        today_import = self.today["import"]
        today_solar = self.today["solar"]
        if usual_import is None or usual_solar is None:
            return
        same_sun = (usual_solar <= 0 and today_solar <= 0) or (
            usual_solar > 0
            and abs(today_solar - usual_solar) <= GRID_RISE_SOLAR_BAND * usual_solar)
        if (same_sun and today_import >= GRID_RISE_MIN_KWH
                and today_import > GRID_RISE_FACTOR * usual_import):
            self._fire(out, "grid_rise", self.today["date"], "hint_msg_grid_rise",
                       {"kwh": round(today_import, 1), "usual": round(usual_import, 1)})

    def _weekly(self, facts: HintFacts, out: List[Hint]) -> None:
        if not facts.enabled.get("weekly_summary") or facts.now.weekday() != 6:
            return
        if self.today is None:
            return
        iso = facts.now.isocalendar()
        key = f"{iso[0]}-W{iso[1]:02d}"
        days = self.daily_totals[-6:] + [self.today]
        solar = sum(d["solar"] for d in days)
        weighted = sum(d["solar"] * d["self_use"] for d in days)
        self_use = weighted / solar if solar > 0 else 0.0
        self._fire(out, "weekly_summary", key, "hint_msg_weekly_summary", {
            "solar": int(round(solar)),
            "self_use": int(round(self_use)),
            "grid": int(round(sum(d["import"] for d in days))),
            "ev": int(round(sum(d["ev"] for d in days))),
            "cost": round(sum(d["cost"] for d in days), 2),
            "currency": facts.currency or "",
        })
        # (#1088) one CO2 line, only when every day of the week has a number
        # (a week half-counted would undersell what the solar avoided)
        co2_days = [d.get("co2") for d in days]
        if days and all(c is not None for c in co2_days):
            self._fire(out, "weekly_summary", key, "hint_msg_weekly_co2",
                       {"co2": round(sum(co2_days), 1)}, slot="co2")

    def _silent_input(self, facts: HintFacts, out: List[Hint]) -> None:
        enabled = bool(facts.enabled.get("silent_input"))
        now_s = facts.now.timestamp()
        dark = dict(facts.dark_inputs or {})
        for entity_id, (name, dark_s) in dark.items():
            if float(dark_s) < SILENT_INPUT_S:
                continue
            start_min = int((now_s - float(dark_s)) // 60)
            key = f"{entity_id}@{start_min}"
            if entity_id in self.silent_open:
                continue
            self.silent_open[entity_id] = (key, str(name))
            if enabled:
                self._fire(out, "silent_input", key, "hint_msg_silent_input",
                           {"name": str(name), "minutes": int(float(dark_s) // 60)},
                           slot=entity_id)
        for entity_id in list(self.silent_open):
            if entity_id in dark:
                continue
            key, name = self.silent_open.pop(entity_id)
            if enabled and self.sent.get(f"silent_input:{entity_id}") == key:
                self._fire(out, "silent_input", key + ":back",
                           "hint_msg_silent_input_back", {"name": name},
                           slot=entity_id)

    def _cheap_now(self, facts: HintFacts, out: List[Hint]) -> None:
        if not (facts.dynamic_tariff and facts.price_cheap):
            self.cheap_since = None
            return
        if self.cheap_since is None:
            self.cheap_since = facts.now.isoformat()
        if not facts.enabled.get("cheap_now") or not facts.idle_plugged_cars:
            return
        self._fire(out, "cheap_now", self.cheap_since, "hint_msg_cheap_now",
                   {"cars": ", ".join(facts.idle_plugged_cars)})
