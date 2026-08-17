"""Tests for SEMStorage from coordinator/storage.py."""
import pytest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.coordinator.storage import (
    SEMStorage,
    STORAGE_VERSION,
    ENERGY_SAVE_DELAY,
    DAILY_SAVE_INTERVAL,
)


@pytest.fixture
def mock_hass():
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
def storage(mock_hass, mock_stores):
    """Create SEMStorage with mocked Store instances."""
    energy_store, daily_store = mock_stores
    with patch(
        "custom_components.solar_energy_management.coordinator.storage.Store"
    ) as MockStore:
        MockStore.side_effect = [energy_store, daily_store]
        s = SEMStorage(mock_hass, "test_entry")
    # Replace internal stores with our mocks
    s._energy_store = energy_store
    s._daily_store = daily_store
    return s


# ──────────────────────────────────────────────
# Initialization
# ──────────────────────────────────────────────

def test_init(mock_hass):
    """Test SEMStorage creates two Store instances with correct keys."""
    with patch(
        "custom_components.solar_energy_management.coordinator.storage.Store"
    ) as MockStore:
        storage = SEMStorage(mock_hass, "my_entry")
        assert MockStore.call_count == 2
        calls = MockStore.call_args_list
        assert calls[0][0] == (mock_hass, STORAGE_VERSION, "solar_energy_management_my_entry_energy")
        assert calls[1][0] == (mock_hass, STORAGE_VERSION, "solar_energy_management_my_entry_daily")


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
    storage._energy_store.async_load = AsyncMock(side_effect=OSError("Corrupt"))
    storage._daily_store.async_load = AsyncMock(side_effect=OSError("Corrupt"))

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
async def test_async_save_daily_throttled(storage):
    """Daily state gets a real mid-run disk write, throttled to one per
    interval (so an unclean reboot loses ≤ one interval, not the day)."""
    storage.set_device_runtime("pump", 1800.0, "2026-07-06")
    # first call writes immediately (last-save ts starts at 0)
    await storage.async_save_daily_throttled()
    storage._daily_store.async_save.assert_called_once_with(storage._daily_data)
    # an immediate second call is throttled out — still just one write
    await storage.async_save_daily_throttled()
    storage._daily_store.async_save.assert_called_once()
    # after the interval elapses it writes again
    storage._last_daily_save_ts -= (DAILY_SAVE_INTERVAL + 1)
    await storage.async_save_daily_throttled()
    assert storage._daily_store.async_save.call_count == 2


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
    """(#563) An out-of-range accumulator is dropped, the rest kept.

    The old all-or-nothing behavior wiped every daily/monthly/cost
    accumulator because ONE pre-#551 inflated lifetime counter tripped
    the 100 MWh cap on the upgrade restart."""
    data = {"accumulators": {"solar": 150_000.0, "home": 12.5}}
    assert SEMStorage._validate_energy_data(data) is True
    assert "solar" not in data["accumulators"]
    assert data["accumulators"]["home"] == 12.5


def test_validate_energy_data_non_numeric():
    """(#563) A non-numeric accumulator is dropped, the rest kept."""
    data = {"accumulators": {"solar": "not_a_number", "home": 3.2}}
    assert SEMStorage._validate_energy_data(data) is True
    assert "solar" not in data["accumulators"]
    assert data["accumulators"]["home"] == 3.2


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
    """(#563) A bad entry is dropped on load; the healthy rest survives."""
    corrupt_data = {
        "accumulators": {"solar": 999_999.0},  # exceeds 100 MWh
        "daily_accumulators": {"solar_2026-07-04": 26.5},
        "previous_values": {},
    }
    storage._energy_store.async_load = AsyncMock(return_value=corrupt_data)
    await storage.async_load()
    # Bad entry dropped, good data KEPT (no whole-store wipe)
    assert storage._energy_data["accumulators"] == {}
    assert storage._energy_data["daily_accumulators"] == {"solar_2026-07-04": 26.5}


@pytest.mark.asyncio
async def test_async_load_563_inflated_lifetime_keeps_dailies(storage):
    """(#563) Regression: the exact ebnerjoh scenario, REAL store layout.

    The calculator's accumulators live in the DAILY store. A pre-#551
    store holding ×1000-inflated lifetime counters (>100 MWh) must NOT
    take the day's dailies, monthlies and cost accumulators with it."""
    daily_store = {
        "baselines": {},
        "flow_accumulators": {},
        "daily_accumulators": {"solar_2026-07-04": 38.2, "grid_export_2026-07-04": 20.1},
        "monthly_accumulators": {"solar_2026-07": 150.0},
        "yearly_accumulators": {"solar_2026": 150.0},
        "lifetime_accumulators": {
            "lifetime_solar": 3_200_000.0,       # Wh read as kWh — inflated
            "lifetime_grid_import": 640_000.0,   # inflated
            "lifetime_home": 55.0,               # sane
        },
        "daily_cost_accumulators": {"cost_2026-07-04": 1.31},
    }
    storage._daily_store.async_load = AsyncMock(return_value=daily_store)
    await storage.async_load()
    # Round-trip through the calculator-facing export
    d = storage.export_energy_calculator_state()
    assert d["daily_accumulators"]["solar_2026-07-04"] == 38.2
    assert d["monthly_accumulators"]["solar_2026-07"] == 150.0
    assert d["daily_cost_accumulators"]["cost_2026-07-04"] == 1.31
    # Only the inflated lifetime entries are gone (re-seeded from hw later)
    assert "lifetime_solar" not in d["lifetime_accumulators"]
    assert "lifetime_grid_import" not in d["lifetime_accumulators"]
    assert d["lifetime_accumulators"]["lifetime_home"] == 55.0


def test_validate_daily_data_structural_corruption():
    """A non-dict accumulator container still starts the store fresh."""
    assert SEMStorage._validate_daily_data("garbage") is False
    assert SEMStorage._validate_daily_data({"daily_accumulators": [1, 2]}) is False


def test_validate_daily_data_negative_daily_clamped():
    data = {"daily_accumulators": {"solar_2026-07-04": -3.5}}
    assert SEMStorage._validate_daily_data(data) is True
    assert data["daily_accumulators"]["solar_2026-07-04"] == 0.0
