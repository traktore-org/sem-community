"""#875 — a SOC that has NEVER been read is not 0 %.

``SensorReader`` holds the last valid SOC across dark reads so the charging
logic never sees 0 % during a sensor gap. That hold had no "no value yet"
state: ``_last_valid_soc`` initialised to 0.0, so between a restart and the
SOC sensor's first report (≤ 76 s on the PROD Huawei, 2 m 43 s in #694) the
held value WAS 0.0 — an empty pack — with ``battery_soc_unavailable`` set
beside it and nothing on the charger path reading it. The fleet was steered
as Zone 1 for those cycles: solar EV charging paused, battery given a
priority it did not need.

The rule: an UNKNOWN battery is neither a source nor a blocker. The charger
path charges the car on surplus (Zone 2), offers no battery assist, does not
reclaim the battery's charging power, and the discharge clamp protects the
pack as it would below the buffer.
"""
from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryIntent,
    BatteryRuntime,
    BatteryView,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
    FleetCycleState,
)
from custom_components.solar_energy_management.coordinator.build_view import (
    build_charger_view,
)
from custom_components.solar_energy_management.coordinator.decide import (
    _ev_reclaims,
    battery_assist_budget_w,
    decide,
)
from custom_components.solar_energy_management.coordinator.decide_battery import (
    decide_battery,
)
from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


# ─── the reader: "never read" is a state of its own ────────────────────────

def _state(value):
    import homeassistant.util.dt as dt_util
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": "%"}
    s.last_updated = s.last_reported = dt_util.utcnow()
    return s


def _reader(soc_state):
    hass = MagicMock()
    hass.states = MagicMock()
    hass.states.get = lambda eid: _state(soc_state[0]) if eid == "sensor.soc" else None
    r = SensorReader(hass, {"battery_soc_sensor": "sensor.soc"})
    r._energy_dashboard_config = None
    return r


@pytest.mark.unit
class TestTheHoldHasANeverReadState:
    def test_a_dark_first_read_is_not_a_held_zero(self):
        soc = ["unavailable"]
        r = _reader(soc)
        p = r.read_power()
        assert p.battery_soc_unavailable is True
        assert p.battery_soc_known is False, "0.0 was published as a held value"

    def test_the_first_success_makes_the_soc_known(self):
        soc = ["unavailable"]
        r = _reader(soc)
        r.read_power()
        soc[0] = "78"
        p = r.read_power()
        assert p.battery_soc == pytest.approx(78.0)
        assert p.battery_soc_known is True
        assert p.battery_soc_unavailable is False

    def test_no_soc_sensor_at_all_is_nothing_measured(self):
        """An install with no SOC sensor configured. The Energy-Dashboard
        path already reported that as unavailable; the explicit-sensor path
        published 0.0 as a measurement — Zone 1 forever, the VPP and the
        night recorder fed an empty pack that does not exist."""
        hass = MagicMock()
        hass.states.get = lambda eid: None
        r = SensorReader(hass, {})
        r._energy_dashboard_config = None
        p = r.read_power()
        assert p.battery_soc_unavailable is True
        assert p.battery_soc_known is False

    def test_a_later_gap_holds_the_last_value_and_stays_known(self):
        """The zero-order hold is the right design for a gap — untouched."""
        soc = ["78"]
        r = _reader(soc)
        r.read_power()
        soc[0] = "unavailable"
        p = r.read_power()
        assert p.battery_soc == pytest.approx(78.0)
        assert p.battery_soc_known is True
        assert p.battery_soc_unavailable is True


# ─── the view carries it ───────────────────────────────────────────────────

def _power(**over):
    power = MagicMock()
    power.solar_power = 5000.0
    power.home_consumption_power = 500.0
    power.battery_soc = 0.0
    power.battery_soc_known = True
    power.battery_soc_unavailable = False
    power.ev_power_per_charger = {}
    power.ev_connected_per_charger = {}
    power.ev_charging_per_charger = {}
    power.inputs_degraded = False
    power.solar_power_unavailable = False
    power.grid_power_unavailable = False
    power.battery_power_unavailable = False
    for k, v in over.items():
        setattr(power, k, v)
    return power


@pytest.mark.unit
def test_the_charger_view_carries_soc_known():
    def _view_for(**over):
        return build_charger_view(
            FleetCycleState(power=_power(**over), config={}, is_night=False,
                            tariff_level=None, forecast_remaining_kwh=0.0),
            charger_id="wb", charger_cfg={"id": "wb"},
            mode="solar_only", daily_ev_kwh=0.0,
        )
    assert _view_for().fleet.battery_soc_known is True
    assert _view_for(battery_soc_known=False).fleet.battery_soc_known is False


# ─── decide: unknown is neither a source nor a blocker ─────────────────────

def _view(mode="min_plus_solar", *, soc=0.0, known=True, solar_w=5000.0,
          home_w=500.0, battery_charge_w=0.0, ev_priority=1,
          battery_priority=5):
    return ChargerView(
        power=ChargerPower(charger_id="keba", power_w=0.0,
                           connected=True, charging=False),
        energy=ChargerEnergy(charger_id="keba"),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 32},
        fleet=FleetContext(
            solar_w=solar_w, home_w=home_w,
            battery_charge_w=battery_charge_w,
            battery_soc=soc, battery_soc_known=known,
            battery_priority=battery_priority,
            battery_assist_max_power_w=4500.0,
            battery_assist_min_surplus_w=1200.0,
        ),
        ev_priority=ev_priority,
    )


@pytest.mark.unit
class TestUnknownSocOnTheChargerPath:
    def test_a_known_empty_pack_still_holds_the_car(self):
        """The existing Zone-1 rule, untouched: SOC 0 % READ → battery first."""
        d = decide(_view(soc=0.0, known=True))
        assert d.intent == ChargerIntent.IDLE
        assert "Zone 1" in d.reason

    def test_an_unknown_pack_does_not_hold_the_car(self):
        """The #875 window: no SOC yet, 4.5 kW of surplus → the car charges."""
        d = decide(_view(soc=0.0, known=False))
        assert d.intent == ChargerIntent.CHARGE_AT_AMPS, d.reason
        assert "Zone 1" not in d.reason

    def test_an_unknown_pack_offers_no_battery_assist(self):
        """…and it is not a source either: the budget is the surplus alone,
        even though 0.0 sits in the field and SOC 95 % would assist."""
        v = _view("solar_only", soc=95.0, known=False)
        assert battery_assist_budget_w(v) == pytest.approx(4500.0)

    def test_an_unknown_pack_is_not_reclaimed(self):
        """A charger above the battery in the list may reclaim the battery's
        charging power at SOC ≥ reserve — not when the SOC is unknown."""
        v = _view("solar_only", soc=95.0, known=False, battery_charge_w=2000.0,
                  ev_priority=1, battery_priority=5)
        assert _ev_reclaims(v) is False
        assert _ev_reclaims(_view("solar_only", soc=95.0, known=True,
                                  battery_charge_w=2000.0)) is True


@pytest.mark.unit
def test_the_discharge_clamp_protects_an_unknown_pack():
    """decide_battery keys the EV discharge clamp on ``soc < buffer``. An
    unknown SOC must land on the protective side even when 0.0 is not what
    the field holds (a FleetContext built from a held 95 % that has since
    been marked unknown is the same question)."""
    view = BatteryView(
        runtime=BatteryRuntime(battery_id="b1", last_known_soc=95.0),
        config={"battery_max_discharge_power": 4000,
                "battery_max_charge_power_w": 5000,
                "battery_mode": "auto",
                "battery_discharge_protection_enabled": True},
        fleet=FleetContext(solar_w=5000.0, home_w=500.0, battery_soc=95.0,
                           battery_soc_known=False, buffer_soc=70.0,
                           battery_assist_min_surplus_w=1200.0),
        charging_state="charging",
        ev_charging=True,
        ev_connected=True,
        home_consumption_w=500.0,
    )
    d = decide_battery(view)
    assert d.intent == BatteryIntent.LIMIT_DISCHARGE, d.reason
