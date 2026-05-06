"""Tests for ROI calculation with dynamic tariff support.

Tests the hybrid ROI approach:
- Past (pre-SEM): lifetime_kWh × 7-day avg rate
- Future (with SEM): accumulated daily_savings at real rates
"""
import pytest
from collections import deque
from datetime import date, timedelta
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
    EnergyTotals,
    CostData,
)


def _make_calculator(config_overrides=None):
    """Create an EnergyCalculator with default test config."""
    config = {
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
        "system_investment_cost": 10000,
        "update_interval": 10,
    }
    if config_overrides:
        config.update(config_overrides)

    time_manager = MagicMock()
    time_manager.get_current_meter_day_sunrise_based.return_value = date.today()
    calc = EnergyCalculator(config, time_manager)
    return calc


def _make_energy(daily_solar=10, daily_home=8, daily_ev=0,
                 daily_grid_import=3, daily_grid_export=5,
                 daily_battery_discharge=2,
                 monthly_solar=300, monthly_home=240, monthly_grid_import=90,
                 monthly_grid_export=150,
                 yearly_solar=3600, yearly_home=2900, yearly_ev=0,
                 yearly_grid_import=1100, yearly_grid_export=1800,
                 yearly_battery_discharge=700):
    """Create an EnergyTotals with test values."""
    e = EnergyTotals()
    e.daily_solar = daily_solar
    e.daily_home = daily_home
    e.daily_ev = daily_ev
    e.daily_grid_import = daily_grid_import
    e.daily_grid_export = daily_grid_export
    e.daily_battery_discharge = daily_battery_discharge
    e.monthly_solar = monthly_solar
    e.monthly_home = monthly_home
    e.monthly_grid_import = monthly_grid_import
    e.monthly_grid_export = monthly_grid_export
    e.yearly_solar = yearly_solar
    e.yearly_home = yearly_home
    e.yearly_ev = yearly_ev
    e.yearly_grid_import = yearly_grid_import
    e.yearly_grid_export = yearly_grid_export
    e.yearly_battery_discharge = yearly_battery_discharge
    return e


# ════════════════════════════════════════════
# Static tariff ROI
# ════════════════════════════════════════════

class TestStaticTariffROI:
    """ROI calculations with static (fixed) tariff rates."""

    def test_static_lifetime_savings(self):
        """Static rate: lifetime self-consumed × rate + export × export_rate."""
        calc = _make_calculator()
        # Set lifetime kWh
        calc._lifetime_accumulators = {
            "lifetime_solar": 5000.0,
            "lifetime_grid_import": 2000.0,
            "lifetime_grid_export": 1500.0,
            "lifetime_battery_discharge": 800.0,
        }

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # self_consumed = 5000 - 1500 = 3500 kWh
        # savings = 3500 × 0.30 = 1050
        # export_revenue = 1500 × 0.08 = 120
        # total = 1170
        assert costs.lifetime_total_savings == 1170.0

    def test_static_roi_percentage(self):
        """System cost 10,000, savings 5,000 → 50% ROI."""
        calc = _make_calculator({"system_investment_cost": 10000})
        calc._lifetime_accumulators = {
            "lifetime_solar": 20000.0,
            "lifetime_grid_import": 5000.0,
            "lifetime_grid_export": 5000.0,
            "lifetime_battery_discharge": 0.0,
        }
        calc._install_year_decimal = 2024.0

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # self_consumed = 20000 - 5000 = 15000
        # savings = 15000 × 0.30 = 4500
        # export = 5000 × 0.08 = 400
        # total = 4900
        assert costs.roi_percentage == 49.0

    def test_static_payback_years(self):
        """Annual savings determine payback period."""
        calc = _make_calculator({"system_investment_cost": 12000})
        calc._lifetime_accumulators = {
            "lifetime_solar": 10000.0,
            "lifetime_grid_import": 3000.0,
            "lifetime_grid_export": 2000.0,
            "lifetime_battery_discharge": 0.0,
        }
        calc._install_year_decimal = 2025.0

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        assert costs.roi_payback_years > 0
        assert costs.roi_annual_savings > 0

    def test_static_unchanged_by_accumulation(self):
        """With no rate history, static ROI uses current rate (same result)."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 5000.0,
            "lifetime_grid_import": 2000.0,
            "lifetime_grid_export": 1500.0,
            "lifetime_battery_discharge": 0.0,
        }

        energy = _make_energy()
        costs1 = calc.calculate_costs(energy)

        # Accumulate some savings (simulating a few days)
        calc._accumulated_savings = 50.0
        calc._accumulated_export_revenue = 10.0
        calc._accumulated_self_consumed_kwh = 200.0
        calc._accumulated_export_kwh = 100.0
        calc._accumulated_grid_import_kwh = 50.0

        costs2 = calc.calculate_costs(energy)

        # Should be approximately the same (small rounding differences ok)
        assert abs(costs1.lifetime_total_savings - costs2.lifetime_total_savings) < 1


# ════════════════════════════════════════════
# Dynamic tariff ROI
# ════════════════════════════════════════════

class TestDynamicTariffROI:
    """ROI calculations with dynamic (varying) tariff rates."""

    def test_dynamic_uses_7day_avg_not_current(self):
        """7-day avg rate used for pre-SEM portion, not current spot price."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 5000.0,
            "lifetime_grid_import": 2000.0,
            "lifetime_grid_export": 1500.0,
            "lifetime_battery_discharge": 0.0,
        }

        # 7-day history with avg ~0.25
        for i in range(7):
            calc._rate_history.append({
                "date": str(date.today() - timedelta(days=i)),
                "import_rate": 0.25,
                "export_rate": 0.06,
            })

        # Current rate is very different (spot price at 3am)
        calc._import_rate = 0.05
        calc._export_rate = 0.02

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # Should use avg 0.25, not current 0.05
        # self_consumed = 3500, pre_sem = 3500 (no accumulation)
        # savings ≈ 3500 × 0.25 = 875, not 3500 × 0.05 = 175
        assert costs.lifetime_total_savings > 800

    def test_dynamic_roi_stable_across_price_swings(self):
        """ROI stays stable when current price swings but avg is steady."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 5000.0,
            "lifetime_grid_import": 2000.0,
            "lifetime_grid_export": 1500.0,
            "lifetime_battery_discharge": 0.0,
        }

        for i in range(7):
            calc._rate_history.append({
                "date": str(date.today() - timedelta(days=i)),
                "import_rate": 0.30,
                "export_rate": 0.08,
            })

        energy = _make_energy()

        # Low spot price
        calc._import_rate = 0.05
        costs_low = calc.calculate_costs(energy)

        # High spot price
        calc._import_rate = 0.45
        costs_high = calc.calculate_costs(energy)

        # Both should use 7-day avg (0.30), so savings should be similar
        assert abs(costs_low.lifetime_total_savings - costs_high.lifetime_total_savings) < 1

    def test_dynamic_accumulated_savings_grow(self):
        """Accumulated savings increase over simulated days."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 1000.0,
            "lifetime_grid_import": 500.0,
            "lifetime_grid_export": 200.0,
            "lifetime_battery_discharge": 0.0,
        }

        # Simulate 7 days of accumulation
        for day in range(7):
            calc._accumulated_savings += 5.0  # 5 CHF/day
            calc._accumulated_export_revenue += 1.0
            calc._accumulated_self_consumed_kwh += 20.0
            calc._accumulated_export_kwh += 5.0
            calc._accumulated_grid_import_kwh += 10.0

        assert calc._accumulated_savings == 35.0
        assert calc._accumulated_export_revenue == 7.0

    def test_dynamic_hybrid_past_plus_accumulated(self):
        """Hybrid: 800kWh × avg rate (past) + 200kWh accumulated at real rates."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 1000.0,
            "lifetime_grid_import": 300.0,
            "lifetime_grid_export": 200.0,
            "lifetime_battery_discharge": 0.0,
        }

        # Accumulated portion (200kWh self-consumed at actual rates)
        calc._accumulated_savings = 60.0  # 200kWh × 0.30
        calc._accumulated_export_revenue = 4.0  # 50kWh × 0.08
        calc._accumulated_self_consumed_kwh = 200.0
        calc._accumulated_export_kwh = 50.0
        calc._accumulated_grid_import_kwh = 100.0

        # 7-day avg rate
        for i in range(7):
            calc._rate_history.append({
                "date": str(date.today() - timedelta(days=i)),
                "import_rate": 0.30,
                "export_rate": 0.08,
            })

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # Pre-SEM: self_consumed=800-200=600, export=200-50=150
        # Est past savings = 600 × 0.30 = 180, est past revenue = 150 × 0.08 = 12
        # Accumulated: 60 + 4 = 64
        # Total ≈ 180 + 12 + 64 = 256
        assert 250 < costs.lifetime_total_savings < 260


# ════════════════════════════════════════════
# Rate history
# ════════════════════════════════════════════

class TestRateHistory:
    """Test rate history tracking and 7-day averaging."""

    def test_rate_history_appends_daily(self):
        """Snapshot adds entry to rate history."""
        calc = _make_calculator()
        yesterday = date.today() - timedelta(days=1)
        calc._daily_accumulators = {
            f"solar_{yesterday}": 10.0,
            f"home_{yesterday}": 8.0,
            f"grid_import_{yesterday}": 3.0,
            f"grid_export_{yesterday}": 5.0,
        }

        calc._snapshot_daily_costs(yesterday)

        assert len(calc._rate_history) == 1
        assert calc._rate_history[0]["date"] == str(yesterday)
        assert calc._rate_history[0]["import_rate"] == 0.30

    def test_rate_history_max_30_days(self):
        """Rate history deque caps at 30 entries."""
        calc = _make_calculator()

        for i in range(35):
            calc._rate_history.append({
                "date": str(date.today() - timedelta(days=i)),
                "import_rate": 0.25 + i * 0.001,
                "export_rate": 0.08,
            })

        assert len(calc._rate_history) == 30

    def test_7day_average_calculation(self):
        """7 days of varying rates → correct average."""
        calc = _make_calculator()
        rates = [0.20, 0.22, 0.25, 0.30, 0.35, 0.28, 0.24]

        for i, rate in enumerate(rates):
            calc._rate_history.append({
                "date": str(date.today() - timedelta(days=6 - i)),
                "import_rate": rate,
                "export_rate": 0.08,
            })

        avg = calc._get_avg_import_rate()
        expected = sum(rates) / 7
        assert abs(avg - expected) < 0.001

    def test_7day_avg_fallback_to_current(self):
        """Empty history → returns current rate."""
        calc = _make_calculator()
        calc._import_rate = 0.35

        assert calc._get_avg_import_rate() == 0.35

    def test_rate_history_persisted(self):
        """get_state() includes history, restore_state() recovers it."""
        calc = _make_calculator()
        calc._rate_history.append({
            "date": "2026-05-05",
            "import_rate": 0.28,
            "export_rate": 0.07,
        })
        calc._accumulated_savings = 150.0
        calc._accumulated_cost = 80.0

        state = calc.get_state()
        assert len(state["rate_history"]) == 1
        assert state["accumulated_savings"] == 150.0

        # Restore into fresh calculator
        calc2 = _make_calculator()
        calc2.restore_state(state)

        assert len(calc2._rate_history) == 1
        assert calc2._rate_history[0]["import_rate"] == 0.28
        assert calc2._accumulated_savings == 150.0
        assert calc2._accumulated_cost == 80.0


# ════════════════════════════════════════════
# Accumulated savings
# ════════════════════════════════════════════

class TestAccumulatedSavings:
    """Test daily cost accumulation at midnight."""

    def test_daily_savings_accumulated_at_midnight(self):
        """Daily savings added to running total when day rolls over."""
        calc = _make_calculator()
        yesterday = date.today() - timedelta(days=1)

        calc._daily_accumulators = {
            f"solar_{yesterday}": 15.0,
            f"home_{yesterday}": 10.0,
            f"grid_import_{yesterday}": 4.0,
            f"grid_export_{yesterday}": 6.0,
        }

        calc._snapshot_daily_costs(yesterday)

        # savings = (10 - 4) × 0.30 = 1.80
        assert abs(calc._accumulated_savings - 1.80) < 0.01
        # export revenue = 6 × 0.08 = 0.48
        assert abs(calc._accumulated_export_revenue - 0.48) < 0.01

    def test_accumulated_kwh_tracked(self):
        """Grid import, self-consumed, export kWh accumulated."""
        calc = _make_calculator()
        yesterday = date.today() - timedelta(days=1)

        calc._daily_accumulators = {
            f"solar_{yesterday}": 20.0,
            f"home_{yesterday}": 12.0,
            f"grid_import_{yesterday}": 5.0,
            f"grid_export_{yesterday}": 8.0,
        }

        calc._snapshot_daily_costs(yesterday)

        assert calc._accumulated_grid_import_kwh == 5.0
        assert calc._accumulated_export_kwh == 8.0
        assert calc._accumulated_self_consumed_kwh == 12.0  # 20 - 8

    def test_accumulation_survives_restart(self):
        """Save state, restore, verify totals preserved."""
        calc = _make_calculator()
        calc._accumulated_savings = 500.0
        calc._accumulated_cost = 200.0
        calc._accumulated_export_revenue = 50.0
        calc._accumulated_grid_import_kwh = 700.0
        calc._accumulated_self_consumed_kwh = 3000.0
        calc._accumulated_export_kwh = 800.0

        state = calc.get_state()

        calc2 = _make_calculator()
        calc2.restore_state(state)

        assert calc2._accumulated_savings == 500.0
        assert calc2._accumulated_cost == 200.0
        assert calc2._accumulated_export_revenue == 50.0
        assert calc2._accumulated_grid_import_kwh == 700.0
        assert calc2._accumulated_self_consumed_kwh == 3000.0
        assert calc2._accumulated_export_kwh == 800.0

    def test_fresh_install_zero_accumulation(self):
        """No prior state → accumulated = 0, falls back to lifetime × avg rate."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 5000.0,
            "lifetime_grid_import": 2000.0,
            "lifetime_grid_export": 1500.0,
            "lifetime_battery_discharge": 0.0,
        }

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # No accumulation → all goes through avg rate (= current rate, no history)
        # self_consumed = 3500, savings = 3500 × 0.30 = 1050
        # export_revenue = 1500 × 0.08 = 120
        assert costs.lifetime_total_savings == 1170.0


# ════════════════════════════════════════════
# Energy balance
# ════════════════════════════════════════════

class TestEnergyBalance:
    """Verify no double-counting between accumulated and estimated portions."""

    def test_accumulated_plus_estimated_equals_total(self):
        """Accumulated + estimated ≈ what old method would compute."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 5000.0,
            "lifetime_grid_import": 2000.0,
            "lifetime_grid_export": 1500.0,
            "lifetime_battery_discharge": 0.0,
        }

        # Accumulate half the lifetime
        calc._accumulated_savings = 525.0    # 1750 × 0.30
        calc._accumulated_export_revenue = 60.0  # 750 × 0.08
        calc._accumulated_self_consumed_kwh = 1750.0
        calc._accumulated_export_kwh = 750.0
        calc._accumulated_grid_import_kwh = 1000.0

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # Old method: 3500 × 0.30 + 1500 × 0.08 = 1050 + 120 = 1170
        # New hybrid should be approximately the same (same rate)
        assert abs(costs.lifetime_total_savings - 1170.0) < 1

    def test_no_negative_estimated_past(self):
        """If accumulated > lifetime (counter reset), estimated past = 0."""
        calc = _make_calculator()
        calc._lifetime_accumulators = {
            "lifetime_solar": 1000.0,
            "lifetime_grid_import": 500.0,
            "lifetime_grid_export": 300.0,
            "lifetime_battery_discharge": 0.0,
        }

        # Accumulated more than lifetime (e.g. energy counter was reset)
        calc._accumulated_self_consumed_kwh = 2000.0
        calc._accumulated_export_kwh = 1000.0
        calc._accumulated_grid_import_kwh = 800.0
        calc._accumulated_savings = 600.0
        calc._accumulated_export_revenue = 80.0

        energy = _make_energy()
        costs = calc.calculate_costs(energy)

        # Pre-SEM portions should be max(0, ...) = 0
        # Total = just accumulated: 600 + 80 = 680
        assert costs.lifetime_total_savings == 680.0
