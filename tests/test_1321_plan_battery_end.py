"""(#1321) The plan says where the battery ends: tonight and tomorrow.

The Plan card's "Expected" tile shows the battery when the period ends, on
the plan's own trajectory and floor — not a number the card works out.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.day_ledger import build_day_slots
from custom_components.solar_energy_management.coordinator.energy_planner import (
    battery_at_end, build_night_ledger,
)

from .ast_contracts import calls

TZ = timezone(timedelta(hours=1))
START = datetime(2026, 11, 13, 20, 0, tzinfo=TZ)


def _ledger(soc_kwh, floor_kwh, home_w=700.0, hours=11):
    slots = build_day_slots(
        start=START, end=START + timedelta(hours=hours), day_kwh=0.0,
        sunrise=START.replace(hour=7, minute=30) + timedelta(days=1),
        sunset=START.replace(hour=16, minute=50),
        home_w_at=lambda t: home_w, price_at=lambda t: 0.36,
        level_cheap_at=lambda t: False, export_rate=0.07)
    return build_night_ledger(slots, soc_kwh=soc_kwh, floor_kwh=floor_kwh,
                              max_discharge_w=5000.0, peak_limit_w=6000.0)


@pytest.mark.unit
def test_a_pack_above_its_floor_ends_at_the_floor_after_a_long_night():
    led = _ledger(soc_kwh=4.2, floor_kwh=3.0)          # 28 % of 15, floor 20 %
    end = battery_at_end(led, 3.0, 15.0)
    assert end["kwh"] == pytest.approx(3.0, abs=0.01)
    assert end["pct"] == pytest.approx(20.0, abs=0.1)
    assert end["at"] == led[-1].end.isoformat()


@pytest.mark.unit
def test_a_short_night_leaves_charge_above_the_floor():
    led = _ledger(soc_kwh=12.0, floor_kwh=3.0, home_w=500.0, hours=4)
    end = battery_at_end(led, 3.0, 15.0)
    assert end["kwh"] == pytest.approx(12.0 - 2.0, abs=0.05)   # 4 h × 0.5 kW


@pytest.mark.unit
def test_no_battery_or_no_slots_gives_none():
    assert battery_at_end([], 3.0, 15.0) is None
    assert battery_at_end(_ledger(4.0, 3.0), 3.0, 0.0) is None


@pytest.mark.unit
def test_both_plans_publish_it():
    assert calls(SEMCoordinator._shadow_energy_plan, "battery_at_end")
    assert calls(SEMCoordinator._compose_tomorrow_preview, "battery_at_end")


@pytest.mark.unit
def test_the_plan_sensor_carries_it():
    from custom_components.solar_energy_management.sensor import _energy_plan_attrs
    attrs = _energy_plan_attrs({"battery_end": {"kwh": 3.0, "pct": 20.0, "at": "x"},
                                "battery_floor_pct": 20.0})
    assert attrs["battery_end"]["pct"] == 20.0 and attrs["battery_floor_pct"] == 20.0
