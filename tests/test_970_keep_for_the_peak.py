"""#970 — keep the battery for the peak limit, on any tariff.

@Hanzzzie85 pays for his highest 15-minute peak. Power bought under that
limit costs him no extra fee, so he wants the house to buy up to the limit
and the battery to give only the rest: house 5 kW, sun 2 kW, limit 2.5 kW —
0.5 kW from the pack. Once the pack is high and the coming sun refills it,
the pack covers the house as usual.

The rate was there since #1003 (``test_970_hold_at_peak.py``): a HELD house
gives way to the slot budget. What was missing was a WHEN on a flat tariff —
the house sink holds only in a cheap hour. This is that WHEN, by its own
switch (default off), and nothing else: the same branch in
``decide_battery``, the same slot budget, the same write through
``actuate_battery``.

The first build (reverted 22.09) sized a shave from the home balance, which
has the car subtracted out, and pinned the pack at 0 W while a car pushed the
meter over. Here the hold stands aside while a car charges, and the cover is
the house's own import against the slot budget (#1003's arithmetic).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.peak_guard import (
    PeakSlotTracker,
    slot_allowed_import_w,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    HELD,
    OPEN,
    PEAK_HOLD_RELEASE_BAND_SOC,
    SinkVerdict,
    peak_hold_state,
    sink_verdicts,
)
from custom_components.solar_energy_management.persisted_flags import (
    PERSISTED_FLAG_DEFAULTS,
)

from .ast_contracts import calls

NOW = datetime(2026, 11, 10, 13, 0)
LIMIT_KW = 2.5
MAX_W = 5000.0


def _house(**kw):
    base = dict(
        now=NOW, tariff_level="flat", upcoming=None, export_rate=None,
        export_rate_known=False, export_guard_enabled=False,
        house_sink_enabled=False, morning_window_enabled=False,
        departure=None, morning_hours=2.0, forecast_refills_pack=False,
        pacing_horizon_end=None)
    base.update(kw)
    return sink_verdicts(**base)["house"]


def _on(**kw):
    base = dict(peak_hold_enabled=True, peak_limit_set=True, pack_soc=60.0,
                peak_hold_release_soc=75.0, sun_refills_pack=False)
    base.update(kw)
    return _house(**base)


# ── the WHEN ─────────────────────────────────────────────────────────

class TestTheSwitchIsOffByDefault:
    def test_it_ships_off(self):
        assert PERSISTED_FLAG_DEFAULTS["battery_peak_hold_enabled"] is False

    @pytest.mark.parametrize("level", ["flat", "cheap", "negative", "normal",
                                       "expensive", "no_prices", None])
    @pytest.mark.parametrize("sink", [False, True])
    def test_off_every_verdict_is_what_it_was(self, level, sink):
        """Inert: with the switch off the new inputs change nothing, whatever
        they say."""
        before = _house(tariff_level=level, house_sink_enabled=sink)
        after = _house(tariff_level=level, house_sink_enabled=sink,
                       peak_hold_enabled=False, peak_limit_set=True,
                       pack_soc=10.0, sun_refills_pack=True,
                       peak_hold_released=True)
        assert (after.state, after.reason) == (before.state, before.reason)
        assert peak_hold_state(after) == ""


class TestWhenItHolds:
    @pytest.mark.parametrize("level", ["flat", "normal", "no_prices", None])
    def test_it_holds_on_a_tariff_with_no_cheap_hour(self, level):
        v = _on(tariff_level=level)
        assert v.state == HELD and peak_hold_state(v) == "held"
        assert v.reason_code == RC.BATTERY_PEAK_HOLD

    def test_no_limit_is_nothing_to_hold_at(self):
        v = _on(peak_limit_set=False)
        assert v.state == OPEN and peak_hold_state(v) == "no_limit"

    def test_a_dear_hour_gets_the_pack(self):
        v = _on(tariff_level="expensive")
        assert v.state == OPEN and peak_hold_state(v) == "dear_hour"

    def test_a_level_nobody_read_does_not_hold(self):
        v = _on(pack_soc=None)
        assert v.state == OPEN and peak_hold_state(v) == "unread"

    def test_a_cheap_hour_with_the_house_sink_on_keeps_its_own_words(self):
        v = _on(tariff_level="cheap", house_sink_enabled=True)
        assert v.state == HELD and peak_hold_state(v) == ""
        assert "cheap hour" in v.reason


class TestWhenItLetsGo:
    def test_a_high_pack_the_sun_refills_covers_the_house(self):
        v = _on(pack_soc=75.0, sun_refills_pack=True)
        assert v.state == OPEN and peak_hold_state(v) == "released"

    def test_a_high_pack_with_no_sun_coming_is_kept(self):
        assert _on(pack_soc=98.0, sun_refills_pack=False).state == HELD

    def test_a_low_pack_is_kept_even_with_sun_coming(self):
        assert _on(pack_soc=74.0, sun_refills_pack=True).state == HELD

    def test_once_let_go_it_stays_so_for_a_band(self):
        low = 75.0 - PEAK_HOLD_RELEASE_BAND_SOC
        assert _on(pack_soc=low, sun_refills_pack=True,
                   peak_hold_released=True).state == OPEN
        assert _on(pack_soc=low - 1.0, sun_refills_pack=True,
                   peak_hold_released=True).state == HELD
        assert _on(pack_soc=low, sun_refills_pack=True,
                   peak_hold_released=False).state == HELD


# ── the HOW MUCH: the branch that was there ──────────────────────────

PEAK_HELD = _on()


def _view(*, home_w=5000.0, solar_w=2000.0, allowed_w=2500.0, soc=80.0,
          ev=False, degraded=False, verdict=PEAK_HELD, mode="auto",
          sched=None, window=False, max_w=MAX_W):
    fleet = FleetContext(
        solar_w=solar_w, home_w=home_w, battery_soc=soc,
        battery_soc_known=True, battery_count=1,
        peak_slot_allowed_w=allowed_w,
        inputs_degraded=degraded, dark_inputs=(("grid",) if degraded else ()),
        battery_assist_min_surplus_w=1200.0)
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": max_w, "battery_mode": mode,
                "battery_discharge_protection_enabled": True,
                "battery_morning_drain_floor_soc": 50.0},
        fleet=fleet, charging_state="idle", ev_charging=ev, ev_connected=ev,
        home_consumption_w=home_w, scheduler_decision=sched,
        sink_verdicts={"house": verdict} if verdict else {},
        morning_window_open=window)


class TestHisExample:
    def test_house_5_sun_2_limit_2_5_the_pack_gives_half_a_kilowatt(self):
        d = decide_battery(_view())
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(500.0)
        assert d.reason_code == RC.BATTERY_PEAK_HOLD_COVER
        assert d.reason.startswith("peak hold")

    def test_a_house_under_the_limit_keeps_the_whole_pack(self):
        d = decide_battery(_view(home_w=3000.0))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(0.0)
        assert d.reason_code == RC.BATTERY_PEAK_HOLD

    def test_the_cheap_hour_hold_keeps_its_own_words_and_codes(self):
        cheap = SinkVerdict("house", HELD, "cheap hour")
        d = decide_battery(_view(verdict=cheap))
        assert d.reason.startswith("house sink held")
        assert d.reason_code == RC.BATTERY_HOUSE_HELD_PEAK


class TestWhatItGivesWayTo:
    def test_a_charging_car_is_the_car_clamps_to_judge(self):
        """The reverted build pinned the pack while a car pushed the meter
        over. A charging car takes the hold out of the decision: what the
        pack does then is what it does with the switch off."""
        with_hold = decide_battery(_view(ev=True, home_w=1500.0, solar_w=5000.0))
        without = decide_battery(_view(ev=True, home_w=1500.0, solar_w=5000.0,
                                       verdict=None))
        assert (with_hold.intent, with_hold.discharge_limit_w,
                with_hold.reason_code) == (
            without.intent, without.discharge_limit_w, without.reason_code)
        assert not with_hold.reason.startswith("peak hold")

    def test_the_reserve_is_not_spent_on_a_peak(self):
        d = decide_battery(_view(soc=20.0))
        assert d.discharge_limit_w == pytest.approx(0.0)
        assert "reserve" in d.reason

    def test_a_house_nobody_measured_is_not_held(self):
        d = decide_battery(_view(degraded=True))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert d.discharge_limit_w == pytest.approx(MAX_W)
        assert d.reason_code == RC.BATTERY_HOUSE_BLIND

    def test_mode_off_is_hands_off(self):
        d = decide_battery(_view(mode="off"))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE

    def test_a_morning_window_spends_the_pack_into_the_car(self):
        d = decide_battery(_view(window=True, soc=80.0))
        assert d.intent is BatteryIntent.NORMAL
        assert d.reason_code == RC.BATTERY_FEEDS_CAR

    def test_the_schedulers_forced_charge_comes_first(self):
        sched = SimpleNamespace(
            state=SimpleNamespace(value="scheduled"), price_forced=True,
            from_arbitrage=False, from_forecast_spend=False,
            charge_power_w=3000.0, target_soc=90.0, duration_min=60,
            reason="negative price")
        d = decide_battery(_view(sched=sched))
        assert d.intent in (BatteryIntent.FORCE_CHARGE,
                            BatteryIntent.STOP_FORCE_CHARGE)
        assert not d.reason.startswith("peak hold")
        assert d.reason_code not in (RC.BATTERY_PEAK_HOLD,
                                     RC.BATTERY_PEAK_HOLD_COVER)


# ── fifteen minutes on the wire ──────────────────────────────────────

class _Adapter:
    """What ``actuate_battery`` talks to, counting the writes that change
    the limit — the adapter drops a repeat of the same value itself."""

    def __init__(self):
        self.last_intent = BatteryIntent.NORMAL
        self.last_discharge_limit_w = None
        self._limit_lower_streak = 0
        self.writes = []

    async def command_limit_discharge(self, watts):
        if self.last_discharge_limit_w != watts:
            self.writes.append(watts)
        self.last_discharge_limit_w = watts
        self.last_intent = BatteryIntent.LIMIT_DISCHARGE

    async def command_normal(self):   # pragma: no cover — not on this path
        self.last_intent = BatteryIntent.NORMAL
        self.last_discharge_limit_w = None


def _house_w(t):
    """A house on a hob: 3 kW base, 6 kW bursts, a kettle on top."""
    w = 3000.0
    if 120 <= t < 300 or 520 <= t < 700:
        w = 6000.0
    if 400 <= t < 460:
        w += 2000.0
    return w


@pytest.mark.asyncio
async def test_a_quarter_hour_stays_under_the_limit_without_a_write_storm():
    adapter, tracker = _Adapter(), PeakSlotTracker()
    solar_w, import_w = 500.0, 0.0
    for t in range(0, 900, 10):
        now = NOW + timedelta(seconds=t)
        tracker.update(now, import_w)
        allowed = slot_allowed_import_w(LIMIT_KW, tracker.imported_kwh,
                                        tracker.elapsed_s, blind=tracker.blind)
        home = _house_w(t)
        d = decide_battery(_view(home_w=home, solar_w=solar_w,
                                 allowed_w=allowed, max_w=9000.0))
        await actuate_battery(d, adapter)
        gap = max(0.0, home - solar_w)
        import_w = gap - min(gap, adapter.last_discharge_limit_w or 0.0)
    tracker.update(NOW + timedelta(seconds=899), import_w)
    assert tracker.imported_kwh <= LIMIT_KW * 0.25 + 0.01, "the slot went over"
    assert tracker.imported_kwh >= LIMIT_KW * 0.25 * 0.6, "the pack paid for the house"
    assert len(adapter.writes) <= 12, adapter.writes


@pytest.mark.asyncio
async def test_observer_mode_sends_nothing_and_says_what_it_would():
    adapter = _Adapter()
    said = []
    controller = SimpleNamespace(
        publish_observer_decision=lambda **kw: said.append(kw))
    await actuate_battery(decide_battery(_view()), adapter, observer=True,
                          controller=controller)
    assert adapter.writes == []
    assert said and said[0]["action"] == "limit_discharge"
    assert said[0]["power_w"] == pytest.approx(500.0)
    assert said[0]["reason"].startswith("peak hold")


# ── the wiring ───────────────────────────────────────────────────────

def test_the_coordinator_asks_with_what_it_already_reads():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )
    fn = SEMCoordinator._build_fleet_cycle_state
    assert calls(fn, "_slot_ceiling_kw")          # the limit in force
    assert calls(fn, "_sun_refills_whole_pack")   # the forecast
    assert calls(fn, "_peak_hold_pack_soc")       # the level, or unread


def test_the_refill_reads_no_forecast_as_no():
    from custom_components.solar_energy_management.coordinator.coordinator import (
        SEMCoordinator,
    )

    def _c(remaining, tomorrow, cap=10.0):
        return SimpleNamespace(
            _forecast_reader=SimpleNamespace(forecast_data=SimpleNamespace(
                forecast_remaining_today_kwh=remaining,
                forecast_tomorrow_kwh=tomorrow)),
            battery_capacity_kwh=cap, config={"battery_reserve_soc": 20.0})

    f = SEMCoordinator._sun_refills_whole_pack
    assert f(_c(0.0, 0.0)) is False
    assert f(_c(0.0, 7.9)) is False
    assert f(_c(0.0, 8.0)) is True
    assert f(_c(9.0, 0.0)) is True
    assert f(_c(9.0, 9.0, cap=0.0)) is False
    assert SEMCoordinator._peak_hold_pack_soc(
        SimpleNamespace(battery_soc=55.0, battery_soc_unavailable=True)) is None
    assert SEMCoordinator._peak_hold_pack_soc(
        SimpleNamespace(battery_soc=55.0, battery_soc_unavailable=False)) == 55.0
