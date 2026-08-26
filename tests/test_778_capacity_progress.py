"""#778 — the pack-size learner's progress must count what already
qualifies, not read 0 until the verdict lands.

PROD 26.08 (Guido, screenshot of the Battery tab): "Measured pack size —
Learning · 0 / 5 nights" while storage held FOUR sealed nights that pass
every gate (trainable, ≥15 % SOC span, positive drain). `measured_capacity`
returns None below MIN_SAMPLES and throws the count away with it, so the
surface said "nothing learned" on the night before the verdict.
"""
from __future__ import annotations

from custom_components.solar_energy_management.coordinator.measured_capacity import (
    MIN_SAMPLES,
    capacity_progress,
    measured_capacity,
)

#: PROD's sealed nights on 26.08, verbatim shape.
PROD_NIGHTS = [
    {"date": "2026-08-19", "trainable": False, "soc_start": 94.0, "soc_morning": 52.0, "drain_kwh": 5.148},
    {"date": "2026-08-20", "trainable": False, "soc_start": 52.0, "soc_morning": 52.0, "drain_kwh": 0.0},
    {"date": "2026-08-20", "trainable": True, "soc_start": 92.0, "soc_morning": 54.0, "drain_kwh": 4.795},
    {"date": "2026-08-21", "trainable": True, "soc_start": 54.0, "soc_morning": 54.0, "drain_kwh": 0.004},
    {"date": "2026-08-21", "trainable": False, "soc_start": 32.0, "soc_morning": 26.0, "drain_kwh": 0.697},
    {"date": "2026-08-22", "trainable": True, "soc_start": 97.0, "soc_morning": 58.0, "drain_kwh": 4.706},
    {"date": "2026-08-23", "trainable": True, "soc_start": 97.0, "soc_morning": 57.0, "drain_kwh": 5.109},
    {"date": "2026-08-24", "trainable": True, "soc_start": 96.0, "soc_morning": 57.0, "drain_kwh": 4.924},
]


def test_prods_four_qualifying_nights_count_as_progress():
    assert measured_capacity(PROD_NIGHTS) is None          # verdict still pending…
    assert capacity_progress(PROD_NIGHTS) == 4              # …but 4 of 5 is the truth


def test_progress_applies_the_same_gates_as_the_verdict():
    # untrainable, flat SOC and rising SOC never count
    assert capacity_progress([PROD_NIGHTS[0], PROD_NIGHTS[1], PROD_NIGHTS[3]]) == 0
    assert capacity_progress(None) == 0
    assert capacity_progress([]) == 0


def test_progress_and_verdict_agree_once_the_verdict_exists():
    nights = PROD_NIGHTS + [
        {"date": "2026-08-25", "trainable": True, "soc_start": 95.0, "soc_morning": 56.0, "drain_kwh": 4.9},
    ]
    cap = measured_capacity(nights)
    assert cap is not None and cap.samples == MIN_SAMPLES
    assert capacity_progress(nights) == cap.samples


def test_the_coordinator_publishes_progress_not_zero():
    import inspect
    from custom_components.solar_energy_management.coordinator import coordinator as cm
    src = inspect.getsource(cm)
    assert "capacity_progress(sealed)" in src
    assert '"battery_capacity_samples": 0 if cap is None else cap.samples' not in src
