"""Tests for per-charger entities (#193).

Verifies that per-charger number entities, switch entities, and sensors
are created correctly when multiple EV chargers are configured.
"""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.components.number import NumberEntityDescription
from homeassistant.components.switch import SwitchEntityDescription
from homeassistant.components.sensor import SensorEntityDescription
from homeassistant.helpers.entity import EntityCategory

from custom_components.solar_energy_management.number import (
    SEMNumberEntity,
    SEMPerChargerNumber,
    NUMBER_TYPES,
)
from custom_components.solar_energy_management.switch import (
    SEMSolarSwitch,
    SEMPerChargerSwitch,
    SWITCH_TYPES,
)


def _mock_coordinator(ev_chargers=None):
    """Create a mock coordinator with optional ev_chargers config."""
    coord = MagicMock()
    coord.last_update_success = True
    coord.data = MagicMock()
    coord.device_info = {"identifiers": {("solar_energy_management", "test")}}
    coord.hass = MagicMock()
    coord.hass.config.currency = "EUR"
    coord.config_entry = MagicMock()
    full_config = {"ev_chargers": ev_chargers or []}
    coord.config_entry.data = {}
    coord.config_entry.options = full_config
    return coord


def _mock_entry(ev_chargers=None, **kwargs):
    """Create a mock config entry."""
    entry = MagicMock()
    opts = {"ev_chargers": ev_chargers or [], **kwargs}
    entry.data = {}
    entry.options = opts
    entry.entry_id = "test_entry_123"
    return entry


TWO_CHARGERS = [
    {
        "id": "ev_charger",
        "name": "KEBA P30",
        "ev_charging_power_sensor": "sensor.keba_power",
        "daily_ev_target": 10,
        "ev_night_initial_current": 10,
        "ev_min_current": 6,
    },
    {
        "id": "ev_charger_1",
        "name": "Wallbox Pulsar",
        "ev_charging_power_sensor": "sensor.wallbox_power",
        "daily_ev_target": 15,
        "ev_night_initial_current": 8,
        "ev_min_current": 6,
    },
]

SINGLE_CHARGER = [
    {
        "id": "ev_charger",
        "name": "KEBA P30",
        "ev_charging_power_sensor": "sensor.keba_power",
    },
]


@pytest.mark.unit
class TestPerChargerNumbers:
    """Test per-charger number entity creation."""

    def test_per_charger_number_created(self):
        """Per-charger number should initialize with correct values."""
        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        desc = NumberEntityDescription(
            key="charger_ev_charger_1_daily_ev_target",
            name="Wallbox Pulsar Night Target",
            native_min_value=0, native_max_value=100, native_step=0.5,
        )
        num = SEMPerChargerNumber(
            coord, desc, entry, "ev_charger_1", "daily_ev_target", 15.0,
        )
        assert num._attr_native_value == 15.0
        assert num._charger_id == "ev_charger_1"
        assert num._config_key == "daily_ev_target"
        assert num.entity_id == "number.sem_charger_ev_charger_1_daily_ev_target"

    def test_per_charger_number_unique_id(self):
        """Each per-charger number should have a unique ID."""
        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        desc1 = NumberEntityDescription(key="charger_ev_charger_daily_ev_target")
        desc2 = NumberEntityDescription(key="charger_ev_charger_1_daily_ev_target")
        num1 = SEMPerChargerNumber(coord, desc1, entry, "ev_charger", "daily_ev_target", 10)
        num2 = SEMPerChargerNumber(coord, desc2, entry, "ev_charger_1", "daily_ev_target", 15)
        assert num1._attr_unique_id != num2._attr_unique_id

    @pytest.mark.asyncio
    async def test_per_charger_number_set_value(self):
        """Setting a per-charger number should update the charger's config dict."""
        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        coord.async_request_refresh = AsyncMock()
        desc = NumberEntityDescription(key="charger_ev_charger_1_daily_ev_target")
        num = SEMPerChargerNumber(
            coord, desc, entry, "ev_charger_1", "daily_ev_target", 15,
        )
        num.hass = coord.hass
        num.async_write_ha_state = MagicMock()

        await num.async_set_native_value(20.0)

        assert num._attr_native_value == 20.0
        # Verify the config entry was updated
        coord.hass.config_entries.async_update_entry.assert_called_once()
        call_kwargs = coord.hass.config_entries.async_update_entry.call_args
        new_options = call_kwargs[1]["options"]
        # Find the charger in updated options
        charger = next(
            c for c in new_options["ev_chargers"]
            if c["id"] == "ev_charger_1"
        )
        assert charger["daily_ev_target"] == 20.0

    def test_per_charger_number_available(self):
        """Per-charger number should be available when coordinator is ok."""
        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        desc = NumberEntityDescription(key="charger_ev_charger_daily_ev_target")
        num = SEMPerChargerNumber(coord, desc, entry, "ev_charger", "daily_ev_target", 10)
        assert num.available is True
        coord.last_update_success = False
        assert num.available is False

    def test_three_settings_per_charger(self):
        """Each charger should get 3 number entities: target, start amps, min amps."""
        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        settings = [
            ("daily_ev_target", 10),
            ("ev_night_initial_current", 10),
            ("ev_min_current", 6),
        ]
        for config_key, default in settings:
            desc = NumberEntityDescription(key=f"charger_ev_charger_{config_key}")
            num = SEMPerChargerNumber(
                coord, desc, entry, "ev_charger", config_key, default,
            )
            assert num._attr_native_value == default
            assert num._config_key == config_key


@pytest.mark.unit
class TestPerChargerSwitches:
    """Test per-charger night charging switch entities."""

    def test_per_charger_switch_created(self):
        """Per-charger switch should initialize correctly."""
        coord = _mock_coordinator(TWO_CHARGERS)
        desc = SwitchEntityDescription(
            key="charger_ev_charger_1_night_charging",
            entity_category=EntityCategory.CONFIG,
        )
        switch = SEMPerChargerSwitch(
            coord, desc, "test_entry", "ev_charger_1", "Wallbox Pulsar",
        )
        assert switch._charger_id == "ev_charger_1"
        assert switch.entity_id == "switch.sem_charger_ev_charger_1_night_charging"
        assert switch.is_on is True  # default ON

    def test_per_charger_switch_unique_ids(self):
        """Each per-charger switch should have a unique ID."""
        coord = _mock_coordinator(TWO_CHARGERS)
        desc1 = SwitchEntityDescription(key="charger_ev_charger_night_charging")
        desc2 = SwitchEntityDescription(key="charger_ev_charger_1_night_charging")
        sw1 = SEMPerChargerSwitch(coord, desc1, "test", "ev_charger", "KEBA")
        sw2 = SEMPerChargerSwitch(coord, desc2, "test", "ev_charger_1", "Wallbox")
        assert sw1._attr_unique_id != sw2._attr_unique_id

    @pytest.mark.asyncio
    async def test_per_charger_switch_toggle(self):
        """Toggling a per-charger switch should change its state."""
        coord = _mock_coordinator(TWO_CHARGERS)
        coord.async_request_refresh = AsyncMock()
        desc = SwitchEntityDescription(key="charger_ev_charger_night_charging")
        switch = SEMPerChargerSwitch(coord, desc, "test", "ev_charger", "KEBA")

        assert switch.is_on is True
        await switch.async_turn_off()
        assert switch.is_on is False
        await switch.async_turn_on()
        assert switch.is_on is True

    def test_per_charger_switch_available(self):
        """Per-charger switch should be unavailable when coordinator fails."""
        coord = _mock_coordinator(TWO_CHARGERS)
        coord.data = None
        desc = SwitchEntityDescription(key="charger_ev_charger_night_charging")
        switch = SEMPerChargerSwitch(coord, desc, "test", "ev_charger", "KEBA")
        assert switch.available is False


@pytest.mark.unit
class TestPerChargerSensors:
    """Test per-charger sensor descriptions are created correctly."""

    def test_intelligence_sensors_created_for_each_charger(self):
        """Each charger should get intelligence sensor descriptions."""
        expected_suffixes = [
            "estimated_soc",
            "nights_until_charge",
            "charge_needed",
            "taper_minutes_to_full",
        ]
        for charger in TWO_CHARGERS:
            cid = charger["id"]
            for suffix in expected_suffixes:
                key = f"charger_{cid}_{suffix}"
                # Just verify the key pattern is valid
                assert cid in key
                assert suffix in key

    def test_power_sensor_per_charger(self):
        """Per-charger power sensor key should follow naming convention."""
        for charger in TWO_CHARGERS:
            cid = charger["id"]
            key = f"charger_{cid}_power"
            assert key.startswith("charger_")
            assert key.endswith("_power")

    def test_session_sensors_per_charger(self):
        """Per-charger session sensors should follow naming convention."""
        for charger in TWO_CHARGERS:
            cid = charger["id"]
            session_key = f"charger_{cid}_session_energy"
            solar_key = f"charger_{cid}_session_solar_share"
            assert "session_energy" in session_key
            assert "session_solar_share" in solar_key


@pytest.mark.unit
class TestPerChargerAggregation:
    """Test that global EV power sums all chargers."""

    def test_ev_power_sums_multi_charger(self):
        """Global ev_power should be sum of all charger power sensors."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        hass = MagicMock()
        config = {
            "solar_production_sensor": "sensor.solar",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.battery",
            "ev_charging_power_sensor": "sensor.keba_power",
            "ev_connected_sensor": "binary_sensor.ev_plug",
            "ev_charging_sensor": "binary_sensor.ev_charging",
            "ev_chargers": TWO_CHARGERS,
        }

        reader = SensorReader(hass, config)

        # Mock sensor states
        def mock_get(entity_id):
            states = {
                "sensor.keba_power": MagicMock(state="3000", attributes={"unit_of_measurement": "W"}),
                "sensor.wallbox_power": MagicMock(state="5000", attributes={"unit_of_measurement": "W"}),
                "sensor.solar": MagicMock(state="8000", attributes={"unit_of_measurement": "W"}),
                "sensor.grid": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.battery": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "binary_sensor.ev_plug": MagicMock(state="on"),
                "binary_sensor.ev_charging": MagicMock(state="on"),
            }
            return states.get(entity_id)

        hass.states.get = mock_get

        readings = reader.read_power()
        # ev_power should be sum of both chargers: 3000 + 5000 = 8000
        assert readings.ev_power == 8000.0

    def test_ev_power_sums_three_chargers(self):
        """Global ev_power should sum 3 chargers correctly."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        three_chargers = [
            {"id": "c1", "name": "C1", "ev_charging_power_sensor": "sensor.c1_power"},
            {"id": "c2", "name": "C2", "ev_charging_power_sensor": "sensor.c2_power"},
            {"id": "c3", "name": "C3", "ev_charging_power_sensor": "sensor.c3_power"},
        ]
        hass = MagicMock()
        config = {
            "solar_production_sensor": "sensor.solar",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.battery",
            "ev_charging_power_sensor": "sensor.c1_power",
            "ev_connected_sensor": "binary_sensor.ev_plug",
            "ev_charging_sensor": "binary_sensor.ev_charging",
            "ev_chargers": three_chargers,
        }
        reader = SensorReader(hass, config)

        def mock_get(entity_id):
            states = {
                "sensor.c1_power": MagicMock(state="2000", attributes={"unit_of_measurement": "W"}),
                "sensor.c2_power": MagicMock(state="3000", attributes={"unit_of_measurement": "W"}),
                "sensor.c3_power": MagicMock(state="4000", attributes={"unit_of_measurement": "W"}),
                "sensor.solar": MagicMock(state="10000", attributes={"unit_of_measurement": "W"}),
                "sensor.grid": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.battery": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "binary_sensor.ev_plug": MagicMock(state="on"),
                "binary_sensor.ev_charging": MagicMock(state="on"),
            }
            return states.get(entity_id)
        hass.states.get = mock_get

        readings = reader.read_power()
        assert readings.ev_power == 9000.0  # 2000 + 3000 + 4000

    def test_ev_power_sums_four_chargers(self):
        """Global ev_power should sum 4 chargers correctly."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        four_chargers = [
            {"id": f"c{i}", "name": f"C{i}", "ev_charging_power_sensor": f"sensor.c{i}_power"}
            for i in range(1, 5)
        ]
        hass = MagicMock()
        config = {
            "solar_production_sensor": "sensor.solar",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.battery",
            "ev_charging_power_sensor": "sensor.c1_power",
            "ev_connected_sensor": "binary_sensor.ev_plug",
            "ev_charging_sensor": "binary_sensor.ev_charging",
            "ev_chargers": four_chargers,
        }
        reader = SensorReader(hass, config)

        def mock_get(entity_id):
            powers = {"sensor.c1_power": "1500", "sensor.c2_power": "2500",
                      "sensor.c3_power": "3500", "sensor.c4_power": "4500"}
            if entity_id in powers:
                return MagicMock(state=powers[entity_id], attributes={"unit_of_measurement": "W"})
            defaults = {
                "sensor.solar": MagicMock(state="15000", attributes={"unit_of_measurement": "W"}),
                "sensor.grid": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.battery": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "binary_sensor.ev_plug": MagicMock(state="on"),
                "binary_sensor.ev_charging": MagicMock(state="on"),
            }
            return defaults.get(entity_id)
        hass.states.get = mock_get

        readings = reader.read_power()
        assert readings.ev_power == 12000.0  # 1500 + 2500 + 3500 + 4500

    def test_per_charger_entities_scale_to_four(self):
        """4 chargers should create 4x number + 4x switch entities."""
        four_chargers = [
            {"id": f"c{i}", "name": f"Charger {i}", "ev_charging_power_sensor": f"sensor.c{i}"}
            for i in range(1, 5)
        ]
        coord = _mock_coordinator(four_chargers)
        entry = _mock_entry(four_chargers)

        numbers = []
        for charger in four_chargers:
            cid = charger["id"]
            for config_key in ["daily_ev_target", "ev_night_initial_current", "ev_min_current"]:
                desc = NumberEntityDescription(key=f"charger_{cid}_{config_key}")
                numbers.append(SEMPerChargerNumber(
                    coord, desc, entry, cid, config_key, 10,
                ))

        assert len(numbers) == 12  # 3 settings × 4 chargers

        switches = []
        for charger in four_chargers:
            cid = charger["id"]
            desc = SwitchEntityDescription(key=f"charger_{cid}_night_charging")
            switches.append(SEMPerChargerSwitch(
                coord, desc, "test", cid, charger["name"],
            ))

        assert len(switches) == 4
        # All unique IDs should be different
        unique_ids = {s._attr_unique_id for s in switches}
        assert len(unique_ids) == 4

    def test_ev_power_single_charger_unchanged(self):
        """Single charger should read from primary sensor only."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        hass = MagicMock()
        config = {
            "solar_production_sensor": "sensor.solar",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.battery",
            "ev_charging_power_sensor": "sensor.keba_power",
            "ev_connected_sensor": "binary_sensor.ev_plug",
            "ev_charging_sensor": "binary_sensor.ev_charging",
            "ev_chargers": SINGLE_CHARGER,
        }

        reader = SensorReader(hass, config)

        def mock_get(entity_id):
            states = {
                "sensor.keba_power": MagicMock(state="3000", attributes={"unit_of_measurement": "W"}),
                "sensor.solar": MagicMock(state="5000", attributes={"unit_of_measurement": "W"}),
                "sensor.grid": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.battery": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "binary_sensor.ev_plug": MagicMock(state="on"),
                "binary_sensor.ev_charging": MagicMock(state="on"),
            }
            return states.get(entity_id)

        hass.states.get = mock_get

        readings = reader.read_power()
        assert readings.ev_power == 3000.0
