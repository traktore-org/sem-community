"""#1083 — backfilled days can be sunny again.

The first backfill tagged 90 days of a sunny PROD summer as 87 mixed,
3 grey, 0 sunny: hourly statistics were never allowed to say "sunny".
Now days the recorder still holds get the nightly rule (raw states), and
older days the hourly rule: yield against the best day within 15 days
(the clear-sky envelope), a curve without a dip, and the forecast rule.
"""
import asyncio
import math
from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

from custom_components.solar_energy_management.analytics.day_tags import (
    GREY_MAX_SHARE,
    HOURLY_SUNNY_SHARE,
    clear_sky_envelope,
    hourly_smooth,
    tag_day,
)
from custom_components.solar_energy_management.coordinator.day_tag_store import (
    DAY_TAG_RULE,
    DayTagger,
)
from custom_components.solar_energy_management.coordinator.storage import SEMStorage

TODAY = date(2026, 10, 14)
ENVELOPE = 60.0
SUNNY, MIXED, GREY = "sunny", "mixed", "grey"

# PROD, read-only, anonymised to numbers: hourly solar kWh of one clearly
# sunny August day and one cloudy one; the envelope is the best day within
# 15 days of them in the backfill window.
PROD_SUNNY = [0, 0, 0, 0, 0, 0, 0.05, 1.07, 2.95, 3.34, 3.59, 4.63, 6.52,
              7.19, 6.62, 5.24, 4.8, 4.21, 3.59, 2.74, 0.18, 0, 0, 0]
PROD_CLOUDY = [0, 0, 0, 0, 0, 0, 0.05, 1.05, 1.29, 1.78, 4.67, 3.54, 3.48,
               3.71, 2.54, 1.54, 1.83, 1.17, 0.5, 0.01, 0, 0, 0, 0]
PROD_ENVELOPE = 60.3


def _bell(total_kwh, dip_hour=None, dip_share=1.0):
    """A clear-sky bell 06:00–20:00 summing to ``total_kwh``; one hour can
    be cut to ``dip_share`` of the bell before the rescale."""
    raw = {h: max(0.0, math.sin(math.pi * (h - 5.5) / 15.0)) for h in range(24)}
    raw = {h: (v if 6 <= h <= 20 else 0.0) for h, v in raw.items()}
    if dip_hour is not None:
        raw[dip_hour] *= dip_share
    k = total_kwh / sum(raw.values())
    return {h: v * k for h, v in raw.items()}


def _hourly_day(hours, envelope, forecast=None):
    solar = [(float(h), hours[h] * 1000.0) for h in range(24)]
    return tag_day(date="2026-08-19", solar=solar,
                   actual_kwh=sum(hours.values()), forecast_kwh=forecast,
                   hourly=True, envelope_kwh=envelope)


# ── the hourly rule ───────────────────────────────────────────────────────

def test_smooth_bell_at_95_percent_is_sunny():
    assert _hourly_day(_bell(0.95 * ENVELOPE), ENVELOPE).sky == SUNNY


def test_same_yield_with_one_cloud_hour_is_mixed():
    day = _bell(0.95 * ENVELOPE, dip_hour=12, dip_share=0.4)
    assert abs(sum(day.values()) - 0.95 * ENVELOPE) < 1e-9
    assert not hourly_smooth(day)
    assert _hourly_day(day, ENVELOPE).sky == MIXED


def test_30_percent_of_envelope_is_grey():
    assert _hourly_day(_bell(0.30 * ENVELOPE), ENVELOPE).sky == GREY


def test_under_the_share_is_mixed_and_the_forecast_can_veto():
    assert _hourly_day(_bell(0.80 * ENVELOPE), ENVELOPE).sky == MIXED
    # a full, smooth day the forecast calls grey stays not-sunny
    day = _bell(0.95 * ENVELOPE)
    assert _hourly_day(day, ENVELOPE,
                       forecast=sum(day.values()) / (GREY_MAX_SHARE * 0.9)
                       ).sky == GREY


def test_no_envelope_keeps_the_old_never_sunny_rule():
    assert _hourly_day(_bell(0.95 * ENVELOPE), None, forecast=57.0).sky == MIXED


def test_real_prod_august_pair():
    sunny = dict(enumerate(PROD_SUNNY))
    cloudy = dict(enumerate(PROD_CLOUDY))
    assert sum(PROD_SUNNY) >= HOURLY_SUNNY_SHARE * PROD_ENVELOPE
    assert _hourly_day(sunny, PROD_ENVELOPE, forecast=50.0).sky == SUNNY
    assert _hourly_day(cloudy, PROD_ENVELOPE, forecast=50.0).sky == MIXED


def test_envelope_reaches_15_days_and_counts_the_day_itself():
    yields = {"2026-08-01": 70.0, "2026-08-16": 40.0, "2026-08-17": 50.0,
              "2026-09-02": 90.0}
    assert clear_sky_envelope(yields, "2026-08-16") == 70.0   # 15 days back
    # 01.08 and 02.09 are 16 days away: out
    assert clear_sky_envelope(yields, "2026-08-17") == 50.0
    assert clear_sky_envelope({"2026-08-16": 40.0}, "2026-08-16") == 40.0
    assert clear_sky_envelope({}, "2026-08-16") is None


# ── the backfill ──────────────────────────────────────────────────────────

def _storage():
    st = SEMStorage.__new__(SEMStorage)
    st._daily_data = {}
    st._energy_data = {}

    async def _save():
        pass
    st.async_save_daily = _save
    st.get_session_history = lambda: []
    return st


def _rows(day, values):
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return [{"start": (start + timedelta(hours=h)).timestamp(), "change": v}
            for h, v in values.items()]


def _tagger(kwh_by_day, storage=None, raw_days=0, states=None, history=()):
    coord = SimpleNamespace(
        config={"simulation_tab": True},
        _forecast_tracker=SimpleNamespace(_history=list(history)),
        _tracker_date=TODAY,
    )
    st = storage or _storage()
    raw_reads = []

    async def _stats(_hass, start, _end, entity_ids, types=None):
        kwh = kwh_by_day.get(start.date())
        if kwh is None:
            return {}
        return {"sensor.sem_daily_solar_energy": _rows(start.date(), kwh)}

    async def _states(_hass, eid, _days, start=None, end=None):
        raw_reads.append((eid, start.date()))
        return (states or {}).get(eid.removeprefix("sensor.sem_"), [])

    tg = DayTagger(SimpleNamespace(), coord, storage=st, read_stats=_stats,
                   read_states=_states, raw_days=lambda _h, _w: raw_days)
    tg._entity_id = lambda key: f"sensor.sem_{key}"
    return tg, st, raw_reads


def _by_date(st):
    return {t["date"]: t for t in st.get_day_tags()}


def test_envelope_uses_only_the_window_days():
    d1, d2, d3 = (TODAY - timedelta(days=i) for i in (1, 2, 3))
    # d3 made far more, but it lies outside a 2-day window
    kwh = {d1: _bell(57.0), d2: _bell(60.0), d3: _bell(200.0)}
    tg, st, _ = _tagger(kwh)
    assert asyncio.run(tg.async_backfill(days=2)) == 2
    tags = _by_date(st)
    assert d3.isoformat() not in tags
    assert tags[d1.isoformat()]["sky"] == SUNNY
    assert tags[d2.isoformat()]["sky"] == SUNNY


def _steady_states(day):
    start = datetime(day.year, day.month, day.day, tzinfo=timezone.utc)
    return [SimpleNamespace(last_changed=start + timedelta(minutes=5 * k),
                            state=str(3000.0 if 6 * 12 <= k < 19 * 12 else 0.0))
            for k in range(24 * 12)]


def test_a_day_the_recorder_holds_goes_through_the_raw_rule():
    held, old = TODAY - timedelta(days=1), TODAY - timedelta(days=5)
    hist = [SimpleNamespace(date=held.isoformat(), actual_kwh=39.0,
                            forecast_kwh=40.0),
            SimpleNamespace(date=(held - timedelta(days=2)).isoformat(),
                            actual_kwh=40.0, forecast_kwh=40.0)]
    tg, st, raw_reads = _tagger(
        {held: _bell(39.0), old: _bell(39.0)}, raw_days=3,
        states={"solar_power": _steady_states(held)}, history=hist)
    assert asyncio.run(tg.async_backfill(days=5)) == 2
    tags = _by_date(st)
    raw = tags[held.isoformat()]
    assert raw["variability"] is not None          # 5-minute states read
    assert raw["sky"] == SUNNY and raw["source"] == "backfill"
    assert raw["rule"] == DAY_TAG_RULE
    assert "_no_solar" not in raw
    assert tags[old.isoformat()]["variability"] is None   # hourly rule
    read_days = {d for _e, d in raw_reads}
    assert held in read_days and old not in read_days   # 5 days back: not held


def test_a_held_day_with_no_raw_solar_falls_back_to_hourly():
    held = TODAY - timedelta(days=1)
    tg, st, raw_reads = _tagger({held: _bell(50.0)}, raw_days=3)
    assert asyncio.run(tg.async_backfill(days=1)) == 1
    rec = _by_date(st)[held.isoformat()]
    assert raw_reads and rec["variability"] is None and rec["sky"] == SUNNY


def test_retag_replaces_old_backfill_records_never_nightly_ones():
    d1, d2, d3 = (TODAY - timedelta(days=i) for i in (1, 2, 3))
    st = _storage()
    st.put_day_tag({"date": d1.isoformat(), "sky": "mixed", "source": "backfill"})
    st.put_day_tag({"date": d2.isoformat(), "sky": "mixed"})          # nightly
    st.put_day_tag({"date": d3.isoformat(), "sky": "mixed",
                    "source": "backfill", "rule": DAY_TAG_RULE})
    kwh = {d: _bell(60.0) for d in (d1, d2, d3)}
    tg, st, _ = _tagger(kwh, storage=st)
    # the version-based re-tag: only the rule-1 backfill record
    assert asyncio.run(tg.async_backfill(days=3)) == 1
    tags = _by_date(st)
    assert tags[d1.isoformat()]["sky"] == SUNNY
    assert tags[d1.isoformat()]["rule"] == DAY_TAG_RULE
    assert tags[d2.isoformat()] == {"date": d2.isoformat(), "sky": "mixed"}
    assert tags[d3.isoformat()]["sky"] == "mixed"
    # asked for: every backfilled record, still never the nightly one
    assert asyncio.run(tg.async_backfill(days=3, retag_backfilled=True)) == 2
    tags = _by_date(st)
    assert tags[d3.isoformat()]["sky"] == SUNNY
    assert tags[d2.isoformat()] == {"date": d2.isoformat(), "sky": "mixed"}


def test_nothing_to_tag_reads_nothing():
    d1 = TODAY - timedelta(days=1)
    st = _storage()
    st.put_day_tag({"date": d1.isoformat(), "sky": "mixed",
                    "source": "backfill", "rule": DAY_TAG_RULE})
    calls = []
    tg, st, _ = _tagger({}, storage=st)
    orig = tg._read_stats

    async def _count(*a, **k):
        calls.append(a)
        return await orig(*a, **k)
    tg._read_stats = _count
    assert asyncio.run(tg.async_backfill(days=1)) == 0
    assert calls == []


def test_a_held_day_the_tracker_missed_takes_the_hourly_yield():
    held = TODAY - timedelta(days=1)
    hist = [SimpleNamespace(date=(held - timedelta(days=2)).isoformat(),
                            actual_kwh=40.0, forecast_kwh=40.0)]
    tg, st, _ = _tagger({held: _bell(39.0)}, raw_days=3,
                        states={"solar_power": _steady_states(held)},
                        history=hist)
    assert asyncio.run(tg.async_backfill(days=1)) == 1
    rec = _by_date(st)[held.isoformat()]
    assert rec["variability"] is not None
    assert abs(rec["actual_kwh"] - 39.0) < 0.01 and rec["sky"] == SUNNY


def test_a_backfilled_record_without_a_sky_is_tried_again():
    d1 = TODAY - timedelta(days=1)
    st = _storage()
    st.put_day_tag({"date": d1.isoformat(), "sky": None, "source": "backfill",
                    "rule": DAY_TAG_RULE})
    tg, st, _ = _tagger({d1: _bell(50.0)}, storage=st)
    assert asyncio.run(tg.async_backfill(days=1)) == 1
    assert _by_date(st)[d1.isoformat()]["sky"] == SUNNY
