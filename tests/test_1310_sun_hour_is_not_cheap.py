"""(#1310) A sunny peak hour was drawn as a cheap hour.

@matekogon, 2.3.0-beta.4, Calendar tariff: peak 06:00-13:00 and
15:00-22:00, off-peak the rest. The Energy Plan card's "cheap hours" band
showed 11:00-12:00 as cheap, and the battery row charged there.

Cause (class 47, one word for two questions): the day ledger marks a
sun-surplus hour ``level_cheap=True``. That is the PACKER's word — a
cheap-only load may run on free sun. The plan rows published the same flag
as ``cheap``, so the card's band, its slot tip and Assist called a
peak-tariff hour cheap. The battery block at 11:00 is the sun filling the
pack, capped at the surplus — never a grid charge.

Now ``LedgerSlot.tariff_cheap`` keeps the tariff's own word on every slot.
The rows publish it as ``cheap`` and mark the sun with ``sun``; the tomorrow
preview's cheap windows read it too. The packer is unchanged.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.helpers import intent

from custom_components.solar_energy_management.assist_intents import (
    INTENT_GOOD_TO_CHARGE,
    async_register_intents,
)
from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
    tariff_cheap_at,
    tariff_price_at,
    tomorrow_preview,
)
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand,
    build_night_ledger,
    pack_night,
)
from custom_components.solar_energy_management.sensor import _energy_plan_attrs
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)

from .test_1086_assist_intents import _add_entry, _fake_coordinator
from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_load, _fake_self, _power, _scheduler,
    freeze_targets,
)

TZ = timezone.utc


def _t(h, m=0, day=4):
    return datetime(2026, 11, day, h, m, tzinfo=TZ)


def _reporter_calendar():
    """The reporter's tariff, through the real provider: peak 06-13 and
    15-22 every day, off-peak the rest."""
    every_day = [0, 1, 2, 3, 4, 5, 6]
    return CalendarTariffProvider(
        None, peak_rate=1.0, off_peak_rate=0.6, export_rate=0.1,
        rules=[
            {"days": every_day, "start": "06:00", "end": "13:00", "tariff": "ht"},
            {"days": every_day, "start": "15:00", "end": "22:00", "tariff": "ht"},
        ],
    )


def _off_peak(t):
    return t.hour in (13, 14) or t.hour >= 22 or t.hour < 6


def _sunny_day(**kw):
    """A 20 kWh day over a 300 W house: every hour from 09 to 16 is sun."""
    args = dict(
        start=_t(7), end=_t(21), day_kwh=20.0,
        sunrise=_t(6), sunset=_t(18),
        home_w_at=lambda t: 300.0,
        price_at=lambda t: 0.6 if _off_peak(t) else 1.0,
        level_cheap_at=_off_peak,
        export_rate=0.1,
    )
    args.update(kw)
    return build_day_slots(**args)


def _by_hour(slots):
    return {s.start.hour: s for s in slots}


class TestTheCalendarItself:
    """The calendar was never wrong: 11:00 is peak, 13:00 is not."""

    def test_the_reporter_hours(self):
        prov = _reporter_calendar()
        assert tariff_cheap_at(prov, _t(11)) is False
        assert tariff_cheap_at(prov, _t(13)) is True
        assert tariff_cheap_at(prov, _t(23)) is True
        assert tariff_cheap_at(prov, _t(16)) is False


class TestTheSlotKeepsTheTariffWord:

    def test_a_sunny_peak_hour_is_cheap_for_the_packer_only(self):
        s = _by_hour(_sunny_day())[11]
        assert s.cap_override_w is not None, "11:00 must be a sun slot"
        assert s.level_cheap is True       # the packer may use the sun
        assert s.tariff_cheap is False     # the tariff is at its peak

    def test_a_sunny_off_peak_hour_is_cheap_on_both(self):
        s = _by_hour(_sunny_day())[13]
        assert s.cap_override_w is not None, "13:00 must be a sun slot"
        assert s.level_cheap is True
        assert s.tariff_cheap is True

    def test_a_dark_hour_has_one_word(self):
        slots = _sunny_day(day_kwh=0.0)
        for s in slots:
            assert s.cap_override_w is None
            assert s.tariff_cheap is s.level_cheap is _off_peak(s.start)

    def test_a_raising_tariff_is_not_cheap(self):
        def _boom(t):
            raise RuntimeError("no level")
        for s in _sunny_day(level_cheap_at=_boom):
            assert s.tariff_cheap is False

    def test_the_real_calendar_through_the_real_accessors(self):
        prov = _reporter_calendar()
        slots = _sunny_day(price_at=lambda ts: tariff_price_at(prov, ts),
                           level_cheap_at=lambda ts: tariff_cheap_at(prov, ts))
        by = _by_hour(slots)
        assert by[11].cap_override_w is not None
        assert by[11].tariff_cheap is False
        assert by[13].tariff_cheap is True and by[14].tariff_cheap is True
        assert by[16].tariff_cheap is False


class TestThePackerIsUnchanged:
    """A cheap-only load still runs on a sunny peak hour: the sun is free."""

    def test_cheap_only_demand_still_uses_the_sun(self):
        slots = _sunny_day(level_cheap_at=lambda t: False)
        ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                    max_discharge_w=0.0, peak_limit_w=8000.0)
        plan = pack_night(
            [Demand(id="load:pool", kind="load", energy_kwh=1.0,
                    max_power_w=500.0, min_power_w=500.0,
                    deadline=_t(21), needs_cheap_level=True)],
            ledger, floor_kwh=0.0, max_discharge_w=0.0, peak_limit_w=8000.0)
        assert plan.fits is True
        assert plan.allocations


class TestTomorrow:

    def _preview(self, **kw):
        args = dict(
            day_start=_t(7, day=5), day_end=_t(21, day=5), day_kwh=20.0,
            sunrise=_t(6, day=5), sunset=_t(18, day=5),
            home_w_at=lambda t: 300.0,
            price_at=lambda t: 0.6 if _off_peak(t) else 1.0,
            level_cheap_at=_off_peak,
            stamps_at=_t(7, day=5),
        )
        args.update(kw)
        return tomorrow_preview(**args)

    def test_cheap_windows_are_the_tariff_hours_sun_or_not(self):
        p = self._preview()
        assert p["surplus_windows"], "a 20 kWh day has sun"
        cheap = p["cheap_windows"]
        # 13:00-15:00 is off-peak even though the sun shines then — the old
        # filter dropped every sunny hour, so this window was lost.
        assert len(cheap) == 1, cheap
        assert "T13:00" in cheap[0]["start"] and "T15:00" in cheap[0]["end"]

    def test_a_sunny_peak_day_has_no_cheap_window(self):
        p = self._preview(level_cheap_at=lambda t: False)
        assert p["cheap_windows"] == []


# ---------------------------------------------------------------------------
# The stamped plan: what the card and Assist read
# ---------------------------------------------------------------------------

class _CalendarLike:
    """The shadow-mode fake tariff plus the reporter's level."""

    def get_price_at(self, t):
        return 0.6 if _off_peak(t) else 1.0

    def get_price_level_at(self, t):
        return "cheap" if _off_peak(t) else "normal"


def _stamp_at_8(monkeypatch):
    fake = _fake_self(devices=[_fake_load()])
    fake.time_manager = _DayCapableTime()
    fake._forecast_reader = SimpleNamespace(forecast_data=SimpleNamespace(
        forecast_remaining_today_kwh=20.0))
    fake._tariff_provider = _CalendarLike()
    fixed = datetime(2026, 7, 29, 8, 0,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(), energy=MagicMock(), power=_power())
    plan = fake._energy_plan_shadow
    assert isinstance(plan, dict) and plan["slots"], "no plan to judge"
    return plan


class TestThePlanRows:

    def test_the_card_band_shows_tariff_hours_only(self, freeze_targets,
                                                   monkeypatch):
        plan = _stamp_at_8(monkeypatch)
        by = {s["start"][11:13]: s for s in plan["slots"]}
        # The reporter's 11:00: sun, peak tariff — not a cheap hour.
        assert by["11"].get("sun") is True
        assert by["11"]["cheap"] is False
        # Off-peak by day and by night stays cheap, sun or not.
        assert by["13"]["cheap"] is True and by["14"]["cheap"] is True
        assert by["23"]["cheap"] is True
        # A peak hour with no sun: neither.
        assert by["21"]["cheap"] is False and "sun" not in by["21"]
        # Every row's cheap is the tariff's word, hour by hour.
        for s in plan["slots"]:
            start = datetime.fromisoformat(s["start"])
            assert s["cheap"] is _off_peak(start), s["start"]

    def test_the_entity_carries_the_same_word(self, freeze_targets,
                                              monkeypatch):
        plan = _stamp_at_8(monkeypatch)
        attrs = _energy_plan_attrs(plan)
        rows = {s["start"][11:13]: s for s in attrs["slots"]}
        assert rows["11"]["cheap"] is False
        assert rows["13"]["cheap"] is True


# ---------------------------------------------------------------------------
# Assist: "is now a good time to charge?"
# ---------------------------------------------------------------------------

def _row(now, **kw):
    return {"start": (now - timedelta(minutes=5)).isoformat(),
            "end": (now + timedelta(minutes=25)).isoformat(), **kw}


async def _ask(hass, row):
    async_register_intents(hass)
    coordinator = _fake_coordinator(hass)
    coordinator._energy_plan_shadow = {"slots": [row]}
    _add_entry(hass, coordinator)
    response = await intent.async_handle(hass, "test", INTENT_GOOD_TO_CHARGE, {})
    return response.speech["plain"]["speech"]


async def test_a_sun_hour_at_peak_is_a_good_hour(hass):
    from homeassistant.util import dt as dt_util
    said = await _ask(hass, _row(dt_util.now(), cheap=False, sun=True))
    assert said.startswith("Yes") and "sun" in said
    assert "cheap" not in said


async def test_a_peak_hour_without_sun_is_not(hass):
    from homeassistant.util import dt as dt_util
    said = await _ask(hass, _row(dt_util.now(), cheap=False))
    assert said == "No, this is not a cheap hour."


async def test_a_cheap_hour_without_sun_is_cheap(hass):
    from homeassistant.util import dt as dt_util
    said = await _ask(hass, _row(dt_util.now(), cheap=True))
    assert said == "Yes, this is a cheap hour."


@pytest.mark.parametrize("hour", [11, 12])
def test_the_reporter_strip_without_the_fix_would_say_cheap(hour):
    """The packer's word on a sunny peak hour IS True — publishing it was
    the bug, so a revert of the row to ``level_cheap`` fails above."""
    s = _by_hour(_sunny_day())[hour]
    assert s.level_cheap is True and s.tariff_cheap is False
