"""(#1385) "Solar + cheapest hours" greyed out on a schedule tariff.

@lostcontrol set a calendar tariff (a Schedule helper for the peak hours,
0.32 peak and 0.21 off-peak). The plan already packed the hot water into the
0.21 hours, but the EV card would not let the car use them: the charge-mode
select said ``tariff_available`` only when ``tariff_mode == "dynamic"``.

The mode reads cheap hours from the tariff's own levels, which a calendar or
a two-rate static tariff gives like a dynamic one. The gate now asks the
tariff whether it has a cheap rate at all (``PriceView.has_cheap_rate``).
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from homeassistant.components.select import SelectEntityDescription

from custom_components.solar_energy_management.consts.ev_charge_modes import (
    EV_CHARGE_MODES,
    MODE_USES_TARIFF,
)
from custom_components.solar_energy_management.coordinator.price_view import (
    PriceView,
)
from custom_components.solar_energy_management.select import SEMPerChargerSelect
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    StaticTariffProvider,
)

HELPER = "schedule.haut_tarif"
DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
        "saturday", "sunday")
# 2026-11-16 is a Monday.
MON = datetime(2026, 11, 16)


def _week(blocks, days=DAYS):
    return {d: (list(blocks) if d in days else []) for d in DAYS}


#: Peak 07:00–21:00 on weekdays, the rest at the off-peak rate.
WEEKDAY_PEAK = _week([{"from": time(7, 0), "to": time(21, 0), "data": {}}],
                     days=DAYS[:5])


def _hass(week, *, state="off"):
    hass = MagicMock()
    states = {HELPER: SimpleNamespace(state=state, last_updated="t0",
                                      attributes={})}
    hass.states.get = lambda eid: states.get(eid)
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock(return_value={HELPER: week})
    hass._states = states
    return hass


async def _calendar(week=WEEKDAY_PEAK, *, peak=0.32, off_peak=0.21,
                    state="off"):
    p = CalendarTariffProvider(_hass(week, state=state), peak_rate=peak,
                               off_peak_rate=off_peak, rules=[],
                               schedule_entity=HELPER)
    await p.async_refresh_service_prices()
    return p


def _select(provider, *, tariff_mode, stored="min_plus_solar"):
    sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
    sel.coordinator = SimpleNamespace(
        config={"tariff_mode": tariff_mode,
                "ev_chargers": [{"id": "box_1", "charge_mode": stored}]},
        _tariff_provider=provider,
        last_update_success=True,
    )
    sel.entity_description = SelectEntityDescription(
        key="charger_box_1_charge_mode", options=list(EV_CHARGE_MODES))
    sel._charger_id = "box_1"
    sel._config_key = "charge_mode"
    sel._value = stored
    return sel


def _available(provider, tariff_mode):
    return _select(provider, tariff_mode=tariff_mode).extra_state_attributes[
        "tariff_available"]


@pytest.mark.unit
class TestTheReportersTariff:
    @pytest.mark.asyncio
    async def test_a_schedule_with_two_rates_offers_the_mode(self):
        p = await _calendar()
        assert _available(p, "calendar") is True

    @pytest.mark.asyncio
    async def test_the_mode_finds_the_cheap_hours_it_was_offered_for(self):
        """Not an empty option: the hours the mode plans with are cheap at
        night and on Saturday, and not at Monday noon."""
        p = await _calendar()
        view = PriceView(p)
        assert view.cheap_at(MON.replace(hour=3)) is True
        assert view.cheap_at(MON.replace(hour=22)) is True
        assert view.cheap_at(MON.replace(hour=12)) is False
        assert "solar_plus_cheap" in MODE_USES_TARIFF

    @pytest.mark.asyncio
    async def test_before_the_week_is_read_the_state_is_enough(self):
        p = CalendarTariffProvider(_hass(WEEKDAY_PEAK, state="on"),
                                   peak_rate=0.32, off_peak_rate=0.21,
                                   rules=[], schedule_entity=HELPER)
        assert _available(p, "calendar") is True


@pytest.mark.unit
class TestNoCheapRateNoMode:
    @pytest.mark.asyncio
    async def test_a_schedule_with_one_rate(self):
        p = await _calendar(peak=0.30, off_peak=0.30)
        assert _available(p, "calendar") is False

    @pytest.mark.asyncio
    async def test_a_schedule_with_no_peak_block(self):
        p = await _calendar(week=_week([]))
        assert _available(p, "calendar") is False

    @pytest.mark.asyncio
    async def test_a_schedule_helper_that_cannot_be_read(self):
        p = await _calendar(state="unavailable")
        assert _available(p, "calendar") is False

    def test_a_calendar_with_no_schedule_at_all(self):
        p = CalendarTariffProvider(MagicMock(), peak_rate=0.32,
                                   off_peak_rate=0.21, rules=[])
        assert _available(p, "calendar") is False

    def test_a_flat_static_tariff(self):
        p = StaticTariffProvider(peak_rate=0.30, off_peak_rate=0.30)
        assert _available(p, "static") is False

    def test_a_static_tariff_with_an_empty_peak_window(self):
        p = StaticTariffProvider(peak_rate=0.32, off_peak_rate=0.21,
                                 peak_start=7, peak_end=7)
        assert _available(p, "static") is False

    def test_no_provider_or_one_that_does_not_answer(self):
        assert _available(None, "dynamic") is False
        assert _available(MagicMock(), "dynamic") is False

        class _Broken:
            def has_cheap_rate(self):
                raise RuntimeError("down")
        assert _available(_Broken(), "dynamic") is False


@pytest.mark.unit
class TestTheOtherTariffs:
    def test_a_static_tariff_with_two_rates_offers_the_mode(self):
        """Weekday nights and weekends are at the off-peak rate."""
        p = StaticTariffProvider(peak_rate=0.32, off_peak_rate=0.21)
        assert _available(p, "static") is True
        assert PriceView(p).cheap_at(MON.replace(hour=3)) is True

    def test_a_dynamic_tariff_still_offers_the_mode(self):
        p = DynamicTariffProvider.__new__(DynamicTariffProvider)
        assert _available(p, "dynamic") is True

    @pytest.mark.asyncio
    async def test_the_mode_name_alone_decides_nothing(self):
        """The provider answers, not the config word next to it."""
        p = await _calendar()
        assert _available(p, "static") is True
        flat = StaticTariffProvider(peak_rate=0.30, off_peak_rate=0.30)
        assert _available(flat, "dynamic") is False


@pytest.mark.unit
class TestTheRealCoordinatorBuildsTheProvider:
    """Through ``SEMCoordinator``'s own provider build, as on the install."""

    def _coordinator(self, mock_hass, **cfg):
        from custom_components.solar_energy_management.coordinator import (
            SEMCoordinator,
        )
        return SEMCoordinator(mock_hass, {"update_interval": 30, **cfg})

    def _attrs(self, coord):
        sel = SEMPerChargerSelect.__new__(SEMPerChargerSelect)
        sel.coordinator = coord
        coord.config.setdefault("ev_chargers",
                                [{"id": "box_1", "charge_mode": "solar_only"}])
        sel.entity_description = SelectEntityDescription(
            key="charger_box_1_charge_mode", options=list(EV_CHARGE_MODES))
        sel._charger_id = "box_1"
        sel._config_key = "charge_mode"
        sel._value = "solar_only"
        return sel.extra_state_attributes

    def test_the_reporters_config(self, mock_hass):
        mock_hass.states.get = lambda eid: (
            SimpleNamespace(state="on", last_updated="t0", attributes={})
            if eid == HELPER else None)
        coord = self._coordinator(
            mock_hass, tariff_mode="calendar", tariff_schedule_entity=HELPER,
            electricity_import_rate=0.32, electricity_off_peak_rate=0.21)
        assert isinstance(coord._tariff_provider, CalendarTariffProvider)
        assert self._attrs(coord)["tariff_available"] is True

    def test_a_static_tariff_left_at_one_price(self, mock_hass):
        coord = self._coordinator(mock_hass, tariff_mode="static",
                                  electricity_import_rate=0.30)
        assert self._attrs(coord)["tariff_available"] is False


@pytest.mark.unit
class TestAWeekendAtOneRate:
    """A day with no peak hour today must not take the mode away."""

    def test_static(self):
        p = StaticTariffProvider(peak_rate=0.32, off_peak_rate=0.21)
        sat = MON + timedelta(days=5)
        assert p.get_price_level_at(sat.replace(hour=12)) is None  # one price
        assert p.has_cheap_rate() is True

    @pytest.mark.asyncio
    async def test_a_weekday_only_schedule_on_sunday(self):
        from homeassistant.util import dt as dt_util
        p = await _calendar()
        sun = (MON + timedelta(days=6)).replace(
            hour=20, tzinfo=dt_util.get_default_time_zone())
        with patch("custom_components.solar_energy_management.tariff."
                   "calendar_provider.dt_util.now", return_value=sun):
            assert p.get_price_level_at(sun) is None  # one price today
            assert _available(p, "calendar") is True


# ── guard: "dynamic" is a mode name, not "this tariff has cheap hours" ──

import ast  # noqa: E402
from pathlib import Path  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent

#: Every place that compares a value with the word "dynamic", and why the
#: mode name is the right question there. A new one fails this test: ask
#: ``PriceView.has_cheap_rate()`` (does the tariff have cheap hours?) or
#: the provider's prices instead, or add it here with its reason.
MODE_NAME_ASKED = {
    # the upgrade that moves a dynamic tariff to percentile levels
    "__init__.py": 1,
    # the Tariff page: which fields the dynamic form shows
    "config_flow.py": 3,
    # building the provider and the dynamic-only price push to the loads
    # (#953, one compare each), and the "cheap now" hint, left
    # dynamic-only (#1385)
    "coordinator/coordinator.py": 3,
    # (#1321) price paid vs the hours' average, left dynamic-only (#1385)
    "coordinator/energy_calculator.py": 1,
    # the install-module census names the dynamic tariff module
    "coordinator/install_modules.py": 1,
}


def _dynamic_compares(source: str) -> int:
    n = 0
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Compare):
            parts = [node.left, *node.comparators]
            n += any(isinstance(x, ast.Constant) and x.value == "dynamic"
                     for x in parts)
    return n


@pytest.mark.unit
def test_no_new_place_reads_the_mode_name_as_cheap_hours():
    found = {}
    for p in sorted(ROOT.rglob("*.py")):
        rel = p.relative_to(ROOT).as_posix()
        if (rel.startswith(("tests/", "node_modules/", ".git", "scripts/"))
                or "/tests/" in rel):
            continue
        n = _dynamic_compares(p.read_text(encoding="utf-8"))
        if n:
            found[rel] = n
    assert found == MODE_NAME_ASKED, found


@pytest.mark.unit
def test_the_guard_sees_the_old_gate():
    old = 'x = {"tariff_available": cfg.get("tariff_mode") == "dynamic"}'
    assert _dynamic_compares(old) == 1
    assert _dynamic_compares("x = view.has_cheap_rate()") == 0
