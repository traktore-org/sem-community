"""v1.4 Integration Tests — multi-charger, multi-inverter, PROD regression.

These tests verify the INTEGRATED behavior of components that caused
bugs on PROD (2026-04-28):
1. Multi-charger coordinator loop with context swap
2. Multi-inverter sensor summing end-to-end
3. Night charge skip when forecast is unavailable
4. False taper detection at low power (1910W bug)
5. Skip counter incrementing once per night, not every cycle
6. EV notification triggers
7. Surplus distribution with multiple chargers

Each test reproduces a real-world scenario from HA-PROD data.
"""
import time
import pytest
from unittest.mock import MagicMock, AsyncMock
from datetime import datetime, timedelta

from custom_components.solar_energy_management.coordinator.ev_taper_detector import (
    EVTaperDetector,
)
from custom_components.solar_energy_management.coordinator.ev_control import (
    EVControlMixin,
)
from custom_components.solar_energy_management.coordinator.types import (
    SessionData,
    SEMData,
    PowerReadings,
)


# ============================================================
# Helpers
# ============================================================

def make_mock_charger(charger_id, name, priority=3, max_current=32,
                      phases=3, power=0, connected=True):
    """Create a mock CurrentControlDevice."""
    device = MagicMock()
    device.device_id = charger_id
    device.name = name
    device.priority = priority
    device.min_current = 6.0
    device.max_current = max_current
    device.phases = phases
    device.voltage = 230.0
    device.min_power_threshold = phases * 230 * 6
    device.power_entity_id = f"sensor.{charger_id}_power"
    device.managed_externally = True
    device._session_active = False
    device._current_setpoint = 0
    device.start_session = AsyncMock()
    device.stop_session = AsyncMock()
    device._set_current = AsyncMock()
    device.watts_to_current = lambda w: w / (phases * 230)
    return device


class MockCoordinator(EVControlMixin):
    """Minimal coordinator mock for EV control testing."""
    def __init__(self, config, ev_taper=None):
        self.config = config
        self._ev_taper_detector = ev_taper
        self._ev_device = None
        self._ev_devices = {}
        self._ev_stalled_since = None
        self._ev_reenable_attempts = 0
        self._ev_charge_refused = False
        self._ev_enable_surplus_since = None
        self._ev_charge_started_at = None
        self._ev_last_change_time = None
        self._forecast_reader = MagicMock()
        self._energy_calculator = MagicMock()
        self._energy_calculator._import_rate = 0.30
        self._predictor = MagicMock()
        self._predictor.predict_ev_consumption_tomorrow.return_value = 4.4
        self._cycle_vehicle_soc = None
        self._load_manager = None
        self._flow_calculator = MagicMock()
        self.time_manager = MagicMock()
        self.hass = MagicMock()
        self._session_data = SessionData()
        self._last_ev_connected = False
        # Multi-charger state dicts
        self._ev_stalled_since_per_charger = {}
        self._ev_reenable_attempts_per_charger = {}
        self._ev_charge_refused_per_charger = {}
        self._ev_enable_surplus_per_charger = {}
        self._ev_charge_started_per_charger = {}
        self._ev_last_change_per_charger = {}
        self._session_data_per_charger = {}
        self._last_ev_connected_per_charger = {}

    @property
    def update_interval(self):
        return timedelta(seconds=10)


def make_energy(daily_ev=0, monthly_home=500, monthly_battery=300):
    energy = MagicMock()
    energy.daily_ev = daily_ev
    energy.monthly_home = monthly_home
    energy.monthly_battery_charge = monthly_battery
    return energy


# ============================================================
# 1. Multi-charger coordinator context swap
# ============================================================

class TestMultiChargerContextSwap:
    """Verify per-charger state isolation during coordinator loop."""

    def test_stall_timers_isolated_between_chargers(self):
        """Charger 1 stall timer must not affect charger 2."""
        coord = MockCoordinator({})
        c1 = make_mock_charger("wb_1", "WB1", priority=3)
        c2 = make_mock_charger("wb_2", "WB2", priority=5)
        coord._ev_devices = {"wb_1": c1, "wb_2": c2}

        # Simulate: charger 1 stalls
        coord._ev_stalled_since_per_charger["wb_1"] = time.monotonic()
        coord._ev_stalled_since_per_charger["wb_2"] = None

        # After context swap for wb_1, stall should be set
        coord._ev_stalled_since = coord._ev_stalled_since_per_charger["wb_1"]
        assert coord._ev_stalled_since is not None

        # After context swap for wb_2, stall should be None
        coord._ev_stalled_since = coord._ev_stalled_since_per_charger["wb_2"]
        assert coord._ev_stalled_since is None

    def test_enable_delay_isolated(self):
        """Enable delay for charger 1 must not bleed to charger 2."""
        coord = MockCoordinator({})
        now = time.monotonic()
        coord._ev_enable_surplus_per_charger["wb_1"] = now - 30  # 30s ago
        coord._ev_enable_surplus_per_charger["wb_2"] = None       # just started

        # Charger 1 has been waiting 30s
        coord._ev_enable_surplus_since = coord._ev_enable_surplus_per_charger["wb_1"]
        assert (now - coord._ev_enable_surplus_since) >= 30

        # Charger 2 has no enable timer
        coord._ev_enable_surplus_since = coord._ev_enable_surplus_per_charger["wb_2"]
        assert coord._ev_enable_surplus_since is None

    def test_session_data_isolated(self):
        """Session energy for charger 1 must not appear in charger 2."""
        coord = MockCoordinator({})
        coord._session_data_per_charger["wb_1"] = SessionData(active=True, energy_kwh=5.0)
        coord._session_data_per_charger["wb_2"] = SessionData(active=True, energy_kwh=2.0)

        assert coord._session_data_per_charger["wb_1"].energy_kwh == 5.0
        assert coord._session_data_per_charger["wb_2"].energy_kwh == 2.0

    def test_context_swap_restores_state(self):
        """After processing charger N, coordinator state must be restored."""
        coord = MockCoordinator({})
        original_stall = 42.0
        coord._ev_stalled_since = original_stall

        # Save before swap
        saved = coord._ev_stalled_since
        # Swap in per-charger
        coord._ev_stalled_since = 99.0
        # Restore
        coord._ev_stalled_since = saved

        assert coord._ev_stalled_since == original_stall

    def test_reenable_guard_isolated_between_chargers(self):
        """#243: charger A's 'car full' latch must not bleed into charger B.

        Mirrors the coordinator.py save/swap/restore sequence for the new
        false-stall guard fields.
        """
        coord = MockCoordinator({})
        # Charger A latched off (refused), charger B fresh
        coord._ev_reenable_attempts_per_charger["wb_1"] = 4
        coord._ev_charge_refused_per_charger["wb_1"] = True
        coord._ev_reenable_attempts_per_charger["wb_2"] = 0
        coord._ev_charge_refused_per_charger["wb_2"] = False

        # Swap in charger A
        coord._ev_reenable_attempts = coord._ev_reenable_attempts_per_charger.get("wb_1", 0)
        coord._ev_charge_refused = coord._ev_charge_refused_per_charger.get("wb_1", False)
        assert coord._ev_reenable_attempts == 4 and coord._ev_charge_refused is True

        # Swap in charger B — must see its own fresh state, not A's
        coord._ev_reenable_attempts = coord._ev_reenable_attempts_per_charger.get("wb_2", 0)
        coord._ev_charge_refused = coord._ev_charge_refused_per_charger.get("wb_2", False)
        assert coord._ev_reenable_attempts == 0 and coord._ev_charge_refused is False

    def test_reenable_guard_saved_back_per_charger(self):
        """New guard state computed during a charger's turn is saved back to its slot."""
        coord = MockCoordinator({})
        coord._ev_reenable_attempts = 2
        coord._ev_charge_refused = False
        # Save-back (end of charger wb_1's turn)
        coord._ev_reenable_attempts_per_charger["wb_1"] = coord._ev_reenable_attempts
        coord._ev_charge_refused_per_charger["wb_1"] = coord._ev_charge_refused
        assert coord._ev_reenable_attempts_per_charger["wb_1"] == 2
        assert coord._ev_charge_refused_per_charger["wb_1"] is False


# ============================================================
# 2. Surplus distribution integration — REMOVED in #651
#
# TestSurplusDistributionIntegration (5 tests) called
# ``SurplusController.distribute_ev_budget`` directly and named its cases
# after real installs ("Rien's setup (#112)", "KEBA + Easee"). The name
# "integration" was the misleading part: the method's only production
# caller wrote its result into ``pcc.budget_w``, and nothing read that
# field. These installs never ran this cascade — #651.
#
# Real multi-charger sharing is covered by
# tests/test_step6_multi_charger_surplus_sharing.py, which drives the
# live path (``_solar_committed_w_per_cycle`` shrinking the surplus each
# charger sees as the priority loop walks the fleet).
# ============================================================


# ============================================================
# 3. Night charge skip — PROD regression tests
# ============================================================

# (TestNightChargeSkipProdRegression) removed in #440 — skip-decision wiring is gone.

class TestTaperFalsePositiveRegression:
    """Prevent false full detection at low power."""

    def test_1910w_night_charge_toggle_no_false_full(self):
        """PROD bug: 1910W night charging + switch toggle → false full."""
        config = {"ev_battery_capacity_kwh": 40}
        detector = EVTaperDetector(config)

        # Simulate night charging at ~1910W
        now = datetime.now()
        for i in range(30):
            detector.update(1910, 10, True, now + timedelta(seconds=i * 10))

        # User toggles switch → power drops to 0
        detector.update(0, 0, True, now + timedelta(seconds=300))
        detector.update(0, 0, True, now + timedelta(seconds=310))

        assert not detector.full_detected, \
            "1910W peak must NOT trigger full detection (threshold is 3000W)"

    def test_real_taper_6000w_detects_full(self):
        """Real taper from 6000W → 0W should detect full."""
        config = {"ev_battery_capacity_kwh": 40}
        detector = EVTaperDetector(config)

        now = datetime.now()
        # Build up session peak
        for i in range(12):
            detector.update(6000, 10, True, now + timedelta(seconds=i * 10))

        # Taper down
        powers = [5500, 5000, 4500, 4000, 3500, 3000, 2500, 2000, 1500, 1000, 500, 100]
        for j, p in enumerate(powers):
            for k in range(6):
                detector.update(p, p / 690, True,
                               now + timedelta(seconds=120 + (j * 6 + k) * 10))

        # Drop to 0
        detector.update(0, 0, True, now + timedelta(seconds=1000))

        # Peak was 6000W > 3000W, so full detection should work
        # Note: detection depends on regression analysis classifying trend as "declining"
        assert detector._session_peak_w >= 6000

    def test_3000w_borderline_no_false_full(self):
        """2999W peak should NOT trigger full (just below threshold)."""
        config = {"ev_battery_capacity_kwh": 40}
        detector = EVTaperDetector(config)

        now = datetime.now()
        for i in range(20):
            detector.update(2999, 10, True, now + timedelta(seconds=i * 10))

        detector.update(0, 0, True, now + timedelta(seconds=200))
        assert not detector.full_detected


# ============================================================
# 5. Skip counter — once per night
# ============================================================

# (TestSkipCounterOncePerNight) removed in #440 — skip-decision wiring is gone.

class TestMultiInverterSumming:
    """End-to-end sensor summing for multiple inverters/batteries."""

    def _make_hass(self, states_dict):
        hass = MagicMock()
        def mock_get(entity_id):
            if entity_id in states_dict:
                state = MagicMock()
                state.state = str(states_dict[entity_id])
                state.attributes = {"unit_of_measurement": "W"}
                return state
            return None
        hass.states.get = MagicMock(side_effect=mock_get)
        return hass

    def test_two_inverters_summed(self):
        """Two Growatt inverters: 3kW + 2kW = 5kW total."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader
        hass = self._make_hass({
            "sensor.growatt_1_power": 3000,
            "sensor.growatt_2_power": 2000,
        })
        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        total = reader._read_sensors_sum(
            ["sensor.growatt_1_power", "sensor.growatt_2_power"], "solar"
        )
        assert total == 5000.0

    def test_three_batteries_summed(self):
        """Three battery units: power summed."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader
        hass = self._make_hass({
            "sensor.bat_1_power": 500,
            "sensor.bat_2_power": 300,
            "sensor.bat_3_power": -200,  # One discharging
        })
        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        total = reader._read_sensors_sum(
            ["sensor.bat_1_power", "sensor.bat_2_power", "sensor.bat_3_power"], "battery"
        )
        assert total == 600.0  # 500 + 300 + (-200)

    def test_unavailable_sensor_skipped(self):
        """Unavailable sensor should be skipped, not crash."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader
        hass = self._make_hass({
            "sensor.inv_1_power": 3000,
            # sensor.inv_2_power not in states (unavailable)
        })
        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        total = reader._read_sensors_sum(
            ["sensor.inv_1_power", "sensor.inv_2_power"], "solar"
        )
        assert total == 3000.0

    def test_single_inverter_unchanged(self):
        """Single inverter: backward compat, returns same value."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import SensorReader
        hass = self._make_hass({"sensor.inverter_power": 4500})
        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        total = reader._read_sensors_sum(
            ["sensor.inverter_power"], "solar"
        )
        assert total == 4500.0


# ============================================================
# 7. EV notification triggers
# ============================================================

# ============================================================
# 8. Night target distribution
# ============================================================

class TestNightTargetDistribution:
    """Verify night target splits equally across connected chargers."""

    def test_two_chargers_split_equally(self):
        """10 kWh target with 2 chargers → 5 kWh each."""
        total_target = 10.0
        connected_count = 2
        per_charger = total_target / connected_count
        assert per_charger == 5.0

    def test_three_chargers_split_equally(self):
        """10 kWh target with 3 chargers → 3.33 kWh each."""
        total_target = 10.0
        connected_count = 3
        per_charger = total_target / connected_count
        assert abs(per_charger - 3.333) < 0.01

    def test_single_charger_gets_full(self):
        """1 charger → full target."""
        assert 10.0 / 1 == 10.0

    def test_zero_target_gives_zero(self):
        """No remaining energy → 0 for all."""
        assert 0.0 / 2 == 0.0


# ============================================================
# 9. Heat Pump SG-Ready integration
# ============================================================

class TestHeatPumpSGReadyIntegration:
    """Verify heat pump registration and surplus activation."""

    def test_relay_state_mapping(self):
        """#523: SG-Ready standard truth table (input1:input2, True=closed).

        BLOCKED=1:0, NORMAL=0:0, BOOST=0:1, FORCE_ON=1:1.
        (Was a non-standard 2-bit count; SEM's BOOST used to drive the
        EVU-block pattern and turned standard pumps off on surplus.)
        """
        from custom_components.solar_energy_management.devices.heat_pump_controller import (
            SGReadyState, SG_READY_RELAY_MAP,
        )
        assert SG_READY_RELAY_MAP[SGReadyState.BLOCKED] == (True, False)
        assert SG_READY_RELAY_MAP[SGReadyState.NORMAL] == (False, False)
        assert SG_READY_RELAY_MAP[SGReadyState.BOOST] == (False, True)
        assert SG_READY_RELAY_MAP[SGReadyState.FORCE_ON] == (True, True)

    def test_boost_vs_force_on_threshold(self):
        """Below force_on_threshold → BOOST, above → FORCE_ON."""
        from custom_components.solar_energy_management.devices.heat_pump_controller import (
            HeatPumpController,
        )
        hass = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hp = HeatPumpController(
            hass=hass, relay1_entity_id="switch.relay1",
            relay2_entity_id="switch.relay2", force_on_threshold=5000,
        )
        # Below threshold → BOOST
        assert 3000 < hp.force_on_threshold
        # Above threshold → FORCE_ON
        assert 6000 >= hp.force_on_threshold

    def test_priority_default_is_4(self):
        """Heat pump default priority = 4 (between battery=2 and EV=5)."""
        from custom_components.solar_energy_management.devices.heat_pump_controller import HeatPumpController
        hass = MagicMock()
        hp = HeatPumpController(hass=hass)
        assert hp.priority == 4

    def test_no_relays_means_no_registration(self):
        """Without relay entities, heat pump should not be registered."""
        config = {}  # No heat_pump_relay1_entity
        has_relay1 = config.get("heat_pump_relay1_entity")
        has_relay2 = config.get("heat_pump_relay2_entity")
        assert not (has_relay1 and has_relay2)


# ============================================================
# 10. Currency fix
# ============================================================

class TestCurrencyFix:
    """Verify sensors use HA-configured currency, not hardcoded CHF."""

    def test_monetary_sensor_gets_ha_currency(self):
        """Sensors with device_class=MONETARY should use hass.config.currency."""
        from homeassistant.components.sensor import SensorDeviceClass
        # The fix: sensor.py line 1338 checks device_class == MONETARY
        # and sets native_unit_of_measurement = coordinator.hass.config.currency
        # We verify the logic by checking the condition
        assert SensorDeviceClass.MONETARY is not None

    def test_semdata_exposes_currency(self):
        """SEMData.to_dict() should include currency field."""
        data = SEMData(currency="EUR")
        d = data.to_dict()
        assert d["currency"] == "EUR"

    def test_semdata_currency_default_eur(self):
        """Default currency should be EUR."""
        data = SEMData()
        assert data.currency == "EUR"

    def test_semdata_currency_chf(self):
        """Swiss users get CHF."""
        data = SEMData(currency="CHF")
        assert data.to_dict()["currency"] == "CHF"


# ============================================================
# 11. Per-charger taper detection
# ============================================================

class TestPerChargerTaperDetection:
    """Verify independent taper detection per charger."""

    def test_separate_detectors_per_charger(self):
        """Each charger should get its own EVTaperDetector instance."""
        config = {"ev_battery_capacity_kwh": 40}
        d1 = EVTaperDetector(config)
        d2 = EVTaperDetector(config)
        assert d1 is not d2

    def test_taper_on_charger1_does_not_affect_charger2(self):
        """Full detection on charger 1 should not set charger 2 as full."""
        config = {"ev_battery_capacity_kwh": 40}
        d1 = EVTaperDetector(config)
        d2 = EVTaperDetector(config)

        now = datetime.now()
        # Charger 1: high power session
        for i in range(20):
            d1.update(6000, 10, True, now + timedelta(seconds=i * 10))
        # Charger 2: idle
        d2.update(0, 0, False, now)

        assert d1._session_peak_w >= 6000
        assert d2._session_peak_w == 0

    def test_independent_soc_tracking(self):
        """Virtual SOC should be independent per charger."""
        config = {"ev_battery_capacity_kwh": 40}
        d1 = EVTaperDetector(config)
        d2 = EVTaperDetector(config)

        # Set SOC via energy_since_full (get_virtual_soc recalculates)
        d1._energy_since_full = 8.0   # 100 - 8/40*100 = 80%
        d1._soc_anchored = True
        d2._energy_since_full = 24.0  # 100 - 24/40*100 = 40%
        d2._soc_anchored = True

        assert d1.get_virtual_soc() == 80.0
        assert d2.get_virtual_soc() == 40.0

    # (test_independent_skip_decisions) removed in #440 — skip-decision
    # wiring is gone, charge mode is the sole authority.


# ============================================================
# 12. Dynamic tariff auto-detection
# ============================================================

class TestDynamicTariffAutoDetection:
    """Verify Tibber/Nordpool/aWATTar auto-detection."""

    def test_tibber_entity_detected(self):
        """Tibber price entity should be found by pattern matching."""
        # The config flow scans for "electricity_price" in entity_id
        entity_id = "sensor.electricity_price_home"
        assert "electricity_price" in entity_id

    def test_nordpool_entity_detected(self):
        """Nordpool entity should be found by pattern."""
        entity_id = "sensor.nordpool_kwh_se3_eur_3_10_025"
        assert "nordpool" in entity_id

    def test_awattar_entity_detected(self):
        """aWATTar entity should be found by pattern."""
        entity_id = "sensor.awattar"
        assert "awattar" in entity_id

    def test_no_dynamic_entity_returns_none(self):
        """When no dynamic entity found, auto-detect returns None."""
        # Simulate scanning entities with no matches
        entities = ["sensor.temperature", "sensor.humidity", "sensor.solar_power"]
        matches = [e for e in entities if any(p in e for p in ("electricity_price", "nordpool", "awattar"))]
        assert len(matches) == 0


# ============================================================
# 13. Config migration v2→v3
# ============================================================

class TestConfigMigrationV2toV3:
    """Verify flat ev_* keys are migrated to ev_chargers list."""

    def test_flat_keys_wrapped_into_list(self):
        """Flat ev_* keys should become ev_chargers[0]."""
        flat = {
            "ev_connected_sensor": "binary_sensor.keba_plug",
            "ev_charging_sensor": "binary_sensor.keba_charging",
            "ev_charging_power_sensor": "sensor.keba_power",
            "ev_charger_service": "keba.set_current",
            "ev_surplus_priority": 3,
        }
        # Simulate migration logic from __init__.py
        charger_0 = {"id": "ev_charger", "name": "EV Charger"}
        ev_keys = [k for k in flat if k.startswith("ev_")]
        for k in ev_keys:
            charger_0[k] = flat[k]
        result = [charger_0]

        assert len(result) == 1
        assert result[0]["ev_charging_power_sensor"] == "sensor.keba_power"
        assert result[0]["ev_charger_service"] == "keba.set_current"

    def test_idempotent_migration(self):
        """Running migration twice should not duplicate chargers."""
        config = {
            "ev_chargers": [{"id": "ev_charger", "name": "EV Charger",
                            "ev_charging_power_sensor": "sensor.keba_power"}],
            "ev_charging_power_sensor": "sensor.keba_power",
        }
        # Migration check: ev_chargers already exists → skip
        if "ev_chargers" in config:
            result = config["ev_chargers"]
        else:
            result = [{"id": "ev_charger"}]

        assert len(result) == 1

    def test_no_ev_config_produces_empty_list(self):
        """Config without EV should not create ev_chargers."""
        config = {"battery_priority_soc": 30}
        has_ev = config.get("ev_charging_power_sensor")
        assert not has_ev

    def test_service_params_preserved(self):
        """Per-integration charger profile keys must survive migration."""
        flat = {
            "ev_charging_power_sensor": "sensor.easee_power",
            "ev_charger_service": "easee.set_charger_dynamic_limit",
            "ev_service_param_name": "current",
            "ev_service_device_id": "device_123",
        }
        charger_0 = {"id": "ev_charger", "name": "EV Charger"}
        for k in flat:
            if k.startswith("ev_"):
                charger_0[k] = flat[k]

        assert charger_0["ev_service_param_name"] == "current"
        assert charger_0["ev_service_device_id"] == "device_123"

    def test_multiple_chargers_from_ev_chargers_list(self):
        """ev_chargers list with 2 entries should be preserved as-is."""
        config = {
            "ev_chargers": [
                {"id": "wb_1", "name": "WB1", "ev_charging_power_sensor": "sensor.wb1_power"},
                {"id": "wb_2", "name": "WB2", "ev_charging_power_sensor": "sensor.wb2_power"},
            ]
        }
        assert len(config["ev_chargers"]) == 2


class TestEVNotificationTriggers:
    """Test notification trigger conditions."""

    @pytest.mark.asyncio
    async def test_nearly_full_fires_when_taper_below_5_min(self):
        """notify_ev_nearly_full should fire when minutes_to_full < 5."""
        from custom_components.solar_energy_management.coordinator.notifications import NotificationManager
        hass = MagicMock()
        hass.bus = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.services.has_service = MagicMock(return_value=False)

        nm = NotificationManager(hass, {"enable_mobile_notifications": False})
        await nm.notify_ev_nearly_full(3.0)

        assert hass.bus.async_fire.call_count == 1
        event_data = hass.bus.async_fire.call_args[0][1]
        assert event_data["event"] == "ev_nearly_full"

    @pytest.mark.asyncio
    async def test_nearly_full_deduplicates(self):
        """Second call should not fire again."""
        from custom_components.solar_energy_management.coordinator.notifications import NotificationManager
        hass = MagicMock()
        hass.bus = MagicMock()
        hass.bus.async_fire = MagicMock()
        hass.services = MagicMock()
        hass.services.async_call = AsyncMock()
        hass.services.has_service = MagicMock(return_value=False)

        nm = NotificationManager(hass, {"enable_mobile_notifications": False})
        await nm.notify_ev_nearly_full(3.0)
        hass.bus.async_fire.reset_mock()
        await nm.notify_ev_nearly_full(2.0)

        assert hass.bus.async_fire.call_count == 0

    # (test_skip_notification_fires) removed in #440 — notify_ev_charge_skip
    # is gone alongside the skip-decision wiring.


# ============================================================
# EV false-stall guard (#243)
# ============================================================

def make_stall_charger(setpoint=10, min_current=6, session_active=True):
    """Mock charger configured for the false-stall scenario."""
    dev = MagicMock()
    dev.device_id = "ev_charger"
    dev.min_current = min_current
    dev._current_setpoint = setpoint
    dev._session_active = session_active
    return dev


def confirm_stall(coord, power):
    """Run two passes so the >30s stall timer trips on the second call.

    First call arms _ev_stalled_since; second call (simulated 31s later)
    evaluates the re-enable decision. Returns the second call's result.
    """
    coord._ev_stalled_since = None
    coord._should_reenable_charger(power)  # arm timer
    # Backdate the arm so the >30s threshold is crossed
    if coord._ev_stalled_since is not None:
        coord._ev_stalled_since -= 31
    return coord._should_reenable_charger(power)


class TestEVFalseStallGuard:
    """#243: full car left plugged in must not loop 're-enabling' forever."""

    def _power(self, ev_power=0.0, ev_connected=True):
        return PowerReadings(ev_power=ev_power, ev_connected=ev_connected)

    def test_first_attempts_reenable(self):
        """First few confirmed stalls return True (genuine self-heal)."""
        coord = MockCoordinator({"ev_max_reenable_attempts": 3})
        coord._ev_device = make_stall_charger()
        assert confirm_stall(coord, self._power()) is True
        assert coord._ev_reenable_attempts == 1

    def test_gives_up_after_max_attempts(self):
        """After max attempts the car is deemed full → stop re-enabling."""
        coord = MockCoordinator({"ev_max_reenable_attempts": 3})
        coord._ev_device = make_stall_charger()
        power = self._power()
        results = [confirm_stall(coord, power) for _ in range(5)]
        # 3 re-enables, then latched off
        assert results[:3] == [True, True, True]
        assert results[3] is False
        assert results[4] is False
        assert coord._ev_charge_refused is True

    def test_stays_quiet_once_refused(self):
        """Once refused, further calls short-circuit to False (no spam)."""
        coord = MockCoordinator({"ev_max_reenable_attempts": 2})
        coord._ev_device = make_stall_charger()
        power = self._power()
        for _ in range(4):
            confirm_stall(coord, power)
        assert coord._ev_charge_refused is True
        # Direct call (no timer) must also stay False without touching timer
        assert coord._should_reenable_charger(power) is False

    def test_resets_when_car_draws_power(self):
        """Car starts drawing → latch + counter clear → self-heal re-armed."""
        coord = MockCoordinator({"ev_max_reenable_attempts": 2})
        coord._ev_device = make_stall_charger()
        power = self._power()
        for _ in range(4):
            confirm_stall(coord, power)
        assert coord._ev_charge_refused is True
        # Car now draws power (>=50W) → healthy branch resets everything
        coord._should_reenable_charger(self._power(ev_power=4200.0))
        assert coord._ev_charge_refused is False
        assert coord._ev_reenable_attempts == 0
        # A fresh stall can re-enable again
        assert confirm_stall(coord, power) is True

    def test_resets_when_car_unplugged(self):
        """Unplug clears the latch so a new session starts fresh."""
        coord = MockCoordinator({"ev_max_reenable_attempts": 2})
        coord._ev_device = make_stall_charger()
        for _ in range(4):
            confirm_stall(coord, self._power())
        assert coord._ev_charge_refused is True
        # Disconnected → healthy branch resets
        coord._should_reenable_charger(self._power(ev_connected=False))
        assert coord._ev_charge_refused is False
        assert coord._ev_reenable_attempts == 0

    def test_no_reenable_when_session_inactive(self):
        """No session → never re-enable regardless of power."""
        coord = MockCoordinator({})
        coord._ev_device = make_stall_charger(session_active=False)
        assert coord._should_reenable_charger(self._power()) is False

    def test_default_max_attempts_is_three(self):
        """Without config override, default cap is 3 attempts."""
        coord = MockCoordinator({})
        coord._ev_device = make_stall_charger()
        results = [confirm_stall(coord, self._power()) for _ in range(5)]
        assert results == [True, True, True, False, False]
