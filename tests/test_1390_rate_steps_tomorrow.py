"""(#1390) The price lane said "Fixed · 0.21" on a schedule tariff.

@lostcontrol set a calendar tariff: a Schedule helper for the peak hours,
0.32 peak and 0.21 off-peak (23:00-07:00 and 12:00-17:00 at 0.21). The plan
card's price lane drew one price for any tariff that is not dynamic; #1385
fixed that word. What was left: a schedule tariff sends no price curve, and
``schedule_today`` ends at midnight. Tomorrow had only the plan's night
hours (all 0.21) and was still drawn as one price.

The coordinator now publishes the tariff's own prices for today and
tomorrow (``tariff_rate_steps``, the plan's own price accessor) for any
tariff that is not dynamic. The card reads them where the plan ends.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.day_ledger import (
    rate_runs,
    tariff_price_at,
)
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    StaticTariffProvider,
)

ZRH = ZoneInfo("Europe/Zurich")
HELPER = "schedule.haut_tarif"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")
#: The reporter's peak blocks, every day: 07:00-12:00 and 17:00-23:00.
PEAK = [{"from": time(7, 0), "to": time(12, 0), "data": {}},
        {"from": time(17, 0), "to": time(23, 0), "data": {}}]
WEEK = {d: list(PEAK) for d in DAYS}
#: Thursday 19.11.2026, 08:26 — the reporter's screenshot.
NOW = datetime(2026, 11, 19, 8, 26, tzinfo=ZRH)
DAY0 = NOW.replace(hour=0, minute=0)
CAL = "custom_components.solar_energy_management.tariff.calendar_provider"


def _hass(*, state="on", next_event=None, week=WEEK):
    hass = MagicMock()
    attrs = {"next_event": next_event} if next_event else {}
    states = {HELPER: SimpleNamespace(state=state, last_updated="t0",
                                      attributes=attrs)}
    hass.states.get = lambda eid: states.get(eid)
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock(return_value={HELPER: week})
    return hass


async def _calendar(*, read_week=True, **kw):
    p = CalendarTariffProvider(
        _hass(next_event=NOW.replace(hour=12, minute=0), **kw),
        peak_rate=0.32, off_peak_rate=0.21, rules=[], schedule_entity=HELPER)
    if read_week:
        await p.async_refresh_service_prices()
    return p


def _hm(iso):
    return datetime.fromisoformat(iso).astimezone(ZRH).strftime("%d %H:%M")


def _table(runs):
    return [(_hm(r["start"]), _hm(r["end"]), r["price"]) for r in runs]


def _contiguous(runs):
    for a, b in zip(runs, runs[1:], strict=False):
        assert a["end"] == b["start"], (a, b)


@pytest.mark.unit
class TestTheReportersSchedule:

    @pytest.mark.asyncio
    async def test_today_and_tomorrow_hold_both_rates(self):
        p = await _calendar()
        with patch(f"{CAL}.dt_util.now", return_value=NOW):
            runs = rate_runs(p, DAY0, DAY0 + timedelta(days=2))
        assert _table(runs) == [
            ("19 00:00", "19 07:00", 0.21),
            ("19 07:00", "19 12:00", 0.32),
            ("19 12:00", "19 17:00", 0.21),
            ("19 17:00", "19 23:00", 0.32),
            ("19 23:00", "20 07:00", 0.21),
            ("20 07:00", "20 12:00", 0.32),
            ("20 12:00", "20 17:00", 0.21),
            ("20 17:00", "20 23:00", 0.32),
            ("20 23:00", "21 00:00", 0.21),
        ]
        _contiguous(runs)

    @pytest.mark.asyncio
    async def test_no_quarter_inside_a_run_has_another_price(self):
        """Merging never hides a change: every quarter of a run reads the
        run's price through the plan's own accessor."""
        p = await _calendar()
        with patch(f"{CAL}.dt_util.now", return_value=NOW):
            runs = rate_runs(p, DAY0, DAY0 + timedelta(days=2))
            for r in runs:
                s = datetime.fromisoformat(r["start"])
                e = datetime.fromisoformat(r["end"])
                t = s
                while t < e:
                    assert tariff_price_at(p, t) == r["price"], t
                    t += timedelta(minutes=15)

    @pytest.mark.asyncio
    async def test_a_helper_whose_week_is_not_read_gives_only_its_window(self):
        """Nothing invented: before the week is read, the helper's state
        speaks from now to its next change only."""
        p = await _calendar(read_week=False)
        with patch(f"{CAL}.dt_util.now", return_value=NOW):
            runs = rate_runs(p, DAY0, DAY0 + timedelta(days=2))
        assert _table(runs) == [("19 08:30", "19 12:00", 0.32)]

    @pytest.mark.asyncio
    async def test_a_helper_that_cannot_be_read_gives_nothing(self):
        p = await _calendar(state="unavailable")
        with patch(f"{CAL}.dt_util.now", return_value=NOW):
            assert rate_runs(p, DAY0, DAY0 + timedelta(days=2)) == []


@pytest.mark.unit
class TestATwoRateStaticTariff:

    def test_friday_then_a_saturday_at_one_rate(self):
        p = StaticTariffProvider(peak_rate=0.32, off_peak_rate=0.21)
        fri = datetime(2026, 11, 20, tzinfo=ZRH)
        runs = rate_runs(p, fri, fri + timedelta(days=2))
        assert _table(runs) == [
            ("20 00:00", "20 07:00", 0.21),
            ("20 07:00", "20 20:00", 0.32),
            ("20 20:00", "22 00:00", 0.21),
        ]

    def test_one_price_is_one_run(self):
        p = StaticTariffProvider(peak_rate=0.30, off_peak_rate=0.30)
        mon = datetime(2026, 11, 16, tzinfo=ZRH)
        assert _table(rate_runs(p, mon, mon + timedelta(days=2))) == [
            ("16 00:00", "18 00:00", 0.3)]


@pytest.mark.unit
class TestClockChanges:
    """Stepped in UTC: a 23 h and a 25 h day are neither cut nor padded."""

    def _hours(self, runs):
        return sum((datetime.fromisoformat(r["end"])
                    - datetime.fromisoformat(r["start"])).total_seconds()
                   for r in runs) / 3600

    def test_spring_forward(self):
        p = StaticTariffProvider(peak_rate=0.32, off_peak_rate=0.21)
        sun = datetime(2026, 3, 29, tzinfo=ZRH)     # 23 h
        runs = rate_runs(p, sun, sun + timedelta(days=2))
        assert self._hours(runs) == 23 + 24
        assert runs[0]["start"] == "2026-03-29T00:00:00+01:00"
        assert runs[0]["end"] == "2026-03-30T07:00:00+02:00"
        assert runs[1] == {"start": "2026-03-30T07:00:00+02:00",
                           "end": "2026-03-30T20:00:00+02:00", "price": 0.32}
        _contiguous(runs)

    def test_fall_back(self):
        p = StaticTariffProvider(peak_rate=0.32, off_peak_rate=0.21)
        sun = datetime(2026, 10, 25, tzinfo=ZRH)    # 25 h
        runs = rate_runs(p, sun, sun + timedelta(days=2))
        assert self._hours(runs) == 25 + 24
        assert runs[-1]["end"] == "2026-10-27T00:00:00+01:00"
        _contiguous(runs)


@pytest.mark.unit
class TestNoPriceNoRun:

    def test_a_provider_that_cannot_price(self):
        t0 = datetime(2026, 11, 19, tzinfo=ZRH)
        assert rate_runs(object(), t0, t0 + timedelta(days=2)) == []

        class _Broken:
            def get_price_at(self, _ts):
                raise RuntimeError("down")
        assert rate_runs(_Broken(), t0, t0 + timedelta(days=2)) == []

    def test_a_gap_splits_the_run(self):
        class _Hole:
            def get_price_at(self, ts):
                return None if ts.hour == 3 else 0.21
        t0 = datetime(2026, 11, 19, tzinfo=ZRH)
        assert _table(rate_runs(_Hole(), t0, t0 + timedelta(days=1))) == [
            ("19 00:00", "19 03:00", 0.21), ("19 04:00", "20 00:00", 0.21)]


# ── the real coordinator and the real sensor, as on the install ──

async def _setup(hass, base, **options):
    from pytest_homeassistant_custom_component.common import MockConfigEntry
    entry = MockConfigEntry(domain=base.domain, version=base.version,
                            minor_version=base.minor_version,
                            data=dict(base.data), options=options,
                            title=base.title)
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry.runtime_data


def _rate_steps(hass):
    st = hass.states.get("sensor.sem_tariff_current_import_rate")
    assert st is not None, "no price sensor"
    return st.attributes


@pytest.mark.asyncio
async def test_the_price_sensor_carries_two_days_of_a_two_rate_tariff(
        sem_real_hass, sem_config_entry):
    coord = await _setup(sem_real_hass, sem_config_entry,
                         tariff_mode="static", electricity_import_rate=0.32,
                         electricity_off_peak_rate=0.21)
    a = _rate_steps(sem_real_hass)
    assert a["is_dynamic"] is False
    runs = a["rate_steps"]
    assert runs, "a two-rate tariff sent no prices"
    from homeassistant.util import dt as dt_util
    day0 = dt_util.start_of_local_day()
    assert datetime.fromisoformat(runs[0]["start"]) == day0
    assert datetime.fromisoformat(runs[-1]["end"]) == day0 + timedelta(days=2)
    _contiguous(runs)
    prov = coord._tariff_provider
    for r in runs:
        assert r["price"] == tariff_price_at(
            prov, dt_util.as_local(datetime.fromisoformat(r["start"])))
    # the test runs on today's date: a weekday holds the peak hours, a
    # Saturday and a Sunday hold none
    weekday = any((day0 + timedelta(days=d)).weekday() < 5 for d in (0, 1))
    assert {r["price"] for r in runs} == ({0.32, 0.21} if weekday else {0.21})


@pytest.mark.asyncio
async def test_a_dynamic_tariff_sends_no_rate_steps(sem_real_hass,
                                                    sem_config_entry):
    sem_real_hass.states.async_set(
        "sensor.test_spot_price", "0.20", {"unit_of_measurement": "CHF/kWh"})
    await _setup(sem_real_hass, sem_config_entry, tariff_mode="dynamic",
                 dynamic_tariff_entity="sensor.test_spot_price")
    a = _rate_steps(sem_real_hass)
    assert a["is_dynamic"] is True
    assert a["rate_steps"] is None


@pytest.mark.unit
def test_rate_steps_are_not_recorded():
    """A card helper, re-sent every cycle: kept out of the recorder (#581)."""
    from custom_components.solar_energy_management.sensor import SEMSolarSensor
    assert "rate_steps" in SEMSolarSensor._unrecorded_attributes


# ── a sun slot's price is the feed-in rate; the lane needs the buy price ──

from .test_1310_one_rate_day_is_cheap import _stamp_sunday  # noqa: E402
from .test_638_shadow_mode import freeze_targets  # noqa: E402,F401


@pytest.mark.unit
def test_a_sun_slot_carries_its_buy_price(freeze_targets, monkeypatch):
    """The plan card drew a sun hour at the feed-in rate (0.1 here) as if a
    grid kWh cost that. The published slot now says what it costs."""
    from custom_components.solar_energy_management.sensor import (
        _energy_plan_attrs,
    )
    plan, _ = _stamp_sunday(monkeypatch)
    sun = [s for s in plan["slots"] if s.get("sun")]
    rest = [s for s in plan["slots"] if not s.get("sun")]
    assert sun and rest, "the stamp needs sun hours and grid hours"
    for s in sun:
        assert s["price"] == pytest.approx(0.1)     # what the sun earns
        assert s["buy"] == pytest.approx(0.6)       # Sunday: off-peak
    assert all("buy" not in s for s in rest)
    published = _energy_plan_attrs(plan)["slots"]
    by_start = {s["start"]: s for s in published}
    for s in sun:
        assert by_start[s["start"]]["buy"] == s["buy"]
    for s in rest:
        assert "buy" not in by_start[s["start"]]
