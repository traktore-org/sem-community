"""Integration tests for the EV deadline + tariff wiring (#246/#247).

Covers the pieces around the pure planner (tested in test_ev_tariff_planner):
- find_cheapest_hours(prefer_consecutive=...) block-wise selection
- _compute_night_plan gathering inputs from config/tariff/switch state
- the daytime tariff pause in _determine_charging_strategy
- the deadline current-floor applied in _execute_ev_control's night branch
"""
from datetime import timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from homeassistant.util import dt as dt_util

from custom_components.solar_energy_management.consts.states import ChargingState
from custom_components.solar_energy_management.coordinator import SEMCoordinator
from custom_components.solar_energy_management.coordinator.charging_control import (
    ChargingContext,
)
from custom_components.solar_energy_management.coordinator.types import PowerReadings
from custom_components.solar_energy_management.tariff.tariff_provider import (
    DynamicTariffProvider,
    PriceLevel,
    PricePoint,
)


# ---------------------------------------------------------------------------
# find_cheapest_hours — block-wise (#247)
# ---------------------------------------------------------------------------
def _provider_with_prices(price_seq):
    now = dt_util.now().replace(minute=0, second=0, microsecond=0)
    prices = [
        PricePoint(timestamp=now + timedelta(hours=i), price=p, level=PriceLevel.NORMAL)
        for i, p in enumerate(price_seq)
    ]
    prov = DynamicTariffProvider.__new__(DynamicTariffProvider)
    prov._read_prices_list = lambda: prices
    return prov, now


class TestFindCheapestHoursBlockwise:
    def test_consecutive_prefers_contiguous_block(self):
        # Alternating cheap/expensive: scattered would pick the 3 isolated dips,
        # block-wise picks the cheapest contiguous run of 3.
        prov, now = _provider_with_prices([0.3, 0.1, 0.3, 0.1, 0.3, 0.1])
        block = prov.find_cheapest_hours(3, within_hours=12, prefer_consecutive=True)
        starts = [p.timestamp for p in block]
        # contiguous → three consecutive hours
        deltas = [(starts[i + 1] - starts[i]).total_seconds() for i in range(len(starts) - 1)]
        assert all(d == 3600 for d in deltas)
        assert len(block) == 3

    def test_scattered_default_picks_globally_cheapest(self):
        prov, now = _provider_with_prices([0.3, 0.1, 0.3, 0.1, 0.3, 0.1])
        scattered = prov.find_cheapest_hours(3, within_hours=12, prefer_consecutive=False)
        # the three cheapest are the 0.1 dips — not contiguous
        assert len(scattered) == 3
        assert all(abs(p.price - 0.1) < 1e-9 for p in scattered)

    def test_block_returns_lowest_sum_window(self):
        # Cheapest contiguous pair is the last two (0.1, 0.1).
        prov, now = _provider_with_prices([0.5, 0.5, 0.5, 0.5, 0.1, 0.1])
        block = prov.find_cheapest_hours(2, within_hours=12, prefer_consecutive=True)
        assert [round(p.price, 2) for p in block] == [0.1, 0.1]


# ---------------------------------------------------------------------------
# Coordinator harness
# ---------------------------------------------------------------------------
def _make_device(device_id="keba", max_current=32, session_active=False,
                 current_setpoint=0):
    dev = MagicMock()
    dev.device_id = device_id
    dev.max_current = max_current
    dev.min_current = 6
    dev.phases = 3
    dev.voltage = 230
    dev._session_active = session_active
    dev._current_setpoint = current_setpoint
    dev.managed_externally = False
    dev._set_current = AsyncMock()
    dev.start_session = AsyncMock()
    dev.stop_session = AsyncMock()
    return dev


def _build_coordinator(config_overrides=None, tariff_on=False, price_level=PriceLevel.NORMAL):
    with patch.object(SEMCoordinator, "__init__", return_value=None):
        coord = SEMCoordinator.__new__(SEMCoordinator)
    coord.config = {
        "ev_chargers": [{"id": "keba", "ev_min_current": 6,
                         "ev_night_initial_current": 10}],
        "ev_max_current": 32,
        "target_peak_limit": 6.0,
        "ev_ramp_rate_amps": 2,
        "ev_stall_cooldown": 120,
    }
    if config_overrides:
        coord.config.update(config_overrides)

    coord._load_manager = None
    coord.time_manager = MagicMock()
    coord.time_manager.is_night_mode = MagicMock(return_value=True)
    coord.time_manager.get_night_end_time = MagicMock(return_value="07:00")

    # hass.states.is_state for the tariff switch
    coord.hass = MagicMock()
    coord.hass.states.is_state = MagicMock(
        side_effect=lambda eid, state: tariff_on and eid.endswith("_tariff_optimized")
    )

    # tariff provider
    coord._tariff_provider = MagicMock()
    coord._tariff_provider.get_price_level = MagicMock(return_value=price_level)
    coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=[])

    # attrs read by _determine_charging_strategy
    coord._cycle_vehicle_soc = None
    coord._cycle_forecast = MagicMock(available=False)
    coord._forecast_reader = MagicMock()
    coord._forecast_reader.read_forecast = MagicMock(return_value=MagicMock(available=False))
    coord._forecast_tracker = MagicMock(dampening_factor=1.0)
    coord._state_machine = MagicMock()
    coord._state_machine.current_state = ChargingState.SOLAR_IDLE
    coord.config.setdefault("battery_capacity_kwh", 15)

    coord._ev_device = None
    return coord


# ---------------------------------------------------------------------------
# _compute_night_plan (#246/#247)
# ---------------------------------------------------------------------------
class TestComputeNightPlan:
    def test_short_deadline_sets_floor(self):
        coord = _build_coordinator()
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "02:00"}
        with patch.object(dt_util, "now", return_value=dt_util.now().replace(
                hour=22, minute=0, second=0, microsecond=0)):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=20.0)
        assert plan.deadline_active
        assert plan.deadline_amps >= 7

    def test_tariff_wait_when_cheap_window_ahead(self):
        coord = _build_coordinator(tariff_on=True)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        # Two consecutive cheap hours ahead. Peak-managed rate here is
        # (6 kW peak - ~0.75 kW home)/690 ≈ 7 A ≈ 4.8 kW; 2 h * 4.8 ≈ 9.6 kWh,
        # which covers an 8 kWh need at the realistic rate → wait is viable.
        cheap = [
            PricePoint(timestamp=base.replace(hour=1) + timedelta(days=1), price=0.1, level=PriceLevel.CHEAP),
            PricePoint(timestamp=base.replace(hour=2) + timedelta(days=1), price=0.1, level=PriceLevel.CHEAP),
        ]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap)
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00"}
        with patch.object(dt_util, "now", return_value=base):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=8.0)
        assert plan.should_wait_for_cheap

    def test_peak_limited_declines_unfillable_wait(self):
        # C1 regression (#274): one cheap hour cannot deliver 10 kWh at the
        # peak-limited rate (~4.8 kW), so the planner must NOT wait — it charges
        # now (using all hours) to guarantee Min, instead of waiting then missing.
        coord = _build_coordinator(tariff_on=True)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        cheap = [PricePoint(timestamp=base.replace(hour=1) + timedelta(days=1),
                            price=0.1, level=PriceLevel.CHEAP)]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap)
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00"}
        with patch.object(dt_util, "now", return_value=base):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=10.0)
        assert not plan.should_wait_for_cheap

    def test_predictor_pattern_sizes_peak_rate(self):
        # Predictor-based path (#274): a high learned overnight load shrinks the
        # peak headroom, so even a generous cheap window can't fill Min → no wait.
        coord = _build_coordinator(tariff_on=True)
        coord._predictor = MagicMock()
        # 5500 W learned night load → headroom 6000-5500=500 W → clamps to min (6A,
        # ~4.1 kW)... so use a load that drops realistic rate below the need.
        coord._predictor.predict_consumption_24h = MagicMock(return_value=[5500.0] * 24)
        coord.time_manager.get_night_window_hours = MagicMock(return_value=8.0)
        base = dt_util.now().replace(hour=22, minute=0, second=0, microsecond=0)
        cheap = [PricePoint(timestamp=base.replace(hour=h) + timedelta(days=1),
                            price=0.1, level=PriceLevel.CHEAP) for h in (1, 2)]
        coord._tariff_provider.find_cheapest_hours = MagicMock(return_value=cheap)
        cfg = {"id": "keba", "ev_min_current": 6, "ev_target_time": "07:00"}
        with patch.object(dt_util, "now", return_value=base):
            plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=12.0)
        # 2 cheap h at min-clamped ~4.1 kW ≈ 8.3 kWh < 12 → must not wait
        assert not plan.should_wait_for_cheap

    def test_no_tariff_no_wait(self):
        coord = _build_coordinator(tariff_on=False)
        cfg = {"id": "keba", "ev_target_time": "07:00"}
        plan = coord._compute_night_plan(cfg, remaining_to_min_kwh=10.0)
        assert not plan.should_wait_for_cheap


# ---------------------------------------------------------------------------
# Daytime tariff pause in _determine_charging_strategy (#247)
# ---------------------------------------------------------------------------
class TestDaytimeTariffPause:
    def _power(self, battery_soc=50.0, **kw):
        return PowerReadings(solar_power=3000.0, battery_soc=battery_soc,
                             ev_connected=True, **kw)

    def test_minpv_pauses_grid_when_expensive(self):
        coord = _build_coordinator(tariff_on=True, price_level=PriceLevel.EXPENSIVE)
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        cfg = {"id": "keba", "ev_charging_mode": "minpv"}
        strategy, reason = coord._determine_charging_strategy(
            self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg)
        # Min+PV grid guarantee dropped → no longer min_pv (falls to surplus zone)
        assert strategy != "min_pv"

    def test_minpv_kept_when_price_normal(self):
        coord = _build_coordinator(tariff_on=True, price_level=PriceLevel.NORMAL)
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        cfg = {"id": "keba", "ev_charging_mode": "minpv"}
        strategy, reason = coord._determine_charging_strategy(
            self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg)
        assert strategy == "min_pv"

    def test_minpv_kept_when_tariff_off(self):
        coord = _build_coordinator(tariff_on=False, price_level=PriceLevel.EXPENSIVE)
        coord.time_manager.is_night_mode = MagicMock(return_value=False)
        cfg = {"id": "keba", "ev_charging_mode": "minpv"}
        strategy, reason = coord._determine_charging_strategy(
            self._power(battery_soc=50), MagicMock(daily_ev=0.0), cfg)
        assert strategy == "min_pv"


# ---------------------------------------------------------------------------
# Deadline floor in _execute_ev_control night branch (#246)
# ---------------------------------------------------------------------------
class TestDeadlineFloorApplied:
    @pytest.mark.asyncio
    async def test_fresh_start_uses_deadline_floor(self):
        coord = _build_coordinator(config_overrides={"target_peak_limit": 50.0})
        dev = _make_device(session_active=False)
        coord._ev_device = dev
        coord._night_target_per_charger = None
        ctx = ChargingContext(night_target_kwh=20.0, night_deadline_amps=20,
                              night_deadline_active=True)
        power = PowerReadings(home_consumption_power=500.0, ev_power=0.0,
                              ev_connected=True)
        await coord._execute_ev_control(
            ChargingState.NIGHT_CHARGING_ACTIVE, power, MagicMock(), ctx)
        # initial would be min(10, peak~32)=10; deadline floor 20 overrides it.
        dev._set_current.assert_awaited_with(20)

    @pytest.mark.asyncio
    async def test_dynamic_deadline_overrides_gentle_ramp(self):
        coord = _build_coordinator(config_overrides={"target_peak_limit": 50.0})
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        coord._night_target_per_charger = None
        coord._ev_last_change_time = None
        ctx = ChargingContext(night_target_kwh=20.0, night_deadline_amps=20,
                              night_deadline_active=True)
        power = PowerReadings(home_consumption_power=500.0, ev_power=6900.0,
                              ev_connected=True)
        await coord._execute_ev_control(
            ChargingState.NIGHT_CHARGING_ACTIVE, power, MagicMock(), ctx)
        # gentle ramp would cap at 12 (10+2); deadline floor 20 overrides.
        dev._set_current.assert_awaited_with(20)

    @pytest.mark.asyncio
    async def test_tariff_wait_state_stops_session(self):
        coord = _build_coordinator()
        dev = _make_device(session_active=True, current_setpoint=10)
        coord._ev_device = dev
        ctx = ChargingContext(night_target_kwh=10.0)
        power = PowerReadings(ev_connected=True)
        await coord._execute_ev_control(
            ChargingState.TARIFF_WAITING_FOR_CHEAP, power, MagicMock(), ctx)
        dev.stop_session.assert_awaited()
