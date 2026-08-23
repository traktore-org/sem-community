"""(#778) Recover a forecast ledger from statistics the install already has.

An install that has been running for months already knows how good its forecast
is — ``forecast_tomorrow_kwh`` and ``daily_solar_energy`` have been recorded all
along, and Home Assistant keeps their hourly statistics indefinitely. Making a
user wait seven days to learn something their own database can already prove is
a waste of their time.

This module is the pure half: given two time series, produce the settled
forecast/actual pairs. The recorder query and the ledger write live at the
service seam, so everything decided here is testable without a database.

**The pairing rule is the substance.** The forecast FOR a day is the last one
published BEFORE that day began — the number a decision made that evening would
actually have used. A mid-morning revision is a different, easier statement:
it already knows how the day is going, and scoring against it would flatter the
forecast and produce a trust figure that overstates what can be planned on.
"""

from __future__ import annotations

import datetime
from typing import Dict, Mapping, Optional, Tuple

#: Hour (local) after which a forecast for the NEXT day is considered settled.
#: Providers revise through the day; the evening figure is the one an overnight
#: plan would have been built on.
DEFAULT_SETTLE_AFTER_HOUR: int = 18


def last_reading_before(
    series: Mapping[datetime.datetime, float],
    day: datetime.date,
    settle_after_hour: int,
) -> Optional[float]:
    """The latest value published on ``day`` at or after ``settle_after_hour``.

    Returns None when nothing was published in that window — a gap in the
    history, which must drop the pair rather than reach for an earlier and
    materially different statement.
    """
    best_ts = None
    best_val = None
    for ts, val in series.items():
        if ts.date() != day or ts.hour < settle_after_hour:
            continue
        if best_ts is None or ts > best_ts:
            best_ts, best_val = ts, val
    return best_val


def daily_maxima(
    series: Mapping[datetime.datetime, float],
) -> Dict[datetime.date, float]:
    """Each day's high-water mark.

    Daily counters reset at midnight, so the day's total is the highest value
    it reached — never the last one, which may already have been zeroed.
    """
    out: Dict[datetime.date, float] = {}
    for ts, val in series.items():
        d = ts.date()
        if d not in out or val > out[d]:
            out[d] = val
    return out


def backfill_pairs(
    forecast_series: Mapping[datetime.datetime, float],
    actual_series: Mapping[datetime.datetime, float],
    *,
    horizon: int,
    settle_after_hour: int = DEFAULT_SETTLE_AFTER_HOUR,
) -> Dict[datetime.date, Tuple[float, float]]:
    """``{target_date: (forecast_kwh, actual_kwh)}`` for every settled day.

    ``horizon`` shifts which day the forecast is FOR: 1 means the reading taken
    on day D describes day D+1. Getting that off by one would produce a ledger
    that looks full and measures nothing at all, so it is pinned by test.

    A pair needs a strictly positive forecast — a zero has no ratio. A zero
    ACTUAL is kept: a day that produced nothing is evidence, and the most
    valuable kind, being the forecast's worst possible miss.
    """
    actuals = daily_maxima(actual_series)
    days = {ts.date() for ts in forecast_series}
    out: Dict[datetime.date, Tuple[float, float]] = {}
    for made_on in days:
        fc = last_reading_before(forecast_series, made_on, settle_after_hour)
        if fc is None or fc <= 0:
            continue
        target = made_on + datetime.timedelta(days=int(horizon))
        actual = actuals.get(target)
        if actual is None:
            continue
        out[target] = (float(fc), float(actual))
    return out


#: How far back to look. A year of evidence is plenty and keeps the recorder
#: query bounded; the ledger prunes to its own window afterwards anyway.
DEFAULT_LOOKBACK_DAYS: int = 365


async def read_statistics(hass, statistic_ids, days: int):
    """``{statistic_id: {datetime: value}}`` from long-term hourly statistics.

    The seam. Statistics survive the recorder's own purge and SEM's status
    retention alike (both act on state rows), so this reaches history that the
    ``history`` API would already have dropped.

    Values are taken as ``state`` (a counter's reading at that hour) falling
    back to ``mean`` — the two shapes SEM's own sensors publish. Timestamps
    come back as local datetimes, because every pairing rule in this module is
    expressed in the user's day boundaries, not UTC's.
    """
    from homeassistant.components.recorder import get_instance, statistics
    from homeassistant.util import dt as dt_util

    end = dt_util.now()
    start = end - datetime.timedelta(days=int(days))

    raw = await get_instance(hass).async_add_executor_job(
        statistics.statistics_during_period,
        hass, start, end, set(statistic_ids), "hour", None, {"state", "mean"},
    )

    out = {}
    for stat_id, rows in (raw or {}).items():
        series = {}
        for row in rows:
            value = row.get("state")
            if value is None:
                value = row.get("mean")
            if value is None:
                continue
            ts = row.get("start")
            if ts is None:
                continue
            if isinstance(ts, (int, float)):
                ts = dt_util.utc_from_timestamp(ts)
            series[dt_util.as_local(ts).replace(tzinfo=None)] = float(value)
        out[stat_id] = series
    return out


async def run_backfill(hass, ledger, *, entity_prefix="sensor.sem_",
                       days: int = DEFAULT_LOOKBACK_DAYS) -> dict:
    """Fill ``ledger`` from this install's own recorded history.

    Returns a small report: how many days each horizon gained, and what the
    trust reads afterwards. Horizon 0 (today's forecast, scored against today)
    and horizon 1 (yesterday's forecast for today) are both recoverable; deeper
    horizons are not, because SEM has never published a day-2 figure to record.
    """
    fc_today = f"{entity_prefix}forecast_today_kwh"
    fc_tomorrow = f"{entity_prefix}forecast_tomorrow_kwh"
    actual = f"{entity_prefix}daily_solar_energy"

    series = await read_statistics(hass, [fc_today, fc_tomorrow, actual], days)
    actual_series = series.get(actual) or {}

    report = {"added": {}, "trust": {}, "actual_days": len(daily_maxima(actual_series))}

    # Horizon 1 first: it is the one the budget actually plans on, and doing it
    # first means a day present in both cannot be claimed by horizon 0.
    for horizon, stat_id, hour in (
        (1, fc_tomorrow, DEFAULT_SETTLE_AFTER_HOUR),
        (0, fc_today, 6),
    ):
        pairs = backfill_pairs(series.get(stat_id) or {}, actual_series,
                               horizon=horizon, settle_after_hour=hour)
        report["added"][horizon] = ledger.backfill(pairs, horizon)
        report["trust"][horizon] = ledger.trust(horizon)
    return report
