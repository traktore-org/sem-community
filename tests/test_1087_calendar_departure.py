"""#1087 — EV departure from a calendar entity.

``departure_for``/``departure_signature`` stay sync and hass-free; a
calendar's next event is read once per cycle, async, and cached on the
coordinator (``_async_refresh_calendar_departures``) — the same
throttled-service-call shape ``tariff/calendar_provider.py`` already
uses for a Schedule helper.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.departure import (
    departure_for,
    departure_signature,
)
from custom_components.solar_energy_management.coordinator import (
    coordinator as coordinator_mod,
)
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

ZRH = ZoneInfo("Europe/Zurich")
CHARGER = {"ev_target_time": "07:00"}
NOW = datetime(2026, 10, 29, 20, 0, tzinfo=ZRH)


def _frozen():
    return patch.object(coordinator_mod.dt_util, "now", return_value=NOW)


# ── departure_for / departure_signature — pure ─────────────────────────

def test_calendar_next_wins_over_the_weekday_table():
    now = datetime(2026, 10, 29, 20, 0, tzinfo=ZRH)
    calendar_next = datetime(2026, 10, 30, 5, 0, tzinfo=ZRH)
    assert departure_for(CHARGER, now, {}, calendar_next=calendar_next) == calendar_next


def test_a_calendar_departure_already_past_falls_through():
    now = datetime(2026, 10, 29, 20, 0, tzinfo=ZRH)
    stale = now - timedelta(hours=1)
    result = departure_for(CHARGER, now, {}, calendar_next=stale)
    assert result == datetime(2026, 10, 30, 7, 0, tzinfo=ZRH)


def test_no_calendar_is_the_same_as_today():
    now = datetime(2026, 10, 29, 20, 0, tzinfo=ZRH)
    with_none = departure_for(CHARGER, now, {}, calendar_next=None)
    without_arg = departure_for(CHARGER, now, {})
    assert with_none == without_arg


def test_signature_changes_when_the_calendar_event_changes():
    base = departure_signature(CHARGER, {})
    with_event = departure_signature(
        CHARGER, {}, calendar_next=datetime(2026, 10, 30, 5, 0, tzinfo=ZRH))
    assert with_event != base
    # the SAME event, read again, is the same signature
    again = departure_signature(
        CHARGER, {}, calendar_next=datetime(2026, 10, 30, 5, 0, tzinfo=ZRH))
    assert with_event == again


# ── coordinator cache + async refresh ───────────────────────────────────

def _bare_coordinator() -> SEMCoordinator:
    coord = SEMCoordinator.__new__(SEMCoordinator)
    coord._ev_calendar_next = {}
    coord._ev_calendar_summary = {}
    coord._ev_calendar_read_at = {}
    return coord


def test_calendar_departure_for_reads_the_cache():
    coord = _bare_coordinator()
    coord._ev_calendar_next["keba"] = datetime(2026, 10, 30, 5, 0, tzinfo=ZRH)
    assert coord._calendar_departure_for("keba") == datetime(2026, 10, 30, 5, 0, tzinfo=ZRH)


def test_calendar_departure_for_is_none_when_unset():
    assert _bare_coordinator()._calendar_departure_for("keba") is None


def test_calendar_departure_for_on_a_truly_bare_instance_does_not_crash():
    """A bare ``__new__`` instance with no ``_ev_calendar_next`` at all —
    the real failure mode caught by the full suite, not a hypothetical."""
    coord = SEMCoordinator.__new__(SEMCoordinator)
    assert coord._calendar_departure_for("keba") is None


@pytest.mark.asyncio
async def test_refresh_skips_a_charger_with_no_calendar_entity():
    coord = _bare_coordinator()
    coord.hass = MagicMock()
    coord.config = {"ev_chargers": [{"id": "keba"}]}
    with _frozen():
        await coord._async_refresh_calendar_departures()
    assert coord._ev_calendar_next == {}
    coord.hass.services.async_call.assert_not_called()


@pytest.mark.asyncio
async def test_refresh_reads_the_earliest_future_event():
    coord = _bare_coordinator()
    coord.hass = MagicMock()
    coord.hass.services.has_service.return_value = True
    coord.hass.services.async_call = AsyncMock(return_value={
        "calendar.kid_school": {"events": [
            {"start": "2026-10-30T08:00:00+01:00", "summary": "Later pickup"},
            {"start": "2026-10-30T06:30:00+01:00", "summary": "School run"},
            {"start": "2026-10-28T06:00:00+01:00", "summary": "Already past"},
        ]},
    })
    coord.config = {"ev_chargers": [
        {"id": "keba", "departure_calendar_entity": "calendar.kid_school"},
    ]}
    with _frozen():
        await coord._async_refresh_calendar_departures()
    assert coord._ev_calendar_next["keba"] == datetime.fromisoformat(
        "2026-10-30T06:30:00+01:00")
    assert coord._ev_calendar_summary["keba"] == "School run"


@pytest.mark.asyncio
async def test_refresh_skips_an_all_day_event_with_no_time():
    coord = _bare_coordinator()
    coord.hass = MagicMock()
    coord.hass.services.has_service.return_value = True
    coord.hass.services.async_call = AsyncMock(return_value={
        "calendar.x": {"events": [{"start": "2026-10-30", "summary": "All day"}]},
    })
    coord.config = {"ev_chargers": [
        {"id": "keba", "departure_calendar_entity": "calendar.x"},
    ]}
    with _frozen():
        await coord._async_refresh_calendar_departures()
    assert coord._ev_calendar_next.get("keba") is None


@pytest.mark.asyncio
async def test_refresh_a_failed_read_keeps_no_calendar_not_a_crash():
    coord = _bare_coordinator()
    coord.hass = MagicMock()
    coord.hass.services.has_service.return_value = True
    coord.hass.services.async_call = AsyncMock(side_effect=RuntimeError("boom"))
    coord.config = {"ev_chargers": [
        {"id": "keba", "departure_calendar_entity": "calendar.x"},
    ]}
    with _frozen():
        await coord._async_refresh_calendar_departures()
    assert coord._ev_calendar_next.get("keba") is None


@pytest.mark.asyncio
async def test_refresh_clears_a_removed_calendar_entity():
    coord = _bare_coordinator()
    coord._ev_calendar_next["keba"] = datetime(2026, 10, 30, 6, 0, tzinfo=ZRH)
    coord._ev_calendar_summary["keba"] = "School run"
    coord.hass = MagicMock()
    coord.config = {"ev_chargers": [{"id": "keba"}]}  # the entity was cleared
    with _frozen():
        await coord._async_refresh_calendar_departures()
    assert "keba" not in coord._ev_calendar_next
    assert "keba" not in coord._ev_calendar_summary


@pytest.mark.asyncio
async def test_refresh_throttles_a_second_read_within_the_window():
    coord = _bare_coordinator()
    coord.hass = MagicMock()
    coord.hass.services.has_service.return_value = True
    coord.hass.services.async_call = AsyncMock(return_value={"calendar.x": {"events": []}})
    coord.config = {"ev_chargers": [
        {"id": "keba", "departure_calendar_entity": "calendar.x"},
    ]}
    with _frozen():
        await coord._async_refresh_calendar_departures()
        assert coord.hass.services.async_call.call_count == 1
        await coord._async_refresh_calendar_departures()
        assert coord.hass.services.async_call.call_count == 1  # still throttled
