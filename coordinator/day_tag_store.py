"""(#1083) Tag each finished day, nightly — asleep until the soak flag or the
Simulation tab switch is on.

At 00:15 local the job reads YESTERDAY from Home Assistant's recorder
through the one reader (``recorder_history.read_states`` — attribute-free,
window clipped to what the recorder keeps, never in setup's await path,
#967), hands it to the pure ``analytics.day_tags.tag_day`` and stores one
small record in SEM's daily store.

It reads SEM's OWN published entities (found by unique id in the entity
registry), not the sources behind them: on an Energy Dashboard install the
sources are resolved at run time, and SEM's entities already are the one
answer to "what did SEM read". Their dark stretches are SEM's dark
stretches.

If the recorder cannot answer, NOTHING is stored — never a guessed tag
(a "could not ask" is not a grey day, #925).
"""
from __future__ import annotations

import asyncio
import logging
import re
from datetime import date as _date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..analytics.day_tags import CAR_MIN_KWH, clear_sky_envelope, tag_day
from ..analytics.simulation.hourly_day import CAR_DOUBT
from ..consts.core import CONF_DAY_TAGS, CONF_SIMULATION_TAB, DEFAULT_DAY_TAGS

_LOGGER = logging.getLogger(__name__)

#: SEM entity keys the tagger reads (unique id ``sem_<key>``)
KEY_SOLAR = "solar_power"
KEY_GRID = "grid_power"
KEY_BATTERY = "battery_power"
KEY_COUNTER = "lifetime_solar_yield_energy"
KEY_PRICE = "tariff_current_import_rate"
DARK = ("unavailable", "unknown", "")
STEP_MIN = 5


#: the backfill reads at most this many finished days (a year: the
#: Simulation tab replays up to 365, #1083)
BACKFILL_DAYS = 365
#: the tag rule a record was made with. 2: the backfill tags days the
#: recorder still holds with the nightly rule, older days by the hourly
#: curve against a clear-sky envelope. A backfilled record without it is
#: re-tagged at the next backfill (rule 1 never said "sunny").
DAY_TAG_RULE = 2
SOURCE_BACKFILL = "backfill"
#: backfill role -> (SEM sensor key, hourly statistic)
BACKFILL_ROLES: Dict[str, Tuple[str, str]] = {
    "solar": ("daily_solar_energy", "change"),
    "grid_import": ("daily_grid_import_energy", "change"),
    "grid_export": ("daily_grid_export_energy", "change"),
    "battery_charge": ("daily_battery_charge_energy", "change"),
    "battery_discharge": ("daily_battery_discharge_energy", "change"),
    "ev": ("daily_ev_energy", "change"),
    "home": ("daily_home_energy", "change"),
    "soc": ("battery_soc", "mean"),
    "import_rate": ("tariff_current_import_rate", "mean"),
    "export_rate": ("tariff_current_export_rate", "mean"),
    # (#1083 accuracy) the day's forecast as SEM held it: the night plan's
    # input (it was never read, so the plan always ran blind)
    "forecast": ("forecast_today_kwh", "mean"),
}
#: a day whose car energy reached this counts as a car day when the
#: session history no longer reaches back that far — the same bar as a
#: session day (``day_tags.CAR_MIN_KWH``)
BACKFILL_CAR_MIN_KWH = CAR_MIN_KWH
_COULD_NOT_ASK = object()
#: (#1176) unique id of a charger's daily-energy sensor
_CAR_DAILY_UID = re.compile(r"^sem_charger_(.+)_daily_energy$")


def car_daily_entities(hass) -> Dict[str, bool]:
    """(#1176) Every charger's daily-energy sensor → is it live. A removed
    charger's sensor is listed (False) while the entity registry still
    remembers it.

    The car's hours are read from these, not from ``daily_ev_energy``. They
    are TOTAL_INCREASING, so the recorder takes a fall as a new cycle and
    their hourly ``change`` holds no reset. ``daily_ev_energy`` said it
    reset at midnight while it fell at the car day's start, so its older
    hours carry a phantom night and a fall that cannot be told apart from
    a real one."""
    try:
        from homeassistant.helpers import entity_registry as er
        from ..const import DOMAIN
        reg = er.async_get(hass)
        entries = ([(e, True) for e in reg.entities.values()]
                   + [(e, False) for e in getattr(
                       reg, "deleted_entities", {}).values()])
    except Exception:  # noqa: BLE001 — no registry, no charger rows
        return {}
    found: Dict[str, bool] = {}
    for entry, live in entries:
        eid = str(getattr(entry, "entity_id", "") or "")
        if (getattr(entry, "platform", None) == DOMAIN
                and eid.startswith("sensor.")
                and _CAR_DAILY_UID.match(str(getattr(entry, "unique_id", "")))):
            found[eid] = found.get(eid, False) or live
    return dict(sorted(found.items()))


def car_daily_entity_ids(hass) -> List[str]:
    """(#1176) The ids of ``car_daily_entities``, live and removed."""
    return list(car_daily_entities(hass))


def car_rows(stats: Dict[str, Any], car_ids: Sequence[str],
             fallback_id: Optional[str]) -> List[Any]:
    """(#1176) The car's hourly rows: every charger's daily-energy rows
    together, or — on a day none of them recorded — ``daily_ev_energy``'s,
    read as before."""
    rows = [row for eid in car_ids for row in (stats.get(eid) or [])]
    if rows:
        return rows
    return list(stats.get(fallback_id) or []) if fallback_id else []


def car_spans(stats: Dict[str, Any], car_ids: Sequence[str]
              ) -> Dict[str, Tuple[datetime, datetime]]:
    """(#1176) Each charger's first and last hour with a row in ``stats``."""
    out: Dict[str, Tuple[datetime, datetime]] = {}
    for eid in car_ids:
        times = [t for t in (_row_time(r) for r in stats.get(eid) or [])
                 if t is not None]
        if times:
            out[eid] = (min(times), max(times))
    return out


def car_day_notes(stats: Dict[str, Any], live: Dict[str, bool],
                  day_start: datetime, day_end: datetime,
                  spans: Optional[Dict[str, Tuple[datetime, datetime]]] = None,
                  ) -> List[str]:
    """(#1176) What makes a day's car sum from its chargers doubtful.

    - A charger with rows in the period (``spans``; without them, on this
      day) but none for some hour of this day inside its span: the sum is
      short.
    - A removed charger's rows on the same hours as a live one's: a renamed
      charger counts twice, a removed one does not — no way to tell.

    Each note starts with ``CAR_DOUBT``; such a day is not exact. Nothing
    when no charger has a row on the day (the fleet row is read instead)."""
    start, end = _utc(day_start), _utc(day_end)
    hours: Dict[str, set] = {}
    for eid in live:
        hours[eid] = {t for t in (_row_time(r) for r in stats.get(eid) or [])
                      if t is not None and start <= t < end}
    if not any(hours.values()):
        return []
    notes: List[str] = []
    for eid in live:
        got = hours[eid]
        span = (spans or {}).get(eid)
        if span is None:
            if not got:
                continue
            span = (min(got), max(got))
        lo = max(start, span[0])
        hi = min(end - timedelta(hours=1), span[1])
        want = set()
        t = lo
        while t <= hi:
            want.add(t)
            t += timedelta(hours=1)
        short = len(want - got)
        if short:
            notes.append(f"{CAR_DOUBT}: a charger's car energy is missing for "
                         f"{short} hours of this day ({eid})")
    live_hours = set().union(*(hours[e] for e, on in live.items() if on))
    for eid, on in live.items():
        both = len(hours[eid] & live_hours) if not on else 0
        if both:
            notes.append(f"{CAR_DOUBT}: a removed charger's car energy "
                         f"overlaps a live one for {both} hours — it may "
                         f"count twice ({eid})")
    return notes


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _row_time(row) -> Optional[datetime]:
    """A statistics row's start in UTC (a UNIX timestamp on current Home
    Assistant, a datetime or ISO text on older ones)."""
    start = (row or {}).get("start")
    if isinstance(start, (int, float)):
        return datetime.fromtimestamp(float(start), tz=timezone.utc)
    if isinstance(start, str):
        try:
            start = datetime.fromisoformat(start)
        except ValueError:
            return None
    if not isinstance(start, datetime):
        return None
    return _utc(start)


def simulation_tab_on(owner) -> bool:
    """Is the Simulation tab switch on? ``owner`` is a config entry, the
    coordinator, or a plain config mapping.

    Same three sources, same order as ``switch._flag``: the runtime flip
    (entry options), the install-time value (entry data), then config."""
    from collections.abc import Mapping
    if owner is None:
        return False
    entry = getattr(owner, "config_entry", None)
    if entry is None and not isinstance(owner, Mapping):
        entry = owner
    for src in (getattr(entry, "options", None), getattr(entry, "data", None)):
        if isinstance(src, Mapping) and CONF_SIMULATION_TAB in src:
            return bool(src[CONF_SIMULATION_TAB])
    cfg = owner if isinstance(owner, Mapping) else getattr(owner, "config", None)
    return bool((cfg or {}).get(CONF_SIMULATION_TAB, False))


def day_tags_on(owner) -> bool:
    """Tag days? The soak flag (#1083, set with set_option) OR the
    Simulation tab switch — the tab needs the tags."""
    return bool((getattr(owner, "config", None) or {}).get(
        CONF_DAY_TAGS, DEFAULT_DAY_TAGS)) or simulation_tab_on(owner)


def _float(v) -> Optional[float]:
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def sample_series(states: Sequence[Tuple[datetime, str]], day_start: datetime,
                  step_min: int = STEP_MIN) -> List[Tuple[float, Optional[float]]]:
    """``(local_hour, value)`` every ``step_min`` minutes across the day, each
    the last state at or before that moment (states are only recorded on a
    change). A dark state stays ``None`` — an absent reading is not 0."""
    out: List[Tuple[float, Optional[float]]] = []
    states = sorted(states, key=lambda s: s[0])
    i, cur = 0, None
    have = False
    for k in range(24 * 60 // step_min):
        t = day_start + timedelta(minutes=k * step_min)
        while i < len(states) and states[i][0] <= t:
            cur = states[i][1]
            have = True
            i += 1
        if not have:
            out.append((k * step_min / 60.0, None))
            continue
        out.append((k * step_min / 60.0,
                    None if str(cur) in DARK else _float(cur)))
    return out


def longest_dark_min(series: Sequence[Tuple[float, Optional[float]]],
                     window: Tuple[float, float],
                     step_min: int = STEP_MIN) -> float:
    """Longest run of dark samples inside ``window`` (local hours)."""
    best = run = 0
    for h, v in series:
        if window[0] <= h < window[1] and v is None:
            run += 1
            best = max(best, run)
        else:
            run = 0
    return float(best * step_min)


def daylight(series: Sequence[Tuple[float, Optional[float]]]) -> Tuple[float, float]:
    """First and last hour with solar above 50 W; a dark day falls back to
    a plain 08:00–17:00 so a dead inverter still has a daylight window."""
    lit = [h for h, v in series if v is not None and v > 50.0]
    return (min(lit), max(lit)) if lit else (8.0, 17.0)


class DayTagger:
    """Reads one finished day and stores its tags."""

    def __init__(self, hass, coordinator, storage=None,
                 read_states: Optional[Callable] = None,
                 read_stats: Optional[Callable] = None,
                 raw_days: Optional[Callable] = None) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._fixed_storage = storage
        if read_states is None:
            from .recorder_history import read_states as _rs
            read_states = _rs
        self._read_states = read_states
        if read_stats is None:
            from .recorder_history import read_hourly_statistics as _rh
            read_stats = _rh
        self._read_stats = read_stats
        if raw_days is None:
            from .recorder_history import raw_history_days as _rd
            raw_days = _rd
        self._raw_days = raw_days
        self._cancelled = False
        self._task: Optional[asyncio.Task] = None

    @property
    def storage(self):
        """The coordinator's storage, read when the job runs — it is
        created on the first refresh, after this tagger."""
        return self._fixed_storage or getattr(self.coordinator, "_storage", None)

    def _entity_id(self, key: str) -> Optional[str]:
        try:
            from homeassistant.helpers import entity_registry as er
            from ..const import DOMAIN
            return er.async_get(self.hass).async_get_entity_id(
                "sensor", DOMAIN, f"sem_{key}")
        except Exception:  # noqa: BLE001 — no registry, no read
            return None

    async def _day_states(self, key: str, day: _date,
                          day_start: datetime) -> Optional[list]:
        eid = self._entity_id(key)
        if not eid:
            return []
        end = day_start + timedelta(days=1)
        from homeassistant.util import dt as dt_util
        back = max(1, (dt_util.now() - day_start).days + 2)
        raw = await self._read_states(self.hass, eid, back,
                                      start=day_start, end=end)
        if raw is None:
            return None
        before, inside = None, []
        for s in raw:
            t = getattr(s, "last_changed", None) or getattr(s, "last_updated", None)
            if t is None:
                continue
            if t.tzinfo is not None:
                t = t.astimezone(day_start.tzinfo)
            if t < day_start:
                if before is None or t >= before[0]:
                    before = (t, str(getattr(s, "state", "")))
            elif t < end:
                inside.append((t, str(getattr(s, "state", ""))))
        # only the day itself, plus the value already in force at midnight:
        # a counter that moved on an EARLIER day must not hide a frozen day
        return ([before] if before else []) + inside

    def _forecast_pair(self, iso: str) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """(actual, forecast, clear-sky) from the forecast tracker's own day
        records — the clear-sky day is the best day of the 30 before."""
        tracker = getattr(self.coordinator, "_forecast_tracker", None)
        history = list(getattr(tracker, "_history", None) or [])
        rec = next((r for r in history if getattr(r, "date", None) == iso), None)
        prior = [float(r.actual_kwh) for r in history
                 if getattr(r, "date", "") < iso][-30:]
        clear = max(prior) if prior else None
        if rec is None:
            return None, None, clear
        return float(rec.actual_kwh), float(rec.forecast_kwh), clear

    def _sessions(self, iso: str) -> List[float]:
        out = []
        for s in (self.storage.get_session_history() or []):
            end = str((s or {}).get("end") or (s or {}).get("timestamp") or "")
            if end[:10] == iso:
                out.append(float(s.get("energy_kwh") or 0.0))
        return out

    async def async_tag_day(self, day: _date) -> Optional[Dict[str, Any]]:
        """Tag ``day`` and store it. ``None`` when the flag is off or the
        recorder could not answer — then nothing is stored."""
        if not day_tags_on(self.coordinator) or self.storage is None:
            return None
        tags = await self._raw_day(day)
        if tags is None:
            return None
        tags.pop("_no_solar", None)
        self.storage.put_day_tag(tags)
        try:
            await self.storage.async_save_daily()
        except Exception:  # noqa: BLE001 — the next save carries it
            _LOGGER.debug("day tags for %s saved later", day.isoformat())
        return tags

    async def _raw_day(self, day: _date,
                       fallback_actual: Optional[float] = None
                       ) -> Optional[Dict[str, Any]]:
        """``day``'s record by the full rule, from the recorder's raw
        states; ``None`` when the recorder could not answer.
        ``fallback_actual``: the day's yield when the forecast tracker has
        no record of it (the backfill passes the hourly statistics' sum)."""
        from homeassistant.util import dt as dt_util
        day_start = dt_util.start_of_local_day(day)
        iso = day.isoformat()
        reads = {}
        for key in (KEY_SOLAR, KEY_GRID, KEY_BATTERY, KEY_COUNTER, KEY_PRICE):
            got = await self._day_states(key, day, day_start)
            if got is None:
                _LOGGER.debug("day tags for %s: recorder could not answer", iso)
                return None
            reads[key] = got
        solar = sample_series(reads[KEY_SOLAR], day_start)
        window = daylight(solar)
        dark = max(longest_dark_min(sample_series(reads[k], day_start), window)
                   for k in (KEY_SOLAR, KEY_GRID, KEY_BATTERY))
        counter = [v for v in (_float(s) for _, s in reads[KEY_COUNTER]) if v is not None]
        counter_flat = bool(counter) and max(counter) - min(counter) < 0.01
        prices = [_float(s) for _, s in reads[KEY_PRICE]]
        actual, forecast, clear = self._forecast_pair(iso)
        if actual is None:
            actual = fallback_actual
        tags = tag_day(
            date=iso, solar=solar, actual_kwh=actual, forecast_kwh=forecast,
            clear_sky_kwh=clear, snow=False,
            session_kwh=self._sessions(iso), prices=prices,
            cheap_threshold=_float((self.coordinator.config or {}).get(
                "cheap_price_threshold")),
            dark_daylight_min=dark,
            counter_flat=counter_flat,
        ).as_dict()
        tags["rule"] = DAY_TAG_RULE
        if not any(v is not None for _, v in solar):
            tags["_no_solar"] = True
        return tags

    # ── backfill (#1083): older days from hourly statistics ──────────────

    def cancel(self) -> None:
        """Stop a running backfill now; what it stored stays stored."""
        self._cancelled = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    def _needs_tag(self, rec: Optional[dict], retag_backfilled: bool) -> bool:
        """No record yet, or a backfilled one that is out of date or could
        not judge the sky. A record the nightly job made is never touched."""
        if rec is None:
            return True
        if rec.get("source") != SOURCE_BACKFILL:
            return False
        return (retag_backfilled or rec.get("rule") != DAY_TAG_RULE
                or rec.get("sky") is None)

    async def async_backfill(self, days: int = BACKFILL_DAYS,
                             retag_backfilled: bool = False) -> int:
        """Tag up to ``days`` (max ``BACKFILL_DAYS``) finished days, oldest first. Returns
        the number of days stored.

        A day with a nightly record is skipped. A backfilled record is
        re-tagged when ``retag_backfilled`` is set or it was made by an
        older rule (``DAY_TAG_RULE``). Days the recorder still holds as raw
        states get the nightly rule; older days the hourly rule against
        the clear-sky envelope of the window's days.

        If the recorder cannot answer, nothing more is stored — never a
        guessed tag (#925)."""
        self._task = asyncio.current_task()
        self._cancelled = False
        if not day_tags_on(self.coordinator) or self.storage is None:
            return 0
        today = getattr(self.coordinator, "_tracker_date", None)
        if today is None:
            return 0
        try:
            days = max(0, min(int(days), BACKFILL_DAYS))
        except (TypeError, ValueError):
            days = BACKFILL_DAYS
        ids = {role: self._entity_id(key)
               for role, (key, _stat) in BACKFILL_ROLES.items()}
        ids = {role: eid for role, eid in ids.items() if eid}
        if "solar" not in ids:
            return 0
        have = {str(t.get("date")): t for t in self.storage.get_day_tags()
                if isinstance(t, dict)}
        window = [today - timedelta(days=back) for back in range(days, 0, -1)]
        todo = [d for d in window
                if self._needs_tag(have.get(d.isoformat()), retag_backfilled)]
        if not todo:
            return 0
        _LOGGER.info("day tags: backfill of %d of %d days started",
                     len(todo), days)
        # pass 1: every day's hourly statistics — the envelope needs the
        # whole window, not only the days to tag
        read: Dict[_date, Any] = {}
        why = "done"
        for day in window:
            if self._cancelled or not day_tags_on(self.coordinator):
                why = "stopped"
                break
            got = await self._read_day_stats(day, ids)
            if got is _COULD_NOT_ASK:
                why = "the recorder could not answer"
                break
            read[day] = got
            await asyncio.sleep(0)
        stored = 0
        if why == "done":
            yields = {d.isoformat(): sum((h.get("solar") or {}).values())
                      for d, h in read.items() if h and h.get("solar")}
            try:
                raw_days = int(self._raw_days(self.hass, days) or 0)
            except Exception:  # noqa: BLE001 — no recorder: no raw days
                raw_days = 0
            for day in todo:
                if self._cancelled or not day_tags_on(self.coordinator):
                    why = "stopped"
                    break
                rec = None
                # the oldest held day is partly purged: only whole days
                if (today - day).days < raw_days:
                    hourly = read.get(day) or {}
                    rec = await self._raw_day(
                        day, sum((hourly.get("solar") or {}).values())
                        if hourly.get("solar") else None)
                    if rec is not None and rec.pop("_no_solar", False):
                        rec = None
                if rec is None and read.get(day):
                    rec = self._hourly_record(
                        day, read[day],
                        clear_sky_envelope(yields, day.isoformat()))
                if rec is not None:
                    rec["source"] = SOURCE_BACKFILL
                    rec["rule"] = DAY_TAG_RULE
                    self.storage.put_day_tag(rec)
                    stored += 1
                await asyncio.sleep(0)
        if stored:
            try:
                await self.storage.async_save_daily()
            except Exception:  # noqa: BLE001 — the next save carries it
                _LOGGER.debug("backfilled day tags saved later")
        _LOGGER.info("day tags: backfill %s — %d days tagged", why, stored)
        return stored

    async def _read_day_stats(self, day: _date, ids: Dict[str, str]):
        """``{role: {hour: value}}`` for ``day`` from hourly statistics;
        ``{}`` when SEM was not recording that day, ``_COULD_NOT_ASK`` when
        the recorder could not answer."""
        from homeassistant.util import dt as dt_util
        day_start = dt_util.start_of_local_day(day)
        car_ids = car_daily_entity_ids(self.hass)
        stats = await self._read_stats(
            self.hass, day_start, day_start + timedelta(days=1),
            set(ids.values()) | set(car_ids), {"change", "mean"})
        if stats is None:
            return _COULD_NOT_ASK
        hourly = {role: _hourly(stats.get(eid), BACKFILL_ROLES[role][1], day_start)
                  for role, eid in ids.items()}
        # (#1176) the car from its chargers' rows, summed per hour
        hourly["ev"] = _hourly(car_rows(stats, car_ids, ids.get("ev")),
                               "change", day_start, add=True)
        return hourly if hourly.get("solar") else {}

    def _hourly_record(self, day: _date, hourly: Dict[str, Dict[int, float]],
                       envelope: Optional[float]) -> Dict[str, Any]:
        """One day's tag record from its hourly statistics."""
        solar_h = hourly.get("solar") or {}
        iso = day.isoformat()
        solar = [(float(h), solar_h[h] * 1000.0 if h in solar_h else None)
                 for h in range(24)]
        window = daylight(solar)
        dark = 0.0
        for role in ("solar", "grid_import", "battery_charge"):
            got = hourly.get(role) or {}
            if not got:
                continue        # no such source on this install
            series = [(float(h), got.get(h)) for h in range(24)]
            dark = max(dark, longest_dark_min(series, window, step_min=60))
        solar_kwh = sum(solar_h.values())
        actual, forecast, clear = self._forecast_pair(iso)
        if actual is None:
            actual = solar_kwh
        sessions = self._sessions(iso)
        ev_kwh = sum((hourly.get("ev") or {}).values())
        if not sessions and ev_kwh >= BACKFILL_CAR_MIN_KWH:
            sessions = [ev_kwh]
        prices = list((hourly.get("import_rate") or {}).values())
        return tag_day(
            date=iso, solar=solar, actual_kwh=actual, forecast_kwh=forecast,
            clear_sky_kwh=clear, snow=False, session_kwh=sessions,
            prices=prices,
            cheap_threshold=_float((self.coordinator.config or {}).get(
                "cheap_price_threshold")),
            dark_daylight_min=dark,
            counter_flat=solar_kwh < 0.01, hourly=True, envelope_kwh=envelope,
        ).as_dict()

    def schedule(self) -> Callable[[], None]:
        """00:15 local, every night: tag yesterday. Returns the unsubscribe."""
        from homeassistant.helpers.event import async_track_time_change

        async def _run(_now) -> None:
            # (#645) one calendar-day authority: the coordinator's own day
            # clock, never a second dt_util.now().date() here
            today = getattr(self.coordinator, "_tracker_date", None)
            if today is None:
                return
            try:
                await self.async_tag_day(today - timedelta(days=1))
            except Exception:  # noqa: BLE001 — a tag is never worth an error
                _LOGGER.debug("day tagging failed", exc_info=True)

        return async_track_time_change(self.hass, _run, hour=0, minute=15, second=0)


def _hourly(rows, stat: str, day_start: datetime,
            add: bool = False) -> Dict[int, float]:
    """``{hour of day: value}`` from statistics rows. A row's ``start`` is a
    UNIX timestamp on current Home Assistant, a datetime on older ones.
    ``add``: rows on one hour add up (#1176: several chargers)."""
    out: Dict[int, float] = {}
    for row in rows or []:
        start = (row or {}).get("start")
        if isinstance(start, (int, float)):
            start = datetime.fromtimestamp(float(start), tz=timezone.utc)
        if not isinstance(start, datetime):
            continue
        if start.tzinfo is None:
            start = start.replace(tzinfo=timezone.utc)
        h = int((start - day_start).total_seconds() // 3600)
        val = _float(row.get(stat))
        if 0 <= h < 24 and val is not None:
            out[h] = out.get(h, 0.0) + val if add else val
    return out


def start_backfill(hass, coordinator, days: int = BACKFILL_DAYS) -> None:
    """Backfill day tags once Home Assistant has started (#967), and keep
    the way to stop it on the coordinator — ``cancel_pending_recorder_work``
    calls ``cancel_backfill`` on unload."""
    from . import recorder_history

    cancel_backfill(coordinator)
    tagger = DayTagger(hass, coordinator)
    unsub = recorder_history.run_after_start(
        hass, lambda: tagger.async_backfill(days),
        name="sem day-tag backfill",
    )

    def _cancel() -> None:
        try:
            unsub()
        except Exception:  # noqa: BLE001 — already fired is fine
            pass
        tagger.cancel()

    coordinator._day_tag_backfill_cancel = _cancel


def cancel_backfill(coordinator) -> None:
    """Stop a pending or running backfill; harmless when there is none."""
    cancel = getattr(coordinator, "_day_tag_backfill_cancel", None)
    try:
        coordinator._day_tag_backfill_cancel = None
    except Exception:  # noqa: BLE001
        pass
    if callable(cancel):
        try:
            cancel()
        except Exception:  # noqa: BLE001 — teardown must finish
            _LOGGER.debug("could not cancel the day-tag backfill")
