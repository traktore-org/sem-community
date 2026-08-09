"""#739 — the charging badge honors the 500 W actual-charging floor.

Reported live on PROD 08.08.2026: `binary_sensor.sem_ev_charging` read
"Charging" at 140 W standby with the charger disabled. Two independent
mechanisms, both fixed here:

1. The published badge (`readings.ev_charging`) was the raw brand
   charging boolean — the signal the codebase itself documents to
   distrust (KEBA's lags ~5 s, numeric state codes read truthy at
   idle). The adapters' own convention is `power_w > 500`
   (`keba.py: handshake_power_w = 500`; `charger_types.py`: "prefer
   power_w > 500 … treat charging as informational"). The badge now
   applies that same floor whenever a power source is configured — a
   real ≥6 A charge is ≥1.38 kW, so 500 W never suppresses a genuine
   charge. Installs with only a charging boolean and no power sensor
   keep the raw signal (nothing better exists there).

2. The `>100 W` physics inference (plug-sensor-lying defence, #285+1)
   sat below KEBA's own ~110–140 W standby draw, so standby power
   inferred a phantom connection. All three sites now use the same
   500 W floor.
"""
from __future__ import annotations

from unittest.mock import MagicMock

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorConfig,
    SensorReader,
)
from custom_components.solar_energy_management.coordinator.types import (
    PowerReadings,
)


def _mk_reader(binary_states: dict, flat_power_sensor: bool = True):
    r = SensorReader.__new__(SensorReader)
    r.config = SensorConfig(
        ev_power_sensor="sensor.evp" if flat_power_sensor else None,
        ev_plug_sensor="binary_sensor.plug",
        ev_charging_sensor="binary_sensor.chg",
    )
    r._raw_config = {"ev_chargers": []}
    r._read_binary_sensor = (
        lambda eid, kind: bool(binary_states.get(eid, False))
    )
    return r


class TestTheBadgeFloor:
    def test_standby_draw_with_a_lagging_boolean_is_not_charging(self):
        """The PROD repro: raw boolean truthy, 140 W standby — off."""
        r = _mk_reader({"binary_sensor.chg": True})
        readings = PowerReadings()
        readings.ev_power = 140.0

        r._read_ev_connection_status(readings, [])

        assert readings.ev_charging is False

    def test_a_real_charge_keeps_the_badge_on(self):
        r = _mk_reader({"binary_sensor.chg": True})
        readings = PowerReadings()
        readings.ev_power = 1400.0

        r._read_ev_connection_status(readings, [])

        assert readings.ev_charging is True

    def test_without_a_power_source_the_raw_boolean_survives(self):
        """Only a charging boolean configured: nothing better exists —
        the badge must NOT be forced off by a permanently-0 ev_power."""
        r = _mk_reader({"binary_sensor.chg": True}, flat_power_sensor=False)
        readings = PowerReadings()
        readings.ev_power = 0.0

        r._read_ev_connection_status(readings, [])

        assert readings.ev_charging is True

    def test_the_per_charger_map_is_gated_per_charger(self):
        """c1 idles at 140 W with a lagging boolean; c2 genuinely
        charges — each is judged on its OWN power reading."""
        chargers = [
            {"id": "c1", "ev_charging_sensor": "binary_sensor.c1",
             "ev_charging_power_sensor": "sensor.c1p"},
            {"id": "c2", "ev_charging_sensor": "binary_sensor.c2",
             "ev_charging_power_sensor": "sensor.c2p"},
        ]
        r = _mk_reader({"binary_sensor.c1": True, "binary_sensor.c2": True})
        r._raw_config = {"ev_chargers": chargers}
        readings = PowerReadings()
        readings.ev_power_per_charger = {"c1": 140.0, "c2": 4000.0}
        readings.ev_power = 4140.0

        r._read_ev_connection_status(readings, chargers)

        assert readings.ev_charging_per_charger["c1"] is False
        assert readings.ev_charging_per_charger["c2"] is True
        assert readings.ev_charging is True  # the fleet OR follows the maps

    def test_a_charger_without_its_own_power_reading_keeps_the_raw_boolean(self):
        chargers = [
            {"id": "c1", "ev_charging_sensor": "binary_sensor.c1"},
        ]
        r = _mk_reader({"binary_sensor.c1": True}, flat_power_sensor=False)
        r._raw_config = {"ev_chargers": chargers}
        readings = PowerReadings()

        r._read_ev_connection_status(readings, chargers)

        assert readings.ev_charging_per_charger["c1"] is True


class TestThePhysicsFloor:
    def test_standby_draw_does_not_infer_a_connection(self):
        """KEBA's own standby (~110–140 W) is below any real charge —
        the plug sensor saying 'off' at 300 W is believed."""
        r = _mk_reader({})
        readings = PowerReadings()
        readings.ev_connected = False
        readings.ev_power = 300.0

        r._infer_fleet_connection_from_physics(readings)

        assert readings.ev_connected is False

    def test_a_real_charge_still_overrides_a_lying_plug_sensor(self):
        """#285+1 stays fixed: 8 kW flowing means connected, whatever
        the plug sensor claims."""
        r = _mk_reader({})
        readings = PowerReadings()
        readings.ev_connected = False
        readings.ev_power = 8000.0

        r._infer_fleet_connection_from_physics(readings)

        assert readings.ev_connected is True

    def test_the_per_charger_mirror_uses_the_same_floor(self):
        r = _mk_reader({})
        readings = PowerReadings()
        readings.ev_connected_per_charger = {"c1": False, "c2": False}
        readings.ev_power_per_charger = {"c1": 300.0, "c2": 4000.0}

        r._infer_per_charger_connection_from_physics(readings)

        assert readings.ev_connected_per_charger["c1"] is False
        assert readings.ev_connected_per_charger["c2"] is True
