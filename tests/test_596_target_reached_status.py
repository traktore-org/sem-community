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


# ── #596 root cause: the fleet charging_state must adopt the single charger's
# effective state (the global state machine runs before the per-charger loop
# refines terminal states). This is the piece that actually made PROD show
# "active" while the charger was night_target_reached. ──
from custom_components.solar_energy_management.const import ChargingState
from custom_components.solar_energy_management.coordinator.coordinator import (
    SEMCoordinator,
)

_resolve = SEMCoordinator._resolve_fleet_charging_state
GLOBAL = ChargingState.NIGHT_CHARGING_ACTIVE


def test_single_charger_adopts_effective_target_reached():
    # THE bug: one charger at night_target_reached → fleet must reflect it.
    eff = {"ev_charger": (ChargingState.NIGHT_TARGET_REACHED, "EV")}
    assert _resolve(GLOBAL, eff) == ChargingState.NIGHT_TARGET_REACHED


def test_single_charger_adopts_effective_solar_idle():
    eff = {"ev_charger": (ChargingState.SOLAR_IDLE, "EV")}
    assert _resolve(GLOBAL, eff) == ChargingState.SOLAR_IDLE


def test_multi_charger_keeps_global_master_state():
    # Chargers can disagree — must NOT collapse to one (#351 M4).
    eff = {
        "a": (ChargingState.NIGHT_TARGET_REACHED, "A"),
        "b": (ChargingState.NIGHT_CHARGING_ACTIVE, "B"),
    }
    assert _resolve(GLOBAL, eff) == GLOBAL


def test_zero_chargers_keeps_global_state():
    assert _resolve(GLOBAL, {}) == GLOBAL


def test_single_charger_none_effective_falls_back_to_global():
    assert _resolve(GLOBAL, {"ev_charger": (None, "EV")}) == GLOBAL


def test_end_to_end_single_charger_target_reached_status():
    # The two fixes together: rollup adopts night_target_reached, and the
    # status getter maps that to "target_reached" (not "active").
    eff = {"ev_charger": (ChargingState.NIGHT_TARGET_REACHED, "EV")}
    fleet = _resolve(GLOBAL, eff)
    d = SEMData()
    d.charging_state = str(getattr(fleet, "value", fleet))
    assert d._get_night_charging_status() == "target_reached"
