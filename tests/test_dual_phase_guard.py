"""Regression tests for the generic dual per-phase guard."""

from datetime import timedelta
from types import SimpleNamespace

import pytest

from custom_components.solar_energy_management.coordinator.dual_phase_guard import (
    evaluate_dual_phase_guard,
)


class _States:
    def __init__(self, states):
        self._states = states

    def get(self, entity_id):
        return self._states.get(entity_id)


def _state(value, unit=None, age_seconds=0):
    from homeassistant.util import dt as dt_util

    return SimpleNamespace(
        state=str(value),
        attributes={"unit_of_measurement": unit} if unit else {},
        last_updated=dt_util.utcnow() - timedelta(seconds=age_seconds),
    )


def _guard_config():
    cfg = {
        "phase_guard_enabled": True,
        "phase_guard_topology": "hybrid_load_port",
        "phase_guard_grid_limit_a": 16,
        "phase_guard_inverter_limit_a": 16,
        "phase_guard_max_age_s": 30,
    }
    for phase in range(1, 4):
        cfg[f"phase_guard_grid_l{phase}_power_entity"] = f"sensor.grid_l{phase}_power"
        cfg[f"phase_guard_grid_l{phase}_voltage_entity"] = f"sensor.grid_l{phase}_voltage"
        cfg[f"phase_guard_inverter_l{phase}_current_entity"] = f"sensor.internal_ct{phase}_current"
    return cfg


def _healthy_states():
    states = {}
    for phase in range(1, 4):
        states[f"sensor.grid_l{phase}_power"] = _state(
            -2300 if phase == 3 else 2300, "W"
        )
        states[f"sensor.grid_l{phase}_voltage"] = _state(230, "V")
        states[f"sensor.internal_ct{phase}_current"] = _state(12, "A")
    return states


def test_dual_guard_keeps_lanes_independent_and_handles_export():
    result = evaluate_dual_phase_guard(_States(_healthy_states()), _guard_config())

    assert result["mode"] == "observer"
    assert result["read_only"] is True
    assert result["safe"] is True
    assert result["data_fresh"] is True
    assert result["grid"]["l3"]["current_a"] == pytest.approx(10.0)
    assert result["grid"]["l3"]["margin_a"] == pytest.approx(6.0)
    assert result["inverter"]["l3"]["current_a"] == pytest.approx(12.0)
    assert result["inverter"]["l3"]["margin_a"] == pytest.approx(4.0)


def test_grid_lane_prefers_direct_rms_current_over_power_voltage_fallback():
    states = _healthy_states()
    config = _guard_config()
    for phase in range(1, 4):
        config[f"phase_guard_grid_l{phase}_current_entity"] = (
            f"sensor.smart_meter_grid_l{phase}_current"
        )
        states[f"sensor.smart_meter_grid_l{phase}_current"] = _state(7 + phase, "A")
        states.pop(f"sensor.grid_l{phase}_power")
        states.pop(f"sensor.grid_l{phase}_voltage")

    result = evaluate_dual_phase_guard(_States(states), config)

    assert result["safe"] is True
    assert result["grid"]["l1"]["current_a"] == pytest.approx(8.0)
    assert result["grid"]["l1"]["source"] == "direct_current"


def test_grid_direct_current_fails_closed_instead_of_falling_back_when_invalid():
    states = _healthy_states()
    config = _guard_config()
    for phase in range(1, 4):
        entity_id = f"sensor.grid_l{phase}_current"
        config[f"phase_guard_grid_l{phase}_current_entity"] = entity_id
        states[entity_id] = _state(8, "A")
    states["sensor.grid_l1_current"] = _state("unavailable", "A")

    result = evaluate_dual_phase_guard(_States(states), config)

    assert result["safe"] is False
    assert result["grid"]["l1"]["source"] == "direct_current"
    assert "grid:l1:unavailable" in result["stop_reason"]


def test_partial_direct_grid_current_triplet_is_invalid_configuration():
    config = _guard_config()
    config["phase_guard_grid_l1_current_entity"] = "sensor.grid_l1_current"

    result = evaluate_dual_phase_guard(_States(_healthy_states()), config)

    assert result["safe"] is False
    assert result["data_fresh"] is False
    assert result["stop_reason"] == "invalid_configuration"


def test_grid_power_voltage_fallback_reports_derived_source():
    result = evaluate_dual_phase_guard(_States(_healthy_states()), _guard_config())

    assert result["grid"]["l1"]["source"] == "derived_power_voltage"


def test_dual_guard_over_limit_names_lane_and_phase():
    states = _healthy_states()
    states["sensor.internal_ct2_current"] = _state(16.5, "A")

    result = evaluate_dual_phase_guard(_States(states), _guard_config())

    assert result["safe"] is False
    assert result["inverter"]["l2"]["safe"] is False
    assert "inverter:l2:over_limit" in result["stop_reason"]


def test_negative_rms_current_fails_closed_instead_of_creating_margin():
    states = _healthy_states()
    states["sensor.internal_ct2_current"] = _state(-1, "A")

    result = evaluate_dual_phase_guard(_States(states), _guard_config())

    assert result["safe"] is False
    assert result["inverter"]["l2"]["current_a"] is None
    assert "inverter:l2:invalid_current" in result["stop_reason"]


def test_grid_only_topology_does_not_require_inverter_lane_sensors():
    config = _guard_config()
    config["phase_guard_topology"] = "grid_only"
    for phase in range(1, 4):
        config.pop(f"phase_guard_inverter_l{phase}_current_entity")

    result = evaluate_dual_phase_guard(_States(_healthy_states()), config)

    assert result["safe"] is True
    assert result["data_fresh"] is True
    assert result["inverter"] == {}


@pytest.mark.parametrize(
    ("entity", "replacement_factory", "reason"),
    [
        (
            "sensor.grid_l1_power",
            lambda: _state(2.3, "kW"),
            "grid:l1:invalid_unit",
        ),
        (
            "sensor.grid_l1_voltage",
            lambda: _state(0.23, "kV"),
            "grid:l1:invalid_unit",
        ),
        (
            "sensor.internal_ct1_current",
            lambda: _state(12000, "mA"),
            "inverter:l1:invalid_unit",
        ),
    ],
)
def test_dual_guard_fails_closed_for_wrong_sensor_units(
    entity, replacement_factory, reason
):
    states = _healthy_states()
    states[entity] = replacement_factory()

    result = evaluate_dual_phase_guard(_States(states), _guard_config())

    assert result["safe"] is False
    assert result["data_fresh"] is False
    assert reason in result["stop_reason"]


def test_dual_guard_fails_closed_for_non_finite_limits():
    config = _guard_config()
    config["phase_guard_grid_limit_a"] = float("nan")

    result = evaluate_dual_phase_guard(_States(_healthy_states()), config)

    assert result["safe"] is False
    assert result["data_fresh"] is False
    assert result["stop_reason"] == "invalid_configuration"


@pytest.mark.parametrize(
    ("entity", "replacement_factory", "reason"),
    [
        ("sensor.grid_l1_power", lambda: None, "grid:l1:missing"),
        (
            "sensor.grid_l1_voltage",
            lambda: _state(0, "V"),
            "grid:l1:invalid_voltage",
        ),
        (
            "sensor.internal_ct3_current",
            lambda: _state("unknown", "A"),
            "inverter:l3:unknown",
        ),
        (
            "sensor.internal_ct1_current",
            lambda: _state(10, "A", age_seconds=31),
            "inverter:l1:stale",
        ),
    ],
)
def test_dual_guard_fails_closed_for_bad_or_stale_data(
    entity, replacement_factory, reason
):
    states = _healthy_states()
    replacement = replacement_factory()
    if replacement is None:
        states.pop(entity)
    else:
        states[entity] = replacement

    result = evaluate_dual_phase_guard(_States(states), _guard_config())

    assert result["safe"] is False
    assert result["data_fresh"] is False
    assert reason in result["stop_reason"]


def test_a_flat_but_alive_sensor_is_fresh_not_stale():
    """A healthy sensor holding a constant reading (grid voltage rounding to
    230 for minutes, a quiet phase at 0 W all night) only bumps
    last_REPORTED — HA moves last_updated exclusively on value/attribute
    CHANGES. Keying freshness on last_updated declared exactly those
    healthy-but-flat sensors stale and failed the guard closed on a healthy
    install (caught live on the HA-TEST rig, 2026-08-02)."""
    from homeassistant.util import dt as dt_util

    states = _healthy_states()
    flat = states["sensor.grid_l1_voltage"]
    flat.last_updated = dt_util.utcnow() - timedelta(seconds=600)  # flat for 10 min
    flat.last_reported = dt_util.utcnow() - timedelta(seconds=2)   # but reporting

    result = evaluate_dual_phase_guard(_States(states), _guard_config())

    assert result["safe"] is True
    assert result["data_fresh"] is True


def test_a_sensor_that_stopped_reporting_is_still_stale():
    """The counterpart: last_reported old = genuinely dead, regardless of
    what last_updated says. Fail closed."""
    from homeassistant.util import dt as dt_util

    states = _healthy_states()
    dead = states["sensor.grid_l1_voltage"]
    dead.last_updated = dt_util.utcnow() - timedelta(seconds=600)
    dead.last_reported = dt_util.utcnow() - timedelta(seconds=600)

    result = evaluate_dual_phase_guard(_States(states), _guard_config())

    assert result["safe"] is False
    assert "stale" in (result["stop_reason"] or "")
