"""#970 — the held house sink stops at the peak limit.

@Hanzzzie85 (#970): in a cheap hour SEM held the battery for later, the house
bought everything, and a capacity tariff bills the month on one bad 15-minute
slot. His own table asks for this: house 5 kW, sun 2 kW, limit 2.5 kW — held,
the grid pays up to the limit and the battery pays the rest, about 0.5 kW.

#1003 delivered that rate (the hold gives way to the slot budget,
``peak_cover_floor_w``). This file pins his numbers so it cannot drift, and
pins what "the limit" means while a slot is running: not the limit itself but
what the meter may still buy for the REST of the quarter hour — so the pack
covers more in a slot that already bought more than its share, and less in a
slot that ran cold.

A house load SEM cannot measure (a dark grid read) holds nothing: nothing
shows the slot is safe, so the pack is back at its maximum discharge — the
existing blind branch, as before the house sink existed.
"""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.peak_guard import (
    PeakSlotTracker,
    slot_allowed_import_w,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    HELD,
    SinkVerdict,
)

HOUSE_W = 5000.0
SOLAR_W = 2000.0
LIMIT_KW = 2.5
MAX_DISCHARGE_W = 5000.0
SLOT = datetime(2026, 10, 6, 13, 0)


def _view(allowed_w, *, degraded=False):
    fleet = FleetContext(
        solar_w=SOLAR_W, home_w=HOUSE_W, battery_soc=80.0,
        battery_soc_known=True, battery_count=1,
        peak_slot_allowed_w=allowed_w,
        inputs_degraded=degraded, dark_inputs=(("grid",) if degraded else ()),
    )
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=80.0),
        config={"battery_max_discharge_power": MAX_DISCHARGE_W,
                "battery_mode": "auto"},
        fleet=fleet, charging_state="idle", ev_charging=False,
        ev_connected=False, home_consumption_w=HOUSE_W,
        scheduler_decision=None,
        sink_verdicts={"house": SinkVerdict("house", HELD, "cheap hour")},
    )


def _slot_after(seconds, import_w):
    """What the meter may still buy after ``seconds`` of this slot at
    ``import_w`` — the tracker and the budget the coordinator runs."""
    tracker = PeakSlotTracker()
    for s in range(0, int(seconds) + 1, 10):
        tracker.update(SLOT + timedelta(seconds=s), import_w)
    return slot_allowed_import_w(LIMIT_KW, tracker.imported_kwh,
                                 tracker.elapsed_s, blind=tracker.blind)


def test_his_table_the_grid_pays_to_the_limit_the_battery_the_rest():
    """A fresh slot may buy the limit itself: 5 − 2 − 2.5 = 0.5 kW."""
    allowed = _slot_after(0, 0.0)
    assert allowed == pytest.approx(2500.0)
    d = decide_battery(_view(allowed))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == pytest.approx(500.0)
    assert "house sink held" in d.reason and "covers 500 W" in d.reason


def test_a_slot_that_bought_too_much_asks_the_pack_for_more():
    """Half the slot at 3 kW leaves 0.25 kWh for 450 s: the meter may buy
    2 kW, so the pack covers 1 kW."""
    allowed = _slot_after(450, 3000.0)
    assert allowed == pytest.approx(2000.0, abs=1.0)
    d = decide_battery(_view(allowed))
    assert d.discharge_limit_w == pytest.approx(1000.0, abs=1.0)


def test_a_slot_that_ran_cold_lets_the_hold_stand():
    """Half the slot at 2 kW leaves room for 3 kW: the house's 3 kW import
    fits, and the whole pack is kept for the dear hour."""
    allowed = _slot_after(450, 2000.0)
    assert allowed == pytest.approx(3000.0, abs=1.0)
    d = decide_battery(_view(allowed))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == pytest.approx(0.0, abs=1.0)


def test_a_spent_slot_puts_the_whole_house_on_the_pack():
    allowed = _slot_after(600, 4000.0)
    assert allowed == 0.0
    d = decide_battery(_view(allowed))
    assert d.discharge_limit_w == pytest.approx(HOUSE_W - SOLAR_W)


def test_a_house_load_nobody_measured_holds_nothing():
    """Dark grid read: the hold cannot show the slot is safe, so it does not
    hold — the pack is back at its maximum discharge."""
    d = decide_battery(_view(_slot_after(0, 0.0), degraded=True))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == pytest.approx(MAX_DISCHARGE_W)
    assert "not held" in d.reason and "grid" in d.reason


def test_without_a_limit_the_hold_keeps_the_whole_pack():
    """No ceiling configured is not a ceiling of zero: held, 0 W."""
    d = decide_battery(_view(None))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w == 0.0
