"""(#1083) Tag each finished day, nightly — asleep until the soak flag is on.

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

import logging
from datetime import date as _date, datetime, timedelta
from typing import Any, Callable, Dict, List, Optional, Sequence, Tuple

from ..analytics.day_tags import tag_day
from ..consts.core import CONF_DAY_TAGS, DEFAULT_DAY_TAGS

_LOGGER = logging.getLogger(__name__)

#: SEM entity keys the tagger reads (unique id ``sem_<key>``)
KEY_SOLAR = "solar_power"
KEY_GRID = "grid_power"
KEY_BATTERY = "battery_power"
KEY_COUNTER = "lifetime_solar_yield_energy"
KEY_PRICE = "tariff_current_import_rate"
DARK = ("unavailable", "unknown", "")
STEP_MIN = 5


def day_tags_on(owner) -> bool:
    """The soak flag (#1083): off unless set with set_option."""
    return bool((getattr(owner, "config", None) or {}).get(
        CONF_DAY_TAGS, DEFAULT_DAY_TAGS))


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
                 read_states: Optional[Callable] = None) -> None:
        self.hass = hass
        self.coordinator = coordinator
        self._fixed_storage = storage
        if read_states is None:
            from .recorder_history import read_states as _rs
            read_states = _rs
        self._read_states = read_states

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
