"""(#1081) A heat pump's COP follows the outdoor temperature, and the plan
ranks its hours by the price of HEAT.

Asked in #1081: "a COP that drops on a cold morning so a mild afternoon
wins". A curve of 2–3 points (outdoor °C → COP) is a per-device goal. With
no curve, nothing changes: the flat COP everywhere, today's plan.
"""
from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.energy_planner import (
    Demand, LedgerSlot, build_night_ledger, demand_why, pack_night,
)
from custom_components.solar_energy_management.coordinator.heat_cost import (
    cop_at, cost_of_heat, format_cop_curve, parse_cop_curve,
)
from custom_components.solar_energy_management.devices.heat_pump_controller import (
    HeatPumpController,
)
from custom_components.solar_energy_management.features.device_registry import (
    UnifiedDeviceRegistry,
)

CURVE = [(-7.0, 2.5), (2.0, 3.2), (12.0, 4.2)]

# ── the curve itself ──────────────────────────────────────────────────────

class TestTheCurve:
    def test_text_and_pairs_parse_to_the_same_sorted_curve(self):
        assert parse_cop_curve("12:4.2, -7:2.5, 2:3.2") == CURVE
        assert parse_cop_curve([(2, 3.2), (-7, 2.5)]) == [(-7.0, 2.5), (2.0, 3.2)]
        assert format_cop_curve(CURVE) == "-7:2.5, 2:3.2, 12:4.2"

    @pytest.mark.parametrize("raw", [
        "", None, "5:3", "1:2,2:3,3:4,4:5", "a:b,1:2", "1:2,1:3", "1:0,5:3",
        "1:-1,5:3", "1:2;", [(1, 2)],
    ])
    def test_a_curve_that_cannot_be_read_is_no_curve(self, raw):
        assert parse_cop_curve(raw) is None

    def test_between_points_it_is_linear(self):
        cop, src = cop_at(CURVE, 7.0, 3.0)
        assert src == "curve" and cop == pytest.approx(3.7)
        assert cop_at(CURVE, -2.5, 3.0)[0] == pytest.approx(2.85)

    def test_outside_the_points_it_is_clamped(self):
        assert cop_at(CURVE, -20.0, 3.0) == (2.5, "curve")
        assert cop_at(CURVE, 30.0, 3.0) == (4.2, "curve")

    def test_two_points_are_enough(self):
        two = parse_cop_curve("0:3, 10:4")
        assert cop_at(two, 5.0, 3.0)[0] == pytest.approx(3.5)

    def test_no_curve_or_no_reading_is_the_flat_cop(self):
        assert cop_at(None, 5.0, 3.0) == (3.0, "flat")
        assert cop_at(CURVE, None, 3.0) == (3.0, "flat")
        assert cop_at(CURVE, float("nan"), 3.0) == (3.0, "flat")

    def test_the_cost_of_heat_divides_by_the_cop_used(self):
        cop, _ = cop_at(CURVE, -7.0, 3.0)
        assert cost_of_heat(0.30, cop) == pytest.approx(0.12)

# ── the goal ──────────────────────────────────────────────────────────────

class _FakeController:
    def __init__(self):
        self._devices = {}

    def register_device(self, d):
        self._devices[d.device_id] = d

    def get_device(self, did):
        return self._devices.get(did)

def _registry_with_pump():
    reg = UnifiedDeviceRegistry(MagicMock(), _FakeController(), MagicMock(), MagicMock())
    reg._store = AsyncMock()
    reg.async_refresh_devices = AsyncMock()
    hp = HeatPumpController(MagicMock(), relay1_entity_id="switch.sg1",
                            rated_power=2000.0)
    reg._surplus_controller.register_device(hp)
    return reg, hp

@pytest.mark.asyncio
async def test_the_curve_is_a_goal_that_reaches_the_heat_pump():
    reg, hp = _registry_with_pump()
    assert hp.cop_curve is None                 # a new pump has no curve
    await reg.async_update_device_goal("heat_pump", "cop_curve", "-7:2.5, 2:3.2, 12:4.2")
    assert hp.cop_curve == CURVE
    # a restart applies the stored goal again
    hp.cop_curve = None
    reg._apply_goals(hp)
    assert hp.cop_curve == CURVE
    await reg.async_update_device_goal("heat_pump", "cop_curve", "")
    assert hp.cop_curve is None

def test_a_load_without_a_cop_takes_no_curve():
    reg, _ = _registry_with_pump()
    other = SimpleNamespace(device_id="pump", daily_min_runtime_sec=0)
    reg._device_goals["pump"] = {"cop_curve": "-7:2.5, 12:4.2"}
    reg._apply_goals(other)
    assert not hasattr(other, "cop_curve")

def test_the_card_payload_shows_the_curve_only_on_a_heat_pump():
    reg, hp = _registry_with_pump()
    reg._device_goals["heat_pump"] = {"cop_curve": "-7:2.5, 12:4.2"}
    assert reg._goal_payload("heat_pump")["goals"]["cop_curve"] == "-7:2.5, 12:4.2"
    reg._device_goals.pop("heat_pump")
    assert reg._goal_payload("heat_pump")["goals"]["cop_curve"] == ""
    # a plain load has no COP: no key for the card to draw an editor from
    reg._surplus_controller.register_device(
        SimpleNamespace(device_id="pool", _daily_runtime_accumulated_sec=0))
    assert "cop_curve" not in reg._goal_payload("pool")["goals"]

def test_the_service_checks_the_curve_with_the_one_parser():
    from custom_components.solar_energy_management.tests.ast_contracts import (
        call_sites,
    )
    assert "cop_curve" in UnifiedDeviceRegistry.GOAL_PROPERTIES
    # the service and the goal apply both read through parse_cop_curve
    files = {str(p).rsplit("/", 1)[-1] for p, *_ in call_sites("parse_cop_curve")}
    assert {"__init__.py", "device_registry.py"} <= files

# ── the plan ──────────────────────────────────────────────────────────────

def _ledger(prices, temps_by_hour=None):
    t0 = dt_util.now().replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    slots = [LedgerSlot(start=t0 + timedelta(hours=n),
                        end=t0 + timedelta(hours=n + 1), price=p,
                        level_cheap=True, home_w=300.0)
             for n, p in enumerate(prices)]
    return t0, build_night_ledger(slots, soc_kwh=0.0, floor_kwh=0.0,
                                  max_discharge_w=5000.0, peak_limit_w=0.0)

def _pack(cop_fn, prices):
    t0, ledger = _ledger(prices)
    d = Demand(id="comfort:heat_pump", kind="comfort", energy_kwh=2.0,
               max_power_w=2000.0, min_power_w=2000.0,
               deadline=t0 + timedelta(hours=len(prices)), cop_at=cop_fn)
    plan = pack_night([d], ledger)
    return t0, ledger, [a for a in plan.allocations if a.demand_id == d.id], plan

class TestThePlanRanksByThePriceOfHeat:
    # 06:00 is a bit cheaper but cold; 14:00 is mild
    PRICES = [0.30, 0.28, 0.30, 0.30]

    def _cop(self, t0):
        temps = {0: 5.0, 1: -7.0, 2: 5.0, 3: 12.0}

        def f(ts):
            return cop_at(CURVE, temps[int((ts - t0).total_seconds() // 3600)], 3.0)[0]
        return f

    def test_without_a_curve_the_cheapest_electricity_wins(self):
        t0, _, allocs, _ = _pack(None, self.PRICES)
        assert [a.start for a in allocs] == [t0 + timedelta(hours=1)]

    def test_with_a_curve_the_mild_hour_wins(self):
        t0, _, _, _ = _pack(None, self.PRICES)
        t0, ledger, allocs, plan = _pack(self._cop(t0), self.PRICES)
        # 0.28 / 2.5 = 0.112 at -7 °C against 0.30 / 4.2 = 0.071 at 12 °C
        assert [a.start for a in allocs] == [t0 + timedelta(hours=3)]
        # rank only: the cost and kWh stay electricity
        assert allocs[0].price == pytest.approx(0.30)
        assert plan.results[0].planned_kwh == pytest.approx(2.0)

    def test_the_reason_names_the_cop(self):
        t0, _, _, _ = _pack(None, self.PRICES)
        cop = self._cop(t0)
        _, ledger, allocs, _ = _pack(cop, self.PRICES)
        why = demand_why(allocs, ledger, "grid", cop)
        assert why["code"] == "cheapest_heat"
        assert why["params"]["cop"] == pytest.approx(4.2)
        assert demand_why(allocs, ledger, "grid")["code"] == "cheapest_hours"

    def test_a_broken_cop_ranks_by_price(self):
        def bad(ts):
            raise RuntimeError("no forecast")
        t0, _, allocs, _ = _pack(bad, self.PRICES)
        assert [a.start for a in allocs] == [t0 + timedelta(hours=1)]

    def test_no_curve_keeps_every_allocation_as_today(self):
        """The no-curve path is byte-identical: same allocations, same cost."""
        prices = [0.31, 0.22, 0.40, 0.18, 0.25, 0.33]
        _, _, a1, p1 = _pack(None, prices)
        t0, ledger = _ledger(prices)
        d = Demand(id="comfort:heat_pump", kind="comfort", energy_kwh=2.0,
                   max_power_w=2000.0, min_power_w=2000.0,
                   deadline=t0 + timedelta(hours=len(prices)))
        p2 = pack_night([d], ledger)
        a2 = [a for a in p2.allocations if a.demand_id == d.id]
        assert [(a.start, a.end, a.price) for a in a1] == [(a.start, a.end, a.price) for a in a2]
        assert p1.results[0].est_cost == p2.results[0].est_cost

def test_the_plan_builder_hands_the_curve_to_heat_pump_demands():
    from custom_components.solar_energy_management.tests.ast_contracts import call_kwargs
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
    kws = call_kwargs(SEMCoordinator._shadow_energy_plan, "Demand")
    assert sum(1 for k in kws if "cop_at" in k) >= 2   # the run-time and the comfort demand

# ── the sensor ────────────────────────────────────────────────────────────

def test_the_data_carries_the_cop_its_source_and_the_outdoor_reading():
    from custom_components.solar_energy_management.coordinator.types import (
        HeatPumpSensorData,
    )
    data = HeatPumpSensorData(heat_pump_cop=3.7, heat_pump_cop_source="curve",
                              heat_pump_cop_outdoor_c=7.0,
                              heat_pump_cost_of_heat=0.081)
    assert data.heat_pump_cop_source == "curve"
    assert data.heat_pump_cop_outdoor_c == 7.0
    # without a curve both stay empty: nothing new is read or shown
    assert HeatPumpSensorData().heat_pump_cop_outdoor_c is None
