"""#1277 — the plan's sale was split over batteries that may not sell.

Two batteries, the plan says sell 4000 W. Battery 2 is in Self-consumption
mode or has no export permission. Each got 2000 W, battery 2 sold nothing,
and only 2000 W went out. The split now counts only the batteries the sale
at hand may use: the arbitrage sale and the forecast spend use different
switches, so each has its own count.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.decide_battery import (
    may_take_the_sale,
    sale_surface_count,
)

from .test_1182_one_sale_power_one_writer import (
    LIMIT,
    LIMIT2,
    SETPOINT,
    SETPOINT2,
    _battery,
    _cycle,
    _Hass,
    _normal,
    _pbc,
    _stub,
)


def _cfg(sale, mode="auto", **extra):
    return {**_pbc(None, sale, mode=mode), **extra}


class TestWhoMayTakeTheSale:
    def test_self_consumption_never_sells(self):
        assert not may_take_the_sale(_cfg(None, "self_consumption"), {}, spend=False)
        assert not may_take_the_sale(_cfg(None, "self_consumption"), {}, spend=True)

    def test_allow_arbitrage_may_sell(self):
        assert may_take_the_sale(_cfg(None, "allow_arbitrage"), {}, spend=False)

    def test_auto_follows_its_own_switch_per_sale(self):
        auto = _cfg(None, "auto")
        assert not may_take_the_sale(auto, {}, spend=False)
        assert not may_take_the_sale(auto, {}, spend=True)
        on = _cfg(None, "auto", battery_grid_arbitrage_enabled=True)
        assert may_take_the_sale(on, {}, spend=False)
        assert not may_take_the_sale(on, {}, spend=True)
        assert may_take_the_sale(auto, {"forecast_spending_enabled": True}, spend=True)
        assert not may_take_the_sale(
            auto, {"forecast_spending_enabled": True}, spend=False)

    def test_a_revoked_export_permission_is_no_sale(self):
        revoked = _cfg(None, "allow_arbitrage",
                       battery_permissions={"may_export": False})
        assert not may_take_the_sale(revoked, {}, spend=False)
        shared = {"battery_permissions": {"may_export": False}}
        assert not may_take_the_sale(_cfg(None, "allow_arbitrage"), shared, spend=False)

    def test_a_granted_permission_lets_self_consumption_sell(self):
        granted = _cfg(None, "self_consumption",
                       battery_permissions={"may_export": True})
        assert may_take_the_sale(granted, {"forecast_spending_enabled": True},
                                 spend=True)


class TestTheCountKeepsOnlySellers:
    def test_a_battery_that_may_not_sell_has_no_share(self):
        units = [(_cfg(SETPOINT, "allow_arbitrage"), None),
                 (_cfg(SETPOINT2, "self_consumption"), None)]
        assert sale_surface_count(units) == 2
        assert sale_surface_count(
            units, may_sell=lambda p: may_take_the_sale(p, {}, spend=False)) == 1

    def test_without_a_filter_the_count_is_as_before(self):
        units = [(_cfg(SETPOINT), None), (_cfg(SETPOINT2), None)]
        assert sale_surface_count(units) == 2

    def test_nobody_selling_is_still_one(self):
        units = [(_cfg(SETPOINT), None), (_cfg(SETPOINT2), None)]
        assert sale_surface_count(units, may_sell=lambda p: False) == 1


@pytest.mark.asyncio
class TestTheSplitInThePipeline:
    async def _run(self, monkeypatch, cfgs, *, spend=False, config=None):
        from custom_components.solar_energy_management.coordinator import (
            energy_plan_actuation as epa,
        )
        hass = _Hass()
        limits, sales = (LIMIT, LIMIT2), (SETPOINT, SETPOINT2)
        stub = _stub(hass, {f"b{i + 1}": _battery(hass, limits[i], sales[i])
                            for i in range(2)})
        stub._per_battery_config = lambda i, n: cfgs[i]
        stub.config = dict(config or {})
        stub._energy_plan_actuation = True
        monkeypatch.setattr(epa, "arbitrage_sell_gate",
                            lambda *a, **k: (True, 4000.0))
        monkeypatch.setattr(epa, "forecast_sell_gate",
                            lambda *a, **k: (True, 4000.0))
        views: list = []
        await _cycle(monkeypatch, stub,
                     {"b1": _normal("b1"), "b2": _normal("b2")}, views=views)
        return views

    async def test_the_arbitrage_sale_goes_to_the_battery_that_may_sell(
            self, monkeypatch):
        cfgs = [_cfg(SETPOINT, "allow_arbitrage"),
                _cfg(SETPOINT2, "self_consumption")]
        views = await self._run(monkeypatch, cfgs)
        assert [v.arbitrage_sell for v in views] == [(True, 4000.0)] * 2

    async def test_two_sellers_still_share_it(self, monkeypatch):
        cfgs = [_cfg(SETPOINT, "allow_arbitrage"),
                _cfg(SETPOINT2, "allow_arbitrage")]
        views = await self._run(monkeypatch, cfgs)
        assert [v.arbitrage_sell for v in views] == [(True, 2000.0)] * 2

    async def test_a_revoked_permission_takes_no_share(self, monkeypatch):
        cfgs = [_cfg(SETPOINT, "allow_arbitrage"),
                _cfg(SETPOINT2, "allow_arbitrage",
                     battery_permissions={"may_export": False})]
        views = await self._run(monkeypatch, cfgs)
        assert [v.arbitrage_sell for v in views] == [(True, 4000.0)] * 2

    async def test_the_forecast_spend_counts_by_its_own_switch(
            self, monkeypatch):
        # b1 follows the spend switch (auto), b2 may not sell at all
        cfgs = [_cfg(SETPOINT, "auto"), _cfg(SETPOINT2, "self_consumption")]
        views = await self._run(monkeypatch, cfgs,
                                config={"forecast_spending_enabled": True})
        assert [v.forecast_sell for v in views] == [(True, 4000.0)] * 2

    async def test_the_spend_split_ignores_the_arbitrage_switch(
            self, monkeypatch):
        # b1 only sells on the arbitrage switch, which the spend does not read
        cfgs = [_cfg(SETPOINT, "auto"),
                _cfg(SETPOINT2, "auto", battery_grid_arbitrage_enabled=True)]
        views = await self._run(monkeypatch, cfgs,
                                config={"forecast_spending_enabled": True})
        assert [v.forecast_sell for v in views] == [(True, 2000.0)] * 2
        assert [v.arbitrage_sell for v in views] == [(True, 4000.0)] * 2
