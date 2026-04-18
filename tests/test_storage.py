"""Tests for SEMStorage from coordinator/storage.py."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch, call

from custom_components.solar_energy_management.coordinator.storage import (
    SEMStorage,
    STORAGE_VERSION,
    ENERGY_SAVE_DELAY,
)


@pytest.fixture
def hass():
    """Return a mocked Home Assistant instance."""
    h = MagicMock()
    h.config = MagicMock()
    h.config.config_dir = "/config"
    h.states = MagicMock()
    h.services = MagicMock()
    h.data = {}
    h.bus = MagicMock()
    h.bus.async_listen_once = MagicMock()
    return h


@pytest.fixture
def mock_stores():
    """Create mock Store instances."""
    energy_store = MagicMock()
    energy_store.async_load = AsyncMock(return_value=None)
    energy_store.async_save = AsyncMock()
    energy_store.async_delay_save = MagicMock()

    daily_store = MagicMock()
    daily_store.async_load = AsyncMock(return_value=None)
    daily_store.async_save = AsyncMock()

    return energy_store, daily_store


@pytest.fixture
def storage(hass, mock_stores):
    """Create SEMStorage with mocked Store instances."""
    energy_store, daily_store = mock_stores
    with patch(
        "custom_components.solar_energy_management.coordinator.storage.Store"
    ) as MockStore:
        MockStore.side_effect = [energy_store, daily_store]
        s = SEMStorage(hass, "test_entry")
    # Replace internal stores with our mocks
    s._energy_store = energy_store
    s._daily_store = daily_store
    return s


# ──────────────────────────────────────────────
# Initialization
# ──────────────────────────────────────────────

def test_init(hass):
    """Test SEMStorage creates two Store instances with correct keys."""
    with patch(
        "custom_components.solar_energy_management.coordinator.storage.Store"
    ) as MockStore:
        storage = SEMStorage(hass, "my_entry")
        assert MockStore.call_count == 2
        calls = MockStore.call_args_list
        assert calls[0][0] == (hass, STORAGE_VERSION, "solar_energy_management_my_entry_energy")
        assert calls[1][0] == (hass, STORAGE_VERSION, "solar_energy_management_my_entry_daily")


def test_is_loaded_property(storage):
    """Test is_loaded is False before load, True after."""
    assert storage.is_loaded is False


@pytest.mark.asyncio
async def test_is_loaded_after_load(storage):
    """Test is_loaded is True after async_load."""
    await storage.async_load()
    assert storage.is_loaded is True


# ──────────────────────────────────────────────
# Loading
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_load_fresh(storage):
    """Test loading with no stored data uses defaults."""
    await storage.async_load()
    assert storage._energy_data == {
        "accumulators": {},
        "previous_values": {},
        "last_update": None,
    }
    assert storage._daily_data == {
        "baselines": {},
        "flow_accumulators": {},
        "daily_accumulators": {},
        "monthly_accumulators": {},
    }
    assert storage.is_loaded is True


@pytest.mark.asyncio
async def test_async_load_existing(storage):
    """Test loading stored data correctly."""
    energy_data = {
        "accumulators": {"solar": 150.0, "grid_import": 50.0},
        "previous_values": {"solar_power": 3000.0},
        "last_update": "2026-03-19T12:00:00",
    }
    daily_data = {
        "baselines": {"solar": 100.0},
        "flow_accumulators": {"solar_to_home": 80.0},
        "daily_accumulators": {"solar_daily": 10.0},
        "monthly_accumulators": {"solar_monthly": 300.0},
    }
    storage._energy_store.async_load = AsyncMock(return_value=energy_data)
    storage._daily_store.async_load = AsyncMock(return_value=daily_data)

    await storage.async_load()
    assert storage._energy_data == energy_data
    assert storage._daily_data == daily_data


@pytest.mark.asyncio
async def test_async_load_error(storage):
    """Test falls back to defaults on error."""
    storage._energy_store.async_load = AsyncMock(side_effect=Exception("Corrupt"))
    storage._daily_store.async_load = AsyncMock(side_effect=Exception("Corrupt"))

    await storage.async_load()
    assert storage._energy_data["accumulators"] == {}
    assert storage._daily_data["baselines"] == {}
    assert storage.is_loaded is True


# ──────────────────────────────────────────────
# Accumulator accessors
# ──────────────────────────────────────────────

def test_accumulator_get_set(storage):
    """Test set and get accumulator."""
    storage.set_accumulator("solar", 123.45)
    assert storage.get_accumulator("solar") == 123.45


def test_accumulator_get_default(storage):
    """Test get accumulator returns 0.0 for missing key."""
    assert storage.get_accumulator("nonexistent") == 0.0


def test_previous_value_get_set(storage):
    """Test set and get previous value."""
    storage.set_previous_value("solar_power", 3000.0)
    assert storage.get_previous_value("solar_power") == 3000.0


def test_previous_value_get_default(storage):
    """Test get previous value returns None for missing key."""
    assert storage.get_previous_value("nonexistent") is None


# ──────────────────────────────────────────────
# Daily data accessors
# ──────────────────────────────────────────────

def test_baseline_get_set(storage):
    """Test set and get baseline."""
    storage.set_baseline("solar", 100.0)
    assert storage.get_baseline("solar") == 100.0


def test_baseline_get_default(storage):
    """Test get baseline returns 0.0 for missing key."""
    assert storage.get_baseline("nonexistent") == 0.0


def test_flow_accumulator_get_set(storage):
    """Test set and get flow accumulator."""
    storage.set_flow_accumulator("solar_to_home", 55.5)
    assert storage.get_flow_accumulator("solar_to_home") == 55.5


def test_daily_accumulator_get_set(storage):
    """Test set and get daily accumulator."""
    storage.set_daily_accumulator("daily_solar", 12.3)
    assert storage.get_daily_accumulator("daily_solar") == 12.3


def test_monthly_accumulator_get_set(storage):
    """Test set and get monthly accumulator."""
    storage.set_monthly_accumulator("monthly_solar", 350.0)
    assert storage.get_monthly_accumulator("monthly_solar") == 350.0


# ──────────────────────────────────────────────
# Clear operations
# ──────────────────────────────────────────────

def test_clear_daily_accumulators(storage):
    """Test clearing daily and flow accumulators."""
    storage.set_daily_accumulator("solar_daily", 10.0)
    storage.set_flow_accumulator("solar_to_home", 8.0)
    storage.clear_daily_accumulators()
    assert storage.get_daily_accumulator("solar_daily") == 0.0
    assert storage.get_flow_accumulator("solar_to_home") == 0.0


def test_clear_monthly_accumulators(storage):
    """Test clearing monthly accumulators."""
    storage.set_monthly_accumulator("monthly_solar", 300.0)
    storage.clear_monthly_accumulators()
    assert storage.get_monthly_accumulator("monthly_solar") == 0.0


# ──────────────────────────────────────────────
# Save operations
# ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_async_save_daily(storage):
    """Test async_save_daily calls store.async_save."""
    storage.set_baseline("test", 42.0)
    await storage.async_save_daily()
    storage._daily_store.async_save.assert_called_once_with(storage._daily_data)


@pytest.mark.asyncio
async def test_async_save_energy_delayed(storage):
    """Test delayed save schedules via async_delay_save."""
    storage.set_accumulator("solar", 100.0)
    await storage.async_save_energy_delayed()
    storage._energy_store.async_delay_save.assert_called_once()
    # Verify the delay argument
    args = storage._energy_store.async_delay_save.call_args
    assert args[0][1] == ENERGY_SAVE_DELAY


@pytest.mark.asyncio
async def test_async_save_all(storage):
    """Test async_save_all saves both stores."""
    await storage.async_save_all()
    storage._energy_store.async_save.assert_called_once()
    storage._daily_store.async_save.assert_called_once()


# ──────────────────────────────────────────────
# State export/import
# ──────────────────────────────────────────────

def test_export_import_energy_calculator_state(storage):
    """Test round-trip state export and import."""
    storage.set_daily_accumulator("solar_daily", 10.5)
    storage.set_monthly_accumulator("solar_monthly", 300.0)
    storage._energy_data["last_update"] = "2026-03-19T12:00:00"

    exported = storage.export_energy_calculator_state()
    assert exported["daily_accumulators"]["solar_daily"] == 10.5
    assert exported["monthly_accumulators"]["solar_monthly"] == 300.0
    assert exported["last_update"] == "2026-03-19T12:00:00"

    # Clear and re-import
    storage.clear_daily_accumulators()
    storage.clear_monthly_accumulators()
    assert storage.get_daily_accumulator("solar_daily") == 0.0

    storage.import_energy_calculator_state(exported)
    assert storage.get_daily_accumulator("solar_daily") == 10.5
    assert storage.get_monthly_accumulator("solar_monthly") == 300.0


def test_import_partial_state(storage):
    """Test importing partial state only updates provided keys."""
    storage.set_daily_accumulator("existing", 5.0)
    storage.import_energy_calculator_state({"daily_accumulators": {"new_key": 99.0}})
    # The imported state replaces the daily_accumulators dict
    assert storage.get_daily_accumulator("new_key") == 99.0


# ──────────────────────────────────────────────
# Last update
# ──────────────────────────────────────────────

def test_get_last_update(storage):
    """Test parsing ISO datetime from last_update."""
    storage._energy_data["last_update"] = "2026-03-19T14:30:00"
    result = storage.get_last_update()
    assert isinstance(result, datetime)
    assert result.year == 2026
    assert result.month == 3
    assert result.day == 19
    assert result.hour == 14


def test_get_last_update_none(storage):
    """Test returns None when no last_update."""
    storage._energy_data["last_update"] = None
    assert storage.get_last_update() is None


def test_get_last_update_missing_key(storage):
    """Test returns None when last_update key missing."""
    storage._energy_data.pop("last_update", None)
    assert storage.get_last_update() is None


# ──────────────────────────────────────────────
# Storage validation (#37)
# ──────────────────────────────────────────────

def test_validate_energy_data_valid():
    """Valid energy data should pass validation."""
    data = {
        "accumulators": {"solar": 150.0, "grid_import": 50.0},
        "previous_values": {},
    }
    assert SEMStorage._validate_energy_data(data) is True


def test_validate_energy_data_empty_accumulators():
    """Empty accumulators should pass (fresh install)."""
    data = {"accumulators": {}}
    assert SEMStorage._validate_energy_data(data) is True


def test_validate_energy_data_exceeds_range():
    """Accumulator exceeding 100 MWh should fail."""
    data = {"accumulators": {"solar": 150_000.0}}
    assert SEMStorage._validate_energy_data(data) is False


def test_validate_energy_data_non_numeric():
    """Non-numeric accumulator values should fail."""
    data = {"accumulators": {"solar": "not_a_number"}}
    assert SEMStorage._validate_energy_data(data) is False


def test_validate_energy_data_not_dict():
    """Non-dict input should fail."""
    assert SEMStorage._validate_energy_data("invalid") is False
    assert SEMStorage._validate_energy_data(None) is False


def test_validate_energy_data_bad_accumulators_type():
    """Non-dict accumulators should fail."""
    data = {"accumulators": [1, 2, 3]}
    assert SEMStorage._validate_energy_data(data) is False


@pytest.mark.asyncio
async def test_async_load_rejects_corrupt_data(storage):
    """Loading corrupt energy data should reset to defaults."""
    corrupt_data = {
        "accumulators": {"solar": 999_999.0},  # exceeds 100 MWh
        "previous_values": {},
    }
    storage._energy_store.async_load = AsyncMock(return_value=corrupt_data)
    await storage.async_load()
    # Should have reset to defaults
    assert storage._energy_data["accumulators"] == {}
