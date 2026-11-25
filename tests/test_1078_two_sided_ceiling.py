"""#1078 — a discharge limit that also caps charging must not block the sun.

A Sessy's maximum_power limits both directions. With a car plugged in but
not drawing, the car clamp pinned the pack at home/N and the sun went to the
grid. With the switch on, a car idle for 15 minutes lifts the clamp; a live
car (drawing, or drew within 15 minutes) keeps it.
"""
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


def _view(*, solar_w, charging=False, two_sided=True, drew_recently=False):
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=40.0),
        config={"battery_max_discharge_power": 5000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto",
                "battery_discharge_protection_enabled": True,
                "battery_discharge_limit_caps_charge": two_sided},
        fleet=FleetContext(solar_w=solar_w, home_w=700.0, battery_soc=40.0,
                           battery_soc_known=True, buffer_soc=70.0,
                           battery_assist_min_surplus_w=1200.0),
        charging_state="idle",
        ev_charging=charging,
        ev_connected=True,
        ev_drew_recently=drew_recently,
        home_consumption_w=700.0,
        ev_help_allowed=False,   # (#1381) no connected charger lets the pack help
    )


@pytest.mark.unit
class TestTwoSidedCeiling:
    def test_sun_over_house_and_idle_car_lifts_the_clamp(self):
        d = decide_battery(_view(solar_w=2000.0))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_a_drawing_car_keeps_the_clamp(self):
        d = decide_battery(_view(solar_w=2000.0, charging=True))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_no_sun_over_house_keeps_the_clamp(self):
        d = decide_battery(_view(solar_w=300.0))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_switch_off_changes_nothing(self):
        d = decide_battery(_view(solar_w=2000.0, two_sided=False))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_a_pulsing_car_in_a_gap_keeps_the_clamp(self):
        d = decide_battery(_view(solar_w=2000.0, drew_recently=True))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE, d.reason
