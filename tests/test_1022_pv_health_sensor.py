"""#1022 — ``sensor.sem_pv_health``: the colour, its attributes, and the
coordinator's feed from the forecast ledger and the reader."""
import json
import os
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)
from custom_components.solar_energy_management.coordinator.forecast_ledger import (
    ForecastLedger,
)
from custom_components.solar_energy_management.sensor import (
    SEMSolarSensor, SENSOR_TYPES,
)

_HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
KEY = "pv_health"
STATES = ("green", "yellow", "orange", "red")


def _description():
    return next(d for d in SENSOR_TYPES if d.key == KEY)


class TestDescription:
    def test_it_is_an_enum_of_the_four_colours(self):
        d = _description()
        assert d.device_class is SensorDeviceClass.ENUM
        assert tuple(d.options) == STATES
        assert d.state_class is None
        assert d.native_unit_of_measurement is None

    def test_every_language_names_it_and_its_states(self):
        with open(os.path.join(_HERE, "strings.json"), encoding="utf-8") as f:
            entry = json.load(f)["entity"]["sensor"][KEY]
        assert set(entry["state"]) == set(STATES)
        for name in os.listdir(os.path.join(_HERE, "translations")):
            with open(os.path.join(_HERE, "translations", name), encoding="utf-8") as f:
                t = json.load(f)["entity"]["sensor"][KEY]
            assert t["name"], name
            assert set(t["state"]) == set(STATES), name


class TestSensor:
    def _sensor(self, mock_coordinator, state, attrs=None):
        mock_coordinator.data = dict(mock_coordinator.data)
        mock_coordinator.data["pv_health"] = state
        mock_coordinator.data["pv_health_attrs"] = attrs or {}
        return SEMSolarSensor(coordinator=mock_coordinator,
                              description=_description(), entry_id="e")

    def test_the_colour_is_the_state_and_the_numbers_are_attributes(self, mock_coordinator):
        s = self._sensor(mock_coordinator, "yellow", {
            "ratio_7d": 0.72, "settled_days": 7, "downtime_min_today": 12,
            "days_since_full_yield": 4, "snow": False,
        })
        assert s.native_value == "yellow"
        attrs = s.extra_state_attributes
        assert attrs["ratio_7d"] == 0.72
        assert attrs["downtime_min_today"] == 12
        assert attrs["days_since_full_yield"] == 4
        assert attrs["snow"] is False

    def test_no_verdict_yet_is_unknown_not_unavailable(self, mock_coordinator):
        s = self._sensor(mock_coordinator, None, {"settled_days": 1})
        assert s.native_value is None
        assert s.available is True
        assert s.extra_state_attributes["settled_days"] == 1


def _coordinator(ledger, temp=None):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = MagicMock()
    c.hass.states.async_all.return_value = []
    c.config = {}
    c._forecast_ledger = ledger
    c._pv_low_since_mono = None
    c._tracker_date = dt_util.now().date()
    if temp is not None:
        c.config = {"outdoor_temperature_entity": "sensor.out"}
        st = MagicMock()
        st.state = str(temp)
        c.hass.states.get.return_value = st
    return c


def _ledger(ratios, horizon=0):
    led = ForecastLedger()
    today = dt_util.now().date()
    for back, r in zip(range(len(ratios), 0, -1), ratios, strict=True):
        day = str(today - timedelta(days=back))
        led.record(day, horizon, 20.0)
        led.settle(day, 20.0 * r)
    # today is settling — never counted
    led.record(str(today), 0, 20.0)
    led.settle(str(today), 1.0)
    return led


class TestCoordinatorFeed:
    def test_seven_settled_days_from_the_ledger_today_excluded(self):
        c = _coordinator(_ledger([0.0] * 3 + [0.9] * 7))
        power = SimpleNamespace(solar_power=3000.0, solar_downtime_min_today=12.4)
        forecast = SimpleNamespace(forecast_power_now_w=3200.0)
        h = c._pv_health_verdict(power, forecast, now_mono=1000.0)
        assert h.state == "green"
        assert h.settled_days == 7
        assert h.downtime_min_today == 12
        assert h.snow is False

    def test_the_day_before_forecast_is_the_fallback(self):
        c = _coordinator(_ledger([0.5] * 4, horizon=1))
        h = c._pv_health_verdict(SimpleNamespace(solar_power=0.0, solar_downtime_min_today=0),
                                 SimpleNamespace(forecast_power_now_w=0.0), now_mono=1.0)
        assert h.state == "orange"

    def test_snow_needs_two_dark_hours_and_a_temperature_source(self):
        c = _coordinator(_ledger([0.9] * 4), temp=-2.0)
        power = SimpleNamespace(solar_power=10.0, solar_downtime_min_today=0)
        forecast = SimpleNamespace(forecast_power_now_w=1500.0)
        assert c._pv_health_verdict(power, forecast, now_mono=0.0).snow is False
        assert c._pv_health_verdict(power, forecast, now_mono=3600.0).snow is False
        assert c._pv_health_verdict(power, forecast, now_mono=7300.0).snow is True
        # the plant wakes up: the clock resets
        bright = SimpleNamespace(solar_power=900.0, solar_downtime_min_today=0)
        assert c._pv_health_verdict(bright, forecast, now_mono=7400.0).snow is False
        assert c._pv_health_verdict(power, forecast, now_mono=7500.0).snow is False

    def test_no_temperature_source_never_claims_snow(self):
        c = _coordinator(_ledger([0.9] * 4))
        power = SimpleNamespace(solar_power=0.0, solar_downtime_min_today=0)
        forecast = SimpleNamespace(forecast_power_now_w=1500.0)
        c._pv_health_verdict(power, forecast, now_mono=0.0)
        assert c._pv_health_verdict(power, forecast, now_mono=9000.0).snow is False
        assert c._outdoor_temperature_or_none() is None
        assert c._read_outdoor_temperature() == 15.0

    def test_no_ledger_is_no_verdict_not_a_crash(self):
        c = _coordinator(None)
        h = c._pv_health_verdict(SimpleNamespace(solar_power=0.0, solar_downtime_min_today=3.0),
                                 SimpleNamespace(forecast_power_now_w=0.0), now_mono=1.0)
        assert h.state is None
        assert h.downtime_min_today == 3


class TestDashboardRow:
    def test_the_insights_screen_has_the_row(self):
        # (#1321) the Insights screen reads it
        from ._dashboard_src import dashboard_src
        assert "pv_health" in dashboard_src()
