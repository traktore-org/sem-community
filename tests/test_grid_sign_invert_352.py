"""Tests for the manual ``grid_sign_invert`` config option (#352).

When the auto-detect path can't stabilise on a given inverter (Enphase
has been the canonical case), the user can set ``grid_sign_invert:
True`` on the integration's options entry. The raw sensor read is then
negated unconditionally and the auto-detect path is bypassed entirely
(no vote counting, no baseline drift).
"""
from __future__ import annotations

from unittest.mock import MagicMock, Mock

import pytest

from custom_components.solar_energy_management.coordinator.sensor_reader import (
    SensorReader,
)


def _state(value, unit="W"):
    s = Mock()
    s.state = str(value)
    s.attributes = {"unit_of_measurement": unit}
    return s


def _ed_config(grid_power="sensor.grid_power"):
    ed = Mock()
    ed.solar_power = None
    ed.solar_power_list = []
    ed.battery_power = None
    ed.battery_power_list = []
    ed.battery_charge_energy = None
    ed.battery_discharge_energy = None
    ed.battery_charge_energy_list = []
    ed.battery_discharge_energy_list = []
    ed.grid_power = grid_power
    ed.grid_import_power = grid_power
    ed.grid_power_list = [grid_power]
    ed.grid_import_energy = None
    ed.grid_export_energy = None
    ed.ev_power = None
    ed.ev_energy = None
    ed.ev_chargers = []
    ed.has_battery = False
    ed.has_solar = False
    ed.has_grid = True
    ed.has_ev = False
    return ed


@pytest.fixture
def mock_hass():
    hass = MagicMock()
    hass.states = MagicMock()
    return hass


class TestGridSignInvertOption:
    """The manual override negates ``grid_power`` and bypasses auto-detect."""

    def test_invert_off_default_behaviour(self, mock_hass):
        """With the flag off (default) auto-detect runs as before."""
        mock_hass.states.get = lambda eid: _state(2000) if eid == "sensor.grid_power" else None
        reader = SensorReader(mock_hass, {})  # no grid_sign_invert key
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(_ed_config())

        readings = reader.read_power()

        # Auto-detect path: with no Energy Dashboard import/export
        # counters configured, _detect_grid_sign returns False, so the
        # raw read is preserved.
        assert readings.grid_power == 2000

    def test_invert_on_negates_grid_power(self, mock_hass):
        """``grid_sign_invert: True`` flips a positive read to negative."""
        mock_hass.states.get = lambda eid: _state(2000) if eid == "sensor.grid_power" else None
        reader = SensorReader(mock_hass, {"grid_sign_invert": True})
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(_ed_config())

        readings = reader.read_power()

        # Manual override applied: SEM convention is -import / +export,
        # the inverter reported +import (2000), so the result is -2000.
        assert readings.grid_power == -2000

    def test_invert_on_negates_negative_read(self, mock_hass):
        """A negative raw read flips to positive (export under SEM)."""
        mock_hass.states.get = lambda eid: _state(-1500) if eid == "sensor.grid_power" else None
        reader = SensorReader(mock_hass, {"grid_sign_invert": True})
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(_ed_config())

        readings = reader.read_power()

        assert readings.grid_power == 1500

    def test_invert_on_skips_autodetect_vote(self, mock_hass):
        """Auto-detect state is not touched when the manual override fires."""
        mock_hass.states.get = lambda eid: _state(2000) if eid == "sensor.grid_power" else None
        reader = SensorReader(mock_hass, {"grid_sign_invert": True})
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(_ed_config())

        # Pre-conditions: auto-detect state untouched.
        assert reader._grid_sign_votes == 0
        assert reader._grid_sign_detected is False

        # Run several cycles.
        for _ in range(5):
            reader.read_power()

        # Post-conditions: auto-detect votes and the "detected" flag are
        # still at their initial values because the manual override
        # bypassed _detect_grid_sign() entirely.
        assert reader._grid_sign_votes == 0
        assert reader._grid_sign_detected is False
        assert reader._grid_sign_inverted is False

    def test_invert_zero_is_zero(self, mock_hass):
        """0 → 0 under negation."""
        mock_hass.states.get = lambda eid: _state(0) if eid == "sensor.grid_power" else None
        reader = SensorReader(mock_hass, {"grid_sign_invert": True})
        reader._sign_vote_warmup = 0
        reader.set_energy_dashboard_config(_ed_config())

        readings = reader.read_power()

        # ``-0.0 == 0.0`` so the comparison is fine; we just want no
        # crash and no spurious sign flip artefact.
        assert readings.grid_power == 0
