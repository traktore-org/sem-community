"""Unit tests for the today's plan composer (#282)."""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.today_plan import (
    compose_today_plan,
    KIND_NOW,
    KIND_CHEAP_START,
    KIND_EXPENSIVE_START,
    KIND_EV_CHARGE_START,
    KIND_EV_MIN_REACHED,
    KIND_EV_DEADLINE,
    KIND_NIGHT_OPEN,
    KIND_SOLAR_PEAK,
)


# Use a fixed naive "now" for deterministic tests.
NOW = datetime(2026, 5, 28, 9, 0, 0)


def _prices(now: datetime, levels: list[tuple[int, str, float]]) -> list[dict]:
    """Build upcoming_prices list from (hour_offset, level, price) tuples."""
    return [
        {"t": (now + timedelta(hours=h)).isoformat(), "level": lvl, "price": p}
        for h, lvl, p in levels
    ]


class TestComposeTodayPlan:
    def test_now_row_always_present(self):
        plan = compose_today_plan(now=NOW)
        kinds = [r["kind"] for r in plan]
        assert KIND_NOW in kinds
        assert plan[0]["kind"] == KIND_NOW

    def test_horizon_clips_far_future_rows(self):
        # A cheap block 30h ahead must not appear within a 24h horizon.
        future = [(30, "cheap", 0.10), (31, "cheap", 0.10)]
        plan = compose_today_plan(
            now=NOW, horizon_hours=24,
            upcoming_prices=_prices(NOW, future),
        )
        assert not any(r["kind"] == KIND_CHEAP_START for r in plan)

    def test_cheap_block_emits_start_row(self):
        # 22:00-02:00 cheap window
        prices = _prices(NOW, [
            (13, "normal", 0.20), (14, "cheap", 0.10), (15, "cheap", 0.10),
            (16, "cheap", 0.12), (17, "normal", 0.20),
        ])
        plan = compose_today_plan(now=NOW, upcoming_prices=prices, currency="CHF")
        cheap_rows = [r for r in plan if r["kind"] == KIND_CHEAP_START]
        assert len(cheap_rows) == 1
        # Block starts at NOW+14h
        when = datetime.fromisoformat(cheap_rows[0]["when"])
        assert when == NOW + timedelta(hours=14)
        # Values carry the end time + average price
        assert cheap_rows[0]["values"]["currency"] == "CHF"
        # avg of [0.10, 0.10, 0.12] = 0.1066...
        assert cheap_rows[0]["values"]["price"].startswith("0.1")

    def test_expensive_block_distinct_from_cheap(self):
        prices = _prices(NOW, [
            (1, "normal", 0.20), (2, "expensive", 0.40),
            (3, "very_expensive", 0.50), (4, "normal", 0.20),
            (10, "cheap", 0.10), (11, "cheap", 0.10), (12, "normal", 0.20),
        ])
        plan = compose_today_plan(now=NOW, upcoming_prices=prices)
        kinds = [r["kind"] for r in plan]
        assert KIND_EXPENSIVE_START in kinds
        assert KIND_CHEAP_START in kinds

    def test_single_hour_block_ignored(self):
        # A lone expensive hour shouldn't generate a block row — too short
        # to be plan-worthy.
        prices = _prices(NOW, [
            (1, "normal", 0.20), (2, "expensive", 0.40),
            (3, "normal", 0.20),
        ])
        plan = compose_today_plan(now=NOW, upcoming_prices=prices)
        assert not any(r["kind"] == KIND_EXPENSIVE_START for r in plan)

    def test_no_ev_rows_when_min_already_met(self):
        plan = compose_today_plan(
            now=NOW,
            ev_min_remaining_kwh=0.0,
            ev_deadline=NOW + timedelta(hours=22),
            night_start=NOW + timedelta(hours=12),
        )
        kinds = [r["kind"] for r in plan]
        assert not any(k in kinds for k in (KIND_EV_CHARGE_START,
                                            KIND_EV_MIN_REACHED, KIND_EV_DEADLINE))

    def test_ev_charge_start_uses_cheap_window_when_tariff_waiting(self):
        # Tariff-optimized + currently waiting + cheap window known →
        # charge_start row points at the cheap window opening.
        cheap_open = NOW + timedelta(hours=15)
        plan = compose_today_plan(
            now=NOW,
            ev_min_remaining_kwh=8.0,
            ev_deadline=NOW + timedelta(hours=22),
            night_start=NOW + timedelta(hours=12),
            ev_tariff_optimized=True,
            ev_tariff_waiting=True,
            ev_next_cheap_window=cheap_open,
            ev_effective_rate_kw=4.0,
        )
        starts = [r for r in plan if r["kind"] == KIND_EV_CHARGE_START]
        assert len(starts) == 1
        assert datetime.fromisoformat(starts[0]["when"]) == cheap_open
        assert starts[0]["detail"] == "plan_ev_charge_tariff"

    def test_ev_charge_start_uses_night_when_not_waiting(self):
        # No tariff or tariff but not waiting → charge_start = night window open.
        night = NOW + timedelta(hours=12)
        plan = compose_today_plan(
            now=NOW,
            ev_min_remaining_kwh=8.0,
            ev_deadline=NOW + timedelta(hours=22),
            night_start=night,
            ev_tariff_optimized=False,
            ev_effective_rate_kw=4.0,
        )
        starts = [r for r in plan if r["kind"] == KIND_EV_CHARGE_START]
        assert len(starts) == 1
        assert datetime.fromisoformat(starts[0]["when"]) == night
        assert starts[0]["detail"] == "plan_ev_charge_night"

    def test_ev_min_reached_estimate(self):
        # 8 kWh at 4 kW = 2h → charge_start + 2h.
        night = NOW + timedelta(hours=12)
        plan = compose_today_plan(
            now=NOW,
            ev_min_remaining_kwh=8.0,
            ev_deadline=NOW + timedelta(hours=22),
            night_start=night,
            ev_effective_rate_kw=4.0,
        )
        min_reached = [r for r in plan if r["kind"] == KIND_EV_MIN_REACHED]
        assert len(min_reached) == 1
        when = datetime.fromisoformat(min_reached[0]["when"])
        assert when == night + timedelta(hours=2)

    def test_rows_sorted_by_time(self):
        # Mixed unsorted input — output must be chronologically ordered.
        prices = _prices(NOW, [
            (1, "normal", 0.20), (5, "cheap", 0.10), (6, "cheap", 0.10),
            (15, "expensive", 0.40), (16, "expensive", 0.40),
        ])
        plan = compose_today_plan(
            now=NOW,
            upcoming_prices=prices,
            night_start=NOW + timedelta(hours=11),
            ev_min_remaining_kwh=5.0,
            ev_deadline=NOW + timedelta(hours=22),
            ev_effective_rate_kw=4.0,
        )
        times = [datetime.fromisoformat(r["when"]) for r in plan]
        assert times == sorted(times), f"plan not sorted: {[t.isoformat() for t in times]}"

    def test_capped_at_8_rows(self):
        # Even with many candidates, output is glanceable (<= 8 rows).
        many_blocks = []
        for i in range(20):
            many_blocks.append((i*2, "cheap" if i%2==0 else "expensive", 0.10))
            many_blocks.append((i*2 + 1, "cheap" if i%2==0 else "expensive", 0.10))
        plan = compose_today_plan(
            now=NOW,
            upcoming_prices=_prices(NOW, many_blocks),
            night_start=NOW + timedelta(hours=11),
            ev_min_remaining_kwh=5.0,
            ev_deadline=NOW + timedelta(hours=22),
            ev_effective_rate_kw=4.0,
        )
        assert len(plan) <= 8


class TestEnrichedScheduleForDay:
    """#282/#3 — schedule_today must expose level + avg_price, not just NT/HT."""

    def test_level_field_present(self):
        from custom_components.solar_energy_management.tariff.tariff_provider import (
            DynamicTariffProvider, PriceLevel, PricePoint,
        )
        from homeassistant.util import dt as dt_util
        now = dt_util.now().replace(minute=0, second=0, microsecond=0)
        prices = [
            PricePoint(now.replace(hour=h), 0.10 if h<6 else 0.40 if h>=17 and h<20 else 0.20,
                       PriceLevel.CHEAP if h<6 else PriceLevel.EXPENSIVE if h>=17 and h<20 else PriceLevel.NORMAL)
            for h in range(24)
        ]
        prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
        prov._read_prices_list = lambda: prices
        sched = prov.get_schedule_for_day()
        # Each block has level + avg_price + legacy tariff
        for block in sched:
            assert "level" in block
            assert block["level"] in ("cheap", "normal", "expensive")
            assert "avg_price" in block
            assert "tariff" in block  # legacy compat
