"""Tests for battery charge scheduler and adapter.

Covers:
- Huawei/GoodWe/Generic adapter start/stop/status
  (brand *selection* is not tested here — it lives in ``adapter_for``, see
  test_inverter_battery_arch.py; the local factory went in #659)
- Scheduler evaluation logic (deficit, break-even, SOC, thresholds)
- Cheapest-hour selection with dynamic tariff
- Update cycle (charge window, target reached, peak coordination)
- Edge cases (no forecast, already full, tiny deficit, EV peak conflict)
"""
import pytest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.coordinator.battery_adapters.force_charge import (
    BatteryChargeAdapter,
    ChargeCommand,
    ChargeCommandStatus,
    ChargeStatus,
    GenericChargeAdapter,
    GoodWeChargeAdapter,
    HuaweiChargeAdapter,
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
def mock_hass():
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
#
# ``TestAdapterFactory`` (6 tests over ``create_charge_adapter``) was deleted
# in #659 along with the factory it exercised. It was the *second* brand
# selector; the live one is ``battery_adapters.adapter_for``, covered by
# ``test_inverter_battery_arch.py`` (explicit huawei / goodwe / generic + the
# no-brand fallback).
#
# The two auto-detect tests here are worth a note, because they were worse
# than merely redundant: they asserted detection via ``hass.config.components``,
# which is what the DEAD factory read. The live ``_integration_loaded`` never
# looks at ``config.components`` — it checks ``hass.data`` / ``hass.config_entries``
# (covered by test_battery_arbitrage_523.py::test_adapter_for_detects_huawei_via_config_entries).
# So these were green about a detection mechanism production does not use.


# ---------------------------------------------------------------------------
# Huawei Adapter Tests
# ---------------------------------------------------------------------------

class TestHuaweiAdapter:
    """Test HuaweiChargeAdapter."""

    @pytest.mark.asyncio
    async def test_start_forced_charge_success(self, mock_hass, huawei_config):
        adapter = HuaweiChargeAdapter(mock_hass, huawei_config)
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000, duration_minutes=240)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.CHARGING
        assert adapter.is_active
        mock_hass.services.async_call.assert_called_once_with(
            "huawei_solar",
            "forcible_charge_soc",
            {"device_id": "abc123", "target_soc": 80, "power": 3000, "duration": 240},
        )

    @pytest.mark.asyncio
    async def test_start_forced_charge_no_device_id(self, mock_hass):
        adapter = HuaweiChargeAdapter(mock_hass, {"battery_charge_platform": "huawei"})
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.FAILED
        assert "No inverter_device_id" in status.message

    @pytest.mark.asyncio
    async def test_start_forced_charge_service_error(self, mock_hass, huawei_config):
        mock_hass.services.async_call = AsyncMock(side_effect=Exception("Service unavailable"))
        adapter = HuaweiChargeAdapter(mock_hass, huawei_config)
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.FAILED
        assert not adapter.is_active

    @pytest.mark.asyncio
    async def test_stop_forced_charge(self, mock_hass, huawei_config):
        adapter = HuaweiChargeAdapter(mock_hass, huawei_config)
        adapter._active = True

        status = await adapter.stop_forced_charge()

        assert status.status == ChargeCommandStatus.IDLE
        assert not adapter.is_active
        mock_hass.services.async_call.assert_called_once_with(
            "huawei_solar",
            "stop_forcible_charge",
            {"device_id": "abc123"},
        )

    @pytest.mark.asyncio
    async def test_get_status_target_reached(self, mock_hass, huawei_config):
        soc_state = MagicMock()
        soc_state.state = "85"
        mock_hass.states.get = MagicMock(return_value=soc_state)

        adapter = HuaweiChargeAdapter(mock_hass, huawei_config)
        adapter._active = True
        adapter._target_soc = 80.0

        status = await adapter.get_status()

        assert status.status == ChargeCommandStatus.TARGET_REACHED
        assert status.current_soc == 85.0

    @pytest.mark.asyncio
    async def test_get_status_still_charging(self, mock_hass, huawei_config):
        soc_state = MagicMock()
        soc_state.state = "60"
        mock_hass.states.get = MagicMock(return_value=soc_state)

        adapter = HuaweiChargeAdapter(mock_hass, huawei_config)
        adapter._active = True
        adapter._target_soc = 80.0

        status = await adapter.get_status()

        assert status.status == ChargeCommandStatus.CHARGING
        assert status.current_soc == 60.0

    # ``test_should_stop`` / ``test_should_stop_inactive`` went with
    # ``should_stop`` in #659. The live target-reached rule is the
    # scheduler's own SOC comparison, covered by the "already at target"
    # planning tests further down — not by anything on the adapter.


# ---------------------------------------------------------------------------
# GoodWe Adapter Tests
# ---------------------------------------------------------------------------

class TestGoodWeAdapter:
    """Test GoodWeChargeAdapter."""

    @pytest.mark.asyncio
    async def test_start_forced_charge(self, mock_hass, goodwe_config):
        adapter = GoodWeChargeAdapter(mock_hass, goodwe_config)
        cmd = ChargeCommand(target_soc=75.0, max_power_w=4000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.CHARGING
        assert adapter.is_active
        assert mock_hass.services.async_call.call_count == 2  # SOC target + work mode

    @pytest.mark.asyncio
    async def test_stop_restores_normal_mode(self, mock_hass, goodwe_config):
        adapter = GoodWeChargeAdapter(mock_hass, goodwe_config)
        adapter._active = True

        status = await adapter.stop_forced_charge()

        assert status.status == ChargeCommandStatus.IDLE
        mock_hass.services.async_call.assert_called_with(
            "select",
            "select_option",
            {"entity_id": "select.goodwe_work_mode", "option": "General"},
        )

    @pytest.mark.asyncio
    async def test_start_no_work_mode_entity(self, mock_hass):
        adapter = GoodWeChargeAdapter(mock_hass, {"battery_charge_platform": "goodwe"})
        cmd = ChargeCommand(target_soc=80.0, max_power_w=3000)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.FAILED


# ---------------------------------------------------------------------------
# Generic Adapter Tests
# ---------------------------------------------------------------------------

class TestGenericAdapter:
    """Test GenericChargeAdapter."""

    @pytest.mark.asyncio
    async def test_start_forced_charge(self, mock_hass, generic_config):
        adapter = GenericChargeAdapter(mock_hass, generic_config)
        cmd = ChargeCommand(target_soc=90.0, max_power_w=2500)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.CHARGING
        assert adapter.is_active

    @pytest.mark.asyncio
    async def test_start_no_switch_configured(self, mock_hass):
        adapter = GenericChargeAdapter(mock_hass, {})
        cmd = ChargeCommand(target_soc=90.0, max_power_w=2500)

        status = await adapter.start_forced_charge(cmd)

        assert status.status == ChargeCommandStatus.UNSUPPORTED

    @pytest.mark.asyncio
    async def test_stop_disables_switch(self, mock_hass, generic_config):
        adapter = GenericChargeAdapter(mock_hass, generic_config)
        adapter._active = True

        status = await adapter.stop_forced_charge()

        assert status.status == ChargeCommandStatus.IDLE
        mock_hass.services.async_call.assert_called_with(
            "switch",
            "turn_off",
            {"entity_id": "switch.force_charge"},
        )


# ---------------------------------------------------------------------------
# Scheduler Evaluation Tests
# ---------------------------------------------------------------------------

class TestSchedulerEvaluation:
    """Test BatteryChargeScheduler.evaluate() decision logic."""

    def _make_scheduler(self, mock_hass, scheduler_config, adapter=None):
        if adapter is None:
            adapter = MagicMock(spec=BatteryChargeAdapter)
            adapter.is_active = False
        return BatteryChargeScheduler(mock_hass, scheduler_config)

    def test_no_deficit_solar_covers_consumption(self, mock_hass, scheduler_config):
        """Solar forecast exceeds consumption — no charge needed."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_deficit_below_threshold(self, mock_hass, scheduler_config):
        """Small deficit below min_deficit_kwh — not worth charging."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_not_profitable(self, mock_hass, scheduler_config):
        """NT effective cost >= HT rate — charging wastes money."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_already_at_target(self, mock_hass, scheduler_config):
        """SOC already at calculated target — no charge needed."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_scheduled_with_static_tariff(self, mock_hass, scheduler_config):
        """Profitable deficit with no dynamic tariff — schedule charge."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_scheduled_never_asks_the_tariff_for_windows(
            self, mock_hass, scheduler_config, mock_tariff_provider):
        """(#638 one-gate C4b) The scheduler owns WHAT, the plan owns
        WHEN — a SCHEDULED verdict must not consult find_cheapest_hours;
        the provider is only for the replan price fingerprint."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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
        mock_tariff_provider.find_cheapest_hours.assert_not_called()

    def test_forecast_correction_reduces_deficit(self, mock_hass, scheduler_config):
        """Correction factor < 1 reduces effective forecast (increases deficit)."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_high_correction_eliminates_deficit(self, mock_hass, scheduler_config):
        """Good correction factor can eliminate deficit entirely."""
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

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

    def test_target_soc_capped(self, mock_hass, scheduler_config):
        """Target SOC never exceeds max_target_soc."""
        scheduler_config.max_target_soc = 90.0
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=20.0,
            forecast_tomorrow_kwh=0.0,  # No sun
            expected_consumption_kwh=20.0,  # Huge deficit
            off_peak_rate=0.05,
            peak_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.target_soc == 90.0  # Capped

    def test_hours_needed_calculation(self, mock_hass, scheduler_config):
        """Hours needed = charge_kwh / charge_power_kw, rounded up (ceil).

        was round-half-up (2.09 → 2), which booked a duration too
        short to actually reach the target. Ceil guarantees the adapter
        duration covers the full charge.
        """
        scheduler_config.battery_max_charge_power_w = 2500  # 2.5 kW
        scheduler = self._make_scheduler(mock_hass, scheduler_config)

        # deficit = 10 - (2*0.8 blended) = 8.4 kWh
        # target_soc = 40 + (8.4/9.5)*100 = 40 + 88.4 = 95 (capped)
        # actual_charge = (95-40)/100 * 9.5 = 5.225 kWh
        # hours = 5.225 / 2.5 = 2.09 → ceil → 3 hours
        decision = scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=2.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=1.0,
        )

        assert decision.hours_needed == 3


# ---------------------------------------------------------------------------
# Scheduler Trigger Tests
# ---------------------------------------------------------------------------

class TestSchedulerTrigger:
    """Test should_trigger_evaluation timing logic."""

    def test_triggers_at_correct_time(self, mock_hass, scheduler_config):
        scheduler_config.trigger_hour = 21
        scheduler_config.trigger_minute = 0
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        trigger_time = dt_util.now().replace(hour=21, minute=0, second=0)
        assert scheduler.should_trigger_evaluation(trigger_time) is True

    def test_does_not_trigger_wrong_time(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        wrong_time = dt_util.now().replace(hour=15, minute=30, second=0)
        assert scheduler.should_trigger_evaluation(wrong_time) is False

    def test_triggers_only_once_per_day(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_reset_clears_state(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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
            # #693 — the key installs actually carry, in kW. The old
            # ``peak_limit_w`` was written by nothing; feeding it here is how
            # the dead read stayed green. A lingering value must be ignored.
            "target_peak_limit": 9.0,
            "peak_limit_w": 4000.0,
            # #604: retired key — deleted by the v14→v15 migration and no
            # longer read by from_config. A lingering value must be ignored.
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
        # 9.0 kW → 9000 W; the dead ``peak_limit_w: 4000`` above must lose.
        assert config.peak_limit_w == 9000.0
        # #604: the legacy ev_priority_over_battery read is retired — the
        # internal knob keeps its default regardless of the config key.
        assert config.ev_priority is True

    def test_from_config_float_trigger_hour_from_options_flow(self, mock_hass):
        """#493: the options-flow NumberSelector stores floats (21.0).

        ``datetime.replace(hour=21.0)`` raises ``TypeError: 'float'
        object cannot be interpreted as an integer`` — on PROD
        (RienduPre, #487 comment, v1.7.3-beta.9) this killed the
        scheduler evaluation on every coordinator cycle for any user
        who ever saved the battery-scheduler options page. Defaults
        stay int, which is why soaks on untouched configs missed it.

        Exercise the exact crashing path: float-shaped config →
        ``should_trigger_evaluation`` → ``_in_planning_window`` →
        ``_window_start`` → ``now.replace(hour=...)``.
        """
        config = SchedulerConfig.from_config({
            "battery_charge_scheduler_enabled": True,
            "battery_precharge_trigger_hour": 21.0,
            "battery_precharge_trigger_minute": 0.0,
        })
        assert config.trigger_hour == 21
        assert isinstance(config.trigger_hour, int)
        assert isinstance(config.trigger_minute, int)

        # String-shaped storage ("21.0") must coerce too — a bare int()
        # would swap the TypeError for a ValueError (review finding on
        # PR #496).
        config_str = SchedulerConfig.from_config({
            "battery_precharge_trigger_hour": "21.0",
            "battery_precharge_trigger_minute": "30",
        })
        assert config_str.trigger_hour == 21
        assert config_str.trigger_minute == 30

        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, config)
        # Must not raise — and inside the window it must trigger, so
        # the call demonstrably reached the production logic.
        in_window = dt_util.now().replace(hour=21, minute=5, second=0)
        assert scheduler.should_trigger_evaluation(in_window) is True
        outside = dt_util.now().replace(hour=12, minute=0, second=0)
        assert scheduler.should_trigger_evaluation(outside) is False


# ---------------------------------------------------------------------------
# Integration-style Tests
# ---------------------------------------------------------------------------

class TestSchedulerIntegration:
    """End-to-end scenarios combining evaluation + update cycles."""

    @pytest.mark.asyncio
    async def test_cloudy_day_scenario(self, mock_hass, scheduler_config):
        """Cloudy forecast + low correction = aggressive charging."""
        scheduler_config.battery_max_charge_power_w = 3000
        adapter = AsyncMock(spec=BatteryChargeAdapter)
        adapter.is_active = False
        adapter.start_forced_charge = AsyncMock(
            return_value=ChargeStatus(status=ChargeCommandStatus.CHARGING)
        )
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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
    async def test_sunny_day_no_charge(self, mock_hass, scheduler_config):
        """Sunny forecast with good correction — no charge needed."""
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=50.0,
            forecast_tomorrow_kwh=25.0,  # 25 * 1.1 * 0.8 = 22
            expected_consumption_kwh=12.0,  # deficit = -10 → no charge
            off_peak_rate=0.10,
            peak_rate=0.30,
            correction_factor=1.1,
        )

        assert decision.state == SchedulerState.NOT_NEEDED


class TestFeatureToggle:
    """Test enabled/disabled behavior."""

    def test_disabled_evaluate_returns_idle(self, mock_hass, scheduler_config):
        scheduler_config.enabled = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.IDLE
        assert "disabled" in decision.reason

    def test_disabled_trigger_returns_false(self, mock_hass, scheduler_config):
        scheduler_config.enabled = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        trigger_time = dt_util.now().replace(hour=21, minute=0, second=0)
        assert scheduler.should_trigger_evaluation(trigger_time) is False

    def test_enabled_property(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)
        assert scheduler.enabled is True

        scheduler_config.enabled = False
        scheduler2 = BatteryChargeScheduler(mock_hass, scheduler_config)
        assert scheduler2.enabled is False


# ---------------------------------------------------------------------------
# Battery Cycle Cost / Degradation Tests
# ---------------------------------------------------------------------------

class TestCycleCost:
    """Test degradation-aware break-even check."""

    def test_cycle_cost_blocks_unprofitable_charge(self, mock_hass, scheduler_config):
        """High cycle cost makes arbitrage unprofitable."""
        scheduler_config.battery_cycle_cost = 0.10
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.NOT_PROFITABLE
        assert "degradation" in decision.reason

    def test_low_cycle_cost_allows_charge(self, mock_hass, scheduler_config):
        """Low cycle cost still allows profitable charging."""
        scheduler_config.battery_cycle_cost = 0.02
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=15.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert decision.state == SchedulerState.SCHEDULED

    def test_zero_cycle_cost_same_as_before(self, mock_hass, scheduler_config):
        """Zero cycle cost = no degradation check (backward compat)."""
        scheduler_config.battery_cycle_cost = 0.0
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_negative_price_forces_full_charge(self, mock_hass, scheduler_config):
        """Negative price -> charge to max SOC regardless of forecast."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_negative_price_respects_already_full(self, mock_hass, scheduler_config):
        """Already at max SOC -> no charge even with negative price."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        decision = scheduler.evaluate(
            current_soc=96.0,
            forecast_tomorrow_kwh=30.0,
            expected_consumption_kwh=10.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
            current_price=-0.05,
        )

        assert decision.state in (SchedulerState.NOT_NEEDED, SchedulerState.IDLE)

    def test_negative_price_feature_disabled(self, mock_hass, scheduler_config):
        """Feature disabled -> no force charge on negative price."""
        scheduler_config.force_charge_on_negative_price = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_no_forecast_charges_conservatively(self, mock_hass, scheduler_config):
        """No forecast -> deficit = full consumption."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_stale_forecast_increases_pessimism(self, mock_hass, scheduler_config):
        """Stale forecast (>6h) uses doubled pessimism weight."""
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_fresh_forecast_applies_pessimism_blend(self, mock_hass, scheduler_config):
        """More pessimism -> higher deficit."""
        scheduler_config.pessimism_weight = 0.0
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        decision_optimistic = scheduler.evaluate(
            current_soc=30.0,
            forecast_tomorrow_kwh=20.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        scheduler.reset()
        scheduler_config.pessimism_weight = 0.5
        scheduler2 = BatteryChargeScheduler(mock_hass, scheduler_config)

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

    def test_soc_deviation_triggers_replan(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert scheduler.should_replan(current_soc=43.0, ev_connected=False) is False
        assert scheduler.should_replan(current_soc=50.0, ev_connected=False) is True

    def test_ev_connect_triggers_replan(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

        scheduler.evaluate(
            current_soc=40.0,
            forecast_tomorrow_kwh=5.0,
            expected_consumption_kwh=12.0,
            off_peak_rate=0.10,
            peak_rate=0.30,
        )

        assert scheduler.should_replan(current_soc=40.0, ev_connected=False) is False
        assert scheduler.should_replan(current_soc=40.0, ev_connected=True) is True

    def test_no_replan_when_idle(self, mock_hass, scheduler_config):
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)
        assert scheduler.should_replan(current_soc=50.0, ev_connected=True) is False

    def test_ev_replan_disabled(self, mock_hass, scheduler_config):
        scheduler_config.replan_on_ev_change = False
        adapter = MagicMock(spec=BatteryChargeAdapter)
        scheduler = BatteryChargeScheduler(mock_hass, scheduler_config)

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


# ── #624: shells retired — deletion guard + relocated startup restore ──────

class TestShellRetirement624:
    """Guards the #624 cleanup: the old coordinator-level shells stay gone."""

    def test_old_module_paths_gone(self):
        import importlib, pytest as _pytest
        with _pytest.raises(ModuleNotFoundError):
            importlib.import_module(
                "custom_components.solar_energy_management.coordinator.battery_charge_adapter")
        with _pytest.raises(ModuleNotFoundError):
            importlib.import_module(
                "custom_components.solar_energy_management.coordinator.battery_protection")

    def test_scheduler_is_a_pure_planner(self):
        import inspect
        from custom_components.solar_energy_management.coordinator.battery_charge_scheduler import (
            BatteryChargeScheduler)
        params = list(inspect.signature(BatteryChargeScheduler.__init__).parameters)
        assert "adapter" not in params          # no actuation dependency

    def test_force_charge_impl_not_imported_outside_battery_adapters(self):
        """The moved brand impls are internal to battery_adapters/ —
        nothing in coordinator/ outside that package may import them."""
        import pathlib, re
        pkg = pathlib.Path(__file__).resolve().parents[1] / "coordinator"
        offenders = []
        for f in pkg.rglob("*.py"):
            if "battery_adapters" in f.parts:
                continue
            txt = f.read_text(encoding="utf-8")
            if re.search(r"from .*battery_adapters\.force_charge import|force_charge import", txt):
                offenders.append(str(f))
        assert not offenders, f"force_charge imported outside battery_adapters/: {offenders}"


@pytest.mark.asyncio
class TestStartupRestoreRelocated624:
    """The BatteryProtectionMixin's one job, relocated to actuate_battery."""

    async def _run(
        self,
        state_value,
        control_entity="number.limit",
        max_w=5000,
        *,
        attributes=None,
        observer_mode=False,
    ):
        from custom_components.solar_energy_management.coordinator.actuate_battery import (
            restore_discharge_limit_on_startup,
        )
        hass = MagicMock()
        hass.services.async_call = AsyncMock()
        st = MagicMock(); st.state = state_value
        st.attributes = attributes or {}
        hass.states.get = MagicMock(return_value=st if state_value is not None else None)
        cfg = {"battery_discharge_control_entity": control_entity,
               "battery_max_discharge_power": max_w,
               "observer_mode": observer_mode}
        await restore_discharge_limit_on_startup(hass, cfg)
        return hass

    async def test_stale_low_limit_restored_to_max(self):
        hass = await self._run("1200")
        hass.services.async_call.assert_awaited_once()
        args = hass.services.async_call.await_args
        assert args.args[0] == "number" and args.args[1] == "set_value"
        assert args.args[2]["value"] == 5000

    async def test_limit_already_at_max_no_call(self):
        hass = await self._run("5000")
        hass.services.async_call.assert_not_awaited()

    async def test_no_control_entity_noop(self):
        hass = await self._run("1200", control_entity="")
        hass.services.async_call.assert_not_awaited()

    async def test_unreadable_state_noop(self):
        hass = await self._run("unavailable")
        hass.services.async_call.assert_not_awaited()

    async def test_observer_mode_never_writes_stale_limit(self):
        """Observer mode is a hard read-only boundary, including startup."""
        hass = await self._run(
            "1200",
            attributes={"unit_of_measurement": "W", "min": 0, "max": 12000},
            observer_mode=True,
        )
        hass.services.async_call.assert_not_awaited()

    async def test_ampere_entity_rejected_without_write(self):
        """Deye max-discharging-current is A, never a watt setpoint."""
        hass = await self._run(
            "185",
            control_entity="number.inverter_battery_max_discharging_current",
            max_w=12000,
            attributes={"unit_of_measurement": "A", "min": 0, "max": 350},
        )
        hass.services.async_call.assert_not_awaited()

    async def test_kw_entity_scales_watts_and_checks_native_range(self):
        hass = await self._run(
            "1.2",
            max_w=5000,
            attributes={"unit_of_measurement": "kW", "min": 0, "max": 12},
        )
        hass.services.async_call.assert_awaited_once()
        args = hass.services.async_call.await_args
        assert args.args[2]["value"] == 5.0
