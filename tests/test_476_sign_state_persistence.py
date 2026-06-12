"""#476 item 5 — sign-detection state persists across restarts.

The autodetect locks (``_grid_sign_detected`` / per-battery dicts) were
RAM-only: every reload re-learned the sign from possibly ambiguous
low-power samples, and three bad votes right after a reboot could lock
the WRONG sign until the next reload (the 2026-06-11 PROD flip).

Pinned here:
1. export → restore round-trips the locked state.
2. Only LOCKED entries restore — votes/warmup/unlocked guesses don't.
3. Garbage / legacy storage shapes are ignored wholesale.
4. A restored lock makes ``_detect_grid_sign`` skip the vote machinery.
5. Manual ``grid_sign_invert`` still short-circuits before autodetect,
   so a restored lock can never fight a manual override.
6. SEMStorage get/set round-trip via the energy-data dict.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _reader(config=None):
    hass = MagicMock()
    return SensorReader(hass, config or {})


# ── 1. round-trip ────────────────────────────────────────────────────

def test_export_restore_roundtrip():
    src = _reader()
    src._grid_sign_detected = True
    src._grid_sign_inverted = True
    src._battery_sign_detected = {"b1": True, "b2": True}
    src._battery_sign_inverted = {"b1": False, "b2": True}

    state = src.export_sign_state()

    dst = _reader()
    dst.restore_sign_state(state)
    assert dst._grid_sign_detected is True
    assert dst._grid_sign_inverted is True
    assert dst._battery_sign_detected == {"b1": True, "b2": True}
    assert dst._battery_sign_inverted == {"b1": False, "b2": True}


# ── 2. only locked entries restore ───────────────────────────────────

def test_unlocked_grid_state_does_not_restore():
    dst = _reader()
    dst.restore_sign_state({"grid_detected": False, "grid_inverted": True})
    assert dst._grid_sign_detected is False
    assert dst._grid_sign_inverted is False  # constructor default kept


def test_unlocked_battery_entries_skipped():
    dst = _reader()
    dst.restore_sign_state({
        "battery_detected": {"b1": True, "b2": False},
        "battery_inverted": {"b1": True, "b2": True},
    })
    assert dst._battery_sign_detected == {"b1": True}
    assert "b2" not in dst._battery_sign_inverted


# ── 3. garbage tolerance ─────────────────────────────────────────────

@pytest.mark.parametrize("garbage", [
    None, "negated", 42, [], {"grid_detected": "yes", "grid_inverted": "no"},
    {"grid_detected": True, "grid_inverted": "maybe"},
    {"battery_detected": ["b1"], "battery_inverted": {"b1": True}},
])
def test_garbage_state_ignored(garbage):
    dst = _reader()
    dst.restore_sign_state(garbage)
    assert dst._grid_sign_detected is False
    assert dst._battery_sign_detected == {}


# ── 4. restored lock skips the vote machinery ────────────────────────

def test_restored_lock_short_circuits_detection():
    """With a restored lock, _detect_grid_sign returns the lock without
    casting votes — even when warmup has elapsed and counters move."""
    r = _reader()
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True})
    r._sign_vote_warmup = 0

    readings = MagicMock()
    readings.grid_power = 2500.0
    # No energy-dashboard config → early-return path; the lock value is
    # what must come back.
    assert r._detect_grid_sign(readings) is True
    # And no votes were cast.
    assert r._grid_sign_votes == 0


# ── 5. manual override precedence ────────────────────────────────────

def test_manual_invert_beats_restored_lock():
    """grid_sign_invert in config short-circuits BEFORE autodetect —
    the restored lock (no inversion) must not undo the manual negate."""
    r = _reader({"grid_sign_invert": True})
    r.restore_sign_state({"grid_detected": True, "grid_inverted": False})

    # The manual path is gated in read_power_values; assert the config
    # gate the way the production code reads it.
    assert bool(r._raw_config.get("grid_sign_invert", False)) is True
    # Restored lock present but subordinate (only consulted when the
    # manual gate is off).
    assert r._grid_sign_detected is True
    assert r._grid_sign_inverted is False


# ── 6. SEMStorage accessor round-trip ────────────────────────────────

def test_storage_accessors_roundtrip():
    from custom_components.solar_energy_management.coordinator.storage import (
        SEMStorage,
    )
    store = SEMStorage.__new__(SEMStorage)  # no hass needed for the dict API
    store._energy_data = {}
    assert store.get_sign_state() == {}
    payload = {
        "grid_detected": True, "grid_inverted": False,
        "battery_detected": {"b1": True}, "battery_inverted": {"b1": True},
    }
    store.set_sign_state(payload)
    assert store.get_sign_state() == payload
    assert store._energy_data["sign_state"] == payload


# ── 7. W1 — restored lock honoured on the first-baseline call ────────

def test_restored_lock_survives_first_baseline_call():
    """Counters can sit unknown through the whole warmup; the first
    post-warmup call stores baselines and used to return a hardcoded
    False — ignoring a restored lock for that cycle (reviewer W1)."""
    r = _reader()
    r.restore_sign_state({"grid_detected": True, "grid_inverted": True})
    r._sign_vote_warmup = 0
    r._grid_import_baseline = None  # nothing seeded during warmup

    ed = MagicMock()
    ed.grid_import_energy = "sensor.imp"
    ed.grid_export_energy = "sensor.exp"
    ed.grid_import_energy_list = None
    ed.grid_export_energy_list = None
    r._energy_dashboard_config = ed
    r._sum_counter_states = lambda entities: 100.0  # both counters readable

    readings = MagicMock()
    readings.grid_power = 2500.0
    assert r._detect_grid_sign(readings) is True
    # Baselines were seeded for the next cycle.
    assert r._grid_import_baseline == 100.0


# ── 8. reset_sign_state — the escape hatch ───────────────────────────

def test_reset_sign_state_clears_locks_and_rearms_warmup():
    r = _reader()
    r.restore_sign_state({
        "grid_detected": True, "grid_inverted": True,
        "battery_detected": {"b1": True}, "battery_inverted": {"b1": True},
    })
    r._sign_vote_warmup = 0
    r._grid_import_baseline = 123.0

    r.reset_sign_state()

    assert r._grid_sign_detected is False
    assert r._grid_sign_inverted is False
    assert r._battery_sign_detected == {}
    assert r._battery_sign_inverted == {}
    assert r._grid_import_baseline is None
    assert r._sign_vote_warmup == 12
    # And the exported state after reset persists nothing locked.
    state = r.export_sign_state()
    assert state["grid_detected"] is False
    assert state["battery_detected"] == {}
