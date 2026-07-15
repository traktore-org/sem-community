"""#596 — a terminal ``*_target_reached`` charging state must report the
``"target_reached"`` derived status, NOT ``"active"``.

Caught on PROD during an overnight ``min_plus_solar`` soak: the charger had
correctly stopped at the night target (0 A / 0 W) but
``sensor.sem_night_charging_status`` still read ``"active"`` because
``night_target_reached`` was bucketed with the truly-active states. Same class
lived in the solar getter (``solar_target_reached``). These tests pin BOTH
siblings so the class can't regress.
"""

import pytest

from custom_components.solar_energy_management.coordinator.types import SEMData


def _status(charging_state, which):
    d = SEMData()
    d.charging_state = charging_state
    return getattr(d, f"_get_{which}_charging_status")()


# ── the bug: terminal target-reached must be "target_reached", not "active" ──
@pytest.mark.parametrize(
    "state,which",
    [
        ("night_target_reached", "night"),
        ("solar_target_reached", "solar"),
    ],
)
def test_target_reached_is_not_active(state, which):
    assert _status(state, which) == "target_reached"


# ── the truly-active states must still report "active" (no over-correction) ──
@pytest.mark.parametrize(
    "state,which",
    [
        ("night_charging_active", "night"),
        ("solar_charging_active", "solar"),
        ("solar_super_charging", "solar"),
        ("solar_min_pv", "solar"),
    ],
)
def test_active_states_stay_active(state, which):
    assert _status(state, which) == "active"


# ── unrelated / off states stay idle ──
@pytest.mark.parametrize(
    "state,which",
    [
        ("idle", "night"),
        ("idle", "solar"),
        ("off", "night"),
        ("disabled", "solar"),
    ],
)
def test_idle_states_stay_idle(state, which):
    assert _status(state, which) == "idle"


def test_night_disabled_still_resolves_non_active():
    # night_disabled must not read as "active": it matches the `night` elif
    # and strips the prefix → "disabled".
    assert _status("night_disabled", "night") == "disabled"
