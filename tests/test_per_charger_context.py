"""Tests for ``coordinator/per_charger_context.py`` (v1.6.7).

The context manager is a mechanical lift of the ad-hoc ``saved = {...}``
swap dict at ``coordinator.py:1136-1258``. These tests pin:

1. The swap captures every primary-charger attribute the legacy code
   captured (no field bleeds into the next iteration).
2. The save-back persists this charger's state to the
   ``_ev_*_per_charger`` dicts.
3. The restore is idempotent on exceptions (the ``finally``-like
   semantic).
4. Nested entry is forbidden — a sanity check for the single-threaded
   per-cycle invariant.
"""

from datetime import datetime
from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.per_charger_context import (
    PerChargerContext,
)


def _make_coord(ev_chargers=None):
    """A minimal coordinator stub with only the per-charger swap surface.

    Keeping the fixture small means future coordinator refactors won't
    flake these tests — we only depend on the 8 ``_ev_*`` attributes the
    swap touches.
    """
    coord = MagicMock()
    coord.config = {"ev_chargers": ev_chargers or [{"id": "left"}, {"id": "right"}]}
    # Primary view (the "fleet" attributes that get swapped per iteration).
    coord._ev_device = None
    coord._ev_stalled_since = None
    coord._ev_enable_surplus_since = None
    coord._ev_charge_started_at = None
    coord._ev_last_change_time = None
    coord._ev_reenable_attempts = 0
    coord._ev_charge_refused = False
    coord._current_charger_budget = None
    coord._cycle_vehicle_soc = None
    # Per-charger storage dicts (populated/read by the context manager).
    coord._ev_stalled_since_per_charger = {}
    coord._ev_enable_surplus_per_charger = {}
    coord._ev_charge_started_per_charger = {}
    coord._ev_last_change_per_charger = {}
    coord._ev_reenable_attempts_per_charger = {}
    coord._ev_charge_refused_per_charger = {}
    return coord


class TestSwapInvariant:
    """The primary view must be restored exactly after the ``with`` block."""

    def test_restores_primary_after_clean_exit(self):
        """No mutation, clean exit: primary view unchanged."""
        coord = _make_coord()
        coord._ev_device = "FLEET_DEV"
        coord._ev_stalled_since = "FLEET_STALL"
        coord._cycle_vehicle_soc = 42.0

        ev_dev = MagicMock(name="left_dev")
        with PerChargerContext.for_charger(coord, "left", ev_dev, {"left": 4000.0}):
            # Inside: coordinator sees the per-charger view.
            assert coord._ev_device is ev_dev
            assert coord._current_charger_budget == 4000.0

        # Outside: primary view restored.
        assert coord._ev_device == "FLEET_DEV"
        assert coord._ev_stalled_since == "FLEET_STALL"
        assert coord._cycle_vehicle_soc == 42.0

    def test_restores_primary_after_exception(self):
        """If the body raises, primary view is still restored.

        The legacy code used a ``try/finally`` block; the context manager
        must offer the same guarantee so a charger-control failure can't
        leak its swap into the next iteration.
        """
        coord = _make_coord()
        coord._ev_device = "FLEET_DEV"

        ev_dev = MagicMock(name="left_dev")
        with pytest.raises(RuntimeError, match="boom"):
            with PerChargerContext.for_charger(coord, "left", ev_dev, {"left": 4000.0}):
                assert coord._ev_device is ev_dev
                raise RuntimeError("boom")

        assert coord._ev_device == "FLEET_DEV"
        assert coord._current_charger_budget is None  # legacy semantic

    def test_per_charger_state_persists_across_iterations(self):
        """Mutations to ``_ev_stalled_since`` inside the context land in
        the per-charger dict so the next iteration of THIS charger sees
        them."""
        coord = _make_coord()
        ev_dev_left = MagicMock(name="left_dev")
        ev_dev_right = MagicMock(name="right_dev")

        # First pass through charger "left": stash a stalled timestamp.
        stall_ts = datetime(2026, 5, 31, 16, 0, 0)
        with PerChargerContext.for_charger(coord, "left", ev_dev_left, {}):
            coord._ev_stalled_since = stall_ts
            coord._ev_reenable_attempts = 3
            coord._ev_charge_refused = True

        # Persisted to the per-charger dicts.
        assert coord._ev_stalled_since_per_charger["left"] == stall_ts
        assert coord._ev_reenable_attempts_per_charger["left"] == 3
        assert coord._ev_charge_refused_per_charger["left"] is True

        # Primary view back to its pre-entry default (None / 0 / False).
        assert coord._ev_stalled_since is None
        assert coord._ev_reenable_attempts == 0
        assert coord._ev_charge_refused is False

        # Second iteration over a DIFFERENT charger: does not see left's state.
        with PerChargerContext.for_charger(coord, "right", ev_dev_right, {}):
            assert coord._ev_stalled_since is None
            assert coord._ev_reenable_attempts == 0
            assert coord._ev_charge_refused is False

        # Third iteration over left again: sees its own state.
        with PerChargerContext.for_charger(coord, "left", ev_dev_left, {}):
            assert coord._ev_stalled_since == stall_ts
            assert coord._ev_reenable_attempts == 3
            assert coord._ev_charge_refused is True


class TestSkipFlag:
    """``skipped_for_night`` is the v1.6.7 carry-over for the existing
    ``_mode_allows_night_charging`` gate. This release leaves the
    actual computation in the coordinator loop body; the field is wired
    so v1.6.8 can move it into ``for_charger`` without a signature
    change."""

    def test_skip_default_false(self):
        coord = _make_coord()
        pcc = PerChargerContext.for_charger(coord, "left", MagicMock(), {})
        assert pcc.skipped_for_night is False


class TestNestingGuard:
    """Re-entering a context without exiting the previous one would
    clobber the snapshot. Sanity check the single-threaded invariant."""

    def test_nested_entry_raises(self):
        coord = _make_coord()
        ev_dev = MagicMock()
        with PerChargerContext.for_charger(coord, "left", ev_dev, {}) as pcc:
            with pytest.raises(RuntimeError, match="entered twice"):
                pcc.__enter__()


class TestCfgLookup:
    """``for_charger`` resolves the per-charger config dict from
    ``coordinator.config['ev_chargers']``."""

    def test_finds_matching_config(self):
        coord = _make_coord([
            {"id": "left", "name": "Wallbox Left"},
            {"id": "right", "name": "Wallbox Right"},
        ])
        pcc = PerChargerContext.for_charger(coord, "right", MagicMock(), {})
        assert pcc.charger_cfg == {"id": "right", "name": "Wallbox Right"}

    def test_missing_id_yields_empty_cfg(self):
        """A charger present in ``_ev_devices`` but not in ``ev_chargers``
        (mid-migration state) gets an empty dict rather than crashing."""
        coord = _make_coord([{"id": "left"}])
        pcc = PerChargerContext.for_charger(coord, "ghost", MagicMock(), {})
        assert pcc.charger_cfg == {}

    def test_prebuilt_lookup_used_when_passed(self):
        """The caller can pre-build ``chargers_by_id`` for the loop and
        pass it in to avoid rebuilding it once per charger."""
        coord = _make_coord([{"id": "left", "name": "from-config"}])
        prebuilt = {"left": {"id": "left", "name": "from-prebuilt"}}
        pcc = PerChargerContext.for_charger(
            coord, "left", MagicMock(), {}, chargers_by_id=prebuilt,
        )
        assert pcc.charger_cfg["name"] == "from-prebuilt"

    def test_chargers_by_id_none_rebuilds_from_config(self):
        """When ``chargers_by_id`` is omitted, ``for_charger`` rebuilds
        the dict from ``coordinator.config['ev_chargers']`` rather than
        crashing. Exercises the fallback path that the coordinator loop
        bypasses (it always passes a pre-built dict)."""
        coord = _make_coord([
            {"id": "left", "name": "rebuilt-left"},
            {"id": "right", "name": "rebuilt-right"},
        ])
        pcc = PerChargerContext.for_charger(
            coord, "right", MagicMock(), {},  # no chargers_by_id arg
        )
        assert pcc.charger_cfg["name"] == "rebuilt-right"


class TestBudget:
    """The budget passed to ``for_charger`` is forwarded into
    ``self._current_charger_budget`` and reset to ``None`` on exit
    (matching the legacy semantic where ``None`` means "not currently
    inside a per-charger iteration")."""

    def test_budget_pushed_then_cleared(self):
        coord = _make_coord()
        with PerChargerContext.for_charger(coord, "left", MagicMock(), {"left": 6800.0}):
            assert coord._current_charger_budget == 6800.0
        assert coord._current_charger_budget is None

    def test_budget_none_when_charger_not_in_dict(self):
        """The night-state path doesn't populate ``ev_budget_per_charger`` —
        in that case the per-charger budget is ``None`` rather than 0."""
        coord = _make_coord()
        with PerChargerContext.for_charger(coord, "left", MagicMock(), {}):
            assert coord._current_charger_budget is None
        assert coord._current_charger_budget is None
