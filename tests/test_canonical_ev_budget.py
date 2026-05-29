"""Unit tests for the canonical EV-budget calculation (#282 Phase A).

These cover the regimes that historically caused the three legacy paths
(coordinator B1, coordinator B2, ev_control B3) to disagree:

  - Zone 2 self_consumption WITH battery_redirect available — the trace
    where state machine returned SOLAR_CHARGING_ACTIVE while the
    actuator returned 0 A. The canonical method must not add redirect
    to self_consumption.
  - Zone 4 battery_assist with measured discharge AND with estimated
    discharge. The legacy B2 missed assist entirely; B3 had it but the
    formula lived only in ev_control.
  - solar_only round-down vs round-to-nearest at the boundary —
    locks in the surplus-leak fix from 591956f.
  - min_pv floor — the actuator's `max(min_power_threshold, ...)`
    is now in the canonical method, not the caller.
  - now override — full charger power, surplus components are zero so
    diagnostic sensors stay honest.
  - idle — everything zero.

The two scenario harness files exercise the same regimes against the
full coordinator pipeline; this file is the unit-level guarantee.
"""
import pytest

from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
    EVBudget,
    EVBudgetStrategy,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings


def _power(*, solar=0.0, home=0.0, batt_charge=0.0, batt_discharge=0.0,
           batt_soc=50.0, ev=0.0, grid_export=0.0, grid_import=0.0,
           ev_connected=False):
    """Build a PowerReadings with derived fields set directly.

    We bypass ``calculate_derived`` because it recomputes
    ``home_consumption_power`` from the energy balance, which makes
    "set home=X exactly" tests fiddly. The canonical budget method
    only reads the derived fields anyway, so setting them directly
    is faithful to the coordinator's view at the call site.
    """
    # signed convention for the constructor
    battery_power = batt_charge - batt_discharge
    grid_power = grid_export - grid_import
    p = PowerReadings(
        solar_power=solar,
        home_consumption_power=home,
        battery_power=battery_power,
        battery_soc=batt_soc,
        ev_power=ev,
        ev_connected=ev_connected,
        grid_power=grid_power,
    )
    # Set derived fields directly (matches what coordinator sees after
    # calculate_derived, but with home as we asked).
    p.grid_import_power = grid_import
    p.grid_export_power = grid_export
    p.battery_charge_power = batt_charge
    p.battery_discharge_power = batt_discharge
    return p


# ──────────────────────────────────────────────────────────────────────
# IDLE — everything zero
# ──────────────────────────────────────────────────────────────────────

class TestIdle:
    def test_idle_returns_all_zero(self):
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=5000, home=500),
            strategy=EVBudgetStrategy.IDLE,
        )
        assert b.strategy == "idle"
        assert b.solar_surplus == 0
        assert b.battery_redirect == 0
        assert b.battery_assist == 0
        assert b.net_w == 0
        assert b.current_a == 0


# ──────────────────────────────────────────────────────────────────────
# SELF_CONSUMPTION — Zone 2. Surplus only, NO redirect.
# This is the regime where the legacy paths disagreed.
# ──────────────────────────────────────────────────────────────────────

class TestSelfConsumption:
    def test_zone2_no_redirect_even_with_battery_charging(self):
        """Replay of the 2026-05-29 PROD bug regime.

        solar=2025, home=100, batt_charge=1900, batt_soc=36.
        Legacy B2 returned ~surplus + redirect → ctx.calculated_current = 3.
        Legacy B3 returned just surplus → 0 A. Display lied.

        Canonical SELF_CONSUMPTION matches B3: no redirect, raw surplus.
        """
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=2025, home=100, batt_charge=1900, batt_soc=36),
            strategy=EVBudgetStrategy.SELF_CONSUMPTION,
            battery_soc=36,
        )
        # raw_surplus = max(0, 2025 - 100 - 1900) = 25
        assert b.solar_surplus == 25
        assert b.battery_redirect == 0  # the whole point of this test
        assert b.battery_assist == 0
        assert b.net_w == 25
        # 25 W / 690 V·phases = 0.036 A → floor to 0
        assert b.current_a == 0

    def test_zone4_self_consumption_does_not_subtract_battery_charge(self):
        """When SOC ≥ auto_start_soc the battery doesn't need its share,
        so self_consumption skips the batt_charge subtraction. Mirrors
        _self_consumption_strategy's Z4-redirect branch."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=3000, home=500, batt_charge=2000, batt_soc=95),
            strategy=EVBudgetStrategy.SELF_CONSUMPTION,
            battery_soc=95,
            battery_auto_start_soc=90,
        )
        # solar - home = 2500; battery_charge NOT subtracted in Z4
        assert b.solar_surplus == 2500
        assert b.net_w == 2500


# ──────────────────────────────────────────────────────────────────────
# SOLAR_ONLY — Zone 3. Surplus + forecast-aware redirect.
# ──────────────────────────────────────────────────────────────────────

class TestSolarOnly:
    def test_zone3_with_redirect_when_forecast_covers_battery(self):
        """Forecast says 30 kWh remaining, battery needs ~10 kWh more
        → redirect kicks in."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=4000, home=500, batt_charge=2000, batt_soc=60),
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            battery_soc=60,
            battery_capacity_kwh=15,
            forecast_remaining_kwh=30,
        )
        # raw_surplus = max(0, 4000 - 500 - 2000) = 1500
        # battery_need = (100 - 60)/100 * 15 = 6 kWh
        # forecast (30) >= need (6) → redirect proportional
        # ratio = 1 - 6/30 = 0.8 → redirect = 2000 * 0.8 = 1600
        assert b.solar_surplus == 1500
        assert b.battery_redirect == 1600
        assert b.net_w == 3100
        # 3100 / 690 = 4.49 → floor to 4
        assert b.current_a == 4

    def test_zone3_no_redirect_without_forecast_and_low_soc(self):
        """No forecast + SOC below 80% → no redirect. Battery keeps it all."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=4000, home=500, batt_charge=2000, batt_soc=60),
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            battery_soc=60,
            forecast_remaining_kwh=0,
        )
        assert b.battery_redirect == 0
        assert b.net_w == 1500

    def test_solar_only_floors_amps_to_strictly_under_budget(self):
        """5200 W / 690 = 7.53 A. Round-to-nearest would give 8 A (which
        is 5520 W — 320 W of grid). Floor must give 7 A. Locks 591956f."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=5700, home=500, batt_soc=85),
            strategy=EVBudgetStrategy.SOLAR_ONLY,
            battery_soc=85,
        )
        assert b.solar_surplus == 5200
        # No battery charging, no redirect needed
        assert b.current_a == 7  # NOT 8


# ──────────────────────────────────────────────────────────────────────
# BATTERY_ASSIST — Zone 4. Surplus + redirect + actual discharge.
# ──────────────────────────────────────────────────────────────────────

class TestBatteryAssist:
    def test_uses_measured_discharge_when_battery_already_discharging(self):
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=1000, home=500, batt_discharge=3000, batt_soc=75),
            strategy=EVBudgetStrategy.BATTERY_ASSIST,
            battery_soc=75,
        )
        # raw_surplus = max(0, 1000 - 500 - 0) = 500
        # redirect = 0 (battery not charging)
        # assist = measured discharge = 3000
        assert b.solar_surplus == 500
        assert b.battery_redirect == 0
        assert b.battery_assist == 3000
        assert b.net_w == 3500

    def test_estimates_assist_proportionally_in_zone3_band(self):
        """SOC = 80, buffer=70, auto_start=90.
        ratio = (80-70)/(90-70) = 0.5
        assist = 4500 * (0.5 + 0.5 * 0.5) = 4500 * 0.75 = 3375
        """
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=800, home=500, batt_soc=80),
            strategy=EVBudgetStrategy.BATTERY_ASSIST,
            battery_soc=80,
            battery_auto_start_soc=90,
            battery_buffer_soc=70,
            battery_assist_floor_soc=60,
            battery_assist_max_power_w=4500,
        )
        assert b.battery_assist == 3375

    def test_no_assist_below_assist_floor(self):
        """SOC below the assist floor → no assist contribution."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=800, home=500, batt_soc=50),
            strategy=EVBudgetStrategy.BATTERY_ASSIST,
            battery_soc=50,
            battery_assist_floor_soc=60,
        )
        assert b.battery_assist == 0


# ──────────────────────────────────────────────────────────────────────
# MIN_PV — surplus floored at min_power_floor_w. User accepts grid backfill.
# ──────────────────────────────────────────────────────────────────────

class TestMinPV:
    def test_floor_applied_when_surplus_below(self):
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=2000, home=500),
            strategy=EVBudgetStrategy.MIN_PV,
            min_power_floor_w=4140,  # 6 A * 3 * 230
        )
        # raw_surplus = 1500, no redirect (no battery charging)
        # floor = 4140 → net_w = 4140 (grid backfills the gap)
        assert b.net_w == 4140
        # 4140 / 690 = 6.0 exactly → floor stays at 6
        assert b.current_a == 6

    def test_floor_ignored_when_surplus_above(self):
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=10_000, home=500),
            strategy=EVBudgetStrategy.MIN_PV,
            min_power_floor_w=4140,
        )
        # raw_surplus = 9500 > floor 4140 → use surplus
        assert b.net_w == 9500


# ──────────────────────────────────────────────────────────────────────
# NOW — user override, full charger power
# ──────────────────────────────────────────────────────────────────────

class TestNow:
    def test_now_uses_override_max_w(self):
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=0, home=500),
            strategy=EVBudgetStrategy.NOW,
            override_max_w=11_040,  # 16 A * 3 * 230
        )
        # NOW intentionally ignores surplus — components stay 0 so the
        # diagnostic sensors are honest about "this is not from solar".
        assert b.solar_surplus == 0
        assert b.battery_redirect == 0
        assert b.battery_assist == 0
        assert b.net_w == 11_040
        assert b.current_a == 16

    def test_now_defaults_to_full_charger_power_without_override(self):
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=0),
            strategy=EVBudgetStrategy.NOW,
        )
        # default = 16 A * 3 * 230 = 11040
        assert b.net_w == 11_040
        assert b.current_a == 16


# ──────────────────────────────────────────────────────────────────────
# Unknown strategy
# ──────────────────────────────────────────────────────────────────────

class TestUnknownStrategy:
    def test_unknown_strategy_raises_loud_error(self):
        """Refuse silent fallthrough — that was the #282 disagreement root."""
        fc = FlowCalculator()
        with pytest.raises(ValueError, match="unknown strategy"):
            fc.calculate_canonical_ev_budget(
                _power(),
                strategy="some_new_strategy_we_forgot_to_map",
            )


# ──────────────────────────────────────────────────────────────────────
# Decomposition invariant — net_w == sum of components for non-override
# strategies
# ──────────────────────────────────────────────────────────────────────

class TestDecompositionInvariant:
    @pytest.mark.parametrize("strategy", [
        EVBudgetStrategy.SELF_CONSUMPTION,
        EVBudgetStrategy.SOLAR_ONLY,
        EVBudgetStrategy.BATTERY_ASSIST,
    ])
    def test_components_sum_to_net_for_non_override_strategies(self, strategy):
        """For everything except IDLE/NOW/MIN_PV (which have explicit
        overrides), net_w must equal the sum of the named components.
        This is the property the forever-sentinel live test will assert."""
        fc = FlowCalculator()
        b = fc.calculate_canonical_ev_budget(
            _power(solar=4000, home=500, batt_discharge=1500, batt_soc=75),
            strategy=strategy,
            battery_soc=75,
            forecast_remaining_kwh=20,
        )
        # Sum component breakdown matches net_w (within rounding).
        assert b.net_w == b.solar_surplus + b.battery_redirect + b.battery_assist
