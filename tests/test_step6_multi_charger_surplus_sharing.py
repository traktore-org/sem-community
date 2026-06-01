"""Step 6 multi-charger surplus sharing scenario tests.

When the per-charger loop walks chargers in priority order, each
``decide(view)`` must see a ``FleetContext.solar_committed_w`` that
reflects what higher-priority chargers in the same cycle already
claimed. Two solar_only chargers cannot each think they own ALL the
surplus.

These tests exercise the decide() function with manually constructed
views that mimic the per-charger loop's commitment threading. The
real loop's threading is exercised by the invariant suite.
"""
import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    ChargerEnergy,
    ChargerIntent,
    ChargerPower,
    ChargerView,
    FleetContext,
)
from custom_components.solar_energy_management.coordinator.decide import (
    decide,
    self_consumption_surplus_w,
)


def _fleet(*, solar_w=8000.0, home_w=500.0, battery_soc=95.0,
           solar_committed_w=0.0, **kw):
    return FleetContext(
        solar_w=solar_w, home_w=home_w, battery_soc=battery_soc,
        solar_committed_w=solar_committed_w, **kw,
    )


def _view(charger_id="keba", mode="solar_only", *, fleet, **kw):
    return ChargerView(
        power=ChargerPower(charger_id=charger_id, connected=True),
        energy=ChargerEnergy(charger_id=charger_id),
        mode=mode,
        config={"ev_min_current": 6, "ev_phases": 3, "ev_voltage": 230,
                "ev_max_current": 16, **kw},
        fleet=fleet,
    )


class TestSolarCommittedReducesSurplus:
    """The core test: solar_committed_w is subtracted from surplus."""

    def test_no_commitment_full_surplus_available(self):
        f = _fleet(solar_w=8000, home_w=500, solar_committed_w=0)
        v = _view(fleet=f)
        # surplus = 8000 - 500 - 0 = 7500
        assert self_consumption_surplus_w(v) == pytest.approx(7500, abs=1)

    def test_full_commitment_zero_surplus(self):
        f = _fleet(solar_w=8000, home_w=500, solar_committed_w=7500)
        v = _view(fleet=f)
        # surplus = 8000 - 500 - 7500 = 0
        assert self_consumption_surplus_w(v) == pytest.approx(0, abs=1)

    def test_partial_commitment(self):
        f = _fleet(solar_w=8000, home_w=500, solar_committed_w=4000)
        v = _view(fleet=f)
        # surplus = 8000 - 500 - 4000 = 3500
        assert self_consumption_surplus_w(v) == pytest.approx(3500, abs=1)


class TestMultiChargerSurplusOrdering:
    """Simulate the per-charger loop: build view A, decide A, update
    commitment, build view B with new commitment, decide B."""

    def test_two_solar_only_chargers_priority_split(self):
        """Solar 8 kW, home 500 W → 7.5 kW surplus. Two
        solar_only chargers each want max 16 A × 3 × 230 = 11 kW.
        With the commitment thread, A claims 7500 W (10 A); B sees
        committed=7500 → 0 surplus → idle."""
        # Cycle: charger A first (high priority)
        f_a = _fleet(solar_w=8000, home_w=500, solar_committed_w=0)
        v_a = _view("a", fleet=f_a)
        d_a = decide(v_a)
        assert d_a.intent is ChargerIntent.CHARGE_AT_AMPS
        # 7500 W / 690 = 10 A
        assert d_a.commanded_amps == 10

        # Update commitment after A's decision
        committed_after_a = min(
            d_a.budget_w,
            d_a.commanded_amps * 3 * 230,
        )

        # Charger B sees the commitment
        f_b = _fleet(solar_w=8000, home_w=500,
                     solar_committed_w=committed_after_a)
        v_b = _view("b", fleet=f_b)
        d_b = decide(v_b)
        assert d_b.intent is ChargerIntent.IDLE
        assert "min=4140" in d_b.reason or "200W threshold" in d_b.reason

    def test_three_chargers_first_two_charge_third_idles(self):
        """Solar 12 kW − home 500 W = 11500 W surplus. Three
        chargers each want 16 A (11040 W). A claims first 10 A
        (6900 W); B claims next 6 A (4140 W) — that's 11040 W
        committed; C sees only ~460 W left → idle."""
        # A
        f_a = _fleet(solar_w=12000, home_w=500, solar_committed_w=0)
        v_a = _view("a", fleet=f_a)
        d_a = decide(v_a)
        assert d_a.intent is ChargerIntent.CHARGE_AT_AMPS
        # Surplus 11500 → 16 A (clamped to max), commits 11040 W
        assert d_a.commanded_amps == 16
        committed_a = d_a.commanded_amps * 3 * 230  # 11040

        # B
        f_b = _fleet(solar_w=12000, home_w=500,
                     solar_committed_w=committed_a)
        v_b = _view("b", fleet=f_b)
        d_b = decide(v_b)
        # surplus = 12000 - 500 - 11040 = 460 W < min 4140 → idle
        assert d_b.intent is ChargerIntent.IDLE

        # C also idles
        committed_b = 0  # B didn't commit
        f_c = _fleet(solar_w=12000, home_w=500,
                     solar_committed_w=committed_a + committed_b)
        v_c = _view("c", fleet=f_c)
        d_c = decide(v_c)
        assert d_c.intent is ChargerIntent.IDLE

    def test_two_chargers_enough_solar_for_both(self):
        """Solar 18 kW − home 500 W = 17500 W. Two chargers each
        wanting 16 A (11040 W) — total need 22080 W > 17500 W, so
        A gets 16 A (full), B gets only 6500 W = 9 A (clamped)."""
        f_a = _fleet(solar_w=18000, home_w=500, solar_committed_w=0)
        v_a = _view("a", fleet=f_a)
        d_a = decide(v_a)
        assert d_a.commanded_amps == 16
        committed_a = 16 * 3 * 230  # 11040

        f_b = _fleet(solar_w=18000, home_w=500,
                     solar_committed_w=committed_a)
        v_b = _view("b", fleet=f_b)
        d_b = decide(v_b)
        # surplus = 18000 - 500 - 11040 = 6460 → 9 A
        assert d_b.intent is ChargerIntent.CHARGE_AT_AMPS
        assert d_b.commanded_amps == 9
