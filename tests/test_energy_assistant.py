"""Tests for EnergyAssistant smart recommendations."""
import pytest
from unittest.mock import MagicMock, patch
from datetime import date, timedelta

from custom_components.solar_energy_management.analytics.energy_assistant import (
    EnergyAssistant,
    EnergyAssistantData,
    EnergyTip,
)


class TestEnergyAssistantInit:
    """Test EnergyAssistant initialization."""

    def test_init(self, hass):
        ea = EnergyAssistant(hass)
        assert ea._tips == []
        assert ea._tip_rotation_index == 0
        assert ea._last_analysis is None
        assert ea._daily_stats == []
        data = ea.assistant_data
        assert data.optimization_score == 0
        assert data.current_tip is None
        assert data.tips_count == 0


class TestEnergyAssistantAnalyze:
    """Test EnergyAssistant.analyze() method."""

    def test_analyze_basic(self, hass):
        ea = EnergyAssistant(hass)
        data = ea.analyze(
            daily_solar_kwh=20.0,
            daily_home_kwh=10.0,
            daily_grid_import_kwh=3.0,
            daily_grid_export_kwh=2.0,
            self_consumption_rate=70.0,
            autarky_rate=60.0,
        )
        assert isinstance(data, EnergyAssistantData)
        assert 0 <= data.optimization_score <= 100

    def test_ev_charging_low_solar_tip(self, hass):
        """solar < 50% of EV -> generates tip."""
        ea = EnergyAssistant(hass)
        data = ea.analyze(
            daily_ev_kwh=10.0,
            solar_to_ev_kwh=3.0,  # 30% solar
            grid_to_ev_kwh=7.0,
            daily_solar_kwh=20.0,
        )
        tips = ea.get_all_tips()
        ev_tips = [t for t in tips if t["category"] == "ev"]
        assert len(ev_tips) >= 1
        assert any("grid" in t["description"].lower() for t in ev_tips)

    def test_ev_charging_good_forecast_tip(self, hass):
        """forecast > 2x EV need -> generates tip."""
        ea = EnergyAssistant(hass)
        data = ea.analyze(
            daily_ev_kwh=5.0,
            solar_to_ev_kwh=1.0,
            grid_to_ev_kwh=4.0,
            forecast_remaining_kwh=15.0,  # > 2 * 5 = 10
            daily_solar_kwh=10.0,
        )
        tips = ea.get_all_tips()
        ev_tips = [t for t in tips if t["category"] == "ev"]
        assert any("solar" in t["description"].lower() or "forecast" in t["description"].lower() for t in ev_tips)

    def test_surplus_high_export_no_hot_water(self, hass):
        """export > 50% -> hot water tip when no hot water."""
        ea = EnergyAssistant(hass)
        ea.analyze(
            daily_solar_kwh=20.0,
            daily_grid_export_kwh=12.0,  # 60% export
            has_hot_water=False,
        )
        tips = ea.get_all_tips()
        surplus_tips = [t for t in tips if t["category"] == "surplus"]
        assert any("hot water" in t["description"].lower() for t in surplus_tips)

    def test_surplus_high_export_no_heat_pump(self, hass):
        """export > 60% -> heat pump tip when no heat pump."""
        ea = EnergyAssistant(hass)
        ea.analyze(
            daily_solar_kwh=20.0,
            daily_grid_export_kwh=14.0,  # 70% export
            has_heat_pump=False,
        )
        tips = ea.get_all_tips()
        surplus_tips = [t for t in tips if t["category"] == "surplus"]
        assert any("heat pump" in t["description"].lower() for t in surplus_tips)

    def test_self_consumption_excellent(self, hass):
        """> 80% -> positive tip."""
        ea = EnergyAssistant(hass)
        ea.analyze(
            self_consumption_rate=85.0,
            daily_solar_kwh=20.0,
        )
        tips = ea.get_all_tips()
        general_tips = [t for t in tips if t["category"] == "general"]
        assert any("excellent" in t["title"].lower() or "well optimized" in t["description"].lower() for t in general_tips)

    def test_self_consumption_low(self, hass):
        """< 40% with solar > 5kWh -> improvement tip."""
        ea = EnergyAssistant(hass)
        ea.analyze(
            self_consumption_rate=30.0,
            daily_solar_kwh=10.0,
            daily_grid_export_kwh=3.0,
        )
        tips = ea.get_all_tips()
        general_tips = [t for t in tips if t["category"] == "general"]
        assert any("low" in t["title"].lower() or "shifting" in t["description"].lower() for t in general_tips)

    def test_price_cheap_tip(self, hass):
        ea = EnergyAssistant(hass)
        ea.analyze(current_price_level="cheap")
        tips = ea.get_all_tips()
        price_tips = [t for t in tips if t["category"] == "price"]
        assert len(price_tips) >= 1
        assert any("cheap" in t["description"].lower() for t in price_tips)

    def test_price_expensive_tip(self, hass):
        ea = EnergyAssistant(hass)
        ea.analyze(current_price_level="expensive")
        tips = ea.get_all_tips()
        price_tips = [t for t in tips if t["category"] == "price"]
        assert len(price_tips) >= 1
        assert any("expensive" in t["description"].lower() for t in price_tips)

    def test_battery_underutilized_tip(self, hass):
        """discharge < grid_import/2."""
        ea = EnergyAssistant(hass)
        ea.analyze(
            daily_battery_charge_kwh=5.0,
            daily_battery_discharge_kwh=2.0,
            daily_grid_import_kwh=10.0,  # grid > discharge * 2
        )
        tips = ea.get_all_tips()
        general_tips = [t for t in tips if t["category"] == "general"]
        assert any("battery" in t["description"].lower() for t in general_tips)


class TestOptimizationScore:
    """Test optimization score calculation."""

    def test_optimization_score_perfect(self, hass):
        ea = EnergyAssistant(hass)
        data = ea.analyze(
            self_consumption_rate=100.0,
            autarky_rate=100.0,
            daily_ev_kwh=10.0,
            solar_to_ev_kwh=10.0,  # 100% solar EV
            daily_solar_kwh=50.0,
            daily_grid_export_kwh=0.0,
        )
        assert data.optimization_score == 100

    def test_optimization_score_zero(self, hass):
        ea = EnergyAssistant(hass)
        data = ea.analyze(
            self_consumption_rate=0.0,
            autarky_rate=0.0,
            daily_ev_kwh=10.0,
            solar_to_ev_kwh=0.0,
            daily_solar_kwh=10.0,
            daily_grid_export_kwh=10.0,  # 100% export
        )
        assert data.optimization_score == 0

    def test_optimization_score_no_ev(self, hass):
        """No EV gives 10 bonus points."""
        ea = EnergyAssistant(hass)
        data = ea.analyze(
            self_consumption_rate=0.0,
            autarky_rate=0.0,
            daily_ev_kwh=0.0,
            daily_solar_kwh=10.0,
            daily_grid_export_kwh=10.0,
        )
        # With 0 self_consumption and 0 autarky but no EV, gets 10 points for EV
        assert data.optimization_score >= 10


class TestTipRotation:
    """Test tip rotation and sorting."""

    def test_tip_rotation(self, hass):
        """Multiple calls rotate through tips."""
        ea = EnergyAssistant(hass)
        # First call generates tips
        data1 = ea.analyze(
            daily_ev_kwh=10.0,
            solar_to_ev_kwh=2.0,
            grid_to_ev_kwh=8.0,
            self_consumption_rate=30.0,
            daily_solar_kwh=10.0,
            daily_grid_export_kwh=3.0,
        )
        tip1 = data1.current_tip
        # Second call should potentially rotate
        data2 = ea.analyze(
            daily_ev_kwh=10.0,
            solar_to_ev_kwh=2.0,
            grid_to_ev_kwh=8.0,
            self_consumption_rate=30.0,
            daily_solar_kwh=10.0,
            daily_grid_export_kwh=3.0,
        )
        # With multiple tips, rotation index increments
        assert ea._tip_rotation_index >= 2

    def test_get_all_tips_sorted(self, hass):
        ea = EnergyAssistant(hass)
        ea.analyze(
            daily_ev_kwh=10.0,
            solar_to_ev_kwh=2.0,
            grid_to_ev_kwh=8.0,
            self_consumption_rate=30.0,
            daily_solar_kwh=10.0,
            daily_grid_export_kwh=3.0,
            current_price_level="expensive",
        )
        tips = ea.get_all_tips()
        # Verify sorted by priority (ascending)
        priorities = [t["priority"] for t in tips]
        assert priorities == sorted(priorities)


class TestDailyStatsTrend:
    """Test daily stats and trend detection."""

    def test_daily_stats_trend_rising(self, hass):
        ea = EnergyAssistant(hass)
        # Simulate multiple days with rising self_consumption
        for i in range(7):
            day = date.today() - timedelta(days=6 - i)
            with patch("custom_components.solar_energy_management.analytics.energy_assistant.date") as mock_date:
                mock_date.today.return_value = day
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                ea._record_daily_stats(
                    solar=10, home=5, ev=2,
                    grid_import=i * 3 + 1,  # Rising
                    grid_export=1,
                    self_consumption=50 + i * 5,
                    autarky=50,
                )
        trend = ea._get_trend("grid_import")
        assert trend == "rising"

    def test_daily_stats_trend_falling(self, hass):
        ea = EnergyAssistant(hass)
        for i in range(7):
            day = date.today() - timedelta(days=6 - i)
            with patch("custom_components.solar_energy_management.analytics.energy_assistant.date") as mock_date:
                mock_date.today.return_value = day
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                ea._record_daily_stats(
                    solar=10, home=5, ev=2,
                    grid_import=20 - i * 3,  # Falling
                    grid_export=1,
                    self_consumption=50,
                    autarky=50,
                )
        trend = ea._get_trend("grid_import")
        assert trend == "falling"

    def test_daily_stats_trend_stable(self, hass):
        ea = EnergyAssistant(hass)
        for i in range(7):
            day = date.today() - timedelta(days=6 - i)
            with patch("custom_components.solar_energy_management.analytics.energy_assistant.date") as mock_date:
                mock_date.today.return_value = day
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                ea._record_daily_stats(
                    solar=10, home=5, ev=2,
                    grid_import=10,  # Constant
                    grid_export=1,
                    self_consumption=50,
                    autarky=50,
                )
        trend = ea._get_trend("grid_import")
        assert trend == "stable"

    def test_daily_stats_max_30_days(self, hass):
        ea = EnergyAssistant(hass)
        for i in range(35):
            day = date.today() - timedelta(days=34 - i)
            with patch("custom_components.solar_energy_management.analytics.energy_assistant.date") as mock_date:
                mock_date.today.return_value = day
                mock_date.side_effect = lambda *a, **kw: date(*a, **kw)
                ea._record_daily_stats(
                    solar=10, home=5, ev=2,
                    grid_import=10, grid_export=1,
                    self_consumption=50, autarky=50,
                )
        assert len(ea._daily_stats) <= 30


class TestEnergyAssistantDataSerialization:
    """Test EnergyAssistantData.to_dict()."""

    def test_energy_assistant_data_to_dict(self):
        data = EnergyAssistantData(
            optimization_score=75,
            current_tip="Test tip",
            tip_category="general",
            tips_count=3,
            self_consumption_trend="rising",
            grid_dependency_trend="falling",
            ev_solar_percentage=65.432,
        )
        d = data.to_dict()
        assert d["energy_optimization_score"] == 75
        assert d["energy_tip"] == "Test tip"
        assert d["energy_tip_category"] == "general"
        assert d["energy_tips_count"] == 3
        assert d["energy_self_consumption_trend"] == "rising"
        assert d["energy_grid_dependency_trend"] == "falling"
        assert d["energy_ev_solar_percentage"] == 65.4

    def test_energy_assistant_data_to_dict_no_tip(self):
        data = EnergyAssistantData()
        d = data.to_dict()
        assert d["energy_tip"] == "No recommendations at this time"
        assert d["energy_tip_category"] == "none"
