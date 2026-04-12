"""Tests for autarky and self-consumption calculations."""
import pytest
from unittest.mock import Mock, patch


class TestAutarkyCalculations:
    """Test autarky and self-consumption rate calculations."""

    def test_autarky_full_self_sufficiency(self):
        """Test autarky when fully self-sufficient (100% autarky)."""
        # Scenario: All consumption covered by solar/battery, no grid import
        test_values = {
            "solar_power": 5000,  # 5kW solar
            "grid_power": -1000,  # Negative = exporting 1kW
            "battery_power": -500,  # Negative = discharging 500W
            "home_consumption": 3000,  # 3kW consumption
            "ev_power": 1500,  # 1.5kW EV charging
        }

        # Total consumption = 3000 + 1500 = 4500W
        # Grid import = 0 (grid_power is negative, so max(0, -1000) = 0)
        # Own generation used = 4500 - 0 = 4500W
        # Autarky = 4500/4500 = 100%

        total_consumption = test_values["home_consumption"] + test_values["ev_power"]
        grid_import = max(0, test_values["grid_power"])  # Positive = import
        own_generation = total_consumption - grid_import
        autarky_rate = round((own_generation / total_consumption) * 100, 2)

        assert autarky_rate == 100.0
        assert grid_import == 0

    def test_autarky_partial_grid_import(self):
        """Test autarky with partial grid import (50% autarky)."""
        # Scenario: Half consumption from grid, half from solar/battery
        test_values = {
            "solar_power": 1000,  # 1kW solar
            "grid_power": 2000,  # Positive = importing 2kW
            "battery_power": 0,  # No battery activity
            "home_consumption": 3000,  # 3kW consumption
            "ev_power": 1000,  # 1kW EV charging
        }

        # Total consumption = 3000 + 1000 = 4000W
        # Grid import = 2000W
        # Own generation used = 4000 - 2000 = 2000W
        # Autarky = 2000/4000 = 50%

        total_consumption = test_values["home_consumption"] + test_values["ev_power"]
        grid_import = max(0, test_values["grid_power"])  # Positive = import
        own_generation = total_consumption - grid_import
        autarky_rate = round((own_generation / total_consumption) * 100, 2)

        assert autarky_rate == 50.0
        assert grid_import == 2000

    def test_autarky_zero_self_sufficiency(self):
        """Test autarky when fully dependent on grid (0% autarky)."""
        # Scenario: All consumption from grid, no solar/battery
        test_values = {
            "solar_power": 0,  # No solar
            "grid_power": 5000,  # Importing 5kW
            "battery_power": 100,  # Charging battery (positive)
            "home_consumption": 4000,  # 4kW consumption
            "ev_power": 1000,  # 1kW EV charging
        }

        # Total consumption = 4000 + 1000 = 5000W
        # Grid import = 5000W
        # Own generation used = 5000 - 5000 = 0W
        # Autarky = 0/5000 = 0%

        total_consumption = test_values["home_consumption"] + test_values["ev_power"]
        grid_import = max(0, test_values["grid_power"])  # Positive = import
        own_generation = total_consumption - grid_import
        autarky_rate = round((own_generation / total_consumption) * 100, 2) if total_consumption > 0 else 0

        assert autarky_rate == 0.0
        assert grid_import == 5000

    def test_autarky_high_self_sufficiency(self):
        """Test autarky with high self-sufficiency (80% autarky)."""
        # Scenario: Most consumption from solar/battery, minimal grid
        test_values = {
            "solar_power": 3000,  # 3kW solar
            "grid_power": 1000,  # Importing 1kW
            "battery_power": -1000,  # Discharging 1kW
            "home_consumption": 4000,  # 4kW consumption
            "ev_power": 1000,  # 1kW EV charging
        }

        # Total consumption = 4000 + 1000 = 5000W
        # Grid import = 1000W
        # Own generation used = 5000 - 1000 = 4000W
        # Autarky = 4000/5000 = 80%

        total_consumption = test_values["home_consumption"] + test_values["ev_power"]
        grid_import = max(0, test_values["grid_power"])  # Positive = import
        own_generation = total_consumption - grid_import
        autarky_rate = round((own_generation / total_consumption) * 100, 2)

        assert autarky_rate == 80.0
        assert grid_import == 1000

    def test_autarky_zero_consumption(self):
        """Test autarky when there's no consumption."""
        # Edge case: No consumption
        test_values = {
            "solar_power": 1000,  # 1kW solar
            "grid_power": -1000,  # Exporting 1kW
            "battery_power": 0,
            "home_consumption": 0,
            "ev_power": 0,
        }

        total_consumption = test_values["home_consumption"] + test_values["ev_power"]

        if total_consumption > 0:
            grid_import = max(0, test_values["grid_power"])
            own_generation = total_consumption - grid_import
            autarky_rate = round((own_generation / total_consumption) * 100, 2)
        else:
            autarky_rate = 0  # Default when no consumption

        assert autarky_rate == 0
        assert total_consumption == 0

    def test_grid_convention_positive_import(self):
        """Test that positive grid power means import."""
        # Positive grid_power should mean importing from grid
        grid_power_positive = 1000  # Should mean importing
        grid_import = max(0, grid_power_positive)
        grid_export = max(0, -grid_power_positive)

        assert grid_import == 1000
        assert grid_export == 0

    def test_grid_convention_negative_export(self):
        """Test that negative grid power means export."""
        # Negative grid_power should mean exporting to grid
        grid_power_negative = -1500  # Should mean exporting
        grid_import = max(0, grid_power_negative)
        grid_export = max(0, -grid_power_negative)

        assert grid_import == 0
        assert grid_export == 1500

    def test_self_consumption_calculation(self):
        """Test self-consumption rate calculation."""
        # Self-consumption: How much solar is used locally vs exported
        daily_solar = 10.0  # 10 kWh solar produced
        daily_grid_export = 3.0  # 3 kWh exported

        if daily_solar > 0:
            self_consumed = daily_solar - daily_grid_export  # 7 kWh self-consumed
            self_consumption_rate = round((self_consumed / daily_solar) * 100, 2)
        else:
            self_consumption_rate = 0

        assert self_consumption_rate == 70.0  # 70% of solar was self-consumed

    def test_autarky_vs_self_consumption_difference(self):
        """Test that autarky and self-consumption are different metrics."""
        # Autarky: How much of consumption is covered by own generation
        # Self-consumption: How much of solar production is used locally

        # Example values
        solar_production = 10.0  # kWh
        grid_import = 5.0  # kWh
        grid_export = 3.0  # kWh
        total_consumption = 12.0  # kWh

        # Autarky calculation
        own_generation_used = total_consumption - grid_import  # 7 kWh from own sources
        autarky = round((own_generation_used / total_consumption) * 100, 2)

        # Self-consumption calculation
        self_consumed = solar_production - grid_export  # 7 kWh of solar used locally
        self_consumption = round((self_consumed / solar_production) * 100, 2)

        assert autarky == 58.33  # 58.33% of consumption from own generation
        assert self_consumption == 70.0  # 70% of solar production used locally
        assert autarky != self_consumption  # Different metrics!