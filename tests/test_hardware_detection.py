"""Tests for EVChargerDetector (hardware_detection.py)."""
import pytest
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.hardware_detection import (
    EVChargerDetector,
    HardwareDetector,
)


# --- Fixtures ---


KEBA_ENTITIES = [
    "sensor.keba_p30_charging_power",
    "sensor.keba_p30_total_energy",
    "binary_sensor.keba_p30_plug_connected",
    "binary_sensor.keba_p30_charging",
    "sensor.keba_p30_charging_current",
    "sensor.keba_p30_session_energy",
]

EASEE_ENTITIES = [
    "sensor.easee_power",
    "sensor.easee_current",
    "sensor.easee_status",
    "sensor.easee_session_energy",
    "sensor.easee_total_energy",
]


def _make_state(entity_id):
    """Return a mock state appropriate for the entity_id."""
    state = MagicMock()
    state.attributes = {}
    if "power" in entity_id:
        state.state = "3500"
    elif "energy" in entity_id:
        state.state = "150.5"
    elif "current" in entity_id or "amp" in entity_id:
        state.state = "16"
    elif "connected" in entity_id or "charging" in entity_id:
        state.state = "on"
    elif "status" in entity_id:
        state.state = "on"
    elif "plug" in entity_id:
        state.state = "on"
    else:
        state.state = "42"
    return state


def _mock_get(entities):
    """Return a states.get function that knows about *entities*."""
    def getter(entity_id):
        if entity_id in entities:
            return _make_state(entity_id)
        return None
    return getter


@pytest.fixture
def detector_keba(hass):
    """Return an EVChargerDetector with KEBA entities available."""
    hass.states.async_entity_ids = MagicMock(return_value=KEBA_ENTITIES)
    hass.states.get = _mock_get(KEBA_ENTITIES)
    with patch(
        "custom_components.solar_energy_management.hardware_detection.entity_registry"
    ) as mock_er:
        mock_er.async_get = MagicMock(return_value=MagicMock())
        yield EVChargerDetector(hass)


@pytest.fixture
def detector_easee(hass):
    """Return an EVChargerDetector with Easee entities available."""
    hass.states.async_entity_ids = MagicMock(return_value=EASEE_ENTITIES)
    hass.states.get = _mock_get(EASEE_ENTITIES)
    with patch(
        "custom_components.solar_energy_management.hardware_detection.entity_registry"
    ) as mock_er:
        mock_er.async_get = MagicMock(return_value=MagicMock())
        yield EVChargerDetector(hass)


@pytest.fixture
def detector_empty(hass):
    """Return an EVChargerDetector with no entities."""
    hass.states.async_entity_ids = MagicMock(return_value=[])
    hass.states.get = MagicMock(return_value=None)
    with patch(
        "custom_components.solar_energy_management.hardware_detection.entity_registry"
    ) as mock_er:
        mock_er.async_get = MagicMock(return_value=MagicMock())
        yield EVChargerDetector(hass)


@pytest.fixture
def detector_generic(hass):
    """Return a detector with generic charger entities (no integration-specific names)."""
    generic_entities = [
        "sensor.my_charger_power_total",
        "binary_sensor.ev_charging_status",
        "binary_sensor.charger_connected_status",
        "sensor.charger_current_reading",
        "sensor.charger_session_kwh",
        "sensor.ev_total_energy_counter",
    ]
    hass.states.async_entity_ids = MagicMock(return_value=generic_entities)
    hass.states.get = _mock_get(generic_entities)
    with patch(
        "custom_components.solar_energy_management.hardware_detection.entity_registry"
    ) as mock_er:
        mock_er.async_get = MagicMock(return_value=MagicMock())
        yield EVChargerDetector(hass)


# --- Tests ---


class TestInit:
    """Test EVChargerDetector initialization."""

    def test_init(self, detector_keba, hass):
        """Detector stores hass and entity_registry."""
        assert detector_keba.hass is hass

    def test_hardware_detector_alias(self):
        """HardwareDetector is an alias for EVChargerDetector."""
        assert HardwareDetector is EVChargerDetector


class TestGetAllEntities:
    """Test get_all_entities method."""

    def test_get_all_entities(self, detector_keba):
        """Returns all entity IDs from hass.states.async_entity_ids."""
        entities = detector_keba.get_all_entities()
        assert set(entities) == set(KEBA_ENTITIES)

    def test_get_all_entities_empty(self, detector_empty):
        """Returns empty list when no entities exist."""
        assert detector_empty.get_all_entities() == []


class TestFindPatternMatches:
    """Test _find_pattern_matches method."""

    def test_find_pattern_matches_wildcard(self, detector_keba):
        """Wildcard pattern matches expected entities."""
        matches = detector_keba._find_pattern_matches(
            "sensor.keba_*_power", KEBA_ENTITIES
        )
        # sensor.keba_p30_charging_power does NOT match sensor.keba_*_power
        # because fnmatch treats * as matching everything including underscores
        # but there are multiple segments. Let's verify what actually matches.
        # sensor.keba_p30_charging_power vs sensor.keba_*_power
        # * matches "p30_charging" so this should match.
        assert "sensor.keba_p30_charging_power" in matches

    def test_find_pattern_matches_exact(self, detector_keba):
        """Exact pattern match works."""
        matches = detector_keba._find_pattern_matches(
            "sensor.keba_p30_charging_power", KEBA_ENTITIES
        )
        assert matches == ["sensor.keba_p30_charging_power"]

    def test_find_pattern_matches_no_match(self, detector_keba):
        """Returns empty list when pattern does not match."""
        matches = detector_keba._find_pattern_matches(
            "sensor.nonexistent_*", KEBA_ENTITIES
        )
        assert matches == []

    def test_find_pattern_matches_exact_not_in_list(self, detector_keba):
        """Exact pattern not in entity list returns empty."""
        matches = detector_keba._find_pattern_matches(
            "sensor.does_not_exist", KEBA_ENTITIES
        )
        assert matches == []


class TestValidateEntity:
    """Test _validate_entity method."""

    def test_validate_entity_power_valid(self, detector_keba):
        """Valid power entity in range returns True."""
        assert detector_keba._validate_entity(
            "sensor.keba_p30_charging_power", "ev_charging_power"
        ) is True

    def test_validate_entity_power_out_of_range(self, hass):
        """Power value > 20000 returns False."""
        hass.states.async_entity_ids = MagicMock(return_value=[])
        state = MagicMock()
        state.state = "25000"
        state.attributes = {}
        hass.states.get = MagicMock(return_value=state)
        with patch(
            "custom_components.solar_energy_management.hardware_detection.entity_registry"
        ) as mock_er:
            mock_er.async_get = MagicMock(return_value=MagicMock())
            det = EVChargerDetector(hass)
        assert det._validate_entity("sensor.x", "ev_charging_power") is False

    def test_validate_entity_binary_valid(self, detector_keba):
        """Binary sensor with on/off/true/false/0/1 returns True."""
        assert detector_keba._validate_entity(
            "binary_sensor.keba_p30_plug_connected", "ev_connected"
        ) is True

    def test_validate_entity_binary_invalid_state(self, hass):
        """Binary sensor with non-boolean state returns False."""
        state = MagicMock()
        state.state = "maybe"
        state.attributes = {}
        hass.states.get = MagicMock(return_value=state)
        hass.states.async_entity_ids = MagicMock(return_value=[])
        with patch(
            "custom_components.solar_energy_management.hardware_detection.entity_registry"
        ) as mock_er:
            mock_er.async_get = MagicMock(return_value=MagicMock())
            det = EVChargerDetector(hass)
        assert det._validate_entity("binary_sensor.x", "ev_connected") is False

    def test_validate_entity_unavailable(self, hass):
        """Unavailable entity returns False."""
        state = MagicMock()
        state.state = "unavailable"
        state.attributes = {}
        hass.states.get = MagicMock(return_value=state)
        hass.states.async_entity_ids = MagicMock(return_value=[])
        with patch(
            "custom_components.solar_energy_management.hardware_detection.entity_registry"
        ) as mock_er:
            mock_er.async_get = MagicMock(return_value=MagicMock())
            det = EVChargerDetector(hass)
        assert det._validate_entity("sensor.x", "ev_charging_power") is False

    def test_validate_entity_not_found(self, detector_keba):
        """Entity that does not exist returns False."""
        assert detector_keba._validate_entity(
            "sensor.does_not_exist", "ev_charging_power"
        ) is False

    def test_validate_entity_unknown_state(self, hass):
        """Entity with 'unknown' state returns False."""
        state = MagicMock()
        state.state = "unknown"
        state.attributes = {}
        hass.states.get = MagicMock(return_value=state)
        hass.states.async_entity_ids = MagicMock(return_value=[])
        with patch(
            "custom_components.solar_energy_management.hardware_detection.entity_registry"
        ) as mock_er:
            mock_er.async_get = MagicMock(return_value=MagicMock())
            det = EVChargerDetector(hass)
        assert det._validate_entity("sensor.x", "ev_current") is False

    def test_validate_entity_other_type_always_true(self, detector_keba):
        """Non-power, non-binary sensor types return True if state is valid."""
        assert detector_keba._validate_entity(
            "sensor.keba_p30_total_energy", "ev_total_energy"
        ) is True


class TestDetectEvEntities:
    """Test detect_ev_entities method."""

    def test_detect_keba_entities(self, detector_keba):
        """Finds KEBA-specific entities."""
        detected = detector_keba.detect_ev_entities()
        # Should detect ev_charging_power with KEBA entity
        power_entities = [
            eid for eid, desc, exists, pri in detected.get("ev_charging_power", [])
        ]
        assert "sensor.keba_p30_charging_power" in power_entities

    def test_detect_easee_entities(self, detector_easee):
        """Finds Easee entities."""
        detected = detector_easee.detect_ev_entities()
        power_entities = [
            eid for eid, desc, exists, pri in detected.get("ev_charging_power", [])
        ]
        assert "sensor.easee_power" in power_entities

    def test_detect_generic_fallback(self, detector_generic):
        """Falls back to generic patterns when no integration-specific match."""
        detected = detector_generic.detect_ev_entities()
        # Generic pattern sensor.*charger*power* should match sensor.my_charger_power_total
        power_entities = [
            eid for eid, desc, exists, pri in detected.get("ev_charging_power", [])
        ]
        assert "sensor.my_charger_power_total" in power_entities

    def test_detect_returns_all_sensor_types(self, detector_keba):
        """Detected dict contains all expected sensor types."""
        detected = detector_keba.detect_ev_entities()
        expected_types = {
            "ev_connected",
            "ev_charging",
            "ev_charging_power",
            "ev_current",
            "ev_session_energy",
            "ev_total_energy",
        }
        assert expected_types.issubset(set(detected.keys()))

    def test_detected_sorted_by_exists_and_priority(self, detector_keba):
        """Results are sorted: valid entities first, then by priority descending."""
        detected = detector_keba.detect_ev_entities()
        for sensor_type, entries in detected.items():
            if len(entries) > 1:
                # Verify sorted: (exists=True, high priority) before (exists=False, low priority)
                for i in range(len(entries) - 1):
                    e1 = entries[i]
                    e2 = entries[i + 1]
                    assert (e1[2], e1[3]) >= (e2[2], e2[3])


class TestGetBestMatch:
    """Test get_best_match method."""

    def test_get_best_match_found(self, detector_keba):
        """Returns highest priority valid entity."""
        result = detector_keba.get_best_match("ev_charging_power")
        assert result == "sensor.keba_p30_charging_power"

    def test_get_best_match_not_found(self, detector_empty):
        """Returns None when no matching entities."""
        result = detector_empty.get_best_match("ev_charging_power")
        assert result is None

    def test_get_best_match_unknown_type(self, detector_keba):
        """Returns None for unknown sensor type."""
        result = detector_keba.get_best_match("nonexistent_type")
        assert result is None


class TestGetDetectedIntegrations:
    """Test get_detected_ev_integrations method."""

    def test_get_detected_integrations_keba(self, detector_keba):
        """Detects KEBA as installed."""
        integrations = detector_keba.get_detected_ev_integrations()
        assert integrations["keba"] is True

    def test_get_detected_integrations_no_easee(self, detector_keba):
        """Does not detect Easee when only KEBA entities present."""
        integrations = detector_keba.get_detected_ev_integrations()
        assert integrations["easee"] is False

    def test_get_detected_integrations_easee(self, detector_easee):
        """Detects Easee when Easee entities present."""
        integrations = detector_easee.get_detected_ev_integrations()
        assert integrations["easee"] is True

    def test_get_detected_integrations_none(self, detector_empty):
        """All integrations False when no entities."""
        integrations = detector_empty.get_detected_ev_integrations()
        for integration, detected in integrations.items():
            assert detected is False


class TestValidateEvConfiguration:
    """Test validate_ev_configuration method."""

    def test_validate_ev_configuration_valid(self, detector_keba):
        """All required sensors present and valid produces no errors."""
        config = {
            "ev_connected_sensor": "binary_sensor.keba_p30_plug_connected",
            "ev_charging_sensor": "binary_sensor.keba_p30_charging",
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        }
        errors = detector_keba.validate_ev_configuration(config)
        assert errors == {}

    def test_validate_ev_configuration_missing(self, detector_keba):
        """Missing sensor config reports error."""
        config = {
            "ev_connected_sensor": "binary_sensor.keba_p30_plug_connected",
            # ev_charging_sensor missing
            # ev_charging_power_sensor missing
        }
        errors = detector_keba.validate_ev_configuration(config)
        assert "ev_charging_sensor" in errors
        assert "ev_charging_power_sensor" in errors

    def test_validate_ev_configuration_invalid_entity(self, detector_keba):
        """Entity that does not exist reports error."""
        config = {
            "ev_connected_sensor": "binary_sensor.keba_p30_plug_connected",
            "ev_charging_sensor": "binary_sensor.keba_p30_charging",
            "ev_charging_power_sensor": "sensor.nonexistent",
        }
        errors = detector_keba.validate_ev_configuration(config)
        assert "ev_charging_power_sensor" in errors

    def test_validate_ev_configuration_empty_value(self, detector_keba):
        """Empty string sensor value reports required error."""
        config = {
            "ev_connected_sensor": "",
            "ev_charging_sensor": "binary_sensor.keba_p30_charging",
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        }
        errors = detector_keba.validate_ev_configuration(config)
        assert "ev_connected_sensor" in errors


class TestGetSuggestedEvDefaults:
    """Test get_suggested_ev_defaults method."""

    def test_get_suggested_ev_defaults(self, detector_keba):
        """Returns detected defaults for all sensor mappings."""
        defaults = detector_keba.get_suggested_ev_defaults()
        assert "ev_connected_sensor" in defaults
        assert "ev_charging_sensor" in defaults
        assert "ev_charging_power_sensor" in defaults
        assert defaults["ev_charging_power_sensor"] == "sensor.keba_p30_charging_power"

    def test_get_suggested_ev_defaults_empty_fallback(self, detector_empty):
        """Returns empty strings when no entities detected."""
        defaults = detector_empty.get_suggested_ev_defaults()
        for key, value in defaults.items():
            assert value == ""


class TestMergedPatterns:
    """Test _get_merged_patterns method."""

    def test_merged_patterns_sorted_by_priority(self, detector_keba):
        """Merged patterns are sorted by priority descending."""
        merged = detector_keba._get_merged_patterns()
        for sensor_type, patterns in merged.items():
            priorities = [p[2] for p in patterns]
            assert priorities == sorted(priorities, reverse=True)

    def test_merged_patterns_contain_generic(self, detector_keba):
        """Merged patterns include generic fallback patterns."""
        merged = detector_keba._get_merged_patterns()
        descriptions = [desc for _, desc, _ in merged.get("ev_charging_power", [])]
        assert any("Generic" in d for d in descriptions)


# ============================================================
# discover_inverter_from_registry — battery discharge control
# ============================================================


def _make_registry_entry(entity_id, platform, config_entry_id="ce-1", disabled=False):
    """Build a fake EntityRegistryEntry that mimics the fields the
    discover function reads."""
    entry = MagicMock()
    entry.entity_id = entity_id
    entry.platform = platform
    entry.config_entry_id = config_entry_id
    entry.disabled_by = None if not disabled else "user"
    return entry


def _build_fake_registry(entries):
    """Build a fake entity_registry.async_get(hass) result that exposes
    the two API surfaces discover_inverter_from_registry actually uses:
    - .async_get(entity_id) → entry or None
    - .entities.values() → iterable of entries
    """
    by_id = {e.entity_id: e for e in entries}

    fake_reg = MagicMock()
    fake_reg.async_get = lambda eid: by_id.get(eid)
    fake_reg.entities = MagicMock()
    fake_reg.entities.values = lambda: list(entries)
    return fake_reg


class _FakeEnergyDashboardConfig:
    """Lightweight stand-in for EnergyDashboardConfig."""

    def __init__(self, **kwargs):
        for key in (
            "battery_power",
            "battery_charge_energy",
            "battery_discharge_energy",
            "solar_power",
            "solar_energy",
            "grid_import_power",
        ):
            setattr(self, key, kwargs.get(key))


class TestDiscoverInverterFromRegistry:
    """Test discover_inverter_from_registry()."""

    def _patch_registry(self, entries):
        """Patch hardware_detection.entity_registry.async_get to return
        a fake registry built from ``entries``."""
        from custom_components.solar_energy_management import hardware_detection

        fake_reg = _build_fake_registry(entries)
        return patch.object(
            hardware_detection.entity_registry,
            "async_get",
            return_value=fake_reg,
        )

    def test_returns_none_when_config_is_none(self):
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        assert discover_inverter_from_registry(MagicMock(), None) is None

    def test_returns_none_when_no_seed_sensors(self):
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        cfg = _FakeEnergyDashboardConfig()  # all attrs are None
        assert discover_inverter_from_registry(MagicMock(), cfg) is None

    def test_returns_none_when_seed_not_in_registry(self):
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.unknown_battery")

        with self._patch_registry([]):
            assert discover_inverter_from_registry(hass, cfg) is None

    def test_huawei_solar_german_locale(self):
        """Realistic Huawei Solar (DE locale) install — the entity name is
        ``number.batteries_maximale_entladeleistung`` and SEM should pick
        it up via the German pattern."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.battery_1_lade_entladeleistung", "huawei_solar"),
            _make_registry_entry("sensor.inverter_eingangsleistung", "huawei_solar"),
            _make_registry_entry(
                "number.batteries_maximale_entladeleistung", "huawei_solar"
            ),
            # Noise from another integration — must be ignored.
            _make_registry_entry(
                "number.shelly_max_power", "shelly", config_entry_id="ce-9"
            ),
        ]
        cfg = _FakeEnergyDashboardConfig(
            battery_power="sensor.battery_1_lade_entladeleistung"
        )

        with self._patch_registry(entries):
            result = discover_inverter_from_registry(hass, cfg)

        assert result == "number.batteries_maximale_entladeleistung"

    def test_english_max_discharge_power(self):
        """English ``number.huawei_battery_max_discharge_power`` matches."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.huawei_battery_power", "huawei_solar"),
            _make_registry_entry(
                "number.huawei_battery_max_discharge_power", "huawei_solar"
            ),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.huawei_battery_power")

        with self._patch_registry(entries):
            assert (
                discover_inverter_from_registry(hass, cfg)
                == "number.huawei_battery_max_discharge_power"
            )

    def test_falls_back_to_solar_seed_if_no_battery(self):
        """If only a solar sensor is known, the discovery still works."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.inverter_input_power", "huawei_solar"),
            _make_registry_entry(
                "number.batteries_maximale_entladeleistung", "huawei_solar"
            ),
        ]
        cfg = _FakeEnergyDashboardConfig(solar_power="sensor.inverter_input_power")

        with self._patch_registry(entries):
            assert (
                discover_inverter_from_registry(hass, cfg)
                == "number.batteries_maximale_entladeleistung"
            )

    def test_skips_disabled_entities(self):
        """Disabled entities must not be returned."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.battery_power", "huawei_solar"),
            _make_registry_entry(
                "number.batteries_maximale_entladeleistung",
                "huawei_solar",
                disabled=True,
            ),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.battery_power")

        with self._patch_registry(entries):
            assert discover_inverter_from_registry(hass, cfg) is None

    def test_skips_entities_from_other_config_entry(self):
        """Number entities from a different config_entry_id (different
        inverter) must not contaminate the result."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry(
                "sensor.battery_power", "huawei_solar", config_entry_id="ce-A"
            ),
            _make_registry_entry(
                "number.batteries_maximale_entladeleistung",
                "huawei_solar",
                config_entry_id="ce-B",  # different inverter
            ),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.battery_power")

        with self._patch_registry(entries):
            assert discover_inverter_from_registry(hass, cfg) is None

    def test_no_pattern_match(self):
        """Same platform but no number entity matches the discharge patterns."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.battery_power", "huawei_solar"),
            _make_registry_entry("number.huawei_grid_export_limit", "huawei_solar"),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.battery_power")

        with self._patch_registry(entries):
            assert discover_inverter_from_registry(hass, cfg) is None

    def test_solax_discharge_entity(self):
        """SolAX discharge control entity should be detected."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.solax_battery_power", "solax_modbus"),
            _make_registry_entry("number.solax_battery_discharge_max_power", "solax_modbus"),
            _make_registry_entry("number.solax_battery_charge_max_current", "solax_modbus"),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.solax_battery_power")

        with self._patch_registry(entries):
            result = discover_inverter_from_registry(hass, cfg)
        assert result == "number.solax_battery_discharge_max_power"

    def test_solarman_deye_discharge_entity(self):
        """Solarman/DEYE discharge control entity should be detected."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.deye_battery_power", "solarman"),
            _make_registry_entry("number.deye_battery_discharge_limit", "solarman"),
            _make_registry_entry("number.deye_grid_export_limit", "solarman"),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.deye_battery_power")

        with self._patch_registry(entries):
            result = discover_inverter_from_registry(hass, cfg)
        assert result == "number.deye_battery_discharge_limit"

    def test_growatt_discharge_entity(self):
        """Growatt discharge control entity should be detected."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.growatt_battery_power", "growatt"),
            _make_registry_entry("number.growatt_battery_discharge_power", "growatt"),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.growatt_battery_power")

        with self._patch_registry(entries):
            result = discover_inverter_from_registry(hass, cfg)
        assert result == "number.growatt_battery_discharge_power"

    def test_generic_discharge_power_limit(self):
        """Generic discharge_power_limit naming should match as fallback."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.inverter_battery_power", "some_integration"),
            _make_registry_entry("number.inverter_discharge_power_limit", "some_integration"),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.inverter_battery_power")

        with self._patch_registry(entries):
            result = discover_inverter_from_registry(hass, cfg)
        assert result == "number.inverter_discharge_power_limit"

    def test_sunsynk_discharge_entity(self):
        """Sunsynk (via solarman) discharge entity should be detected."""
        from custom_components.solar_energy_management.hardware_detection import (
            discover_inverter_from_registry,
        )

        hass = MagicMock()
        entries = [
            _make_registry_entry("sensor.sunsynk_battery_power", "solarman"),
            _make_registry_entry("number.sunsynk_battery_discharge_max", "solarman"),
        ]
        cfg = _FakeEnergyDashboardConfig(battery_power="sensor.sunsynk_battery_power")

        with self._patch_registry(entries):
            result = discover_inverter_from_registry(hass, cfg)
        assert result == "number.sunsynk_battery_discharge_max"
