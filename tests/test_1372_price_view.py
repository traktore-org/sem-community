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
    view = PriceView(prov)
    got = [view.cheap_at(t) for t in _hours()]
    assert got == [_ref_plan(prov, t) for t in _hours()]


@pytest.mark.parametrize("name", list(_tariffs()))
def test_the_live_rule_about_a_later_hour_is_what_the_gate_read(name):
    prov = _tariffs()[name]
    view = PriceView(prov)
    got = [view.cheap_seen_from_now(t) for t in _hours()]
    assert got == [ps.is_cheap(prov, t) for t in _hours()]
    assert view.cheap_now() == ps.is_cheap(prov)
    assert view.cheap_at(None) == ps.is_cheap(prov)


@pytest.mark.parametrize("name", list(_tariffs()))
def test_rate_word_is_what_the_plan_card_read(name):
    prov = _tariffs()[name]
    view = PriceView(prov)
    assert [view.rate_cheap_at(t) for t in _hours()] == [
        _ref_rate(prov, t) for t in _hours()]


def test_the_parity_is_not_vacuous():
    """Both answers occur on the fixtures, and the two rules differ on a
    one-rate weekend (the #1310 case), so equality above means something."""
    t = _tariffs()
    cal = t["calendar"]
    plan = [PriceView(cal).cheap_at(x) for x in _hours()]
    rate = [PriceView(cal).rate_cheap_at(x) for x in _hours()]
    assert any(plan) and not all(plan)
    assert plan != rate
    dyn = [PriceView(t["dynamic"]).cheap_seen_from_now(x) for x in _hours()]
    assert any(dyn) and not all(dyn)


def test_a_provider_that_raises_is_not_cheap_on_both_rules():
    bad = _Fake(PriceLevel.CHEAP, raises=True)
    view = PriceView(bad)
    assert view.cheap_at(FRI) is False and view.cheap_now() is False
    assert view.cheap_seen_from_now(FRI) is False
    assert view.at(FRI).state is PriceState.UNKNOWN


def test_no_provider_is_not_cheap():
    v = PriceView(None)
    assert v.cheap_at(FRI) is False and v.cheap_now() is False
    assert v.at(FRI).state is PriceState.UNKNOWN
    assert v.now().state is PriceState.UNKNOWN
    assert v.rate_cheap_fn() is None


def test_the_day_ledger_wrappers_delegate_and_keep_their_answers():
    for prov in _tariffs().values():
        for t in _hours(2):
            assert day_ledger.tariff_cheap_at(prov, t) == _ref_plan(prov, t)
            assert day_ledger.tariff_rate_cheap_at(prov, t) == _ref_rate(prov, t)


def test_rate_cheap_fn_is_none_for_a_dynamic_tariff_only():
    t = _tariffs()
    assert PriceView(t["dynamic"]).rate_cheap_fn() is None
    assert callable(PriceView(t["calendar"]).rate_cheap_fn())
    assert callable(PriceView(t["static two rate"]).rate_cheap_fn())


# ── the four states ───────────────────────────────────────────────────────

def test_cheap_and_dear():
    for ask in (lambda v: v.at(FRI), lambda v: v.now()):     # both questions
        cheap = ask(PriceView(_Fake(PriceLevel.CHEAP)))
        assert cheap == PriceAnswer(PriceState.CHEAP) and cheap.is_cheap
        dear = ask(PriceView(_Fake(PriceLevel.VERY_EXPENSIVE)))
        assert dear.state is PriceState.DEAR and dear.peak and not dear.is_cheap
        normal = ask(PriceView(_Fake(PriceLevel.NORMAL)))
        assert normal.state is PriceState.DEAR and not normal.peak


def test_the_two_questions_differ_where_they_should():
    """(#1372 step 8) A provider whose word is "cheap" while the prices SEM
    can still act on are all the same: the HOUR is at a cheap level (the
    plan may use it), but it is not worth acting NOW (the gate holds)."""
    flat_but_cheap = _Fake(PriceLevel.CHEAP, lo=0.3, hi=0.3)
    view = PriceView(flat_but_cheap)
    assert view.cheap_at(FRI) is True and view.at(FRI).is_cheap
    assert view.cheap_now() is False
    assert view.now().state is PriceState.ONE_PRICE
    assert view.cheap_seen_from_now(FRI) is False


def test_a_one_rate_weekend_does_not_hide_mondays_cheap_hours():
    """Why the two questions must not be merged: asked on a Sunday, Monday
    00:00 is a cheap hour for the plan. The live rule about that hour looks
    at the prices from now on and may not see it."""
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    monday_night = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)
    sunday_noon = datetime(2026, 11, 8, 12, 0, tzinfo=UTC)
    view = PriceView(prov)
    assert view.cheap_at(monday_night) is True
    assert view.cheap_at(sunday_noon) is False          # a one-rate day
    assert view.at(sunday_noon).state in (PriceState.ONE_PRICE, PriceState.UNKNOWN)


def test_unknown_is_never_cheap():
    v = PriceView(_Fake(None))
    assert v.at(FRI).state is PriceState.UNKNOWN
    assert v.now().state is PriceState.UNKNOWN
    assert not v.at(FRI).is_cheap and v.cheap_at(FRI) is False and v.cheap_now() is False


def test_now_is_the_live_level():
    live = _Fake(PriceLevel.CHEAP)
    assert PriceView(live).now().is_cheap                # get_price_level()
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    night = datetime(2026, 11, 9, 3, 0, tzinfo=UTC)      # a Monday, off-peak
    noon = datetime(2026, 11, 9, 12, 0, tzinfo=UTC)
    assert PriceView(prov).at(night).is_cheap
    assert not PriceView(prov).at(noon).is_cheap


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
    assert PriceView(p).at(NOW0).state is PriceState.UNKNOWN


def test_an_hour_past_the_forecast_is_unknown():
    p = _dynamic([0.1, 0.5, 0.1, 0.5, 0.1, 0.5])
    v = PriceView(p)
    assert v.at(NOW0 + timedelta(hours=5, minutes=59)).state is not PriceState.UNKNOWN
    assert v.at(NOW0 + timedelta(hours=6)).state is PriceState.UNKNOWN


# ── cheap_hours ───────────────────────────────────────────────────────────

def test_cheap_hours_counts_quarter_hours_on_a_rule():
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    mon_0 = datetime(2026, 11, 9, 0, 0, tzinfo=UTC)
    # Monday 00:00-24:00: cheap outside 07:00-20:00 = 11 h
    got = PriceView(prov).cheap_hours(
        mon_0, mon_0 + timedelta(hours=24))
    assert got == pytest.approx(11.0)


def test_cheap_hours_is_none_when_the_span_is_not_fully_known():
    p = _dynamic([0.1, 0.5, 0.1, 0.5])
    v = PriceView(p)
    assert v.cheap_hours(NOW0, NOW0 + timedelta(hours=4)) is not None
    assert v.cheap_hours(NOW0, NOW0 + timedelta(hours=5)) is None
    # a tolerance lets the curve end that much early
    assert v.cheap_hours(NOW0, NOW0 + timedelta(hours=5), tolerance_h=1.0) is not None
    assert PriceView(_dynamic([])).cheap_hours(
        NOW0, NOW0 + timedelta(hours=1)) is None


# ── comparing hours ───────────────────────────────────────────────────────

def test_price_no_dearer_and_day_has_cheaper_helpers():
    assert price_no_dearer(0.2, 0.2) and price_no_dearer(0.2, 0.3)
    assert not price_no_dearer(0.31, 0.3)
    assert not price_no_dearer(None, 0.3) and not price_no_dearer(0.2, None)
    assert day_has_cheaper([False, True]) and not day_has_cheaper([])
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    v = PriceView(prov)
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
    v = PriceView.for_device(dev, house, tariffs)
    assert v.cheap_at(FRI) is True
    tariffs.plan_tariff.assert_called_once_with(dev)


def test_a_device_without_one_or_an_unreadable_one_asks_the_house():
    house = _Fake(PriceLevel.NORMAL)
    tariffs = MagicMock()
    tariffs.plan_tariff.return_value = None     # unreadable or not set
    assert PriceView.for_device(object(), house, tariffs).cheap_at(FRI) is False
    assert PriceView.for_device(object(), _Fake(PriceLevel.CHEAP)).cheap_at(FRI)


# ── the Legionella count keeps its numbers ────────────────────────────────

def _ref_cheap_hours_left(prov, dev, hw, now):
    """FROZEN copy of ``SEMCoordinator._legionella_cheap_hours_left`` as it
    was before the view (#1368): the private price list and the plan rule."""
    try:
        if (prov is None or not hasattr(prov, "get_price_level_at")
                or getattr(hw, "_last_legionella_time", None) is None
                or any(getattr(dev, k, None) for k in
                       ("tariff_rate", "tariff_entity", "tariff_meter"))):
            return None
        left_h = float(hw.legionella_interval_hours) - float(hw.hours_since_legionella)
        if not 0.0 < left_h <= 24.0:
            return None
        reader = getattr(prov, "_read_prices_list", None)
        if callable(reader):
            prices = reader() or []
            if not prices or max(p.timestamp for p in prices) < (
                    now + timedelta(hours=left_h - 1.0)):
                return None
        steps = int(left_h * 4)
        return 0.25 * sum(
            1 for i in range(steps)
            if _ref_plan(prov, now + timedelta(minutes=15 * i)))
    except Exception:  # noqa: BLE001
        return None


def _left_now(prov, left_h, monkeypatch, *, now, own=False, run=True):
    from custom_components.solar_energy_management.coordinator import (
        coordinator as coord_mod,
    )
    dev = SimpleNamespace(tariff_rate=0.1 if own else 0.0, tariff_entity="",
                          tariff_meter="")
    hw = SimpleNamespace(
        _last_legionella_time=object() if run else None,
        legionella_interval_hours=168.0, hours_since_legionella=168.0 - left_h)
    fake = SimpleNamespace(
        _tariff_provider=prov,
        _surplus_controller=SimpleNamespace(_devices={"hot_water": dev}))
    monkeypatch.setattr(coord_mod, "dt_util", SimpleNamespace(now=lambda: now))
    got = coord_mod.SEMCoordinator._legionella_cheap_hours_left(fake, hw)
    return got, _ref_cheap_hours_left(prov, dev, hw, now)


def _local(h, d=9):
    return datetime(2026, 11, d, h, 0, tzinfo=dt_util.DEFAULT_TIME_ZONE)


def test_legionella_hours_on_a_static_tariff_are_the_same(monkeypatch):
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    got, ref = _left_now(prov, 12.0, monkeypatch, now=_local(14))
    # Monday 14:00 -> 02:00: cheap 20:00-24:00 and 00:00-02:00
    assert got == ref == pytest.approx(6.0)
    got, ref = _left_now(prov, 10.3, monkeypatch, now=_local(14))
    assert got == ref and got > 0


def test_legionella_hours_on_a_dynamic_curve_are_the_same(monkeypatch):
    curve = [0.10 + 0.02 * (i % 24) for i in range(48)]
    prov = _dynamic(curve)
    got, ref = _left_now(prov, 9.5, monkeypatch, now=NOW0)
    assert got == ref and got is not None and got > 0


def test_a_forecast_that_ends_before_the_due_time_is_not_known(monkeypatch):
    prov = _dynamic([0.1, 0.5, 0.1, 0.5, 0.1, 0.5])        # 6 h of prices
    got, ref = _left_now(prov, 9.0, monkeypatch, now=NOW0)
    assert got is None and ref is None
    # and it IS known when the curve covers the span
    got, ref = _left_now(prov, 5.0, monkeypatch, now=NOW0)
    assert got == ref and got is not None


def test_a_curve_ending_up_to_an_hour_early_still_counts(monkeypatch):
    """Kept on purpose (#1372): the last point may START up to 1 h before
    the due time — hourly and 15-minute curves alike."""
    hourly = _dynamic([0.1, 0.5, 0.1, 0.5, 0.1, 0.5])       # last starts +5 h
    got, ref = _left_now(hourly, 6.0, monkeypatch, now=NOW0)
    assert got == ref and got is not None
    got, ref = _left_now(hourly, 6.5, monkeypatch, now=NOW0)
    assert got is None and ref is None
    quarter = _dynamic([0.10 + 0.01 * (i % 8) for i in range(24)],
                       step_min=15)                          # last starts +5.75 h
    got, ref = _left_now(quarter, 6.5, monkeypatch, now=NOW0)
    assert got == ref and got is not None
    got, ref = _left_now(quarter, 7.0, monkeypatch, now=NOW0)
    assert got is None and ref is None


def test_a_tank_with_its_own_tariff_or_no_run_or_a_far_due_time_is_not_known(
        monkeypatch):
    prov = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
    for kw, left in (({"own": True}, 12.0), ({"run": False}, 12.0), ({}, 30.0),
                     ({}, 0.0)):
        got, ref = _left_now(prov, left, monkeypatch, now=_local(14), **kw)
        assert got is None and ref is None, (kw, left)


# ── (#1372 step 6) a device's gate: parity with device_price_level ─────────

def _dev(**tariff):
    d = SimpleNamespace(device_id="d1", tariff_rate=0.0, tariff_entity="",
                        tariff_meter="", _tariff_level=None,
                        tariff_inputs=None)
    d.__dict__.update(tariff)
    return d


def _stamped_devices():
    from custom_components.solar_energy_management.coordinator.device_tariff import (
        DeviceTariffs,
    )
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    raw = [{"start": (now + timedelta(hours=i)).isoformat(), "value": v}
           for i, v in enumerate([0.1, 0.2, 0.3, 0.4, 0.5, 0.6])]
    live = SimpleNamespace(state="0.1", attributes={"raw_today": raw})
    states = {"sensor.own": live,
              "sensor.gone": SimpleNamespace(state="unavailable",
                                             attributes={})}
    hass = MagicMock()
    hass.states.get = lambda eid: states.get(eid)
    devs = {
        "none": _dev(),
        "fixed": _dev(tariff_rate=0.21),
        "entity": _dev(tariff_entity="sensor.own"),
        "meter": _dev(tariff_rate=0.19, tariff_meter="sensor.m"),
        "unread": _dev(tariff_entity="sensor.gone"),
    }
    DeviceTariffs(hass).stamp(list(devs.values()))
    return devs


@pytest.mark.parametrize("house", ["very_cheap", "cheap", "normal",
                                   "expensive", "very_expensive", "flat", None])
def test_a_devices_answer_is_the_level_its_gate_reads_today(house):
    from custom_components.solar_energy_management.coordinator.device_tariff import (
        device_price_level,
    )
    from custom_components.solar_energy_management.coordinator.price_view import (
        answer_for_device,
    )
    for name, d in _stamped_devices().items():
        lvl = device_price_level(d, house)
        got = answer_for_device(d, house)
        assert got.is_cheap == ps.is_cheap_name(lvl), (name, house)
        assert got.peak == ps.is_expensive_name(lvl), (name, house)
        assert got == answer_for_level(lvl), (name, house)
