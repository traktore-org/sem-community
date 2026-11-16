"""(#1372) One place decides what a cheap hour is: ``PriceView``.

Steps 1-5 are a pure refactor, so the proof is PARITY: for the tariffs the
#994 and #1310 tests use, the view answers exactly what today's two rules
answer, hour by hour. The reference functions below are FROZEN copies of
the rules as they stood before the view existed (``tariff_cheap_at``,
``tariff_rate_cheap_at`` and ``price_signal.is_cheap``) — the live
``tariff_cheap_at`` now delegates to the view, so comparing against it
would test nothing.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator import day_ledger
from custom_components.solar_energy_management.coordinator import price_signal as ps
from custom_components.solar_energy_management.coordinator.price_view import (
    PriceAnswer, PriceState, PriceView, answer_for_level, day_has_cheaper,
    price_no_dearer,
)
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider, PriceLevel, PricePoint, StaticTariffProvider,
)

UTC = timezone.utc
FRI = datetime(2026, 11, 6, tzinfo=UTC)  # Fri..Mon covers a weekend
# A forecast is classified against the clock, so its fixtures start now.
NOW0 = dt_util.now().replace(minute=0, second=0, microsecond=0)


# ── frozen references: the rules as they were before the view ─────────────

def _ref_plan(prov, ts):
    if hasattr(prov, "get_price_level_at"):
        try:
            lvl = prov.get_price_level_at(ts)
        except Exception:  # noqa: BLE001
            return False
        return ps.is_cheap_name(lvl)
    return False


def _ref_rate(prov, ts):
    if hasattr(prov, "get_rate_level_at"):
        try:
            lvl = prov.get_rate_level_at(ts)
        except Exception:  # noqa: BLE001
            return False
        return ps.is_cheap_name(lvl)
    return _ref_plan(prov, ts)


# ── fixtures ──────────────────────────────────────────────────────────────

def _dynamic(curve, start=NOW0, step_min=60):
    """A dynamic provider whose price list IS ``curve`` (levels applied the
    way the real reader does)."""
    p = DynamicTariffProvider(MagicMock(), price_entity="sensor.fake",
                              classification_mode="percentile")
    p.hass.states.get.return_value = SimpleNamespace(state="0.30")
    pts = [PricePoint(timestamp=start + timedelta(minutes=step_min * i),
                      price=v, currency="EUR", level=PriceLevel.NORMAL)
           for i, v in enumerate(curve)]
    p._prices_cache = pts   # the classifier reads the cache
    p._apply_levels(pts)
    p._read_prices_list = lambda: pts
    return p


def _calendar():
    days = [0, 1, 2, 3, 4]
    return CalendarTariffProvider(
        None, peak_rate=1.0, off_peak_rate=0.6, export_rate=0.1,
        rules=[{"days": days, "start": "06:00", "end": "13:00", "tariff": "ht"},
               {"days": days, "start": "15:00", "end": "22:00", "tariff": "ht"}])


def _tariffs():
    spread = [0.10 + 0.02 * (i % 24) for i in range(96)]
    return {
        "static two rate": StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22),
        "static flat": StaticTariffProvider(peak_rate=0.36, off_peak_rate=0.36),
        "calendar": _calendar(),
        "dynamic": _dynamic(spread),
        "dynamic flat day": _dynamic([0.25] * 96),
        "dynamic forecast ends early": _dynamic(spread[:30]),
    }


def _hours(days=5):
    """Fri..Tue for the rules, and the same span from now for the curves."""
    return ([FRI + timedelta(hours=h) for h in range(24 * days)]
            + [NOW0 + timedelta(hours=h - 6) for h in range(24 * days)])


class _Fake:
    """A provider that answers a fixed level and a fixed price range."""

    def __init__(self, level, lo=0.2, hi=0.4, raises=False):
        self.level, self.raises = level, raises
        self._d = SimpleNamespace(today_min_price=lo, today_max_price=hi,
                                  today_avg_price=(lo + hi) / 2,
                                  price_level=level, upcoming_prices=[])

    def get_tariff_data(self):
        return self._d

    def get_price_level(self):
        if self.raises:
            raise RuntimeError("no")
        return self.level

    def get_price_level_at(self, when):
        return self.get_price_level()


# ── parity ────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("name", list(_tariffs()))
def test_plan_rule_is_what_tariff_cheap_at_was(name):
    prov = _tariffs()[name]
    view = PriceView(prov, rule="plan")
    got = [view.cheap_at(t) for t in _hours()]
    assert got == [_ref_plan(prov, t) for t in _hours()]


@pytest.mark.parametrize("name", list(_tariffs()))
def test_gate_rule_is_what_the_live_gate_reads(name):
    prov = _tariffs()[name]
    view = PriceView(prov, rule="gate")
    got = [view.cheap_at(t) for t in _hours()]
    assert got == [ps.is_cheap(prov, t) for t in _hours()]


@pytest.mark.parametrize("name", list(_tariffs()))
def test_rate_word_is_what_the_plan_card_read(name):
    prov = _tariffs()[name]
    view = PriceView(prov, rule="plan")
    assert [view.rate_cheap_at(t) for t in _hours()] == [
        _ref_rate(prov, t) for t in _hours()]


def test_the_parity_is_not_vacuous():
    """Both answers occur on the fixtures, and the two rules differ on a
    one-rate weekend (the #1310 case), so equality above means something."""
    t = _tariffs()
    cal = t["calendar"]
    plan = [PriceView(cal, rule="plan").cheap_at(x) for x in _hours()]
    rate = [PriceView(cal, rule="plan").rate_cheap_at(x) for x in _hours()]
    assert any(plan) and not all(plan)
    assert plan != rate
    dyn = [PriceView(t["dynamic"], rule="gate").cheap_at(x) for x in _hours()]
    assert any(dyn) and not all(dyn)


def test_a_provider_that_raises_is_not_cheap_on_both_rules():
    bad = _Fake(PriceLevel.CHEAP, raises=True)
    for rule in ("plan", "gate"):
        assert PriceView(bad, rule=rule).cheap_at(FRI) is False
    assert PriceView(bad, rule="plan").at(FRI).state is PriceState.UNKNOWN


def test_no_provider_is_not_cheap():
    for rule in ("plan", "gate"):
        v = PriceView(None, rule=rule)
        assert v.cheap_at(FRI) is False
        assert v.at(FRI).state is PriceState.UNKNOWN
    assert v.rate_cheap_fn() is None


def test_the_day_ledger_wrappers_delegate_and_keep_their_answers():
    for prov in _tariffs().values():
        for t in _hours(2):
            assert day_ledger.tariff_cheap_at(prov, t) == _ref_plan(prov, t)
            assert day_ledger.tariff_rate_cheap_at(prov, t) == _ref_rate(prov, t)


def test_rate_cheap_fn_is_none_for_a_dynamic_tariff_only():
    t = _tariffs()
    assert PriceView(t["dynamic"], rule="plan").rate_cheap_fn() is None
    assert callable(PriceView(t["calendar"], rule="plan").rate_cheap_fn())
    assert callable(PriceView(t["static two rate"], rule="plan").rate_cheap_fn())


# ── the four states ───────────────────────────────────────────────────────

def test_cheap_and_dear():
    cheap = PriceView(_Fake(PriceLevel.CHEAP), rule="gate").at(FRI)
    assert cheap == PriceAnswer(PriceState.CHEAP) and cheap.is_cheap
    dear = PriceView(_Fake(PriceLevel.VERY_EXPENSIVE), rule="gate").at(FRI)
    assert dear.state is PriceState.DEAR and dear.peak and not dear.is_cheap
    normal = PriceView(_Fake(PriceLevel.NORMAL), rule="gate").at(FRI)
    assert normal.state is PriceState.DEAR and not normal.peak


def test_one_price_is_a_state_on_the_gate_but_the_plan_reads_the_raw_word():
    flat_but_cheap = _Fake(PriceLevel.CHEAP, lo=0.3, hi=0.3)
    gate = PriceView(flat_but_cheap, rule="gate")
    assert gate.at(FRI).state is PriceState.ONE_PRICE
    assert gate.cheap_at(FRI) is False
    # the plan rule keeps today's answer: the raw word, cheap
    assert PriceView(flat_but_cheap, rule="plan").cheap_at(FRI) is True


def test_unknown_is_never_cheap():
    v = PriceView(_Fake(None), rule="gate")
    assert v.at(FRI).state is PriceState.UNKNOWN
    assert not v.at(FRI).is_cheap and v.cheap_at(FRI) is False


def test_now_uses_the_clock_it_was_given_and_the_live_level_on_the_gate():
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    night = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)   # a Monday, off-peak
    noon = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert PriceView(prov, now=night, rule="plan").now().is_cheap
    assert not PriceView(prov, now=lambda: noon, rule="plan").now().is_cheap
    live = _Fake(PriceLevel.CHEAP)
    assert PriceView(live, rule="gate").now().is_cheap   # get_price_level()


def test_answer_for_level_reads_a_stamped_word():
    assert answer_for_level("cheap").is_cheap
    assert answer_for_level(PriceLevel.NEGATIVE).is_cheap
    assert answer_for_level("expensive") == PriceAnswer(PriceState.DEAR, True)
    assert answer_for_level("normal") == PriceAnswer(PriceState.DEAR, False)
    for none in (None, "", "  "):
        assert answer_for_level(none).state is PriceState.UNKNOWN


# ── known_until ───────────────────────────────────────────────────────────

def test_a_rule_has_no_limit():
    assert StaticTariffProvider().known_until() is None
    assert _calendar().known_until() is None


def test_a_forecast_ends_where_its_last_point_ends():
    p = _dynamic([0.1, 0.2, 0.3, 0.4])
    assert p.known_until() == NOW0 + timedelta(hours=4)
    q = _dynamic([0.1, 0.2, 0.3, 0.4], step_min=15)
    assert q.known_until() == NOW0 + timedelta(minutes=60)


def test_a_forecast_with_no_prices_knows_nothing():
    p = _dynamic([])
    assert p.known_until() < NOW0 - timedelta(days=3650)
    assert PriceView(p, rule="plan").at(NOW0).state is PriceState.UNKNOWN


def test_an_hour_past_the_forecast_is_unknown():
    p = _dynamic([0.1, 0.5, 0.1, 0.5, 0.1, 0.5])
    v = PriceView(p, rule="plan")
    assert v.at(NOW0 + timedelta(hours=5, minutes=59)).state is not PriceState.UNKNOWN
    assert v.at(NOW0 + timedelta(hours=6)).state is PriceState.UNKNOWN


# ── cheap_hours ───────────────────────────────────────────────────────────

def test_cheap_hours_counts_quarter_hours_on_a_rule():
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    mon_0 = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    # Monday 00:00-24:00: cheap outside 07:00-20:00 = 11 h
    got = PriceView(prov, rule="plan").cheap_hours(
        mon_0, mon_0 + timedelta(hours=24))
    assert got == pytest.approx(11.0)


def test_cheap_hours_is_none_when_the_span_is_not_fully_known():
    p = _dynamic([0.1, 0.5, 0.1, 0.5])
    v = PriceView(p, rule="plan")
    assert v.cheap_hours(NOW0, NOW0 + timedelta(hours=4)) is not None
    assert v.cheap_hours(NOW0, NOW0 + timedelta(hours=5)) is None
    # a tolerance lets the curve end that much early
    assert v.cheap_hours(NOW0, NOW0 + timedelta(hours=5), tolerance_h=1.0) is not None
    assert PriceView(_dynamic([]), rule="plan").cheap_hours(
        NOW0, NOW0 + timedelta(hours=1)) is None


# ── comparing hours ───────────────────────────────────────────────────────

def test_no_dearer_compares_two_hours_of_the_same_tariff():
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    v = PriceView(prov, rule="plan")
    night = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    night2 = datetime(2026, 11, 9, 23, 0, tzinfo=UTC)
    noon = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert v.no_dearer(night2, night) is True       # same rate
    assert v.no_dearer(noon, night) is False        # dearer
    assert v.no_dearer(night, noon) is True         # cheaper
    assert PriceView(None, rule="plan").no_dearer(night, noon) is False


def test_price_no_dearer_and_day_has_cheaper_helpers():
    assert price_no_dearer(0.2, 0.2) and price_no_dearer(0.2, 0.3)
    assert not price_no_dearer(0.31, 0.3)
    assert not price_no_dearer(None, 0.3) and not price_no_dearer(0.2, None)
    assert day_has_cheaper([False, True]) and not day_has_cheaper([])
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    v = PriceView(prov, rule="plan")
    mon = datetime(2026, 11, 9, tzinfo=UTC)
    assert v.day_has_cheaper([mon + timedelta(hours=h) for h in (9, 12, 23)])
    assert not v.day_has_cheaper([mon + timedelta(hours=h) for h in (9, 12)])


# ── a device with its own tariff ──────────────────────────────────────────

def test_a_device_with_its_own_readable_tariff_asks_that_tariff():
    house = _Fake(PriceLevel.NORMAL)
    own = _Fake(PriceLevel.CHEAP)
    tariffs = MagicMock()
    tariffs.plan_tariff.return_value = SimpleNamespace(provider=own)
    dev = object()
    v = PriceView.for_device(dev, house, tariffs, rule="gate")
    assert v.cheap_at(FRI) is True
    tariffs.plan_tariff.assert_called_once_with(dev)


def test_a_device_without_one_or_an_unreadable_one_asks_the_house():
    house = _Fake(PriceLevel.NORMAL)
    tariffs = MagicMock()
    tariffs.plan_tariff.return_value = None     # unreadable or not set
    assert PriceView.for_device(object(), house, tariffs).cheap_at(FRI) is False
    assert PriceView.for_device(object(), _Fake(PriceLevel.CHEAP)).cheap_at(FRI)
