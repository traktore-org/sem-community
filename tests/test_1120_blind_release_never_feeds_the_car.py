"""#1120 — a cycle with no house reading must not hand the pack to the car.

In a held hour (#879) a cycle that cannot read the house releases the hold
(#1003): the pack may cover the house again, at its full discharge power. That
release returned before the EV clamp ran, so with a car plugged in the pack
fed the car — on a battery the user had told not to (``may_assist_ev`` off),
or with the discharge protection on. The release is about the HOUSE; the car
clamp still decides what the car may take.

The house figure here is not hand-fed: it is what ``PowerReadings`` makes of a
dark grid read with a car drawing, as the reader hands it on.
"""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.actuate_battery import (
    actuate_battery,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent, BatteryRuntime, BatteryView, FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.sink_verdicts import (
    HELD, SinkVerdict,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)

MAX_W = 9000.0
CAR_W = 7000.0


def _dark_cycle():
    """Night, held pack, car drawing, grid read dark (reader's 0 W fallback)."""
    p = PowerReadings()
    p.solar_power = 0.0
    p.grid_power = 0.0
    p.battery_power = 0.0
    p.ev_power = CAR_W
    p.calculate_derived()
    return p


def _view(p, *, perms=None, protection=True, ev=True):
    cfg = {"battery_max_discharge_power": MAX_W, "battery_mode": "auto",
           "battery_discharge_protection_enabled": protection}
    fleet = FleetContext(
        solar_w=p.solar_power, home_w=p.home_consumption_power,
        battery_soc=80.0, battery_soc_known=True, battery_count=1,
        buffer_soc=30.0, battery_assist_min_surplus_w=1200.0,
        peak_slot_allowed_w=6000.0, inputs_degraded=True,
        dark_inputs=("grid",),
        home_residual_clamped_w=float(getattr(p, "home_residual_clamped_w", 0.0) or 0.0),
    )
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=80.0), config=cfg,
        fleet=fleet, charging_state="charging" if ev else "idle",
        ev_charging=ev, ev_connected=ev,
        home_consumption_w=p.home_consumption_power,
        scheduler_decision=None, battery_permissions=perms,
        ev_help_allowed=(perms or {}).get("may_assist_ev") is not False,  # (#1381)
        sink_verdicts={"house": SinkVerdict("house", HELD, "cheap hour")},
    )


def _adapter():
    a = MagicMock()
    a.last_intent = BatteryIntent.LIMIT_DISCHARGE      # the hold's 0 W
    a.last_discharge_limit_w = 0.0
    a._limit_lower_streak = 0
    a.command_limit_discharge = AsyncMock()
    a.command_normal = AsyncMock()
    return a


@pytest.mark.asyncio
@pytest.mark.parametrize("perms,protection", [
    ({"may_assist_ev": False}, False),   # the user's own "no"
    ({"may_assist_ev": False}, True),
    (None, True),                         # protection on, no surplus
])
async def test_a_dark_cycle_never_opens_the_pack_to_the_car(perms, protection):
    p = _dark_cycle()
    d = decide_battery(_view(p, perms=perms, protection=protection))
    assert d.intent is BatteryIntent.LIMIT_DISCHARGE
    assert d.discharge_limit_w < CAR_W, d.reason
    assert "ev plugged in" in d.reason
    a = _adapter()
    await actuate_battery(d, a, inputs_degraded=True)
    for call in a.command_limit_discharge.await_args_list:
        assert call.args[0] < CAR_W
    a.command_normal.assert_not_awaited()


def test_without_a_car_the_blind_cycle_still_releases_the_hold():
    """#1003 stands: no car, the pack covers the house at its max."""
    p = _dark_cycle()
    p.ev_power = 0.0
    p.calculate_derived()
    d = decide_battery(_view(p, ev=False))
    assert d.discharge_limit_w == pytest.approx(MAX_W)
    assert "not held" in d.reason


def test_a_car_the_pack_may_feed_still_gets_the_release():
    """Protection off and assist allowed: nothing forbids the car the pack."""
    p = _dark_cycle()
    d = decide_battery(_view(p, perms={"may_assist_ev": True}, protection=False))
    assert d.discharge_limit_w == pytest.approx(MAX_W)
