"""#1085 Part A — the grid CO2 forecast feeding the 24-48h plan card.

``_grid_co2_reading`` (#1088) already finds the entity and reports a live
``kg_per_kwh`` value every cycle; this adds the FORWARD-LOOKING half —
reading that same entity's own forecast attribute (already detected, never
previously consumed) into a ``[(start, kg)]`` series, and ``_co2_at(when)``
looks it up the same way ``_temperature_at`` looks up the outdoor-temp
forecast (#1082): live for the next 30 minutes, the covering forecast row
beyond that, ``None`` past the forecast.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

NOW = datetime(2026, 10, 29, 12, 0, tzinfo=timezone.utc)


def _coord(*, status=None, eid=None, forecast_attr=None, forecast=None,
           forecast_at=-1e9):
    c = SEMCoordinator.__new__(SEMCoordinator)
    c.hass = MagicMock()
    c._grid_co2_status = status or {}
    c._grid_co2_eid = eid
    c._grid_co2_forecast_attr = forecast_attr
    c._co2_forecast = forecast or []
    c._co2_forecast_at = forecast_at
    return c


@pytest.mark.unit
class TestCo2At:
    def test_the_next_30_minutes_use_the_live_reading(self):
        c = _coord(status={"kg_per_kwh": 0.21})
        with _frozen(NOW):
            assert c._co2_at(NOW + timedelta(minutes=10)) == 0.21

    def test_a_forecast_row_covers_the_time_it_starts(self):
        rows = [(NOW + timedelta(hours=1), 0.15),
                (NOW + timedelta(hours=2), 0.22)]
        c = _coord(status={"kg_per_kwh": 0.21}, forecast=rows)
        with _frozen(NOW):
            assert c._co2_at(NOW + timedelta(hours=1, minutes=30)) == 0.15
            assert c._co2_at(NOW + timedelta(hours=2, minutes=1)) == 0.22

    def test_the_last_row_covers_one_hour_then_stops(self):
        rows = [(NOW + timedelta(hours=1), 0.15)]
        c = _coord(forecast=rows)
        with _frozen(NOW):
            assert c._co2_at(NOW + timedelta(hours=1, minutes=59)) == 0.15
            assert c._co2_at(NOW + timedelta(hours=2, minutes=1)) is None

    def test_no_forecast_and_beyond_live_is_none(self):
        c = _coord(status={"kg_per_kwh": 0.21})
        with _frozen(NOW):
            assert c._co2_at(NOW + timedelta(hours=5)) is None

    def test_a_broken_lookup_never_raises(self):
        c = _coord()
        c._grid_co2_status = None  # malformed on purpose
        assert c._co2_at(NOW + timedelta(minutes=5)) is None


def _state(attrs, unit="kgCO2/kWh"):
    return SimpleNamespace(state="0.2",
                            attributes={"unit_of_measurement": unit, **attrs})


@pytest.mark.unit
class TestMaybeRefreshCo2Forecast:
    def test_no_entity_or_no_forecast_attribute_clears_the_series(self):
        c = _coord(forecast=[("stale", 1.0)])
        c._maybe_refresh_co2_forecast()
        assert c._co2_forecast == []

    def test_a_found_series_is_parsed_and_unit_converted(self):
        c = _coord(eid="sensor.co2", forecast_attr="forecast")
        c.hass.states.get = MagicMock(return_value=_state(
            {"forecast": [{"from": "2026-10-29T13:00:00+00:00", "intensity": 210}]},
            unit="gCO2eq/kWh"))
        c._maybe_refresh_co2_forecast()
        assert len(c._co2_forecast) == 1
        start, kg = c._co2_forecast[0]
        assert kg == pytest.approx(0.210)

    def test_an_implausible_row_is_dropped(self):
        """Same sanity bound as read_co2_intensity_kg: >1.5 kg/kWh is a
        unit or sensor fault, never a real grid."""
        c = _coord(eid="sensor.co2", forecast_attr="forecast")
        c.hass.states.get = MagicMock(return_value=_state(
            {"forecast": [{"from": "2026-10-29T13:00:00+00:00", "intensity": 9999}]},
            unit="gCO2eq/kWh"))
        c._maybe_refresh_co2_forecast()
        assert c._co2_forecast == []

    def test_throttled_within_the_refresh_window(self):
        c = _coord(eid="sensor.co2", forecast_attr="forecast",
                   forecast_at=__import__("time").monotonic())
        c.hass.states.get = MagicMock(return_value=_state(
            {"forecast": [{"from": "2026-10-29T13:00:00+00:00", "intensity": 210}]}))
        c._maybe_refresh_co2_forecast()
        c.hass.states.get.assert_not_called()

    def test_a_missing_state_clears_the_series_without_raising(self):
        c = _coord(eid="sensor.co2", forecast_attr="forecast",
                    forecast=[("stale", 1.0)])
        c.hass.states.get = MagicMock(return_value=None)
        c._maybe_refresh_co2_forecast()
        assert c._co2_forecast == []


class _frozen:
    """Freeze dt_util.now() for the duration of a ``with`` block — a tiny
    local double, since this module's only time dependency is that one
    call inside ``_co2_at``."""
    def __init__(self, when):
        self._when = when
        self._orig = None

    def __enter__(self):
        import custom_components.solar_energy_management.coordinator.coordinator as mod
        self._orig = mod.dt_util.now
        mod.dt_util.now = lambda: self._when
        return self

    def __exit__(self, *exc):
        import custom_components.solar_energy_management.coordinator.coordinator as mod
        mod.dt_util.now = self._orig


class TestThePlanSensorCarriesCo2:
    """The card tooltip reads ``slot.co2``; the sensor must not drop it."""

    def test_a_slot_with_a_reading_keeps_it(self):
        from custom_components.solar_energy_management.sensor import (
            _energy_plan_attrs,
        )
        attrs = _energy_plan_attrs({"demands": [], "slots": [
            {"start": "a", "end": "b", "price": 0.2, "cheap": False,
             "home_grid_w": 0.0, "co2": 0.31},
            {"start": "b", "end": "c", "price": 0.2, "cheap": False,
             "home_grid_w": 0.0, "co2": None},
            {"start": "c", "end": "d", "price": 0.2, "cheap": False,
             "home_grid_w": 0.0},
        ]})
        assert attrs["slots"][0]["co2"] == 0.31
        assert "co2" not in attrs["slots"][1]
        assert "co2" not in attrs["slots"][2]
