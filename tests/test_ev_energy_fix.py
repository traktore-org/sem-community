"""Scenario tests for EV daily energy fix (Layer 1-3).

Tests the three-layer fix for daily_ev_energy stuck at 0:
- Layer 1: Config key mismatch (ev_power_sensor vs ev_charging_power_sensor)
- Layer 2: Energy Dashboard fallback to config EV power sensor
- Layer 3: Hardware reconciliation with KEBA daily energy counter
"""
import pytest
from unittest.mock import Mock

from freezegun import freeze_time

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.energy_calculator import (
    EnergyCalculator,
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


def _make_time_manager(mock_hass) -> TimeManager:
    return TimeManager(mock_hass)


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
        reader._sign_vote_warmup = 0
        assert reader.config.ev_power_sensor == "sensor.keba_p30_charging_power"

    def test_config_flow_key_ev_charging_power_sensor(self):
        """Config uses ev_charging_power_sensor (config_flow saves this key)."""
        config = {"ev_charging_power_sensor": "sensor.keba_p30_charging_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
        assert reader.config.ev_power_sensor == "sensor.keba_p30_charging_power"

    def test_both_keys_legacy_wins(self):
        """When both keys exist, ev_power_sensor (legacy) takes precedence."""
        config = {
            "ev_power_sensor": "sensor.legacy_ev",
            "ev_charging_power_sensor": "sensor.configflow_ev",
        }
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
        assert reader.config.ev_power_sensor == "sensor.legacy_ev"

    def test_neither_key_is_none(self):
        """No EV power sensor configured at all → None."""
        config = {}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
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
        reader._sign_vote_warmup = 0
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
        reader._sign_vote_warmup = 0

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
        reader._sign_vote_warmup = 0

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
        reader._sign_vote_warmup = 0

        ed = EnergyDashboardConfig(solar_power="sensor.ed_solar", ev_power=None)
        reader.set_energy_dashboard_config(ed)

        readings = reader.read_power()
        assert readings.ev_power == 0.0


# ===========================================================================
# Layer 3: Hardware reconciliation
# ===========================================================================

class TestLayer3HardwareReconciliation:
    """EnergyCalculator reconciles integrated EV energy with the wallbox counter.

    Layer 3 shipped in a shape that could not be switched on: it compared the
    counter's ABSOLUTE value against the daily bucket, and those two do not
    share a day boundary (KEBA resets at midnight, ``ev_day`` rolls at the
    charge deadline). Six of these tests were therefore born skipped. #658
    rebuilt the reconciliation on counter DELTAS, which makes the boundary
    question disappear — a reset is just a reset — and the tests are live
    again, now asserting the delta contract:

    **A counter is never adopted for what it read before SEM was watching.**
    First sight only establishes a baseline; ``15.5`` on the counter at
    startup could be today's charging or a lifetime total and SEM has no way
    to tell. What it recovers is what the counter ADVANCES by while
    integration does not — which is exactly the SEM-was-down case the issue
    is about (see ``test_658_ev_counter_reconcile.py``).
    """

    @pytest.fixture
    def mock_hass(self):
        return _make_hass()

    @pytest.fixture
    def time_manager(self, mock_hass):
        return _make_time_manager(mock_hass)

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

    @freeze_time("2026-05-15 12:00:00")
    def test_counter_advance_is_adopted(self, calc):
        """The un-skipped original: a 15.5 kWh advance SEM did not integrate.

        Same scenario the skipped version asserted (SEM sees ev_power = 0
        throughout, the wallbox charges anyway), stated as a delta: the
        counter is baselined first, then advances.
        """
        sensors = {"sensor.keba_p30_charging_daily": (0.0, {})}
        hw_hass = _make_hass(sensors)
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)  # first call sets _last_update + baseline
        calc.calculate_energy(power)

        sensors["sensor.keba_p30_charging_daily"] = (15.5, {})
        energy = calc.calculate_energy(power)

        assert energy.daily_ev == 15.5

    @freeze_time("2026-05-15 12:00:00")
    def test_first_sight_of_a_counter_is_not_adopted(self, calc):
        """The half of the old expectation that #658 deliberately dropped.

        A counter reading 15.5 the first time SEM looks at it is a baseline,
        not a finding. Adopting it would credit a lifetime total to today —
        the shape of the mis-adoption that got Layer 3 parked.
        """
        sensors = {"sensor.keba_p30_charging_daily": (15.5, {})}
        hw_hass = _make_hass(sensors)
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        assert energy.daily_ev == 0.0

    @freeze_time("2026-05-15 12:00:00")
    def test_reconciliation_ignores_small_delta(self, calc):
        """A 0.3 kWh advance is below the threshold → integrator keeps the day."""
        sensors = {"sensor.keba_p30_charging_daily": (0.0, {})}
        hw_hass = _make_hass(sensors)
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        sensors["sensor.keba_p30_charging_daily"] = (0.3, {})
        energy = calc.calculate_energy(power)

        # 0.3 < threshold (0.5), should stay at integrated value (0.0)
        assert energy.daily_ev < 0.3

    @freeze_time("2026-05-15 12:00:00")
    def test_reconciliation_when_integrated_close_to_hardware(self, calc):
        """Integrated 14.8, counter advances 0.2 → below threshold, no override.

        Pinned to a fixed datetime (#294 fix): pre-fix the test depended
        on wall-clock and broke on two fronts whenever a CI run crossed
        a meter-day boundary:
          - The test seeded the accumulator with one ``today`` and
            ``calculate_energy`` looked it up with another.
          - ``_check_rollover`` pruned EV accumulators not matching
            today or yesterday from the *real* clock, so a seeded key
            for a different date got silently deleted.
        Freezing the whole test at noon eliminates both — no boundary
        crossings, no key-drift, no flake. Verified against PR #295 CI
        run that failed at 06:24 UTC.
        """
        sensors = {"sensor.keba_p30_charging_daily": (14.8, {})}
        hw_hass = _make_hass(sensors)
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        # Manually seed the accumulator to simulate prior integration.
        # Use the same method ``calculate_energy`` uses internally so the
        # key matches by construction regardless of which path
        # ``_ev_reset_day`` takes (sunrise vs offset).
        today = calc._ev_reset_day(None)
        calc._daily_accumulators[f"ev_{today}"] = 14.8
        calc._monthly_accumulators[
            f"ev_{today.year}_{today.month}"
        ] = 14.8

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        sensors["sensor.keba_p30_charging_daily"] = (15.0, {})
        energy = calc.calculate_energy(power)

        # Delta 0.2 < 0.5 threshold → keep integrated value
        assert energy.daily_ev == 14.8

    def test_reconciliation_hardware_unavailable(self, calc):
        """Hardware sensor unavailable → no crash, keep integrated value."""
        sensors = {"sensor.keba_p30_charging_daily": ("unavailable", {})}
        hw_hass = _make_hass(sensors)
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        power = PowerReadings(ev_power=500.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # Should have integrated some ev energy from power, no crash
        assert energy.daily_ev >= 0.0

    def test_reconciliation_hardware_missing_entity(self, calc):
        """Hardware sensor entity doesn't exist → no crash."""
        hw_hass = _make_hass({})  # empty — entity not found
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)
        assert energy.daily_ev == 0.0

    @freeze_time("2026-05-15 12:00:00")
    def test_reconciliation_updates_monthly_accumulator(self, calc):
        """When reconciliation fires, monthly accumulator gets the delta too.

        #666's lesson in reverse: one ``_accumulate`` call writes daily,
        monthly, yearly and lifetime, so one correction must move all four or
        the periods drift apart in a way nothing reports.
        """
        sensors = {"sensor.keba_p30_charging_daily": (0.0, {})}
        hw_hass = _make_hass(sensors)
        calc.configure_ev_counters(
            hw_hass, ["sensor.keba_p30_charging_daily"], True)

        # Seed daily at 2.0, monthly at 50.0
        today = calc._ev_reset_day(None)
        month_key = f"{today.year}_{today.month}"
        calc._daily_accumulators[f"ev_{today}"] = 2.0
        calc._monthly_accumulators[f"ev_{month_key}"] = 50.0

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)  # baselines the counter at 0.0
        sensors["sensor.keba_p30_charging_daily"] = (8.0, {})
        energy = calc.calculate_energy(power)

        # Daily = anchor (2.0) + counter advance (8.0)
        assert energy.daily_ev == 10.0
        # Monthly should have gained the same delta (8.0)
        assert calc._get_monthly("ev", month_key) == 58.0


# ===========================================================================
# Auto-detection of KEBA daily energy sensor
# ===========================================================================

class TestKebaAutoDetection:
    """SensorReader auto-detects KEBA daily energy sensor from power sensor name."""

    def test_keba_power_sensor_no_auto_detect(self):
        """KEBA auto-detection removed — daily energy must be explicitly configured."""
        config = {"ev_charging_power_sensor": "sensor.keba_p30_charging_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
        assert reader.config.ev_daily_energy_sensor is None

    def test_non_keba_power_sensor_no_auto_detect(self):
        """Non-KEBA power sensor → no auto-detection."""
        config = {"ev_charging_power_sensor": "sensor.wallbox_power"}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
        assert reader.config.ev_daily_energy_sensor is None

    def test_explicit_daily_sensor_overrides_auto_detect(self):
        """Explicit ev_daily_energy_sensor overrides auto-detection."""
        config = {
            "ev_charging_power_sensor": "sensor.keba_p30_charging_power",
            "ev_daily_energy_sensor": "sensor.my_custom_daily",
        }
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
        assert reader.config.ev_daily_energy_sensor == "sensor.my_custom_daily"

    def test_no_ev_sensor_no_crash(self):
        """No EV power sensor at all → no daily energy sensor, no crash."""
        config = {}
        hass = _make_hass()
        reader = SensorReader(hass, config)
        reader._sign_vote_warmup = 0
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

    @freeze_time("2026-05-15 12:00:00")
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
        reader._sign_vote_warmup = 0
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

        # Layer 3: even with power integration missing the charge entirely,
        # the wallbox counter's advance is recovered. (The counter must be
        # baselined first — see TestLayer3HardwareReconciliation's docstring.)
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.configure_ev_counters(
            hass, ["sensor.keba_p30_charging_daily"], True)

        # Simulate scenario where power integration somehow drifted
        # (e.g. SEM was restarted mid-charge, missed 10 kWh)
        sensors["sensor.keba_p30_charging_daily"] = (0.0, {})
        power_zero = PowerReadings(ev_power=0.0)
        power_zero.calculate_derived()
        calc.calculate_energy(power_zero)
        sensors["sensor.keba_p30_charging_daily"] = (15.5, {})
        energy = calc.calculate_energy(power_zero)

        # Hardware reconciliation should catch us up to 15.5
        assert energy.daily_ev == 15.5

    @freeze_time("2026-05-15 12:00:00")
    def test_night_charging_remaining_correct(self):
        """After fix, remaining energy for night charging is correct."""
        sensors = {"sensor.keba_p30_charging_daily": (0.0, {})}
        hass = _make_hass(sensors)
        config = {"update_interval": 10, "daily_ev_target": 10}
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.configure_ev_counters(
            hass, ["sensor.keba_p30_charging_daily"], True)

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        sensors["sensor.keba_p30_charging_daily"] = (15.5, {})
        energy = calc.calculate_energy(power)

        # daily_ev = 15.5 (from hardware), target = 10
        # remaining = max(0, 10 - 15.5) = 0  → no night charging needed
        daily_target = config["daily_ev_target"]
        remaining = max(0, daily_target - energy.daily_ev)
        assert remaining == 0.0

    @freeze_time("2026-05-15 12:00:00")
    def test_external_charge_via_keba_app(self):
        """User charges via KEBA app (SEM never saw ev_power) → hardware catches it."""
        sensors = {"sensor.keba_p30_charging_daily": (0.0, {})}
        hass = _make_hass(sensors)
        config = {"update_interval": 10}
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.configure_ev_counters(
            hass, ["sensor.keba_p30_charging_daily"], True)

        # SEM never saw any ev_power (external charge)
        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        sensors["sensor.keba_p30_charging_daily"] = (8.3, {})
        energy = calc.calculate_energy(power)

        assert energy.daily_ev == 8.3

    @freeze_time("2026-05-15 12:00:00")
    def test_sem_restart_midcharge_catches_up(self):
        """SEM restarts mid-charge, misses 5 kWh, hardware counter has it all.

        THE scenario #658 exists for, and the one that only works because the
        baselines are persisted with the accumulators: here the restored store
        carries ``base = 7.0`` from before the restart, so the counter's climb
        to 12.0 during the downtime is a 5.0 kWh advance rather than a fresh
        baseline. Drop the persistence and this test goes back to 7.0.
        """
        sensors = {"sensor.keba_p30_charging_daily": (12.0, {})}
        hass = _make_hass(sensors)
        config = {"update_interval": 10}
        tm = _make_time_manager(hass)
        calc = EnergyCalculator(config, tm)
        calc.configure_ev_counters(
            hass, ["sensor.keba_p30_charging_daily"], True)

        # SEM only integrated 7 kWh before restart, and its last look at the
        # counter — persisted across the restart — also read 7.0.
        today = calc._ev_reset_day(None)
        month_key = f"{today.year}_{today.month}"
        calc.restore_state({
            "daily_accumulators": {f"ev_{today}": 7.0},
            "monthly_accumulators": {f"ev_{month_key}": 7.0},
            "ev_counter_baselines": {
                "date": str(today),
                "base": {"sensor.keba_p30_charging_daily": 7.0},
                "last": {"sensor.keba_p30_charging_daily": 7.0},
                "anchor": 7.0,
            },
        })

        power = PowerReadings(ev_power=0.0)
        power.calculate_derived()
        calc.calculate_energy(power)
        energy = calc.calculate_energy(power)

        # Counter advanced 7.0 → 12.0 while SEM integrated nothing → adopt 12.0
        assert energy.daily_ev == 12.0
        # Monthly should have gained the delta (5.0)
        assert calc._get_monthly("ev", month_key) == 12.0
