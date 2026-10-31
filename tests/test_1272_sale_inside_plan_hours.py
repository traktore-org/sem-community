"""#1272 — a battery sale runs only inside the hours of the plan that holds it.

A plan stamped after midnight ends at sunrise. If its sale block is for that
evening, the block is not the plan's to start: the sale was sized from the
night's battery level. Both sell gates now ask the span rule ``plan_gate``
already used.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from custom_components.solar_energy_management.coordinator.energy_plan_actuation import (
    arbitrage_sell_gate, forecast_sell_gate,
)

UTC = timezone.utc
STAMP_NIGHT = datetime(2026, 10, 31, 2, 0, tzinfo=UTC)
SUNRISE = datetime(2026, 10, 31, 7, 0, tzinfo=UTC)
EVENING = datetime(2026, 10, 31, 19, 30, tzinfo=UTC)
STAMP_MORNING = datetime(2026, 10, 31, 7, 30, tzinfo=UTC)
NEXT_SUNRISE = datetime(2026, 11, 1, 7, 0, tzinfo=UTC)


def _block():
    return [{"start": "2026-10-31T19:00:00+00:00",
             "end": "2026-10-31T21:00:00+00:00", "kwh": 3.0}]


def _plan(stamp, slots_end):
    return {
        "computed_at": stamp.isoformat(),
        "slots": [{"start": stamp.isoformat(), "end": slots_end.isoformat()}],
        "arbitrage": {"opportunity": True, "discharge_blocks": _block()},
        "forecast_sell": {"enabled": True, "blocks": _block()},
    }


@pytest.mark.parametrize("gate", [arbitrage_sell_gate, forecast_sell_gate])
class TestBothSellGates:
    def test_a_night_plan_cannot_start_the_evening_sale(self, gate):
        plan = _plan(STAMP_NIGHT, SUNRISE)
        assert gate(plan, EVENING) == (False, 0.0)

    def test_a_day_plan_runs_the_evening_sale(self, gate):
        plan = _plan(STAMP_MORNING, NEXT_SUNRISE)
        open_, watts = gate(plan, EVENING)
        assert open_ is True
        assert watts == pytest.approx(1500.0)

    def test_the_plan_stamp_starts_its_hours_even_before_its_first_slot(self, gate):
        plan = _plan(STAMP_MORNING, NEXT_SUNRISE)
        plan["slots"][0]["start"] = (STAMP_MORNING + timedelta(minutes=30)).isoformat()
        plan["arbitrage"]["discharge_blocks"][0]["start"] = STAMP_MORNING.isoformat()
        plan["forecast_sell"]["blocks"][0]["start"] = STAMP_MORNING.isoformat()
        assert gate(plan, STAMP_MORNING + timedelta(minutes=5))[0] is True

    def test_the_end_of_the_last_slot_closes_it(self, gate):
        plan = _plan(STAMP_MORNING, EVENING)
        assert gate(plan, EVENING) == (False, 0.0)

    @pytest.mark.parametrize("slots", [None, [], [{"start": "junk", "end": "junk"}]])
    def test_no_readable_hours_means_no_sale(self, gate, slots):
        plan = _plan(STAMP_MORNING, NEXT_SUNRISE)
        if slots is None:
            del plan["slots"]
        else:
            plan["slots"] = slots
        assert gate(plan, EVENING) == (False, 0.0)
