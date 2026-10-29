"""(#1088) Grid CO2 intensity — found by its unit, counted at its live value.

SEM counted CO2 avoided with one fixed number, the Swiss grid average
(0.128 kg/kWh). PROD has the Electricity Maps integration reporting the real
intensity for CH (``sensor.electricity_maps_co2_intensity`` = 96 gCO2eq/kWh on
13.10.2026, attributes ``country_code`` and ``attribution``, no forecast).

- The crawler finds such a sensor by its UNIT, never by an integration name:
  "CO2 per energy", in g or kg, per kWh or MWh.
- A value outside 0..1.5 kg/kWh, a non-number or unavailable is not used.
- Behind the soak flag ``co2_live_intensity`` the CO2 books count each kWh of
  solar used in the house at the live value. They do it as a correction on top
  of the fixed number, so switching on never makes a total jump, and a cycle
  without a reading counts exactly as before.
"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    CO2_CORRECTION_CATEGORY,
    GRID_CO2_KG_PER_KWH,
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.hardware_detection import (
    co2_unit_factor,
    find_grid_co2_sensors,
    parse_co2_forecast_rows,
    read_co2_intensity_kg,
    series_attribute,
)
from custom_components.solar_energy_management.utils.time_manager import TimeManager

PROD_ATTRS = {"unit_of_measurement": "gCO2eq/kWh", "country_code": "CH",
              "attribution": "Data provided by Electricity Maps"}


def _state(value, attrs, eid="sensor.electricity_maps_co2_intensity"):
    return SimpleNamespace(entity_id=eid, state=str(value), attributes=attrs)


@pytest.mark.unit
class TestFoundByUnit:

    @pytest.mark.parametrize("unit,factor", [
        ("gCO2eq/kWh", 0.001),          # Electricity Maps
        ("g CO₂/kWh", 0.001),      # spaces and the subscript
        ("gCO2/kWh", 0.001),
        ("kgCO2/kWh", 1.0),
        ("kg CO2eq/kWh", 1.0),
        ("gCO2eq/MWh", 0.000001),
    ])
    def test_a_co2_unit_reads_as_kg_per_kwh(self, unit, factor):
        assert co2_unit_factor(unit) == pytest.approx(factor)

    @pytest.mark.parametrize("unit", ["kg", "%", "W", "kWh", "g", None, ""])
    def test_other_units_are_not_co2_intensity(self, unit):
        # "kg" is SEM's own CO2 *avoided*; "%" is the fossil-fuel share
        assert co2_unit_factor(unit) is None

    def test_prods_sensor_reads_96_grams(self):
        assert read_co2_intensity_kg(_state(96.0, PROD_ATTRS)) == pytest.approx(0.096)

    @pytest.mark.parametrize("value", ["unavailable", "unknown", "", "x", "-5", "2000"])
    def test_an_unusable_reading_is_none(self, value):
        """2000 g = 2 kg/kWh: no grid emits that — a unit or sensor fault."""
        assert read_co2_intensity_kg(_state(value, PROD_ATTRS)) is None

    def test_no_state_is_none(self):
        assert read_co2_intensity_kg(None) is None

    def test_the_crawler_lists_every_co2_sensor_and_nothing_else(self):
        states = [
            _state(96.0, PROD_ATTRS),
            _state(9.47, {"unit_of_measurement": "%"}, "sensor.electricity_maps_grid_fossil_fuel_percentage"),
            _state(2.26, {"unit_of_measurement": "kg"}, "sensor.sem_daily_co2_avoided"),
            _state(0.21, {"unit_of_measurement": "kgCO2/kWh",
                          "forecast": [{"from": "2026-10-13T12:00Z", "intensity": 0.2}]},
                   "sensor.a_other_source"),
        ]
        hass = SimpleNamespace(states=SimpleNamespace(async_all=lambda domain: states))
        found = find_grid_co2_sensors(hass)
        assert [f["entity_id"] for f in found] == [
            "sensor.a_other_source", "sensor.electricity_maps_co2_intensity"]
        by_id = {f["entity_id"]: f for f in found}
        assert by_id["sensor.electricity_maps_co2_intensity"]["has_forecast"] is False
        assert by_id["sensor.a_other_source"]["has_forecast"] is True
        assert by_id["sensor.a_other_source"]["forecast_attribute"] == "forecast"

    def test_no_hass_finds_nothing(self):
        assert find_grid_co2_sensors(None) == []


@pytest.mark.unit
class TestForecastShape:

    def test_prods_attributes_carry_no_series(self):
        assert series_attribute(PROD_ATTRS) is None

    def test_a_list_of_timed_entries_is_a_series(self):
        attrs = {"forecast": [{"from": "2026-10-13T12:00Z", "intensity": 120}]}
        assert series_attribute(attrs) == "forecast"

    def test_a_series_under_any_name_is_found_by_shape(self):
        attrs = {"next_hours": [{"start": "2026-10-13T12:00Z", "value": 0.1}]}
        assert series_attribute(attrs) == "next_hours"

    def test_a_list_without_times_is_not_a_series(self):
        assert series_attribute({"forecast": [{"intensity": 120}]}) is None
        assert series_attribute({"forecast": [1, 2, 3]}) is None


@pytest.mark.unit
class TestParseCo2ForecastRows:
    """(#1085 Part A) The value key is found by shape, like the time key."""

    def test_the_known_intensity_key_wins(self):
        attrs = {"forecast": [
            {"from": "2026-10-13T12:00Z", "intensity": 0.2},
            {"from": "2026-10-13T13:00Z", "intensity": 0.18},
        ]}
        rows = parse_co2_forecast_rows(attrs, "forecast")
        assert [v for _, v in rows] == [0.2, 0.18]

    def test_an_unknown_key_name_still_resolves_when_it_is_the_only_one(self):
        attrs = {"next_hours": [{"start": "2026-10-13T12:00Z", "gco2": 210}]}
        rows = parse_co2_forecast_rows(attrs, "next_hours")
        assert rows == [(rows[0][0], 210.0)]

    def test_rows_are_sorted_by_time_regardless_of_input_order(self):
        attrs = {"forecast": [
            {"from": "2026-10-13T14:00Z", "intensity": 0.3},
            {"from": "2026-10-13T12:00Z", "intensity": 0.1},
        ]}
        rows = parse_co2_forecast_rows(attrs, "forecast")
        assert [v for _, v in rows] == [0.1, 0.3]

    def test_an_unparseable_time_skips_only_that_row(self):
        attrs = {"forecast": [
            {"from": "not a time", "intensity": 0.9},
            {"from": "2026-10-13T12:00Z", "intensity": 0.2},
        ]}
        rows = parse_co2_forecast_rows(attrs, "forecast")
        assert [v for _, v in rows] == [0.2]

    def test_two_unnamed_numeric_candidates_are_ambiguous_and_skipped(self):
        """#925: a guess is worse than nothing when the shape is genuinely
        ambiguous — two numbers, neither a recognised value-key name."""
        attrs = {"forecast": [
            {"from": "2026-10-13T12:00Z", "a": 1, "b": 2}]}
        assert parse_co2_forecast_rows(attrs, "forecast") == []

    def test_a_missing_attribute_is_empty(self):
        assert parse_co2_forecast_rows({}, "forecast") == []

    def test_a_non_dict_row_is_skipped(self):
        attrs = {"forecast": [1, 2, {"from": "2026-10-13T12:00Z", "intensity": 0.2}]}
        # series_attribute would already reject this shape, but the parser
        # itself must not raise on it either.
        rows = parse_co2_forecast_rows(attrs, "forecast")
        assert [v for _, v in rows] == [0.2]


def _calc():
    hass = Mock()
    hass.states.get = lambda _eid: None
    return EnergyCalculator({"update_interval": 3600}, TimeManager(hass))


def _hour(calc, solar_w=2000.0, export_w=500.0):
    """One cycle of one hour (``_last_update`` cleared so the configured
    interval is used)."""
    calc._last_update = None
    r = PowerReadings(solar_power=solar_w, grid_power=export_w)
    r.calculate_derived()
    energy = calc.calculate_energy(r)
    return calc.calculate_costs(energy)


@pytest.mark.unit
@freeze_time("2026-10-13 12:00:00")
class TestLiveIntensityCounts:

    def test_flag_off_keeps_the_fixed_number(self):
        calc = _calc()
        calc.set_grid_co2_intensity(0.096, live=False)
        costs = _hour(calc)
        used = 2.0 - 0.5
        assert costs.daily_co2_avoided_kg == pytest.approx(round(used * GRID_CO2_KG_PER_KWH, 2))
        assert calc._co2_correction("lifetime", None) == 0.0

    def test_flag_on_counts_the_live_value(self):
        """1.5 kWh of solar used in the house at 96 g instead of 128 g."""
        calc = _calc()
        calc.set_grid_co2_intensity(0.096, live=True)
        costs = _hour(calc)
        assert costs.daily_co2_avoided_kg == pytest.approx(round(1.5 * 0.096, 2))
        assert costs.yearly_co2_avoided_kg == pytest.approx(round(1.5 * 0.096, 1))
        assert calc._co2_correction("lifetime", None) == pytest.approx(1.5 * (0.096 - 0.128))

    def test_switching_on_adds_nothing_at_that_moment(self):
        """Two hours at the fixed value, then the flag goes on: the lifetime
        total right after the switch equals the total right before — the
        correction starts at 0 and only grows with the next kWh."""
        calc = _calc()
        calc.set_grid_co2_intensity(0.096, live=False)
        _hour(calc)
        before = _hour(calc).lifetime_co2_avoided_kg
        calc.set_grid_co2_intensity(0.096, live=True)
        after = calc.calculate_costs(calc._build_current_totals(
            *_keys())).lifetime_co2_avoided_kg
        assert after == pytest.approx(before)

    def test_a_cycle_without_a_reading_counts_the_fixed_number(self):
        calc = _calc()
        calc.set_grid_co2_intensity(None, live=True)
        costs = _hour(calc)
        assert costs.daily_co2_avoided_kg == pytest.approx(round(1.5 * GRID_CO2_KG_PER_KWH, 2))
        assert calc._co2_correction("daily", _keys()[0]) == 0.0

    def test_no_solar_used_books_no_correction(self):
        """All solar exported (or none): no kWh used in the house, nothing
        to correct."""
        calc = _calc()
        calc.set_grid_co2_intensity(0.3, live=True)
        _hour(calc, solar_w=1000.0, export_w=1000.0)
        assert calc._co2_correction("lifetime", None) == 0.0

    def test_the_correction_survives_a_restart(self):
        calc = _calc()
        calc.set_grid_co2_intensity(0.3, live=True)
        _hour(calc)
        state = calc.get_state()
        again = _calc()
        again.restore_state(state)
        assert again._co2_correction("lifetime", None) == pytest.approx(
            calc._co2_correction("lifetime", None))
        assert again._co2_correction("lifetime", None) == pytest.approx(1.5 * (0.3 - 0.128))

    def test_never_below_zero(self):
        """A clean grid (0 g) makes the correction negative; the published
        CO2 avoided floors at 0, it is a saving."""
        calc = _calc()
        calc.set_grid_co2_intensity(0.0, live=True)
        costs = _hour(calc)
        assert costs.daily_co2_avoided_kg == pytest.approx(0.0)
        assert costs.lifetime_co2_avoided_kg >= 0.0


def _keys():
    from datetime import date
    today = date(2026, 10, 13)
    return today, f"{today.year}_{today.month}", f"{today.year}"


def test_the_category_name_is_its_own():
    """The correction lives beside the energy rows; its name must not be a
    prefix any energy category shares (the rollover and seeding read rows by
    category name)."""
    assert CO2_CORRECTION_CATEGORY == "co2_live_correction"


def _coord(states, config=None):
    """A minimal coordinator for ``_grid_co2_reading``."""
    from custom_components.solar_energy_management.coordinator.coordinator import SEMCoordinator
    by_id = {s.entity_id: s for s in states}
    hass = SimpleNamespace(states=SimpleNamespace(
        async_all=lambda domain: list(states), get=lambda eid: by_id.get(eid)))
    fake = SimpleNamespace(hass=hass, config=config or {},
                           _GRID_CO2_RESCAN_S=SEMCoordinator._GRID_CO2_RESCAN_S)
    return fake, (lambda: SEMCoordinator._grid_co2_reading(fake))


@pytest.mark.unit
class TestTheCoordinatorPicksTheSource:

    def test_the_crawlers_find_is_used(self):
        fake, read = _coord([_state(96.0, PROD_ATTRS)])
        assert read() == pytest.approx(0.096)
        assert fake._grid_co2_status == {"source": "detected", "kg_per_kwh": 0.096,
                                         "fallback": False, "has_forecast": False}

    def test_the_users_pick_wins(self):
        other = _state(0.2, {"unit_of_measurement": "kgCO2/kWh"}, "sensor.a_first_by_name")
        fake, read = _coord([other, _state(96.0, PROD_ATTRS)],
                            {"grid_co2_entity": "sensor.electricity_maps_co2_intensity"})
        assert read() == pytest.approx(0.096)
        assert fake._grid_co2_status["source"] == "configured"

    def test_nothing_found_falls_back(self):
        fake, read = _coord([])
        assert read() is None
        assert fake._grid_co2_status["source"] == "none"
        assert fake._grid_co2_status["fallback"] is True

    def test_an_unavailable_source_falls_back_but_keeps_its_kind(self):
        fake, read = _coord([_state("unavailable", PROD_ATTRS)])
        assert read() is None
        assert fake._grid_co2_status == {"source": "detected", "kg_per_kwh": None,
                                         "fallback": True, "has_forecast": False}

    def test_the_status_never_holds_an_entity_id(self):
        fake, read = _coord([_state(96.0, PROD_ATTRS)])
        read()
        assert "sensor." not in repr(fake._grid_co2_status)

    def test_a_sensor_added_later_is_found_after_the_rescan(self, monkeypatch):
        states = []
        fake, read = _coord(states)
        clock = {"t": 1000.0}
        import time as _time
        monkeypatch.setattr(_time, "monotonic", lambda: clock["t"])
        assert read() is None
        states.append(_state(96.0, PROD_ATTRS))
        fake.hass.states.get = lambda eid: states[0] if eid == states[0].entity_id else None
        assert read() is None                       # within the rescan window
        clock["t"] += fake._GRID_CO2_RESCAN_S + 1
        assert read() == pytest.approx(0.096)


@pytest.mark.unit
def test_the_pick_is_redacted_in_diagnostics():
    from custom_components.solar_energy_management.diagnostics import REDACT_CONFIG_KEYS
    assert "grid_co2_entity" in REDACT_CONFIG_KEYS


@pytest.mark.unit
def test_a_removed_sensor_is_replaced_after_the_rescan(monkeypatch):
    """The detected sensor disappears (integration removed) and another
    appears: SEM drops the dead id and finds the new one on the rescan."""
    import time as _time
    first = _state(96.0, PROD_ATTRS)
    states = [first]
    fake, read = _coord(states)
    clock = {"t": 1000.0}
    monkeypatch.setattr(_time, "monotonic", lambda: clock["t"])
    assert read() == pytest.approx(0.096)
    states.clear()
    second = _state(0.2, {"unit_of_measurement": "kgCO2/kWh"}, "sensor.new_source")
    states.append(second)
    fake.hass.states.get = lambda eid: second if eid == "sensor.new_source" else None
    assert read() is None                     # the old id is gone
    clock["t"] += fake._GRID_CO2_RESCAN_S + 1
    assert read() == pytest.approx(0.2)


@pytest.mark.unit
@freeze_time("2026-10-13 12:00:00")
def test_a_negative_daily_correction_survives_the_store():
    """A grid cleaner than 0.128 kg/kWh makes today's correction NEGATIVE.
    The store's repair resets negative daily kWh rows to 0 — this row is kg
    of correction, and a restart must not wipe today's live CO2 count."""
    from custom_components.solar_energy_management.coordinator.storage import SEMStorage
    calc = _calc()
    calc.set_grid_co2_intensity(0.05, live=True)
    _hour(calc)
    day_key = f"{CO2_CORRECTION_CATEGORY}_{_keys()[0]}"
    state = calc.get_state()
    assert state["daily_accumulators"][day_key] == pytest.approx(1.5 * (0.05 - 0.128))
    assert SEMStorage._repair_accumulator_dicts(state, ("daily_accumulators",))
    assert state["daily_accumulators"][day_key] == pytest.approx(1.5 * (0.05 - 0.128))
    again = _calc()
    again.restore_state(state)
    assert again._co2_correction("daily", _keys()[0]) == pytest.approx(1.5 * (0.05 - 0.128))
