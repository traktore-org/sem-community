"""Phase A of the per-battery card mirror — backend data layer.

Two structural invariants pinned by these tests:

1. ``sensor_reader`` populates ``PowerReadings.batteries`` with short
   stable slugs (``b1``, ``b2`` …) keyed by the Energy Dashboard
   ``battery_power_list`` order — not the source entity name. The
   downstream sensor IDs (``sensor.sem_battery_b1_power``) are then
   predictable at setup time without re-reading the registry.

2. ``SEMData.to_dict`` unpacks each ``BatteryPower`` entry into flat
   ``battery_<bid>_*`` keys (power / soc / status / capacity). The
   ``status`` value is derived from ``power_w`` with a 50 W dead-band
   so inverter rebalance noise doesn't toggle it.

Single-battery installs (today's PROD configs) leave
``power.batteries`` empty and produce zero per-battery keys — the
fleet sensors remain the only source, unchanged.
"""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from custom_components.solar_energy_management.coordinator.charger_types import (
    BatteryPower,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings, SEMData,
)


def _battery(bid: str, power_w: float, soc: float = 50.0, capacity: float = 10.0):
    return BatteryPower(
        battery_id=bid,
        power_w=power_w,
        soc_pct=soc,
        capacity_kwh=capacity,
        name=f"sensor.battery_{bid}_power",
    )


def _semdata_with_batteries(*batteries):
    sem = SEMData()
    for bp in batteries:
        sem.power.batteries[bp.battery_id] = bp
    return sem


class TestPerBatteryToDict:
    """Per-battery flat-dict unpack in ``SEMData.to_dict``."""

    def test_single_battery_no_per_battery_keys(self):
        """Single-battery installs leave ``power.batteries`` empty; the
        legacy fleet sensors must be the only source — zero per-
        battery keys in the flat dict."""
        sem = SEMData()  # batteries dict default empty
        out = sem.to_dict()
        battery_keys = [k for k in out if k.startswith("battery_") and "_b" in k[:11]]
        assert battery_keys == []

    def test_two_battery_keys_per_battery(self):
        sem = _semdata_with_batteries(
            _battery("b1", power_w=1500.0, soc=80.0, capacity=10.0),
            _battery("b2", power_w=-400.0, soc=60.0, capacity=7.5),
        )
        out = sem.to_dict()

        for bid, p, soc, cap in (
            ("b1", 1500.0, 80.0, 10.0),
            ("b2", -400.0, 60.0, 7.5),
        ):
            assert out[f"battery_{bid}_power"] == pytest.approx(p)
            assert out[f"battery_{bid}_soc"] == pytest.approx(soc)
            assert out[f"battery_{bid}_capacity_kwh"] == pytest.approx(cap)

    def test_status_derived_from_power_with_deadband(self):
        """Status is one of {charging, discharging, idle}, gated by a
        50 W dead-band so the inverter's micro-rebalance doesn't
        toggle it."""
        sem = _semdata_with_batteries(
            _battery("b1", power_w=1500.0),    # charging
            _battery("b2", power_w=-2000.0),   # discharging
            _battery("b3", power_w=10.0),      # idle (within dead-band)
            _battery("b4", power_w=-49.9),     # idle (within dead-band)
        )
        out = sem.to_dict()
        assert out["battery_b1_status"] == "charging"
        assert out["battery_b2_status"] == "discharging"
        assert out["battery_b3_status"] == "idle"
        assert out["battery_b4_status"] == "idle"


class TestSensorReaderSlugAssignment:
    """``sensor_reader`` assigns short stable slugs in
    ``battery_power_list`` order — not the source entity name."""

    def test_short_slug_keys_in_order(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )

        # Minimal Energy-Dashboard mock with two battery entries.
        hass = MagicMock()
        ed = MagicMock()
        ed.battery_power_list = [
            "sensor.huawei_b1_power",
            "sensor.huawei_b2_power",
        ]
        ed.battery_power = "sensor.huawei_b1_power"
        # #551 mock fidelity — MagicMock auto-attrs are truthy.
        ed.battery_power_from = None
        ed.battery_power_to = None
        ed.battery_power_inverted = False
        ed.battery_soc = None
        ed.battery_soc_list = []
        ed.battery_power_pairs = []
        ed.solar_power = None
        ed.solar_power_list = []
        ed.grid_power = None
        ed.grid_power_list = []
        ed.grid_import_power = None
        ed.grid_import_energy = None
        ed.grid_export_energy = None
        ed.ev_power = None
        ed.ev_energy = None
        ed.ev_chargers = []
        ed.battery_charge_energy = None
        ed.battery_discharge_energy = None
        ed.battery_charge_energy_list = []
        ed.battery_discharge_energy_list = []
        ed.has_battery = True
        ed.has_solar = False
        ed.has_grid = False
        ed.has_ev = False

        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(ed)

        # Make the sensor reads return deterministic watts so the test
        # asserts the keying, not the value.
        def _state(eid):
            if eid == "sensor.huawei_b1_power":
                return MagicMock(state="1500", attributes={"unit_of_measurement": "W"})
            if eid == "sensor.huawei_b2_power":
                return MagicMock(state="-400", attributes={"unit_of_measurement": "W"})
            return None

        hass.states.get = _state

        readings = reader.read_power()

        # Stable, short, in-order keys.
        assert list(readings.batteries.keys()) == ["b1", "b2"]
        assert readings.batteries["b1"].power_w == pytest.approx(1500.0)
        assert readings.batteries["b2"].power_w == pytest.approx(-400.0)
        # Source entity preserved on ``name`` so the card's friendly-
        # name override still has something useful.
        assert readings.batteries["b1"].name == "sensor.huawei_b1_power"
        assert readings.batteries["b2"].name == "sensor.huawei_b2_power"

    def test_single_battery_leaves_dict_empty(self):
        """``battery_power_list`` of length 1 stays in the legacy
        single-sensor path — no per-battery dict population, no
        per-battery sensors, today's PROD configs unchanged."""
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )

        hass = MagicMock()
        ed = MagicMock()
        ed.battery_power_list = ["sensor.huawei_b1_power"]
        ed.battery_power = "sensor.huawei_b1_power"
        # #551 mock fidelity — MagicMock auto-attrs are truthy.
        ed.battery_power_from = None
        ed.battery_power_to = None
        ed.battery_power_inverted = False
        ed.battery_soc = None
        ed.battery_soc_list = []
        ed.battery_power_pairs = []
        ed.solar_power = None
        ed.solar_power_list = []
        ed.grid_power = None
        ed.grid_power_list = []
        ed.grid_import_power = None
        ed.grid_import_energy = None
        ed.grid_export_energy = None
        ed.ev_power = None
        ed.ev_energy = None
        ed.ev_chargers = []
        ed.battery_charge_energy = None
        ed.battery_discharge_energy = None
        ed.battery_charge_energy_list = []
        ed.battery_discharge_energy_list = []
        ed.has_battery = True
        ed.has_solar = False
        ed.has_grid = False
        ed.has_ev = False
        hass.states.get = lambda eid: (
            MagicMock(state="1500", attributes={"unit_of_measurement": "W"})
            if eid == "sensor.huawei_b1_power" else None
        )
        reader = SensorReader(hass, {})
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(ed)
        readings = reader.read_power()
        # Fleet field populated; per-battery dict stays empty.
        assert readings.batteries == {}
        assert readings.battery_power == pytest.approx(1500.0)
