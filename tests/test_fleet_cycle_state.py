"""Pin the FleetCycleState contract.

Companion to ``tests/test_fleet_state_completeness.py`` (the AST
lint). This file pins the behavioural invariants:

  * ``FleetCycleState`` is frozen — instances cannot be mutated
    after construction (Python's ``dataclasses.FrozenInstanceError``)
  * Two ``FleetCycleState`` instances built with the same inputs
    compare equal — value-type semantics
  * ``build_charger_view`` reading fields from ``fleet_state``
    produces a ``FleetContext`` that matches what the state's
    fields say

If a future refactor accidentally adds a mutable field to
``FleetCycleState`` or relaxes the frozen guarantee, the strict
single-source-of-truth contract breaks. The cross-view consistency
invariant the v1.7 refactor relies on requires per-cycle immutability.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    FleetCycleState,
    FleetContext,
)


def _power(
    *, solar: float = 0, home: float = 0, batt: float = 0,
    soc: float = 50, ev: float = 0,
) -> MagicMock:
    """Mock PowerReadings with the fields ``build_charger_view`` reads."""
    p = MagicMock()
    p.solar_power = solar
    p.home_consumption_power = home
    p.battery_power = batt
    p.battery_charge_power = max(0, batt)
    p.battery_discharge_power = max(0, -batt)
    p.battery_soc = soc
    p.grid_import_power = 0.0
    p.grid_export_power = 0.0
    p.ev_power = ev
    p.ev_power_per_charger = None
    p.ev_connected = True
    p.ev_charging = False
    p.ev_connected_per_charger = None
    p.ev_charging_per_charger = None
    return p


# ---------------------------------------------------------------------------
# Frozen invariant
# ---------------------------------------------------------------------------


def test_fleet_cycle_state_is_frozen() -> None:
    """Cannot mutate fields after construction. The whole refactor
    rests on this — if instances were mutable, the multi-charger
    loop could accidentally adjust the state between views and
    break the cross-view equality invariant."""
    state = FleetCycleState(
        power=_power(solar=5000),
        config={"battery_capacity_kwh": 15},
        is_night=False,
    )

    with pytest.raises(Exception) as excinfo:
        state.is_night = True  # type: ignore[misc]
    # FrozenInstanceError is a subclass of AttributeError in Python's
    # dataclasses; assert by name to be implementation-neutral.
    assert "FrozenInstanceError" in type(excinfo.value).__name__ \
        or isinstance(excinfo.value, AttributeError)


# ---------------------------------------------------------------------------
# Value-type equality
# ---------------------------------------------------------------------------


def test_two_states_with_same_inputs_compare_equal() -> None:
    """Frozen dataclasses get __eq__ generated automatically — verify
    the contract holds. Two views built from equal FleetCycleStates
    must agree on fleet inputs."""
    power = _power(solar=5000, home=800, soc=72)
    config = {
        "battery_capacity_kwh": 15,
        "battery_buffer_soc": 70,
        "battery_auto_start_soc": 90,
    }

    a = FleetCycleState(
        power=power, config=config, is_night=False,
        tariff_level="normal", forecast_remaining_kwh=12.5,
    )
    b = FleetCycleState(
        power=power, config=config, is_night=False,
        tariff_level="normal", forecast_remaining_kwh=12.5,
    )

    assert a == b


def test_states_with_different_inputs_compare_unequal() -> None:
    """The sanity check on equality: any input change makes them
    unequal. Catches a future broken __eq__ override."""
    power = _power(solar=5000)
    config = {"battery_capacity_kwh": 15}

    base = FleetCycleState(
        power=power, config=config, is_night=False,
        tariff_level="normal", forecast_remaining_kwh=12.0,
    )

    # Each variation produces an unequal instance
    assert base != FleetCycleState(
        power=power, config=config, is_night=True,
        tariff_level="normal", forecast_remaining_kwh=12.0,
    )
    assert base != FleetCycleState(
        power=power, config=config, is_night=False,
        tariff_level="cheap", forecast_remaining_kwh=12.0,
    )
    assert base != FleetCycleState(
        power=power, config=config, is_night=False,
        tariff_level="normal", forecast_remaining_kwh=15.0,
    )


# ---------------------------------------------------------------------------
# build_charger_view roundtrip — primary's fleet equals a 2nd view's fleet
# ---------------------------------------------------------------------------


def test_two_views_built_from_same_fleet_state_share_fleet_context() -> None:
    """The structural payoff: two ``build_charger_view`` calls in the
    same cycle, both passing the same FleetCycleState, produce views
    whose ``FleetContext`` fields agree on every fleet-level input.

    ``solar_committed_w`` is the only field that legitimately differs
    (it's per-charger, carries the cascade state). Everything else
    must match by construction.

    Pre-refactor this invariant was the v1.7 prep PR's findings:
    primary view saw tariff_level=None while multi-charger views saw
    tariff_level=<actual>. After the refactor it's structurally
    impossible.
    """
    from custom_components.solar_energy_management.coordinator.build_view import (
        build_charger_view,
    )

    state = FleetCycleState(
        power=_power(solar=5000, home=800, batt=1000, soc=72),
        config={
            "battery_capacity_kwh": 15,
            "battery_buffer_soc": 70,
            "battery_auto_start_soc": 90,
            "battery_priority_soc": 30,
        },
        is_night=False,
        tariff_level="normal",
        forecast_remaining_kwh=18.0,
    )

    primary = build_charger_view(
        state,
        charger_id="primary",
        charger_cfg={"id": "primary"},
        mode="solar_only",
        daily_ev_kwh=0.0,
    )
    secondary = build_charger_view(
        state,
        charger_id="secondary",
        charger_cfg={"id": "secondary"},
        mode="solar_only",
        daily_ev_kwh=0.0,
        solar_committed_w=2000.0,  # secondary sees less surplus
    )

    p, s = primary.fleet, secondary.fleet

    # Fleet inputs match field-by-field except solar_committed_w
    assert p.solar_w == s.solar_w
    assert p.home_w == s.home_w
    assert p.battery_charge_w == s.battery_charge_w
    assert p.battery_soc == s.battery_soc
    assert p.is_night == s.is_night
    assert p.tariff_level == s.tariff_level
    assert p.forecast_remaining_kwh == s.forecast_remaining_kwh
    assert p.auto_start_soc == s.auto_start_soc
    assert p.buffer_soc == s.buffer_soc
    assert p.priority_soc == s.priority_soc

    # Only solar_committed_w differs — that's per-view by design.
    assert p.solar_committed_w == 0.0
    assert s.solar_committed_w == 2000.0


def test_min_solar_w_wired_from_config():
    """The 'Minimum Solar Power' slider (config key ``minimum_solar_power``)
    must reach FleetContext.min_solar_w — it was hardcoded to the 200 W
    default before, so the slider did nothing. Fallback stays 200 W when the
    key is absent (configs without it are unchanged)."""
    from custom_components.solar_energy_management.coordinator.build_view import (
        build_charger_view,
    )

    def _view(cfg_extra):
        state = FleetCycleState(
            power=_power(solar=5000, home=800, batt=1000, soc=72),
            config={"battery_capacity_kwh": 15, **cfg_extra},
            is_night=False, tariff_level="normal", forecast_remaining_kwh=18.0,
        )
        return build_charger_view(
            state, charger_id="c", charger_cfg={"id": "c"},
            mode="solar_only", daily_ev_kwh=0.0,
        )

    # Configured value is honoured.
    assert _view({"minimum_solar_power": 1500}).fleet.min_solar_w == 1500.0
    # Legacy config-flow key also honoured.
    assert _view({"min_solar_power": 800}).fleet.min_solar_w == 800.0
    # Absent → 200 W fallback (unchanged behaviour).
    assert _view({}).fleet.min_solar_w == 200.0
