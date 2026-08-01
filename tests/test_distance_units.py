"""Regression tests for vehicle-range distance normalisation."""

import pytest

from custom_components.solar_energy_management.coordinator.distance_units import (
    distance_to_km,
)


def test_distance_metres_are_normalised_to_km():
    assert distance_to_km(1_057_000, "m") == pytest.approx(1057.0)


def test_distance_miles_are_normalised_to_km():
    assert distance_to_km(100, "mi") == pytest.approx(160.9344)


@pytest.mark.parametrize("unit", [None, "", "yards", "bananas"])
def test_distance_unknown_unit_fails_closed(unit):
    assert distance_to_km(1057000, unit) is None
