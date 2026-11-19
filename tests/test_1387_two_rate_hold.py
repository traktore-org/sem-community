"""#1387 — a two-rate tariff marks its peak NORMAL, so the night planner
that holds only through EXPENSIVE hours started the car in the peak.

Night from 22:00, peak until 23:00, 10 kWh by 07:00 (an uncovered night).
A tariff with cheaper hours that is not dynamic holds through every hour
that is not cheap. A dynamic tariff keeps its own words.
"""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from custom_components.solar_energy_management.coordinator.ev_tariff_planner import (
    plan_night_charge,
)
from custom_components.solar_energy_management.coordinator.price_view import PriceView
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider, PriceLevel, StaticTariffProvider,
)

TZ = ZoneInfo("Europe/Zurich")
NOW = datetime(2026, 11, 17, 22, 0, tzinfo=TZ)      # a Tuesday


def _dynamic():
    """The real dynamic provider; 22:00 and 23:00 are NORMAL, then CHEAP."""
    p = DynamicTariffProvider.__new__(DynamicTariffProvider)
    p.get_price_level_at = lambda t: (
        PriceLevel.NORMAL if t.hour in (22, 23) else PriceLevel.CHEAP)
    return p


def _plan(level_at):
    return plan_night_charge(
        now=NOW, remaining_to_min_kwh=10.0, min_amps=6, max_amps=16,
        watts_per_amp=690.0, night_end="07:00", night_start="22:00",
        tariff_optimized=True, peak_managed_amps=16, level_at=level_at)


@pytest.mark.unit
def test_two_rate_peak_hour_is_held_until_it_ends():
    provider = StaticTariffProvider(
        peak_rate=0.30, off_peak_rate=0.18, peak_start=7, peak_end=23)
    assert provider.get_price_level_at(NOW) is PriceLevel.NORMAL
    plan = _plan(PriceView(provider).hold_level_at_fn())
    assert plan.should_wait_for_cheap is True
    assert plan.next_cheap_start == NOW.replace(hour=23)


@pytest.mark.unit
def test_the_raw_levels_start_in_the_peak():
    """What the planner did before: it asked the raw levels."""
    provider = StaticTariffProvider(
        peak_rate=0.30, off_peak_rate=0.18, peak_start=7, peak_end=23)
    assert _plan(PriceView(provider).level_at_fn()).should_wait_for_cheap is False


@pytest.mark.unit
def test_a_dynamic_tariff_is_unchanged():
    p = _dynamic()
    assert p.has_cheap_rate() is True        # the mode is offered ...
    view = PriceView(p)
    assert view.hold_level_at_fn() == view.level_at_fn()   # ... no new hold
    plan = _plan(view.hold_level_at_fn())
    assert plan.should_wait_for_cheap is False   # starts at 22:00, as before


@pytest.mark.unit
def test_a_flat_tariff_never_holds():
    provider = StaticTariffProvider(peak_rate=0.2, off_peak_rate=0.2)
    view = PriceView(provider)
    assert view.hold_level_at_fn() == view.level_at_fn()
    assert _plan(view.hold_level_at_fn()).should_wait_for_cheap is False
