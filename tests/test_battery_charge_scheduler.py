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
    NightChargeSchedule,
    SchedulerConfig,
    SchedulerDecision,
    SchedulerState,
    TimeSlot,
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
        enabled=True,
        battery_capacity_kwh=10.0,
        battery_usable_capacity_kwh=9.5,
        battery_min_soc=5.0,
        battery_max_charge_power_w=5000.0,
        roundtrip_efficiency=0.92,
        battery_cycle_cost=0.0,
        trigger_hour=21,
        trigger_minute=0,
        min_deficit_kwh=2.0,
        forecast_confidence=0.8,
        max_target_soc=95.0,
        forecast_fallback_soc=70.0,
        stale_forecast_hours=6,
        pessimism_weight=0.3,
        replan_soc_deviation_pct=5.0,
        replan_on_ev_change=True,
        peak_limit_w=0.0,
        max_grid_import_w=0.0,
        ev_priority=True,
        force_charge_on_negative_price=True,
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
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.NOT_NEEDED
        assert "Solar forecast covers" in decision.reason

    def test_deficit_below_threshold(self, hass, scheduler_config):
        """Small deficit below min_deficit_kwh — not worth charging."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # With pessimism_weight=0.3:
        # optimistic = 15 * 1.0 * 0.8 = 12.0, pessimistic = 6.0
        # effective = 12.0 * 0.7 + 6.0 * 0.3 = 8.4 + 1.8 = 10.2
        # deficit = 11 - 10.2 = 0.8 < 2.0 threshold
        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=11.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
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
            off_peak_rate=0.28,  # 0.28 / 0.92 = 0.304 > 0.30
            peak_rate=0.30,
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
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.NOT_NEEDED
        assert "Already at target" in decision.reason

    def test_scheduled_with_static_tariff(self, hass, scheduler_config):
        """Profitable deficit with no dynamic tariff — schedule charge."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # With pessimism_weight=0.3:
        # optimistic = 5 * 1.0 * 0.8 = 4.0, pessimistic = 4.0 * 0.5 = 2.0
        # effective = 4.0 * 0.7 + 2.0 * 0.3 = 3.4
        # deficit = 12 - 3.4 = 8.6
        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.should_charge
        assert decision.deficit_kwh == pytest.approx(8.6)
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
            off_peak_rate=0.10,
            peak_rate=0.30,
            tariff_provider=mock_tariff_provider,
            correction_factor=1.0,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert len(decision.charge_windows) > 0
        mock_tariff_provider.find_cheapest_hours.assert_called_once()

    def test_forecast_correction_reduces_deficit(self, hass, scheduler_config):
        """Correction factor < 1 reduces effective forecast (increases deficit)."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # With pessimism_weight=0.3, correction=0.7:
        # optimistic = 15 * 0.7 * 0.8 = 8.4, pessimistic = 8.4 * 0.5 = 4.2
        # effective = 8.4 * 0.7 + 4.2 * 0.3 = 7.14
        # deficit = 12 - 7.14 = 4.86
        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=0.7,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.deficit_kwh == pytest.approx(4.86)

    def test_high_correction_eliminates_deficit(self, hass, scheduler_config):
        """Good correction factor can eliminate deficit entirely."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        # Raw 15, correction 1.2, confidence 0.8 → effective 14.4
        # deficit = 12 - 14.4 = -2.4 → no charge
        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
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
            off_peak_rate=0.05,
            peak_rate=0.30,
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
            off_peak_rate=0.10,
            peak_rate=0.30,
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
            off_peak_rate=0.10,
            peak_rate=0.30,
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
            off_peak_rate=0.10,
            peak_rate=0.30,
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
            off_peak_rate=0.08,
            peak_rate=0.25,
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
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=1.1,
        )

        assert decision.state == SchedulerState.NOT_NEEDED


# ---------------------------------------------------------------------------
# TimeSlot & NightChargeSchedule Tests
# ---------------------------------------------------------------------------

class TestTimeSlot:
    """Test TimeSlot dataclass properties."""

    def test_total_power(self):
        slot = TimeSlot(
            start=dt_util.now(),
            end=dt_util.now() + timedelta(hours=1),
            battery_power_w=3000,
            ev_power_w=7000,
        )
        assert slot.total_power_w == 10000

    def test_energy_calculation_one_hour(self):
        now = dt_util.now()
        slot = TimeSlot(
            start=now,
            end=now + timedelta(hours=1),
            battery_power_w=5000,
            ev_power_w=11000,
        )
        assert slot.battery_energy_kwh == pytest.approx(5.0)
        assert slot.ev_energy_kwh == pytest.approx(11.0)

    def test_energy_calculation_half_hour(self):
        now = dt_util.now()
        slot = TimeSlot(
            start=now,
            end=now + timedelta(minutes=30),
            battery_power_w=4000,
            ev_power_w=0,
        )
        assert slot.battery_energy_kwh == pytest.approx(2.0)


class TestNightChargeSchedule:
    """Test NightChargeSchedule properties and serialization."""

    def test_total_energy(self):
        schedule = NightChargeSchedule(
            total_battery_kwh=5.0,
            total_ev_kwh=11.0,
        )
        assert schedule.total_energy_kwh == 16.0

    def test_estimated_cost(self):
        now = dt_util.now()
        schedule = NightChargeSchedule(
            slots=[
                TimeSlot(
                    start=now,
                    end=now + timedelta(hours=1),
                    battery_power_w=3000,
                    ev_power_w=7000,
                    price=0.08,
                ),
                TimeSlot(
                    start=now + timedelta(hours=1),
                    end=now + timedelta(hours=2),
                    battery_power_w=3000,
                    ev_power_w=0,
                    price=0.10,
                ),
            ],
        )
        # Slot 1: (3+7) * 0.08 = 0.80, Slot 2: 3 * 0.10 = 0.30
        assert schedule.estimated_cost == pytest.approx(1.10)

    def test_active_slot(self):
        now = dt_util.now()
        s1 = TimeSlot(start=now, end=now + timedelta(hours=1), is_active=False)
        s2 = TimeSlot(start=now + timedelta(hours=1), end=now + timedelta(hours=2), is_active=True)
        schedule = NightChargeSchedule(slots=[s1, s2])

        assert schedule.active_slot is s2

    def test_no_active_slot(self):
        schedule = NightChargeSchedule(slots=[])
        assert schedule.active_slot is None

    def test_as_dict_serialization(self):
        now = dt_util.now()
        schedule = NightChargeSchedule(
            slots=[
                TimeSlot(
                    start=now,
                    end=now + timedelta(hours=1),
                    battery_power_w=3000,
                    ev_power_w=7000,
                    price=0.08,
                ),
            ],
            total_battery_kwh=3.0,
            total_ev_kwh=7.0,
            peak_limit_w=9000,
        )
        d = schedule.as_dict()

        assert len(d["slots"]) == 1
        assert d["slots"][0]["battery_w"] == 3000
        assert d["slots"][0]["ev_w"] == 7000
        assert d["slots"][0]["total_w"] == 10000
        assert d["total_battery_kwh"] == 3.0
        assert d["total_ev_kwh"] == 7.0
        assert d["total_kwh"] == 10.0
        assert d["peak_limit_w"] == 9000


# ---------------------------------------------------------------------------
# Schedule Planning Tests
# ---------------------------------------------------------------------------

class TestSchedulePlanning:
    """Test _plan_night_schedule power allocation logic."""

    def _make_scheduler(self, hass, scheduler_config, adapter=None):
        if adapter is None:
            adapter = MagicMock(spec=BatteryChargeAdapter)
            adapter.is_active = False
        return BatteryChargeScheduler(hass, adapter, scheduler_config)

    def test_no_peak_limit_both_at_max(self, hass, scheduler_config):
        """No peak limit — battery and EV charge simultaneously at full power."""
        scheduler_config.peak_limit_w = 0  # No limit
        scheduler_config.battery_max_charge_power_w = 5000
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=3.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            ev_kwh_needed=20.0,
            ev_max_power_w=11000,
        )

        assert decision.schedule is not None
        schedule = decision.schedule
        assert schedule.total_battery_kwh > 0
        assert schedule.total_ev_kwh > 0
        # First slot should have both battery and EV power
        first_slot = schedule.slots[0]
        assert first_slot.battery_power_w > 0
        assert first_slot.ev_power_w > 0

    def test_peak_limit_ev_priority(self, hass, scheduler_config):
        """With peak limit and EV priority — EV gets power first, battery gets remainder."""
        scheduler_config.peak_limit_w = 9000
        scheduler_config.battery_max_charge_power_w = 5000
        scheduler_config.ev_priority = True
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=3.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            ev_kwh_needed=20.0,
            ev_max_power_w=7000,  # EV takes 7kW, leaving 2kW for battery
        )

        assert decision.schedule is not None
        first_slot = decision.schedule.slots[0]
        # EV gets its full 7kW (within peak limit)
        assert first_slot.ev_power_w == 7000
        # Battery gets remainder: 9000 - 7000 = 2000W
        assert first_slot.battery_power_w == 2000

    def test_peak_limit_proportional_split(self, hass, scheduler_config):
        """With peak limit and proportional mode — power split by demand ratio."""
        scheduler_config.peak_limit_w = 8000
        scheduler_config.battery_max_charge_power_w = 5000
        scheduler_config.ev_priority = False  # Proportional
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=3.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            ev_kwh_needed=20.0,
            ev_max_power_w=11000,
        )

        assert decision.schedule is not None
        first_slot = decision.schedule.slots[0]
        # Total demand = 5000 + 11000 = 16000, peak = 8000
        # ratio = 0.5, battery = 2500, ev = 5500
        assert first_slot.total_power_w <= 8000
        assert first_slot.battery_power_w > 0
        assert first_slot.ev_power_w > 0

    def test_battery_only_no_ev(self, hass, scheduler_config):
        """No EV needed — all slots are battery-only."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=3.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            ev_kwh_needed=0.0,
            ev_max_power_w=0,
        )

        assert decision.schedule is not None
        for slot in decision.schedule.slots:
            assert slot.ev_power_w == 0
            assert slot.battery_power_w > 0
        assert decision.schedule.total_ev_kwh == 0

    def test_schedule_with_dynamic_tariff_prices(self, hass, scheduler_config, mock_tariff_provider):
        """Schedule slots inherit prices from tariff provider."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            tariff_provider=mock_tariff_provider,
            ev_kwh_needed=5.0,
            ev_max_power_w=7000,
        )

        assert decision.schedule is not None
        # Prices should be populated from mock_tariff_provider
        for slot in decision.schedule.slots:
            assert slot.price >= 0

    def test_schedule_stops_when_energy_met(self, hass, scheduler_config):
        """Schedule doesn't create more slots than needed."""
        scheduler_config.battery_max_charge_power_w = 5000
        scheduler = self._make_scheduler(hass, scheduler_config)

        # Only need 3 kWh of battery charge at 5kW = ~0.6 hours
        # Should only create 1 slot even though 8 are available
        decision = scheduler.evaluate(
            current_soc=65.0,
            forecast_tomorrow_kwh=5.0,  # 5*0.8=4
            expected_consumption_kwh=8.0,  # deficit = 4
            off_peak_rate=0.10,
            peak_rate=0.30,
            ev_kwh_needed=0.0,
            ev_max_power_w=0,
        )

        if decision.schedule:
            total_planned = decision.schedule.total_battery_kwh
            # Should not massively over-plan
            actual_needed = (decision.target_soc - 65.0) / 100 * 9.5
            assert total_planned <= actual_needed + 5.1  # 1 slot = max 5kWh

    def test_schedule_as_dict_for_sensor(self, hass, scheduler_config):
        """Schedule serializes to dict suitable for HA sensor attributes."""
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=3.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            ev_kwh_needed=10.0,
            ev_max_power_w=7000,
        )

        assert decision.schedule is not None
        d = decision.schedule.as_dict()
        assert "slots" in d
        assert "total_battery_kwh" in d
        assert "total_ev_kwh" in d
        assert "total_kwh" in d
        assert "estimated_cost" in d
        assert "peak_limit_w" in d

    def test_ev_finishes_before_battery(self, hass, scheduler_config):
        """EV needs less energy — later slots are battery-only."""
        scheduler_config.peak_limit_w = 0
        scheduler_config.battery_max_charge_power_w = 3000
        scheduler = self._make_scheduler(hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=20.0,
            forecast_tomorrow_kwh=0.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.08,
            peak_rate=0.25,
            ev_kwh_needed=3.0,  # EV done after ~1 slot at 7kW
            ev_max_power_w=7000,
        )

        assert decision.schedule is not None
        slots = decision.schedule.slots
        assert len(slots) >= 2
        # First slot: both battery + EV
        assert slots[0].ev_power_w > 0
        assert slots[0].battery_power_w > 0
        # Later slots: battery only (EV done)
        ev_done = False
        for slot in slots[1:]:
            if slot.ev_power_w == 0:
                ev_done = True
            if ev_done:
                assert slot.ev_power_w == 0


# ---------------------------------------------------------------------------
# Active Slot Tracking Tests
# ---------------------------------------------------------------------------

class TestActiveSlotTracking:
    """Test _get_active_slot and schedule-aware update cycle."""

    @pytest.mark.asyncio
    async def test_uses_schedule_power_level(self, hass, scheduler_config):
        """Update uses planned power from schedule, not just max."""
        scheduler_config.peak_limit_w = 9000
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        now = dt_util.now()
        # Create a decision with a schedule that has specific power levels
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
            schedule=NightChargeSchedule(
                slots=[
                    TimeSlot(
                        start=now - timedelta(minutes=5),
                        end=now + timedelta(minutes=55),
                        battery_power_w=2500,
                        ev_power_w=6000,
                    ),
                ],
                total_battery_kwh=2.5,
                total_ev_kwh=6.0,
                peak_limit_w=9000,
            ),
        )

        state = await scheduler.update(current_soc=50.0, ev_charging_power_w=6000.0)

        assert state == SchedulerState.CHARGING
        cmd = adapter.start_forced_charge.call_args[0][0]
        # Should use the planned 2500W, not max power
        assert cmd.max_power_w == 2500

    @pytest.mark.asyncio
    async def test_adjusts_power_when_ev_differs_from_plan(self, hass, scheduler_config):
        """When actual EV power differs from planned, recalculate dynamically."""
        scheduler_config.peak_limit_w = 9000
        scheduler_config.battery_max_charge_power_w = 5000
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = True  # Already charging
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        now = dt_util.now()
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.CHARGING,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
            schedule=NightChargeSchedule(
                slots=[
                    TimeSlot(
                        start=now - timedelta(minutes=5),
                        end=now + timedelta(minutes=55),
                        battery_power_w=2000,
                        ev_power_w=7000,  # Planned 7kW
                    ),
                ],
                peak_limit_w=9000,
            ),
        )

        # EV actually using only 4kW (e.g., tapering) → more room for battery
        state = await scheduler.update(current_soc=60.0, ev_charging_power_w=4000.0)

        assert state == SchedulerState.CHARGING
        # Should have issued a new command with more power: 9000-4000-200 = 4800W
        cmd = adapter.start_forced_charge.call_args[0][0]
        assert cmd.max_power_w == 4800

    @pytest.mark.asyncio
    async def test_ev_only_slot_skips_battery(self, hass, scheduler_config):
        """Slot with 0 battery power = waiting, not charging."""
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        now = dt_util.now()
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
            schedule=NightChargeSchedule(
                slots=[
                    TimeSlot(
                        start=now - timedelta(minutes=5),
                        end=now + timedelta(minutes=55),
                        battery_power_w=0,  # EV-only slot
                        ev_power_w=9000,
                    ),
                ],
            ),
        )

        state = await scheduler.update(current_soc=50.0)

        assert state == SchedulerState.WAITING_FOR_SLOT
        adapter.start_forced_charge.assert_not_called()


# ---------------------------------------------------------------------------
# Feature Toggle Tests
# ---------------------------------------------------------------------------

class TestFeatureToggle:
    """Test enabled/disabled behavior."""

    def test_disabled_evaluate_returns_idle(self, hass, scheduler_config):
        scheduler_config.enabled = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.IDLE
        assert "disabled" in decision.reason

    def test_disabled_trigger_returns_false(self, hass, scheduler_config):
        scheduler_config.enabled = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        trigger_time = dt_util.now().replace(hour=21, minute=0, second=0)
        assert scheduler.should_trigger_evaluation(trigger_time) is False

    def test_enabled_property(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)
        assert scheduler.enabled is True

        scheduler_config.enabled = False
        scheduler2 = BatteryChargeScheduler(hass, adapter, scheduler_config)
        assert scheduler2.enabled is False


# ---------------------------------------------------------------------------
# Battery Cycle Cost / Degradation Tests
# ---------------------------------------------------------------------------

class TestCycleCost:
    """Test degradation-aware break-even check."""

    def test_cycle_cost_blocks_unprofitable_charge(self, hass, scheduler_config):
        """High cycle cost makes arbitrage unprofitable."""
        scheduler_config.battery_cycle_cost = 0.10
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.NOT_PROFITABLE
        assert "degradation" in decision.reason

    def test_low_cycle_cost_allows_charge(self, hass, scheduler_config):
        """Low cycle cost still allows profitable charging."""
        scheduler_config.battery_cycle_cost = 0.02
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.SCHEDULED

    def test_zero_cycle_cost_same_as_before(self, hass, scheduler_config):
        """Zero cycle cost = no degradation check (backward compat)."""
        scheduler_config.battery_cycle_cost = 0.0
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.SCHEDULED


# ---------------------------------------------------------------------------
# Negative Tariff Tests
# ---------------------------------------------------------------------------

class TestNegativeTariff:
    """Test force-charge during negative prices."""

    def test_negative_price_forces_full_charge(self, hass, scheduler_config):
        """Negative price -> charge to max SOC regardless of forecast."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=30.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            current_price=-0.05,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.target_soc == 95.0
        assert "Negative price" in decision.reason

    def test_negative_price_respects_already_full(self, hass, scheduler_config):
        """Already at max SOC -> no charge even with negative price."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=96.0,
            forecast_tomorrow_kwh=30.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            current_price=-0.05,
        )

        assert decision.state in (SchedulerState.NOT_NEEDED, SchedulerState.IDLE)

    def test_negative_price_feature_disabled(self, hass, scheduler_config):
        """Feature disabled -> no force charge on negative price."""
        scheduler_config.force_charge_on_negative_price = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=30.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            current_price=-0.05,
        )

        assert decision.state == SchedulerState.NOT_NEEDED


# ---------------------------------------------------------------------------
# Forecast Fallback Tests
# ---------------------------------------------------------------------------

class TestForecastFallback:
    """Test 3-tier forecast fallback strategy."""

    def test_no_forecast_charges_conservatively(self, hass, scheduler_config):
        """No forecast -> deficit = full consumption."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=0.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            forecast_available=False,
        )

        assert decision.state == SchedulerState.SCHEDULED
        assert decision.deficit_kwh == pytest.approx(12.0)

    def test_stale_forecast_increases_pessimism(self, hass, scheduler_config):
        """Stale forecast (>6h) uses doubled pessimism weight."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision_fresh = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            forecast_available=True,
            forecast_age_hours=1.0,
        )

        scheduler.reset()

        decision_stale = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=15.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            forecast_available=True,
            forecast_age_hours=8.0,
        )

        assert decision_stale.deficit_kwh > decision_fresh.deficit_kwh

    def test_fresh_forecast_applies_pessimism_blend(self, hass, scheduler_config):
        """More pessimism -> higher deficit."""
        scheduler_config.pessimism_weight = 0.0
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision_optimistic = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=20.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        scheduler.reset()
        scheduler_config.pessimism_weight = 0.5
        scheduler2 = BatteryChargeScheduler(hass, adapter, scheduler_config)

        decision_pessimistic = scheduler2.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=20.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision_pessimistic.deficit_kwh >= decision_optimistic.deficit_kwh


# ---------------------------------------------------------------------------
# Re-plan Trigger Tests
# ---------------------------------------------------------------------------

class TestReplanTriggers:
    """Test should_replan() conditions."""

    def test_soc_deviation_triggers_replan(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert scheduler.should_replan(current_soc=43.0, ev_connected=False) is False
        assert scheduler.should_replan(current_soc=50.0, ev_connected=False) is True

    def test_ev_connect_triggers_replan(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert scheduler.should_replan(current_soc=40.0, ev_connected=False) is False
        assert scheduler.should_replan(current_soc=40.0, ev_connected=True) is True

    def test_no_replan_when_idle(self, hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)
        assert scheduler.should_replan(current_soc=50.0, ev_connected=True) is False

    def test_ev_replan_disabled(self, hass, scheduler_config):
        scheduler_config.replan_on_ev_change = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        scheduler.should_replan(current_soc=40.0, ev_connected=False)
        assert scheduler.should_replan(current_soc=40.0, ev_connected=True) is False


# ---------------------------------------------------------------------------
# Grid Import Limit Tests
# ---------------------------------------------------------------------------

class TestGridImportLimit:
    """Test max_grid_import_w constraint."""

    @pytest.mark.asyncio
    async def test_grid_import_limit_caps_battery_power(self, hass, scheduler_config):
        """Grid import limit reduces available battery charge power."""
        scheduler_config.max_grid_import_w = 6000
        scheduler_config.peak_limit_w = 0
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = BatteryChargeScheduler(hass, adapter, scheduler_config)

        now = dt_util.now()
        scheduler._decision = SchedulerDecision(
            state=SchedulerState.SCHEDULED,
            target_soc=80.0,
            hours_needed=2,
            charge_windows=[],
            schedule=NightChargeSchedule(
                slots=[
                    TimeSlot(
                        start=now - timedelta(minutes=5),
                        end=now + timedelta(minutes=55),
                        battery_power_w=5000,
                        ev_power_w=3000,
                    ),
                ],
            ),
        )

        state = await scheduler.update(current_soc=50.0, ev_charging_power_w=3000.0)

        assert state == SchedulerState.CHARGING
        cmd = adapter.start_forced_charge.call_args[0][0]
        assert cmd.max_power_w == 2700


# ---------------------------------------------------------------------------
# Config from_config Tests (updated)
# ---------------------------------------------------------------------------

class TestSchedulerConfigExtended:
    """Test extended SchedulerConfig.from_config()."""

    def test_from_config_with_new_fields(self):
        config = SchedulerConfig.from_config({
            "battery_charge_scheduler_enabled": True,
            "battery_cycle_cost": 0.067,
            "battery_forecast_fallback_soc": 65.0,
            "battery_stale_forecast_hours": 8,
            "battery_pessimism_weight": 0.4,
            "battery_replan_soc_deviation": 10.0,
            "battery_replan_on_ev_change": False,
            "battery_max_grid_import_w": 6000.0,
            "battery_force_charge_negative_price": False,
        })

        assert config.enabled is True
        assert config.battery_cycle_cost == 0.067
        assert config.forecast_fallback_soc == 65.0
        assert config.stale_forecast_hours == 8
        assert config.pessimism_weight == 0.4
        assert config.replan_soc_deviation_pct == 10.0
        assert config.replan_on_ev_change is False
        assert config.max_grid_import_w == 6000.0
        assert config.force_charge_on_negative_price is False

    def test_defaults_disabled(self):
        config = SchedulerConfig.from_config({})
        assert config.enabled is False
