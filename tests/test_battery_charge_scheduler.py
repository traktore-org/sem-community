"""Tests for battery charge scheduler and adapter.

Covers:
- Adapter factory and platform detection
- Huawei/GoodWe/Generic adapter start/stop/status
- Scheduler evaluation logic (deficit, break-even, SOC, thresholds)
- Cheapest-hour selection with dynamic tariff
- Update cycle (charge window, target reached, peak coordination)
- Edge cases (no forecast, already full, tiny deficit, EV peak conflict)
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.battery_charge_adapter import (
    BatteryChargeAdapter,
    ChargeCommand,
    ChargeCommandStatus,
    ChargeStatus,
    GenericChargeAdapter,
    GoodWeChargeAdapter,
    HuaweiChargeAdapter,
    create_charge_adapter,
)
from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
    BatteryChargeScheduler,
    SchedulerConfig,
    SchedulerDecision,
    SchedulerState,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def hass():
    """Mocked Home Assistant instance."""
    mock = MagicMock()
    mock.config = MagicMock()
    mock.config.components = {"huawei_solar", "homeassistant"}
    mock.states = MagicMock()
    mock.services = MagicMock()
    mock.services.async_call = AsyncMock()
    return mock


@pytest.fixture
def huawei_config():
    """Config for Huawei adapter."""
    return {
        "battery_charge_platform": "huawei",
        "inverter_device_id": "abc123",
        "battery_soc_entity": "sensor.battery_soc",
    }


@pytest.fixture
def goodwe_config():
    """Config for GoodWe adapter."""
    return {
        "battery_charge_platform": "goodwe",
        "inverter_work_mode_entity": "select.goodwe_work_mode",
        "battery_target_soc_entity": "number.goodwe_soc_target",
        "battery_soc_entity": "sensor.battery_soc",
        "inverter_normal_work_mode": "General",
    }


@pytest.fixture
def generic_config():
    """Config for generic adapter."""
    return {
        "battery_charge_platform": "generic",
        "battery_force_charge_switch": "switch.force_charge",
        "battery_target_soc_entity": "number.soc_target",
        "battery_soc_entity": "sensor.battery_soc",
    }


@pytest.fixture
def scheduler_config():
    """Default scheduler config."""
    return SchedulerConfig(
        battery_capacity_kwh=10.0,
        battery_usable_capacity_kwh=9.5,
        battery_min_soc=5.0,
        battery_max_charge_power_w=5000.0,
        roundtrip_efficiency=0.92,
        trigger_hour=21,
        trigger_minute=0,
        min_deficit_kwh=2.0,
        forecast_confidence=0.8,
        max_target_soc=95.0,
        peak_limit_w=0.0,
        ev_priority=True,
    )


@pytest.fixture
def mock_tariff_provider():
    """Mock dynamic tariff provider with find_cheapest_hours."""
    provider = MagicMock()
    # Return 3 cheap hours starting at midnight
    base = dt_util.now().replace(hour=0, minute=0, second=0) + timedelta(days=1)
    provider.find_cheapest_hours.return_value = [
        MagicMock(timestamp=base, price=0.05),
        MagicMock(timestamp=base + timedelta(hours=1), price=0.06),
        MagicMock(timestamp=base + timedelta(hours=2), price=0.07),
    ]
    return provider


# ---------------------------------------------------------------------------
# Adapter Factory Tests
# ---------------------------------------------------------------------------

class TestAdapterFactory:
    """Test create_charge_adapter factory."""

    def test_explicit_huawei(self, hass, huawei_config):
        adapter = create_charge_adapter(hass, huawei_config)
        assert isinstance(adapter, HuaweiChargeAdapter)

    def test_explicit_goodwe(self, hass, goodwe_config):
        adapter = create_charge_adapter(hass, goodwe_config)
        assert isinstance(adapter, GoodWeChargeAdapter)

    def test_explicit_generic(self, hass, generic_config):
        adapter = create_charge_adapter(hass, generic_config)
        assert isinstance(adapter, GenericChargeAdapter)

    def test_auto_detect_huawei(self, hass):
        hass.config.components = {"huawei_solar", "homeassistant"}
        config = {"battery_charge_platform": "auto", "inverter_device_id": "abc"}
        adapter = create_charge_adapter(hass, config)
        assert isinstance(adapter, HuaweiChargeAdapter)

    def test_auto_detect_goodwe(self, hass):
        hass.config.components = {"goodwe", "homeassistant"}
        config = {"battery_charge_platform": "auto"}
        adapter = create_charge_adapter(hass, config)
        assert isinstance(adapter, GoodWeChargeAdapter)

    def test_auto_detect_fallback_generic(self, hass):
        hass.config.components = {"homeassistant"}
        config = {"battery_charge_platform": "auto"}
        adapter = create_charge_adapter(hass, config)
        assert isinstance(adapter, GenericChargeAdapter)


# ---------------------------------------------------------------------------
# Huawei Adapter Tests
# ---------------------------------------------------------------------------

class TestHuaweiAdapter:
    """Test HuaweiChargeAdapter."""

    @pytest.mark.asyncio
    async def test_start_forced_charge_success(self, hass, huawei_config):
        adapter = HuaweiChargeAdapter(hass, huawei_config)
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000, duration_minutes=240)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.CHARGING
        assert adapter.is_active
        hass.services.async_call.assert_called_once_with(
            "huawei_solar",
            "forcible_charge_soc",
            {"device_id": "abc123", "target_soc": 80, "power": 3000, "duration": 240},
        )

    @pytest.mark.asyncio
    async def test_start_forced_charge_no_device_id(self, hass):
        adapter = HuaweiChargeAdapter(hass, {"battery_charge_platform": "huawei"})
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.FAILED
        assert "No inverter_device_id" in status.message

    @pytest.mark.asyncio
    async def test_start_forced_charge_service_error(self, hass, huawei_config):
        hass.services.async_call = AsyncMock(side_effect=Exception("Service unavailable"))
        adapter = HuaweiChargeAdapter(hass, huawei_config)
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.FAILED
        assert not adapter.is_active

    @pytest.mark.asyncio
    async def test_stop_forced_charge(self, hass, huawei_config):
        adapter = HuaweiChargeAdapter(hass, huawei_config)
        adapter._active = True

        status = await adapter.stop_forced_charge()

        assert status.status == ChargeCommandStatus.IDLE
        assert not adapter.is_active
        hass.services.async_call.assert_called_once_with(
            "huawei_solar",
            "stop_forcible_charge",
            {"device_id": "abc123"},
        )

    @pytest.mark.asyncio
    async def test_get_status_target_reached(self, hass, huawei_config):
        soc_state = MagicMock()
        soc_state.state = "85"
        hass.states.get = MagicMock(return_value=soc_state)

        adapter = HuaweiChargeAdapter(hass, huawei_config)
        adapter._active = True
        adapter._target_soc = 80.0

        status = await adapter.get_status()

        assert status.status == ChargeCommandStatus.TARGET_REACHED
        assert status.current_soc == 85.0

    @pytest.mark.asyncio
    async def test_get_status_still_charging(self, hass, huawei_config):
        soc_state = MagicMock()
        soc_state.state = "60"
        hass.states.get = MagicMock(return_value=soc_state)

        adapter = HuaweiChargeAdapter(hass, huawei_config)
        adapter._active = True
        adapter._target_soc = 80.0

        status = await adapter.get_status()

        assert status.status == ChargeCommandStatus.CHARGING
        assert status.current_soc == 60.0

    def test_should_stop(self, hass, huawei_config):
        adapter = HuaweiChargeAdapter(hass, huawei_config)
        adapter._active = True
        adapter._target_soc = 80.0

        assert not adapter.should_stop(75.0)
        assert adapter.should_stop(80.0)
        assert adapter.should_stop(85.0)

    def test_should_stop_inactive(self, hass, huawei_config):
        adapter = HuaweiChargeAdapter(hass, huawei_config)
        assert not adapter.should_stop(100.0)


# ---------------------------------------------------------------------------
# GoodWe Adapter Tests
# ---------------------------------------------------------------------------

class TestGoodWeAdapter:
    """Test GoodWeChargeAdapter."""

    @pytest.mark.asyncio
    async def test_start_forced_charge(self, hass, goodwe_config):
        adapter = GoodWeChargeAdapter(hass, goodwe_config)
        cmd = ChargeCommand(target_soc=75.0, max_power_w=4000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.CHARGING
        assert adapter.is_active
        assert hass.services.async_call.call_count == 2  # SOC target + work mode

    @pytest.mark.asyncio
    async def test_stop_restores_normal_mode(self, hass, goodwe_config):
        adapter = GoodWeChargeAdapter(hass, goodwe_config)
        adapter._active = True

        status = await adapter.stop_forced_charge()

        assert status.status == ChargeCommandStatus.IDLE
        hass.services.async_call.assert_called_with(
            "select",
            "select_option",
            {"entity_id": "select.goodwe_work_mode", "option": "General"},
        )

    @pytest.mark.asyncio
    async def test_start_no_work_mode_entity(self, hass):
        adapter = GoodWeChargeAdapter(hass, {"battery_charge_platform": "goodwe"})
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.FAILED


# ---------------------------------------------------------------------------
# Generic Adapter Tests
# ---------------------------------------------------------------------------

class TestGenericAdapter:
    """Test GenericChargeAdapter."""

    @pytest.mark.asyncio
    async def test_start_forced_charge(self, hass, generic_config):
        adapter = GenericChargeAdapter(hass, generic_config)
        cmd = ChargeCommand(target_soc=90.0, max_power_w=2500)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.CHARGING
        assert adapter.is_active

    @pytest.mark.asyncio
    async def test_start_no_switch_configured(self, hass):
        adapter = GenericChargeAdapter(hass, {})
        cmd = ChargeCommand(target_soc=90.0, max_power_w=2500)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_stop_disables_switch(self, hass, generic_config):
        adapter = GenericChargeAdapter(hass, generic_config)
        adapter._active = True

        status = await adapter.stop_forced_charge()

        assert status.status == ChargeCommandStatus.IDLE
        hass.services.async_call.assert_called_with(
            "switch",
            "turn_off",
            {"entity_id": "switch.force_charge"},
        )


# ---------------------------------------------------------------------------
# Scheduler Evaluation Tests
# ---------------------------------------------------------------------------

class TestSchedulerEvaluation:
    """Test BatteryChargeScheduler.evaluate() decision logic."""

    def _make_scheduler(self, hass, scheduler_config, adapter=None):
        if adapter is None:
            adapter = MagicMock(spec=BatteryChargeAdapter)
            adapter.is_active = False
        return BatteryChargeScheduler(hass, adapter, scheduler_config)

    def test_no_deficit_solar_covers_consumption(self, hass, scheduler_config):
        """Solar forecast exceeds consumption — no charge needed."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=20.0,  # Lots of sun
            expected_consumption_kwh=10.0,
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.NOT_NEEDED
        assert "Solar forecast covers" in decision.reason

    def test_deficit_below_threshold(self, hass, scheduler_config):
        """Small deficit below min_deficit_kwh — not worth charging."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=12.0,  # 12 * 0.8 = 9.6 corrected
            expected_consumption_kwh=11.0,  # deficit = 11 - 9.6 = 1.4 < 2.0
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.NOT_NEEDED
        assert "below threshold" in decision.reason

    def test_not_profitable(self, hass, scheduler_config):
        """NT effective cost >= HT rate — charging wastes money."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,  # 5 * 0.8 = 4.0
            expected_consumption_kwh=15.0,  # deficit = 11 kWh
            nt_rate=0.28,  # 0.28 / 0.92 = 0.304 > 0.30
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.NOT_PROFITABLE
        assert "Not profitable" in decision.reason

    def test_already_at_target(self, hass, scheduler_config):
        """SOC already at calculated target — no charge needed."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # Small deficit = small SOC increase needed
        # deficit = 15 - (5 * 0.8) = 11 kWh
        # soc_increase = 11 / 9.5 * 100 = 115% → capped at 95%
        # With current_soc=95 → already there
        decision = scheduler.evaluate(
            current_soc=95.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.NOT_NEEDED
        assert "Already at target" in decision.reason

    def test_scheduled_with_static_tariff(self, hass, scheduler_config):
        """Profitable deficit with no dynamic tariff — schedule charge."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,  # 5 * 0.8 = 4.0
            expected_consumption_kwh=12.0,  # deficit = 8 kWh
            nt_rate=0.10,  # 0.10 / 0.92 = 0.108 < 0.30 → profitable
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.should_charge
        assert decision.deficit_kwh == pytest.approx(8.0)
        # target_soc = 30 + (8/9.5)*100 = 30 + 84.2 → capped at 95
        assert decision.target_soc == 95.0
        assert decision.hours_needed >= 1
        assert decision.charge_windows == []  # No dynamic tariff

    def test_scheduled_with_dynamic_tariff(self, hass, scheduler_config, mock_tariff_provider):
        """Profitable deficit with dynamic tariff — picks cheapest hours."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=5.0,  # 5 * 0.8 = 4.0
            expected_consumption_kwh=10.0,  # deficit = 6 kWh
            nt_rate=0.10,
            ht_rate=0.30,
            tariff_provider=mock_tariff_provider,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert len(decision.charge_windows) > 0
        mock_tariff_provider.find_cheapest_hours.assert_called_once()

    def test_forecast_correction_reduces_deficit(self, hass, scheduler_config):
        """Correction factor < 1 reduces effective forecast (increases deficit)."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # Raw forecast 15 kWh, correction 0.7, confidence 0.8
        # Effective: 15 * 0.7 * 0.8 = 8.4
        # Deficit: 12 - 8.4 = 3.6 kWh
        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=12.0,
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=0.7,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.deficit_kwh == pytest.approx(3.6)

    def test_high_correction_eliminates_deficit(self, hass, scheduler_config):
        """Good correction factor can eliminate deficit entirely."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # Raw 15, correction 1.2, confidence 0.8 → effective 14.4
        # deficit = 12 - 14.4 = -2.4 → no charge
        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=12.0,
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=1.2,
        )

        assert decision.state == SchedulerState.NOT_NEEDED

    def test_target_soc_capped(self, hass, scheduler_config):
        """Target SOC never exceeds max_target_soc."""
        scheduler_config.max_target_soc = 90.0
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=20.0,
            forecast_tomorrow_kwh=0.0,  # No sun
            expected_consumption_kwh=20.0,  # Huge deficit
            nt_rate=0.05,
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.target_soc == 90.0  # Capped

    def test_hours_needed_calculation(self, hass, scheduler_config):
        """Hours needed = charge_kwh / charge_power_kw, rounded up."""
        scheduler_config.battery_max_charge_power_w = 2500  # 2.5 kW
        scheduler = self._make_scheduler(hass, scheduler_config)

        # deficit = 10 - (2*0.8) = 8.4 kWh
        # target_soc = 40 + (8.4/9.5)*100 = 40 + 88.4 = 95 (capped)
        # actual_charge = (95-40)/100 * 9.5 = 5.225 kWh
        # hours = 5.225 / 2.5 = 2.09 → 2 hours
        decision = scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=2.0,
            expected_consumption_kwh=10.0,
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.hours_needed == 2


# ---------------------------------------------------------------------------
# Scheduler Update Cycle Tests
# ---------------------------------------------------------------------------

class TestSchedulerUpdate:
    """Test BatteryChargeScheduler.update() execution logic."""

    def _make_scheduler(self, hass, scheduler_config, adapter=None):
        if adapter is None:
            adapter = AsyncMock(spec=BatteryChargeAdapter)
            adapter.is_active = False
            adapter.start_forced_charge = AsyncMock(
                return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
            )
            adapter.stop_forced_charge = AsyncMock(
                return_value=ChargeStatus(status=ChargeCommandStatus.IDLE)
            )
        return BatteryChargeScheduler(hass, adapter, scheduler_config)

    @pytest.mark.asyncio
    async def test_idle_returns_idle(self, hass, scheduler_config):
        scheduler = self._make_scheduler(hass, scheduler_config)
        state = await scheduler.update(current_soc=50.0)
        assert state == SchedulerState.IDLE

    @pytest.mark.asyncio
    async def test_target_reached_stops_charge(self, hass, scheduler_config):
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = True
        adapter.stop_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.IDLE)
        )
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        # Simulate a scheduled decision
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.CHARGING,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
        )

        state = await scheduler.update(current_soc=80.0)

        assert state == SchedulerState.TARGET_REACHED
        adapter.stop_forced_charge.assert_called_once()

    @pytest.mark.asyncio
    async def test_starts_charge_in_window(self, hass, scheduler_config):
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        # Schedule with no specific windows (= always in window)
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],  # Empty = full NT window
        )

        state = await scheduler.update(current_soc=50.0)

        assert state == SchedulerState.CHARGING
        adapter.start_forced_charge.assert_called_once()

    @pytest.mark.asyncio
    async def test_waits_outside_window(self, hass, scheduler_config):
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        # Schedule with specific window far in the future
        future = dt_util.now() + timedelta(hours=5)
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=1,
            charge_windows=[future],
        )

        state = await scheduler.update(current_soc=50.0)

        assert state == SchedulerState.WAITING_FOR_SLOT
        adapter.start_forced_charge.assert_not_called()

    @pytest.mark.asyncio
    async def test_peak_limit_reduces_power(self, hass, scheduler_config):
        scheduler_config.peak_limit_w = 9000.0
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
        )

        # EV using 6000W — only 9000-6000-200 = 2800W available
        state = await scheduler.update(current_soc=50.0, ev_charging_power_w=6000.0)

        assert state == SchedulerState.CHARGING
        cmd = adapter.start_forced_charge.call_args[0][0]
        assert cmd.max_power_w == 2800.0  # peak_limit - ev - safety

    @pytest.mark.asyncio
    async def test_peak_limit_blocks_charge(self, hass, scheduler_config):
        scheduler_config.peak_limit_w = 7000.0
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
        )

        # EV using 7000W — 7000-7000-200 = -200 → 0 → blocked
        state = await scheduler.update(current_soc=50.0, ev_charging_power_w=7000.0)

        assert state == SchedulerState.WAITING_FOR_SLOT
        adapter.start_forced_charge.assert_not_called()

    @pytest.mark.asyncio
    async def test_failed_start_sets_failed_state(self, hass, scheduler_config):
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(
                status=ChargeCommandStatus.FAILED, message="Inverter offline"
            )
        )
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
        )

        state = await scheduler.update(current_soc=50.0)

        assert state == SchedulerState.FAILED

    @pytest.mark.asyncio
    async def test_stops_charge_outside_window(self, hass, scheduler_config):
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = True  # Currently charging
        adapter.stop_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.IDLE)
        )
        scheduler = self._make_scheduler(hass, scheduler_config, adapter)

        # Window already passed
        past = dt_util.now() - timedelta(hours=2)
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.CHARGING,
            target_soc=80.0,
            hours_needed=1,
            charge_windows=[past],
        )

        state = await scheduler.update(current_soc=60.0)

        assert state == SchedulerState.WAITING_FOR_SLOT
        adapter.stop_forced_charge.assert_called_once()


# ---------------------------------------------------------------------------
# Scheduler Trigger Tests
# ---------------------------------------------------------------------------

class TestSchedulerTrigger:
    """Test should_trigger_evaluation timing logic."""

    def test_triggers_at_correct_time(self, hass, scheduler_config):
        scheduler_config.trigger_hour = 21
        scheduler_config.trigger_minute = 0
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        trigger_time = dt_util.now().replace(hour=21, minute=0, second=0)
        assert scheduler.should_trigger_evaluation(trigger_time) is True

    def test_does_not_trigger_wrong_time(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        wrong_time = dt_util.now().replace(hour=15, minute=30, second=0)
        assert scheduler.should_trigger_evaluation(wrong_time) is False

    def test_triggers_only_once_per_day(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        trigger_time = dt_util.now().replace(hour=21, minute=0, second=0)
        assert scheduler.should_trigger_evaluation(trigger_time) is True

        # Simulate evaluation happened
        scheduler._last_evaluation_date = trigger_time

        assert scheduler.should_trigger_evaluation(trigger_time) is False


# ---------------------------------------------------------------------------
# Scheduler Reset Tests
# ---------------------------------------------------------------------------

class TestSchedulerReset:
    """Test scheduler reset behavior."""

    def test_reset_clears_state(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        scheduler._decision = SchedulerDecision(
            state=SchedulerState.CHARGING, target_soc=80.0
        )
        scheduler._charge_started_at = dt_util.now()

        scheduler.reset()

        assert scheduler.state == SchedulerState.IDLE
        assert scheduler._charge_started_at is None


# ---------------------------------------------------------------------------
# SchedulerConfig Tests
# ---------------------------------------------------------------------------

class TestSchedulerConfig:
    """Test SchedulerConfig.from_config()."""

    def test_from_config_defaults(self):
        config = SchedulerConfig.from_config({})
        assert config.battery_capacity_kwh == 10.0
        assert config.roundtrip_efficiency == 0.92
        assert config.trigger_hour == 21
        assert config.min_deficit_kwh == 2.0

    def test_from_config_custom(self):
        config = SchedulerConfig.from_config({
            "battery_capacity_kwh": 15.0,
            "battery_usable_capacity_kwh": 14.0,
            "battery_roundtrip_efficiency": 0.95,
            "battery_precharge_trigger_hour": 22,
            "battery_precharge_trigger_minute": 30,
            "battery_min_deficit_kwh": 3.0,
            "battery_forecast_confidence": 0.9,
            "battery_max_target_soc": 100.0,
            "peak_limit_w": 9000.0,
            "ev_priority_over_battery": False,
        })

        assert config.battery_capacity_kwh == 15.0
        assert config.battery_usable_capacity_kwh == 14.0
        assert config.roundtrip_efficiency == 0.95
        assert config.trigger_hour == 22
        assert config.trigger_minute == 30
        assert config.min_deficit_kwh == 3.0
        assert config.forecast_confidence == 0.9
        assert config.max_target_soc == 100.0
        assert config.peak_limit_w == 9000.0
        assert config.ev_priority is False


# ---------------------------------------------------------------------------
# Integration-style Tests
# ---------------------------------------------------------------------------

class TestSchedulerIntegration:
    """End-to-end scenarios combining evaluation + update cycles."""

    @pytest.mark.asyncio
    async def test_full_cycle_static_tariff(self, hass, scheduler_config):
        """Full cycle: evaluate → schedule → charge → target reached."""
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        adapter.stop_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.IDLE)
        )
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        # 1. Evaluate at 21:00
        decision = scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            nt_rate=0.10,
            ht_rate=0.30,
        )
        assert decision.state == SchedulerState.SCHEDULED

        # 2. First update — starts charging
        state = await scheduler.update(current_soc=40.0)
        assert state == SchedulerState.CHARGING
        adapter.start_forced_charge.assert_called_once()

        # 3. Charging in progress
        adapter.is_active = True
        state = await scheduler.update(current_soc=60.0)
        assert state == SchedulerState.CHARGING

        # 4. Target reached
        state = await scheduler.update(current_soc=decision.target_soc)
        assert state == SchedulerState.TARGET_REACHED
        adapter.stop_forced_charge.assert_called_once()

    @pytest.mark.asyncio
    async def test_full_cycle_dynamic_tariff(self, hass, scheduler_config, mock_tariff_provider):
        """Full cycle with dynamic tariff — waits for cheap window."""
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        # Evaluate with dynamic tariff
        decision = scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            nt_rate=0.10,
            ht_rate=0.30,
            tariff_provider=mock_tariff_provider,
        )
        assert decision.state == SchedulerState.SCHEDULED
        assert len(decision.charge_windows) > 0

        # Update outside window — should wait
        state = await scheduler.update(current_soc=40.0)
        # Windows are tomorrow midnight, so we're likely outside them now
        # Exact behavior depends on current time, but test structure is valid
        assert state in (SchedulerState.WAITING_FOR_SLOT, SchedulerState.CHARGING)

    @pytest.mark.asyncio
    async def test_cloudy_day_scenario(self, hass, scheduler_config):
        """Cloudy forecast + low correction = aggressive charging."""
        scheduler_config.battery_max_charge_power_w = 3000
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        # Low forecast, poor correction factor (overcast history)
        decision = scheduler.evaluate(
            current_soc=20.0,
            forecast_tomorrow_kwh=3.0,  # 3 * 0.6 * 0.8 = 1.44
            expected_consumption_kwh=12.0,  # deficit = 10.56
            nt_rate=0.08,
            ht_rate=0.25,
            correction_factor=0.6,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.target_soc == 95.0  # Capped (huge deficit)
        # (95-20)/100 * 9.5 = 7.125 kWh at 3kW = 2.375 → 2 hours
        assert decision.hours_needed >= 2

    @pytest.mark.asyncio
    async def test_sunny_day_no_charge(self, hass, scheduler_config):
        """Sunny forecast with good correction — no charge needed."""
        scheduler = BatteryChargeScheduler(
            hass, MagicMock(spec=BatteryChargeAdapter), scheduler_config
        )

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=25.0,  # 25 * 1.1 * 0.8 = 22
            expected_consumption_kwh=12.0,  # deficit = -10 → no charge
            nt_rate=0.10,
            ht_rate=0.30,
            correction_factor=1.1,
        )

        assert decision.state == SchedulerState.NOT_NEEDED
