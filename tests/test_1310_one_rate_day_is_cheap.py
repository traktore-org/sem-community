"""(#1310, round 2) A whole off-peak Sunday was not drawn as cheap.

@matekogon, Calendar tariff through a Schedule helper: peak Mon-Fri
06:00-13:00 and 15:00-22:00, the weekend all off-peak. On Sunday
08.11.2026 the Energy Plan card's "cheap hours" band began at Monday 00:00.
Sunday 15:00-24:00 had the same price and no band; the slot tip showed the
same off-peak price on both sides of midnight.

Cause (class 47, third catch): round 1 gave the slot its own word,
``LedgerSlot.tariff_cheap``, but filled it from execution's accessor.
``get_price_level_at`` refuses a day that holds one rate (#994: execution
must not hold the pack until Monday), so a Sunday with no peak block has no
level, while Monday has both rates and its night is CHEAP. One rate, two
words on one timeline.

Now ``get_rate_level_at`` asks the tariff's week, and
``day_ledger.tariff_rate_cheap_at`` fills ``tariff_cheap`` on every slot
the card's band, the tomorrow preview and Assist read. Execution and the
packer keep the day rule.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import datetime, time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import coordinator as coord_mod
from custom_components.solar_energy_management.coordinator import energy_planner
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.day_ledger import (
    build_day_slots,
    tariff_cheap_at,
    tariff_price_at,
    tariff_rate_cheap_at,
    tomorrow_preview,
)
from custom_components.solar_energy_management.sensor import _energy_plan_attrs
from custom_components.solar_energy_management.tariff.calendar_provider import (
    CalendarTariffProvider,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    StaticTariffProvider,
    TariffProvider,
)

from .test_638_shadow_mode import (  # noqa: F401 — fixtures come along
    _DayCapableTime, _fake_load, _fake_self, _power, _scheduler,
    freeze_targets,
)

ROOT = Path(__file__).resolve().parent.parent

# 2026-11-07 is a Saturday, 2026-11-08 the reporter's Sunday.
SAT = datetime(2026, 11, 7)
SUN = datetime(2026, 11, 8)
MON = datetime(2026, 11, 9)

WORKDAYS = [0, 1, 2, 3, 4]


def _g12w(peak=1.0, off_peak=0.6, **kw):
    """The reporter's tariff as rules: peak Mon-Fri 06-13 and 15-22."""
    return CalendarTariffProvider(
        kw.pop("hass", None), peak_rate=peak, off_peak_rate=off_peak,
        export_rate=0.1,
        rules=kw.pop("rules", [
            {"days": WORKDAYS, "start": "06:00", "end": "13:00", "tariff": "ht"},
            {"days": WORKDAYS, "start": "15:00", "end": "22:00", "tariff": "ht"},
        ]),
        **kw,
    )


def _peak(t):
    return t.weekday() < 5 and (6 <= t.hour < 13 or 15 <= t.hour < 22)


# ---------------------------------------------------------------------------
# The provider: one word per question
# ---------------------------------------------------------------------------

class TestTheCalendarRules:

    def test_a_sunday_is_at_the_cheap_rate(self):
        p = _g12w()
        assert p.get_rate_level_at(SUN.replace(hour=15)) is PriceLevel.CHEAP
        assert p.get_rate_level_at(SAT.replace(hour=12)) is PriceLevel.CHEAP

    def test_execution_keeps_the_day_rule(self):
        """#994: a day with one rate has no level for execution."""
        p = _g12w()
        assert p.get_price_level_at(SUN.replace(hour=15)) is None
        assert p.get_price_level_at(SAT.replace(hour=12)) is None

    def test_a_workday_has_the_same_word_on_both(self):
        p = _g12w()
        for h in range(24):
            t = MON.replace(hour=h)
            want = PriceLevel.NORMAL if _peak(t) else PriceLevel.CHEAP
            assert p.get_rate_level_at(t) is want, h
            assert p.get_price_level_at(t) is want, h

    def test_equal_rates_have_no_word(self):
        p = _g12w(peak=0.6, off_peak=0.6)
        for t in (SUN.replace(hour=15), MON.replace(hour=3)):
            assert p.get_rate_level_at(t) is None

    def test_a_week_without_a_peak_has_no_word(self):
        """The #994 incident: no rules at all answered CHEAP forever."""
        p = _g12w(rules=[])
        for t in (SUN.replace(hour=15), MON.replace(hour=3)):
            assert p.get_rate_level_at(t) is None

    def test_a_zero_width_peak_is_no_peak(self):
        p = _g12w(rules=[{"days": WORKDAYS, "start": "06:00",
                          "end": "06:00", "tariff": "ht"}])
        assert p.get_rate_level_at(SUN.replace(hour=15)) is None

    def test_a_holiday_has_no_peak_to_compare(self):
        hass = MagicMock()
        hass.states.get = lambda eid: SimpleNamespace(state="on")
        p = _g12w(hass=hass, holiday_entity="binary_sensor.holiday")
        assert p.get_rate_level_at(MON.replace(hour=3)) is None

    def test_an_unreadable_holiday_has_no_word(self):
        hass = MagicMock()
        hass.states.get = lambda eid: SimpleNamespace(state="unavailable")
        p = _g12w(hass=hass, holiday_entity="binary_sensor.holiday")
        assert p.get_rate_level_at(SUN.replace(hour=15)) is None


HELPER = "schedule.g12w"
_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday",
         "saturday", "sunday")
_BLOCKS = [{"from": time(6, 0), "to": time(13, 0)},
           {"from": time(15, 0), "to": time(22, 0)}]


def _helper_hass(week, state="off"):
    hass = MagicMock()
    states = {HELPER: SimpleNamespace(state=state, last_updated="t0")}
    hass.states.get = lambda eid: states.get(eid)
    hass.services.has_service = MagicMock(return_value=True)
    hass.services.async_call = AsyncMock(return_value={HELPER: week})
    return hass


async def _helper(week, state="off"):
    p = CalendarTariffProvider(
        _helper_hass(week, state), peak_rate=1.0, off_peak_rate=0.6,
        rules=[], schedule_entity=HELPER)
    await p.async_refresh_service_prices()
    return p


G12W_WEEK = {d: (list(_BLOCKS) if i < 5 else []) for i, d in enumerate(_DAYS)}


class TestTheScheduleHelper:
    """The reporter's real input: blocks are the peak hours."""

    @pytest.mark.asyncio
    async def test_the_reporters_sunday(self):
        p = await _helper(G12W_WEEK)
        sun = SUN.replace(hour=15)
        assert p.get_price_level_at(sun) is None            # #994 kept
        assert p.get_rate_level_at(sun) is PriceLevel.CHEAP
        assert p.get_rate_level_at(MON.replace(hour=3)) is PriceLevel.CHEAP
        assert p.get_rate_level_at(MON.replace(hour=7)) is PriceLevel.NORMAL
        assert p.get_rate_level_at(MON.replace(hour=13)) is PriceLevel.CHEAP

    @pytest.mark.asyncio
    async def test_a_helper_with_no_block_has_no_word(self):
        p = await _helper({d: [] for d in _DAYS})
        assert p.get_rate_level_at(MON.replace(hour=3)) is None

    def test_an_unavailable_helper_has_no_word(self):
        p = CalendarTariffProvider(
            _helper_hass(G12W_WEEK, state="unavailable"), peak_rate=1.0,
            off_peak_rate=0.6, rules=[], schedule_entity=HELPER)
        assert p.get_rate_level_at(SUN.replace(hour=15)) is None


class TestTheStaticClock:
    """The sibling provider has the same weekend rule (#994)."""

    def test_a_saturday_is_at_the_cheap_rate(self):
        p = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22)
        sat = SAT.replace(hour=12)
        assert p.get_price_level_at(sat) is None            # #994 kept
        assert p.get_rate_level_at(sat) is PriceLevel.CHEAP
        assert p.get_rate_level_at(MON.replace(hour=12)) is PriceLevel.NORMAL
        assert p.get_rate_level_at(MON.replace(hour=3)) is PriceLevel.CHEAP

    def test_the_flat_default_has_no_word(self):
        p = StaticTariffProvider()              # 0.3387 = 0.3387
        assert p.get_rate_level_at(SAT.replace(hour=12)) is None
        assert p.get_rate_level_at(MON.replace(hour=3)) is None

    def test_an_empty_peak_window_has_no_word(self):
        p = StaticTariffProvider(peak_rate=0.35, off_peak_rate=0.22,
                                 peak_start=7, peak_end=7)
        assert p.get_rate_level_at(MON.replace(hour=3)) is None


class TestADynamicTariff:

    def test_the_rate_word_is_the_price_level(self):
        fake = SimpleNamespace(get_price_level_at=lambda t: PriceLevel.EXPENSIVE)
        assert (TariffProvider.get_rate_level_at(fake, MON)
                is PriceLevel.EXPENSIVE)

    def test_no_dynamic_provider_overrides_it(self):
        assert (DynamicTariffProvider.get_rate_level_at
                is TariffProvider.get_rate_level_at)


# ---------------------------------------------------------------------------
# The accessors and the slots
# ---------------------------------------------------------------------------

class TestTheAccessors:

    def test_the_two_words_on_the_reporters_sunday(self):
        p = _g12w()
        sun = SUN.replace(hour=15)
        assert tariff_rate_cheap_at(p, sun) is True
        assert tariff_cheap_at(p, sun) is False

    def test_a_raising_provider_is_not_cheap(self):
        class _Boom:
            def get_rate_level_at(self, t):
                raise RuntimeError("no level")
        assert tariff_rate_cheap_at(_Boom(), SUN) is False

    def test_a_provider_without_the_rate_word_uses_the_gate(self):
        fake = SimpleNamespace(get_price_level_at=lambda t: PriceLevel.CHEAP)
        assert tariff_rate_cheap_at(fake, SUN) is True
        assert tariff_rate_cheap_at(object(), SUN) is False


def _sunday_slots(**kw):
    p = _g12w()
    args = dict(
        start=SUN.replace(hour=7), end=SUN.replace(hour=21), day_kwh=20.0,
        sunrise=SUN.replace(hour=7), sunset=SUN.replace(hour=17),
        home_w_at=lambda t: 300.0,
        price_at=lambda ts: tariff_price_at(p, ts),
        level_cheap_at=lambda ts: tariff_cheap_at(p, ts),
        tariff_cheap_at=lambda ts: tariff_rate_cheap_at(p, ts),
    )
    args.update(kw)
    return build_day_slots(**args)


class TestTheDaySlots:

    def test_every_sunday_slot_is_at_the_cheap_rate(self):
        slots = _sunday_slots()
        assert any(s.cap_override_w is not None for s in slots)
        assert any(s.cap_override_w is None for s in slots)
        for s in slots:
            assert s.tariff_cheap is True, s.start

    def test_the_packer_keeps_execution_s_word(self):
        """A sun slot may hold a cheap-only load; a dark Sunday hour may not."""
        for s in _sunday_slots():
            if s.cap_override_w is not None:
                assert s.level_cheap is True, s.start
            else:
                assert s.level_cheap is False, s.start

    def test_without_the_rate_word_the_slot_has_one_word(self):
        for s in _sunday_slots(tariff_cheap_at=None):
            if s.cap_override_w is None:
                assert s.tariff_cheap is s.level_cheap is False

    def test_a_raising_rate_word_leaves_the_gate_alone(self):
        def _boom(t):
            raise RuntimeError("no level")
        for s in _sunday_slots(tariff_cheap_at=_boom):
            assert s.tariff_cheap is False
            if s.cap_override_w is not None:
                assert s.level_cheap is True

    def test_tomorrow_s_sunday_is_one_cheap_window(self):
        p = _g12w()
        prev = tomorrow_preview(
            day_start=SUN.replace(hour=7), day_end=SUN.replace(hour=21),
            day_kwh=20.0, sunrise=SUN.replace(hour=7),
            sunset=SUN.replace(hour=17), home_w_at=lambda t: 300.0,
            price_at=lambda ts: tariff_price_at(p, ts),
            level_cheap_at=lambda ts: tariff_cheap_at(p, ts),
            tariff_cheap_at=lambda ts: tariff_rate_cheap_at(p, ts),
            stamps_at=SUN.replace(hour=7))
        assert prev["cheap_windows"] == [{
            "start": SUN.replace(hour=7).isoformat(),
            "end": SUN.replace(hour=21).isoformat()}]


# ---------------------------------------------------------------------------
# The stamped plan: what the card and Assist read
# ---------------------------------------------------------------------------

def _stamp_sunday(monkeypatch):
    seen = []
    real = energy_planner.build_night_ledger

    def _spy(slots, **kw):
        seen.extend(slots)
        return real(slots, **kw)

    monkeypatch.setattr(energy_planner, "build_night_ledger", _spy)
    fake = _fake_self(devices=[_fake_load()])
    fake.time_manager = _DayCapableTime()          # night 21:00-07:00
    fake._forecast_reader = SimpleNamespace(forecast_data=SimpleNamespace(
        forecast_remaining_today_kwh=20.0))
    fake._tariff_provider = _g12w()
    fixed = datetime(2026, 11, 8, 8, 0,
                     tzinfo=coord_mod.dt_util.DEFAULT_TIME_ZONE)
    monkeypatch.setattr(coord_mod.dt_util, "now", lambda *a, **k: fixed)
    SEMCoordinator._shadow_energy_plan(
        fake, _scheduler(), energy=MagicMock(), power=_power())
    plan = fake._energy_plan_shadow
    assert isinstance(plan, dict) and plan["slots"], "no plan to judge"
    assert seen, "the stamp never built its ledger"
    return plan, seen


class TestThePlanRows:

    def test_the_band_covers_sunday_and_monday_night(self, freeze_targets,
                                                     monkeypatch):
        plan, _ = _stamp_sunday(monkeypatch)
        rows = plan["slots"]
        assert rows[0]["start"].startswith("2026-11-08T08")
        assert rows[-1]["end"].startswith("2026-11-09T07")
        for r in rows:
            t = datetime.fromisoformat(r["start"])
            assert r["cheap"] is (not _peak(t)), r["start"]
        sunday_evening = [r for r in rows if r["start"][:13] in (
            "2026-11-08T15", "2026-11-08T22", "2026-11-08T23")]
        assert len(sunday_evening) == 3
        assert all(r["cheap"] for r in sunday_evening)

    def test_the_packer_still_waits_for_monday(self, freeze_targets,
                                               monkeypatch):
        """Execution's word is unchanged: a dark Sunday hour is not a
        cheap-hours slot, Monday 00:00 is."""
        _, ledger = _stamp_sunday(monkeypatch)
        for s in ledger:
            if s.cap_override_w is not None:
                continue
            want = s.start.weekday() == 0 and s.start.hour < 6
            assert s.level_cheap is want, s.start
            assert s.tariff_cheap is (not _peak(s.start)), s.start

    def test_the_entity_carries_the_same_word(self, freeze_targets,
                                              monkeypatch):
        plan, _ = _stamp_sunday(monkeypatch)
        rows = {s["start"][:13]: s for s in _energy_plan_attrs(plan)["slots"]}
        assert rows["2026-11-08T22"]["cheap"] is True
        assert rows["2026-11-09T03"]["cheap"] is True
        assert rows["2026-11-09T06"]["cheap"] is False


# ---------------------------------------------------------------------------
# Guard: every published slot gets the rate word, not the gate's
# ---------------------------------------------------------------------------

def _calls(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            f = node.func
            fname = f.id if isinstance(f, ast.Name) else getattr(f, "attr", None)
            if fname == name:
                yield node


def _one_word_slots(source):
    """``LedgerSlot(...)`` calls whose two words are the same expression."""
    bad = []
    for call in _calls(ast.parse(source), "LedgerSlot"):
        kw = {k.arg: ast.dump(k.value) for k in call.keywords}
        if "level_cheap" in kw and kw.get("tariff_cheap") == kw["level_cheap"]:
            bad.append(call.lineno)
    return bad


class TestTheGuard:

    PLANNER = ("coordinator/coordinator.py", "coordinator/day_ledger.py")

    def test_every_published_builder_gets_the_rate_word(self):
        tree = ast.parse((ROOT / "coordinator/coordinator.py").read_text())
        calls = [c for n in ("build_day_slots", "tomorrow_preview")
                 for c in _calls(tree, n)]
        assert len(calls) >= 3
        for c in calls:
            assert "tariff_cheap_at" in {k.arg for k in c.keywords}, c.lineno

    def test_no_slot_copies_the_gate_into_the_rate_word(self):
        for rel in self.PLANNER:
            assert _one_word_slots((ROOT / rel).read_text()) == [], rel

    def test_the_guard_catches_the_old_line(self):
        old = textwrap.dedent("""
            cheap = bool(_cheap_at(t))
            LedgerSlot(start=t, end=end, level_cheap=cheap, tariff_cheap=cheap)
        """)
        assert _one_word_slots(old) == [3]

    def test_the_rows_publish_the_rate_word(self):
        src = inspect.getsource(SEMCoordinator._shadow_energy_plan)
        assert '"cheap": bool(s.tariff_cheap)' in src
