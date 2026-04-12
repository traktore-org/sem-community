"""Tests for PVPerformanceAnalyzer PV performance monitoring."""
import pytest
from unittest.mock import MagicMock
from datetime import datetime, date

from custom_components.solar_energy_management.analytics.pv_performance import (
    PVPerformanceAnalyzer,
    PVPerformanceData,
    MonthlyPerformance,
)


class TestPVPerformanceInit:
    """Test PVPerformanceAnalyzer initialization."""

    def test_init_defaults(self, hass):
        analyzer = PVPerformanceAnalyzer(hass)
        assert analyzer.system_size_kwp == 10.0
        assert analyzer.inverter_max_power_w == 10000.0
        assert analyzer.system_install_date is None
        assert analyzer._monthly_history == []
        assert analyzer._daily_peak_power == 0.0
        assert analyzer._clipping_minutes == 0
        data = analyzer.performance_data
        assert data.estimated_annual_degradation == 0.0
        assert data.degradation_trend == "unknown"

    def test_init_custom_values(self, hass):
        analyzer = PVPerformanceAnalyzer(
            hass,
            system_size_kwp=15.0,
            inverter_max_power_w=12000.0,
            system_install_date="2020-06-15",
        )
        assert analyzer.system_size_kwp == 15.0
        assert analyzer.inverter_max_power_w == 12000.0
        assert analyzer.system_install_date == "2020-06-15"


class TestPVPerformanceUpdate:
    """Test PVPerformanceAnalyzer.update() method."""

    def test_update_specific_yield(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        data = analyzer.update(daily_solar_kwh=50.0, monthly_solar_kwh=0.0, current_solar_power_w=0.0)
        assert data.daily_specific_yield == pytest.approx(5.0)  # 50 / 10

    def test_update_monthly_specific_yield(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        data = analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=300.0, current_solar_power_w=0.0)
        assert data.monthly_specific_yield == pytest.approx(30.0)  # 300 / 10

    def test_update_performance_vs_forecast(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        data = analyzer.update(
            daily_solar_kwh=40.0,
            monthly_solar_kwh=0.0,
            current_solar_power_w=0.0,
            forecast_today_kwh=50.0,
        )
        assert data.performance_vs_forecast == pytest.approx(80.0)  # (40/50)*100

    def test_update_no_forecast(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        data = analyzer.update(
            daily_solar_kwh=40.0,
            monthly_solar_kwh=0.0,
            current_solar_power_w=0.0,
            forecast_today_kwh=0.0,
        )
        assert data.performance_vs_forecast == 0.0

    def test_update_clipping_detection(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0, inverter_max_power_w=10000.0)
        # Power at 96% of inverter max triggers clipping (>= 95%)
        data = analyzer.update(
            daily_solar_kwh=0.0,
            monthly_solar_kwh=0.0,
            current_solar_power_w=9600.0,
        )
        assert analyzer._clipping_minutes == 1
        assert data.clipping_losses_kwh > 0.0

    def test_update_no_clipping_below_threshold(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0, inverter_max_power_w=10000.0)
        # Power at 90% of inverter max -- below 95% threshold
        data = analyzer.update(
            daily_solar_kwh=0.0,
            monthly_solar_kwh=0.0,
            current_solar_power_w=9000.0,
        )
        assert analyzer._clipping_minutes == 0
        assert data.clipping_losses_kwh == 0.0

    def test_update_system_age(self, hass):
        analyzer = PVPerformanceAnalyzer(
            hass, system_install_date="2020-01-01"
        )
        data = analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=0.0)
        # System should be several years old
        assert data.system_age_years > 5.0

    def test_update_system_age_invalid_date(self, hass):
        analyzer = PVPerformanceAnalyzer(
            hass, system_install_date="not-a-date"
        )
        data = analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=0.0)
        assert data.system_age_years == 0.0

    def test_update_peak_power_tracking(self, hass):
        analyzer = PVPerformanceAnalyzer(hass)
        analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=5000.0)
        assert analyzer._daily_peak_power == 5000.0
        analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=3000.0)
        assert analyzer._daily_peak_power == 5000.0  # Should not decrease
        analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=7000.0)
        assert analyzer._daily_peak_power == 7000.0


class TestPVDegradation:
    """Test degradation analysis."""

    def _fill_monthly_history(self, analyzer, months_data):
        """Helper to populate monthly history."""
        for year, month, kwh in months_data:
            analyzer.record_monthly(year, month, kwh, forecast_kwh=kwh)

    def test_update_degradation_normal(self, hass):
        """< 1% degradation = normal."""
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        # Create 14 months with very small degradation (~0.5%)
        months = []
        for m in range(1, 13):
            months.append((2024, m, 100.0))
        # Year 2 same month with ~0.5% less
        months.append((2025, 1, 99.5))
        for year, month, kwh in months:
            analyzer.record_monthly(year, month, kwh)
        data = analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=0.0)
        assert data.degradation_trend == "normal"

    def test_update_degradation_warning(self, hass):
        """1-2% degradation = warning."""
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        months = []
        for m in range(1, 13):
            months.append((2024, m, 100.0))
        # Year 2: 1.5% less
        months.append((2025, 1, 98.5))
        for year, month, kwh in months:
            analyzer.record_monthly(year, month, kwh)
        data = analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=0.0)
        assert data.degradation_trend == "warning"

    def test_update_degradation_critical(self, hass):
        """> 2% degradation = critical."""
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        months = []
        for m in range(1, 13):
            months.append((2024, m, 100.0))
        # Year 2: 3% less
        months.append((2025, 1, 97.0))
        for year, month, kwh in months:
            analyzer.record_monthly(year, month, kwh)
        data = analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=0.0)
        assert data.degradation_trend == "critical"

    def test_estimate_degradation_insufficient_data(self, hass):
        analyzer = PVPerformanceAnalyzer(hass)
        # Only 5 months of data
        for m in range(1, 6):
            analyzer.record_monthly(2024, m, 100.0)
        assert analyzer._estimate_degradation() == 0.0

    def test_estimate_degradation_year_over_year(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        # 13 months with known degradation
        for m in range(1, 13):
            analyzer.record_monthly(2024, m, 100.0)
        analyzer.record_monthly(2025, 1, 95.0)  # 5% degradation in Jan
        deg = analyzer._estimate_degradation()
        assert deg > 0  # Should detect degradation
        assert deg <= 5.0  # Clamped to max 5%


class TestPVRecordMonthly:
    """Test monthly recording and history."""

    def test_record_monthly(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        analyzer.record_monthly(2024, 6, 300.0, forecast_kwh=320.0)
        assert len(analyzer._monthly_history) == 1
        record = analyzer._monthly_history[0]
        assert record.year == 2024
        assert record.month == 6
        assert record.total_kwh == 300.0
        assert record.specific_yield == pytest.approx(30.0)
        assert record.performance_ratio == pytest.approx((300.0 / 320.0) * 100)

    def test_record_monthly_max_36(self, hass):
        analyzer = PVPerformanceAnalyzer(hass)
        for i in range(40):
            analyzer.record_monthly(2020 + i // 12, (i % 12) + 1, 100.0)
        assert len(analyzer._monthly_history) == 36

    def test_get_monthly_history(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, system_size_kwp=10.0)
        analyzer.record_monthly(2024, 3, 250.0, forecast_kwh=260.0)
        history = analyzer.get_monthly_history()
        assert len(history) == 1
        entry = history[0]
        assert "year" in entry
        assert "month" in entry
        assert "kwh" in entry
        assert "specific_yield" in entry
        assert "performance_ratio" in entry
        assert entry["year"] == 2024
        assert entry["month"] == 3
        assert entry["kwh"] == 250.0


class TestPVResetDaily:
    """Test daily reset."""

    def test_reset_daily(self, hass):
        analyzer = PVPerformanceAnalyzer(hass, inverter_max_power_w=10000.0)
        # Trigger clipping and peak tracking
        analyzer.update(daily_solar_kwh=0.0, monthly_solar_kwh=0.0, current_solar_power_w=9600.0)
        assert analyzer._daily_peak_power > 0
        assert analyzer._clipping_minutes > 0
        analyzer.reset_daily()
        assert analyzer._daily_peak_power == 0.0
        assert analyzer._clipping_minutes == 0


class TestPVPerformanceDataSerialization:
    """Test PVPerformanceData.to_dict()."""

    def test_performance_data_to_dict(self):
        data = PVPerformanceData(
            daily_specific_yield=4.5,
            monthly_specific_yield=120.0,
            annual_specific_yield=1100.0,
            performance_vs_forecast=95.5,
            daily_performance_ratio=95.5,
            estimated_annual_degradation=0.8,
            degradation_trend="normal",
            clipping_losses_kwh=0.5,
            curtailment_kwh=0.0,
        )
        d = data.to_dict()
        assert d["pv_daily_specific_yield"] == 4.5
        assert d["pv_monthly_specific_yield"] == 120.0
        assert d["pv_annual_specific_yield"] == 1100.0
        assert d["pv_performance_vs_forecast"] == 95.5
        assert d["pv_daily_performance_ratio"] == 95.5
        assert d["pv_estimated_annual_degradation"] == 0.8
        assert d["pv_degradation_trend"] == "normal"
        assert d["pv_clipping_losses_kwh"] == 0.5
        assert d["pv_curtailment_kwh"] == 0.0
