"""Tests for battery sign auto-detection in SensorReader.

Validates that SEM correctly detects and corrects battery power sign
conventions for inverters that use the opposite convention:
- SEM convention: positive = charge, negative = discharge
- Opposite (Enphase, GoodWe, Powerwall, Sunsynk): positive = discharge, negative = charge
"""
import pytest
from unittest.mock import Mock, MagicMock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _make_sensor_state(value, unit="W"):
    """Create a mock sensor state."""
    state = Mock()
    state.state = str(value)
    state.attributes = {"unit_of_measurement": unit}
    return state


def _make_energy_dashboard_config(
    battery_power="sensor.battery_power",
    battery_charge_energy="sensor.battery_charge_total",
    battery_discharge_energy="sensor.battery_discharge_total",
    solar_power="sensor.solar_power",
    grid_import_power="sensor.grid_power",
    grid_import_energy="sensor.grid_import_total",
    grid_export_energy="sensor.grid_export_total",
):
    """Create a mock EnergyDashboardConfig."""
    config = Mock()
    config.battery_power = battery_power
    config.battery_charge_energy = battery_charge_energy
    config.battery_discharge_energy = battery_discharge_energy
    config.solar_power = solar_power
    config.grid_import_power = grid_import_power
    config.grid_import_energy = grid_import_energy
    config.grid_export_energy = grid_export_energy
    config.ev_power = None
    config.has_battery = True
    config.has_solar = True
    config.has_grid = True
    config.has_ev = False
    config.grid_power = grid_import_power
    return config


@pytest.fixture
def mock_hass():
    """Create a mock Home Assistant instance."""
    hass = Mock()
    hass.states = Mock()
    return hass


@pytest.fixture
def sensor_reader(mock_hass):
    """Create a SensorReader with empty config."""
    r = SensorReader(mock_hass, {})
    r._sign_vote_warmup = 0
    r._sign_vote_warmup = 0  # unit tests exercise post-warmup voting (#487)
    return r


class TestBatterySignAutoDetect:
    """Tests for _detect_battery_sign method."""

    def test_no_energy_dashboard_returns_false(self, sensor_reader):
        """Without Energy Dashboard, trust the sensor as-is."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        readings = PowerReadings(battery_power=500.0)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_missing_charge_energy_returns_false(self, sensor_reader):
        """If charge energy counter is missing, can't detect."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config(battery_charge_energy=None)
        sensor_reader.set_energy_dashboard_config(ed)
        readings = PowerReadings(battery_power=500.0)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_missing_discharge_energy_returns_false(self, sensor_reader):
        """If discharge energy counter is missing, can't detect."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config(battery_discharge_energy=None)
        sensor_reader.set_energy_dashboard_config(ed)
        readings = PowerReadings(battery_power=500.0)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_low_power_keeps_last_state(self, sensor_reader, mock_hass):
        """Power below 100W threshold should keep last known state."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)
        readings = PowerReadings(battery_power=50.0)  # Below 100W threshold
        # Default state is False (no inversion)
        assert sensor_reader._detect_battery_sign(readings) is False

    def test_first_call_stores_baselines(self, sensor_reader, mock_hass):
        """First call stores baselines and returns False."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)

        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False
        # #404: state is keyed by battery_id; the fleet path uses the
        # ``_FLEET_BID`` sentinel so legacy single-battery / combined-
        # sensor installs still funnel through one entry.
        assert sensor_reader._battery_charge_baseline[
            sensor_reader._FLEET_BID
        ] == 100.0
        assert sensor_reader._battery_discharge_baseline[
            sensor_reader._FLEET_BID
        ] == 50.0

    def test_huawei_sem_convention_no_negate(self, sensor_reader, mock_hass):
        """Huawei Solar: positive=charge matches SEM → no negation needed.

        Scenario: battery_power=+500W (charging) and charge counter increasing.
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: store baselines (charge=100, discharge=50)
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: charge counter grew (100→100.5), power positive → SEM convention
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.5, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False, "Huawei (SEM convention) should NOT negate"

    def test_enphase_opposite_convention_negate(self, sensor_reader, mock_hass):
        """Enphase: positive=discharge is opposite SEM → negation needed.

        Scenario: battery_power=+500W but discharge counter is increasing
        (meaning the battery is actually discharging, so +500 means discharge).
        Requires 3 consistent votes after baseline to lock in.
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: store baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))

        # Calls 2-4: 3 consistent detections — discharge growing, power positive → negate
        for i in range(3):
            mock_hass.states.get = lambda eid, _i=i: {
                "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
                "sensor.battery_discharge_total": _make_sensor_state(50.0 + 0.5 * (_i + 1), "kWh"),
            }.get(eid)
            result = sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))
        assert result is True, "Enphase (opposite convention) should negate"

    def test_goodwe_negative_charge_negate(self, sensor_reader, mock_hass):
        """GoodWe: negative=charge is opposite SEM → negation needed.

        Scenario: battery_power=-500W but charge counter is increasing
        (meaning negative = charging, opposite of SEM where positive = charge).
        Requires 3 consistent votes after baseline to lock in.
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: store baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        sensor_reader._detect_battery_sign(PowerReadings(battery_power=-500.0))

        # Calls 2-4: 3 consistent detections — charge growing, power negative → negate
        for i in range(3):
            mock_hass.states.get = lambda eid, _i=i: {
                "sensor.battery_charge_total": _make_sensor_state(100.0 + 0.5 * (_i + 1), "kWh"),
                "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
            }.get(eid)
            result = sensor_reader._detect_battery_sign(PowerReadings(battery_power=-500.0))
        assert result is True, "GoodWe (negative=charge) should negate"

    def test_huawei_discharge_no_negate(self, sensor_reader, mock_hass):
        """Huawei: negative=discharge matches SEM → no negation.

        Scenario: battery_power=-500W and discharge counter increasing.
        """
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=-500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: discharge counter grew, power negative → SEM convention
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.5, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=-500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False, "Huawei discharge (SEM convention) should NOT negate"

    def test_ambiguous_both_counters_moving_keeps_state(self, sensor_reader, mock_hass):
        """When both counters move, keep last known state (ambiguous)."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        sensor_reader._detect_battery_sign(readings)

        # Call 2: both counters grew (ambiguous)
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.5, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.5, "kWh"),
        }.get(eid)
        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False, "Ambiguous case should keep default (no negate)"

    def test_unavailable_counter_keeps_state(self, sensor_reader, mock_hass):
        """Unavailable counter should keep last known state."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        unavailable = Mock()
        unavailable.state = "unavailable"

        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": unavailable,
        }.get(eid)

        readings = PowerReadings(battery_power=500.0)
        result = sensor_reader._detect_battery_sign(readings)
        assert result is False

    def test_detection_persists_across_calls(self, sensor_reader, mock_hass):
        """Once detected, the sign state persists even through low-power periods."""
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Call 1: baselines
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))

        # Calls 2-4: 3 consistent detections to lock in opposite convention
        for i in range(3):
            mock_hass.states.get = lambda eid, _i=i: {
                "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
                "sensor.battery_discharge_total": _make_sensor_state(50.0 + 0.5 * (_i + 1), "kWh"),
            }.get(eid)
            result = sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))
        assert result is True

        # Call 5: low power period — should keep the detected state
        result = sensor_reader._detect_battery_sign(PowerReadings(battery_power=30.0))
        assert result is True, "Low power should preserve detected inversion state"


class TestBatteryCapacityAutoDetect:
    """Tests for battery capacity auto-detection (#84)."""

    def _make_reader(self, mock_hass):
        config = {"battery_power_sensor": "sensor.battery_power"}
        reader = SensorReader(mock_hass, config)
        reader._sign_vote_warmup = 0
        ed = _make_energy_dashboard_config()
        reader.set_energy_dashboard_config(ed)
        return reader

    def test_detect_huawei_capacity_wh(self):
        """Huawei: sensor.batterien_akkukapazitat in Wh → kWh."""
        hass = MagicMock()
        reader = self._make_reader(hass)

        capacity_state = Mock()
        capacity_state.entity_id = "sensor.batterien_akkukapazitat"
        capacity_state.state = "15000"
        capacity_state.attributes = {
            "unit_of_measurement": "Wh",
            "friendly_name": "Batteries Rated Capacity",
        }
        hass.states.async_all.return_value = [capacity_state]

        result = reader.auto_detect_battery_capacity_kwh()
        assert result == 15.0

    def test_detect_goodwe_capacity_wh(self):
        """GoodWe: sensor with 'battery_capacity' in name."""
        hass = MagicMock()
        reader = self._make_reader(hass)

        capacity_state = Mock()
        capacity_state.entity_id = "sensor.goodwe_battery_capacity"
        capacity_state.state = "10000"
        capacity_state.attributes = {
            "unit_of_measurement": "Wh",
            "friendly_name": "Battery Capacity",
        }
        hass.states.async_all.return_value = [capacity_state]

        result = reader.auto_detect_battery_capacity_kwh()
        assert result == 10.0

    def test_detect_kwh_unit(self):
        """Sensor already in kWh — no conversion."""
        hass = MagicMock()
        reader = self._make_reader(hass)

        capacity_state = Mock()
        capacity_state.entity_id = "sensor.battery_rated_capacity"
        capacity_state.state = "10.0"
        capacity_state.attributes = {
            "unit_of_measurement": "kWh",
            "friendly_name": "Rated Capacity",
        }
        hass.states.async_all.return_value = [capacity_state]

        result = reader.auto_detect_battery_capacity_kwh()
        assert result == 10.0

    def test_no_capacity_sensor(self):
        """No capacity sensor found → returns None."""
        hass = MagicMock()
        reader = self._make_reader(hass)

        unrelated = Mock()
        unrelated.entity_id = "sensor.temperature"
        unrelated.state = "22.5"
        unrelated.attributes = {"friendly_name": "Temperature"}
        hass.states.async_all.return_value = [unrelated]

        result = reader.auto_detect_battery_capacity_kwh()
        assert result is None

    def test_unavailable_capacity_ignored(self):
        """Unavailable capacity sensor → returns None."""
        hass = MagicMock()
        reader = self._make_reader(hass)

        capacity_state = Mock()
        capacity_state.entity_id = "sensor.battery_rated_capacity"
        capacity_state.state = "unavailable"
        capacity_state.attributes = {"friendly_name": "Rated Capacity"}
        hass.states.async_all.return_value = [capacity_state]

        result = reader.auto_detect_battery_capacity_kwh()
        assert result is None

    def test_insane_value_rejected(self):
        """Value outside 1-200 kWh range rejected."""
        hass = MagicMock()
        reader = self._make_reader(hass)

        capacity_state = Mock()
        capacity_state.entity_id = "sensor.battery_rated_capacity"
        capacity_state.state = "500000"  # 500 kWh — too large
        capacity_state.attributes = {
            "unit_of_measurement": "Wh",
            "friendly_name": "Rated Capacity",
        }
        hass.states.async_all.return_value = [capacity_state]

        result = reader.auto_detect_battery_capacity_kwh()
        assert result is None


# ════════════════════════════════════════════
# Split grid power sensor discovery (#129)
# ════════════════════════════════════════════

class TestSplitGridPowerDiscovery:
    """Test auto-discovery of split import/export grid power sensors (Growatt, etc.)."""

    def _make_reader(self, mock_hass):
        config = {"update_interval": 10}
        return SensorReader(mock_hass, config)

    def _make_power_state(self, entity_id, value=1000, unit="W"):
        state = Mock()
        state.entity_id = entity_id
        state.state = str(value)
        # (#911) a candidate must be a live measurement — a forecast or a
        # statistic is never a grid meter
        state.attributes = {"unit_of_measurement": unit, "device_class": "power",
                            "state_class": "measurement"}
        return state

    def test_discovers_growatt_sph_sensors(self):
        """Discover Growatt SPH import/export sensors."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        ed = Mock()
        ed.grid_import_energy = "sensor.mix_import_from_grid_today"
        hass.states.async_all.return_value = [
            self._make_power_state("sensor.mix_import_from_grid", 500),
            self._make_power_state("sensor.mix_export_to_grid", 2000),
        ]
        imp, exp, _conf = reader._discover_split_grid_power(ed)
        assert imp == "sensor.mix_import_from_grid"
        assert exp == "sensor.mix_export_to_grid"

    def test_discovers_growatt_tlx_sensors(self):
        """Discover Growatt TLX pac_to sensors."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        ed = Mock()
        ed.grid_import_energy = "sensor.tlx_import_energy"
        hass.states.async_all.return_value = [
            self._make_power_state("sensor.tlx_pac_to_user_total", 800),
            self._make_power_state("sensor.tlx_pac_to_grid_total", 3000),
        ]
        imp, exp, _conf = reader._discover_split_grid_power(ed)
        assert imp == "sensor.tlx_pac_to_user_total"
        assert exp == "sensor.tlx_pac_to_grid_total"

    def test_returns_none_when_no_split_sensors(self):
        """Return None when no split sensors found."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        ed = Mock()
        ed.grid_import_energy = "sensor.grid_import_total"
        hass.states.async_all.return_value = [
            self._make_power_state("sensor.solar_power", 5000),
        ]
        imp, exp, _conf = reader._discover_split_grid_power(ed)
        assert imp is None
        assert exp is None

    def test_split_grid_export(self):
        """Split sensors: positive grid_power when exporting."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        hass.states.get = lambda eid: {
            "sensor.mix_import_from_grid": _make_sensor_state(0),
            "sensor.mix_export_to_grid": _make_sensor_state(2000),
        }.get(eid)
        import_w = reader._read_sensor("sensor.mix_import_from_grid", "grid_import")
        export_w = reader._read_sensor("sensor.mix_export_to_grid", "grid_export")
        assert export_w - import_w == 2000

    def test_split_grid_import(self):
        """Split sensors: negative grid_power when importing."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        hass.states.get = lambda eid: {
            "sensor.mix_import_from_grid": _make_sensor_state(1500),
            "sensor.mix_export_to_grid": _make_sensor_state(0),
        }.get(eid)
        import_w = reader._read_sensor("sensor.mix_import_from_grid", "grid_import")
        export_w = reader._read_sensor("sensor.mix_export_to_grid", "grid_export")
        assert export_w - import_w == -1500

    def test_import_only_discovered(self):
        """Only import sensor found, no export."""
        hass = MagicMock()
        reader = self._make_reader(hass)
        ed = Mock()
        ed.grid_import_energy = "sensor.grid_import_total"
        hass.states.async_all.return_value = [
            self._make_power_state("sensor.growatt_import_from_grid", 500),
        ]
        imp, exp, _conf = reader._discover_split_grid_power(ed)
        assert imp == "sensor.growatt_import_from_grid"
        assert exp is None


def _make_multi_battery_ed(
    battery_power_list,
    battery_charge_energy_list,
    battery_discharge_energy_list,
):
    """Build a multi-battery EnergyDashboardConfig mock for #404 tests.

    Mirrors the parallel-list shape ``ha_energy_reader.py`` populates
    when the HA Energy Dashboard has multiple battery sources configured.
    """
    config = Mock()
    config.battery_power = None  # No combined sensor in multi-battery mode
    config.battery_charge_energy = None
    config.battery_discharge_energy = None
    config.battery_power_list = list(battery_power_list)
    config.battery_charge_energy_list = list(battery_charge_energy_list)
    config.battery_discharge_energy_list = list(battery_discharge_energy_list)
    config.solar_power = "sensor.solar_power"
    config.solar_power_list = []
    config.grid_power = "sensor.grid_power"
    config.grid_power_list = []
    config.grid_import_power = "sensor.grid_power"
    config.grid_import_energy = "sensor.grid_import_total"
    config.grid_export_energy = "sensor.grid_export_total"
    config.ev_power = None
    config.has_battery = True
    config.has_solar = True
    config.has_grid = True
    config.has_ev = False
    return config


class TestPerBatterySignAutoDetect404:
    """#404 — per-battery sign autodetect.

    Single boolean ``_battery_sign_inverted`` doesn't work for dual-brand
    installs (Sessy + Huawei in one fleet). The autodetect now runs
    independently per battery, keyed by the ``b1`` / ``b2`` … slugs
    assigned in the read-power loop. Fleet ``battery_power`` is rebuilt
    from the corrected per-battery values — fleet ↔ per-battery agreement
    is guaranteed by construction.
    """

    @staticmethod
    def _make_reader_with_multi_ed(charge_vals, discharge_vals):
        """Build a SensorReader pre-loaded with multi-battery EnergyDashboardConfig.

        ``charge_vals`` / ``discharge_vals`` are lists of cumulative
        energy counter values (kWh) — one per battery, in the same
        order as ``battery_power_list``.
        """
        hass = Mock()
        hass.states = Mock()
        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        ed = _make_multi_battery_ed(
            battery_power_list=[f"sensor.b{i+1}_power" for i in range(len(charge_vals))],
            battery_charge_energy_list=[f"sensor.b{i+1}_charge" for i in range(len(charge_vals))],
            battery_discharge_energy_list=[f"sensor.b{i+1}_discharge" for i in range(len(charge_vals))],
        )
        reader.set_energy_dashboard_config(ed)
        # Populate hass.states with the per-battery counters
        states_map = {}
        for i, (c, d) in enumerate(zip(charge_vals, discharge_vals, strict=False)):
            states_map[f"sensor.b{i+1}_charge"] = _make_sensor_state(c, "kWh")
            states_map[f"sensor.b{i+1}_discharge"] = _make_sensor_state(d, "kWh")
        hass.states.get = lambda eid: states_map.get(eid)
        return reader, ed

    def test_independent_per_battery_state(self):
        """Each battery_id has its own baseline + voting state.

        Two batteries see different power values and different counter
        deltas — neither should pollute the other's state.
        """
        reader, _ed = self._make_reader_with_multi_ed(
            charge_vals=[100.0, 200.0], discharge_vals=[50.0, 75.0],
        )

        # Prime baselines for both
        reader._detect_battery_sign_for("b1", 500.0, "sensor.b1_charge", "sensor.b1_discharge")
        reader._detect_battery_sign_for("b2", -500.0, "sensor.b2_charge", "sensor.b2_discharge")

        assert reader._battery_charge_baseline["b1"] == 100.0
        assert reader._battery_charge_baseline["b2"] == 200.0
        assert reader._battery_discharge_baseline["b1"] == 50.0
        assert reader._battery_discharge_baseline["b2"] == 75.0
        # Each starts fresh — neither flipped on the first call.
        assert reader._battery_sign_inverted["b1"] is False
        assert reader._battery_sign_inverted["b2"] is False

    def test_dual_brand_one_flipped_one_not(self):
        """Battery 1 reports opposite convention (Sessy-shape: positive
        during discharge → needs flip). Battery 2 reports canonical
        (Huawei-shape: positive during charge → no flip).

        After 3 consecutive correlation votes per battery, only b1's
        ``_battery_sign_inverted`` flag flips. b2 stays at False.
        """
        reader, _ed = self._make_reader_with_multi_ed(
            charge_vals=[100.0, 200.0], discharge_vals=[50.0, 75.0],
        )
        hass = reader.hass

        # 4 cycles: each cycle advances both batteries' counters in
        # opposite directions relative to their reported power.
        for cycle in range(4):
            states_map = {
                "sensor.b1_charge": _make_sensor_state(100.0 + cycle * 0.0000001, "kWh"),
                # b1 discharge counter growing while power is POSITIVE → opposite convention → flip
                "sensor.b1_discharge": _make_sensor_state(50.0 + (cycle + 1) * 0.5, "kWh"),
                # b2 charge counter growing while power is POSITIVE → canonical → no flip
                "sensor.b2_charge": _make_sensor_state(200.0 + (cycle + 1) * 0.5, "kWh"),
                "sensor.b2_discharge": _make_sensor_state(75.0 + cycle * 0.0000001, "kWh"),
            }
            hass.states.get = lambda eid, _m=states_map: _m.get(eid)
            reader._detect_battery_sign_for("b1", 500.0, "sensor.b1_charge", "sensor.b1_discharge")
            reader._detect_battery_sign_for("b2", 500.0, "sensor.b2_charge", "sensor.b2_discharge")

        assert reader._battery_sign_inverted["b1"] is True, (
            "b1 (Sessy-shape: positive during discharge) should be flipped"
        )
        assert reader._battery_sign_inverted["b2"] is False, (
            "b2 (Huawei-shape: positive during charge) should NOT be flipped"
        )

    def test_both_invert_both_canonical_after_correction(self):
        """RienduPre's actual install: both batteries Sessy-shape, both
        need flipping. After autodetect locks in, both per-battery
        entries report the canonical SEM sign for the user-visible direction.
        """
        reader, _ed = self._make_reader_with_multi_ed(
            charge_vals=[100.0, 200.0], discharge_vals=[50.0, 75.0],
        )
        hass = reader.hass

        for cycle in range(4):
            states_map = {
                "sensor.b1_charge": _make_sensor_state(100.0 + cycle * 0.0000001, "kWh"),
                "sensor.b1_discharge": _make_sensor_state(50.0 + (cycle + 1) * 0.4, "kWh"),
                "sensor.b2_charge": _make_sensor_state(200.0 + cycle * 0.0000001, "kWh"),
                "sensor.b2_discharge": _make_sensor_state(75.0 + (cycle + 1) * 0.3, "kWh"),
            }
            hass.states.get = lambda eid, _m=states_map: _m.get(eid)
            # Both report POSITIVE power while their discharge counter
            # is growing → Sessy-shape → autodetect votes "flip".
            reader._detect_battery_sign_for("b1", 712.0, "sensor.b1_charge", "sensor.b1_discharge")
            reader._detect_battery_sign_for("b2", 300.0, "sensor.b2_charge", "sensor.b2_discharge")

        assert reader._battery_sign_inverted["b1"] is True
        assert reader._battery_sign_inverted["b2"] is True

    def test_neither_inverts_canonical_baseline(self):
        """Two canonical batteries (Huawei-shape): neither flips."""
        reader, _ed = self._make_reader_with_multi_ed(
            charge_vals=[100.0, 200.0], discharge_vals=[50.0, 75.0],
        )
        hass = reader.hass

        for cycle in range(4):
            states_map = {
                "sensor.b1_charge": _make_sensor_state(100.0 + (cycle + 1) * 0.5, "kWh"),
                "sensor.b1_discharge": _make_sensor_state(50.0 + cycle * 0.0000001, "kWh"),
                "sensor.b2_charge": _make_sensor_state(200.0 + (cycle + 1) * 0.4, "kWh"),
                "sensor.b2_discharge": _make_sensor_state(75.0 + cycle * 0.0000001, "kWh"),
            }
            hass.states.get = lambda eid, _m=states_map: _m.get(eid)
            reader._detect_battery_sign_for("b1", 500.0, "sensor.b1_charge", "sensor.b1_discharge")
            reader._detect_battery_sign_for("b2", 400.0, "sensor.b2_charge", "sensor.b2_discharge")

        assert reader._battery_sign_inverted["b1"] is False
        assert reader._battery_sign_inverted["b2"] is False

    def test_fallback_when_per_battery_counters_missing(self):
        """If a battery is missing its energy counters (user didn't
        configure them in the Energy Dashboard), per-battery autodetect
        returns the stored default (False) for that battery — no crash.
        """
        reader = SensorReader(Mock(states=Mock()), {})
        reader._sign_vote_warmup = 0
        # No charge/discharge entities provided
        result = reader._detect_battery_sign_for("b1", 500.0, None, None)
        assert result is False
        # State entry created lazily so subsequent calls work
        assert reader._battery_sign_inverted["b1"] is False

    def test_voting_threshold_prevents_premature_flip(self):
        """One-off readings don't flip a battery's sign — need 3
        consecutive votes per battery (heuristic carried over from the
        fleet-level autodetect).
        """
        reader, _ed = self._make_reader_with_multi_ed(
            charge_vals=[100.0], discharge_vals=[50.0],
        )
        hass = reader.hass

        # Cycle 1: prime baseline.
        reader._detect_battery_sign_for("b1", 500.0, "sensor.b1_charge", "sensor.b1_discharge")

        # Cycle 2: one Sessy-shape vote. NOT enough.
        states = {
            "sensor.b1_charge": _make_sensor_state(100.0000001, "kWh"),
            "sensor.b1_discharge": _make_sensor_state(50.5, "kWh"),
        }
        hass.states.get = lambda eid, _m=states: _m.get(eid)
        reader._detect_battery_sign_for("b1", 500.0, "sensor.b1_charge", "sensor.b1_discharge")
        assert reader._battery_sign_inverted["b1"] is False, (
            "single vote should not flip"
        )

        # Cycles 3-4: two more Sessy-shape votes → 3 total → locks in.
        for cycle in range(2):
            states = {
                "sensor.b1_charge": _make_sensor_state(100.0000001 + cycle * 0.0000001, "kWh"),
                "sensor.b1_discharge": _make_sensor_state(50.5 + (cycle + 1) * 0.5, "kWh"),
            }
            hass.states.get = lambda eid, _m=states: _m.get(eid)
            reader._detect_battery_sign_for("b1", 500.0, "sensor.b1_charge", "sensor.b1_discharge")

        assert reader._battery_sign_inverted["b1"] is True
        assert reader._battery_sign_detected["b1"] is True

    def test_fleet_sentinel_separate_from_per_battery_state(self):
        """Legacy single-battery installs use ``_FLEET_BID`` as the key
        and stay isolated from per-battery state — switching modes
        doesn't cross-contaminate.
        """
        reader = SensorReader(Mock(states=Mock()), {})
        reader._sign_vote_warmup = 0
        # Prime fleet path
        reader._detect_battery_sign_for("b1", 500.0, None, None)
        reader._detect_battery_sign_for(reader._FLEET_BID, 500.0, None, None)
        assert reader._battery_sign_inverted["b1"] == reader._battery_sign_inverted[
            reader._FLEET_BID
        ] == False
        # The dicts have separate entries
        assert "b1" in reader._battery_sign_inverted
        assert reader._FLEET_BID in reader._battery_sign_inverted


class TestCounterResetGuard:
    """#476: daily energy counters (Growatt firmware resets at midnight) can
    reset in DIFFERENT update cycles. A negative delta on either side means
    both deltas are garbage for that cycle — one side can still show a
    legitimate-looking increment and cast a wrong sign vote. The guard
    re-baselines and sits the cycle out."""

    def test_battery_counter_reset_does_not_vote(self, sensor_reader, mock_hass):
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Baseline at high counter values just before midnight.
        mock_hass.states.get = lambda eid: {
            "sensor.battery_charge_total": _make_sensor_state(100.0, "kWh"),
            "sensor.battery_discharge_total": _make_sensor_state(50.0, "kWh"),
        }.get(eid)
        sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))

        # Midnight: charge counter reset to 0, discharge still pre-reset and
        # showing a small increment — without the guard this is a clean
        # "discharge growing" vote in whatever direction power points.
        for _ in range(3):
            mock_hass.states.get = lambda eid: {
                "sensor.battery_charge_total": _make_sensor_state(0.0, "kWh"),
                "sensor.battery_discharge_total": _make_sensor_state(50.2, "kWh"),
            }.get(eid)
            sensor_reader._detect_battery_sign(PowerReadings(battery_power=500.0))

        # First post-reset cycle re-baselines (0.0 / 50.2); later identical
        # reads produce zero deltas → no votes either way. Nothing locked.
        bid = "__fleet__"
        assert sensor_reader._battery_sign_detected.get(bid, False) is False
        assert sensor_reader._battery_sign_votes.get(bid, 0) == 0

    def test_grid_counter_reset_does_not_vote(self, sensor_reader, mock_hass):
        from custom_components.solar_energy_management.coordinator.types import PowerReadings
        ed = _make_energy_dashboard_config()
        sensor_reader.set_energy_dashboard_config(ed)

        # Baseline.
        mock_hass.states.get = lambda eid: {
            "sensor.grid_import_total": _make_sensor_state(200.0, "kWh"),
            "sensor.grid_export_total": _make_sensor_state(80.0, "kWh"),
        }.get(eid)
        sensor_reader._detect_grid_sign(PowerReadings(grid_power=800.0))

        # Import counter resets at midnight while export ticks up — the
        # export increment would otherwise vote "negate" on positive power.
        mock_hass.states.get = lambda eid: {
            "sensor.grid_import_total": _make_sensor_state(0.0, "kWh"),
            "sensor.grid_export_total": _make_sensor_state(80.1, "kWh"),
        }.get(eid)
        result = sensor_reader._detect_grid_sign(PowerReadings(grid_power=800.0))

        assert result is False
        assert sensor_reader._grid_sign_detected is False
        assert sensor_reader._grid_sign_samples == 0
        # Baselines were reset to the post-reset values.
        assert sensor_reader._grid_import_baseline == 0.0
        assert sensor_reader._grid_export_baseline == 80.1
