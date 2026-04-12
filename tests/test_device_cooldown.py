"""Tests for power-change cooldown and daily runtime tracking on devices."""
import pytest
from datetime import date, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from custom_components.solar_energy_management.devices.base import (
    ControllableDevice,
    CurrentControlDevice,
    SetpointDevice,
    SwitchDevice,
    DeviceState,
)


@pytest.fixture
def hass():
    """Return a mocked Home Assistant instance."""
    h = MagicMock()
    h.config = MagicMock()
    h.config.config_dir = "/config"
    h.states = MagicMock()
    h.states.get = MagicMock(return_value=None)
    h.services = MagicMock()
    h.services.async_call = AsyncMock()
    return h


# --- Cooldown tests ---


class TestCooldownBlocksRapidAdjust:
    """Test that cooldown prevents rapid adjust_power calls."""

    @pytest.mark.asyncio
    async def test_cooldown_blocks_rapid_adjust(self, hass):
        """Two adjust_power calls within 30s: second returns unchanged."""
        dev = CurrentControlDevice(
            hass, "ev1", "EV Charger",
            min_current=6, max_current=16, phases=3, voltage=230,
            min_power_change_interval=30.0,
        )
        # Activate first
        await dev.activate(5000)
        assert dev.is_active

        # First adjust — should proceed
        result1 = await dev.adjust_power(8000)
        assert result1 > 0

        # Second adjust immediately — should be blocked by cooldown
        result2 = await dev.adjust_power(10000)
        assert result2 == result1  # unchanged

    @pytest.mark.asyncio
    async def test_cooldown_allows_after_interval(self, hass):
        """After cooldown elapses, adjust_power proceeds."""
        dev = CurrentControlDevice(
            hass, "ev1", "EV Charger",
            min_current=6, max_current=16, phases=3, voltage=230,
            min_power_change_interval=30.0,
        )
        await dev.activate(5000)

        # First adjust
        await dev.adjust_power(8000)

        # Fake the timestamp to 31s ago
        dev._last_power_change_time = datetime.now() - timedelta(seconds=31)

        # This should proceed
        old = dev._status.current_consumption_w
        result = await dev.adjust_power(3000)
        # Should have changed (different target current)
        assert result > 0

    @pytest.mark.asyncio
    async def test_activate_ignores_cooldown(self, hass):
        """activate() should work even during cooldown window."""
        dev = CurrentControlDevice(
            hass, "ev1", "EV Charger",
            min_current=6, max_current=16, phases=3, voltage=230,
            min_power_change_interval=30.0,
        )
        # Set a recent power change time
        dev._last_power_change_time = datetime.now()

        # activate should still work
        result = await dev.activate(5000)
        assert result > 0
        assert dev.is_active

    @pytest.mark.asyncio
    async def test_deactivate_ignores_cooldown(self, hass):
        """deactivate() should work even during cooldown window."""
        dev = CurrentControlDevice(
            hass, "ev1", "EV Charger",
            min_current=6, max_current=16, phases=3, voltage=230,
            min_power_change_interval=30.0,
        )
        await dev.activate(5000)
        # Set recent power change
        dev._last_power_change_time = datetime.now()

        # deactivate should still work
        await dev.deactivate()
        assert not dev.is_active


class TestSetpointCooldown:
    """Test SetpointDevice cooldown defaults."""

    def test_setpoint_default_300s(self, hass):
        """SetpointDevice should have 300s default cooldown."""
        dev = SetpointDevice(
            hass, "hp1", "Heat Pump",
            rated_power=2000,
        )
        assert dev._min_power_change_interval == 300.0

    def test_heat_pump_inherits_cooldown(self, hass):
        """HeatPumpController should inherit 300s cooldown."""
        from custom_components.solar_energy_management.devices.heat_pump_controller import (
            HeatPumpController,
        )
        dev = HeatPumpController(hass)
        assert dev._min_power_change_interval == 300.0


# --- Daily runtime tests ---


class TestDailyRuntime:
    """Test daily runtime tracking on ControllableDevice."""

    def _make_switch(self, hass, daily_min=3600):
        return SwitchDevice(
            hass, "hw1", "Hot Water", rated_power=2000,
            entity_id="switch.hot_water",
            daily_min_runtime_sec=daily_min,
        )

    def test_runtime_accumulates_when_active(self, hass):
        """Active device should accumulate runtime."""
        dev = self._make_switch(hass)
        dev._status.state = DeviceState.ACTIVE
        today = date(2026, 3, 21)

        t1 = datetime(2026, 3, 21, 12, 0, 0)
        t2 = datetime(2026, 3, 21, 12, 0, 10)

        with patch("custom_components.solar_energy_management.devices.base.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            dev.update_daily_runtime(today)

            mock_dt.now.return_value = t2
            dev.update_daily_runtime(today)

        assert dev._daily_runtime_accumulated_sec == pytest.approx(10.0, abs=0.1)

    def test_runtime_no_accumulate_when_idle(self, hass):
        """Idle device should not accumulate runtime."""
        dev = self._make_switch(hass)
        today = date(2026, 3, 21)

        t1 = datetime(2026, 3, 21, 12, 0, 0)
        t2 = datetime(2026, 3, 21, 12, 0, 10)

        with patch("custom_components.solar_energy_management.devices.base.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            dev.update_daily_runtime(today)

            mock_dt.now.return_value = t2
            dev.update_daily_runtime(today)

        assert dev._daily_runtime_accumulated_sec == 0.0

    def test_runtime_resets_on_meter_day_rollover(self, hass):
        """Runtime should reset when meter day changes."""
        dev = self._make_switch(hass)
        dev._status.state = DeviceState.ACTIVE
        day1 = date(2026, 3, 21)
        day2 = date(2026, 3, 22)

        t1 = datetime(2026, 3, 21, 12, 0, 0)
        t2 = datetime(2026, 3, 21, 12, 0, 10)
        t3 = datetime(2026, 3, 22, 7, 0, 0)

        with patch("custom_components.solar_energy_management.devices.base.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            dev.update_daily_runtime(day1)

            mock_dt.now.return_value = t2
            dev.update_daily_runtime(day1)

        assert dev._daily_runtime_accumulated_sec == pytest.approx(10.0, abs=0.1)

        # Now rollover
        with patch("custom_components.solar_energy_management.devices.base.datetime") as mock_dt:
            mock_dt.now.return_value = t3
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            dev.update_daily_runtime(day2)

        assert dev._daily_runtime_accumulated_sec == 0.0

    def test_runtime_ignores_large_jumps(self, hass):
        """Gaps > 120s should be ignored (restart recovery)."""
        dev = self._make_switch(hass)
        dev._status.state = DeviceState.ACTIVE
        today = date(2026, 3, 21)

        t1 = datetime(2026, 3, 21, 12, 0, 0)
        t2 = datetime(2026, 3, 21, 12, 5, 0)  # 300s gap

        with patch("custom_components.solar_energy_management.devices.base.datetime") as mock_dt:
            mock_dt.now.return_value = t1
            mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)
            dev.update_daily_runtime(today)

            mock_dt.now.return_value = t2
            dev.update_daily_runtime(today)

        assert dev._daily_runtime_accumulated_sec == 0.0

    def test_remaining_daily_runtime(self, hass):
        """Test remaining runtime calculation."""
        dev = self._make_switch(hass, daily_min=3600)
        dev._daily_runtime_accumulated_sec = 1800
        assert dev.remaining_daily_runtime_sec == 1800

    def test_needs_offpeak_true(self, hass):
        """Device with deficit, enabled, not active => needs off-peak."""
        dev = self._make_switch(hass, daily_min=3600)
        dev._daily_runtime_accumulated_sec = 1800
        assert dev.needs_offpeak_activation is True

    def test_needs_offpeak_false_target_met(self, hass):
        """Runtime target met => no off-peak needed."""
        dev = self._make_switch(hass, daily_min=3600)
        dev._daily_runtime_accumulated_sec = 3600
        assert dev.needs_offpeak_activation is False

    def test_needs_offpeak_false_disabled(self, hass):
        """Disabled device => no off-peak."""
        dev = self._make_switch(hass, daily_min=3600)
        dev._daily_runtime_accumulated_sec = 1800
        dev._enabled = False
        assert dev.needs_offpeak_activation is False

    def test_needs_offpeak_false_no_target(self, hass):
        """Target=0 => no off-peak."""
        dev = self._make_switch(hass, daily_min=0)
        assert dev.needs_offpeak_activation is False

    def test_daily_energy_budget(self, hass):
        """2000W rated, 3600s target => 2.0 kWh budget."""
        dev = self._make_switch(hass, daily_min=3600)
        assert dev.daily_energy_budget_kwh == pytest.approx(2.0)


class TestHotWaterOffpeakTemperature:
    """Test HotWaterController temperature-aware needs_offpeak_activation."""

    def test_hot_water_offpeak_respects_temperature(self, hass):
        """At max temp, needs_offpeak_activation should return False."""
        from custom_components.solar_energy_management.devices.hot_water_controller import (
            HotWaterController,
        )
        dev = HotWaterController(
            hass,
            temperature_entity_id="sensor.water_temp",
            max_temperature=60.0,
            daily_min_runtime_sec=3600,
        )
        dev._daily_runtime_accumulated_sec = 1800  # deficit exists

        # At max temp => is_temperature_safe() returns False
        state = MagicMock()
        state.state = "61.0"
        hass.states.get.return_value = state

        assert dev.needs_offpeak_activation is False

    def test_hot_water_offpeak_allows_when_cold(self, hass):
        """Below max temp, needs_offpeak_activation should return True."""
        from custom_components.solar_energy_management.devices.hot_water_controller import (
            HotWaterController,
        )
        dev = HotWaterController(
            hass,
            temperature_entity_id="sensor.water_temp",
            max_temperature=60.0,
            daily_min_runtime_sec=3600,
        )
        dev._daily_runtime_accumulated_sec = 1800

        state = MagicMock()
        state.state = "45.0"
        hass.states.get.return_value = state

        assert dev.needs_offpeak_activation is True
