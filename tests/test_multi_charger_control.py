"""Multi-charger control tests for SEM v1.4 (#112).

Tests the multi-EV charger architecture:
- Config migration: flat ev_* keys → ev_chargers list
- Hardware detection: discover_all returns multiple chargers
- Registration: N chargers registered in surplus controller
- Surplus distribution: priority-based with minimum threshold
- Session tracking: per-charger isolation
- Backward compatibility: single-charger works identically
"""
import pytest
from unittest.mock import MagicMock, AsyncMock, patch
from datetime import datetime

from custom_components.solar_energy_management.coordinator.types import (
    SessionData,
    SEMData,
)
from custom_components.solar_energy_management.coordinator.surplus_controller import (
    SurplusController,
)
from custom_components.solar_energy_management.consts.sensors import SEM_SENSORS
from custom_components.solar_energy_management.hardware_detection import (
    _discover_wallbox,
    _discover_keba,
)


# ============================================================
# Mock fixtures for multi-charger scenarios
# ============================================================

def make_mock_charger(charger_id: str, name: str, priority: int = 3,
                      power: float = 0, connected: bool = True,
                      phases: int = 3, max_current: float = 32):
    """Create a mock CurrentControlDevice for testing."""
    device = MagicMock()
    device.device_id = charger_id
    device.name = name
    device.priority = priority
    device.min_current = 6.0
    device.max_current = max_current
    device.phases = phases
    device.voltage = 230.0
    device.min_power_threshold = phases * 230 * 6  # 4140W (3-phase) or 1380W (1-phase)
    device.managed_externally = True
    device._session_active = False
    device._current_setpoint = 0
    device.start_session = AsyncMock()
    device.stop_session = AsyncMock()
    device._set_current = AsyncMock()
    device.watts_to_current = lambda w: w / (phases * 230)
    return device


def make_mock_entity_registry_entry(entity_id: str, platform: str,
                                     device_class=None, device_id=None):
    """Create a mock entity registry entry."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.platform = platform
    entry.original_device_class = device_class
    entry.device_id = device_id or f"device_{platform}"
    entry.disabled_by = None
    return entry


# ============================================================
# Scenario mocks: real-world multi-charger setups
# ============================================================

SCENARIO_DUAL_WALLBOX = {
    "name": "Dual Wallbox Pulsar (Rien's setup from #112)",
    "chargers": [
        {
            "id": "ev_charger_0",
            "name": "Wallbox Links",
            "ev_connected_sensor": "sensor.wallbox_1_status",
            "ev_charging_sensor": "sensor.wallbox_1_status",
            "ev_charging_power_sensor": "sensor.wallbox_1_power",
            "ev_charger_service": "wallbox.set_charging_current",
            "ev_charger_service_entity_id": "sensor.wallbox_1_status",
            "ev_surplus_priority": 3,
            "ev_phases": 3,
            "max_charging_current": 32,
        },
        {
            "id": "ev_charger_1",
            "name": "Wallbox Rechts",
            "ev_connected_sensor": "sensor.wallbox_2_status",
            "ev_charging_sensor": "sensor.wallbox_2_status",
            "ev_charging_power_sensor": "sensor.wallbox_2_power",
            "ev_charger_service": "wallbox.set_charging_current",
            "ev_charger_service_entity_id": "sensor.wallbox_2_status",
            "ev_surplus_priority": 5,
            "ev_phases": 3,
            "max_charging_current": 32,
        },
    ],
}

SCENARIO_KEBA_PLUS_EASEE = {
    "name": "KEBA P30 (garage) + Easee (driveway)",
    "chargers": [
        {
            "id": "ev_charger_0",
            "name": "KEBA Garage",
            "ev_connected_sensor": "binary_sensor.keba_p30_plug",
            "ev_charging_sensor": "binary_sensor.keba_p30_charging_state",
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
            "ev_charger_service": "keba.set_current",
            "ev_charger_service_entity_id": "binary_sensor.keba_p30_plug",
            "ev_service_param_name": "current",
            "ev_surplus_priority": 3,
            "ev_phases": 3,
            "max_charging_current": 16,
        },
        {
            "id": "ev_charger_1",
            "name": "Easee Driveway",
            "ev_connected_sensor": "sensor.easee_status",
            "ev_charging_sensor": "sensor.easee_status",
            "ev_charging_power_sensor": "sensor.easee_power",
            "ev_charger_service": "easee.set_charger_dynamic_limit",
            "ev_charger_service_entity_id": "sensor.easee_status",
            "ev_service_param_name": "current",
            "ev_surplus_priority": 5,
            "ev_phases": 3,
            "max_charging_current": 32,
        },
    ],
}

SCENARIO_SINGLE_KEBA_MIGRATED = {
    "name": "Single KEBA P30 (migrated from flat config)",
    "flat_config": {
        "ev_connected_sensor": "binary_sensor.keba_p30_plug",
        "ev_charging_sensor": "binary_sensor.keba_p30_charging_state",
        "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        "ev_charger_service": "keba.set_current",
        "ev_charger_service_entity_id": "binary_sensor.keba_p30_plug",
        "ev_service_param_name": "current",
        "ev_surplus_priority": 3,
    },
}


# ============================================================
# Tests: Config migration
# ============================================================

class TestConfigMigration:
    """Test v2 → v3 config migration (flat ev_* → ev_chargers list)."""

    def test_migration_wraps_flat_keys(self):
        """Flat ev_* keys should be wrapped into ev_chargers[0]."""
        flat = SCENARIO_SINGLE_KEBA_MIGRATED["flat_config"].copy()
        assert "ev_chargers" not in flat

        # Simulate migration logic
        charger_0 = {"id": "ev_charger", "name": "EV Charger"}
        ev_keys = [k for k in flat if k.startswith("ev_")]
        for k in ev_keys:
            charger_0[k] = flat[k]

        result = [charger_0]

        assert len(result) == 1
        assert result[0]["id"] == "ev_charger"
        assert result[0]["ev_charging_power_sensor"] == "sensor.keba_p30_charging_power"
        assert result[0]["ev_charger_service"] == "keba.set_current"

    def test_migration_is_idempotent(self):
        """If ev_chargers already exists, migration should not re-wrap."""
        config = {
            "ev_chargers": SCENARIO_DUAL_WALLBOX["chargers"],
            "ev_charging_power_sensor": "sensor.wallbox_1_power",
        }
        # Migration check: ev_chargers exists → skip
        assert "ev_chargers" in config
        assert len(config["ev_chargers"]) == 2

    def test_migration_preserves_all_keys(self):
        """All charger-specific keys should be preserved in migration."""
        flat = SCENARIO_SINGLE_KEBA_MIGRATED["flat_config"].copy()
        charger_0 = {"id": "ev_charger", "name": "EV Charger"}
        for k in flat:
            if k.startswith("ev_"):
                charger_0[k] = flat[k]

        assert charger_0["ev_service_param_name"] == "current"
        assert charger_0["ev_surplus_priority"] == 3


# ============================================================
# Tests: Hardware detection (multi-charger)
# ============================================================

class TestMultiChargerDetection:
    """Test discover_all_ev_chargers_from_registry returns all chargers."""

    def test_detects_two_wallbox_chargers(self):
        """Two Wallbox Pulsars should produce two results."""
        # Device 1 entities
        entities_1 = [
            make_mock_entity_registry_entry(
                "sensor.wallbox_1_status", "wallbox", device_id="wb_001"),
            make_mock_entity_registry_entry(
                "sensor.wallbox_1_power", "wallbox", device_class="power", device_id="wb_001"),
        ]

        # Device 2 entities
        entities_2 = [
            make_mock_entity_registry_entry(
                "sensor.wallbox_2_status", "wallbox", device_id="wb_002"),
            make_mock_entity_registry_entry(
                "sensor.wallbox_2_power", "wallbox", device_class="power", device_id="wb_002"),
        ]

        result_1 = _discover_wallbox(entities_1)
        result_2 = _discover_wallbox(entities_2)

        # Both should be discovered
        assert result_1, "Wallbox 1 should be detected"
        assert result_2, "Wallbox 2 should be detected"
        # Different power sensors
        assert result_1.get("ev_charging_power_sensor") != result_2.get("ev_charging_power_sensor")

    def test_single_charger_returns_one(self):
        """Single KEBA should return exactly one result."""
        entities = [
            make_mock_entity_registry_entry(
                "binary_sensor.keba_p30_plug", "keba", device_class="plug"),
            make_mock_entity_registry_entry(
                "binary_sensor.keba_p30_charging_state", "keba", device_class="power"),
            make_mock_entity_registry_entry(
                "sensor.keba_p30_charging_power", "keba", device_class="power"),
        ]

        result = _discover_keba(entities)
        assert result
        assert result["ev_charging_power_sensor"] == "sensor.keba_p30_charging_power"
        assert result["ev_charger_service"] == "keba.set_current"


# ============================================================
# Surplus distribution — REMOVED in #651
#
# Two classes lived here: TestMultiChargerSurplusDistribution (8 tests,
# arithmetic on mock attributes, never touching production code at all)
# and TestSurplusControllerDistribution (9 tests against
# ``SurplusController.distribute_ev_budget``). Both described a priority
# cascade that allocated a fleet budget charger-by-charger.
#
# No such cascade ran in a shipped install. Its only caller wrote the
# result into ``pcc.budget_w``, which nothing downstream read — see #651.
# The live allocator is ``decide.self_consumption_surplus_w``, which
# subtracts ``_solar_committed_w_per_cycle`` (accumulated from each
# charger's ACTUAL decision as the priority loop walks it) rather than
# pre-dividing a pot.
#
# The surviving coverage for real multi-charger sharing is
# tests/test_step6_multi_charger_surplus_sharing.py —
# TestSolarCommittedReducesSurplus and TestMultiChargerSurplusOrdering
# cover the two-charger priority split, the three-charger
# first-two-charge case, and both-charge.
# ============================================================


# ============================================================
# Tests: Session tracking isolation
# ============================================================

class TestPerChargerSessionTracking:
    """Test that session tracking is isolated per charger."""

    def test_separate_session_data(self):
        """Each charger should have its own SessionData instance."""
        # SessionData imported at module level

        sessions = {
            "wb_1": SessionData(active=True, energy_kwh=5.5, solar_share_pct=80),
            "wb_2": SessionData(active=True, energy_kwh=3.2, solar_share_pct=60),
        }

        assert sessions["wb_1"].energy_kwh == 5.5
        assert sessions["wb_2"].energy_kwh == 3.2
        assert sessions["wb_1"].solar_share_pct != sessions["wb_2"].solar_share_pct

    def test_primary_charger_is_first(self):
        """Primary charger (for backward compat sensors) should be first in dict."""
        from collections import OrderedDict

        chargers = OrderedDict([
            ("ev_charger_0", make_mock_charger("ev_charger_0", "Wallbox 1", priority=3)),
            ("ev_charger_1", make_mock_charger("ev_charger_1", "Wallbox 2", priority=5)),
        ])

        primary = next(iter(chargers))
        assert primary == "ev_charger_0"

    def test_session_energy_not_mixed(self):
        """Energy from charger 1 should not appear in charger 2's session."""
        # SessionData imported at module level

        session_1 = SessionData(active=True)
        session_2 = SessionData(active=True)

        # Simulate charging on charger 1 only
        session_1.energy_kwh += 2.5
        session_1.solar_energy_kwh += 2.0

        assert session_1.energy_kwh == 2.5
        assert session_2.energy_kwh == 0


# ============================================================
# Tests: Backward compatibility (single charger)
# ============================================================

class TestSingleChargerBackwardCompat:
    """Verify single-charger setups work identically to v1.3."""

    def test_migrated_config_has_one_charger(self):
        """Migrated flat config should produce exactly one charger entry."""
        flat = SCENARIO_SINGLE_KEBA_MIGRATED["flat_config"].copy()
        charger_0 = {"id": "ev_charger", "name": "EV Charger"}
        for k in flat:
            if k.startswith("ev_"):
                charger_0[k] = flat[k]

        ev_chargers = [charger_0]
        assert len(ev_chargers) == 1
        assert ev_chargers[0]["id"] == "ev_charger"

    def test_primary_device_alias(self):
        """coordinator._ev_device should point to first charger."""
        charger = make_mock_charger("ev_charger", "EV Charger")
        ev_devices = {"ev_charger": charger}

        # Simulate __init__.py: _ev_device = first in dict
        primary = next(iter(ev_devices.values()))
        assert primary is charger
        assert primary.device_id == "ev_charger"

    def test_sensor_names_unchanged(self):
        """Primary charger sensors should keep existing names (no _0 suffix)."""
        # SEM_SENSORS imported at module level
        assert SEM_SENSORS["ev_power"] == "sensor.sem_ev_power"
        # New aggregate sensor exists
        assert SEM_SENSORS["ev_charger_count"] == "sensor.sem_ev_charger_count"


# ============================================================
# Tests: Per-charger state isolation
# ============================================================

class TestPerChargerStateIsolation:
    """Verify per-charger timers don't interfere with each other."""

    def test_stall_timers_are_independent(self):
        """Charger 1's stall timer should not affect charger 2."""
        stalled = {"wb_1": 100.0, "wb_2": None}
        # Charger 1 stalled at T=100, charger 2 not stalled
        assert stalled["wb_1"] == 100.0
        assert stalled["wb_2"] is None
        # Clearing charger 2 doesn't affect charger 1
        stalled["wb_2"] = 200.0
        assert stalled["wb_1"] == 100.0

    def test_enable_delay_timers_independent(self):
        """Per-charger enable delay must not bleed between chargers."""
        enable_since = {"wb_1": 50.0, "wb_2": None}
        # Charger 1 has been seeing surplus for 50s, charger 2 just started
        assert enable_since["wb_1"] == 50.0
        assert enable_since["wb_2"] is None

    def test_charge_started_timers_independent(self):
        """Per-charger charge start time must be isolated."""
        started = {"wb_1": 1000.0, "wb_2": 2000.0}
        # Different start times
        assert started["wb_1"] != started["wb_2"]

    def test_night_target_split_equally(self):
        """Night target should split equally across connected chargers."""
        total_target = 10.0  # kWh
        connected_count = 2
        per_charger = total_target / connected_count
        assert per_charger == 5.0

    def test_night_target_single_charger_gets_full(self):
        """Single connected charger gets full night target."""
        total_target = 10.0
        connected_count = 1
        per_charger = total_target / connected_count
        assert per_charger == 10.0


# ============================================================
# Tests: Session persistence
# ============================================================

class TestSessionPersistence:
    """Verify per-charger session save/restore."""

    def test_save_format_includes_chargers_dict(self):
        """Saved state should include 'chargers' dict keyed by charger_id."""
        state = {
            "session_active": True,
            "current_setpoint": 10.0,
            "chargers": {
                "wb_1": {"session_active": True, "current_setpoint": 10.0},
                "wb_2": {"session_active": False, "current_setpoint": 0.0},
            }
        }
        assert "chargers" in state
        assert state["chargers"]["wb_1"]["session_active"] is True
        assert state["chargers"]["wb_2"]["session_active"] is False

    def test_restore_falls_back_to_top_level_for_primary(self):
        """Primary charger should read from top-level if 'chargers' missing (migration)."""
        state = {"session_active": True, "current_setpoint": 12.0}
        # No 'chargers' key — old format
        primary_id = "ev_charger"
        chargers_dict = state.get("chargers", {})
        # Fallback: primary reads from top level
        primary_state = chargers_dict.get(primary_id, state)
        assert primary_state["session_active"] is True
        assert primary_state["current_setpoint"] == 12.0


# ============================================================
# Tests: SEMData multi-charger fields
# ============================================================

class TestSEMDataMultiCharger:
    """Test SEMData includes multi-charger metadata."""

    def test_to_dict_includes_charger_count(self):
        """SEMData.to_dict() should include ev_charger_count."""
        # SEMData imported at module level

        data = SEMData(ev_charger_count=2, ev_charger_ids=["wb_1", "wb_2"])
        d = data.to_dict()

        assert d["ev_charger_count"] == 2

    def test_to_dict_single_charger(self):
        """Single charger: ev_charger_count=1."""
        # SEMData imported at module level

        data = SEMData(ev_charger_count=1, ev_charger_ids=["ev_charger"])
        d = data.to_dict()

        assert d["ev_charger_count"] == 1

    def test_sessions_dict_per_charger(self):
        """Sessions dict should hold per-charger SessionData."""
        # SEMData imported at module level, SessionData

        data = SEMData(
            sessions={
                "wb_1": SessionData(active=True, energy_kwh=5.0),
                "wb_2": SessionData(active=False, energy_kwh=0),
            }
        )

        assert data.sessions["wb_1"].active is True
        assert data.sessions["wb_2"].active is False
