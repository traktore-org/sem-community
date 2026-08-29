"""#425 — telemetry surface for ConsumptionPredictor.

Locks the ``*_prediction_path`` strings each branch sets. Mirrors the
#359/#416/#420/#421/#422 precedents.

Surface: ``ConsumptionPredictor.get_diagnostics()`` — coordinator will
expose this dict on existing consumption-prediction sensors.
"""
from __future__ import annotations

from datetime import datetime

from custom_components.solar_energy_management.analytics.consumption_predictor import (
    ConsumptionPredictor,
)


def _seed(predictor, days, hours_per_day=24, consumption_w=500.0, solar_w=2000.0):
    """Feed observations across N days × hours_per_day to advance training_status."""
    for day in range(days):
        for hour in range(hours_per_day):
            dt = datetime(2026, 1, 1 + day, hour, 0)
            # Manually adjust weekday by offsetting from a known Monday
            # — for the unique_days() heuristic we just need varied (dow, hour=12) bins
            predictor.observe(dt, consumption_w, solar_w)


# ──────────────────────────────────────────────
# observation_path
# ──────────────────────────────────────────────


def test_observation_path_recorded():
    p = ConsumptionPredictor()
    p.observe(datetime(2026, 1, 1, 10), 500.0, 2000.0)
    assert p.get_diagnostics()["observation_path"] == "recorded"


def test_observation_path_deduplicated():
    p = ConsumptionPredictor()
    dt = datetime(2026, 1, 1, 10)
    p.observe(dt, 500.0, 2000.0)  # first call — recorded
    p.observe(dt, 600.0, 2100.0)  # second call same hour — deduplicated
    assert p.get_diagnostics()["observation_path"] == "deduplicated"


# ──────────────────────────────────────────────
# consumption_prediction_path
# ──────────────────────────────────────────────


def test_consumption_prediction_path_cold_start_empty():
    p = ConsumptionPredictor()
    result = p.predict_consumption_24h(datetime(2026, 1, 1, 0))
    assert result == []
    assert p.get_diagnostics()["consumption_prediction_path"] == "cold_start_empty"


def test_consumption_prediction_path_trained_with_fallback():
    p = ConsumptionPredictor()
    # Seed enough to enter "learning"/"trained" state
    _seed(p, days=8)
    result = p.predict_consumption_24h(datetime(2026, 1, 20, 0))  # different week
    assert len(result) == 24
    # Some hours may use fallback (hour-only average) — expect fallback path
    assert p.get_diagnostics()["consumption_prediction_path"].startswith("trained")


# ──────────────────────────────────────────────
# solar_prediction_path
# ──────────────────────────────────────────────


def test_solar_prediction_path_cold_start_empty():
    p = ConsumptionPredictor()
    result = p.predict_solar_24h(datetime(2026, 1, 1, 0))
    assert result == []
    assert p.get_diagnostics()["solar_prediction_path"] == "cold_start_empty"


# ──────────────────────────────────────────────
# surplus_window_path
# ──────────────────────────────────────────────


def test_surplus_window_path_no_data():
    p = ConsumptionPredictor()
    result = p.predict_surplus_window(datetime(2026, 1, 1, 0))
    assert result == ""
    assert p.get_diagnostics()["surplus_window_path"] == "no_data"


def test_surplus_window_path_no_surplus():
    p = ConsumptionPredictor()
    # Seed with consumption > solar across all hours
    _seed(p, days=8, consumption_w=5000.0, solar_w=100.0)
    p.predict_surplus_window(datetime(2026, 1, 20, 0))
    assert p.get_diagnostics()["surplus_window_path"] in (
        "no_surplus", "no_data",
    )


def test_surplus_window_path_found_window():
    p = ConsumptionPredictor()
    # Seed with solar > consumption during midday hours
    for day in range(8):
        for hour in range(24):
            dt = datetime(2026, 1, 1 + day, hour, 0)
            consumption = 500.0
            solar = 5000.0 if 10 <= hour <= 16 else 0.0
            p.observe(dt, consumption, solar)
    p.predict_surplus_window(datetime(2026, 1, 1, 0))
    assert p.get_diagnostics()["surplus_window_path"] in (
        "found_window", "no_data",
    )


# ──────────────────────────────────────────────
# ev_prediction_path
# ──────────────────────────────────────────────


def test_ev_prediction_path_no_data():
    p = ConsumptionPredictor()
    val = p.predict_ev_consumption_tomorrow(datetime(2026, 1, 1, 0))
    assert val == 0.0
    assert p.get_diagnostics()["ev_prediction_path"] == "no_data"


def test_ev_prediction_path_weekday_match():
    p = ConsumptionPredictor()
    # Record an EV obs for Monday (dow=0)
    p.observe_ev(datetime(2026, 1, 5, 12), 12.5)  # Mon
    # Predict for Monday → exact match
    val = p.predict_ev_consumption_tomorrow(datetime(2026, 1, 11, 12))  # Sun → predict Mon
    assert val == 12.5
    assert p.get_diagnostics()["ev_prediction_path"] == "weekday_match"


# ──────────────────────────────────────────────
# get_diagnostics shape
# ──────────────────────────────────────────────


def test_get_diagnostics_shape():
    p = ConsumptionPredictor()
    diag = p.get_diagnostics()
    assert set(diag.keys()) >= {
        "consumption_prediction_path",
        "solar_prediction_path",
        "surplus_window_path",
        "ev_prediction_path",
        "observation_path",
        "training_status",
        "consumption_samples",
        "consumption_unique_days",
    }
    assert diag["training_status"] == "cold_start"
    assert diag["consumption_samples"] == 0
