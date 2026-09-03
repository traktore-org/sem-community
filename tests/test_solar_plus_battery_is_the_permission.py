"""Solar + battery on the charger IS the permission to spend the pack.

Guido, 03.09: *"why do I have to switch it on since I chose the option on the
EV charger — this just does not make sense."* He is right. The
``forecast_spending_enabled`` master switch was the release train's inertness
device for the #778 arc (land asleep, wake deliberately), not a user concept.
A charger set to *Solar + battery* has already said the pack may feed the car;
the forecast budget (spendable > 0, tonight's floor) is the safety, not the
consent. The switch keeps one job: selling forecast surplus to the grid, where
no device mode exists to carry the consent.
"""
from __future__ import annotations

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryRuntime,
    BatteryView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    _battery_assist_split,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    BatteryIntent,
    decide_battery,
)

from .test_decide import _view as _decide_view


def _sunless(mode, *, switch, spendable=1.7, soc=92.0):
    v = _decide_view(mode)
    f = v.fleet
    for k, val in dict(solar_w=0.0, home_w=700.0, battery_charge_w=0.0,
                       battery_soc=soc, buffer_soc=75.0, auto_start_soc=90.0,
                       battery_assist_max_power_w=5000.0,
                       battery_assist_min_surplus_w=1000.0,
                       battery_may_assist_ev=True,
                       forecast_spending_enabled=switch,
                       battery_spendable_kwh=spendable,
                       dynamic_floor_pct=78.5).items():
        object.__setattr__(f, k, val)
    return v


@pytest.mark.unit
class TestTheChargerModeCarriesTheConsent:

    def test_solar_plus_battery_spends_without_the_switch(self):
        surplus, assist = _battery_assist_split(_sunless("solar_plus_battery", switch=False))
        assert assist > 0, "the mode said 'battery' — no second switch"

    def test_the_budget_is_still_the_safety(self):
        surplus, assist = _battery_assist_split(
            _sunless("solar_plus_battery", switch=False, spendable=0.0))
        assert assist == 0.0, "nothing spendable tonight → nothing spent"

    def test_the_floor_is_still_the_floor(self):
        surplus, assist = _battery_assist_split(
            _sunless("solar_plus_battery", switch=False, soc=77.0))
        assert assist == 0.0

    def test_other_modes_still_need_the_switch(self):
        # min_plus_solar never meant "battery for the car"; the switch is the
        # only consent it can carry, unchanged.
        _, off = _battery_assist_split(_sunless("min_plus_solar", switch=False))
        _, on = _battery_assist_split(_sunless("min_plus_solar", switch=True))
        assert off == 0.0 and on > 0


def _bview(*, switch, ev_wants_pack, soc=92.0, spendable=1.7):
    fleet = FleetContext(solar_w=1000.0, home_w=1000.0, battery_soc=soc,
                         buffer_soc=75.0, battery_assist_min_surplus_w=1000.0)
    return BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=soc),
        config={"battery_max_discharge_power": 5000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto", "battery_reserve_soc": 20},
        fleet=fleet, charging_state="solar_charging_allowed",
        ev_charging=True, ev_connected=True, home_consumption_w=1000.0,
        forecast_spending_enabled=switch, battery_spendable_kwh=spendable,
        dynamic_floor_pct=78.5, ev_wants_pack=ev_wants_pack,
    )


@pytest.mark.unit
class TestTheBatterySideReadsTheSameConsent:

    def test_a_solar_plus_battery_car_opens_the_clamp_without_the_switch(self):
        d = decide_battery(_bview(switch=False, ev_wants_pack=True))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE, d.reason

    def test_no_consent_anywhere_keeps_the_clamp(self):
        d = decide_battery(_bview(switch=False, ev_wants_pack=False))
        assert d.intent is BatteryIntent.LIMIT_DISCHARGE

    def test_the_switch_alone_still_opens_it(self):
        d = decide_battery(_bview(switch=True, ev_wants_pack=False))
        assert d.intent is not BatteryIntent.LIMIT_DISCHARGE

    def test_the_view_defaults_to_no_consent(self):
        assert BatteryView.__dataclass_fields__["ev_wants_pack"].default is False


@pytest.mark.unit
class TestTheCoordinatorDerivesIt:
    def test_the_battery_view_is_built_with_the_fleet_consent(self):
        import inspect
        from custom_components.solar_energy_management.coordinator import coordinator as cm
        src = inspect.getsource(cm)
        assert "ev_wants_pack=" in src and "_ev_wants_pack(" in src

    def test_helper_answers_from_mode_and_connection(self):
        from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
        c = SEMCoordinator.__new__(SEMCoordinator)
        c.config = {"ev_chargers": [{"id": "a", "charge_mode": "solar_plus_battery"},
                                    {"id": "b", "charge_mode": "min_plus_solar"}]}
        c._effective_charge_mode_for = lambda cfg: cfg.get("charge_mode", "off")
        class P: ev_connected_per_charger = {"a": True, "b": True}; ev_connected = True
        assert c._ev_wants_pack(P()) is True
        P.ev_connected_per_charger = {"a": False, "b": True}
        assert c._ev_wants_pack(P()) is False
        c.config = {"ev_chargers": []}
        assert c._ev_wants_pack(P()) is False
