"""Tests for the per-charger primary types
(arch/multi-charger-primary Step 1).

These tests pin the *shape and contracts* of the new types only —
they do not assert any consumer behaviour, because consumers do not
exist yet. Steps 3 (decide) and 4 (actuate) build against this
foundation.

Invariants pinned:
1. All types are immutable (frozen=True).
2. ``FleetView.from_per_charger`` is pure (calling twice with the
   same inputs returns equal results).
3. Conservation: ``FleetView.total_power_w == sum(per_charger
   power_w)`` exactly.
4. ``ChargerDecision`` carries enough info for the actuator —
   intent + commanded_amps fully specifies the actuator call.
5. ``FleetContext`` is the SAME object across every ``ChargerView``
   in a cycle (test pins that the dataclass is value-equal so two
   chargers see identical fleet state).
"""
from dataclasses import FrozenInstanceError

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerDecision,
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
    FleetView,
)


class TestImmutability:
    """All types are frozen — no field reassignment, no aliasing
    bugs from in-place mutation in the per-charger loop (the
    pattern that produced the #318 / #346 disagreement class)."""

    def test_charger_power_is_frozen(self):
        p = ChargerPower(charger_id="keba", power_w=1500.0, connected=True)
        with pytest.raises(FrozenInstanceError):
            p.power_w = 2000.0  # type: ignore[misc]

    def test_charger_energy_is_frozen(self):
        e = ChargerEnergy(charger_id="keba", day_kwh=5.5)
        with pytest.raises(FrozenInstanceError):
            e.day_kwh = 6.0  # type: ignore[misc]

    def test_charger_decision_is_frozen(self):
        d = ChargerDecision(
            charger_id="keba", mode="solar_only",
            intent=ChargerIntent.IDLE,
        )
        with pytest.raises(FrozenInstanceError):
            d.intent = ChargerIntent.CHARGE_MAX  # type: ignore[misc]

    def test_charger_view_is_frozen(self):
        view = ChargerView(
            power=ChargerPower(charger_id="keba"),
            energy=ChargerEnergy(charger_id="keba"),
            mode="solar_only", config={},
            fleet=FleetContext(),
        )
        with pytest.raises(FrozenInstanceError):
            view.mode = "off"  # type: ignore[misc]

    def test_fleet_context_is_frozen(self):
        ctx = FleetContext(solar_w=5000.0)
        with pytest.raises(FrozenInstanceError):
            ctx.solar_w = 0.0  # type: ignore[misc]

    def test_fleet_view_is_frozen(self):
        fv = FleetView()
        with pytest.raises(FrozenInstanceError):
            fv.total_power_w = 100.0  # type: ignore[misc]


class TestFleetViewConservation:
    """``FleetView.from_per_charger`` is the only way to compute a
    fleet number. The invariant is exact summation over the
    per-charger dict — no shadow accumulator, no drift."""

    def test_empty_fleet(self):
        fv = FleetView.from_per_charger({}, {})
        assert fv.total_power_w == 0.0
        assert fv.total_day_kwh == 0.0
        assert fv.any_connected is False
        assert fv.any_charging is False
        assert fv.count == 0

    def test_single_charger_sum(self):
        power = {"keba": ChargerPower("keba", power_w=4140.0, connected=True, charging=True)}
        energy = {"keba": ChargerEnergy("keba", day_kwh=12.5)}
        fv = FleetView.from_per_charger(power, energy)
        assert fv.total_power_w == 4140.0
        assert fv.total_day_kwh == 12.5
        assert fv.any_connected is True
        assert fv.any_charging is True
        assert fv.count == 1

    def test_two_chargers_sum_exact(self):
        """Sum invariant — the v1.6.16 FleetEvPower newtype existed
        because this kept drifting. The new primary architecture
        eliminates drift by construction."""
        power = {
            "keba": ChargerPower("keba", power_w=4140.0, connected=True, charging=True),
            "wallbox": ChargerPower("wallbox", power_w=6900.0, connected=True, charging=True),
        }
        energy = {
            "keba": ChargerEnergy("keba", day_kwh=12.5),
            "wallbox": ChargerEnergy("wallbox", day_kwh=8.2),
        }
        fv = FleetView.from_per_charger(power, energy)
        assert fv.total_power_w == 11040.0  # 4140 + 6900
        assert fv.total_day_kwh == 20.7      # 12.5 + 8.2
        assert fv.count == 2

    def test_three_chargers_mixed_state(self):
        power = {
            "a": ChargerPower("a", power_w=4140.0, connected=True, charging=True),
            "b": ChargerPower("b", power_w=0.0, connected=True, charging=False),
            "c": ChargerPower("c", power_w=0.0, connected=False, charging=False),
        }
        energy = {cid: ChargerEnergy(cid) for cid in power}
        fv = FleetView.from_per_charger(power, energy)
        assert fv.total_power_w == 4140.0
        assert fv.any_connected is True
        assert fv.any_charging is True
        assert fv.count == 3

    def test_purity_called_twice_same_result(self):
        """Calling ``from_per_charger`` twice with the same inputs
        returns equal results. No hidden state."""
        power = {"keba": ChargerPower("keba", power_w=2000.0)}
        energy = {"keba": ChargerEnergy("keba", day_kwh=4.0)}
        fv1 = FleetView.from_per_charger(power, energy)
        fv2 = FleetView.from_per_charger(power, energy)
        assert fv1 == fv2


class TestChargerDecisionShape:
    """Each ``ChargerIntent`` value implies a specific actuator
    call. The decision carries everything the actuator needs."""

    def test_idle_intent_amps_irrelevant(self):
        d = ChargerDecision(
            charger_id="keba", mode="solar_only",
            intent=ChargerIntent.IDLE, commanded_amps=0,
            reason="solar insufficient",
        )
        assert d.intent is ChargerIntent.IDLE
        assert d.commanded_amps == 0

    def test_charge_at_amps_carries_value(self):
        d = ChargerDecision(
            charger_id="keba", mode="solar_only",
            intent=ChargerIntent.CHARGE_AT_AMPS, commanded_amps=8,
            budget_w=5520.0, reason="solar 5520W → 8A",
        )
        assert d.commanded_amps == 8
        assert d.budget_w == 5520.0

    def test_disable_intent_explicit(self):
        d = ChargerDecision(
            charger_id="keba", mode="off",
            intent=ChargerIntent.DISABLE,
            reason="user-explicit OFF",
        )
        assert d.intent is ChargerIntent.DISABLE
        # DISABLE is distinct from IDLE — same actuator output
        # (zero current) but different brand call (keba.disable
        # vs set_current(0)). Pinning the distinction here so a
        # future refactor doesn't collapse them.
        assert d.intent != ChargerIntent.IDLE


class TestFleetContextSharing:
    """``FleetContext`` is intentionally the same object across
    every ``ChargerView`` in a cycle. Two chargers must see
    identical fleet state — no drift between charger A's
    ``solar_w`` and charger B's."""

    def test_two_views_share_fleet_context_value(self):
        fleet = FleetContext(solar_w=8000.0, home_w=500.0, battery_soc=72.0)
        view_a = ChargerView(
            power=ChargerPower("a"), energy=ChargerEnergy("a"),
            mode="solar_only", config={}, fleet=fleet,
        )
        view_b = ChargerView(
            power=ChargerPower("b"), energy=ChargerEnergy("b"),
            mode="min_plus_solar", config={}, fleet=fleet,
        )
        # Same identity → no in-place mutation can drift them
        assert view_a.fleet is view_b.fleet
        # And value-equal — defensive copy would also satisfy
        # downstream consumers
        assert view_a.fleet == view_b.fleet

    def test_fleet_context_equality_excludes_per_charger_data(self):
        """``FleetContext`` is the cross-charger common ground.
        Per-charger fields belong on ``ChargerView``, not here."""
        ctx = FleetContext(solar_w=5000.0)
        # Spot check: no fields like charger_id, power_w, day_kwh
        assert not hasattr(ctx, "charger_id")
        assert not hasattr(ctx, "power_w")
        assert not hasattr(ctx, "day_kwh")
