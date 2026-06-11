"""#487 — Wallbox number-entity range fixes + restart sign-vote warmup.

RienduPre's log: 167× per charger ``Failed to set current: out_of_range``
— SEM wrote 0 A (stop) and >entity-max amps to Wallbox max-current
number entities; HA core rejects both BEFORE anything reaches the
charger. Plus the live 2026-06-11 PROD grid-sign flip from restart
window votes, and 413× health-check WARNING spam.
"""
import logging
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.devices.base import (
    CurrentControlDevice,
)
from custom_components.solar_energy_management.coordinator.charger_adapters.wallbox import (
    WallboxAdapter,
)
from custom_components.solar_energy_management.coordinator.health_check import (
    HealthCheck,
)


def _number_state(min_a=6.0, max_a=16.0):
    state = MagicMock()
    state.attributes = {"min": min_a, "max": max_a, "step": 1.0}
    return state


def _device(**kwargs):
    hass = MagicMock()
    hass.services.async_call = AsyncMock()
    defaults = dict(
        hass=hass, device_id="wb", name="Laadpaal Links",
        min_current=6.0, max_current=32.0, phases=3,
    )
    defaults.update(kwargs)
    return CurrentControlDevice(**defaults)


@pytest.mark.unit
class TestEntityRangeBounds:
    @pytest.mark.asyncio
    async def test_zero_stop_skips_write_on_min6_entity(self):
        dev = _device(current_entity_id="number.wallbox_links_max_charging_current")
        dev.hass.states.get = MagicMock(return_value=_number_state(6.0, 16.0))
        consumed = await dev._set_current(0)
        dev.hass.services.async_call.assert_not_awaited()
        assert consumed == 0.0
        assert dev._current_setpoint == 0

    @pytest.mark.asyncio
    async def test_above_entity_max_is_clamped(self):
        # Links: entity range 6-16 while SEM's configured max is 32.
        dev = _device(current_entity_id="number.wallbox_links_max_charging_current")
        dev.hass.states.get = MagicMock(return_value=_number_state(6.0, 16.0))
        await dev._set_current(32)
        call = dev.hass.services.async_call.await_args
        assert call.args[2]["value"] == 16

    @pytest.mark.asyncio
    async def test_below_entity_min_clamps_up(self):
        dev = _device(current_entity_id="number.wallbox_links_max_charging_current")
        dev.hass.states.get = MagicMock(return_value=_number_state(6.0, 16.0))
        await dev._set_current(4)
        call = dev.hass.services.async_call.await_args
        assert call.args[2]["value"] == 6

    @pytest.mark.asyncio
    async def test_unreadable_entity_leaves_command_untouched(self):
        dev = _device(current_entity_id="number.wallbox_links_max_charging_current")
        dev.hass.states.get = MagicMock(return_value=None)
        await dev._set_current(10)
        call = dev.hass.services.async_call.await_args
        assert call.args[2]["value"] == 10

    @pytest.mark.asyncio
    async def test_zero_on_entity_allowing_zero_still_writes(self):
        dev = _device(current_entity_id="number.charger_current")
        dev.hass.states.get = MagicMock(return_value=_number_state(0.0, 32.0))
        await dev._set_current(0)
        call = dev.hass.services.async_call.await_args
        assert call.args[2]["value"] == 0

    @pytest.mark.asyncio
    async def test_entity_service_shape_also_bounded(self):
        dev = _device(
            charger_service="number.set_value",
            current_entity_id="number.wallbox_links_max_charging_current",
        )
        dev.hass.states.get = MagicMock(return_value=_number_state(6.0, 16.0))
        await dev._set_current(0)
        dev.hass.services.async_call.assert_not_awaited()


@pytest.mark.unit
class TestWallboxConfiguredStopSwitch:
    def test_configured_start_stop_entity_wins(self):
        dev = _device(current_entity_id="number.wallbox_links_max_charging_current")
        dev.start_stop_entity = "switch.wallbox_links_pause_resume"
        adapter = WallboxAdapter(dev)
        assert adapter._discover_pause_switch() == "switch.wallbox_links_pause_resume"

    def test_non_switch_config_falls_through_to_discovery(self):
        dev = _device(current_entity_id="number.wallbox_links_max_charging_current")
        dev.start_stop_entity = "button.wallbox_links_resume"
        dev.hass = None  # discovery aborts cleanly
        adapter = WallboxAdapter(dev)
        assert adapter._discover_pause_switch() is None


@pytest.mark.unit
class TestHealthCheckLogRateLimit:
    def test_warning_drops_to_debug_after_streak(self, caplog):
        hc = HealthCheck()
        power = MagicMock(
            solar_power=1000.0, grid_import_power=0.0,
            battery_discharge_power=0.0, home_consumption_power=5000.0,
            ev_power=0.0, grid_export_power=0.0, battery_charge_power=0.0,
        )
        with caplog.at_level(logging.DEBUG):
            for _ in range(hc._WARN_CYCLES + 4):
                hc.run_all_checks(power)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING
                    and "Health check violation:" in r.message]
        assert len(warnings) == hc._WARN_CYCLES
        # the violations keep counting even while quiet
        assert hc.total_violations >= hc._WARN_CYCLES + 4

    def test_streak_resets_when_clean(self, caplog):
        hc = HealthCheck()
        bad = MagicMock(
            solar_power=1000.0, grid_import_power=0.0,
            battery_discharge_power=0.0, home_consumption_power=5000.0,
            ev_power=0.0, grid_export_power=0.0, battery_charge_power=0.0,
        )
        good = MagicMock(
            solar_power=1000.0, grid_import_power=0.0,
            battery_discharge_power=0.0, home_consumption_power=1000.0,
            ev_power=0.0, grid_export_power=0.0, battery_charge_power=0.0,
        )
        with caplog.at_level(logging.DEBUG):
            for _ in range(hc._WARN_CYCLES + 2):
                hc.run_all_checks(bad)
            hc.run_all_checks(good)
            caplog.clear()
            hc.run_all_checks(bad)
        warnings = [r for r in caplog.records if r.levelno == logging.WARNING]
        assert warnings  # WARNING level again after a clean cycle


@pytest.mark.unit
class TestSignVoteWarmup:
    """#487 follow-up: live PROD grid-sign flip from restart-window votes."""

    def _reader(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        from custom_components.solar_energy_management.coordinator.types import (
            PowerReadings,
        )
        hass = MagicMock()
        reader = SensorReader(hass, {})
        ed = MagicMock()
        ed.grid_import_energy = "sensor.grid_import_total"
        ed.grid_export_energy = "sensor.grid_export_total"
        ed.grid_import_energy_list = ["sensor.grid_import_total"]
        ed.grid_export_energy_list = ["sensor.grid_export_total"]
        reader._energy_dashboard_config = ed
        states = {}
        hass.states.get = lambda eid: states.get(eid)

        def set_counters(imp, exp):
            for eid, v in (("sensor.grid_import_total", imp),
                           ("sensor.grid_export_total", exp)):
                s = MagicMock()
                s.state = str(v)
                s.attributes = {"unit_of_measurement": "kWh"}
                states[eid] = s
        return reader, set_counters, PowerReadings

    def test_no_votes_during_warmup(self):
        reader, set_counters, PowerReadings = self._reader()
        assert reader._sign_vote_warmup > 0  # armed at construction
        set_counters(100.0, 50.0)
        reader._detect_grid_sign(PowerReadings(grid_power=800.0))
        # import counter climbing while power positive would normally
        # vote "negate" — warmup must swallow it.
        for step in range(1, 5):
            set_counters(100.0 + step * 0.1, 50.0)
            result = reader._detect_grid_sign(PowerReadings(grid_power=800.0))
        assert result is False
        assert reader._grid_sign_votes == 0
        assert reader._grid_sign_detected is False

    def test_votes_resume_after_warmup(self):
        reader, set_counters, PowerReadings = self._reader()
        reader._sign_vote_warmup = 0
        set_counters(100.0, 50.0)
        reader._detect_grid_sign(PowerReadings(grid_power=800.0))  # baseline
        for step in range(1, 4):
            set_counters(100.0 + step * 0.1, 50.0)
            result = reader._detect_grid_sign(PowerReadings(grid_power=800.0))
        assert result is True  # locked after 3 consistent votes
        assert reader._grid_sign_detected is True

    def test_read_power_decrements_warmup(self):
        from custom_components.solar_energy_management.coordinator.sensor_reader import (
            SensorReader,
        )
        hass = MagicMock()
        hass.states.get = MagicMock(return_value=None)
        reader = SensorReader(hass, {})
        reader._energy_dashboard_config = None
        before = reader._sign_vote_warmup
        reader.read_power()
        assert reader._sign_vote_warmup == before - 1
