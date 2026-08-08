"""#638 — the shadow arbitrage advisor, the last string.

The one client that reads EVERY page of the books: prices (both
horizons), the SOC trajectory, discharge budgets, peak headroom, and
tomorrow's forecast. Buy in the cheap slots, deliver in the expensive
ones — but only when the spread survives the round trip and the wear,
only into hours where the home actually draws from the grid, and never
buying what tomorrow's sun fills free.

SHADOW-ONLY: the advisor publishes advice on the plan; the demand
injection is config-gated off by default and nothing actuates from it
(#533 state — the command wire's live proof is post-1.8 on Guido's
call). Its build-phase job is to be the framework's sharpest test
instrument on the .175 rig.
"""
from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.arbitrage import (
    arbitrage_advice,
)
from custom_components.solar_energy_management.coordinator.overnight_planner import (
    LedgerSlot,
)

TZ = timezone.utc


def _t(h, m=0, day=8):
    return datetime(2026, 8, day, h, m, tzinfo=TZ)


def _slot(h, price, home_grid_w=800.0, day=8, hours=1):
    return LedgerSlot(
        start=_t(h, day=day), end=_t(h, day=day) + timedelta(hours=hours),
        price=price, home_w=home_grid_w, home_grid_w=home_grid_w,
    )


def _advice(slots, **kw):
    args = dict(
        soc_kwh=3.0, capacity_kwh=10.0,
        max_charge_w=5000.0, max_discharge_w=5000.0,
        round_trip_efficiency=0.92, cycle_cost_per_kwh=0.05,
        tomorrow_free_kwh=0.0,
    )
    args.update(kw)
    return arbitrage_advice(slots, **args)


class TestTheOpportunity:
    def test_a_wide_spread_is_an_opportunity(self):
        """Buy at 10 ct in the valley, deliver into a 45 ct morning:
        0.92 × 0.45 − 0.10 − 0.05 ≈ +26 ct/kWh — clearly worth it."""
        adv = _advice([_slot(2, 0.10), _slot(3, 0.10),
                       _slot(7, 0.45), _slot(8, 0.45)])
        assert adv.opportunity is True
        assert adv.charge_kwh > 0
        assert all(b["start"].hour in (2, 3) for b in adv.charge_blocks)
        assert all(b["start"].hour in (7, 8) for b in adv.discharge_blocks)
        assert adv.est_profit > 0

    def test_a_thin_spread_does_not_survive_the_round_trip(self):
        """28 → 32 ct: 0.92 × 0.32 − 0.28 − 0.05 < 0 — the honest no.
        The reason must carry the numbers, not just the verdict."""
        adv = _advice([_slot(2, 0.28), _slot(7, 0.32)])
        assert adv.opportunity is False
        assert adv.charge_kwh == 0
        assert "0.32" in adv.reason or "spread" in adv.reason

    def test_the_efficiency_term_does_something(self):
        """(the #708/#735 lesson: prove the term, don't let it cancel)
        A marginal case that pays at η=1.0 and loses at η=0.80: the buy
        price must sit BETWEEN η·sell (0.256) and sell (0.32)."""
        slots = [_slot(2, 0.28), _slot(7, 0.32)]
        lossless = _advice(slots, round_trip_efficiency=1.0,
                           cycle_cost_per_kwh=0.0)
        lossy = _advice(slots, round_trip_efficiency=0.80,
                        cycle_cost_per_kwh=0.0)
        assert lossless.opportunity is True
        assert lossy.opportunity is False

    def test_the_wear_term_does_something(self):
        slots = [_slot(2, 0.20), _slot(7, 0.30)]
        cheap_wear = _advice(slots, cycle_cost_per_kwh=0.0)
        dear_wear = _advice(slots, cycle_cost_per_kwh=0.20)
        assert cheap_wear.opportunity is True
        assert dear_wear.opportunity is False


class TestTheHonestBounds:
    def test_discharge_only_after_the_charge(self):
        """An expensive hour BEFORE the valley is yesterday's chance —
        energy cannot flow backwards in time."""
        adv = _advice([_slot(7, 0.45), _slot(22, 0.10)])
        assert adv.opportunity is False

    def test_discharge_value_exists_only_where_the_home_draws(self):
        """Avoided import needs an import to avoid: a 45 ct hour with the
        home fully on solar (home_grid_w 0) buys nothing."""
        adv = _advice([_slot(2, 0.10),
                       _slot(7, 0.45, home_grid_w=0.0)])
        assert adv.opportunity is False

    def test_the_deliverable_energy_caps_the_buy(self):
        """One 800 W home-hour can absorb 0.8 kWh — buying more than
        η-adjusted that is buying to nowhere."""
        adv = _advice([_slot(2, 0.10), _slot(3, 0.10), _slot(4, 0.10),
                       _slot(7, 0.45, home_grid_w=800.0)])
        assert adv.opportunity is True
        assert adv.charge_kwh <= 0.8 / 0.92 + 0.01

    def test_tomorrows_free_sun_caps_the_buy(self):
        """Never grid-charge what tomorrow's sun fills free: room above
        the floor is 8 kWh minus 6 kWh of expected free charging."""
        big_home = [_slot(2, 0.10), _slot(3, 0.10),
                    _slot(7, 0.45, home_grid_w=5000.0),
                    _slot(8, 0.45, home_grid_w=5000.0)]
        free = _advice(big_home, soc_kwh=2.0, tomorrow_free_kwh=6.0)
        greedy = _advice(big_home, soc_kwh=2.0, tomorrow_free_kwh=0.0)
        assert greedy.charge_kwh > free.charge_kwh > 0
        assert free.charge_kwh <= 10.0 - 2.0 - 6.0 + 0.01

    def test_a_full_battery_buys_nothing(self):
        adv = _advice([_slot(2, 0.10), _slot(7, 0.45)], soc_kwh=10.0)
        assert adv.opportunity is False
        assert "full" in adv.reason or "room" in adv.reason

    def test_unpriced_slots_are_not_a_market(self):
        adv = _advice([_slot(2, None), _slot(7, None)])
        assert adv.opportunity is False

    def test_slot_power_caps_bound_the_volume(self):
        """A 2 kW charger cannot buy 5 kWh in one cheap hour."""
        adv = _advice([_slot(2, 0.10),
                       _slot(7, 0.45, home_grid_w=5000.0),
                       _slot(8, 0.45, home_grid_w=5000.0)],
                      max_charge_w=2000.0)
        assert adv.charge_kwh <= 2.0 + 0.01

    def test_no_slots_is_a_calm_no(self):
        adv = _advice([])
        assert adv.opportunity is False

    def test_free_surplus_slots_are_not_a_buy(self):
        """A price-0 day-surplus slot (cap_override marks it) is the sun
        banking itself — normal solar charging, the scheduler's job.
        Counting it as an arbitrage 'buy' would claim the system's
        default behavior as the advisor's profit."""
        sun = LedgerSlot(start=_t(13), end=_t(14), price=0.0,
                         level_cheap=True, home_w=0.0,
                         cap_override_w=3000.0)
        adv = _advice([sun, _slot(19, 0.45)])
        assert adv.opportunity is False
