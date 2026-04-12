"""Scenario tests for EV daily energy fix (Layer 1-3).

Tests the three-layer fix for daily_ev_energy stuck at 0:
- Layer 1: Config key mismatch (ev_power_sensor vs ev_charging_power_sensor)
- Layer 2: Energy Dashboard fallback to config EV power sensor
- Layer 3: Hardware reconciliation with KEBA daily energy counter
"""
import pytest
from unittest.mock import Mock, MagicMock
from datetime import date

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
    SensorConfig,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
    RECONCILIATION_THRESHOLD,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.ha_energy_reader import EnergyDashboardConfig
from custom_components.solar_energy_management.utils.time_manager import TimeManager


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_hass(sensor_map: dict = None) -> Mock:
    """Create a mock hass with optional sensor values.

    sensor_map: {entity_id: (state_value, attributes_dict)}
    """
    hass = Mock()
    hass.data = {}
    hass.config = Mock()
    hass.config.config_dir = "/config"
    _map = sensor_map or {}

    def _get(entity_id):
        if entity_id in _map:
            val, attrs = _map[entity_id]
            state = Mock()
            state.state = str(val)
            state.attributes = attrs or {}
            return state
        return None

    hass.states.get = _get
    return hass


def _make_time_manager(hass) -> TimeManager:
    return TimeManager(hass)


# ===========================================================================
# Layer 1: Config key mismatch
# ===========================================================================

class TestLayer1ConfigKeyMismatch:
    """SensorReader must find EV power sensor regardless of config key name."""

    def test_legacy_key_ev_power_sensor(self):
        """Config uses ev_power_sensor (legacy / Energy Dashboard to_dict)."""
        config = {"ev_power_sensor": "sensor.keba_p30_charging_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_power_sensor == "sensor.keba_p30_charging_power"

    def test_config_flow_key_ev_charging_power_sensor(self):
        """Config uses ev_charging_power_sensor (config_flow saves this key)."""
        config = {"ev_charging_power_sensor": "sensor.keba_p30_charging_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_power_sensor == "sensor.keba_p30_charging_power"

    def test_both_keys_legacy_wins(self):
        """When both keys exist, ev_power_sensor (legacy) takes precedence."""
        config = {
            "ev_power_sensor": "sensor.legacy_ev",
            "ev_charging_power_sensor": "sensor.configflow_ev",
        }
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_power_sensor == "sensor.legacy_ev"

    def test_neither_key_is_none(self):
        """No EV power sensor configured at all → None."""
        config = {}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_power_sensor is None

    def test_legacy_read_uses_resolved_sensor(self):
        """Legacy path actually reads from the resolved ev_power_sensor."""
        sensors = {
            "sensor.keba_p30_charging_power": (7200, {"unit_of_measurement": "W"}),
            "binary_sensor.keba_p30_plug": ("on", {}),
            "binary_sensor.keba_p30_charging_state": ("on", {}),
        }
        config = {"ev_charging_power_sensor": "sensor.keba_p30_charging_power"}
        hass = _make_hass(sensors)
        reader = SensorReader(hass, config)
        readings = reader.read_power()
        assert readings.ev_power == 7200.0


# ===========================================================================
# Layer 2: Energy Dashboard fallback
# ===========================================================================

class TestLayer2EnergyDashboardFallback:
    """When Energy Dashboard has no EV power, fall back to config sensor."""

    def test_ed_has_ev_power(self):
        """Energy Dashboard provides EV power → use it."""
        sensors = {
            "sensor.ed_solar": (5000, {"unit_of_measurement": "W"}),
            "sensor.ed_ev": (3500, {"unit_of_measurement": "W"}),
            "binary_sensor.keba_p30_plug": ("off", {}),
            "binary_sensor.keba_p30_charging_state": ("off", {}),
        }
        config = {
            "ev_power_sensor": "sensor.config_ev",  # should NOT be used
        }
        hass = _make_hass(sensors)
        reader = SensorReader(hass, config)

        ed = EnergyDashboardConfig(
            solar_power="sensor.ed_solar",
            ev_power="sensor.ed_ev",
        )
        reader.set_energy_dashboard_config(ed)

        readings = reader.read_power()
        assert readings.ev_power == 3500.0

    def test_ed_missing_ev_power_falls_back_to_config(self):
        """Energy Dashboard has no EV power sensor → fallback to config."""
        sensors = {
            "sensor.ed_solar": (5000, {"unit_of_measurement": "W"}),
            "sensor.keba_p30_charging_power": (7200, {"unit_of_measurement": "W"}),
            "binary_sensor.keba_p30_plug": ("on", {}),
            "binary_sensor.keba_p30_charging_state": ("on", {}),
        }
        config = {
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        }
        hass = _make_hass(sensors)
        reader = SensorReader(hass, config)

        # Energy Dashboard has solar but no ev_power
        ed = EnergyDashboardConfig(
            solar_power="sensor.ed_solar",
            ev_power=None,  # <-- the bug scenario
        )
        reader.set_energy_dashboard_config(ed)

        readings = reader.read_power()
        assert readings.ev_power == 7200.0

    def test_ed_missing_ev_and_no_config_gives_zero(self):
        """No EV power anywhere → 0."""
        sensors = {
            "sensor.ed_solar": (5000, {"unit_of_measurement": "W"}),
            "binary_sensor.keba_p30_plug": ("off", {}),
            "binary_sensor.keba_p30_charging_state": ("off", {}),
        }
        config = {}
        hass = _make_hass(sensors)
        reader = SensorReader(hass, config)

        ed = EnergyDashboardConfig(solar_power="sensor.ed_solar", ev_power=None)
        reader.set_energy_dashboard_config(ed)

        readings = reader.read_power()
        assert readings.ev_power == 0.0


# ===========================================================================
# Layer 3: Hardware reconciliation
# ===========================================================================

class TestLayer3HardwareReconciliation:
    """EnergyCalculator reconciles integrated EV energy with KEBA counter."""

    @pytest.fixture
    def hass(self):
        return _make_hass()

    @pytest.fixture
    def time_manager(self, hass):
        return _make_time_manager(hass)

    @pytest.fixture
    def config(self):
        return {"update_interval": 10}

    @pytest.fixture
    def calc(self, config, time_manager):
        return EnergyCalculator(config, time_manager)

    def test_no_reconciliation_sensor_configured(self, calc):
        """No hardware sensor → no reconciliation, no crash."""
        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)
        assert energy.daily_ev == 0.0

    @pytest.mark.skip(reason="Reconciliation disabled - midnight/sunrise date mismatch")
    def test_reconciliation_adopts_higher_hardware(self, calc, hass):
        """Hardware counter 15.5 kWh > integrated 0.0 → adopt 15.5."""
        sensors = {"sensor.keba_p30_charging_daily": (15.5, {})}
        hw_hass = _make_hass(sensors)
        calc.set_ev_daily_energy_sensor(hw_hass, "sensor.keba_p30_charging_daily")

        # Simulate a cycle where ev_power = 0 (SEM couldn't read it)
        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)  # first call to set _last_update
        energy = calc.calculate_energy(power)

        assert energy.daily_ev == 15.5

    def test_reconciliation_ignores_small_delta(self, calc, hass):
        """Hardware 0.3 kWh > integrated 0.0 → below threshold, don't adopt."""
        sensors = {"sensor.keba_p30_charging_daily": (0.3, {})}
        hw_hass = _make_hass(sensors)
        calc.set_ev_daily_energy_sensor(hw_hass, "sensor.keba_p30_charging_daily")

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # 0.3 < threshold (0.5), should stay at integrated value (0.0)
        assert energy.daily_ev < 0.3

    def test_reconciliation_when_integrated_close_to_hardware(self, calc):
        """Integrated 14.8, hardware 15.0 → delta 0.2 < threshold, no override."""
        sensors = {"sensor.keba_p30_charging_daily": (15.0, {})}
        hw_hass = _make_hass(sensors)
        calc.set_ev_daily_energy_sensor(hw_hass, "sensor.keba_p30_charging_daily")

        # Manually seed the accumulator to simulate prior integration
        today = calc._time_manager.get_current_meter_day_sunrise_based()
        calc._daily_accumulators[f"ev_daily_sun_{today}"] = 14.8
        calc._monthly_accumulators[f"ev_daily_sun_{today.year}_{today.month}"] = 14.8

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # Delta 0.2 < 0.5 threshold → keep integrated value
        assert energy.daily_ev == 14.8

    def test_reconciliation_hardware_unavailable(self, calc):
        """Hardware sensor unavailable → no crash, keep integrated value."""
        sensors = {"sensor.keba_p30_charging_daily": ("unavailable", {})}
        hw_hass = _make_hass(sensors)
        calc.set_ev_daily_energy_sensor(hw_hass, "sensor.keba_p30_charging_daily")

        power = PowerReadings(ev_power=500.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # Should have integrated some ev energy from power, no crash
        assert energy.daily_ev >= 0.0

    def test_reconciliation_hardware_missing_entity(self, calc):
        """Hardware sensor entity doesn't exist → no crash."""
        hw_hass = _make_hass({})  # empty — entity not found
        calc.set_ev_daily_energy_sensor(hw_hass, "sensor.keba_p30_charging_daily")

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)
        assert energy.daily_ev == 0.0

    @pytest.mark.skip(reason="Reconciliation disabled - midnight/sunrise date mismatch")
    def test_reconciliation_updates_monthly_accumulator(self, calc):
        """When reconciliation fires, monthly accumulator gets the delta too."""
        sensors = {"sensor.keba_p30_charging_daily": (10.0, {})}
        hw_hass = _make_hass(sensors)
        calc.set_ev_daily_energy_sensor(hw_hass, "sensor.keba_p30_charging_daily")

        # Seed daily at 2.0, monthly at 50.0
        today = calc._time_manager.get_current_meter_day_sunrise_based()
        month_key = f"{today.year}_{today.month}"
        calc._daily_accumulators[f"ev_daily_sun_{today}"] = 2.0
        calc._monthly_accumulators[f"ev_daily_sun_{month_key}"] = 50.0

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # Daily should be hardware value
        assert energy.daily_ev == 10.0
        # Monthly should have gained the delta (10.0 - 2.0 = 8.0)
        monthly = calc._get_monthly("ev", month_key)
        assert monthly == 58.0


# ===========================================================================
# Auto-detection of KEBA daily energy sensor
# ===========================================================================

class TestKebaAutoDetection:
    """SensorReader auto-detects KEBA daily energy sensor from power sensor name."""

    def test_keba_power_sensor_auto_detects_daily(self):
        """KEBA power sensor → auto-detect sensor.keba_p30_charging_daily."""
        config = {"ev_charging_power_sensor": "sensor.keba_p30_charging_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_daily_energy_sensor == "sensor.keba_p30_charging_daily"

    def test_non_keba_power_sensor_no_auto_detect(self):
        """Non-KEBA power sensor → no auto-detection."""
        config = {"ev_charging_power_sensor": "sensor.wallbox_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_daily_energy_sensor is None

    def test_explicit_daily_sensor_overrides_auto_detect(self):
        """Explicit ev_daily_energy_sensor overrides auto-detection."""
        config = {
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
            "ev_daily_energy_sensor": "sensor.my_custom_daily",
        }
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_daily_energy_sensor == "sensor.my_custom_daily"

    def test_no_ev_sensor_no_crash(self):
        """No EV power sensor at all → no daily energy sensor, no crash."""
        config = {}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        assert reader.config.ev_daily_energy_sensor is None


# ===========================================================================
# End-to-end scenario: the original bug
# ===========================================================================

class TestEndToEndOriginalBug:
    """Reproduce the exact production bug: KEBA charges 15.5 kWh but SEM shows 0.

    Setup: Energy Dashboard configured but has no ev_power (stat_rate missing).
    Config flow saved ev_charging_power_sensor but SensorReader looked for ev_power_sensor.
    Result: ev_power always 0, daily_ev always 0, night charging thinks 10 kWh remaining.
    """

    @pytest.mark.skip(reason="Reconciliation disabled - midnight/sunrise date mismatch")
    def test_full_scenario_all_layers(self):
        """All three layers working together to fix the bug."""
        sensors = {
            # Energy Dashboard sensors (solar, grid — but NOT ev)
            "sensor.ed_solar": (5000, {"unit_of_measurement": "W"}),
            "sensor.ed_grid": (200, {"unit_of_measurement": "W"}),
            # KEBA sensors (power + daily energy counter)
            "sensor.keba_p30_charging_power": (7200, {"unit_of_measurement": "W"}),
            "sensor.keba_p30_charging_daily": (15.5, {}),
            # Binary sensors
            "binary_sensor.keba_p30_plug": ("on", {}),
            "binary_sensor.keba_p30_charging_state": ("on", {}),
        }
        hass = _make_hass(sensors)

        # Config as config_flow would save it (ev_charging_power_sensor, not ev_power_sensor)
        config = {
            "update_interval": 10,
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
        }

        # Layer 1: SensorReader resolves the key mismatch
        reader = SensorReader(hass, config)
        assert reader.config.ev_power_sensor == "sensor.keba_p30_charging_power"

        # Energy Dashboard has no ev_power
        ed = EnergyDashboardConfig(
            solar_power="sensor.ed_solar",
            grid_import_power="sensor.ed_grid",
            ev_power=None,
        )
        reader.set_energy_dashboard_config(ed)

        # Layer 2: read_power falls back to config sensor
        readings = reader.read_power()
        assert readings.ev_power == 7200.0
        assert readings.ev_connected is True

        # Layer 3: Even if power was somehow missed, hardware reconciliation catches up
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.set_ev_daily_energy_sensor(hass, reader.config.ev_daily_energy_sensor)

        # Simulate scenario where power integration somehow drifted
        # (e.g. SEM was restarted mid-charge, missed 10 kWh)
        power_zero = PowerReadings(ev_power=0.0)
        power_zero.calculate_derived()
        calc.calculate_energy(power_zero)
        energy = calc.calculate_energy(power_zero)

        # Hardware reconciliation should catch us up to 15.5
        assert energy.daily_ev == 15.5

    @pytest.mark.skip(reason="Reconciliation disabled - midnight/sunrise date mismatch")
    def test_night_charging_remaining_correct(self):
        """After fix, remaining energy for night charging is correct."""
        sensors = {
            "sensor.keba_p30_charging_daily": (15.5, {}),
        }
        hass = _make_hass(sensors)
        config = {"update_interval": 10, "daily_ev_target": 10}
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.set_ev_daily_energy_sensor(hass, "sensor.keba_p30_charging_daily")

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # daily_ev = 15.5 (from hardware), target = 10
        # remaining = max(0, 10 - 15.5) = 0  → no night charging needed
        daily_target = config["daily_ev_target"]
        remaining = max(0, daily_target - energy.daily_ev)
        assert remaining == 0.0

    @pytest.mark.skip(reason="Reconciliation disabled - midnight/sunrise date mismatch")
    def test_external_charge_via_keba_app(self):
        """User charges via KEBA app (SEM never saw ev_power) → hardware catches it."""
        sensors = {
            "sensor.keba_p30_charging_daily": (8.3, {}),
        }
        hass = _make_hass(sensors)
        config = {"update_interval": 10}
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.set_ev_daily_energy_sensor(hass, "sensor.keba_p30_charging_daily")

        # SEM never saw any ev_power (external charge)
        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        assert energy.daily_ev == 8.3

    @pytest.mark.skip(reason="Reconciliation disabled - midnight/sunrise date mismatch")
    def test_sem_restart_midcharge_catches_up(self):
        """SEM restarts mid-charge, misses 5 kWh, hardware counter has it all."""
        sensors = {
            "sensor.keba_p30_charging_daily": (12.0, {}),
        }
        hass = _make_hass(sensors)
        config = {"update_interval": 10}
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.set_ev_daily_energy_sensor(hass, "sensor.keba_p30_charging_daily")

        # SEM only integrated 7 kWh before restart
        today = tm.get_current_meter_day_sunrise_based()
        month_key = f"{today.year}_{today.month}"
        calc._daily_accumulators[f"ev_daily_sun_{today}"] = 7.0
        calc._monthly_accumulators[f"ev_daily_sun_{month_key}"] = 7.0

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # Hardware 12.0 > integrated 7.0 + 0.5 threshold → adopt 12.0
        assert energy.daily_ev == 12.0
        # Monthly should have gained the delta (5.0)
        assert calc._get_monthly("ev", month_key) == 12.0
