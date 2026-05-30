"""Unit tests for the night-charging-enabled debounce (#290).

Observed live on PROD 2026-05-29 21:47 UTC: a one-cycle blip
``NIGHT_CHARGING_ACTIVE → NIGHT_DISABLED → NIGHT_CHARGING_ACTIVE``
fired immediately after a per-charger Number slider write. Root
cause: ``_any_night_charging_enabled()`` queries
``hass.states.is_state(...)`` per cycle, and there's a brief race
window during ``config_entries.async_update_entry`` where the
per-charger switch entity's state reads False before settling.

Fix: require 2 consecutive cycles of the new value before flipping
the cached state we return. Trades 10 s of responsiveness for race
immunity.

These tests pin the debounce against regression — both the
"transient blip is suppressed" property and the "legitimate
sustained change does flip after 2 cycles" property.
"""
from unittest.mock import MagicMock, patch

import pytest

from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingStateMachine,
)


def _build_state_machine(switch_returns):
    """Build a state machine whose night-enabled switch reads from a
    controllable list. Each call to ``_read_night_enabled_raw`` consumes
    the next value from ``switch_returns``; if exhausted, repeats the
    last one.
    """
    hass = MagicMock()
    # Per-charger switch lookup: we make `hass.states.is_state(...)` return
    # the next value from switch_returns each call.
    seq = iter(switch_returns)
    last = [switch_returns[0]]
    def is_state(eid, state):
        try:
            v = next(seq)
            last[0] = v
        except StopIteration:
            v = last[0]
        return v
    hass.states.is_state = is_state

    sm = ChargingStateMachine(
        hass=hass,
        config={
            "ev_chargers": [{"id": "ev_charger"}],
            "current_delta": 1,
        },
        time_manager=MagicMock(),
    )
    return sm


# ──────────────────────────────────────────────────────────────────────
# First-call semantics — commit immediately, no debounce
# ──────────────────────────────────────────────────────────────────────

class TestFirstCall:
    def test_first_call_commits_immediately_true(self):
        sm = _build_state_machine([True, True])
        assert sm._any_night_charging_enabled() is True
        assert sm._night_enabled_cached is True

    def test_first_call_commits_immediately_false(self):
        sm = _build_state_machine([False, False])
        assert sm._any_night_charging_enabled() is False
        assert sm._night_enabled_cached is False


# ──────────────────────────────────────────────────────────────────────
# Transient blip — single-cycle flip MUST be suppressed
# ──────────────────────────────────────────────────────────────────────

class TestTransientBlip:
    def test_one_cycle_off_blip_is_held_at_true(self):
        """The exact 2026-05-29 PROD repro: was True, one cycle reads False,
        next cycle reads True again. Must keep returning True throughout.
        """
        sm = _build_state_machine([True, False, True])
        # Cycle 1: commits True
        assert sm._any_night_charging_enabled() is True
        # Cycle 2: one-cycle blip to False — debounce holds True
        assert sm._any_night_charging_enabled() is True, (
            "single-cycle False blip must be suppressed — that's the "
            "whole point of the debounce"
        )
        # Cycle 3: back to True, blip cleared
        assert sm._any_night_charging_enabled() is True

    def test_one_cycle_on_blip_is_held_at_false(self):
        """Symmetric: was False, brief True, back to False. Stays False."""
        sm = _build_state_machine([False, True, False])
        assert sm._any_night_charging_enabled() is False
        assert sm._any_night_charging_enabled() is False
        assert sm._any_night_charging_enabled() is False


# ──────────────────────────────────────────────────────────────────────
# Legitimate sustained change — flips after 2 consecutive cycles
# ──────────────────────────────────────────────────────────────────────

class TestSustainedChange:
    def test_two_consecutive_off_flips_to_false(self):
        """User actually turned off the switch — must transition False
        on the SECOND cycle reading False."""
        sm = _build_state_machine([True, False, False, False])
        assert sm._any_night_charging_enabled() is True  # cycle 1: cached True
        assert sm._any_night_charging_enabled() is True  # cycle 2: pending False (1)
        assert sm._any_night_charging_enabled() is False  # cycle 3: flips on 2nd consecutive
        assert sm._any_night_charging_enabled() is False  # cycle 4: stays False

    def test_two_consecutive_on_flips_to_true(self):
        sm = _build_state_machine([False, True, True, True])
        assert sm._any_night_charging_enabled() is False
        assert sm._any_night_charging_enabled() is False
        assert sm._any_night_charging_enabled() is True
        assert sm._any_night_charging_enabled() is True


# ──────────────────────────────────────────────────────────────────────
# Pending counter resets when raw vote returns to cached
# ──────────────────────────────────────────────────────────────────────

class TestPendingReset:
    def test_pending_counter_resets_when_back_to_cached(self):
        """Was True; cycle 2 reads False (pending counter = 1); cycle 3
        reads True again — pending must reset. Cycle 4 reads False,
        pending counter starts fresh at 1 (NOT continued at 2).
        """
        sm = _build_state_machine([True, False, True, False])
        assert sm._any_night_charging_enabled() is True
        assert sm._any_night_charging_enabled() is True  # pending=1
        assert sm._any_night_charging_enabled() is True  # back to cached → pending reset
        assert sm._night_enabled_pending_cycles == 0
        # cycle 4: new disagreement, must start fresh, NOT roll over
        assert sm._any_night_charging_enabled() is True
        assert sm._night_enabled_pending_cycles == 1
