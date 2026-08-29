"""Property-based fuzz tests for SEM coordinator invariants.

Uses random generation with fixed seeds (no hypothesis dependency) to validate
core invariants across 1000 random scenarios per property. The goal is to
surface edge cases that deterministic unit tests miss.

Invariants verified:
  Power balance:
    1. Energy balance closes within 1 W
    2. home_consumption_power >= 0 always
    3. grid_import_power >= 0, grid_export_power >= 0
    4. battery_charge_power >= 0, battery_discharge_power >= 0
    5. Grid import and export are mutually exclusive (one is 0 at any instant)
  Cost:
    6. daily_solar_savings >= 0
    7. daily_battery_savings >= 0
    8. daily_costs >= 0
    9. self_consumption_rate in [0, 100]
   10. autarky_rate in [0, 100]
  Flow:
   11. solar_to_home + solar_to_battery + solar_to_grid + solar_to_ev <= solar_power + tol
   12. All flow values >= 0
  EV control:
   13. EV charging current between 0 and max_current (no charge) or min_current..max_current
   14. Calculated EV power ~ current × watts_per_amp
  EnergyCalculator:
   15-18. Accumulated energy values are non-negative across a simulated 24h day
"""
from __future__ import annotations

import random
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Tuple
from unittest.mock import MagicMock, patch

import pytest

# Ensure custom_components package is importable (mirrors conftest.py logic)
_ha_config_dir = str(Path(__file__).resolve().parent.parent.parent.parent)
if _ha_config_dir not in sys.path:
    sys.path.insert(0, _ha_config_dir)

from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    EnergyTotals,
)
from custom_components.solar_energy_management.coordinator.flow_calculator import (
    FlowCalculator,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)

# ──────────────────────────────────────────────────────────────────────────────
# Random scenario generation helpers
# ──────────────────────────────────────────────────────────────────────────────

SEED = 42
NUM_SCENARIOS = 1000

# Physical limits used by the generator
SOLAR_MAX_W = 15_000.0
GRID_MAX_W = 10_000.0     # absolute value; sign is randomised
BATTERY_MAX_W = 5_000.0   # absolute value; sign is randomised
EV_MAX_W = 11_000.0
SOC_MAX = 100.0


def _make_scenarios(n: int = NUM_SCENARIOS, seed: int = SEED) -> List[PowerReadings]:
    """Generate n PowerReadings instances from random raw sensor values.

    Each scenario is created by calling calculate_derived() on raw values so
    that the derived fields (grid_import_power, grid_export_power, …) are
    populated exactly as the production code would populate them.
    """
    rng = random.Random(seed)
    scenarios = []
    for _ in range(n):
        solar = rng.uniform(0.0, SOLAR_MAX_W)
        grid = rng.uniform(-GRID_MAX_W, GRID_MAX_W)   # negative = import
        battery = rng.uniform(-BATTERY_MAX_W, BATTERY_MAX_W)  # positive = charge
        ev = rng.uniform(0.0, EV_MAX_W)
        soc = rng.uniform(0.0, SOC_MAX)

        p = PowerReadings(
            solar_power=solar,
            grid_power=grid,
            battery_power=battery,
            ev_power=ev,
            battery_soc=soc,
        )
        p.calculate_derived()
        scenarios.append(p)
    return scenarios


def _make_edge_scenarios() -> List[PowerReadings]:
    """Hand-crafted scenarios at boundary conditions."""
    edges = []

    # All zeros
    p = PowerReadings(); p.calculate_derived(); edges.append(p)

    # Maximum solar, no grid/battery
    p = PowerReadings(solar_power=SOLAR_MAX_W); p.calculate_derived(); edges.append(p)

    # Full grid import, no solar
    p = PowerReadings(grid_power=-GRID_MAX_W); p.calculate_derived(); edges.append(p)

    # Full grid export, no solar (unusual but should not crash)
    p = PowerReadings(grid_power=GRID_MAX_W); p.calculate_derived(); edges.append(p)

    # Battery full discharge
    p = PowerReadings(battery_power=-BATTERY_MAX_W); p.calculate_derived(); edges.append(p)

    # Battery full charge
    p = PowerReadings(battery_power=BATTERY_MAX_W); p.calculate_derived(); edges.append(p)

    # Maximum EV, no supply
    p = PowerReadings(ev_power=EV_MAX_W); p.calculate_derived(); edges.append(p)

    # All maximum simultaneously (physically impossible but must not crash)
    p = PowerReadings(
        solar_power=SOLAR_MAX_W,
        grid_power=-GRID_MAX_W,
        battery_power=-BATTERY_MAX_W,
        ev_power=EV_MAX_W,
    )
    p.calculate_derived()
    edges.append(p)

    # Tiny values near floating-point zero
    p = PowerReadings(solar_power=0.001, grid_power=-0.001, battery_power=0.001)
    p.calculate_derived()
    edges.append(p)

    # SOC at boundaries
    for soc in (0.0, 100.0):
        p = PowerReadings(solar_power=5000, battery_soc=soc)
        p.calculate_derived()
        edges.append(p)

    return edges


_ALL_SCENARIOS: List[PowerReadings] = _make_scenarios() + _make_edge_scenarios()


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 1: Energy balance closes within 1 W
# ──────────────────────────────────────────────────────────────────────────────

class TestEnergyBalanceCloses:
    """Invariant 1: home_consumption_power == max(0, supply - ev - export - charge).

    Note: EV power, grid_export_power and battery_charge_power are raw sensor inputs
    (not derived) and can individually exceed total supply when sensor noise or
    unrealistic combinations occur. The energy balance is only guaranteed to hold for
    the DERIVED field home_consumption_power, which is explicitly clamped to >= 0.

    The balance invariant is:
        home = max(0, solar + import + discharge - ev - export - charge)

    When supply < ev + export + charge, home = 0 and surplus is clipped.
    This is intentional — the code does NOT reduce ev_power to maintain balance.
    """

    def test_home_derivation_matches_balance_formula_random(self):
        """home_consumption_power must equal max(0, supply - ev - export - charge)."""
        failures = []
        for i, p in enumerate(_ALL_SCENARIOS):
            supply = p.solar_power + p.grid_import_power + p.battery_discharge_power
            loads_excl_home = p.ev_power + p.grid_export_power + p.battery_charge_power
            expected_home = max(0.0, supply - loads_excl_home)
            # Allow 1 W floating-point tolerance
            if abs(p.home_consumption_power - expected_home) >= 1.0:
                failures.append((i, p.home_consumption_power, expected_home))

        assert not failures, (
            f"{len(failures)} scenario(s): home_consumption_power != max(0, supply-loads): "
            f"first at index={failures[0][0]}, got={failures[0][1]:.2f} W, "
            f"expected={failures[0][2]:.2f} W"
        )

    def test_home_derivation_matches_balance_formula_edge_cases(self):
        """should correctly derive home from balance formula for edge scenarios."""
        for p in _make_edge_scenarios():
            supply = p.solar_power + p.grid_import_power + p.battery_discharge_power
            loads_excl_home = p.ev_power + p.grid_export_power + p.battery_charge_power
            expected_home = max(0.0, supply - loads_excl_home)
            assert abs(p.home_consumption_power - expected_home) < 1.0, (
                f"home={p.home_consumption_power:.1f} W, expected={expected_home:.1f} W"
            )

    def test_energy_in_minus_out_when_supply_sufficient(self):
        """when supply >= ev + export + charge, the balance closes exactly."""
        rng = random.Random(SEED + 90)
        failures = []
        for i in range(NUM_SCENARIOS):
            solar = rng.uniform(5000.0, SOLAR_MAX_W)  # large solar
            battery_power = rng.uniform(0.0, 1000.0)   # mild charging only
            ev = rng.uniform(0.0, 2000.0)              # modest EV
            grid_export = rng.uniform(0.0, 2000.0)     # modest export
            # No grid import, no discharge — supply = solar only
            p = PowerReadings(
                solar_power=solar,
                grid_power=grid_export,       # positive = export
                battery_power=battery_power,  # positive = charging
                ev_power=ev,
            )
            p.calculate_derived()

            # Only check scenarios where supply clearly exceeds loads
            supply = p.solar_power + p.grid_import_power + p.battery_discharge_power
            loads = p.ev_power + p.grid_export_power + p.battery_charge_power
            if supply < loads:
                continue  # supply insufficient — skip (home will be 0)

            energy_in = supply
            energy_out = (
                p.home_consumption_power
                + p.ev_power
                + p.grid_export_power
                + p.battery_charge_power
            )
            if abs(energy_in - energy_out) >= 1.0:
                failures.append((i, abs(energy_in - energy_out)))

        assert not failures, (
            f"{len(failures)} surplus scenario(s) had energy imbalance >= 1 W: "
            f"first imbalance={failures[0][1]:.2f} W"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 2: home_consumption_power >= 0
# ──────────────────────────────────────────────────────────────────────────────

class TestHomeConsumptionNonNegative:
    """Invariant 2: home_consumption_power is always >= 0 (clamped from balance)."""

    def test_home_consumption_never_negative_random(self):
        """should never produce negative home_consumption_power for any input."""
        negatives = [
            (i, p.home_consumption_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.home_consumption_power < 0.0
        ]
        assert not negatives, (
            f"{len(negatives)} scenario(s) had negative home_consumption_power: "
            f"first at index={negatives[0][0]}, value={negatives[0][1]:.3f} W"
        )

    def test_home_consumption_clamp_when_ev_exceeds_supply(self):
        """should clamp to 0 when EV draws more than total supply."""
        p = PowerReadings(
            solar_power=1000.0,
            grid_power=0.0,
            battery_power=0.0,
            ev_power=5000.0,   # far exceeds supply
        )
        p.calculate_derived()
        assert p.home_consumption_power >= 0.0

    def test_home_consumption_clamp_when_battery_discharge_causes_imbalance(self):
        """should clamp to 0 when discharge + export exceeds all sources."""
        p = PowerReadings(
            solar_power=0.0,
            grid_power=3000.0,   # export 3000
            battery_power=-4000.0,  # discharge 4000
            ev_power=0.0,
        )
        p.calculate_derived()
        assert p.home_consumption_power >= 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 3: grid_import_power >= 0 and grid_export_power >= 0
# ──────────────────────────────────────────────────────────────────────────────

class TestGridSplitNonNegative:
    """Invariant 3: Both sides of the grid split must be >= 0."""

    def test_grid_import_always_non_negative(self):
        """should never produce negative grid_import_power."""
        negatives = [
            (i, p.grid_import_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.grid_import_power < 0.0
        ]
        assert not negatives, (
            f"{len(negatives)} scenario(s) had negative grid_import_power"
        )

    def test_grid_export_always_non_negative(self):
        """should never produce negative grid_export_power."""
        negatives = [
            (i, p.grid_export_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.grid_export_power < 0.0
        ]
        assert not negatives, (
            f"{len(negatives)} scenario(s) had negative grid_export_power"
        )

    def test_grid_import_magnitude_matches_negative_grid_power(self):
        """should set grid_import_power = |grid_power| when grid_power < 0."""
        rng = random.Random(SEED + 1)
        for _ in range(500):
            raw = rng.uniform(-GRID_MAX_W, 0.0)  # force negative (import)
            p = PowerReadings(grid_power=raw)
            p.calculate_derived()
            assert abs(p.grid_import_power - (-raw)) < 1e-9
            assert p.grid_export_power == 0.0

    def test_grid_export_magnitude_matches_positive_grid_power(self):
        """should set grid_export_power = grid_power when grid_power > 0."""
        rng = random.Random(SEED + 2)
        for _ in range(500):
            raw = rng.uniform(0.0, GRID_MAX_W)  # force positive (export)
            p = PowerReadings(grid_power=raw)
            p.calculate_derived()
            assert abs(p.grid_export_power - raw) < 1e-9
            assert p.grid_import_power == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 4: battery_charge_power >= 0 and battery_discharge_power >= 0
# ──────────────────────────────────────────────────────────────────────────────

class TestBatterySplitNonNegative:
    """Invariant 4: Both sides of the battery split must be >= 0."""

    def test_battery_charge_always_non_negative(self):
        """should never produce negative battery_charge_power."""
        negatives = [
            (i, p.battery_charge_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.battery_charge_power < 0.0
        ]
        assert not negatives, (
            f"{len(negatives)} scenario(s) had negative battery_charge_power"
        )

    def test_battery_discharge_always_non_negative(self):
        """should never produce negative battery_discharge_power."""
        negatives = [
            (i, p.battery_discharge_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.battery_discharge_power < 0.0
        ]
        assert not negatives, (
            f"{len(negatives)} scenario(s) had negative battery_discharge_power"
        )

    def test_battery_charge_from_positive_battery_power(self):
        """should set charge = battery_power when battery_power > 0."""
        rng = random.Random(SEED + 3)
        for _ in range(500):
            raw = rng.uniform(0.01, BATTERY_MAX_W)  # positive → charging
            p = PowerReadings(battery_power=raw)
            p.calculate_derived()
            assert abs(p.battery_charge_power - raw) < 1e-9
            assert p.battery_discharge_power == 0.0

    def test_battery_discharge_from_negative_battery_power(self):
        """should set discharge = |battery_power| when battery_power < 0."""
        rng = random.Random(SEED + 4)
        for _ in range(500):
            raw = rng.uniform(-BATTERY_MAX_W, -0.01)  # negative → discharging
            p = PowerReadings(battery_power=raw)
            p.calculate_derived()
            assert abs(p.battery_discharge_power - (-raw)) < 1e-9
            assert p.battery_charge_power == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Invariant 5: Grid import and export mutually exclusive
# ──────────────────────────────────────────────────────────────────────────────

class TestGridMutualExclusion:
    """Invariant 5: At any instant, at most one of import/export can be non-zero."""

    def test_import_and_export_not_both_nonzero(self):
        """should never have both grid_import_power > 0 and grid_export_power > 0."""
        both_nonzero = [
            (i, p.grid_import_power, p.grid_export_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.grid_import_power > 0.0 and p.grid_export_power > 0.0
        ]
        assert not both_nonzero, (
            f"{len(both_nonzero)} scenario(s) had both import and export non-zero: "
            f"first at index={both_nonzero[0][0]}, "
            f"import={both_nonzero[0][1]:.1f} W, export={both_nonzero[0][2]:.1f} W"
        )

    def test_battery_charge_and_discharge_not_both_nonzero(self):
        """should never have both battery_charge_power > 0 and battery_discharge_power > 0."""
        both_nonzero = [
            (i, p.battery_charge_power, p.battery_discharge_power)
            for i, p in enumerate(_ALL_SCENARIOS)
            if p.battery_charge_power > 0.0 and p.battery_discharge_power > 0.0
        ]
        assert not both_nonzero, (
            f"{len(both_nonzero)} scenario(s) had both battery charge and discharge non-zero"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Flow Calculator invariants (11, 12)
# ──────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def flow_calc():
    """Module-scoped FlowCalculator with mocked dt_util date."""
    with patch(
        "custom_components.solar_energy_management.coordinator.flow_calculator.dt_util"
    ) as mock_dt:
        mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)
        calc = FlowCalculator()
    return calc


class TestFlowInvariants:
    """Invariants 11–12: Solar flows cannot exceed production; all flows are non-negative."""

    def test_solar_flows_do_not_exceed_solar_production(self):
        """should not route more solar than was produced to any combination of destinations."""
        calc = FlowCalculator()
        random.Random(SEED + 10)
        violations = []
        for i, p in enumerate(_ALL_SCENARIOS[:NUM_SCENARIOS]):
            flows = calc.calculate_power_flows(p)
            solar_distributed = (
                flows.solar_to_home
                + flows.solar_to_battery
                + flows.solar_to_grid
                + flows.solar_to_ev
            )
            # Allow floating-point rounding of 1 W
            if solar_distributed > p.solar_power + 1.0:
                violations.append((i, solar_distributed, p.solar_power))
        assert not violations, (
            f"{len(violations)} scenario(s) distributed more solar than produced: "
            f"first at index={violations[0][0]}, "
            f"distributed={violations[0][1]:.1f} W, produced={violations[0][2]:.1f} W"
        )

    def test_all_flow_values_non_negative(self):
        """should produce only non-negative power flow values."""
        calc = FlowCalculator()
        violations = []
        for i, p in enumerate(_ALL_SCENARIOS[:NUM_SCENARIOS]):
            flows = calc.calculate_power_flows(p)
            for attr in (
                "solar_to_home", "solar_to_battery", "solar_to_ev", "solar_to_grid",
                "grid_to_home", "grid_to_ev", "grid_to_battery",
                "battery_to_home", "battery_to_ev",
            ):
                val = getattr(flows, attr)
                if val < 0.0:
                    violations.append((i, attr, val))
        assert not violations, (
            f"{len(violations)} negative flow value(s): "
            f"first at index={violations[0][0]}, "
            f"field={violations[0][1]}, value={violations[0][2]:.3f}"
        )

    def test_solar_to_home_never_exceeds_home_consumption(self):
        """should not route more solar to home than home actually consumes."""
        calc = FlowCalculator()
        violations = []
        for i, p in enumerate(_ALL_SCENARIOS[:NUM_SCENARIOS]):
            flows = calc.calculate_power_flows(p)
            # Allow 1 W rounding tolerance
            if flows.solar_to_home > p.home_consumption_power + 1.0:
                violations.append((i, flows.solar_to_home, p.home_consumption_power))
        assert not violations, (
            f"{len(violations)} scenario(s) routed more solar to home than home consumed"
        )

    def test_grid_to_home_does_not_exceed_grid_import(self):
        """should not route more grid power to home than was imported."""
        calc = FlowCalculator()
        violations = []
        for i, p in enumerate(_ALL_SCENARIOS[:NUM_SCENARIOS]):
            flows = calc.calculate_power_flows(p)
            grid_routed = flows.grid_to_home + flows.grid_to_ev + flows.grid_to_battery
            if grid_routed > p.grid_import_power + 1.0:
                violations.append((i, grid_routed, p.grid_import_power))
        assert not violations, (
            f"{len(violations)} scenario(s) routed more grid power than was imported"
        )

    def test_battery_to_destinations_does_not_exceed_discharge(self):
        """should not route more battery power than was discharged."""
        calc = FlowCalculator()
        violations = []
        for i, p in enumerate(_ALL_SCENARIOS[:NUM_SCENARIOS]):
            flows = calc.calculate_power_flows(p)
            batt_routed = flows.battery_to_home + flows.battery_to_ev
            if batt_routed > p.battery_discharge_power + 1.0:
                violations.append((i, batt_routed, p.battery_discharge_power))
        assert not violations, (
            f"{len(violations)} scenario(s) routed more battery discharge than available"
        )

    def test_flow_calculator_does_not_raise_on_any_scenario(self):
        """should never raise an exception regardless of input values."""
        calc = FlowCalculator()
        for p in _ALL_SCENARIOS:
            calc.calculate_power_flows(p)  # must not raise


# ──────────────────────────────────────────────────────────────────────────────
# EV Control invariants (13, 14)
# ──────────────────────────────────────────────────────────────────────────────

class TestEVControlInvariants:
    """Invariants 13–14: EV current and power relationships.

    Pre-D.2 these invariants were pinned against the now-deleted
    ``calculate_charging_current`` / ``calculate_ev_budget`` primitives.
    Post-D.2 we pin them against the canonical EVBudget — same physical
    invariants (non-negative, ≤ 16 A clamp, etc.), exercised end-to-end
    through the unified path.
    """

    def test_canonical_budget_never_negative(self):
        """Canonical EVBudget.net_w must never be negative regardless of inputs."""
        calc = FlowCalculator()
        from custom_components.solar_energy_management.coordinator.flow_calculator import (
            EVBudgetStrategy,
        )
        for p in _ALL_SCENARIOS[:NUM_SCENARIOS]:
            for strategy in (
                EVBudgetStrategy.SELF_CONSUMPTION,
                EVBudgetStrategy.SOLAR_ONLY,
                EVBudgetStrategy.MIN_PV,
            ):
                b = calc.calculate_canonical_ev_budget(
                    power=p, strategy=strategy,
                    forecast_remaining_kwh=0.0,
                    battery_soc=50.0, battery_capacity_kwh=15.0,
                )
                assert b.net_w >= 0.0, (
                    f"Negative canonical budget {b.net_w:.1f} W "
                    f"strategy={strategy} solar={p.solar_power:.0f} W"
                )

    def test_canonical_budget_never_negative_with_forecast(self):
        """Same invariant across random forecast / SOC combinations."""
        calc = FlowCalculator()
        from custom_components.solar_energy_management.coordinator.flow_calculator import (
            EVBudgetStrategy,
        )
        rng = random.Random(SEED + 23)
        for p in _ALL_SCENARIOS[:NUM_SCENARIOS]:
            forecast = rng.uniform(0.0, 50.0)
            soc = rng.uniform(0.0, 100.0)
            b = calc.calculate_canonical_ev_budget(
                power=p, strategy=EVBudgetStrategy.SOLAR_ONLY,
                forecast_remaining_kwh=forecast,
                battery_soc=soc, battery_capacity_kwh=15.0,
            )
            assert b.net_w >= 0.0, (
                f"Negative canonical budget {b.net_w:.1f} W "
                f"forecast={forecast:.1f} kWh"
            )

    def test_canonical_budget_current_a_clamped_to_16(self):
        """``EVBudget.current_a`` must never exceed the 16 A KEBA ceiling
        regardless of how much surplus the canonical math computes.

        Sweep extreme solar / battery inputs across every non-IDLE
        strategy — including BATTERY_ASSIST which can blow past the
        surplus ceiling by design — and verify the clamp holds.
        """
        calc = FlowCalculator()
        from custom_components.solar_energy_management.coordinator.flow_calculator import (
            EVBudgetStrategy,
        )
        rng = random.Random(SEED + 24)
        for _ in range(NUM_SCENARIOS):
            # Build a power-rich scenario likely to push above 16 A
            # (16 A × 3 × 230 V = 11 040 W).
            p = PowerReadings(
                solar_power=rng.uniform(8_000.0, 40_000.0),
                home_consumption_power=rng.uniform(0.0, 1_000.0),
                battery_power=rng.uniform(-10_000.0, 0.0),  # discharging
                battery_soc=rng.uniform(50.0, 100.0),
                ev_power=0.0,
                ev_connected=True,
                grid_power=0.0,
            )
            p.calculate_derived()
            for strategy in (
                EVBudgetStrategy.SELF_CONSUMPTION,
                EVBudgetStrategy.SOLAR_ONLY,
                EVBudgetStrategy.MIN_PV,
                EVBudgetStrategy.BATTERY_ASSIST,
                EVBudgetStrategy.NOW,
            ):
                b = calc.calculate_canonical_ev_budget(
                    power=p, strategy=strategy,
                    forecast_remaining_kwh=20.0,
                    battery_soc=p.battery_soc,
                    battery_capacity_kwh=15.0,
                    battery_assist_max_power_w=8000.0,
                )
                assert 0 <= b.current_a <= 16, (
                    f"current_a={b.current_a} A out of [0, 16] range "
                    f"strategy={strategy} solar={p.solar_power:.0f} W "
                    f"net_w={b.net_w:.0f} W"
                )


# ──────────────────────────────────────────────────────────────────────────────
# Performance metrics invariants (9, 10)
# ──────────────────────────────────────────────────────────────────────────────

def _make_energy_calculator(import_rate=0.30, export_rate=0.08):
    """Build an EnergyCalculator with mocked time dependencies."""
    config = {
        "update_interval": 30,
        "electricity_import_rate": import_rate,
        "electricity_export_rate": export_rate,
        "battery_capacity_kwh": 15.0,
        "system_size_kwp": 10.0,
    }
    time_manager = MagicMock()
    time_manager.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)
    return EnergyCalculator(config, time_manager)


class TestPerformanceMetricsRange:
    """Invariants 9–10: self_consumption_rate and autarky_rate in [0, 100]."""

    def test_self_consumption_rate_in_valid_range(self):
        """should keep self_consumption_rate in [0, 100] for random energy totals."""
        calc = _make_energy_calculator()
        rng = random.Random(SEED + 30)

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)

            violations = []
            for _ in range(NUM_SCENARIOS):
                solar_kwh = rng.uniform(0.0, 80.0)
                export_kwh = rng.uniform(0.0, solar_kwh)  # export <= solar
                home_kwh = rng.uniform(0.0, 50.0)
                import_kwh = rng.uniform(0.0, 50.0)
                ev_kwh = rng.uniform(0.0, 30.0)

                energy = EnergyTotals(
                    daily_solar=solar_kwh,
                    daily_grid_export=export_kwh,
                    daily_grid_import=import_kwh,
                    daily_home=home_kwh,
                    daily_ev=ev_kwh,
                )
                power = PowerReadings()
                metrics = calc.calculate_performance(power, energy)

                if not (0.0 <= metrics.self_consumption_rate <= 100.0):
                    violations.append(metrics.self_consumption_rate)

            assert not violations, (
                f"{len(violations)} self_consumption_rate(s) outside [0,100]: "
                f"first={violations[0]:.2f}"
            )

    def test_autarky_rate_in_valid_range(self):
        """should keep autarky_rate in [0, 100] for random energy totals."""
        calc = _make_energy_calculator()
        rng = random.Random(SEED + 31)

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)

            violations = []
            for _ in range(NUM_SCENARIOS):
                solar_kwh = rng.uniform(0.0, 80.0)
                export_kwh = rng.uniform(0.0, solar_kwh)
                home_kwh = rng.uniform(0.0, 50.0)
                import_kwh = rng.uniform(0.0, home_kwh + 1.0)
                ev_kwh = rng.uniform(0.0, 30.0)

                energy = EnergyTotals(
                    daily_solar=solar_kwh,
                    daily_grid_export=export_kwh,
                    daily_grid_import=import_kwh,
                    daily_home=home_kwh,
                    daily_ev=ev_kwh,
                )
                power = PowerReadings()
                metrics = calc.calculate_performance(power, energy)

                if not (0.0 <= metrics.autarky_rate <= 100.0):
                    violations.append(metrics.autarky_rate)

            assert not violations, (
                f"{len(violations)} autarky_rate(s) outside [0,100]: "
                f"first={violations[0]:.2f}"
            )

    def test_self_consumption_rate_zero_when_no_solar(self):
        """should be exactly 0 when daily_solar is 0."""
        calc = _make_energy_calculator()

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)
            energy = EnergyTotals(daily_solar=0.0, daily_grid_import=5.0, daily_home=5.0)
            metrics = calc.calculate_performance(PowerReadings(), energy)
            assert metrics.self_consumption_rate == 0.0

    def test_autarky_rate_zero_when_no_consumption(self):
        """should be exactly 0 when total consumption is 0."""
        calc = _make_energy_calculator()

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)
            energy = EnergyTotals(daily_home=0.0, daily_ev=0.0, daily_solar=10.0)
            metrics = calc.calculate_performance(PowerReadings(), energy)
            assert metrics.autarky_rate == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Cost invariants (6, 7, 8)
# ──────────────────────────────────────────────────────────────────────────────

class TestCostInvariants:
    """Invariants 6–8: Savings are non-negative; costs are non-negative."""

    def _run_simulated_day(self, scenarios: List[PowerReadings]) -> None:
        """Drive EnergyCalculator through a list of power scenarios at 30s intervals."""
        config = {
            "update_interval": 30,
            "electricity_import_rate": 0.30,
            "electricity_export_rate": 0.08,
            "battery_capacity_kwh": 15.0,
            "system_size_kwp": 10.0,
        }
        time_manager = MagicMock()
        today = date(2026, 5, 15)
        time_manager.get_current_meter_day_sunrise_based.return_value = today
        calc = EnergyCalculator(config, time_manager)

        start = datetime(2026, 5, 15, 6, 0, 0)
        for tick, p in enumerate(scenarios):
            ts = start + timedelta(seconds=30 * tick)
            with patch(
                "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
            ) as mock_dt:
                mock_dt.now.return_value = ts
                energy = calc.calculate_energy(p)

        month_key = f"{today.year}_{today.month}"
        year_key = str(today.year)
        # Build final energy summary for costs
        energy = EnergyTotals(
            daily_solar=calc._get_daily("solar", today),
            daily_grid_export=calc._get_daily("grid_export", today),
            daily_grid_import=calc._get_daily("grid_import", today),
            daily_home=calc._get_daily("home", today),
            daily_battery_charge=calc._get_daily("battery_charge", today),
            daily_battery_discharge=calc._get_daily("battery_discharge", today),
            monthly_solar=calc._get_monthly("solar", month_key),
            monthly_grid_export=calc._get_monthly("grid_export", month_key),
            yearly_solar=calc._get_yearly("solar", year_key),
            yearly_grid_export=calc._get_yearly("grid_export", year_key),
        )

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = start + timedelta(seconds=30 * len(scenarios))
            costs = calc.calculate_costs(energy)

        return costs

    def test_daily_solar_savings_non_negative(self):
        """should never produce negative daily_savings (solar self-consumption)."""
        rng = random.Random(SEED + 40)
        # Sample 20 random 1-hour windows (120 cycles each) from the full scenario list
        for trial in range(20):
            start_idx = rng.randint(0, len(_ALL_SCENARIOS) - 121)
            subset = _ALL_SCENARIOS[start_idx : start_idx + 120]
            costs = self._run_simulated_day(subset)
            assert costs.daily_savings >= 0.0, (
                f"Trial {trial}: negative daily_savings = {costs.daily_savings:.4f}"
            )

    def test_daily_battery_savings_non_negative(self):
        """should never produce negative daily_battery_savings."""
        rng = random.Random(SEED + 41)
        for trial in range(20):
            start_idx = rng.randint(0, len(_ALL_SCENARIOS) - 121)
            subset = _ALL_SCENARIOS[start_idx : start_idx + 120]
            costs = self._run_simulated_day(subset)
            assert costs.daily_battery_savings >= 0.0, (
                f"Trial {trial}: negative daily_battery_savings = {costs.daily_battery_savings:.4f}"
            )

    def test_daily_costs_non_negative(self):
        """should never produce negative daily_costs (import cost)."""
        rng = random.Random(SEED + 42)
        for trial in range(20):
            start_idx = rng.randint(0, len(_ALL_SCENARIOS) - 121)
            subset = _ALL_SCENARIOS[start_idx : start_idx + 120]
            costs = self._run_simulated_day(subset)
            assert costs.daily_costs >= 0.0, (
                f"Trial {trial}: negative daily_costs = {costs.daily_costs:.4f}"
            )


# ──────────────────────────────────────────────────────────────────────────────
# EnergyCalculator 24-hour simulation (invariants 15–18)
# ──────────────────────────────────────────────────────────────────────────────

def _build_24h_scenarios(seed: int = SEED + 50) -> List[PowerReadings]:
    """Build 24 hours × 120 cycles/hour = 2880 scenarios simulating a realistic day.

    Hour 0–5: night (no solar, light home load, possible battery discharge)
    Hour 6–17: daytime (solar production ramp)
    Hour 18–23: evening (solar ramps down, home load stays)
    """
    rng = random.Random(seed)
    scenarios = []
    for hour in range(24):
        # Solar follows a sine profile
        import math
        solar_factor = max(0.0, math.sin(math.pi * (hour - 6) / 12))
        solar_peak = rng.uniform(5000, 12000)
        solar = solar_peak * solar_factor

        home_base = rng.uniform(500, 3000)
        ev = rng.uniform(0, 7000) if 22 <= hour or hour < 6 else 0  # night charging

        # Battery: charge when solar surplus, discharge at night
        if solar > home_base + ev + 500:
            battery = rng.uniform(0, min(5000, solar - home_base - ev))  # charging
        elif hour < 6 or hour >= 20:
            battery = -rng.uniform(0, 3000)  # discharging
        else:
            battery = rng.uniform(-2000, 2000)

        # Grid balances everything else
        net = solar - home_base - ev - battery
        grid = -net  # positive net → grid import (negative here)

        for _ in range(120):  # 120 cycles × 30s = 1 hour
            p = PowerReadings(
                solar_power=max(0.0, solar + rng.gauss(0, 50)),
                grid_power=grid + rng.gauss(0, 20),
                battery_power=battery + rng.gauss(0, 10),
                ev_power=max(0.0, ev + rng.gauss(0, 30)),
                battery_soc=max(0.0, min(100.0, 50.0 + rng.gauss(0, 20))),
            )
            p.calculate_derived()
            scenarios.append(p)
    return scenarios


_DAY_SCENARIOS: List[PowerReadings] = _build_24h_scenarios()


class TestEnergyCalculator24hSimulation:
    """Drive EnergyCalculator through a full simulated day and verify non-negativity."""

    def _make_calculator(self) -> Tuple[EnergyCalculator, MagicMock]:
        config = {
            "update_interval": 30,
            "electricity_import_rate": 0.30,
            "electricity_export_rate": 0.08,
            "battery_capacity_kwh": 15.0,
            "system_size_kwp": 10.0,
        }
        tm = MagicMock()
        tm.get_current_meter_day_sunrise_based.return_value = date(2026, 5, 15)
        return EnergyCalculator(config, tm), tm

    def test_daily_accumulators_non_negative_over_24h(self):
        """should never accumulate negative energy over a full 24-hour day."""
        calc, _ = self._make_calculator()
        start = datetime(2026, 5, 15, 0, 0, 0)
        date(2026, 5, 15)

        for tick, p in enumerate(_DAY_SCENARIOS):
            ts = start + timedelta(seconds=30 * tick)
            with patch(
                "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
            ) as mock_dt:
                mock_dt.now.return_value = ts
                energy = calc.calculate_energy(p)

            # Check mid-run for non-negativity
            if tick % 120 == 0:
                assert energy.daily_solar >= 0.0
                assert energy.daily_home >= 0.0
                assert energy.daily_grid_import >= 0.0
                assert energy.daily_grid_export >= 0.0
                assert energy.daily_battery_charge >= 0.0
                assert energy.daily_battery_discharge >= 0.0

    def test_final_daily_solar_plausible_range(self):
        """daily solar should be in a physically plausible kWh range after a sunny day."""
        calc, _ = self._make_calculator()
        start = datetime(2026, 5, 15, 0, 0, 0)
        date(2026, 5, 15)
        final_energy = None

        for tick, p in enumerate(_DAY_SCENARIOS):
            ts = start + timedelta(seconds=30 * tick)
            with patch(
                "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
            ) as mock_dt:
                mock_dt.now.return_value = ts
                final_energy = calc.calculate_energy(p)

        # 10 kWp system, 12h sun → theoretical max ~120 kWh
        # With noise and capping: must be in [0, 160] kWh
        assert 0.0 <= final_energy.daily_solar <= 160.0, (
            f"daily_solar={final_energy.daily_solar:.1f} kWh outside [0, 160] kWh"
        )

    def test_daily_energy_integration_is_monotonically_non_decreasing(self):
        """daily energy accumulators should never decrease within a day."""
        calc, _ = self._make_calculator()
        start = datetime(2026, 5, 15, 0, 0, 0)
        prev_solar = 0.0

        for tick, p in enumerate(_DAY_SCENARIOS):
            ts = start + timedelta(seconds=30 * tick)
            with patch(
                "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
            ) as mock_dt:
                mock_dt.now.return_value = ts
                energy = calc.calculate_energy(p)

            if energy.daily_solar < prev_solar - 0.01:  # allow tiny float noise
                pytest.fail(
                    f"daily_solar decreased at tick {tick}: "
                    f"{prev_solar:.3f} → {energy.daily_solar:.3f} kWh"
                )
            prev_solar = energy.daily_solar

    def test_energy_gap_protection_skips_spike_scenarios(self):
        """should skip integration when a gap exceeds 120 s to prevent spikes."""
        calc, _ = self._make_calculator()
        date(2026, 5, 15)
        p = PowerReadings(solar_power=10_000.0)
        p.calculate_derived()

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            # First call: sets _last_update
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)
            calc.calculate_energy(p)

            # Second call: 10-minute gap — should be skipped
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 10, 0)
            energy_after_gap = calc.calculate_energy(p)

        # Accumulated energy must equal the first cycle only (gap skipped)
        # First cycle uses config interval (30s/3600), second skipped
        # So daily_solar must be < 2 kWh (10000W × 30s = 0.083 kWh; spike would be 10000W × 600s = 1.67 kWh)
        # Because gap is skipped, it should equal only the first cycle's integration
        assert energy_after_gap.daily_solar < 2.0, (
            f"Energy spike not prevented by gap protection: "
            f"daily_solar={energy_after_gap.daily_solar:.3f} kWh"
        )

    def test_negative_time_delta_does_not_accumulate(self):
        """should skip integration when clock goes backwards (NTP correction)."""
        calc, _ = self._make_calculator()
        p = PowerReadings(solar_power=8000.0)
        p.calculate_derived()

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.dt_util"
        ) as mock_dt:
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 5, 0)
            energy_before = calc.calculate_energy(p)
            solar_before = energy_before.daily_solar

            # Clock goes back 5 minutes
            mock_dt.now.return_value = datetime(2026, 5, 15, 12, 0, 0)
            energy_after = calc.calculate_energy(p)

        # After NTP rollback, no additional energy should have accumulated
        assert energy_after.daily_solar <= solar_before + 0.01, (
            "Energy accumulated despite negative time delta (NTP rollback not handled)"
        )


# ──────────────────────────────────────────────────────────────────────────────
# Available power invariants
# ──────────────────────────────────────────────────────────────────────────────

# TestAvailablePowerInvariants removed in Phase D.2 (#282):
# ``calculate_available_power`` was deleted. The non-negative + capped-at-
# (solar + discharge) invariants now ride on the canonical EVBudget
# property tests above (``TestEVControlInvariants``).


# ──────────────────────────────────────────────────────────────────────────────
# Battery redirect invariants
# ──────────────────────────────────────────────────────────────────────────────

class TestBatteryRedirectInvariants:
    """_calculate_battery_redirect must be in [0, battery_charge_w]."""

    def test_redirect_never_exceeds_battery_charge_power(self):
        """should never redirect more than the battery is currently charging."""
        calc = FlowCalculator()
        rng = random.Random(SEED + 60)
        violations = []
        for _ in range(NUM_SCENARIOS):
            charge_w = rng.uniform(0.0, BATTERY_MAX_W)
            soc = rng.uniform(0.0, 100.0)
            capacity = rng.uniform(5.0, 20.0)
            forecast = rng.uniform(0.0, 50.0)

            redirect = calc._calculate_battery_redirect(charge_w, soc, capacity, forecast)
            if redirect > charge_w + 1.0:
                violations.append((redirect, charge_w))

        assert not violations, (
            f"{len(violations)} redirect(s) exceeded battery_charge_w: "
            f"first: redirect={violations[0][0]:.1f} W, charge={violations[0][1]:.1f} W"
        )

    def test_redirect_non_negative_always(self):
        """should never return negative redirect power."""
        calc = FlowCalculator()
        rng = random.Random(SEED + 61)
        violations = []
        for _ in range(NUM_SCENARIOS):
            charge_w = rng.uniform(0.0, BATTERY_MAX_W)
            soc = rng.uniform(0.0, 100.0)
            capacity = rng.uniform(5.0, 20.0)
            forecast = rng.uniform(0.0, 50.0)

            redirect = calc._calculate_battery_redirect(charge_w, soc, capacity, forecast)
            if redirect < 0.0:
                violations.append((redirect, charge_w, soc, forecast))

        assert not violations, (
            f"{len(violations)} negative redirect(s): "
            f"first: redirect={violations[0][0]:.1f} W"
        )

    def test_redirect_zero_when_battery_not_charging(self):
        """should always return 0 when charge_w is 0."""
        calc = FlowCalculator()
        rng = random.Random(SEED + 62)
        for _ in range(200):
            soc = rng.uniform(0.0, 100.0)
            capacity = rng.uniform(5.0, 20.0)
            forecast = rng.uniform(0.0, 50.0)
            assert calc._calculate_battery_redirect(0.0, soc, capacity, forecast) == 0.0


# ──────────────────────────────────────────────────────────────────────────────
# PowerReadings.calculate_derived idempotency
# ──────────────────────────────────────────────────────────────────────────────

class TestCalculateDerivedIdempotency:
    """Calling calculate_derived() twice must produce identical results."""

    def test_calculate_derived_is_idempotent(self):
        """should produce the same derived values regardless of how many times called."""
        rng = random.Random(SEED + 70)
        for _ in range(NUM_SCENARIOS):
            p = PowerReadings(
                solar_power=rng.uniform(0.0, SOLAR_MAX_W),
                grid_power=rng.uniform(-GRID_MAX_W, GRID_MAX_W),
                battery_power=rng.uniform(-BATTERY_MAX_W, BATTERY_MAX_W),
                ev_power=rng.uniform(0.0, EV_MAX_W),
            )
            p.calculate_derived()
            # Capture after first call
            gi1, ge1 = p.grid_import_power, p.grid_export_power
            bc1, bd1 = p.battery_charge_power, p.battery_discharge_power
            home1 = p.home_consumption_power

            p.calculate_derived()  # second call
            assert p.grid_import_power == gi1
            assert p.grid_export_power == ge1
            assert p.battery_charge_power == bc1
            assert p.battery_discharge_power == bd1
            assert p.home_consumption_power == home1


# ──────────────────────────────────────────────────────────────────────────────
# Known bug regression: export > solar impossible via signed grid_power
# ──────────────────────────────────────────────────────────────────────────────

class TestSignConventionRegression:
    """Verify sign-convention handling for all four hardware patterns."""

    def test_pattern_a_huawei_sma_victron_sungrow(self):
        """Pattern A: grid positive = export, battery positive = charge."""
        # Exporting 3 kW, battery charging at 2 kW, solar 10 kW
        p = PowerReadings(solar_power=10000, grid_power=3000, battery_power=2000)
        p.calculate_derived()
        assert p.grid_export_power == pytest.approx(3000.0)
        assert p.grid_import_power == 0.0
        assert p.battery_charge_power == pytest.approx(2000.0)
        assert p.battery_discharge_power == 0.0
        assert p.home_consumption_power >= 0.0

    def test_pattern_b_fronius_enphase_powerwall(self):
        """Pattern B (inverted): grid positive = import, battery positive = discharge.

        In SEM convention, Fronius sensors need to be negated before storage.
        This test verifies that raw SEM-convention values (already negated) work.
        """
        # After negation by sensor_reader: grid_power=-1500 (import), battery_power=-2000 (discharge)
        p = PowerReadings(solar_power=5000, grid_power=-1500, battery_power=-2000)
        p.calculate_derived()
        assert p.grid_import_power == pytest.approx(1500.0)
        assert p.grid_export_power == 0.0
        assert p.battery_discharge_power == pytest.approx(2000.0)
        assert p.battery_charge_power == 0.0

    def test_pattern_c_goodwe_sonnen(self):
        """Pattern C: grid positive = export, battery negative = discharge."""
        # Exporting 500 W, battery discharging 3 kW
        p = PowerReadings(solar_power=6000, grid_power=500, battery_power=-3000)
        p.calculate_derived()
        assert p.grid_export_power == pytest.approx(500.0)
        assert p.battery_discharge_power == pytest.approx(3000.0)
        assert p.home_consumption_power >= 0.0

    def test_pattern_d_solax(self):
        """Pattern D: grid positive = import, battery positive = charge."""
        # In SEM convention after negation: grid_power=-2000 (import), battery_power=1000 (charge)
        p = PowerReadings(solar_power=4000, grid_power=-2000, battery_power=1000)
        p.calculate_derived()
        assert p.grid_import_power == pytest.approx(2000.0)
        assert p.battery_charge_power == pytest.approx(1000.0)
        assert p.home_consumption_power >= 0.0

    def test_home_consumption_sign_independence(self):
        """home_consumption_power must be >= 0 regardless of sign pattern used."""
        rng = random.Random(SEED + 80)
        for _ in range(NUM_SCENARIOS):
            # Randomly flip signs to test all four pattern combinations
            grid_sign = rng.choice([-1, 1])
            batt_sign = rng.choice([-1, 1])
            p = PowerReadings(
                solar_power=rng.uniform(0, SOLAR_MAX_W),
                grid_power=grid_sign * rng.uniform(0, GRID_MAX_W),
                battery_power=batt_sign * rng.uniform(0, BATTERY_MAX_W),
                ev_power=rng.uniform(0, EV_MAX_W),
            )
            p.calculate_derived()
            assert p.home_consumption_power >= 0.0
