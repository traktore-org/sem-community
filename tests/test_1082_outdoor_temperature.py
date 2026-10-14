"""(#1082) Outdoor temperature — one source, and the home-load forecast learns it.

Four parts of SEM wanted the temperature outside and each read it its own
way: the car's cold taper (weather entity, 15 °C made up when none), the
battery night record (first weather entity), the snow flag (a setting with no
field in the GUI, then any weather entity — including HA's unusable
``weather.forecast_*`` twin). Now there is one producer:

    the user's pick → the crawler's outdoor thermometer → a real weather entity

The crawler finds a thermometer by what it says about itself, never by brand.
PROD (13.10.2026): ``sensor.wetterstationrempfer_temperatur`` (14.8 °C, a
weather station) and ``weather.erlen``.

The consumption predictor learns how far the load moves per degree of cold
(degree hours below 15 °C, against the usual for that weekday and hour). It
learns from day one; the plans use it only behind the soak flag
``temperature_load_forecast``.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.analytics.consumption_predictor import (
    HDD_BASE_C,
    TEMP_SLOPE_MAX_W,
    ConsumptionPredictor,
)
from custom_components.solar_energy_management.coordinator.hints import (
    HintEngine,
    HintFacts,
)
from custom_components.solar_energy_management.hardware_detection import (
    find_outdoor_temperature_sensors,
    temperature_c,
    weather_entities,
)


def _st(eid, state, unit="°C", dc="temperature", name=None, **attrs):
    a = {"unit_of_measurement": unit, "friendly_name": name or eid}
    if dc:
        a["device_class"] = dc
    a.update(attrs)
    return SimpleNamespace(entity_id=eid, state=str(state), attributes=a)


class _Hass:
    """States only; no registry (the crawler then reads names alone)."""

    def __init__(self, states):
        self._s = {s.entity_id: s for s in states}
        self.states = self

    def async_all(self, domain=None):
        return [s for e, s in self._s.items() if domain is None or e.startswith(domain + ".")]

    def get(self, eid):
        return self._s.get(eid)


PROD = [
    _st("sensor.wetterstationrempfer_temperatur", 14.81, name="WetterstationRempfer_Temperatur"),
    _st("sensor.current_weather_temperature", 11.8, name="Current Weather Temperature"),
    _st("sensor.weather_today", 12.2, name="Weather Today"),
    _st("sensor.weather_tomorrow", 17.5, name="Weather Tomorrow"),
    _st("sensor.temperatur_garten_temperatur", "unavailable", name="Temperatur Garten Temperature"),
    _st("sensor.inverter_interne_temperatur", 41.0, name="Inverter interne Temperatur"),
    _st("sensor.living_room_temperature", 21.5, name="Living room temperature"),
    _st("sensor.heat_pump_flow_temperature", 35.0, name="Heat pump flow temperature"),
    SimpleNamespace(entity_id="weather.erlen", state="cloudy",
                    attributes={"temperature": 12.0, "temperature_unit": "°C"}),
    SimpleNamespace(entity_id="weather.forecast_home", state="cloudy",
                    attributes={"temperature": 99.0, "temperature_unit": "°C"}),
]


@pytest.mark.unit
class TestTheCrawlerFindsTheOutside:

    def test_prods_station_is_found_first(self):
        found = [r["entity_id"] for r in find_outdoor_temperature_sensors(_Hass(PROD))]
        assert found[0] == "sensor.wetterstationrempfer_temperatur"

    def test_what_is_not_the_air_outside_is_never_found(self):
        found = {r["entity_id"] for r in find_outdoor_temperature_sensors(_Hass(PROD))}
        for eid in ("sensor.weather_today", "sensor.weather_tomorrow",   # forecasts
                    "sensor.inverter_interne_temperatur",                # electronics
                    "sensor.living_room_temperature",                    # indoors
                    "sensor.heat_pump_flow_temperature"):                # water
            assert eid not in found, eid

    def test_a_dark_garden_sensor_ranks_after_one_that_reads(self):
        found = [r["entity_id"] for r in find_outdoor_temperature_sensors(_Hass(PROD))]
        assert found.index("sensor.temperatur_garten_temperatur") > found.index(
            "sensor.wetterstationrempfer_temperatur")

    def test_a_heat_pumps_own_outdoor_sensor_is_the_outside(self):
        """A heat pump measures the air it pulls in: its OUTDOOR reading is
        real, its flow or inverter reading is not."""
        hp = [_st("sensor.heat_pump_outdoor_temperature", 6.0, name="Heat pump outdoor temperature"),
              _st("sensor.heat_pump_inverter_temperature", 38.0, name="Heat pump inverter temperature")]
        found = [r["entity_id"] for r in find_outdoor_temperature_sensors(_Hass(hp))]
        assert found == ["sensor.heat_pump_outdoor_temperature"]

    def test_a_plain_temperature_says_nothing_about_where(self):
        assert find_outdoor_temperature_sensors(_Hass([_st("sensor.temp_1", 20.0)])) == []

    def test_weather_entities_skip_the_auto_made_twin(self):
        assert weather_entities(_Hass(PROD)) == ["weather.erlen"]


@pytest.mark.unit
class TestOneReading:

    @pytest.mark.parametrize("state,unit,expect", [
        (14.81, "°C", 14.81),
        (50.0, "°F", 10.0),
        (283.15, "K", 10.0),
        ("unavailable", "°C", None),
        ("x", "°C", None),
        (95.0, "°C", None),          # no weather is that hot: a fault
        (12.0, "kWh", None),         # not a temperature
    ])
    def test_a_temperature_in_celsius_or_none(self, state, unit, expect):
        got = temperature_c(_st("sensor.t", state, unit=unit))
        assert (got is None) if expect is None else got == pytest.approx(expect)

    def test_a_weather_entity_reads_its_own_attribute_and_unit(self):
        w = SimpleNamespace(entity_id="weather.x", state="sunny",
                            attributes={"temperature": 50.0, "temperature_unit": "°F"})
        assert temperature_c(w) == pytest.approx(10.0)


def _producer(states, config=None):
    """The REAL coordinator method on a minimal host."""
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
    host = SimpleNamespace(hass=_Hass(states), config=config or {},
                           _OUTDOOR_TEMP_RESCAN_S=600)
    return SEMCoordinator._outdoor_temperature_or_none(host), host


@pytest.mark.unit
class TestOneProducer:

    def test_the_pick_wins(self):
        t, host = _producer(PROD, {"outdoor_temperature_entity": "sensor.current_weather_temperature"})
        assert t == pytest.approx(11.8)
        assert host._outdoor_temp_status["source"] == "configured"

    def test_then_the_crawlers_thermometer(self):
        t, host = _producer(PROD)
        assert t == pytest.approx(14.81)
        assert host._outdoor_temp_status["source"] == "detected"

    def test_then_a_real_weather_entity_never_the_twin(self):
        states = [s for s in PROD if s.entity_id.startswith("weather.")]
        t, host = _producer(states)
        assert t == pytest.approx(12.0)
        assert host._outdoor_temp_status["source"] == "weather"

    def test_a_dark_pick_falls_through_not_to_a_made_up_value(self):
        t, _ = _producer(PROD, {"outdoor_temperature_entity": "sensor.temperatur_garten_temperatur"})
        assert t == pytest.approx(14.81)

    def test_nothing_reads_is_none(self):
        t, host = _producer([])
        assert t is None
        assert host._outdoor_temp_status["source"] == "none"

    def test_the_status_never_carries_an_entity_id(self):
        _, host = _producer(PROD)
        assert "sensor." not in repr(host._outdoor_temp_status)


def _train(pred, days, slope_w=120.0, base_w=500.0, start=datetime(2026, 10, 5)):
    """Hourly samples: load = base + slope × degree hours below 15 °C, with
    the weather moving day to day (cold and mild spells)."""
    for d in range(days):
        day_temp = 14.0 if d % 4 < 2 else 2.0       # mild / cold spells
        for h in range(24):
            dt = start + timedelta(days=d, hours=h)
            t = day_temp + (2.0 if 10 <= h <= 16 else 0.0)
            hdd = max(0.0, HDD_BASE_C - t)
            pred.observe(dt, consumption_w=base_w + slope_w * hdd, solar_w=0.0, temp_c=t)


@pytest.mark.unit
class TestTheForecastLearnsTheCold:

    def test_it_learns_the_load_per_degree(self):
        p = ConsumptionPredictor()
        _train(p, days=28)
        assert p.temperature_slope_w == pytest.approx(120.0, rel=0.25)

    def test_nothing_is_claimed_before_the_weather_varied(self):
        p = ConsumptionPredictor()
        _train(p, days=1)
        assert p.temperature_slope_w is None

    def test_off_by_default_the_plans_see_nothing_new(self):
        p = ConsumptionPredictor()
        _train(p, days=28)
        p.set_temperature(lambda dt: -5.0, use=False)
        assert p.temperature_delta_w(datetime(2026, 11, 2, 18)) == 0.0

    def test_on_a_cold_evening_the_plan_expects_more_load(self):
        p = ConsumptionPredictor()
        _train(p, days=28)
        when = datetime(2026, 11, 2, 18)
        p.set_temperature(lambda dt: 14.0, use=False)
        usual = p.predict_consumption_24h(when)[0]
        p.set_temperature(lambda dt: -5.0, use=True)
        cold = p.predict_consumption_24h(when)[0]
        assert cold > usual + 500.0
        assert p.get_diagnostics()["temperature_path"] == "applied"

    def test_a_missing_forecast_hour_changes_nothing(self):
        p = ConsumptionPredictor()
        _train(p, days=28)
        p.set_temperature(lambda dt: None, use=True)
        assert p.temperature_delta_w(datetime(2026, 11, 2, 18)) == 0.0

    def test_a_load_that_falls_with_cold_never_makes_a_negative_slope(self):
        p = ConsumptionPredictor()
        _train(p, days=28, slope_w=-200.0, base_w=3000.0)
        assert p.temperature_slope_w == 0.0

    def test_the_slope_is_capped(self):
        p = ConsumptionPredictor()
        _train(p, days=28, slope_w=10_000.0)
        assert p.temperature_slope_w == TEMP_SLOPE_MAX_W

    def test_it_survives_a_restart(self):
        p = ConsumptionPredictor()
        _train(p, days=28)
        q = ConsumptionPredictor()
        q.restore_state(p.get_state())
        assert q.temperature_slope_w == pytest.approx(p.temperature_slope_w)

    def test_a_store_from_before_starts_learning_from_zero(self):
        p = ConsumptionPredictor()
        _train(p, days=10)
        old = {k: v for k, v in p.get_state().items() if k not in ("hdd", "t_sxx", "t_sxy", "t_samples")}
        q = ConsumptionPredictor()
        q.restore_state(old)
        assert q.temperature_slope_w is None


@pytest.mark.unit
class TestTheWeeklyCo2Line:

    def _week(self, co2_of_day):
        eng = HintEngine()
        out = []
        start = datetime(2026, 10, 5, 22)       # a Monday
        for d in range(7):
            for hour_shift, night in ((-8, False), (0, True)):   # day, then night start
                facts = HintFacts(now=start + timedelta(days=d, hours=hour_shift), night=night,
                                  enabled={"weekly_summary": True},
                                  daily_solar_kwh=10.0, daily_co2_kg=co2_of_day(d))
                out += eng.evaluate(facts)
        return [h for h in out if h.text_key == "hint_msg_weekly_co2"]

    def test_a_full_week_gets_one_co2_line(self):
        lines = self._week(lambda d: 1.5)
        assert len(lines) == 1 and lines[0].params["co2"] == pytest.approx(10.5)

    def test_a_week_with_a_day_unknown_gets_none(self):
        assert self._week(lambda d: None if d == 2 else 1.5) == []


# ── (#1088) CO2 per car session ─────────────────────────────────────────

@pytest.mark.unit
class TestCo2PerSession:

    def _host(self, kg_now):
        from .test_1024_session_record import _host
        h = _host(session_kwh=0.0)
        h._session_data.grid_energy_kwh = 0.0
        h._session_data.solar_energy_kwh = 0.0
        h._energy_calculator = SimpleNamespace(
            _import_rate=0.3, ev_battery_cost_rate=lambda: 0.0,
            grid_co2_kg_now=lambda: kg_now["v"])
        return h

    def _charge(self, h, grid_w, cycles):
        from custom_components.solar_energy_management.coordinator.ev_control import EVControlMixin
        from custom_components.solar_energy_management.coordinator.types import PowerFlows
        for _ in range(cycles):
            p = SimpleNamespace(ev_connected=True, ev_power=grid_w,
                                ev_connected_per_charger=None)
            EVControlMixin._update_session_tracking(h, p, PowerFlows(grid_to_ev=grid_w))

    def test_grid_kwh_count_at_the_intensity_they_were_drawn_at(self):
        kg = {"v": 0.1}
        h = self._host(kg)
        self._charge(h, 3600.0, 10)          # 10 × 10 s at 3.6 kW = 0.1 kWh
        kg["v"] = 0.3
        self._charge(h, 3600.0, 10)          # another 0.1 kWh, dirtier grid
        sd = h._session_data
        assert sd.grid_energy_kwh == pytest.approx(0.2, rel=0.05)
        assert sd.co2_kg == pytest.approx(0.1 * 0.1 + 0.1 * 0.3, rel=0.05)

    def test_the_record_and_the_csv_carry_it(self):
        from custom_components.solar_energy_management.session_history import sessions_csv
        kg = {"v": 0.2}
        h = self._host(kg)
        self._charge(h, 3600.0, 30)
        from .test_1024_session_record import _unplug
        _unplug(h)
        rec = h._storage.add_session_to_history.call_args.args[0]
        assert rec["co2_kg"] == pytest.approx(0.06, abs=0.01)
        assert sessions_csv([rec]).splitlines()[0].endswith(",co2_kg")

    def test_one_rule_for_every_co2_number(self):
        from custom_components.solar_energy_management.coordinator.energy_calculator import (
            GRID_CO2_KG_PER_KWH, EnergyCalculator)
        calc = EnergyCalculator.__new__(EnergyCalculator)
        calc._grid_co2_kg, calc._co2_live = 0.096, False
        assert calc.grid_co2_kg_now() == GRID_CO2_KG_PER_KWH     # flag off: the average
        calc._co2_live = True
        assert calc.grid_co2_kg_now() == pytest.approx(0.096)    # flag on: live
        calc._grid_co2_kg = None
        assert calc.grid_co2_kg_now() == GRID_CO2_KG_PER_KWH     # no reading: the average
