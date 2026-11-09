"""(#1102) What the heater ladder says about itself, and Keep at without prices.

Found on .175 (09.11, simulated 3 kW boiler):
- the observer roster named the rung only by its source, never its code;
- the "too cold" run claimed 1000 W for a 3000 W boiler (a tank without its
  own power sensor reports a stored figure, not a measurement);
- the Legionella run logged ``[source=None]``;
- with no price published at all, the Keep-at goal was never placed.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator import reason_codes as RC
from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, pack_night,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    OWN_RUN_SOURCE, LoadIntent, SurplusController, reconcile_load,
)

from .test_1102_heater_ladder import _boiler, _intent

TZ = timezone(timedelta(hours=1))
NIGHT = datetime(2026, 11, 9, 22, 0, tzinfo=TZ)


# ── 1. the roster names the rung ─────────────────────────────────────────

@pytest.mark.unit
def test_the_roster_carries_the_reason_code():
    sc = SurplusController(MagicMock())
    dev = SimpleNamespace(device_id="boiler", name="Boiler")
    sc.record_observer_decision(
        dev, LoadIntent(True, 3000.0, "comfort_floor", "too cold", RC.LOAD_COMFORT_FLOOR),
        active=False)
    row = sc.observer_decisions["boiler"]
    assert row["reason_code"] == RC.LOAD_COMFORT_FLOOR and row["source"] == "comfort_floor"


# ── 2. the floor run claims the boiler's real draw ───────────────────────

@pytest.mark.unit
def test_floor_start_claims_the_rating():
    assert _intent(_boiler(34.0)).power_w == 3000.0


@pytest.mark.unit
def test_floor_run_without_a_power_sensor_claims_the_rating_not_a_stored_figure():
    dev = _boiler(40.0, active=True)
    dev._comfort_floor_run = True
    dev._status.current_consumption_w = 1000.0   # the stored figure .175 showed
    assert dev.power_entity_id in (None, "")
    assert _intent(dev).power_w == 3000.0


@pytest.mark.unit
def test_floor_run_with_a_power_sensor_claims_the_measurement():
    dev = _boiler(40.0, active=True)
    dev._comfort_floor_run = True
    dev.power_entity_id = "sensor.boiler_power"
    dev.get_current_consumption = lambda: 2950.0
    assert _intent(dev).power_w == 2950.0


# ── 3. Legionella is named, SEM-driven, and never re-tuned ───────────────

@pytest.mark.unit
def test_a_legionella_run_has_its_own_source(monkeypatch):
    dev = _boiler(48.0)
    monkeypatch.setattr(type(dev), "runs_without_surplus", property(lambda self: True))
    start = _intent(dev)
    assert start.on and start.source == OWN_RUN_SOURCE and start.code == RC.LOAD_LEGIONELLA
    assert start.power_w == 3000.0


@pytest.mark.unit
def test_a_running_legionella_run_is_held_not_re_tuned(monkeypatch):
    dev = _boiler(48.0, active=True)
    monkeypatch.setattr(type(dev), "runs_without_surplus", property(lambda self: True))
    dev.adjust_power = AsyncMock()
    dev.activate = AsyncMock()
    intent = _intent(dev)
    assert intent.source == OWN_RUN_SOURCE
    asyncio.run(reconcile_load(dev, intent, observer=False))
    dev.adjust_power.assert_not_called()
    dev.activate.assert_not_called()
    sc = SurplusController(MagicMock())
    sc.record_observer_decision(dev, intent, active=True)
    assert sc.observer_decisions["boiler"]["action"] == "hold"


# ── 4. Keep at is placed with no price published ─────────────────────────

def _unpriced_night(hours=9):
    slots = [LedgerSlot(start=NIGHT + timedelta(hours=h), end=NIGHT + timedelta(hours=h + 1),
                        price=None, level_cheap=False, home_w=500.0) for h in range(hours)]
    return build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0, max_discharge_w=0.0,
                              peak_limit_w=11000.0)


def _goal(**kw):
    return Demand(id="comfort:boiler", kind="comfort", energy_kwh=3.0,
                  max_power_w=3000.0, min_power_w=3000.0, deadline=NIGHT + timedelta(hours=9),
                  source="grid", needs_cheap_level=True, **kw)


@pytest.mark.unit
def test_a_goal_with_no_prices_is_placed_before_the_deadline_and_its_cost_is_unknown():
    plan = pack_night([_goal(unpriced_ok=True)], _unpriced_night(), floor_kwh=0.0,
                      max_discharge_w=0.0, peak_limit_w=11000.0)
    assert plan.allocations, "the goal must not stay unplaced"
    a = plan.allocations[0]
    assert a.start == NIGHT + timedelta(hours=8)      # nearest the morning deadline
    assert a.price is None
    assert plan.total_cost is None and plan.results[0].est_cost is None
    assert "cost unknown" in plan.results[0].note


@pytest.mark.unit
def test_without_the_flag_an_unpriced_night_still_yields():
    plan = pack_night([_goal()], _unpriced_night(), floor_kwh=0.0,
                      max_discharge_w=0.0, peak_limit_w=11000.0)
    assert plan.allocations == () and plan.results[0].status == "yields"


@pytest.mark.unit
def test_priced_cheap_slots_still_come_first():
    slots = [LedgerSlot(start=NIGHT + timedelta(hours=h), end=NIGHT + timedelta(hours=h + 1),
                        price=(0.20 if h == 2 else None), level_cheap=(h == 2), home_w=500.0)
             for h in range(9)]
    ledger = build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0, max_discharge_w=0.0,
                                peak_limit_w=11000.0)
    plan = pack_night([_goal(unpriced_ok=True)], ledger, floor_kwh=0.0,
                      max_discharge_w=0.0, peak_limit_w=11000.0)
    assert plan.allocations[0].start == NIGHT + timedelta(hours=2)
    assert plan.total_cost == pytest.approx(0.6)
