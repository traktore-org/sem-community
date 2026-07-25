"""Tests for UtilitySignalMonitor ripple control signal handling."""
import logging

import pytest
from unittest.mock import MagicMock

from custom_components.solar_energy_management.utility_signals import (
    UtilitySignalMonitor,
    UtilitySignalData,
)


def _make_state(state_value):
    """Create a mock HA state object."""
    mock_state = MagicMock()
    mock_state.state = state_value
    return mock_state


class TestUtilitySignalInit:
    """Test UtilitySignalMonitor initialization."""

    def test_init_defaults(self, mock_hass):
        monitor = UtilitySignalMonitor(mock_hass)
        assert monitor.signal_entity_id is None
        assert monitor.solar_loads_exempt is True
        assert monitor.is_signal_active is False
        assert monitor._was_active is False
        data = monitor.signal_data
        assert data.signal_active is False
        assert data.signal_count_today == 0

    def test_init_with_entity(self, mock_hass):
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.signal_entity_id == "binary_sensor.ripple"

    def test_init_solar_exempt_false(self, mock_hass):
        monitor = UtilitySignalMonitor(mock_hass, solar_loads_exempt=False)
        assert monitor.solar_loads_exempt is False


class TestIsSignalActive:
    """Test is_signal_active property."""

    def test_is_signal_active_on(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is True

    def test_is_signal_active_true(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("true"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is True

    def test_is_signal_active_1(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("1"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is True

    def test_is_signal_active_active(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("active"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is True

    def test_is_signal_active_off(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("off"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is False

    def test_is_signal_active_no_entity(self, mock_hass):
        monitor = UtilitySignalMonitor(mock_hass)
        assert monitor.is_signal_active is False

    def test_is_signal_active_unavailable(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("unavailable"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is False

    def test_is_signal_active_entity_none(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=None)
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert monitor.is_signal_active is False


class TestUtilitySignalUpdate:
    """Test update() method."""

    def test_update_signal_start(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        data = monitor.update()
        assert data.signal_active is True
        assert data.signal_count_today == 1
        assert data.last_signal_start is not None
        assert data.signal_source == "ripple_control"

    def test_update_signal_end(self, mock_hass):
        # Start active
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        monitor.update()  # Signal starts
        # Now deactivate
        mock_hass.states.get = MagicMock(return_value=_make_state("off"))
        data = monitor.update()
        assert data.signal_active is False
        assert data.last_signal_end is not None

    def test_update_no_change(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("off"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        data1 = monitor.update()
        data2 = monitor.update()
        assert data2.signal_count_today == 0
        assert data2.last_signal_start is None

    def test_multiple_signals_per_day(self, mock_hass):
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        # Signal 1
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor.update()
        mock_hass.states.get = MagicMock(return_value=_make_state("off"))
        monitor.update()
        # Signal 2
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor.update()
        mock_hass.states.get = MagicMock(return_value=_make_state("off"))
        monitor.update()
        assert monitor.signal_data.signal_count_today == 2


class TestTheMonitorDoesNotClaimToShed654:
    """#654 — this monitor observes and reports. It must not say otherwise.

    ``TestGetDevicesToBlock`` used to live here: four tests proving that
    ``get_devices_to_block`` picked the right devices, passing green for
    eight releases while nothing in production ever called it. They are the
    reason the feature read as shipped. The method is gone (#664 re-adds it
    with the wiring); what replaces its tests is an assertion that the
    surface makes no claim it cannot keep.
    """

    def test_the_blocking_surface_is_gone(self, mock_hass):
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        assert not hasattr(monitor, "get_devices_to_block"), (
            "blocking was re-added without wiring — see #664"
        )
        assert "utility_loads_blocked" not in monitor.signal_data.to_dict()
        assert "utility_block_path" not in monitor.signal_data.to_dict()

    def test_the_active_log_does_not_claim_shedding(self, mock_hass, caplog):
        """The old WARNING read 'shedding non-critical loads'. A user with a
        ripple-control contract would take that as confirmation of
        compliance, and it was false."""
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        with caplog.at_level(logging.WARNING):
            monitor.update()
        assert "ACTIVE" in caplog.text, "the signal must still be reported"
        assert "shedding non-critical loads" not in caplog.text
        assert "no loads are being shed" in caplog.text

    def test_the_docstrings_do_not_claim_an_integration(self):
        """The class docstring claimed SurplusController integration that
        grep proved absent."""
        import custom_components.solar_energy_management.utility_signals as mod

        assert "does not shed" in mod.__doc__.lower()
        assert "integrates with surpluscontroller" not in (
            UtilitySignalMonitor.__doc__ or ""
        ).lower()


class TestResetDailyCounters:
    """Test reset_daily_counters() method."""

    def test_reset_daily_counters(self, mock_hass):
        mock_hass.states.get = MagicMock(return_value=_make_state("on"))
        monitor = UtilitySignalMonitor(mock_hass, signal_entity_id="binary_sensor.ripple")
        monitor.update()
        assert monitor.signal_data.signal_count_today == 1
        monitor.reset_daily_counters()
        assert monitor.signal_data.signal_count_today == 0


class TestSignalDataSerialization:
    """Test UtilitySignalData.to_dict()."""

    def test_signal_data_to_dict(self):
        data = UtilitySignalData(
            signal_active=True,
            signal_source="ripple_control",
            signal_count_today=3,
            solar_loads_exempt=True,
        )
        d = data.to_dict()
        assert d["utility_signal_active"] is True
        assert d["utility_signal_source"] == "ripple_control"
        assert d["utility_signal_count_today"] == 3
        assert d["utility_solar_exempt"] is True
