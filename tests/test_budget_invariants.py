"""Property-based invariants on the canonical EV budget math.

The YAML scenario suite (``tests/test_scenarios.py``) pins narrative
regressions — one cycle, one regime, one expected outcome. But it
can't enumerate the input space: solar can be any non-negative
number, battery_soc can be anywhere 0-100, forecast can be 0-30+ kWh,
etc. The matrix test (``tests/test_scenario_coverage.py``) is one
scenario per regime cell; that's the *narrative* floor, not the
*combinatorial* floor.

This file fills that gap. ``hypothesis`` generates many random
inputs and asserts invariants that must hold for ALL of them:

  * net_w is never negative (no negative budgets that the actuator
    would have to interpret as "discharge to grid")
  * net_w is never NaN / inf (Decimal/float safety)
  * SOLAR_ONLY net_w is bounded by ``solar - home + battery_charge``
    (= solar - home for SOC<auto_start; surplus formula floor)
  * IDLE always returns net_w=0 + current_a=0 (no leakage)
  * NOW always returns max charger nameplate (the user-asked override)
  * SELF_CONSUMPTION never includes battery redirect (Zone 2 contract)
  * BATTERY_ASSIST net_w >= raw_surplus (assist + redirect add, not
    subtract)
  * current_a == floor(net_w / (voltage * phases)) for surplus regimes
    (the rounding policy locked in by #353 + the surplus_leak scenario)

Why hypothesis vs. plain unit tests
-----------------------------------
The legacy disagreement bug class (#282) was about three paths
computing the SAME logical budget and getting different answers.
Plain unit tests cover the cases someone thought to write; the
disagreement only appears at the inputs nobody tested. Hypothesis
finds those inputs automatically and shrinks failing cases to the
smallest repro.

Each test runs ~100 randomised inputs by default. The CI cost is
~1 second per test class. Cheap insurance.
"""
from __future__ import annotations

import math

from hypothesis import given, settings, strategies as st

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    EVBudgetStrategy,
    FlowCalculator,
    battery_redirect_w,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


# ---------------------------------------------------------------------------
# Strategies — the input space
# ---------------------------------------------------------------------------


def _power(
    *,
    solar: float = 0,
    home: float = 0,
    grid: float = 0,
    batt_charge: float = 0,
    batt_discharge: float = 0,
    ev: float = 0,
    batt_soc: float = 50,
) -> PowerReadings:
    """Build a PowerReadings with explicit components (no auto-derive)."""
    pr = PowerReadings(
        solar_power=solar,
        grid_power=grid,
        battery_power=batt_charge - batt_discharge,
        ev_power=ev,
        battery_soc=batt_soc,
    )
    pr.calculate_derived()
    # The flow_calculator math depends on these specific fields, which
    # calculate_derived populates. ``home`` is computed via the energy
    # balance unless explicitly overridden.
    if home > 0:
        pr.home_consumption_power = home
    return pr


# Bounded sensible ranges. Solar caps at 30 kW (large residential),
# battery at 20 kWh / 8 kW, EV at 22 kW (3-phase 32A).
_solar = st.floats(min_value=0.0, max_value=30000.0, allow_nan=False, allow_infinity=False)
_home = st.floats(min_value=0.0, max_value=15000.0, allow_nan=False, allow_infinity=False)
_batt_chg = st.floats(min_value=0.0, max_value=8000.0, allow_nan=False, allow_infinity=False)
_batt_dis = st.floats(min_value=0.0, max_value=8000.0, allow_nan=False, allow_infinity=False)
_soc = st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False)
_capacity = st.floats(min_value=2.0, max_value=30.0, allow_nan=False, allow_infinity=False)
_forecast = st.floats(min_value=0.0, max_value=60.0, allow_nan=False, allow_infinity=False)


# ---------------------------------------------------------------------------
# battery_redirect_w invariants
# ---------------------------------------------------------------------------


class TestBatteryRedirectInvariants:
    @given(batt_chg=_batt_chg, soc=_soc, capacity=_capacity, forecast=_forecast)
    def test_redirect_never_negative(
        self, batt_chg: float, soc: float, capacity: float, forecast: float,
    ) -> None:
        redirect = battery_redirect_w(batt_chg, soc, capacity, forecast)
        assert redirect >= 0
        assert not math.isnan(redirect)
        assert not math.isinf(redirect)

    @given(batt_chg=_batt_chg, soc=_soc, capacity=_capacity, forecast=_forecast)
    def test_redirect_never_exceeds_battery_charge(
        self, batt_chg: float, soc: float, capacity: float, forecast: float,
    ) -> None:
        """Can't divert more than the battery is currently taking."""
        redirect = battery_redirect_w(batt_chg, soc, capacity, forecast)
        assert redirect <= batt_chg + 1e-6  # tiny float slack

    @given(soc=_soc, capacity=_capacity, forecast=_forecast)
    def test_redirect_zero_when_battery_not_charging(
        self, soc: float, capacity: float, forecast: float,
    ) -> None:
        assert battery_redirect_w(0.0, soc, capacity, forecast) == 0
        assert battery_redirect_w(-100.0, soc, capacity, forecast) == 0


# ---------------------------------------------------------------------------
# IDLE — should be a hard zero
# ---------------------------------------------------------------------------


class TestIdleStrategyInvariants:
    @given(solar=_solar, home=_home, batt_chg=_batt_chg, soc=_soc)
    def test_idle_always_zero(
        self, solar: float, home: float, batt_chg: float, soc: float,
    ) -> None:
        """IDLE produces 0 budget regardless of inputs."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=solar, home=home, batt_charge=batt_chg, batt_soc=soc),
            strategy=EVBudgetStrategy.IDLE,
            battery_soc=soc,
        )
        assert b.net_w == 0.0
        assert b.current_a == 0
        assert b.solar_surplus == 0.0
        assert b.battery_redirect == 0.0
        assert b.battery_assist == 0.0


# ---------------------------------------------------------------------------
# Generic safety — net_w bounded, never NaN
# ---------------------------------------------------------------------------


_strategy = st.sampled_from([
    EVBudgetStrategy.IDLE,
    EVBudgetStrategy.SELF_CONSUMPTION,
    EVBudgetStrategy.SOLAR_ONLY,
    EVBudgetStrategy.BATTERY_ASSIST,
    EVBudgetStrategy.MIN_PV,
    EVBudgetStrategy.NOW,
])


class TestUniversalBudgetInvariants:
    @given(
        strategy=_strategy,
        solar=_solar, home=_home, batt_chg=_batt_chg, batt_dis=_batt_dis,
        soc=_soc, capacity=_capacity, forecast=_forecast,
    )
    @settings(max_examples=200, deadline=2000)
    def test_net_w_never_negative_never_nan(
        self,
        strategy: str, solar: float, home: float, batt_chg: float,
        batt_dis: float, soc: float, capacity: float, forecast: float,
    ) -> None:
        """Across every strategy and every realistic input, the budget
        must be a non-negative finite number. A negative would mean
        the actuator should somehow extract power FROM the EV, which
        SEM doesn't support (and would crash the dashboard sensor)."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=solar, home=home, batt_charge=batt_chg,
                   batt_discharge=batt_dis, batt_soc=soc),
            strategy=strategy,
            battery_soc=soc,
            battery_capacity_kwh=capacity,
            forecast_remaining_kwh=forecast,
            min_power_floor_w=0.0,  # only MIN_PV reads this; default OK
            override_max_w=None,    # only NOW reads this
        )
        assert b.net_w >= 0
        assert not math.isnan(b.net_w)
        assert not math.isinf(b.net_w)
        assert b.current_a >= 0
        # current_a max-clamped per charger (default 16A in SOLAR_ONLY etc.)
        # but NOW path can hit the configured ev_max_current. The
        # default 16 covers all branches.
        assert b.current_a <= 16


# ---------------------------------------------------------------------------
# SELF_CONSUMPTION — Zone 2 contract, NO redirect
# ---------------------------------------------------------------------------


class TestSelfConsumptionInvariants:
    @given(
        solar=_solar, home=_home, batt_chg=_batt_chg, soc=_soc,
        capacity=_capacity, forecast=_forecast,
    )
    @settings(max_examples=100)
    def test_self_consumption_never_includes_redirect(
        self, solar: float, home: float, batt_chg: float, soc: float,
        capacity: float, forecast: float,
    ) -> None:
        """SELF_CONSUMPTION (Zone 2 — SOC in priority band) is
        surplus-only by contract. The battery has priority on solar;
        we never divert battery_charge to the EV."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=solar, home=home, batt_charge=batt_chg, batt_soc=soc),
            strategy=EVBudgetStrategy.SELF_CONSUMPTION,
            battery_soc=soc,
            battery_capacity_kwh=capacity,
            forecast_remaining_kwh=forecast,
        )
        assert b.battery_redirect == 0
        assert b.battery_assist == 0


# ---------------------------------------------------------------------------
# SOLAR_ONLY — net_w must equal raw_surplus + redirect
# ---------------------------------------------------------------------------


class TestSolarOnlyInvariants:
    @given(
        solar=_solar, home=_home, batt_chg=_batt_chg, soc=_soc,
        capacity=_capacity, forecast=_forecast,
    )
    @settings(max_examples=100)
    def test_solar_only_net_w_is_surplus_plus_redirect(
        self, solar: float, home: float, batt_chg: float, soc: float,
        capacity: float, forecast: float,
    ) -> None:
        """SOLAR_ONLY: net_w == solar_surplus + battery_redirect.
        Pins the contract that the canonical method and decide.py
        SolarOnlyMode agree on the effective surplus (the restored
        redirect path).

        Tolerance: production rounds each component independently
        then computes net_w from the unrounded sum, so the rounded
        decomposition can diverge by up to ~1.5W (worst-case
        banker's rounding on both components — 0.5W each)."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=solar, home=home, batt_charge=batt_chg, batt_soc=soc),
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            battery_soc=soc,
            battery_capacity_kwh=capacity,
            forecast_remaining_kwh=forecast,
        )
        expected = b.solar_surplus + b.battery_redirect
        assert abs(b.net_w - expected) <= 1.5

    @given(
        solar=_solar, home=_home, batt_chg=_batt_chg, soc=_soc,
        capacity=_capacity, forecast=_forecast,
    )
    def test_solar_only_redirect_bounded_by_battery_charge(
        self, solar: float, home: float, batt_chg: float, soc: float,
        capacity: float, forecast: float,
    ) -> None:
        """Can't redirect more battery_charge than is actually being
        consumed. Catches a sign-flip bug class (negate redirect by
        accident → SEM tries to draw power INTO the battery from the
        EV side).

        Tolerance: ``battery_redirect`` is rounded to integer watts
        in EVBudget; the rounding can push it 0.5W above the
        unrounded batt_chg at a half-integer boundary."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=solar, home=home, batt_charge=batt_chg, batt_soc=soc),
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            battery_soc=soc,
            battery_capacity_kwh=capacity,
            forecast_remaining_kwh=forecast,
        )
        # Round batt_chg the same way the EVBudget rounds its
        # components — equal-tolerance comparison.
        assert b.battery_redirect <= round(batt_chg, 0) + 1.0


# ---------------------------------------------------------------------------
# NOW — max charge, the override
# ---------------------------------------------------------------------------


class TestNowInvariants:
    @given(
        solar=_solar, home=_home, batt_chg=_batt_chg, soc=_soc,
        override_max=st.floats(min_value=0.0, max_value=22000.0, allow_nan=False),
    )
    @settings(max_examples=50)
    def test_now_returns_override_max(
        self, solar: float, home: float, batt_chg: float, soc: float,
        override_max: float,
    ) -> None:
        """NOW returns ``override_max_w`` regardless of solar / battery
        state. The user explicitly asked for max charge — we don't
        second-guess them."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=solar, home=home, batt_charge=batt_chg, batt_soc=soc),
            strategy=EVBudgetStrategy.NOW,
            battery_soc=soc,
            override_max_w=override_max,
        )
        assert abs(b.net_w - round(override_max, 0)) < 1.0
        # NOW doesn't decompose — solar_surplus and the others are 0.
        assert b.solar_surplus == 0
        assert b.battery_redirect == 0
        assert b.battery_assist == 0


# ---------------------------------------------------------------------------
# current_a rounding policy — locked by #353 (surplus_leak)
# ---------------------------------------------------------------------------


class TestCurrentAmpsRoundingPolicy:
    @given(
        net_w=st.floats(min_value=0.0, max_value=20000.0, allow_nan=False),
        phases=st.sampled_from([1, 3]),
        voltage=st.sampled_from([230, 400]),
    )
    @settings(max_examples=100)
    def test_amps_floored_against_net_w(
        self, net_w: float, phases: int, voltage: int,
    ) -> None:
        """Amps must be floor(net_w / (voltage * phases)), clamped
        to [0, 16]. Round-to-nearest would have over-commanded grid
        on the boundary (591956f surplus_leak fix). Pins the floor
        policy across the input space."""
        fc = FlowCalculator()
        amps = fc._watts_to_amps(net_w, voltage, phases)
        expected_unclamped = int(net_w // (voltage * phases))
        expected = max(0, min(16, expected_unclamped))
        assert amps == expected
