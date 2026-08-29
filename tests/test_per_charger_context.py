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
    """#589 swap retirement — the context no longer touches the
    coordinator's primary attributes at all. The primary view is
    trivially preserved because nothing writes it; the per-charger view
    lives on the context (``pcc.ev_dev``, ``pcc.skipped_for_night``, …)
    and the real coordinator's PROPERTIES dispatch on ``_current_pcc``
    (tested against a real SEMCoordinator below and in
    test_589_followup.py)."""

    def test_primary_untouched_after_clean_exit(self):
        """No mutation, clean exit: the coordinator's primary attributes
        are never written (there is no swap), and the per-charger view
        lives on the context object."""
        coord = _make_coord()
        coord._ev_device = "FLEET_DEV"
        coord._cycle_vehicle_soc = 42.0

        ev_dev = MagicMock(name="left_dev")
        with PerChargerContext.for_charger(coord, "left", ev_dev) as pcc:
            # The per-charger view is ON THE CONTEXT. NOTE (review): on
            # this MagicMock stub the coordinator PROPERTIES don't exist,
            # so we deliberately assert only what the stub can prove —
            # that the context NEVER WRITES coord attrs. The real property
            # dispatch (in-context reads resolve to pcc.ev_dev) is proven
            # on a real coordinator in
            # test_ev_device_property_dispatches_on_real_coordinator and
            # test_589_followup.py::TestSwapRetirementInterleaved.
            assert pcc.ev_dev is ev_dev
            assert coord._current_pcc is pcc

        # Outside: pointer cleared, primary attrs never changed.
        assert coord._current_pcc is None
        assert coord._ev_device == "FLEET_DEV"
        assert coord._cycle_vehicle_soc == 42.0

    def test_pointer_cleared_after_exception(self):
        """If the body raises, ``_current_pcc`` is still unbound so the
        coordinator properties fall back to the primary view — the
        ``finally``-like guarantee the old restore provided."""
        coord = _make_coord()
        coord._ev_device = "FLEET_DEV"

        ev_dev = MagicMock(name="left_dev")
        with pytest.raises(RuntimeError, match="boom"):
            with PerChargerContext.for_charger(coord, "left", ev_dev) as pcc:
                assert coord._current_pcc is pcc
                raise RuntimeError("boom")

        assert coord._current_pcc is None
        assert coord._ev_device == "FLEET_DEV"

    def test_ev_device_property_dispatches_on_real_coordinator(self):
        """On a REAL coordinator, ``_ev_device`` resolves to the active
        context's device inside the block and to the primary outside —
        the property replacement for the retired swap."""
        from unittest.mock import MagicMock as MM
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator(MM(), {})
        primary = MM(name="primary_dev")
        coord._ev_device = primary  # out-of-loop write → default backing
        left = MM(name="left_dev")

        with PerChargerContext(cid="left", ev_dev=left, charger_cfg={}, _coord=coord):
            assert coord._ev_device is left

        assert coord._ev_device is primary

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

    def test_vehicle_soc_override_cannot_leak(self):
        """#589 swap retirement — a per-charger vehicle-SOC override dies
        with its context: the next charger seeds fresh from the global
        value, and the global value survives the loop untouched. This is
        the exact leak the old ``_saved_vehicle_soc`` restore prevented by
        convention; the pcc-backed property prevents it by construction
        (there is no restore to forget)."""
        from unittest.mock import MagicMock as MM
        from custom_components.solar_energy_management.coordinator.coordinator import (
            SEMCoordinator,
        )
        coord = SEMCoordinator(MM(), {})
        coord._cycle_vehicle_soc = 55.0  # global (primary-entity) cycle SOC

        with PerChargerContext(cid="left", ev_dev=MM(), charger_cfg={}, _coord=coord):
            assert coord._cycle_vehicle_soc == 55.0  # seeded from global
            coord._cycle_vehicle_soc = 81.0  # per-charger entity override
            assert coord._cycle_vehicle_soc == 81.0

        # Post-loop: the global value is untouched by the override.
        assert coord._cycle_vehicle_soc == 55.0

        # Next charger seeds from the GLOBAL value, not left's override.
        with PerChargerContext(cid="right", ev_dev=MM(), charger_cfg={}, _coord=coord):
            assert coord._cycle_vehicle_soc == 55.0


class TestSkipFlag:
    """``skipped_for_night`` is the v1.6.7 carry-over for the existing
    ``_mode_allows_night_charging`` gate. This release leaves the
    actual computation in the coordinator loop body; the field is wired
    so v1.6.8 can move it into ``for_charger`` without a signature
    change."""

    def test_skip_default_false(self):
        coord = _make_coord()
        pcc = PerChargerContext.for_charger(coord, "left", MagicMock())
        assert pcc.skipped_for_night is False


class TestNestingGuard:
    """Re-entering a context without exiting the previous one would
    clobber the snapshot. Sanity check the single-threaded invariant."""

    def test_nested_entry_raises(self):
        coord = _make_coord()
        ev_dev = MagicMock()
        with PerChargerContext.for_charger(coord, "left", ev_dev) as pcc:
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
        pcc = PerChargerContext.for_charger(coord, "right", MagicMock())
        assert pcc.charger_cfg == {"id": "right", "name": "Wallbox Right"}

    def test_missing_id_yields_empty_cfg(self):
        """A charger present in ``_ev_devices`` but not in ``ev_chargers``
        (mid-migration state) gets an empty dict rather than crashing."""
        coord = _make_coord([{"id": "left"}])
        pcc = PerChargerContext.for_charger(coord, "ghost", MagicMock())
        assert pcc.charger_cfg == {}

    def test_prebuilt_lookup_used_when_passed(self):
        """The caller can pre-build ``chargers_by_id`` for the loop and
        pass it in to avoid rebuilding it once per charger."""
        coord = _make_coord([{"id": "left", "name": "from-config"}])
        prebuilt = {"left": {"id": "left", "name": "from-prebuilt"}}
        pcc = PerChargerContext.for_charger(
            coord, "left", MagicMock(), chargers_by_id=prebuilt,
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
            coord, "right", MagicMock(),  # no chargers_by_id arg
        )
        assert pcc.charger_cfg["name"] == "rebuilt-right"


class TestThereIsNoPerChargerBudget651:
    """#651 — the context carried a ``budget_w`` whose docstring called it
    "the single source for this charger's budget", fed from a priority
    cascade that ran every solar cycle. ``build_charger_view`` takes no
    budget argument and never did; nothing outside the writer read the
    field. Two allocators for one concept, one of them invisible.

    The surviving one is ``fleet.solar_committed_w`` — see
    ``test_step6_multi_charger_surplus_sharing.py``. Pin the absence so a
    parallel budget cannot quietly reappear next to it."""

    def test_the_context_has_no_budget_field(self):
        coord = _make_coord()
        with PerChargerContext.for_charger(coord, "left", MagicMock()) as pcc:
            assert not hasattr(pcc, "budget_w"), (
                "PerChargerContext grew a budget_w again — if a per-charger "
                "budget is genuinely needed, it must REPLACE "
                "fleet.solar_committed_w, not run beside it (#651)"
            )

    def test_the_factory_takes_no_budget_map(self):
        import inspect
        params = inspect.signature(PerChargerContext.for_charger).parameters
        assert "ev_budget_per_charger" not in params


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
            coord, "left", ev_dev,
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
        with PerChargerContext.for_charger(coord, "left", MagicMock()):
            pass  # no assignment to pcc.effective_state
        assert coord._effective_states_per_charger == {}

    def test_effective_state_falls_back_to_cid_when_name_missing(self):
        """Config without a ``name`` key — the cid stands in as the
        display name (matches legacy behaviour at coordinator.py:1245)."""
        coord = _make_coord()
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(),
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
            coord, "left", MagicMock(),
            chargers_by_id={"left": {"id": "left", "name": "A"}},
        ) as pcc_left:
            pcc_left.effective_state = "CHARGING_ACTIVE"
        with PerChargerContext.for_charger(
            coord, "right", MagicMock(),
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
            coord, "left", ev_dev, power=power,
        ) as pcc:
            assert pcc.this_power_w == 4150.0
            # Helper called with this charger's ev_dev + the cycle power.
            coord._this_charger_power.assert_called_once_with(ev_dev, power)

    def test_this_power_w_none_when_no_power_passed(self):
        """Legacy/unit-test callers that omit ``power`` get ``None`` —
        the in-loop helper then falls back to direct compute."""
        coord = _make_coord()
        with PerChargerContext.for_charger(
            coord, "left", MagicMock(),
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
            coord, "left", MagicMock(), power=MagicMock(),
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
            coord, "left", MagicMock(),
        ) as pcc:
            assert coord._current_pcc is pcc
        assert coord._current_pcc is None

    def test_current_pcc_cleared_even_on_exception(self):
        coord = _make_coord()
        with pytest.raises(RuntimeError, match="boom"):
            with PerChargerContext.for_charger(
                coord, "left", MagicMock(),
            ):
                assert coord._current_pcc is not None
                raise RuntimeError("boom")
        assert coord._current_pcc is None
