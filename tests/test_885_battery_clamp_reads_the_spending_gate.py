"""#885 — the battery-side discharge clamp reads the same gate the charger
side opens with.

The charger's ``_battery_assist_split`` bypasses the #537 solar gate when
``forecast_spending_enabled`` is on and tonight's budget has something
spendable (#778 phase 5). ``decide_battery`` never learned that: with the
EV plugged and surplus under the gate it pins discharge to the house load
regardless — so the charger offers assist amps the pack is forbidden to
deliver, and the car draws grid under a strategy line that says battery
assist (PROD 02.09, recorded on #885). One gate, two readers.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    BatteryIntent,
    decide_battery,
)


def _view(*, soc, spending, spendable, dynamic_floor=None, surplus_w=0.0):
    fleet = FleetContext(
        solar_w=surplus_w + 1000.0, home_w=1000.0,
        battery_soc=soc, buffer_soc=75.0,
        battery_assist_min_surplus_w=1000.0,
    )
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 5000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto", "battery_reserve_soc": 20},
        fleet=fleet,
        charging_state="night_charging_active",
        ev_charging=True, ev_connected=True,
        home_consumption_w=1000.0,
        forecast_spending_enabled=spending,
        battery_spendable_kwh=spendable,
        dynamic_floor_pct=dynamic_floor,
    )


@pytest.mark.unit
class TestTheClampReadsTheSpendingGate:

    def test_today_the_pack_is_pinned_to_the_house(self):
        d = decide_battery(_view(soc=92.0, spending=False, spendable=0.0))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert "gate" in d.reason

    def test_spending_on_with_a_budget_lets_the_pack_feed_the_car(self):
        d = decide_battery(_view(soc=92.0, spending=True, spendable=1.7,
                                 dynamic_floor=78.5))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_spending_on_but_nothing_spendable_still_clamps(self):
        d = decide_battery(_view(soc=92.0, spending=True, spendable=0.0))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE

    def test_the_dynamic_floor_still_binds_with_spending_on(self):
        # 77 % is above the 75 % buffer but below tonight's 78.5 % floor.
        d = decide_battery(_view(soc=77.0, spending=True, spendable=1.7,
                                 dynamic_floor=78.5))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
        assert "floor" in d.reason

    def test_below_the_buffer_clamps_regardless(self):
        d = decide_battery(_view(soc=70.0, spending=True, spendable=1.7))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE
