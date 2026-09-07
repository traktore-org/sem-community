"""(#931) The forecast-spend sell refuses to sell at a price that is not
positive — and refuses when the price cannot be read.

`evaluate_forecast_sell` was written price-blind ON PURPOSE for a fixed
feed-in, where the rate is a constant the budget already priced. But the
switch that enables it is a plain global with no fixed-tariff gate, and a
dynamic-tariff install that turns it on would be sold at whatever the
evening's export price is — zero, or negative, paying to give energy away.

Three states, never two: unreadable is not zero, and neither is a reason
to sell. A static-tariff install hands in its configured feed-in and is
unchanged.
"""

from __future__ import annotations

from datetime import datetime, timezone

from custom_components.solar_energy_management.coordinator.forecast_sell import (
    evaluate_forecast_sell,
)

NOW = datetime(2026, 9, 8, 19, 30, tzinfo=timezone.utc)


def _sell(**kw):
    base = dict(now=NOW, enabled=True, in_block=True, block_w=1500.0,
                spendable_kwh=3.0, max_discharge_w=5000.0,
                dynamic_floor_pct=None, reserve_pct=20.0)
    base.update(kw)
    return evaluate_forecast_sell(**base)


class TestThePriceGate:

    def test_a_positive_price_sells(self):
        d = _sell(export_rate=0.075, export_rate_known=True)
        assert d.state.value == "discharging_arbitrage"

    def test_a_zero_price_holds(self):
        d = _sell(export_rate=0.0, export_rate_known=True)
        assert d.state.value != "discharging_arbitrage"
        assert "not positive" in d.reason

    def test_a_negative_price_holds(self):
        """A dynamic tariff at a negative export price: selling pays to give
        energy away. This is the case the switch's name never warned about."""
        d = _sell(export_rate=-0.02, export_rate_known=True)
        assert d.state.value != "discharging_arbitrage"
        assert "not positive" in d.reason

    def test_an_unreadable_price_holds_and_says_so(self):
        """Unreadable is not zero — and it is not a reason to sell either."""
        d = _sell(export_rate=None, export_rate_known=False)
        assert d.state.value != "discharging_arbitrage"
        assert "unreadable" in d.reason

    def test_the_default_keeps_the_old_behaviour_for_direct_callers(self):
        """No price handed in, known=True: the pre-#931 contract, so a caller
        that has not been wired yet is not silently disabled."""
        d = _sell()
        assert d.state.value == "discharging_arbitrage"

    def test_the_price_gate_comes_after_the_enable_switch(self):
        d = _sell(enabled=False, export_rate=-1.0, export_rate_known=True)
        assert d.reason == "forecast spending off"
