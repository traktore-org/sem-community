"""Tests for conservative discovery of direct per-phase grid current sensors."""
from types import SimpleNamespace

from custom_components.solar_energy_management.coordinator.phase_current_discovery import (
    discover_grid_phase_current_entities,
)


def _state(entity_id, value="8", unit="A", friendly_name=None):
    return SimpleNamespace(
        entity_id=entity_id,
        state=value,
        attributes={
            "unit_of_measurement": unit,
            "friendly_name": friendly_name or entity_id,
        },
    )


def test_discovers_complete_same_family_grid_current_triplet():
    states = [
        _state(f"sensor.smart_meter_grid_l{phase}_current")
        for phase in range(1, 4)
    ]

    result = discover_grid_phase_current_entities(states)

    assert result == {
        "phase_guard_grid_l1_current_entity": "sensor.smart_meter_grid_l1_current",
        "phase_guard_grid_l2_current_entity": "sensor.smart_meter_grid_l2_current",
        "phase_guard_grid_l3_current_entity": "sensor.smart_meter_grid_l3_current",
    }


def test_rejects_incomplete_or_mixed_current_families():
    states = [
        _state("sensor.meter_a_grid_l1_current"),
        _state("sensor.meter_a_grid_l2_current"),
        _state("sensor.meter_b_grid_l3_current"),
    ]

    assert discover_grid_phase_current_entities(states) == {}


def test_rejects_wrong_units_invalid_values_and_non_grid_currents():
    states = [
        _state("sensor.grid_l1_current", value="8000", unit="mA"),
        _state("sensor.grid_l2_current", value="unavailable"),
        _state("sensor.grid_l3_current", value="8"),
        _state("sensor.inverter_output_l1_current"),
        _state("sensor.inverter_output_l2_current"),
        _state("sensor.inverter_output_l3_current"),
    ]

    assert discover_grid_phase_current_entities(states) == {}
