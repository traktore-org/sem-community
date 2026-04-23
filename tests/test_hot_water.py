"""Tests for hot water controller with Legionella prevention (#92).

Covers:
- Three entity types (water_heater, climate, switch)
- Temperature reading from entity attributes vs separate sensor
- Legionella prevention cycle (overdue detection, forced heating, hold, completion)
- Temperature safety cutoff
- Solar surplus heating
"""
import pytest
from datetime import datetime, timedelta
from homeassistant.util import dt as dt_util
from unittest.mock import MagicMock, AsyncMock, patch

from custom_components.solar_energy_management.devices.hot_water_controller import (
    HotWaterController,
    DEFAULT_LEGIONELLA_TARGET,
    DEFAULT_LEGIONELLA_INTERVAL_HOURS,
    DEFAULT_SOLAR_TARGET_TEMP,
    LEGIONELLA_HOLD_MINUTES,
)


@pytest.fixture
def hass():
    h = MagicMock()
    h.services.async_call = AsyncMock()
    h.states = MagicMock()
    return h


def _make_state(state_val, attributes=None):
    s = MagicMock()
    s.state = str(state_val)
    s.attributes = attributes or {}
    return s


# ════════════════════════════════════════════
# Entity Type Detection
# ════════════════════════════════════════════

class TestEntityTypeDetection:

    def test_switch_entity(self, hass):
        ctrl = HotWaterController(hass, entity_id="switch.boiler_relay")
        assert ctrl.entity_domain == "switch"

    def test_water_heater_entity(self, hass):
        ctrl = HotWaterController(hass, entity_id="water_heater.viessmann_dhw")
        assert ctrl.entity_domain == "water_heater"

    def test_climate_entity(self, hass):
        ctrl = HotWaterController(hass, entity_id="climate.knx_hot_water")
        assert ctrl.entity_domain == "climate"

    def test_no_entity(self, hass):
        ctrl = HotWaterController(hass, entity_id=None)
        assert ctrl.entity_domain is None


# ════════════════════════════════════════════
# Temperature Reading
# ════════════════════════════════════════════

class TestTemperatureReading:

    def test_switch_reads_separate_sensor(self, hass):
        hass.states.get = lambda eid: _make_state(52.3) if eid == "sensor.water_temp" else None
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.water_temp")
        assert ctrl.get_current_temperature() == 52.3

    def test_water_heater_reads_current_temperature_attr(self, hass):
        hass.states.get = lambda eid: _make_state("heating",
            {"current_temperature": 48.5}) if eid == "water_heater.dhw" else None
        ctrl = HotWaterController(hass, entity_id="water_heater.dhw")
        assert ctrl.get_current_temperature() == 48.5

    def test_climate_reads_current_temperature_attr(self, hass):
        hass.states.get = lambda eid: _make_state("heat",
            {"current_temperature": 45.0}) if eid == "climate.knx_dhw" else None
        ctrl = HotWaterController(hass, entity_id="climate.knx_dhw")
        assert ctrl.get_current_temperature() == 45.0

    def test_no_temp_sensor_returns_none(self, hass):
        hass.states.get = lambda eid: None
        ctrl = HotWaterController(hass, entity_id="switch.boiler")
        assert ctrl.get_current_temperature() is None

    def test_unavailable_sensor_returns_none(self, hass):
        hass.states.get = lambda eid: _make_state("unavailable")
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.water_temp")
        assert ctrl.get_current_temperature() is None

    def test_fallback_to_separate_sensor_when_attr_missing(self, hass):
        """water_heater without current_temperature attr falls back to sensor."""
        def get_state(eid):
            if eid == "water_heater.dhw":
                return _make_state("idle", {})  # No current_temperature attr
            if eid == "sensor.water_temp":
                return _make_state(47.0)
            return None
        hass.states.get = get_state
        ctrl = HotWaterController(hass, entity_id="water_heater.dhw",
                                   temperature_entity_id="sensor.water_temp")
        assert ctrl.get_current_temperature() == 47.0


# ════════════════════════════════════════════
# Temperature Safety
# ════════════════════════════════════════════

class TestTemperatureSafety:

    def test_safe_when_below_solar_target(self, hass):
        hass.states.get = lambda eid: _make_state(45.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   solar_target_temp=60.0)
        assert ctrl.is_temperature_safe() is True

    def test_unsafe_when_above_solar_target(self, hass):
        hass.states.get = lambda eid: _make_state(62.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   solar_target_temp=60.0)
        assert ctrl.is_temperature_safe() is False

    def test_safe_when_no_sensor(self, hass):
        hass.states.get = lambda eid: None
        ctrl = HotWaterController(hass, entity_id="switch.boiler")
        assert ctrl.is_temperature_safe() is True  # Rely on thermostat

    def test_legionella_cycle_allows_higher_temp(self, hass):
        """During Legionella cycle, cutoff is Legionella target, not solar target."""
        hass.states.get = lambda eid: _make_state(62.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   solar_target_temp=60.0,
                                   legionella_target_temp=65.0)
        # Normally 62 > 60 (solar target) → unsafe
        assert ctrl.is_temperature_safe() is False
        # But during Legionella cycle → 62 < 65 → safe
        ctrl._legionella_cycle_active = True
        assert ctrl.is_temperature_safe() is True

    def test_high_solar_target_allows_high_temp(self, hass):
        """Solar target 80°C allows heating above 60°C — Legionella met naturally."""
        hass.states.get = lambda eid: _make_state(65.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   solar_target_temp=80.0)
        assert ctrl.is_temperature_safe() is True  # 65 < 80

    @pytest.mark.asyncio
    async def test_activate_blocked_above_solar_target(self, hass):
        hass.states.get = lambda eid: _make_state(62.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   solar_target_temp=60.0)
        result = await ctrl.activate(3000)
        assert result == 0.0  # Blocked — above solar target


# ════════════════════════════════════════════
# Multi-Entity Activation
# ════════════════════════════════════════════

class TestMultiEntityActivation:

    @pytest.mark.asyncio
    async def test_switch_activation(self, hass):
        hass.states.get = lambda eid: _make_state(40.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp")
        result = await ctrl.activate(3000)
        assert result > 0
        hass.services.async_call.assert_called()

    @pytest.mark.asyncio
    async def test_water_heater_activation(self, hass):
        hass.states.get = lambda eid: _make_state("idle", {"current_temperature": 40.0})
        ctrl = HotWaterController(hass, entity_id="water_heater.dhw",
                                   solar_target_temp=50.0)
        result = await ctrl.activate(3000)
        assert result == ctrl.rated_power
        # Should have called set_temperature with solar target
        calls = [c for c in hass.services.async_call.call_args_list
                 if c[0][1] == "set_temperature"]
        assert len(calls) >= 1
        assert calls[0][0][2]["temperature"] == 50.0  # 3rd positional arg is service_data

    @pytest.mark.asyncio
    async def test_climate_activation(self, hass):
        hass.states.get = lambda eid: _make_state("off", {"current_temperature": 38.0})
        ctrl = HotWaterController(hass, entity_id="climate.knx_dhw",
                                   solar_target_temp=50.0)
        result = await ctrl.activate(3000)
        assert result == ctrl.rated_power
        # Should set hvac_mode to heat
        calls = [c for c in hass.services.async_call.call_args_list
                 if c[0][1] == "set_hvac_mode"]
        assert len(calls) >= 1

    @pytest.mark.asyncio
    async def test_water_heater_deactivation(self, hass):
        hass.states.get = lambda eid: _make_state("heating", {"current_temperature": 50.0})
        ctrl = HotWaterController(hass, entity_id="water_heater.dhw")
        ctrl._status.state = MagicMock()
        await ctrl.deactivate()
        assert hass.services.async_call.called

    @pytest.mark.asyncio
    async def test_climate_deactivation(self, hass):
        hass.states.get = lambda eid: _make_state("heat", {"current_temperature": 50.0})
        ctrl = HotWaterController(hass, entity_id="climate.knx_dhw")
        ctrl._status.state = MagicMock()
        await ctrl.deactivate()
        calls = [c for c in hass.services.async_call.call_args_list
                 if c[0][1] == "set_hvac_mode"]
        assert any(c[0][2].get("hvac_mode") == "off" for c in calls)


# ════════════════════════════════════════════
# Legionella Prevention
# ════════════════════════════════════════════

class TestLegionellaPrevention:

    def test_overdue_when_never_run(self, hass):
        ctrl = HotWaterController(hass, entity_id="switch.boiler")
        assert ctrl.legionella_overdue is True
        assert ctrl.hours_since_legionella == 999.0

    def test_not_overdue_when_recently_run(self, hass):
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   legionella_interval_hours=72)
        ctrl._last_legionella_time = datetime.now(tz=dt_util.UTC)
        # hours_since will be ~0
        assert ctrl.legionella_overdue is False

    def test_overdue_after_interval(self, hass):
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   legionella_interval_hours=72)
        ctrl._last_legionella_time = datetime.now(tz=dt_util.UTC) - timedelta(hours=80)
        assert ctrl.legionella_overdue is True

    def test_hold_duration_by_temperature(self, hass):
        ctrl60 = HotWaterController(hass, legionella_target_temp=60)
        ctrl65 = HotWaterController(hass, legionella_target_temp=65)
        ctrl70 = HotWaterController(hass, legionella_target_temp=70)
        ctrl80 = HotWaterController(hass, legionella_target_temp=80)
        assert ctrl60.legionella_hold_minutes == 30
        assert ctrl65.legionella_hold_minutes == 20
        assert ctrl70.legionella_hold_minutes == 5
        assert ctrl80.legionella_hold_minutes == 3

    def test_target_enforces_minimum_60(self, hass):
        """User cannot set Legionella target below 60°C."""
        ctrl = HotWaterController(hass, legionella_target_temp=40)
        assert ctrl.legionella_target_temp == 60.0

    @pytest.mark.asyncio
    async def test_natural_achievement_records_timestamp(self, hass):
        """If solar heats to ≥60°C naturally, record it as a Legionella cycle."""
        hass.states.get = lambda eid: _make_state(62.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp")
        result = await ctrl.check_legionella_cycle()
        assert result is None  # No forced action needed
        assert ctrl._last_legionella_time is not None
        assert ctrl.legionella_overdue is False

    @pytest.mark.asyncio
    async def test_forced_cycle_starts_when_overdue(self, hass):
        """Force heating when overdue and temp below target."""
        hass.states.get = lambda eid: _make_state(42.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   legionella_interval_hours=72)
        # Never run → overdue
        result = await ctrl.check_legionella_cycle()
        assert result == "legionella_started"
        assert ctrl._legionella_cycle_active is True
        assert hass.services.async_call.called

    @pytest.mark.asyncio
    async def test_no_forced_cycle_without_temp_sensor(self, hass):
        """Skip forced cycle if no temperature sensor available."""
        hass.states.get = lambda eid: None
        ctrl = HotWaterController(hass, entity_id="switch.boiler")
        result = await ctrl.check_legionella_cycle()
        assert result == "legionella_no_sensor"
        assert ctrl._legionella_cycle_active is False

    @pytest.mark.asyncio
    async def test_cycle_completes_after_hold(self, hass):
        """Cycle completes after hold duration at target temperature."""
        hass.states.get = lambda eid: _make_state(66.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   legionella_target_temp=65)
        ctrl._legionella_cycle_active = True
        # Simulate hold start was 25 minutes ago (>20 min hold for 65°C)
        ctrl._legionella_hold_start = datetime.now(tz=dt_util.UTC) - timedelta(minutes=25)

        result = await ctrl.check_legionella_cycle()
        assert result == "legionella_complete"
        assert ctrl._legionella_cycle_active is False
        assert ctrl._last_legionella_time is not None

    @pytest.mark.asyncio
    async def test_cycle_continues_during_hold(self, hass):
        """Cycle continues if hold duration not yet reached."""
        hass.states.get = lambda eid: _make_state(66.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   legionella_target_temp=65)
        ctrl._legionella_cycle_active = True
        # Hold started 5 minutes ago (<20 min needed)
        ctrl._legionella_hold_start = datetime.now(tz=dt_util.UTC) - timedelta(minutes=5)

        result = await ctrl.check_legionella_cycle()
        # Should still be holding (temp at target but not long enough)
        assert ctrl._legionella_cycle_active is True

    @pytest.mark.asyncio
    async def test_cycle_still_heating(self, hass):
        """Cycle returns heating status while below target."""
        hass.states.get = lambda eid: _make_state(50.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   legionella_target_temp=65)
        ctrl._legionella_cycle_active = True

        result = await ctrl.check_legionella_cycle()
        assert result == "legionella_heating"
        assert ctrl._legionella_hold_start is None  # Not yet at target

    def test_record_legionella_cycle(self, hass):
        """Manual recording (e.g. from storage restore)."""
        ctrl = HotWaterController(hass, entity_id="switch.boiler")
        ts = datetime(2026, 4, 20, 10, 0, 0)
        ctrl.record_legionella_cycle(ts)
        assert ctrl._last_legionella_time == ts


# ════════════════════════════════════════════
# to_dict / Serialization
# ════════════════════════════════════════════

class TestSerialization:

    def test_to_dict_includes_legionella_data(self, hass):
        hass.states.get = lambda eid: _make_state(50.0)
        ctrl = HotWaterController(hass, entity_id="switch.boiler",
                                   temperature_entity_id="sensor.temp",
                                   legionella_target_temp=65,
                                   legionella_interval_hours=72)
        d = ctrl.to_dict()
        assert "legionella_target_temp" in d
        assert d["legionella_target_temp"] == 65
        assert "legionella_overdue" in d
        assert "hours_since_legionella" in d
        assert "entity_domain" in d
        assert d["entity_domain"] == "switch"
        assert "solar_target_temp" in d

    def test_to_dict_water_heater(self, hass):
        ctrl = HotWaterController(hass, entity_id="water_heater.dhw")
        d = ctrl.to_dict()
        assert d["entity_domain"] == "water_heater"
