"""Unit tests for the ev_connected physics-defence in SensorReader.

Reported live on PROD 2026-05-29: across an HA restart, the KEBA
plug binary_sensor reported "off" for 67 minutes while charging_state
cycled on/off through 15 transitions and the charging-power sensor
peaked at 8 kW. SEM correctly trusted the lying plug sensor and
stopped supervising the EV. The car drew 6 kWh past the configured
Max ceiling because SEM wasn't even watching.

The fix: if either ``ev_charging`` is True OR ``ev_power > 100 W``,
infer ``ev_connected = True`` regardless of what the plug sensor
says. Current cannot flow without a connection — physics says no.

These tests pin the four corners of the truth table to lock the
defence against regression.
"""
import pytest
from unittest.mock import MagicMock, patch

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _build_reader(plug_state="off", charging_state="off", charging_power_w=0):
    """Build a minimally-wired SensorReader stubbed against a fake hass."""
    hass = MagicMock()

    def fake_state_get(entity_id):
        state = MagicMock()
        if entity_id == "binary_sensor.fake_plug":
            state.state = plug_state
            return state
        if entity_id == "binary_sensor.fake_charging":
            state.state = charging_state
            return state
        if entity_id == "sensor.fake_charging_power":
            state.state = str(charging_power_w)
            return state
        return None

    hass.states.get = fake_state_get

    # Minimum config the legacy-config path needs to compute ev_connected.
    config = {
        "ev_charging_power_sensor": "sensor.fake_charging_power",
        "ev_connected_sensor": "binary_sensor.fake_plug",
        "ev_charging_sensor": "binary_sensor.fake_charging",
    }
    reader = SensorReader(hass, config)
    return reader


# ──────────────────────────────────────────────────────────────────────
# The four truth-table corners
# ──────────────────────────────────────────────────────────────────────

class TestPhysicsDefence:
    def test_plug_off_charging_off_no_power_stays_disconnected(self):
        """The honest 'truly disconnected' case — no override should fire."""
        reader = _build_reader(plug_state="off", charging_state="off", charging_power_w=0)
        readings = reader._read_from_legacy_config()
        assert readings.ev_connected is False
        assert readings.ev_charging is False

    def test_plug_on_doesnt_need_override(self):
        """When the plug sensor is honest, no override needed; charging power
        in the standby range (under 100 W) shouldn't matter."""
        reader = _build_reader(plug_state="on", charging_state="off", charging_power_w=10)
        readings = reader._read_from_legacy_config()
        assert readings.ev_connected is True

    def test_plug_off_but_charging_state_on_triggers_override(self):
        """The 2026-05-29 PROD repro shape — charging_state=on, plug lying off."""
        reader = _build_reader(
            plug_state="off", charging_state="on", charging_power_w=0,
        )
        readings = reader._read_from_legacy_config()
        assert readings.ev_connected is True, (
            "When ev_charging is True, ev_connected MUST be inferred True "
            "regardless of the plug sensor — current can't flow without a "
            "connection. PROD #285+1 regime."
        )

    def test_plug_off_but_power_over_100w_triggers_override(self):
        """The other half of the 2026-05-29 PROD repro — charging_state could
        also be lying off; the power sensor catches it."""
        reader = _build_reader(
            plug_state="off", charging_state="off", charging_power_w=4200,
        )
        readings = reader._read_from_legacy_config()
        assert readings.ev_connected is True, (
            "When ev_power > 100W, ev_connected MUST be inferred True. "
            "KEBA standby is ~50W; anything past 100W is real charging."
        )

    def test_standby_draw_under_100w_does_not_trigger_override(self):
        """KEBA's own standby consumption (~50 W) must NOT trigger the
        physics override — otherwise an unplugged-but-powered KEBA would
        falsely register as connected."""
        reader = _build_reader(
            plug_state="off", charging_state="off", charging_power_w=50,
        )
        readings = reader._read_from_legacy_config()
        assert readings.ev_connected is False
