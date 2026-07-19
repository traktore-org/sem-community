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
    flake these tests — we only depend on the attributes the swap touches.

    Note: The 7 Surface-A scalars (_ev_stalled_since, _ev_enable_surplus_since,
    _ev_charge_started_at, _ev_last_change_time, _ev_reenable_attempts,
    _ev_charge_refused, _ev_last_set_amps_ts) are PROPERTIES on the real
    coordinator backed by _pcc_store, so MagicMock lets them be set/read as
    plain attributes here — the property logic runs on the real coordinator.
    We add _pcc_store = {} so __enter__'s setdefault call works correctly.
    """
    coord = MagicMock()
    coord.config = {"ev_chargers": ev_chargers or [{"id": "left"}, {"id": "right"}]}
    # Primary view (the "fleet" attributes that get swapped per iteration).
    coord._ev_device = None
    coord._current_charger_budget = None
    coord._cycle_vehicle_soc = None
    # #589 Surface-A: _pcc_store is the durable per-charger state store.
    coord._pcc_store = {}
    # v1.6.14: parallel dict written by ``__exit__`` from ``pcc.effective_state``.
    coord._effective_states_per_charger = {}
    # v1.6.14: cache pointer ``__enter__`` sets, ``__exit__`` clears.
    coord._current_pcc = None
    # v1.6.14: ``__enter__`` calls this helper to pre-compute
    # ``this_power_w``. Real coordinator's helper is on ``EVControlMixin``;
    # the stub returns whatever the test wants.
    coord._this_charger_power = MagicMock(return_value=0.0)
    return coord


class TestSwapInvariant:
    """The primary view must be restored exactly after the ``with`` block."""

    def test_restores_primary_after_clean_exit(self):
        """No mutation, clean exit: primary view unchanged.

        #589 Surface-A: _ev_stalled_since and the other 6 migrated scalars
        are PROPERTIES on the real coordinator backed by _pcc_store; they
        are NOT in the _saved snapshot and are tested via the real-coordinator
        isolation tests in test_589_followup.py. This test covers the still-
        swap-based fields: _ev_device, _current_charger_budget, _cycle_vehicle_soc.
        """
        coord = _make_coord()
        coord._ev_device = "FLEET_DEV"
        coord._cycle_vehicle_soc = 42.0

        ev_dev = MagicMock(name="left_dev")
        with PerChargerContext.for_charger(coord, "left", ev_dev, {"left": 4000.0}):
            # Inside: coordinator sees the per-charger view.
            assert coord._ev_device is ev_dev
            assert coord._current_charger_budget == 4000.0

        # Outside: primary view restored.
        assert coord._ev_device == "FLEET_DEV"
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
        """Mutations to Surface-A fields inside the context are durable across
        iterations via the _pcc_store (real coordinator required — properties
        don't work on a MagicMock stub).

        #589 Surface-A: ALL 7 scalars are properties backed by the durable
        _pcc_store; per-charger dicts are retired. This test uses a real
        SEMCoordinator so the property getter/setter logic runs correctly.
        Comprehensive cross-charger isolation is in
        test_589_followup.py::TestSurfaceA* — this test is the minimal
        in-file sanity check that the still-non-Surface-A swap fields
        (_ev_device) + the migrated scalar fields (_ev_reenable_attempts,
        _ev_charge_refused) both behave correctly together.
        """
        from unittest.mock import MagicMock as MM
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator(MM(), {})
        ev_dev_left = MM(name="left_dev")
        ev_dev_right = MM(name="right_dev")

        with PerChargerContext(cid="left", ev_dev=ev_dev_left, charger_cfg={}, _coord=coord):
            coord._ev_reenable_attempts = 3
            coord._ev_charge_refused = True

        # Primary view back to default (out-of-loop falls back to _default).
        assert coord._ev_reenable_attempts == 0
        assert coord._ev_charge_refused is False

        # Second iteration over a DIFFERENT charger: does not see left's state.
        with PerChargerContext(cid="right", ev_dev=ev_dev_right, charger_cfg={}, _coord=coord):
            assert coord._ev_reenable_attempts == 0
            assert coord._ev_charge_refused is False

        # Third iteration over left again: sees its own persisted state.
        with PerChargerContext(cid="left", ev_dev=ev_dev_left, charger_cfg={}, _coord=coord):
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


class TestEffectiveStateField:
    """v1.6.14: ``pcc.effective_state`` is the write path for
    ``coord._effective_states_per_charger``. ``__exit__`` persists the
    field if it's not ``None``; the post-loop notification dispatcher
    iterates the dict. The loop body never touches the dict directly."""

    def test_effective_state_persists_on_exit(self):
        """Writing the field inside the ``with`` block lands the
        ``(state, name)`` tuple in the coordinator's per-charger dict
        after exit."""
        coord = _make_coord()
        ev_dev = MagicMock(name="left_dev")
        cfg = {"id": "left", "name": "Wallbox Left"}
        with PerChargerContext.for_charger(
            coord, "left", ev_dev, {"left": 4000.0},
            chargers_by_id={"left": cfg},
        ) as pcc:
            pcc.effective_state = "CHARGING_ACTIVE"
        assert coord._effective_states_per_charger == {
            "left": ("CHARGING_ACTIVE", "Wallbox Left"),
        }

    def test_effective_state_omitted_when_not_set(self):
        """Skipped chargers (e.g. ``solar_only`` during night) never
        set ``pcc.effective_state``; the dict stays empty for them."""
        coord = _make_coord()
        with PerChargerContext.for_charger(coord, "left", MagicMock(), {}):
            pass  # no assignment to pcc.effective_state
        assert coord._effective_states_per_charger == {}

    def test_effective_state_falls_back_to_cid_when_name_missing(self):
        """Config without a ``name`` key — the cid stands in as the
        display name (matches legacy behaviour at coordinator.py:1245)."""
        coord = _make_coord()
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(), {"left": 4000.0},
            chargers_by_id={"left": {"id": "left"}},
        ) as pcc:
            pcc.effective_state = "CHARGING_ACTIVE"
        assert coord._effective_states_per_charger["left"] == (
            "CHARGING_ACTIVE", "left",
        )

    def test_multi_charger_dispatches_independently(self):
        """Two chargers, different states — each ``__exit__`` writes its
        own key into the dict; no cross-contamination."""
        coord = _make_coord()
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(), {"left": 4000.0},
            chargers_by_id={"left": {"id": "left", "name": "A"}},
        ) as pcc_left:
            pcc_left.effective_state = "CHARGING_ACTIVE"
        with PerChargerContext.for_charger(
            coord, "right", MagicMock(), {"right": 0.0},
            chargers_by_id={"right": {"id": "right", "name": "B"}},
        ) as pcc_right:
            pcc_right.effective_state = "IDLE"
        assert coord._effective_states_per_charger == {
            "left": ("CHARGING_ACTIVE", "A"),
            "right": ("IDLE", "B"),
        }


class TestThisPowerWField:
    """v1.6.14: ``pcc.this_power_w`` is precomputed in ``__enter__``
    via ``coord._this_charger_power(ev_dev, power)``. The coordinator
    stashes the active pcc on ``coord._current_pcc`` so the helper's
    subsequent calls (from inside ev_control methods) serve the cached
    value rather than re-reading HA state."""

    def test_this_power_w_precomputed_on_enter(self):
        coord = _make_coord()
        coord._this_charger_power.return_value = 4150.0
        ev_dev = MagicMock(name="left_dev")
        power = MagicMock()
        with PerChargerContext.for_charger(
            coord, "left", ev_dev, {"left": 4000.0}, power=power,
        ) as pcc:
            assert pcc.this_power_w == 4150.0
            # Helper called with this charger's ev_dev + the cycle power.
            coord._this_charger_power.assert_called_once_with(ev_dev, power)

    def test_this_power_w_none_when_no_power_passed(self):
        """Legacy/unit-test callers that omit ``power`` get ``None`` —
        the in-loop helper then falls back to direct compute."""
        coord = _make_coord()
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(), {"left": 4000.0},
        ) as pcc:
            assert pcc.this_power_w is None
        # Helper not called when power wasn't supplied.
        coord._this_charger_power.assert_not_called()

    def test_this_power_w_helper_failure_falls_through(self):
        """If the helper raises (transient HA state issue), pcc gets
        ``None`` and the legacy method-local recompute path runs.
        ``__enter__`` must not propagate the exception — that would
        leave the swap half-applied."""
        coord = _make_coord()
        coord._this_charger_power.side_effect = ValueError("bad state")
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(), {"left": 4000.0}, power=MagicMock(),
        ) as pcc:
            assert pcc.this_power_w is None
        # Swap still restored.
        assert coord._current_pcc is None


class TestCurrentPccPointer:
    """v1.6.14: ``coord._current_pcc`` is set in ``__enter__``, cleared
    in ``__exit__``. Lets the ``_this_charger_power`` helper return the
    cached value to in-loop callers without changing their signatures."""

    def test_current_pcc_set_inside_block_cleared_outside(self):
        coord = _make_coord()
        assert coord._current_pcc is None
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(), {"left": 4000.0},
        ) as pcc:
            assert coord._current_pcc is pcc
        assert coord._current_pcc is None

    def test_current_pcc_cleared_even_on_exception(self):
        coord = _make_coord()
        with pytest.raises(RuntimeError, match="boom"):
            with PerChargerContext.for_charger(
                coord, "left", MagicMock(), {"left": 4000.0},
            ):
                assert coord._current_pcc is not None
                raise RuntimeError("boom")
        assert coord._current_pcc is None
