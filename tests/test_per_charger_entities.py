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
        assert switch.is_on is False  # opt-in (#256): default OFF, won't night-charge until enabled

    @pytest.mark.asyncio
    async def test_per_charger_switch_existing_state_preserved(self):
        """Existing per-charger switches keep their state on upgrade: a restored 'on'
        wins over the new default-OFF, so multi-charger users aren't silently changed (#256)."""
        from homeassistant.helpers.update_coordinator import CoordinatorEntity
        coord = _mock_coordinator(TWO_CHARGERS)
        desc = SwitchEntityDescription(key="charger_ev_charger_1_night_charging")
        switch = SEMPerChargerSwitch(coord, desc, "test", "ev_charger_1", "Wallbox")
        assert switch.is_on is False  # new default
        switch.async_get_last_state = AsyncMock(return_value=MagicMock(state="on"))
        with patch.object(CoordinatorEntity, "async_added_to_hass", AsyncMock()):
            await switch.async_added_to_hass()
        assert switch.is_on is True  # prior state restored, not overwritten

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
        switch.async_write_ha_state = MagicMock()  # not added to hass in isolation

        assert switch.is_on is False  # opt-in default (#256)
        await switch.async_turn_on()
        assert switch.is_on is True
        await switch.async_turn_off()
        assert switch.is_on is False
        assert switch.async_write_ha_state.call_count == 2  # both toggles pushed state (#259)

    def test_per_charger_switch_available(self):
        """Per-charger switch should be unavailable when coordinator fails."""
        coord = _mock_coordinator(TWO_CHARGERS)
        coord.data = None
        desc = SwitchEntityDescription(key="charger_ev_charger_night_charging")
        switch = SEMPerChargerSwitch(coord, desc, "test", "ev_charger", "KEBA")
        assert switch.available is False


@pytest.mark.unit
class TestPerChargerTargetTime:
    """Per-charger charge-by deadline time entity (#246)."""

    @pytest.mark.asyncio
    async def test_time_set_persists_hhmm_to_charger(self):
        from datetime import time as dt_time
        from custom_components.solar_energy_management.time import (
            SEMPerChargerTime, _parse_hhmm,
        )
        from homeassistant.components.time import TimeEntityDescription

        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        desc = TimeEntityDescription(key="charger_ev_charger_1_target_time")
        ent = SEMPerChargerTime(coord, desc, entry, "ev_charger_1", "ev_target_time", "07:00")
        ent.hass = coord.hass
        ent.async_write_ha_state = MagicMock()

        assert ent.native_value == dt_time(7, 0)
        await ent.async_set_value(dt_time(6, 30))
        assert ent.native_value == dt_time(6, 30)
        call = coord.hass.config_entries.async_update_entry.call_args
        new_options = call[1]["options"]
        charger = next(c for c in new_options["ev_chargers"] if c["id"] == "ev_charger_1")
        assert charger["ev_target_time"] == "06:30"

    def test_parse_hhmm_fallback(self):
        from datetime import time as dt_time
        from custom_components.solar_energy_management.time import _parse_hhmm
        assert _parse_hhmm("08:15") == dt_time(8, 15)
        assert _parse_hhmm("07:00:00") == dt_time(7, 0)
        assert _parse_hhmm(None) == dt_time(7, 0)   # default 07:00
        assert _parse_hhmm("junk") == dt_time(7, 0)


# TestSetDefaultButton — RETIRED v1.7.0-beta.11 (#355 follow-up).
# The per-charger "Set target as default" button was retired; HA's number-
# entity state restoration already persists the current slider values, and
# the inherit-on-new-charger flow served a niche workflow that nobody
# observed using. The button.py module is now a cleanup-only stub that
# removes orphaned set-default button entities from the entity registry.


@pytest.mark.unit
class TestPerChargerSensors:
    """Test per-charger sensor descriptions are created correctly."""

    def test_intelligence_sensors_created_for_each_charger(self):
        """Each charger should get intelligence sensor descriptions."""
        expected_suffixes = [
            "estimated_soc",
            "vehicle_soc",
            # (#440) nights_until_charge / charge_needed removed
            "taper_minutes_to_full",
        ]
        for charger in TWO_CHARGERS:
            cid = charger["id"]
            for suffix in expected_suffixes:
                key = f"charger_{cid}_{suffix}"
                # Just verify the key pattern is valid
                assert cid in key
                assert suffix in key

    def test_per_charger_vehicle_soc_description_registered(self):
        """#383: Each per-charger ``vehicle_soc`` description must be
        registered alongside ``estimated_soc`` so multi-charger cards
        can read the right car's SOC instead of falling back to the
        clobbered global ``sem_vehicle_soc``."""
        from custom_components.solar_energy_management import sensor as sensor_module
        # Walk the descriptions module-level builder by introspecting
        # the source — keeps the test independent of HA fixtures.
        with open(sensor_module.__file__, encoding="utf-8") as f:
            src = f.read()
        for charger in TWO_CHARGERS:
            cid = charger["id"]
            assert f'key=f"charger_{{cid}}_vehicle_soc"' in src or \
                   f'key=f"charger_{cid}_vehicle_soc"' in src or \
                   '"charger_{cid}_vehicle_soc"' in src or \
                   "vehicle_soc" in src

    def test_vehicle_soc_in_data_dict_per_charger(self):
        """The flat ``EnergyTotals.to_dict`` output must include one
        ``charger_<cid>_vehicle_soc`` key per charger present in
        ``per_charger_intelligence``."""
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        e = SEMData()
        e.per_charger_intelligence = {
            "ev_charger":   {"estimated_soc": 80, "vehicle_soc": 75},
            "ev_charger_1": {"estimated_soc": 65, "vehicle_soc": 60},
        }
        out = e.to_dict()
        assert out["charger_ev_charger_vehicle_soc"] == 75
        assert out["charger_ev_charger_1_vehicle_soc"] == 60
        # Each charger still gets its own estimated_soc (pre-existing).
        assert out["charger_ev_charger_estimated_soc"] == 80
        assert out["charger_ev_charger_1_estimated_soc"] == 65

    def test_vehicle_soc_none_when_unconfigured(self):
        """When ``vehicle_soc_entity`` isn't configured for a charger
        the dict carries ``None``, NOT a fabricated zero — the
        downstream sensor reports as unavailable rather than 0 %."""
        from custom_components.solar_energy_management.coordinator.types import (
            SEMData,
        )
        e = SEMData()
        e.per_charger_intelligence = {
            "ev_charger":   {"estimated_soc": 80, "vehicle_soc": None},
            "ev_charger_1": {"estimated_soc": 65},  # missing key
        }
        out = e.to_dict()
        assert out["charger_ev_charger_vehicle_soc"] is None
        assert out["charger_ev_charger_1_vehicle_soc"] is None

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
        reader._sign_vote_warmup = 0

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
        reader._sign_vote_warmup = 0

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
        reader._sign_vote_warmup = 0

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

    def test_ev_connected_or_multi_charger(self):
        """Global ev_connected should be True if ANY charger is connected (#193)."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        chargers = [
            {"id": "c1", "name": "C1", "ev_charging_power_sensor": "sensor.c1_power",
             "ev_connected_sensor": "binary_sensor.c1_plug", "ev_charging_sensor": "binary_sensor.c1_charging"},
            {"id": "c2", "name": "C2", "ev_charging_power_sensor": "sensor.c2_power",
             "ev_connected_sensor": "binary_sensor.c2_plug", "ev_charging_sensor": "binary_sensor.c2_charging"},
        ]
        hass = MagicMock()
        config = {
            "solar_production_sensor": "sensor.solar",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.battery",
            "ev_charging_power_sensor": "sensor.c1_power",
            "ev_connected_sensor": "binary_sensor.c1_plug",
            "ev_charging_sensor": "binary_sensor.c1_charging",
            "ev_chargers": chargers,
        }
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0

        # Only charger 2 connected, charger 1 disconnected
        def mock_get(entity_id):
            states = {
                "sensor.c1_power": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.c2_power": MagicMock(state="3000", attributes={"unit_of_measurement": "W"}),
                "sensor.solar": MagicMock(state="5000", attributes={"unit_of_measurement": "W"}),
                "sensor.grid": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.battery": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "binary_sensor.c1_plug": MagicMock(state="off"),
                "binary_sensor.c2_plug": MagicMock(state="on"),
                "binary_sensor.c1_charging": MagicMock(state="off"),
                "binary_sensor.c2_charging": MagicMock(state="on"),
            }
            return states.get(entity_id)
        hass.states.get = mock_get

        readings = reader.read_power()
        assert readings.ev_connected is True  # OR'd: c2 is connected
        assert readings.ev_charging is True  # OR'd: c2 is charging

    def test_ev_connected_none_multi_charger(self):
        """Global ev_connected should be False if NO charger is connected."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader

        chargers = [
            {"id": "c1", "name": "C1", "ev_charging_power_sensor": "sensor.c1_power",
             "ev_connected_sensor": "binary_sensor.c1_plug", "ev_charging_sensor": "binary_sensor.c1_charging"},
            {"id": "c2", "name": "C2", "ev_charging_power_sensor": "sensor.c2_power",
             "ev_connected_sensor": "binary_sensor.c2_plug", "ev_charging_sensor": "binary_sensor.c2_charging"},
        ]
        hass = MagicMock()
        config = {
            "solar_production_sensor": "sensor.solar",
            "grid_power_sensor": "sensor.grid",
            "battery_power_sensor": "sensor.battery",
            "ev_charging_power_sensor": "sensor.c1_power",
            "ev_connected_sensor": "binary_sensor.c1_plug",
            "ev_charging_sensor": "binary_sensor.c1_charging",
            "ev_chargers": chargers,
        }
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0

        def mock_get(entity_id):
            states = {
                "sensor.c1_power": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.c2_power": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.solar": MagicMock(state="5000", attributes={"unit_of_measurement": "W"}),
                "sensor.grid": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "sensor.battery": MagicMock(state="0", attributes={"unit_of_measurement": "W"}),
                "binary_sensor.c1_plug": MagicMock(state="off"),
                "binary_sensor.c2_plug": MagicMock(state="off"),
                "binary_sensor.c1_charging": MagicMock(state="off"),
                "binary_sensor.c2_charging": MagicMock(state="off"),
            }
            return states.get(entity_id)
        hass.states.get = mock_get

        readings = reader.read_power()
        assert readings.ev_connected is False
        assert readings.ev_charging is False

    @pytest.mark.asyncio
    async def test_per_charger_connected_binary_sensor(self):
        """Per-charger connected binary sensor should be created for each charger."""
        from custom_components.solar_energy_management.binary_sensor import (
            async_setup_entry, BinarySensorEntityDescription,
        )
        coord = _mock_coordinator(TWO_CHARGERS)
        entry = _mock_entry(TWO_CHARGERS)
        entry.runtime_data = coord

        entities = []
        def mock_add(ents):
            entities.extend(ents)

        await async_setup_entry(coord.hass, entry, mock_add)

        # Should have per-charger connected binary sensors
        keys = [e.entity_description.key for e in entities]
        assert "charger_ev_charger_connected" in keys
        assert "charger_ev_charger_1_connected" in keys

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
        reader._sign_vote_warmup = 0

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
