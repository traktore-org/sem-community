"""Tests for yearly sensor seeding from HA recorder statistics."""
import pytest
from datetime import datetime
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
)


@pytest.fixture
def config():
    """Minimal config for EnergyCalculator."""
    return {
        "electricity_import_rate": 0.30,
        "electricity_export_rate": 0.08,
    }


@pytest.fixture
def time_manager():
    return MagicMock()


@pytest.fixture
def calculator(config, time_manager):
    return EnergyCalculator(config, time_manager)


@pytest.fixture
def ed_config():
    """Mock Energy Dashboard config with all energy sensors."""
    cfg = MagicMock()
    cfg.solar_energy = "sensor.solar_total"
    cfg.grid_import_energy = "sensor.grid_import_total"
    cfg.grid_export_energy = "sensor.grid_export_total"
    cfg.battery_charge_energy = "sensor.batt_charge_total"
    cfg.battery_discharge_energy = "sensor.batt_discharge_total"
    cfg.device_consumption = [
        {"stat_consumption": "sensor.keba_total_energy"}
    ]
    return cfg


def _make_stats(entity_id, first_sum, last_sum):
    """Build a minimal stats response for one entity."""
    return {
        entity_id: [
            {"start": "2026-01-01T00:00:00", "sum": first_sum},
            {"start": "2026-04-15T12:00:00", "sum": last_sum},
        ]
    }


def _make_full_stats(solar=500, grid_import=300, grid_export=200,
                     batt_charge=150, batt_discharge=120, ev=80):
    """Build complete stats response for all energy entities."""
    return {
        "sensor.solar_total": [
            {"start": "2026-01-01T00:00:00", "sum": 1000},
            {"start": "2026-04-15T12:00:00", "sum": 1000 + solar},
        ],
        "sensor.grid_import_total": [
            {"start": "2026-01-01T00:00:00", "sum": 500},
            {"start": "2026-04-15T12:00:00", "sum": 500 + grid_import},
        ],
        "sensor.grid_export_total": [
            {"start": "2026-01-01T00:00:00", "sum": 200},
            {"start": "2026-04-15T12:00:00", "sum": 200 + grid_export},
        ],
        "sensor.batt_charge_total": [
            {"start": "2026-01-01T00:00:00", "sum": 100},
            {"start": "2026-04-15T12:00:00", "sum": 100 + batt_charge},
        ],
        "sensor.batt_discharge_total": [
            {"start": "2026-01-01T00:00:00", "sum": 80},
            {"start": "2026-04-15T12:00:00", "sum": 80 + batt_discharge},
        ],
        "sensor.keba_total_energy": [
            {"start": "2026-01-01T00:00:00", "sum": 50},
            {"start": "2026-04-15T12:00:00", "sum": 50 + ev},
        ],
    }


@pytest.mark.unit
class TestYearlySeeding:
    """Test yearly accumulator seeding from recorder statistics."""

    @pytest.mark.asyncio
    async def test_seed_from_statistics_success(self, calculator, ed_config):
        """Successful seeding populates all yearly accumulators."""
        hass = MagicMock()
        stats = _make_full_stats(solar=500, grid_import=300, grid_export=200,
                                 batt_charge=150, batt_discharge=120, ev=80)

        with patch(
            "custom_components.solar_energy_management.coordinator.energy_calculator.statistics_during_period",
            new_callable=AsyncMock,
            return_value=stats,
        ):
            # Patch the import inside the method
            with patch.dict("sys.modules", {
                "homeassistant.components.recorder.statistics": MagicMock(
                    statistics_during_period=AsyncMock(return_value=stats)
                )
            }):
                await calculator.seed_yearly_from_statistics(hass, ed_config)

        assert calculator._yearly_seeded is True
        year = str(datetime.now().year)
        assert calculator._yearly_accumulators.get(f"solar_{year}") == 500
        assert calculator._yearly_accumulators.get(f"grid_import_{year}") == 300
        assert calculator._yearly_accumulators.get(f"grid_export_{year}") == 200
        assert calculator._yearly_accumulators.get(f"battery_charge_{year}") == 150
        assert calculator._yearly_accumulators.get(f"battery_discharge_{year}") == 120
        # home = max(0, 500 + 300 + 120 - 200 - 150) = 570
        assert calculator._yearly_accumulators.get(f"home_{year}") == 570
        assert calculator._yearly_accumulators.get(f"ev_{year}") == 80

    @pytest.mark.asyncio
    async def test_skip_when_already_seeded(self, calculator, ed_config):
        """Should return immediately when _yearly_seeded is True."""
        calculator._yearly_seeded = True
        hass = MagicMock()
        await calculator.seed_yearly_from_statistics(hass, ed_config)
        # No accumulators modified
        assert calculator._yearly_accumulators == {}

    @pytest.mark.asyncio
    async def test_skip_when_no_ed_config(self, calculator):
        """Should return when ed_config is None."""
        hass = MagicMock()
        await calculator.seed_yearly_from_statistics(hass, None)
        assert calculator._yearly_seeded is False

    @pytest.mark.asyncio
    async def test_skip_when_existing_data(self, calculator, ed_config):
        """Should set flag and skip if accumulators already have >10 kWh."""
        year = str(datetime.now().year)
        calculator._yearly_accumulators[f"solar_{year}"] = 50.0
        hass = MagicMock()
        await calculator.seed_yearly_from_statistics(hass, ed_config)
        assert calculator._yearly_seeded is True
        # Value unchanged (not overwritten)
        assert calculator._yearly_accumulators[f"solar_{year}"] == 50.0

    @pytest.mark.asyncio
    async def test_handles_missing_recorder(self, calculator, ed_config):
        """Should handle ImportError gracefully when recorder unavailable."""
        hass = MagicMock()
        with patch.dict("sys.modules", {
            "homeassistant.components.recorder.statistics": None,
            "homeassistant.components.recorder": None,
        }):
            await calculator.seed_yearly_from_statistics(hass, ed_config)
        assert calculator._yearly_seeded is False

    @pytest.mark.asyncio
    async def test_derived_home_calculation(self, calculator, ed_config):
        """Home should be max(0, solar + import + discharge - export - charge)."""
        hass = MagicMock()
        # solar=100, import=50, discharge=30, export=200, charge=100
        # home = max(0, 100+50+30-200-100) = max(0, -120) = 0
        stats = _make_full_stats(solar=100, grid_import=50, grid_export=200,
                                 batt_charge=100, batt_discharge=30, ev=0)

        with patch.dict("sys.modules", {
            "homeassistant.components.recorder.statistics": MagicMock(
                statistics_during_period=AsyncMock(return_value=stats)
            )
        }):
            await calculator.seed_yearly_from_statistics(hass, ed_config)

        year = str(datetime.now().year)
        assert calculator._yearly_accumulators.get(f"home_{year}") == 0

    @pytest.mark.asyncio
    async def test_state_persistence_roundtrip(self, calculator, config, time_manager):
        """get_state/restore_state should preserve yearly_seeded flag."""
        calculator._yearly_seeded = True
        calculator._yearly_accumulators = {"solar_2026": 500.0}
        state = calculator.get_state()
        assert state["yearly_seeded"] is True

        new_calc = EnergyCalculator(config, time_manager)
        assert new_calc._yearly_seeded is False
        new_calc.restore_state(state)
        assert new_calc._yearly_seeded is True
        assert new_calc._yearly_accumulators == {"solar_2026": 500.0}
