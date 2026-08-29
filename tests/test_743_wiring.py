"""#743 wiring — the probe's grant reaches decide() through the one seam.

FleetCycleState.curtailment_grant_w → build_charger_view → FleetContext
→ self_consumption_surplus_w. One field, one thread, and the surplus
math treats granted watts exactly like measured solar — every solar
mode and the multi-charger cascade inherit the behavior for free.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.charger_types import (
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.decide import (
    self_consumption_surplus_w,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


def _view(grant_w: float):
    power = PowerReadings()
    power.solar_power = 1000.0
    power.home_consumption_power = 1000.0
    power.ev_connected = True
    fleet_state = FleetCycleState(
        power=power,
        config={"battery_soc_reserve": 20},
        curtailment_grant_w=grant_w,
    )
    return build_charger_view(
        fleet_state,
        charger_id="ev_charger",
        charger_cfg={"id": "ev_charger"},
        mode="solar_only",
        daily_ev_kwh=0.0,
    )


class TestTheGrantReachesDecide:
    def test_the_grant_rides_the_fleet_context(self):
        view = _view(4340.0)
        assert view.fleet.curtailment_grant_w == 4340.0

    def test_granted_watts_count_as_surplus(self):
        """Measured surplus is 0 (production == home) — the grant is
        the only surplus, and it must be enough to start the floor."""
        view = _view(4340.0)
        assert self_consumption_surplus_w(view) == 4340.0

    def test_no_grant_no_change(self):
        view = _view(0.0)
        assert self_consumption_surplus_w(view) == 0.0
