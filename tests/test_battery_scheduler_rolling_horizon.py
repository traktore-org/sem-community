"""Tests for the battery scheduler soundness rework.

Covers the four improvements shipped together:
1. Break-even prices derived from the actual day-ahead series
   (``get_charge_window_rate`` / ``get_next_daytime_rate``) instead of
   sampling today's already-past 02:00/14:00 slots — plus the None-rate
   crash guard in ``evaluate()``.
2. Slot-granularity-aware ``find_cheapest_hours`` (hours → 15/30/60-min
   slots) and block-mode (``prefer_consecutive``) wiring from the
   scheduler config.
3. Re-plan on day-ahead price updates via ``price_series_fingerprint``.
4. Rolling-horizon trigger: first evaluation at the window open
   (trigger hour), then re-evaluation every ``replan_interval_min``
   until the window closes.
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    BatteryChargeAdapter,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
    SchedulerDecision,
    SchedulerState,
)
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
)


DT_UTIL_PATH = "custom_components.solar_energy_management.tariff.tariff_provider.dt_util"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _provider_with_series(price_seq, slot_minutes=60, start=None):
    """DynamicTariffProvider with a stubbed price series.

    ``start`` defaults to the top of the NEXT hour so every slot is in
    the future regardless of the real wall-clock minute (15-min slots
    at the top of the current hour would already be in the past).
    """
    if start is None:
        start = dt_util.now().replace(
            minute=0, second=0, microsecond=0
        ) + timedelta(hours=1)
    prices = [
        PricePoint(
            timestamp=start + timedelta(minutes=slot_minutes * i),
            price=p,
            level=PriceLevel.NORMAL,
        )
        for i, p in enumerate(price_seq)
    ]
    prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
    prov._read_prices_list = lambda: prices
    return prov, start


def _make_scheduler(scheduler_config, adapter=None):
    if adapter is None:
        adapter = MagicMock(spec=BatteryChargeAdapter)  # unused since #624
        adapter.is_active = False
        adapter.stop_forced_charge = AsyncMock()
    return BatteryChargeScheduler(MagicMock(), scheduler_config)


@pytest.fixture
def scheduler_config():
    return SchedulerConfig(
        enabled=True,
        battery_capacity_kwh=10.0,
        battery_usable_capacity_kwh=9.5,
        battery_max_charge_power_w=5000.0,
        roundtrip_efficiency=0.92,
        battery_cycle_cost=0.0,
        trigger_hour=21,
        trigger_minute=0,
        min_deficit_kwh=2.0,
        forecast_confidence=0.8,
        max_target_soc=95.0,
        pessimism_weight=0.3,
        replan_interval_min=30,
        planning_window_hours=9,
        prefer_consecutive_window=True,
    )


def _local(hour, minute=0, day_offset=0):
    """A tz-aware local datetime at the given wall-clock time."""
    return (dt_util.now() + timedelta(days=day_offset)).replace(
        hour=hour, minute=minute, second=0, microsecond=0
    )


# ---------------------------------------------------------------------------
# 1. find_cheapest_hours — slot granularity
# ---------------------------------------------------------------------------

class TestSlotGranularity:
    """hours_needed / within_hours are HOURS, converted per slot interval."""

    def test_hourly_market_two_hours_two_slots(self):
        prov, _ = _provider_with_series([0.3, 0.1, 0.3, 0.1, 0.3, 0.1])
        slots = prov.find_cheapest_hours(2, within_hours=12)
        assert len(slots) == 2
        assert all(p.price == 0.1 for p in slots)

    def test_15min_market_one_hour_four_slots(self):
        prov, _ = _provider_with_series(
            [0.30, 0.05, 0.25, 0.02, 0.40, 0.08, 0.50, 0.04],
            slot_minutes=15,
        )
        slots = prov.find_cheapest_hours(1, within_hours=12)
        assert len(slots) == 4
        assert sorted(p.price for p in slots) == [0.02, 0.04, 0.05, 0.08]

    def test_15min_market_consecutive_block_is_contiguous(self):
        # Cheapest contiguous 8-slot (2 h) run is at the tail.
        prov, _ = _provider_with_series(
            [0.5] * 8 + [0.1] * 8,
            slot_minutes=15,
        )
        block = prov.find_cheapest_hours(2, within_hours=12, prefer_consecutive=True)
        assert len(block) == 8
        deltas = [
            (block[i + 1].timestamp - block[i].timestamp).total_seconds()
            for i in range(len(block) - 1)
        ]
        assert all(d == 900 for d in deltas)
        assert all(p.price == 0.1 for p in block)

    def test_fractional_hours_round_up_to_slots(self):
        prov, _ = _provider_with_series([0.3, 0.1, 0.3, 0.1])
        # 1.2 h on an hourly market needs 2 slots
        assert len(prov.find_cheapest_hours(1.2, within_hours=12)) == 2
        # 0.5 h on an hourly market needs 1 slot
        assert len(prov.find_cheapest_hours(0.5, within_hours=12)) == 1

    def test_fractional_hours_on_15min_market(self):
        prov, _ = _provider_with_series([0.3, 0.1, 0.3, 0.1, 0.2, 0.2], slot_minutes=15)
        # 0.5 h on a 15-min market needs 2 slots
        assert len(prov.find_cheapest_hours(0.5, within_hours=12)) == 2

    def test_within_hours_is_time_based_not_slot_count(self):
        # 24 h of 15-min slots; the absolute cheapest slot sits 6 h out.
        # A 2 h lookahead must NOT see it (the old code sliced [:within]
        # slots, i.e. 3 h of 15-min data for within_hours=12).
        seq = [0.30] * 96
        seq[24] = 0.01  # 6 h out
        seq[2] = 0.10   # 30 min out — cheapest within the 2 h horizon
        prov, _ = _provider_with_series(seq, slot_minutes=15)
        slots = prov.find_cheapest_hours(0.25, within_hours=2)
        assert len(slots) == 1
        assert slots[0].price == 0.10

    def test_zero_hours_returns_empty(self):
        prov, _ = _provider_with_series([0.3, 0.1, 0.3])
        assert prov.find_cheapest_hours(0, within_hours=12) == []

    def test_fewer_slots_than_needed_returns_all(self):
        prov, _ = _provider_with_series([0.3, 0.1])
        slots = prov.find_cheapest_hours(6, within_hours=12)
        assert len(slots) == 2


# ---------------------------------------------------------------------------
# 1b. Break-even rate derivation
# ---------------------------------------------------------------------------

class TestChargeWindowRate:
    def test_mean_of_cheapest_hours(self):
        prov, _ = _provider_with_series(
            [0.30, 0.10, 0.30, 0.12, 0.30, 0.14, 0.30, 0.16, 0.30, 0.30]
        )
        rate = prov.get_charge_window_rate(hours=4.0, within_hours=12)
        assert rate == pytest.approx((0.10 + 0.12 + 0.14 + 0.16) / 4)

    def test_none_without_price_data(self):
        prov, _ = _provider_with_series([])
        assert prov.get_charge_window_rate() is None

    def test_15min_market_uses_slot_count(self):
        prov, _ = _provider_with_series([0.4, 0.1, 0.1, 0.1, 0.1, 0.4], slot_minutes=15)
        rate = prov.get_charge_window_rate(hours=1.0, within_hours=12)
        assert rate == pytest.approx(0.1)


class TestNextDaytimeRate:
    def _prov_at(self, now, points):
        """Provider with explicit (datetime, price) points and frozen now."""
        prices = [
            PricePoint(timestamp=ts, price=p, level=PriceLevel.NORMAL)
            for ts, p in points
        ]
        prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
        prov._read_prices_list = lambda: prices
        return prov

    def test_evening_uses_tomorrows_daytime(self):
        now = datetime(2026, 6, 9, 21, 0)
        points = (
            # Tonight (excluded: not daytime)
            [(datetime(2026, 6, 9, 22 + i, 0), 0.05) for i in range(2)]
            # Tomorrow daytime 07-20 (included)
            + [(datetime(2026, 6, 10, 7 + i, 0), 0.30 + 0.01 * i) for i in range(3)]
            # Tomorrow late evening (excluded)
            + [(datetime(2026, 6, 10, 21, 0), 0.05)]
        )
        prov = self._prov_at(now, points)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.as_local = lambda ts: ts
            rate = prov.get_next_daytime_rate()
        assert rate == pytest.approx((0.30 + 0.31 + 0.32) / 3)

    def test_after_midnight_uses_todays_daytime(self):
        now = datetime(2026, 6, 10, 2, 0)
        points = (
            [(datetime(2026, 6, 10, 3, 0), 0.08)]  # night, excluded
            + [(datetime(2026, 6, 10, 10, 0), 0.40)]
            + [(datetime(2026, 6, 10, 14, 0), 0.20)]
        )
        prov = self._prov_at(now, points)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.as_local = lambda ts: ts
            rate = prov.get_next_daytime_rate()
        assert rate == pytest.approx(0.30)

    def test_past_slots_are_ignored(self):
        now = datetime(2026, 6, 10, 21, 0)
        # Only TODAY's (past) daytime is known — tomorrow not published.
        points = [(datetime(2026, 6, 10, 7 + i, 0), 0.50) for i in range(13)]
        prov = self._prov_at(now, points)
        with patch(DT_UTIL_PATH) as mock_dt:
            mock_dt.now.return_value = now
            mock_dt.as_local = lambda ts: ts
            assert prov.get_next_daytime_rate() is None

    def test_none_without_price_data(self):
        prov = self._prov_at(datetime(2026, 6, 10, 21, 0), [])
        assert prov.get_next_daytime_rate() is None


class TestPriceFingerprint:
    def test_stable_for_unchanged_series(self):
        prov, _ = _provider_with_series([0.1, 0.2, 0.3])
        assert prov.price_series_fingerprint() == prov.price_series_fingerprint()

    def test_changes_when_a_price_changes(self):
        prov_a, start = _provider_with_series([0.1, 0.2, 0.3])
        prov_b, _ = _provider_with_series([0.1, 0.25, 0.3], start=start)
        assert prov_a.price_series_fingerprint() != prov_b.price_series_fingerprint()

    def test_changes_when_day_ahead_extends(self):
        prov_a, start = _provider_with_series([0.1, 0.2])
        prov_b, _ = _provider_with_series([0.1, 0.2, 0.3], start=start)
        assert prov_a.price_series_fingerprint() != prov_b.price_series_fingerprint()

    def test_none_when_empty(self):
        prov, _ = _provider_with_series([])
        assert prov.price_series_fingerprint() is None


# ---------------------------------------------------------------------------
# 2. Scheduler — None-rate guard + cheapest-window request shape
# ---------------------------------------------------------------------------

class TestSchedulerPriceGuard:
    def test_none_off_peak_rate_is_not_profitable_not_a_crash(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=2.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=None,
            peak_rate=0.30,
            correction_factor=1.0,
        )
        assert decision.state == SchedulerState.NOT_PROFITABLE
        assert "Price data unavailable" in decision.reason

    def test_none_peak_rate_is_not_profitable_not_a_crash(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=2.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=None,
            correction_factor=1.0,
        )
        assert decision.state == SchedulerState.NOT_PROFITABLE

    def test_negative_price_override_works_without_rates(self, scheduler_config):
        """The negative-price branch precedes the break-even, so a missing
        rate pair must not block free charging."""
        scheduler = _make_scheduler(scheduler_config)
        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=10.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=None,
            peak_rate=None,
            correction_factor=1.0,
            current_price=-0.05,
        )
        assert decision.state == SchedulerState.SCHEDULED
        assert decision.target_soc == scheduler_config.max_target_soc


class TestCheapestWindowRequest:
    def _evaluate(self, scheduler, provider):
        return scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=2.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            tariff_provider=provider,
            correction_factor=1.0,
        )

    def test_prefer_consecutive_follows_config_default_on(self, scheduler_config):
        provider = MagicMock()
        provider.find_cheapest_hours.return_value = []
        scheduler = _make_scheduler(scheduler_config)
        self._evaluate(scheduler, provider)
        kwargs = provider.find_cheapest_hours.call_args.kwargs
        assert kwargs["prefer_consecutive"] is True

    def test_prefer_consecutive_follows_config_off(self, scheduler_config):
        scheduler_config.prefer_consecutive_window = False
        provider = MagicMock()
        provider.find_cheapest_hours.return_value = []
        scheduler = _make_scheduler(scheduler_config)
        self._evaluate(scheduler, provider)
        kwargs = provider.find_cheapest_hours.call_args.kwargs
        assert kwargs["prefer_consecutive"] is False

    def test_fractional_hours_requested_not_rounded(self, scheduler_config):
        """A 1.2 h charge must request 1.2 h of slots, not a pre-rounded 2."""
        scheduler_config.battery_max_charge_power_w = 5000.0
        provider = MagicMock()
        provider.find_cheapest_hours.return_value = []
        scheduler = _make_scheduler(scheduler_config)
        # deficit 3.0 kWh (consumption 3, forecast 0) → target_soc raise
        # of 3/9.5 → charge 3.0 kWh at 5 kW = 0.6 h requested
        scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=0.0,
            expected_consumption_kwh=3.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            tariff_provider=provider,
            correction_factor=1.0,
            forecast_available=False,
        )
        hours_requested = provider.find_cheapest_hours.call_args.args[0]
        assert hours_requested == pytest.approx(0.6)

    def test_15min_slots_produce_15min_schedule(self, scheduler_config):
        """Slot length flows from the price points into the plan."""
        start = dt_util.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
        points = [
            MagicMock(timestamp=start + timedelta(minutes=15 * i), price=0.05)
            for i in range(8)  # 2 h of 15-min slots
        ]
        provider = MagicMock()
        provider.find_cheapest_hours.return_value = points
        # #485 F3: the market interval now comes from the provider
        # (selected-slot gap inference remains the fallback only).
        provider.detect_slot_hours.return_value = 0.25
        scheduler = _make_scheduler(scheduler_config)
        decision = self._evaluate(scheduler, provider)

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.schedule is not None
        durations = {
            (s.end - s.start).total_seconds() for s in decision.schedule.slots
        }
        assert durations == {900.0}
        # Energy accounting follows the slot duration: 5 kW × 0.25 h
        first = decision.schedule.slots[0]
        assert first.battery_energy_kwh == pytest.approx(
            first.battery_power_w / 1000 * 0.25
        )

    def test_15min_slot_power_cap_scales_with_duration(self, scheduler_config):
        """The 'don't overshoot' cap must deliver the remaining energy
        within ONE slot: 1 kWh left in a 15-min slot needs 4 kW, not
        1 kW (which would stop the plan after a quarter of the energy).
        Mirrors the fix on the tariff & pricing review branch."""
        start = dt_util.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=3)
        points = [
            MagicMock(timestamp=start + timedelta(minutes=15 * i), price=0.05)
            for i in range(8)
        ]
        scheduler = _make_scheduler(scheduler_config)
        schedule = scheduler._plan_night_schedule(
            battery_kwh_needed=1.0,
            ev_kwh_needed=0.0,
            ev_max_power_w=0.0,
            cheapest_prices=points,
            now=dt_util.now(),
        )
        assert len(schedule.slots) == 1
        assert schedule.slots[0].battery_power_w == pytest.approx(4000, abs=1)
        assert schedule.total_battery_kwh == pytest.approx(1.0, abs=0.01)


# ---------------------------------------------------------------------------
# 3. Re-plan on price updates
# ---------------------------------------------------------------------------

class TestPriceUpdateReplan:
    def _scheduled(self, scheduler_config, state=SchedulerState.SCHEDULED, fp=111):
        scheduler = _make_scheduler(scheduler_config)
        scheduler._decision = SchedulerDecision(state=state, target_soc=80.0)
        scheduler._planned_soc = 50.0
        scheduler._price_fingerprint = fp
        # An evaluation has notionally run (#485 F2: should_replan
        # short-circuits while a re-plan is pending / pre-first-eval).
        scheduler._last_evaluation_date = dt_util.now()
        return scheduler

    def test_changed_fingerprint_triggers_replan(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config)
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is True

    def test_same_fingerprint_no_replan(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config)
        assert scheduler.should_replan(50.0, False, price_fingerprint=111) is False

    def test_price_change_revisits_not_profitable_verdict(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config, state=SchedulerState.NOT_PROFITABLE)
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is True

    def test_price_change_revisits_not_needed_verdict(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config, state=SchedulerState.NOT_NEEDED)
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is True

    def test_price_change_ignored_after_target_reached(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config, state=SchedulerState.TARGET_REACHED)
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is False

    def test_no_stored_fingerprint_static_tariff_no_replan(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config, fp=None)
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is False

    def test_no_fingerprint_argument_keeps_legacy_behavior(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config)
        # SOC drift still triggers
        assert scheduler.should_replan(58.0, False) is True
        assert scheduler.should_replan(51.0, False) is False

    def test_evaluate_captures_fingerprint_from_provider(self, scheduler_config):
        provider = MagicMock()
        provider.find_cheapest_hours.return_value = []
        provider.price_series_fingerprint.return_value = 12345
        scheduler = _make_scheduler(scheduler_config)
        scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=2.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            tariff_provider=provider,
            correction_factor=1.0,
        )
        assert scheduler._price_fingerprint == 12345

    def test_reset_clears_fingerprint(self, scheduler_config):
        scheduler = self._scheduled(scheduler_config)
        scheduler.reset()
        assert scheduler._price_fingerprint is None


# ---------------------------------------------------------------------------
# 4. Rolling-horizon trigger
# ---------------------------------------------------------------------------

class TestRollingHorizonTrigger:
    def test_disabled_never_triggers(self, scheduler_config):
        scheduler_config.enabled = False
        scheduler = _make_scheduler(scheduler_config)
        assert scheduler.should_trigger_evaluation(_local(21, 0)) is False

    def test_no_trigger_before_window(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        # 15:00 — outside 21:00→06:00 even with no evaluation yet
        assert scheduler.should_trigger_evaluation(_local(15, 0)) is False

    def test_first_evaluation_at_window_open(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        assert scheduler.should_trigger_evaluation(_local(21, 0)) is True

    def test_startup_inside_window_triggers_immediately(self, scheduler_config):
        """Integration restart at 23:00 must not miss tonight's plan
        (legacy only triggered at the exact trigger minute)."""
        scheduler = _make_scheduler(scheduler_config)
        assert scheduler.should_trigger_evaluation(_local(23, 17)) is True

    def test_no_retrigger_before_interval(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        scheduler._last_evaluation_date = _local(21, 0)
        assert scheduler.should_trigger_evaluation(_local(21, 20)) is False

    def test_retriggers_after_interval(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        scheduler._last_evaluation_date = _local(21, 0)
        assert scheduler.should_trigger_evaluation(_local(21, 30)) is True

    def test_rolls_across_midnight(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        # Evaluated yesterday 23:50; now 00:30 — same window, 40 min elapsed
        now = _local(0, 30)
        scheduler._last_evaluation_date = now - timedelta(minutes=40)
        assert scheduler.should_trigger_evaluation(now) is True
        # ...but not 10 minutes after the last evaluation
        scheduler._last_evaluation_date = now - timedelta(minutes=10)
        assert scheduler.should_trigger_evaluation(now) is False

    def test_window_closes_after_planning_hours(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        # 21:00 + 9 h = 06:00 — 06:30 is outside
        scheduler._last_evaluation_date = _local(2, 0)
        assert scheduler.should_trigger_evaluation(_local(6, 30)) is False

    def test_armed_replan_triggers_next_cycle_in_window(self, scheduler_config):
        """should_replan() arms via _last_evaluation_date = None; the next
        coordinator cycle inside the window must evaluate (the legacy code
        armed it but only re-evaluated at the next day's trigger minute)."""
        scheduler = _make_scheduler(scheduler_config)
        scheduler._last_evaluation_date = None
        assert scheduler.should_trigger_evaluation(_local(23, 45)) is True

    def test_armed_replan_outside_window_waits(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        scheduler._last_evaluation_date = None
        assert scheduler.should_trigger_evaluation(_local(12, 0)) is False

    def test_stale_evaluation_from_previous_window_triggers(self, scheduler_config):
        """An evaluation from last night's window does not satisfy tonight's."""
        scheduler = _make_scheduler(scheduler_config)
        scheduler._last_evaluation_date = _local(23, 0, day_offset=-1)
        assert scheduler.should_trigger_evaluation(_local(21, 0)) is True

    def test_custom_trigger_hour_shifts_window(self, scheduler_config):
        scheduler_config.trigger_hour = 22
        scheduler_config.planning_window_hours = 8  # 22:00 → 06:00
        scheduler = _make_scheduler(scheduler_config)
        assert scheduler.should_trigger_evaluation(_local(21, 30)) is False
        assert scheduler.should_trigger_evaluation(_local(22, 0)) is True


# ---------------------------------------------------------------------------
# Config plumbing
# ---------------------------------------------------------------------------

class TestSchedulerConfigRework:
    def test_new_defaults(self):
        config = SchedulerConfig.from_config({})
        # Runtime fallback stays 0.0 so upgrading installs that never
        # set the key keep their pre-v1.7.3 break-even (#485 F5); the
        # 0.02 suggestion lives in the config-flow form default only.
        assert config.battery_cycle_cost == 0.0
        assert config.replan_interval_min == 30
        assert config.planning_window_hours == 9
        assert config.prefer_consecutive_window is True

    def test_replan_interval_clamped_to_minimum(self):
        config = SchedulerConfig.from_config({"battery_replan_interval_min": 1})
        assert config.replan_interval_min == 5

    def test_planning_window_clamped(self):
        assert SchedulerConfig.from_config(
            {"battery_planning_window_hours": 30}
        ).planning_window_hours == 24
        assert SchedulerConfig.from_config(
            {"battery_planning_window_hours": 0}
        ).planning_window_hours == 1

    def test_custom_values_pass_through(self):
        config = SchedulerConfig.from_config({
            "battery_cycle_cost": 0.067,
            "battery_replan_interval_min": 15,
            "battery_planning_window_hours": 10,
            "battery_prefer_consecutive_window": False,
        })
        assert config.battery_cycle_cost == pytest.approx(0.067)
        assert config.replan_interval_min == 15
        assert config.planning_window_hours == 10
        assert config.prefer_consecutive_window is False

    def test_cycle_cost_zero_still_allowed(self):
        config = SchedulerConfig.from_config({"battery_cycle_cost": 0.0})
        assert config.battery_cycle_cost == 0.0


# ---------------------------------------------------------------------------
# Coordinator rate derivation (integration-style)
# ---------------------------------------------------------------------------

from custom_components.solar_energy_management.coordinator import SEMCoordinator

COORD_DT_PATH = "custom_components.solar_energy_management.coordinator.coordinator.dt_util"


def _build_rate_coordinator(provider, now, forecast_today=4.0, forecast_tomorrow=8.0):
    """Minimal coordinator harness around _maybe_run_scheduler_evaluation."""
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)

    scheduler = MagicMock()
    scheduler.should_trigger_evaluation = MagicMock(return_value=True)
    coord._battery_charge_scheduler = scheduler

    forecast = MagicMock()
    forecast.available = True
    forecast.forecast_today_kwh = forecast_today
    forecast.forecast_tomorrow_kwh = forecast_tomorrow
    forecast.last_update = now - timedelta(hours=1)
    coord._forecast_reader = MagicMock()
    coord._forecast_reader.read_forecast = MagicMock(return_value=forecast)

    coord._forecast_tracker = MagicMock(correction_factor=1.0)
    coord._predictor = MagicMock()
    coord._predictor.predict_consumption_today_kwh = MagicMock(return_value=12.0)
    coord._tariff_provider = provider
    coord._ev_devices = {}
    coord.config = {
        "electricity_off_peak_rate": 0.22,
        "electricity_import_rate": 0.30,
    }
    return coord, scheduler


class TestCoordinatorRateDerivation:
    async def test_dynamic_provider_rates_come_from_series(self):
        now = _local(21, 0)
        provider = MagicMock()
        provider.get_charge_window_rate = MagicMock(return_value=0.11)
        provider.get_next_daytime_rate = MagicMock(return_value=0.33)
        provider.get_price_at = MagicMock(return_value=0.99)  # must NOT be used
        provider.price_series_fingerprint = MagicMock(return_value=1)
        provider.find_cheapest_hours = MagicMock(return_value=[])
        coord, scheduler = _build_rate_coordinator(provider, now)

        with patch(COORD_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            await coord._maybe_run_scheduler_evaluation(MagicMock(battery_soc=50.0))

        kwargs = scheduler.evaluate.call_args.kwargs
        assert kwargs["off_peak_rate"] == pytest.approx(0.11)
        assert kwargs["peak_rate"] == pytest.approx(0.33)
        provider.get_price_at.assert_not_called()

    async def test_dynamic_provider_without_data_falls_back_to_config(self):
        now = _local(21, 0)
        provider = MagicMock()
        provider.get_charge_window_rate = MagicMock(return_value=None)
        provider.get_next_daytime_rate = MagicMock(return_value=None)
        provider.get_price_at = MagicMock(return_value=None)
        provider.price_series_fingerprint = MagicMock(return_value=None)
        provider.find_cheapest_hours = MagicMock(return_value=[])
        coord, scheduler = _build_rate_coordinator(provider, now)

        with patch(COORD_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            await coord._maybe_run_scheduler_evaluation(MagicMock(battery_soc=50.0))

        kwargs = scheduler.evaluate.call_args.kwargs
        assert kwargs["off_peak_rate"] == pytest.approx(0.22)
        assert kwargs["peak_rate"] == pytest.approx(0.30)

    async def test_static_provider_uses_time_of_day_rates(self):
        now = _local(21, 0)
        provider = MagicMock(spec=["get_price_at", "find_cheapest_hours"])
        provider.get_price_at = MagicMock(side_effect=[0.18, 0.34])
        provider.find_cheapest_hours = MagicMock(return_value=[])
        coord, scheduler = _build_rate_coordinator(provider, now)

        with patch(COORD_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            await coord._maybe_run_scheduler_evaluation(MagicMock(battery_soc=50.0))

        kwargs = scheduler.evaluate.call_args.kwargs
        assert kwargs["off_peak_rate"] == pytest.approx(0.18)
        assert kwargs["peak_rate"] == pytest.approx(0.34)

    async def test_evening_evaluation_plans_for_tomorrow(self):
        now = _local(21, 0)
        provider = MagicMock()
        provider.get_charge_window_rate = MagicMock(return_value=0.11)
        provider.get_next_daytime_rate = MagicMock(return_value=0.33)
        provider.price_series_fingerprint = MagicMock(return_value=1)
        provider.find_cheapest_hours = MagicMock(return_value=[])
        coord, scheduler = _build_rate_coordinator(
            provider, now, forecast_today=4.0, forecast_tomorrow=8.0,
        )

        with patch(COORD_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            await coord._maybe_run_scheduler_evaluation(MagicMock(battery_soc=50.0))

        kwargs = scheduler.evaluate.call_args.kwargs
        assert kwargs["forecast_tomorrow_kwh"] == pytest.approx(8.0)

    async def test_after_midnight_evaluation_plans_for_today(self):
        now = _local(2, 0)
        provider = MagicMock()
        provider.get_charge_window_rate = MagicMock(return_value=0.11)
        provider.get_next_daytime_rate = MagicMock(return_value=0.33)
        provider.price_series_fingerprint = MagicMock(return_value=1)
        provider.find_cheapest_hours = MagicMock(return_value=[])
        coord, scheduler = _build_rate_coordinator(
            provider, now, forecast_today=4.0, forecast_tomorrow=8.0,
        )

        with patch(COORD_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            await coord._maybe_run_scheduler_evaluation(MagicMock(battery_soc=50.0))

        kwargs = scheduler.evaluate.call_args.kwargs
        assert kwargs["forecast_tomorrow_kwh"] == pytest.approx(4.0)

    async def test_replan_passes_price_fingerprint(self):
        now = _local(23, 0)
        provider = MagicMock()
        provider.price_series_fingerprint = MagicMock(return_value=777)
        coord, scheduler = _build_rate_coordinator(provider, now)
        scheduler.should_trigger_evaluation = MagicMock(return_value=False)
        scheduler.should_replan = MagicMock(return_value=True)

        with patch(COORD_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            await coord._maybe_run_scheduler_evaluation(
                MagicMock(battery_soc=50.0, ev_connected=False)
            )

        kwargs = scheduler.should_replan.call_args.kwargs
        assert kwargs["price_fingerprint"] == 777
        assert scheduler._last_evaluation_date is None
        scheduler.evaluate.assert_not_called()


# ---------------------------------------------------------------------------
# #485 pre-stable review batch (F1-F7)
# ---------------------------------------------------------------------------

SCHED_DT_PATH = (
    "custom_components.solar_energy_management.coordinator."
    "battery_charge_scheduler.dt_util"
)


def _stub_provider(fingerprint=1, cheapest=None, slot_hours=None):
    """Tariff-provider stub with the duck-typed scheduler surface."""
    prov = MagicMock()
    prov.price_series_fingerprint = MagicMock(return_value=fingerprint)
    prov.find_cheapest_hours = MagicMock(return_value=cheapest or [])
    prov.detect_slot_hours = MagicMock(return_value=slot_hours)
    return prov


class TestTargetSocAnchor:
    """#485 F1: re-evaluations must not ratchet the target with charge progress."""

    def _evaluate(self, scheduler, now, soc, provider=None):
        with patch(SCHED_DT_PATH) as mock_dt:
            mock_dt.now.return_value = now
            return scheduler.evaluate(
                current_soc=soc,
                forecast_tomorrow_kwh=8.0,
                expected_consumption_kwh=8.0,
                off_peak_rate=0.10,
                peak_rate=0.30,
                tariff_provider=provider,
            )

    def test_replan_keeps_anchor_target(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        first = self._evaluate(scheduler, _local(21, 5), soc=50.0)
        assert first.state == SchedulerState.SCHEDULED
        target_first = first.target_soc

        # 30 min later the battery has charged 50% → 60%; the target
        # must NOT grow by the charge progress.
        second = self._evaluate(scheduler, _local(21, 35), soc=60.0)
        assert second.state == SchedulerState.SCHEDULED
        assert second.target_soc == pytest.approx(target_first, abs=0.01)

    def test_new_window_re_anchors(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        first = self._evaluate(scheduler, _local(21, 5), soc=50.0)
        increase = first.target_soc - 50.0

        # Next night, battery starts at 60% → fresh anchor.
        nxt = self._evaluate(
            scheduler, _local(21, 5, day_offset=1), soc=60.0,
        )
        assert nxt.target_soc == pytest.approx(60.0 + increase, abs=0.01)

    def test_reset_clears_anchor(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        self._evaluate(scheduler, _local(21, 5), soc=50.0)
        scheduler.reset()
        assert scheduler._window_anchor_soc is None
        assert scheduler._window_anchor_at is None


class TestReplanTriggerOneShot:
    """#485 F2: price-update replan fires once per series change."""

    def _evaluated_scheduler(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        provider = _stub_provider(fingerprint=111)
        with patch(SCHED_DT_PATH) as mock_dt:
            mock_dt.now.return_value = _local(21, 5)
            scheduler.evaluate(
                current_soc=50.0,
                forecast_tomorrow_kwh=8.0,
                expected_consumption_kwh=8.0,
                off_peak_rate=0.10,
                peak_rate=0.30,
                tariff_provider=provider,
            )
        return scheduler

    def test_price_update_fires_once(self, scheduler_config):
        scheduler = self._evaluated_scheduler(scheduler_config)
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is True
        # Same updated series next cycle: consumed, no re-fire.
        assert scheduler.should_replan(50.0, False, price_fingerprint=222) is False
        # Another update fires again.
        assert scheduler.should_replan(50.0, False, price_fingerprint=333) is True

    def test_no_refire_while_replan_pending(self, scheduler_config):
        scheduler = self._evaluated_scheduler(scheduler_config)
        # Coordinator arms a re-plan by clearing the evaluation date.
        scheduler._last_evaluation_date = None
        assert scheduler.should_replan(50.0, False, price_fingerprint=999) is False

    def test_has_price_fingerprint_property(self, scheduler_config):
        scheduler = _make_scheduler(scheduler_config)
        assert scheduler.has_price_fingerprint is False
        scheduler._price_fingerprint = 42
        assert scheduler.has_price_fingerprint is True


class TestSlotHoursFromProvider:
    """#485 F3: slot length comes from the market, not from selected-slot gaps."""

    def test_scattered_15min_slots_use_provider_interval(self, scheduler_config):
        start = _local(22, 0)
        # Scattered 15-min picks 30 minutes apart — gap inference
        # would wrongly yield 0.5h slots.
        cheapest = [
            PricePoint(timestamp=start + timedelta(minutes=30 * i),
                       price=0.05, level=PriceLevel.CHEAP)
            for i in range(3)
        ]
        provider = _stub_provider(cheapest=cheapest, slot_hours=0.25)
        scheduler = _make_scheduler(scheduler_config)
        with patch(SCHED_DT_PATH) as mock_dt:
            mock_dt.now.return_value = _local(21, 5)
            decision = scheduler.evaluate(
                current_soc=50.0,
                forecast_tomorrow_kwh=8.0,
                expected_consumption_kwh=8.0,
                off_peak_rate=0.10,
                peak_rate=0.30,
                tariff_provider=provider,
            )
        assert decision.schedule is not None and decision.schedule.slots
        slot = decision.schedule.slots[0]
        assert (slot.end - slot.start) == timedelta(minutes=15)

    def test_gap_inference_still_used_without_hint(self, scheduler_config):
        start = _local(22, 0)
        cheapest = [
            PricePoint(timestamp=start + timedelta(minutes=15 * i),
                       price=0.05, level=PriceLevel.CHEAP)
            for i in range(4)
        ]
        provider = _stub_provider(cheapest=cheapest, slot_hours=None)
        scheduler = _make_scheduler(scheduler_config)
        with patch(SCHED_DT_PATH) as mock_dt:
            mock_dt.now.return_value = _local(21, 5)
            decision = scheduler.evaluate(
                current_soc=50.0,
                forecast_tomorrow_kwh=8.0,
                expected_consumption_kwh=8.0,
                off_peak_rate=0.10,
                peak_rate=0.30,
                tariff_provider=provider,
            )
        slot = decision.schedule.slots[0]
        assert (slot.end - slot.start) == timedelta(minutes=15)


class TestServicePriceBackoff:
    """#485 F6: failed Nord Pool service fetches back off instead of hammering."""

    def _provider_with_failing_service(self):
        hass = MagicMock()
        hass.services.has_service = MagicMock(return_value=True)
        hass.services.async_call = AsyncMock(side_effect=Exception("API down"))
        entry = MagicMock()
        entry.entry_id = "np_entry"
        hass.config_entries.async_entries = MagicMock(return_value=[entry])
        prov = DynamicTariffProvider(hass, price_entity=None)
        return prov, hass

    async def test_failed_fetch_backs_off(self):
        prov, hass = self._provider_with_failing_service()
        assert await prov.async_refresh_service_prices() is False
        calls_after_first = hass.services.async_call.await_count
        assert calls_after_first == 2  # today + tomorrow attempted

        # Immediately retried cycle: throttled, no new service calls.
        assert await prov.async_refresh_service_prices() is False
        assert hass.services.async_call.await_count == calls_after_first

    async def test_retry_after_backoff_window(self):
        prov, hass = self._provider_with_failing_service()
        await prov.async_refresh_service_prices()
        # Age the failure beyond the retry window.
        prov._service_prices_failed_at = (
            dt_util.now() - prov.SERVICE_PRICE_RETRY - timedelta(seconds=1)
        )
        await prov.async_refresh_service_prices()
        assert hass.services.async_call.await_count == 4


class TestPriceParseMemo:
    """#485 F7: _read_prices_list memoizes per entity-state change."""

    def _make_provider(self):
        hass = MagicMock()
        start = dt_util.now().replace(minute=0, second=0, microsecond=0)
        state = MagicMock()
        state.state = "0.20"
        state.last_updated = start
        state.attributes = {
            "raw_today": [
                {"start": (start + timedelta(hours=i)).isoformat(), "value": 0.2 + i * 0.01}
                for i in range(4)
            ]
        }
        hass.states.get = MagicMock(return_value=state)
        prov = DynamicTariffProvider(
            hass, price_entity="sensor.price", classification_mode="static",
        )
        return prov, hass, state

    def test_second_read_is_memo_hit(self):
        prov, hass, state = self._make_provider()
        first = prov._read_prices_list()
        assert len(first) == 4
        second = prov._read_prices_list()
        assert second is first  # same object → no reparse

    def test_entity_update_invalidates_memo(self):
        prov, hass, state = self._make_provider()
        first = prov._read_prices_list()

        new_state = MagicMock()
        new_state.state = "0.25"
        new_state.last_updated = state.last_updated + timedelta(minutes=5)
        new_state.attributes = state.attributes
        hass.states.get = MagicMock(return_value=new_state)

        second = prov._read_prices_list()
        assert second is not first
        assert len(second) == 4


class TestCfgRateFalsyZero:
    """#485 F4: a configured 0.0 rate is a value, not a missing key."""

    def test_zero_is_respected(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _cfg_rate,
        )
        assert _cfg_rate({"electricity_import_rate": 0.0},
                         "electricity_import_rate", default=0.30) == 0.0

    def test_missing_falls_back(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _cfg_rate,
        )
        assert _cfg_rate({}, "electricity_import_rate", default=0.30) == 0.30

    def test_chained_keys(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _cfg_rate,
        )
        assert _cfg_rate(
            {"electricity_nt_rate": 0.0},
            "electricity_off_peak_rate", "electricity_nt_rate", default=0.22,
        ) == 0.0

    def test_non_numeric_skipped(self):
        from custom_components.solar_energy_management.coordinator.coordinator import (
            _cfg_rate,
        )
        assert _cfg_rate({"electricity_import_rate": "abc"},
                         "electricity_import_rate", default=0.30) == 0.30
