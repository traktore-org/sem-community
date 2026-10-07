"""#1040 — Calendar tariff mode had no field to set its times.

The Tariff page offered "Calendar", but nothing wrote the schedule the mode
runs on. So it used the off-peak price all day and found no cheap hours
(@mdscgan, Octopus Germany: NT 00:00–05:00, HT 05:00–24:00 — they edited
``tariff/calendar_provider.py`` by hand to get there).

The provider has read a HA Schedule helper since #25; only the field was
missing (bug class 30). And the helper's STATE only answers for now, so once
wired, every other hour — the day strip, the next change, the battery
break-even at 02:00/14:00 — would have got the current tariff (bug class
104: a moment dropped on the way in). The provider now reads the helper's
week through ``schedule.get_schedule``.
"""
from __future__ import annotations

import ast
import inspect
import json
import textwrap
from datetime import datetime, time, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
    timetable_from_schedule,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    PriceLevel,
)

ROOT = Path(__file__).resolve().parent.parent
HELPER = "schedule.octopus_ht"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")

# 2026-09-21 is a Monday.
MON = datetime(2026, 9, 21)
SUN = datetime(2026, 9, 27)


def _week(blocks, days=DAYS):
    return {d: (list(blocks) if d in days else []) for d in DAYS}


#: The reporter's tariff, as HA hands it back in process: ``time`` objects,
#: and the end of the day as ``time.max`` (HA's own spelling of 24:00).
REPORTER_WEEK = _week([{"from": time(5, 0), "to": time.max, "data": {}}])


def _hass(week, *, state="on", stamp="t0", has_service=True):
    hass = MagicMock()
    states = {HELPER: SimpleNamespace(state=state, last_updated=stamp)}
    hass.states.get = lambda eid: states.get(eid)
    hass.services.has_service = MagicMock(return_value=has_service)
    hass.services.async_call = AsyncMock(return_value={HELPER: week})
    hass._states = states
    return hass


def _provider(hass, peak=0.36, off_peak=0.22):
    return CalendarTariffProvider(
        hass, peak_rate=peak, off_peak_rate=off_peak, rules=[],
        schedule_entity=HELPER)


async def _read(provider):
    return await provider.async_refresh_service_prices()


@pytest.mark.unit
class TestTheHelpersWeekAnswersEveryHour:
    @pytest.mark.asyncio
    async def test_the_reporters_tariff_has_cheap_nights(self):
        p = _provider(_hass(REPORTER_WEEK))
        assert await _read(p) is True
        assert p.get_price_level_at(MON.replace(hour=3)) is PriceLevel.CHEAP
        assert p.get_price_level_at(MON.replace(hour=12)) is PriceLevel.NORMAL
        assert p.get_price_level_at(MON.replace(hour=23, minute=59)) is PriceLevel.NORMAL
        assert p.get_price_level_at(MON.replace(hour=5)) is PriceLevel.NORMAL

    @pytest.mark.asyncio
    async def test_the_battery_break_even_sees_both_rates(self):
        """The scheduler samples 02:00 and 14:00. With the helper ON now,
        both used to come back as the peak rate: no spread, no arbitrage."""
        p = _provider(_hass(REPORTER_WEEK, state="on"))
        await _read(p)
        assert p.get_price_at(MON.replace(hour=2)) == pytest.approx(0.22)
        assert p.get_price_at(MON.replace(hour=14)) == pytest.approx(0.36)

    @pytest.mark.asyncio
    async def test_the_day_strip_shows_the_night_window(self):
        p = _provider(_hass(REPORTER_WEEK))
        await _read(p)
        rows = p.get_schedule_for_day(MON.replace(hour=12))
        assert [(r["start"], r["end"], r["level"]) for r in rows] == [
            ("00:00", "05:00", "cheap"), ("05:00", "24:00", "normal")]

    @pytest.mark.asyncio
    async def test_the_next_change_is_found_on_the_minute(self):
        p = _provider(_hass(REPORTER_WEEK))
        await _read(p)
        assert (p._find_next_transition(MON.replace(hour=12, minute=7), "nt")
                == MON + timedelta(days=1))
        assert (p._find_next_transition(MON.replace(hour=3, minute=58, second=33), "ht")
                == MON.replace(hour=5))

    def test_without_the_week_only_now_is_known(self):
        """The state speaks for now. Copied to every hour it gave a strip of
        one confident block and the peak rate at 02:00 (class 86)."""
        p = _provider(_hass(REPORTER_WEEK, state="on"))
        assert p.get_price_level() is PriceLevel.NORMAL
        assert p.get_price_level_at(MON.replace(hour=3)) is None
        assert p.get_price_at(MON.replace(hour=2)) is None
        rows = p.get_schedule_for_day(MON.replace(hour=12))
        assert [(r["tariff"], r["level"]) for r in rows] == [(None, "no_prices")]

    def test_without_the_week_the_state_still_speaks_until_its_next_event(self):
        from homeassistant.util import dt as dt_util
        now = dt_util.now()
        hass = _hass(REPORTER_WEEK, state="off")
        hass._states[HELPER].attributes = {"next_event": now + timedelta(hours=2)}
        p = _provider(hass)
        assert p.get_price_level_at(now + timedelta(hours=1)) is PriceLevel.CHEAP
        assert p.get_price_level_at(now + timedelta(hours=3)) is None

    @pytest.mark.asyncio
    async def test_the_minute_before_an_edge_reads_the_week_past_it(self):
        """The state's word ends at its next_event, however close."""
        from homeassistant.util import dt as dt_util
        from custom_components.solar_energy_management.tariff import (
            calendar_provider as mod,
        )
        now = dt_util.now().replace(hour=4, minute=59, second=30, microsecond=0)
        edge = now.replace(minute=0, second=0) + timedelta(hours=1)
        hass = _hass(REPORTER_WEEK, state="off")
        hass._states[HELPER].attributes = {"next_event": edge}
        p = _provider(hass)
        await _read(p)
        with patch.object(mod.dt_util, "now", return_value=now):
            assert p.get_price_level() is PriceLevel.CHEAP
            assert p.get_price_level_at(edge) is PriceLevel.NORMAL
            assert p._find_next_transition(now, "ht") == edge

    def test_an_unreadable_helper_is_no_answer_not_one_price(self):
        hass = _hass(REPORTER_WEEK, state="unavailable")
        assert _provider(hass).get_tariff_data().level_absence == "no_prices"

    @pytest.mark.asyncio
    async def test_a_week_with_no_block_today_is_one_price(self):
        hass = _hass(_week([]), state="off")
        p = _provider(hass)
        await _read(p)
        td = p.get_tariff_data()
        assert td.price_level is None and td.level_absence == "flat"

    @pytest.mark.asyncio
    async def test_the_state_wins_over_a_stale_week_for_now(self):
        """A week read before an edit must not overrule what the helper
        says right now."""
        from homeassistant.util import dt as dt_util
        hass = _hass(_week([]), state="on")       # stale: no blocks at all
        p = _provider(hass)
        await _read(p)
        assert p.get_price_level() is PriceLevel.NORMAL
        assert p.get_price_at(dt_util.now()) == pytest.approx(0.36)

    @pytest.mark.asyncio
    async def test_a_day_with_no_block_has_one_price(self):
        """Class 104: the helper existing is not a peak hour TODAY."""
        week = _week([{"from": time(7, 0), "to": time(20, 0)}],
                     days=DAYS[:5])
        p = _provider(_hass(week))
        await _read(p)
        assert p.get_price_level_at(MON.replace(hour=12)) is PriceLevel.NORMAL
        assert p.get_price_level_at(MON.replace(hour=22)) is PriceLevel.CHEAP
        assert p.get_price_level_at(SUN.replace(hour=12)) is None
        assert p.get_price_level_at(SUN.replace(hour=3)) is None

    @pytest.mark.asyncio
    async def test_a_helper_that_will_not_read_says_nothing(self):
        hass = _hass(REPORTER_WEEK)
        p = _provider(hass)
        await _read(p)
        hass._states[HELPER] = SimpleNamespace(state="unavailable",
                                               last_updated="t1")
        assert p.get_price_level_at(MON.replace(hour=3)) is None
        assert p.get_price_level_at(MON.replace(hour=12)) is None


@pytest.mark.unit
class TestReadingTheWeek:
    @pytest.mark.parametrize("end", ["24:00:00", "24:00", "23:59:59.999999"])
    def test_json_and_yaml_spellings_are_read_too(self, end):
        week = _week([{"from": "05:00:00", "to": end}])
        assert timetable_from_schedule(week)[0] == (0, time(5, 0), time.max)

    def test_an_answer_that_is_not_a_week_is_none_not_empty(self):
        assert timetable_from_schedule(None) is None
        assert timetable_from_schedule(["monday"]) is None
        assert timetable_from_schedule(_week([])) == []

    def test_a_block_the_helper_would_refuse_is_skipped(self):
        week = _week([{"from": "20:00", "to": "07:00"},
                      {"from": "09:00", "to": "10:00"}], days=("monday",))
        assert timetable_from_schedule(week) == [(0, time(9, 0), time(10, 0))]

    def test_a_block_we_cannot_read_makes_the_week_unknown(self):
        """Dropping it would turn "could not read" into "no peak then"."""
        week = _week([{"from": "x", "to": "08:00"},
                      {"from": "09:00", "to": "10:00"}], days=("monday",))
        assert timetable_from_schedule(week) is None
        assert timetable_from_schedule(_week(["09:00"])) is None

    @pytest.mark.asyncio
    async def test_it_asks_the_helper_by_entity(self):
        hass = _hass(REPORTER_WEEK)
        await _read(_provider(hass))
        args, kwargs = hass.services.async_call.call_args
        assert args[:3] == ("schedule", "get_schedule", {"entity_id": HELPER})
        assert kwargs == {"blocking": True, "return_response": True}

    @pytest.mark.asyncio
    async def test_it_reads_again_only_when_the_helper_changed(self):
        hass = _hass(REPORTER_WEEK)
        p = _provider(hass)
        assert await _read(p) is True
        assert await _read(p) is False
        assert hass.services.async_call.await_count == 1
        hass._states[HELPER] = SimpleNamespace(state="off", last_updated="t1")
        assert await _read(p) is True
        assert hass.services.async_call.await_count == 2

    @pytest.mark.asyncio
    async def test_it_reads_again_after_the_refresh_interval(self):
        from custom_components.solar_energy_management.tariff import (
            calendar_provider as mod,
        )
        hass = _hass(REPORTER_WEEK)
        p = _provider(hass)
        t0 = datetime(2026, 9, 21, 12, 0)
        with patch.object(mod.dt_util, "now", return_value=t0):
            await _read(p)
        later = t0 + CalendarTariffProvider.TIMETABLE_REFRESH
        with patch.object(mod.dt_util, "now", return_value=later):
            assert await _read(p) is True
        assert hass.services.async_call.await_count == 2

    @pytest.mark.asyncio
    async def test_a_failed_read_keeps_the_last_good_week(self):
        hass = _hass(REPORTER_WEEK)
        p = _provider(hass)
        await _read(p)
        hass.services.async_call.side_effect = RuntimeError("gone")
        hass._states[HELPER] = SimpleNamespace(state="off", last_updated="t1")
        assert await _read(p) is False
        assert p.get_price_level_at(MON.replace(hour=3)) is PriceLevel.CHEAP
        # …and backs off instead of calling every cycle.
        hass._states[HELPER] = SimpleNamespace(state="on", last_updated="t2")
        await _read(p)
        assert hass.services.async_call.await_count == 2

    @pytest.mark.asyncio
    async def test_a_reply_that_is_not_a_week_stores_nothing(self):
        hass = _hass(REPORTER_WEEK)
        hass.services.async_call.return_value = {HELPER: "nope"}
        p = _provider(hass)
        assert await _read(p) is False
        assert p._timetable is None

    @pytest.mark.asyncio
    async def test_no_service_no_call(self):
        hass = _hass(REPORTER_WEEK, has_service=False)
        p = _provider(hass)
        assert await _read(p) is False
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_hand_written_on_off_entity_is_not_asked_for_a_week(self):
        hass = _hass(REPORTER_WEEK)
        p = CalendarTariffProvider(hass, rules=[],
                                   schedule_entity="input_boolean.ht")
        assert await _read(p) is False
        hass.services.async_call.assert_not_called()

    @pytest.mark.asyncio
    async def test_a_rule_install_never_calls_the_helper(self):
        hass = _hass(REPORTER_WEEK)
        p = CalendarTariffProvider(hass, rules=[
            {"days": [0], "start": "07:00", "end": "20:00", "tariff": "ht"}])
        assert await _read(p) is False
        hass.services.async_call.assert_not_called()

    def test_the_coordinator_calls_this_hook_by_name(self):
        """The cycle reaches the provider through ``getattr`` on a name; a
        rename on either side would silently stop the week being read."""
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        tree = ast.parse(textwrap.dedent(
            inspect.getsource(SEMCoordinator._async_update_data)))
        names = {n.value for n in ast.walk(tree)
                 if isinstance(n, ast.Constant) and isinstance(n.value, str)}
        assert "async_refresh_service_prices" in names
        assert inspect.iscoroutinefunction(
            CalendarTariffProvider.async_refresh_service_prices)


@pytest.mark.unit
class TestTheCoordinatorReadsTheField:
    def _provider(self, mock_hass, **cfg):
        from custom_components.solar_energy_management.coordinator import SEMCoordinator
        return SEMCoordinator(mock_hass, {"tariff_mode": "calendar",
                                          "update_interval": 30, **cfg})._tariff_provider

    def test_the_field_reaches_the_provider(self, mock_hass):
        p = self._provider(mock_hass, tariff_schedule_entity=HELPER)
        assert isinstance(p, CalendarTariffProvider)
        assert p.schedule_entity == HELPER

    def test_a_hand_written_schedule_still_works(self, mock_hass):
        p = self._provider(mock_hass, tariff_schedule={
            "schedule_entity": "schedule.legacy"})
        assert p.schedule_entity == "schedule.legacy"

    def test_the_field_wins_over_the_hand_written_one(self, mock_hass):
        p = self._provider(mock_hass, tariff_schedule_entity=HELPER,
                           tariff_schedule={"schedule_entity": "schedule.legacy"})
        assert p.schedule_entity == HELPER


def _flow(mock_hass, config_entry, options):
    from custom_components.solar_energy_management.config_flow import (
        OptionsFlowHandler,
    )
    config_entry.options = options
    flow = OptionsFlowHandler(config_entry)
    flow.hass = mock_hass
    return flow


async def _step(flow, config_entry, user_input=None):
    with patch.object(type(flow), "config_entry",
                      new_callable=lambda: property(lambda self: config_entry)):
        return await flow.async_step_settings_tariff(user_input)


def _field(result, key):
    for marker, sel in result["data_schema"].schema.items():
        if marker.schema == key:
            return sel
    return None


class TestTheTariffPageHasTheField:
    @pytest.mark.asyncio
    async def test_the_page_offers_a_schedule_helper(self, mock_hass, config_entry):
        result = await _step(_flow(mock_hass, config_entry, {}), config_entry)
        sel = _field(result, "tariff_schedule_entity")
        assert sel is not None, "Calendar mode needs a field for its times"
        assert sel.config["domain"] == ["schedule"]

    @pytest.mark.asyncio
    async def test_calendar_without_a_schedule_is_refused(self, mock_hass, config_entry):
        result = await _step(_flow(mock_hass, config_entry, {}), config_entry,
                             {"tariff_mode": "calendar"})
        assert result["type"] == "form"
        assert result["step_id"] == "settings_tariff"
        assert result["errors"] == {"tariff_schedule_entity": "calendar_needs_schedule"}
        # The page comes back as the user left it, not as it was saved.
        mode = next(m for m in result["data_schema"].schema
                    if m.schema == "tariff_mode")
        assert mode.default() == "calendar"

    @pytest.mark.asyncio
    async def test_a_field_emptied_before_the_refusal_stays_empty(
            self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry,
                     {"dynamic_feedin_entity": "sensor.feed_in"})
        flow.cur_step = await _step(flow, config_entry)     # what HA records
        result = await _step(flow, config_entry, {"tariff_mode": "calendar"})
        assert result["errors"]
        feed = next(m for m in result["data_schema"].schema
                    if m.schema == "dynamic_feedin_entity")
        assert feed.description["suggested_value"] is None

    @pytest.mark.asyncio
    async def test_calendar_with_a_schedule_is_saved(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {})
        result = await _step(flow, config_entry, {
            "tariff_mode": "calendar", "tariff_schedule_entity": HELPER})
        assert result["step_id"] == "load_management"
        assert flow._data["tariff_schedule_entity"] == HELPER

    @pytest.mark.asyncio
    async def test_other_modes_do_not_need_one(self, mock_hass, config_entry):
        result = await _step(_flow(mock_hass, config_entry, {}), config_entry,
                             {"tariff_mode": "static"})
        assert result["step_id"] == "load_management"

    @pytest.mark.asyncio
    async def test_a_hand_written_schedule_is_not_refused(self, mock_hass, config_entry):
        flow = _flow(mock_hass, config_entry, {"tariff_schedule": {
            "rules": [{"days": [0], "start": "07:00", "end": "20:00",
                       "tariff": "ht"}]}})
        result = await _step(flow, config_entry, {"tariff_mode": "calendar"})
        assert result["step_id"] == "load_management"

    def test_the_key_is_owned_and_reloads(self):
        from custom_components.solar_energy_management import (
            _SET_OPTION_STRUCTURAL_KEYS,
        )
        from custom_components.solar_energy_management.config_flow import (
            OPTIONS_FLOW_OWNED_KEYS,
        )
        assert "tariff_schedule_entity" in OPTIONS_FLOW_OWNED_KEYS
        assert "tariff_schedule_entity" in _SET_OPTION_STRUCTURAL_KEYS

    def test_the_refusal_has_words_in_every_language(self):
        files = [ROOT / "strings.json", *sorted((ROOT / "translations").glob("*.json"))]
        assert len(files) == 17
        for f in files:
            d = json.loads(f.read_text(encoding="utf-8"))
            assert d["options"]["error"].get("calendar_needs_schedule"), f.name
            assert d["options"]["step"]["settings_tariff"]["data"].get(
                "tariff_schedule_entity"), f.name


# ── Second round (06.10.2026): the helper was set, the card said "no price
# difference". The off-peak rate was hidden in the default view, and an
# unsaved rate showed one number on screen while Calendar used another. ──

CARD = ROOT / "dashboard" / "card" / "src" / "cards" / "sem-config-card.js"


def _card_default(key):
    """The number the config card shows for an unsaved option."""
    import re
    src = CARD.read_text(encoding="utf-8")
    m = re.search(r"_renderOptionNumberInput\('" + key + r"',.*?default: ([0-9.]+)",
                  src, re.DOTALL)
    assert m, key
    return float(m.group(1))


@pytest.mark.unit
class TestAnUnsavedRateIsTheShownRate:
    def _coord_provider(self, mock_hass, mode, **cfg):
        from custom_components.solar_energy_management.coordinator import SEMCoordinator
        return SEMCoordinator(mock_hass, {"tariff_mode": mode,
                                          "update_interval": 30, **cfg})._tariff_provider

    def test_calendar_starts_at_the_card_defaults(self, mock_hass):
        p = self._coord_provider(mock_hass, "calendar", tariff_schedule_entity=HELPER)
        assert p.peak_rate == _card_default("electricity_import_rate")
        assert p.off_peak_rate == _card_default("electricity_off_peak_rate")

    def test_calendar_and_static_agree(self, mock_hass):
        cal = self._coord_provider(mock_hass, "calendar", tariff_schedule_entity=HELPER)
        sta = self._coord_provider(mock_hass, "static")
        assert (cal.peak_rate, cal.off_peak_rate) == (sta.peak_rate, sta.off_peak_rate)

    def test_no_rates_saved_is_no_spread(self, mock_hass):
        """Before: 0.35 and 0.22 nobody entered, a spread SEM acted on."""
        mock_hass.states.get = lambda eid: (
            SimpleNamespace(state="on", last_updated="t0", attributes={})
            if eid == HELPER else None)
        p = self._coord_provider(mock_hass, "calendar", tariff_schedule_entity=HELPER)
        assert p.get_price_level() is None
        assert p.get_tariff_data().level_absence == "flat"

    def test_saved_rates_are_used(self, mock_hass):
        p = self._coord_provider(mock_hass, "calendar", tariff_schedule_entity=HELPER,
                                 electricity_import_rate=0.32,
                                 electricity_off_peak_rate=0.22)
        assert (p.peak_rate, p.off_peak_rate) == (0.32, 0.22)

    def test_a_saved_zero_is_kept(self, mock_hass):
        p = self._coord_provider(mock_hass, "calendar", tariff_schedule_entity=HELPER,
                                 electricity_off_peak_rate=0.0)
        assert p.off_peak_rate == 0.0

    @pytest.mark.asyncio
    async def test_the_tariff_page_shows_the_same_defaults(self, mock_hass, config_entry):
        for key in ("electricity_import_rate", "electricity_off_peak_rate",
                    "electricity_nt_rate"):
            config_entry.data.pop(key, None)
        result = await _step(_flow(mock_hass, config_entry, {}), config_entry)
        for key in ("electricity_import_rate", "electricity_off_peak_rate"):
            marker = next(m for m in result["data_schema"].schema if m.schema == key)
            assert marker.default() == _card_default(key), key

    @pytest.mark.asyncio
    async def test_the_tariff_page_keeps_a_saved_zero(self, mock_hass, config_entry):
        """A free night is 0, not "unset". The old `or` showed 0.3387, and
        Submit wrote it back over the user's 0."""
        config_entry.data.pop("electricity_nt_rate", None)
        result = await _step(_flow(mock_hass, config_entry,
                                   {"electricity_off_peak_rate": 0.0}), config_entry)
        marker = next(m for m in result["data_schema"].schema
                      if m.schema == "electricity_off_peak_rate")
        assert marker.default() == 0.0


@pytest.mark.unit
class TestTheDefaultViewSetsUpCalendar:
    """The behaviour is pinned by ``dashboard/card/test/calendar-setup.test.js``
    (the real card); this keeps the two lists the ratchet counts honest."""

    def _src(self):
        return CARD.read_text(encoding="utf-8")

    def test_the_off_peak_rate_is_essential_in_calendar_only(self):
        import re
        src = self._src()
        m = re.search(r"const ESSENTIAL_IN_MODE = \{(.*?)\};", src, re.DOTALL)
        assert m and "electricity_off_peak_rate: 'calendar'" in m.group(1)
        m = re.search(r"const ESSENTIAL_CONTROLS = new Set\(\[(.*?)\]\)", src, re.DOTALL)
        assert "'electricity_off_peak_rate'" in m.group(1)

    def test_the_help_names_the_fields_the_user_sees(self):
        tr = json.loads((ROOT / "dashboard" / "translations.json")
                        .read_text(encoding="utf-8"))
        for lang, t in tr.items():
            help_text = t["config_help_tariff_schedule_entity"]
            for label in (t["config_import_rate"], t["config_off_peak_rate"]):
                assert label.lower() in help_text.lower(), (lang, label)
