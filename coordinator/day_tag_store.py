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
from datetime import date as _date, datetime, timedelta, timezone
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..analytics.day_tags import tag_day
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


#: the backfill reads at most this many finished days
BACKFILL_DAYS = 90
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
}
#: a day whose car energy reached this counts as a car day when the
#: session history no longer reaches back that far
BACKFILL_CAR_MIN_KWH = 0.5
_COULD_NOT_ASK = object()


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
                 read_stats: Optional[Callable] = None) -> None:
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
        raw = await self._read_states(self.hass, eid, 3)
        if raw is None:
            return None
        end = day_start + timedelta(days=1)
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
        tags = tag_day(
            date=iso, solar=solar, actual_kwh=actual, forecast_kwh=forecast,
            clear_sky_kwh=clear, snow=False,
            session_kwh=self._sessions(iso), prices=prices,
            cheap_threshold=_float((self.coordinator.config or {}).get(
                "cheap_price_threshold")),
            dark_daylight_min=dark, restarted=self.storage.started_on(iso),
            counter_flat=counter_flat,
        ).as_dict()
        self.storage.put_day_tag(tags)
        try:
            await self.storage.async_save_daily()
        except Exception:  # noqa: BLE001 — the next save carries it
            _LOGGER.debug("day tags for %s saved later", iso)
        return tags

    # ── backfill (#1083): older days from hourly statistics ──────────────

    def cancel(self) -> None:
        """Stop a running backfill now; what it stored stays stored."""
        self._cancelled = True
        task = self._task
        if task is not None and not task.done():
            task.cancel()

    async def async_backfill(self, days: int = BACKFILL_DAYS) -> int:
        """Tag up to ``days`` (max 90) finished days from hourly statistics,
        oldest first, one day per step. A day that already has a tag is
        skipped. Returns the number of days stored.

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
        have = {str(t.get("date")) for t in self.storage.get_day_tags()
                if isinstance(t, dict)}
        _LOGGER.info("day tags: backfill of up to %d days started", days)
        stored = 0
        why = "done"
        for back in range(days, 0, -1):
            if self._cancelled or not day_tags_on(self.coordinator):
                why = "stopped"
                break
            day = today - timedelta(days=back)
            if day.isoformat() in have:
                continue
            rec = await self._backfill_day(day, ids)
            if rec is _COULD_NOT_ASK:
                why = "the recorder could not answer"
                break
            if rec is not None:
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

    async def _backfill_day(self, day: _date, ids: Dict[str, str]):
        """One day's tag record from its hourly statistics; ``None`` when
        the recorder has no statistics for the day, ``_COULD_NOT_ASK``
        when it could not answer."""
        from homeassistant.util import dt as dt_util
        day_start = dt_util.start_of_local_day(day)
        stats = await self._read_stats(
            self.hass, day_start, day_start + timedelta(days=1),
            set(ids.values()), {"change", "mean"})
        if stats is None:
            return _COULD_NOT_ASK
        hourly = {role: _hourly(stats.get(eid), BACKFILL_ROLES[role][1], day_start)
                  for role, eid in ids.items()}
        solar_h = hourly.get("solar") or {}
        if not solar_h:
            return None          # SEM was not recording that day
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
        rec = tag_day(
            date=iso, solar=solar, actual_kwh=actual, forecast_kwh=forecast,
            clear_sky_kwh=clear, snow=False, session_kwh=sessions,
            prices=prices,
            cheap_threshold=_float((self.coordinator.config or {}).get(
                "cheap_price_threshold")),
            dark_daylight_min=dark, restarted=self.storage.started_on(iso),
            counter_flat=solar_kwh < 0.01, hourly=True,
        ).as_dict()
        rec["source"] = "backfill"
        return rec

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


def _hourly(rows, stat: str, day_start: datetime) -> Dict[int, float]:
    """``{hour of day: value}`` from statistics rows. A row's ``start`` is a
    UNIX timestamp on current Home Assistant, a datetime on older ones."""
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
            out[h] = val
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
